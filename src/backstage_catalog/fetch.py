import asyncio
import re
from typing import Any

from rich.console import Console
from rich.progress import Progress

from backstage_catalog.npm import NpmClient, SearchHit
from backstage_catalog.store import Package, Store, Version

# Broad text search catches official plugins that lack the `backstage` keyword.
SEARCH_QUERIES = ["keywords:backstage", "keywords:backstage-plugin", "backstage"]
MAX_VERSIONS = 15
MAX_README = 100_000
# Libraries and the CLI also declare a role; only these count as plugins.
PLUGIN_ROLES = {"frontend-plugin", "frontend-plugin-module", "backend-plugin", "backend-plugin-module"}


def is_plugin(keywords: list[str], role: str) -> bool:
    return role in PLUGIN_ROLES or {"backstage", "plugin"} <= set(keywords)


def normalize_repo(repo: Any) -> str:
    if isinstance(repo, dict):
        url, directory = str(repo.get("url") or ""), str(repo.get("directory") or "")
    else:
        url, directory = str(repo or ""), ""
    url = re.sub(r"^git\+", "", url)
    url = re.sub(r"^git@github\.com:", "https://github.com/", url)
    url = re.sub(r"^(git|ssh)://(git@)?", "https://", url)
    url = re.sub(r"^github:", "https://github.com/", url)
    if re.fullmatch(r"[\w.-]+/[\w.-]+", url):
        url = f"https://github.com/{url}"
    url = re.sub(r"\.git$", "", url).rstrip("/")
    if directory and url.startswith("https://github.com/"):
        url = f"{url}/tree/HEAD/{directory.strip('/')}"
    return url


def person(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("name") or "")
    return re.sub(r"\s*[<(].*$", "", str(value or ""))


def to_package(doc: dict[str, Any]) -> Package | None:
    latest_tag = doc.get("dist-tags", {}).get("latest")
    latest = doc.get("versions", {}).get(latest_tag)
    if not latest:
        return None
    keywords = sorted({str(k).lower().strip() for k in latest.get("keywords") or [] if k})
    backstage = latest.get("backstage") if isinstance(latest.get("backstage"), dict) else {}
    role = str(backstage.get("role") or "")
    if not is_plugin(keywords, role):
        return None
    times: dict[str, str] = doc.get("time", {})
    released = sorted(
        (Version(version=v, date=times[v]) for v in doc["versions"] if v in times),
        key=lambda v: v["date"],
        reverse=True,
    )
    name: str = doc["name"]
    readme = str(doc.get("readme") or latest.get("readme") or "")
    return Package(
        name=name,
        scope=name.split("/")[0] if name.startswith("@") else "",
        description=str(latest.get("description") or ""),
        version=latest_tag,
        license=str(latest.get("license") or ""),
        keywords=keywords,
        role=role,
        plugin_id=str(backstage.get("pluginId") or ""),
        homepage=str(latest.get("homepage") or ""),
        repository=normalize_repo(latest.get("repository")),
        author=person(latest.get("author")),
        maintainers=sorted({person(m) for m in doc.get("maintainers") or []} - {""}),
        created=times.get("created", ""),
        updated=times.get(latest_tag, ""),
        deprecated=deprecation(latest),
        versions=released[:MAX_VERSIONS],
        version_count=len(doc["versions"]),
        readme=readme[:MAX_README],
    )


def deprecation(manifest: dict[str, Any]) -> str:
    value = manifest.get("deprecated")
    return value if isinstance(value, str) else ("deprecated" if value else "")


async def fetch(store: Store, console: Console, full: bool = False) -> None:
    async with NpmClient() as npm:
        found: dict[str, SearchHit] = {}
        for query in SEARCH_QUERIES:
            hits = await npm.search(query)
            console.log(f"search [cyan]{query}[/]: {len(hits)} hits")
            found |= hits

        ignored = store.load_ignored()
        for name in store.names():
            pkg = store.load(name)
            if not is_plugin(pkg["keywords"], pkg["role"]):
                store.delete(name)
                ignored[name] = pkg["version"]

        stored = set(store.names())
        todo = {
            name
            for name, hit in found.items()
            if store.stored_version(name) != hit.version and ignored.get(name) != hit.version
        }
        if full:
            todo |= stored
        # Deprecation doesn't publish a new version, so check the small /latest manifest.
        to_check = sorted(stored - todo)
        console.log(f"{len(found)} candidates, {len(todo)} to fetch, {len(to_check)} to check")

        with Progress(console=console, transient=True) as progress:
            checking = progress.add_task("latest manifests", total=len(to_check))

            async def check(name: str) -> None:
                manifest = await npm.latest(name)
                progress.advance(checking)
                pkg = store.load(name)
                if manifest is None or manifest.get("version") != pkg["version"]:
                    todo.add(name)
                elif deprecation(manifest) != pkg["deprecated"]:
                    pkg["deprecated"] = deprecation(manifest)
                    store.save(pkg)
                    console.log(f"deprecation changed: {name}")

            await asyncio.gather(*(check(n) for n in to_check))

            added = dropped = 0
            fetching = progress.add_task("packuments", total=len(todo))

            async def process(name: str) -> None:
                nonlocal added, dropped
                doc = await npm.packument(name)
                pkg = to_package(doc) if doc else None
                if pkg:
                    store.save(pkg)
                    ignored.pop(name, None)
                    added += 1
                else:
                    if store.stored_version(name):
                        dropped += 1
                    store.delete(name)
                    if name in found:
                        ignored[name] = found[name].version
                progress.advance(fetching)

            await asyncio.gather(*(process(n) for n in sorted(todo)))

        store.save_ignored(dict(sorted(ignored.items())))
        console.log(f"saved {added}, dropped {dropped}, total {len(store.names())}")

        # Search results carry weekly downloads; keep the last value for packages search missed.
        previous = store.load_downloads()
        store.save_downloads(
            {n: found[n].weekly_downloads if n in found else previous.get(n, 0) for n in store.names()}
        )
