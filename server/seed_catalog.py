#!/usr/bin/env python3
"""Import an agents catalog JSON file into MongoDB."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from catalog_store import get_catalog, save_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed agents catalog into MongoDB")
    parser.add_argument(
        "catalog_file",
        nargs="?",
        type=Path,
        help="Path to agents catalog JSON (defaults to ./agents_catalog.json if present)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing catalog document",
    )
    args = parser.parse_args()

    catalog_path = args.catalog_file or Path(__file__).resolve().parent / "agents_catalog.json"
    if not catalog_path.is_file():
        print(f"Catalog file not found: {catalog_path}", file=sys.stderr)
        return 1

    with open(catalog_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    existing = get_catalog()
    if existing.get("agents") and not args.force:
        print(
            f"Catalog already exists in MongoDB ({len(existing['agents'])} agents). "
            "Pass --force to replace."
        )
        return 0

    result = save_catalog(data)
    print(f"Seeded catalog with {len(result.get('agents', []))} agents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
