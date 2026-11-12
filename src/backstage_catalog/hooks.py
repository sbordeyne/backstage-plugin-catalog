"""ProperDocs hooks, registered in properdocs.yaml."""

from pathlib import Path
from typing import Any

from backstage_catalog.render import README_PLACEHOLDER, clean_readme
from backstage_catalog.store import Store


def on_page_content(html: str, page: Any, config: Any, files: Any) -> str:
    src: str = page.file.src_uri
    if not src.startswith("plugins/") or README_PLACEHOLDER not in html:
        return html
    store = Store(Path(config.config_file_path).parent / "data")
    pkg = store.load(src.removeprefix("plugins/").removesuffix(".md"))
    filled = README_PLACEHOLDER.replace("></section>", f">\n{clean_readme(pkg)}\n</section>")
    return html.replace(README_PLACEHOLDER, filled)
