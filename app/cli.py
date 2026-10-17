"""Command-line entry points: a scrape smoke test and the Mealie migration tool.

Neither of these is a route. Both write rendered files straight to a directory,
reusing the same render() the web layer uses -- see the brief's "one structural
rule".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import httpx

from app.config import Settings
from app.mealie import MealieError, migrate_from_mealie
from app.pipeline import process_url

logger = logging.getLogger(__name__)


async def _scrape_to_directory(urls: list[str], out_dir: Path, settings: Settings) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0

    async with httpx.AsyncClient() as client:
        for url in urls:
            outcome = await process_url(url, None, client=client, settings=settings)
            if not outcome.ok or not outcome.files:
                print(f"FAILED {url}: {outcome.error}", file=sys.stderr)
                failures += 1
                continue

            for warning in outcome.warnings:
                print(f"WARNING {url}: {warning}", file=sys.stderr)

            for relative_path, content in outcome.files.items():
                destination = out_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            print(f"OK {url}")

    return failures


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="scrape one or more URLs to a directory")
    scrape_parser.add_argument("urls", nargs="+", help="recipe URLs")
    scrape_parser.add_argument("--out", type=Path, default=Path("out"), help="output directory")

    migrate_parser = subparsers.add_parser(
        "mealie-migrate", help="migrate every recipe from a Mealie instance to a directory"
    )
    migrate_parser.add_argument("base_url", help="Mealie base URL, e.g. https://mealie.example.com")
    migrate_parser.add_argument(
        "--token",
        default=os.environ.get("MEALIE_API_TOKEN"),
        help="Mealie API token (default: $MEALIE_API_TOKEN)",
    )
    migrate_parser.add_argument("--out", type=Path, default=Path("out"), help="output directory")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=settings.log_level.upper())

    if args.command == "scrape":
        failures = asyncio.run(_scrape_to_directory(args.urls, args.out, settings))
        return 1 if failures else 0

    if args.command == "mealie-migrate":
        if not args.token:
            print("FAILED: pass --token or set MEALIE_API_TOKEN", file=sys.stderr)
            return 1
        try:
            failures = asyncio.run(
                migrate_from_mealie(args.base_url, args.token, args.out, settings)
            )
        except MealieError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        return 1 if failures else 0

    return 1  # pragma: no cover -- unreachable, argparse enforces a known subcommand


if __name__ == "__main__":
    raise SystemExit(main())
