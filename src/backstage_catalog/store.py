import json
from pathlib import Path
from typing import Any, NotRequired, TypedDict


class Version(TypedDict):
    version: str
    date: str


class Package(TypedDict):
    name: str
    scope: str
    description: str
    version: str
    license: str
    keywords: list[str]
    role: str
    plugin_id: str
    homepage: str
    repository: str
    author: str
    maintainers: list[str]
    created: str
    updated: str
    deprecated: str
    versions: list[Version]
    version_count: int
    readme: str
    downloads: NotRequired[int]


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


class Store:
    """JSON files under data/, one per package so daily diffs stay small."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.packages_dir = root / "packages"
        self.ignored_path = root / "ignored.json"
        self.downloads_path = root / "downloads.json"

    def _path(self, name: str) -> Path:
        return self.packages_dir / f"{name}.json"

    def names(self) -> list[str]:
        return sorted(
            p.relative_to(self.packages_dir).with_suffix("").as_posix()
            for p in self.packages_dir.rglob("*.json")
        )

    def load(self, name: str) -> Package:
        data: Package = json.loads(self._path(name).read_text())
        return data

    def stored_version(self, name: str) -> str | None:
        path = self._path(name)
        return json.loads(path.read_text())["version"] if path.exists() else None

    def save(self, pkg: Package) -> None:
        _dump(self._path(pkg["name"]), pkg)

    def delete(self, name: str) -> None:
        path = self._path(name)
        if not path.exists():
            return
        path.unlink()
        if path.parent != self.packages_dir and not any(path.parent.iterdir()):
            path.parent.rmdir()

    def load_ignored(self) -> dict[str, str]:
        if not self.ignored_path.exists():
            return {}
        data: dict[str, str] = json.loads(self.ignored_path.read_text())
        return data

    def save_ignored(self, ignored: dict[str, str]) -> None:
        _dump(self.ignored_path, ignored)

    def load_downloads(self) -> dict[str, int]:
        if not self.downloads_path.exists():
            return {}
        data: dict[str, int] = json.loads(self.downloads_path.read_text())
        return data

    def save_downloads(self, downloads: dict[str, int]) -> None:
        _dump(self.downloads_path, downloads)
