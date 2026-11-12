import html
import io
import json
import posixpath
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import markdown
import nh3
from rich.console import Console
from ruamel.yaml import YAML

from backstage_catalog.store import Package, Store

GENERATED_DIRS = ("plugins", "roles", "scopes")
STALE_AFTER = timedelta(days=730)
GENERIC_KEYWORDS = {"backstage", "plugin", "backstage-plugin", "spotify", "frontend", "backend"}
MAX_TAGS = 10
ROLE_LABELS = {
    "frontend-plugin": "Frontend plugin",
    "frontend-plugin-module": "Frontend plugin module",
    "backend-plugin": "Backend plugin",
    "backend-plugin-module": "Backend plugin module",
    "common-library": "Common library",
    "web-library": "Web library",
    "node-library": "Node library",
    "cli": "CLI",
    "": "Unspecified",
}
UNSCOPED = "unscoped"
# Filled by hooks.py after Markdown. <section>, not <div>: Material's search parser matches
# excluded elements by tag name, and nh3 strips <section> from READMEs.
README_PLACEHOLDER = '<section class="catalog-readme" data-search-exclude></section>'
# nh3 drops disallowed tags but keeps their text, so links become plain text; <img> has none.
CARD_TAGS = {"strong", "em", "b", "i", "code", "del", "s", "br"}
README_EXTENSIONS = ["tables", "sane_lists", "pymdownx.superfences", "pymdownx.tasklist", "pymdownx.tilde"]
README_ATTRIBUTES = {
    **{tag: set(attrs) for tag, attrs in nh3.ALLOWED_ATTRIBUTES.items()},
    "*": {"class", "align"},
    "img": {"src", "alt", "title", "width", "height", "align"},
    "input": {"type", "checked", "disabled"},
}


def role_slug(role: str) -> str:
    return role or "unspecified"


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role.replace("-", " ").capitalize())


def scope_slug(scope: str) -> str:
    return scope.lstrip("@") or UNSCOPED


def page_path(name: str) -> str:
    return f"plugins/{name}.md"


def link(src: str, dest: str) -> str:
    return posixpath.relpath(dest, posixpath.dirname(src))


def cell(text: str) -> str:
    """Plain npm text, safe inside Markdown (tables included)."""
    escaped = re.sub(r"([\\`*_\[\]()#!])", r"\\\1", html.escape(text, quote=False))
    return escaped.replace("|", "&#124;").replace("\n", " ")


def is_stale(pkg: Package, now: datetime) -> bool:
    return bool(pkg["updated"]) and datetime.fromisoformat(pkg["updated"]) < now - STALE_AFTER


def install_command(pkg: Package) -> str:
    role = pkg["role"]
    if role.startswith("frontend-plugin"):
        return f"yarn --cwd packages/app add {pkg['name']}"
    if role.startswith("backend-plugin"):
        return f"yarn --cwd packages/backend add {pkg['name']}"
    return f"yarn add {pkg['name']}"


def _is_relative(url: str) -> bool:
    return not re.match(r"^([a-z][a-z0-9+.-]*:|//|#|/)", url, re.IGNORECASE)


def readme_base(pkg: Package) -> tuple[str, str]:
    """Base URLs for (links, images) used to absolutize README-relative paths."""
    repo = pkg["repository"]
    if repo.startswith("https://github.com/"):
        tree = repo if "/tree/" in repo else f"{repo}/tree/HEAD"
        return tree.replace("/tree/", "/blob/", 1), tree.replace("/tree/", "/raw/", 1)
    unpkg = f"https://unpkg.com/{pkg['name']}@{pkg['version']}"
    return unpkg, unpkg


def clean_readme(pkg: Package) -> str:
    """Render README to sanitized HTML: balanced tags, no scripts, absolute URLs."""
    links, images = readme_base(pkg)

    def fix_url(tag: str, attr: str, value: str) -> str:
        if attr in {"href", "src"} and _is_relative(value):
            base = images if attr == "src" else links
            return f"{base}/{value.removeprefix('./')}"
        return value

    body = markdown.markdown(pkg["readme"], extensions=README_EXTENSIONS)
    body = nh3.clean(body, attributes=README_ATTRIBUTES, attribute_filter=fix_url)
    # Demote headings so the README sits under our "## README" section.
    return re.sub(r"<(/?)h([1-6])(?=[\s>])", lambda m: f"<{m[1]}h{min(int(m[2]) + 2, 6)}", body)


def card_description(text: str) -> str:
    """Description as inline HTML for cards: no links (cards are links), no images."""
    body = markdown.markdown(text, extensions=["pymdownx.tilde"])
    body = nh3.clean(body, tags=CARD_TAGS, attributes={})
    return re.sub(r"\s+", " ", body).strip()


def front_matter(data: dict[str, object]) -> str:
    yaml = YAML()
    yaml.default_flow_style = False
    buf = io.StringIO()
    yaml.dump(data, buf)
    return f"---\n{buf.getvalue()}---\n"


def plugin_page(pkg: Package, now: datetime) -> str:
    src = page_path(pkg["name"])
    tags = [k for k in pkg["keywords"] if k not in GENERIC_KEYWORDS][:MAX_TAGS]
    parts = [
        front_matter({"title": pkg["name"], "description": pkg["description"], "tags": tags}),
        f"# {pkg['name']}\n",
    ]
    if pkg["deprecated"]:
        parts.append(f'!!! danger "Deprecated"\n    {cell(pkg["deprecated"])}\n')
    elif is_stale(pkg, now):
        parts.append('!!! warning "Stale"\n    No release in over two years.\n')
    if pkg["description"]:
        parts.append(f"{cell(pkg['description'])}\n")
    parts.append(f"```sh\n{install_command(pkg)}\n```\n")

    npm_url = f"https://www.npmjs.com/package/{pkg['name']}"
    rows = [
        ("Version", f"`{pkg['version']}` ({pkg['updated'][:10]})"),
        ("Role", f"[{role_label(pkg['role'])}]({link(src, f'roles/{role_slug(pkg["role"])}.md')})"),
        (
            "Scope",
            f"[{pkg['scope'] or UNSCOPED}]({link(src, f'scopes/{scope_slug(pkg["scope"])}.md')})",
        ),
        ("Plugin ID", f"`{pkg['plugin_id']}`" if pkg["plugin_id"] else ""),
        ("Weekly downloads", f"{pkg.get('downloads', 0):,}"),
        ("License", cell(pkg["license"])),
        ("Repository", f"<{pkg['repository']}>" if pkg["repository"].startswith("http") else ""),
        ("Homepage", f"<{pkg['homepage']}>" if pkg["homepage"].startswith("http") else ""),
        ("npm", f"<{npm_url}>"),
        ("Author", cell(pkg["author"])),
        ("Maintainers", cell(", ".join(pkg["maintainers"]))),
        ("First published", pkg["created"][:10]),
    ]
    parts.append("| | |\n|---|---|\n" + "".join(f"| {k} | {v} |\n" for k, v in rows if v))

    parts.append(f"## Versions\n\n{pkg['version_count']} versions published. Latest releases:\n")
    parts.append(
        "| Version | Date |\n|---|---|\n"
        + "".join(f"| `{v['version']}` | {v['date'][:10]} |\n" for v in pkg["versions"])
    )
    if pkg["readme"].strip():
        parts.append(f"## README\n\n{README_PLACEHOLDER}\n")
    return "\n".join(parts)


def listing_page(title: str, src: str, pkgs: list[Package]) -> str:
    rows = "".join(
        f"| [{p['name']}]({link(src, page_path(p['name']))}) | {cell(p['description'])} "
        f"| {p.get('downloads', 0):,} | {p['updated'][:10]} |\n"
        for p in sorted(pkgs, key=lambda p: -p.get("downloads", 0))
    )
    return (
        f"# {title}\n\n{len(pkgs)} packages.\n\n"
        f"| Package | Description | Weekly downloads | Updated |\n|---|---|--:|---|\n{rows}"
    )


def index_page(title: str, groups: dict[str, list[Package]], labels: dict[str, str]) -> str:
    rows = "".join(
        f"| [{labels[slug]}]({slug}.md) | {len(pkgs)} |\n"
        for slug, pkgs in sorted(groups.items(), key=lambda kv: -len(kv[1]))
    )
    return f"# {title}\n\n| | Packages |\n|---|--:|\n{rows}"


def card(pkg: Package, now: datetime) -> dict[str, object]:
    return {
        "n": pkg["name"],
        "d": pkg["description"],
        "dh": card_description(pkg["description"]),
        "r": pkg["role"],
        "rl": role_label(pkg["role"]),
        "s": pkg["scope"] or UNSCOPED,
        "k": pkg["keywords"],
        "v": pkg["version"],
        "u": pkg["updated"][:10],
        "dl": pkg.get("downloads", 0),
        "dep": bool(pkg["deprecated"]),
        "st": is_stale(pkg, now),
        "p": f"plugins/{pkg['name']}/",
    }


def render(store: Store, docs: Path, console: Console) -> None:
    now = datetime.now(UTC)
    downloads = store.load_downloads()
    pkgs: list[Package] = []
    for name in store.names():
        pkg = store.load(name)
        pkg["downloads"] = downloads.get(name, 0)
        pkgs.append(pkg)

    for d in GENERATED_DIRS:
        shutil.rmtree(docs / d, ignore_errors=True)

    def write(rel: str, content: str) -> None:
        path = docs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    by_role: dict[str, list[Package]] = {}
    by_scope: dict[str, list[Package]] = {}
    for pkg in pkgs:
        write(page_path(pkg["name"]), plugin_page(pkg, now))
        by_role.setdefault(role_slug(pkg["role"]), []).append(pkg)
        by_scope.setdefault(scope_slug(pkg["scope"]), []).append(pkg)

    role_names = {slug: role_label(group[0]["role"]) for slug, group in by_role.items()}
    scope_names = {slug: group[0]["scope"] or UNSCOPED for slug, group in by_scope.items()}
    for slug, group in by_role.items():
        write(f"roles/{slug}.md", listing_page(role_names[slug], f"roles/{slug}.md", group))
    for slug, group in by_scope.items():
        write(f"scopes/{slug}.md", listing_page(scope_names[slug], f"scopes/{slug}.md", group))
    write("roles/index.md", index_page("Plugins by role", by_role, role_names))
    write("scopes/index.md", index_page("Plugins by scope", by_scope, scope_names))

    cards = sorted((card(p, now) for p in pkgs), key=lambda c: str(c["n"]))
    write("assets/catalog.json", json.dumps(cards, separators=(",", ":"), ensure_ascii=False))
    console.log(f"rendered {len(pkgs)} plugins, {len(by_role)} roles, {len(by_scope)} scopes")
