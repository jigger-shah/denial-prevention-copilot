"""
CLI for ingesting LCD/NCD/Article documents from the CMS Coverage API.

Usage:
    python scripts/ingest_coverage.py --type lcd --id 33797
    python scripts/ingest_coverage.py --type ncd --id 190.33
    python scripts/ingest_coverage.py --type article --id A57699
    python scripts/ingest_coverage.py --type lcd --id 33797 --force-refresh
    python scripts/ingest_coverage.py --type lcd --id 33797 --dry-run
    python scripts/ingest_coverage.py --type lcd --id 33797 --output-dir /tmp/coverage

--dry-run prints what would be fetched/saved without making a network call or
writing any file. --force-refresh bypasses the local cache and re-fetches.
"""

from __future__ import annotations

import argparse
import sys

from retrieval.ingest import DEFAULT_OUTPUT_DIR, CoverageAPIError, fetch_article, fetch_lcd, fetch_ncd

_FETCHERS = {
    "lcd": fetch_lcd,
    "ncd": fetch_ncd,
    "article": fetch_article,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest an LCD/NCD/Article from the CMS Coverage API.")
    parser.add_argument("--type", choices=sorted(_FETCHERS), required=True, help="Document type to fetch.")
    parser.add_argument("--id", required=True, help="Document ID (e.g. LCD ID, NCD ID, or Article ID).")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory to save raw JSON to.")
    parser.add_argument("--force-refresh", action="store_true", help="Bypass the local cache and re-fetch.")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen without fetching or saving.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fetch = _FETCHERS[args.type]

    if args.dry_run:
        print(
            f"[dry-run] Would fetch {args.type.upper()} id={args.id} "
            f"(force_refresh={args.force_refresh}) and save to {args.output_dir}"
        )
        return 0

    try:
        document = fetch(args.id, output_dir=_resolve_output_dir(args.output_dir), force_refresh=args.force_refresh)
    except CoverageAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    section_count = len(document["sections"])
    print(
        f"Ingested {document['document_type']} {document['document_id']}: "
        f"\"{document['document_title']}\" ({section_count} section(s))"
    )
    return 0


def _resolve_output_dir(output_dir: str):
    import pathlib
    return pathlib.Path(output_dir)


if __name__ == "__main__":
    sys.exit(main())
