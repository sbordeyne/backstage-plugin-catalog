import argparse
import asyncio
from pathlib import Path

from rich.console import Console

from backstage_catalog.fetch import fetch
from backstage_catalog.render import render
from backstage_catalog.store import Store


def main() -> None:
    parser = argparse.ArgumentParser(prog="backstage-catalog")
    parser.add_argument("--data", type=Path, default=Path("data"))
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_cmd = sub.add_parser("fetch", help="Refresh data/ from npm")
    fetch_cmd.add_argument("--full", action="store_true", help="Refetch every stored package")
    fetch_cmd.add_argument("--full-every", type=int, default=14, help="Days to fully refresh every package")
    fetch_cmd.add_argument("--check-every", type=int, default=7, help="Days to check every deprecation")
    fetch_cmd.add_argument("--concurrency", type=int, default=8, help="Parallel npm requests")
    render_cmd = sub.add_parser("render", help="Generate Markdown pages from data/")
    render_cmd.add_argument("--docs", type=Path, default=Path("docs"))
    args = parser.parse_args()

    console = Console(stderr=True)
    store = Store(args.data)
    if args.command == "fetch":
        asyncio.run(
            fetch(
                store,
                console,
                full=args.full,
                full_every=args.full_every,
                check_every=args.check_every,
                concurrency=args.concurrency,
            )
        )
    else:
        render(store, args.docs, console)


if __name__ == "__main__":
    main()
