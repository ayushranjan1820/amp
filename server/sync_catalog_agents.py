#!/usr/bin/env python3
"""Merge selected agents and categories from a catalog JSON file into MongoDB.

Writes through ``agents_catalog_db``, which is the store ``/api/agents`` reads:
database ``core_system`` (``CORE_SYSTEM_MONGO_DB``), collection
``agents_catalog``, document ``_id: "main"``. Note that ``seed_catalog.py`` and
``catalog_store`` target a *different*, legacy document (``agents_platform`` /
``_id: "default"``), so seeding there does not change what the API serves.

Saving here also refreshes the running server's dependent registries, so new
agents appear without a restart.

This script is additive: it upserts only the agent ids (and their categories)
that you name, leaving every other agent untouched.

Typical use after adding agents to ``agents_catalog.json``::

    python sync_catalog_agents.py zoho_email_meeting_agent \\
        zoho_support_ticket_agent zoho_new_customer_agent

With no ids it syncs every agent present in the JSON file, still without
deleting agents that exist only in the database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_source(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _merge(target: Dict[str, Any], source: Dict[str, Any], agent_ids: List[str]) -> Dict[str, Any]:
    """Upsert the named agents (and any categories they need) into *target*."""
    source_agents = {a["id"]: a for a in source.get("agents", []) if a.get("id")}
    wanted = agent_ids or list(source_agents)

    missing = [i for i in wanted if i not in source_agents]
    if missing:
        raise SystemExit(f"Not present in the source catalog: {', '.join(missing)}")

    agents = list(target.get("agents") or [])
    index = {a.get("id"): i for i, a in enumerate(agents)}
    added, replaced = [], []
    for agent_id in wanted:
        record = source_agents[agent_id]
        if agent_id in index:
            agents[index[agent_id]] = record
            replaced.append(agent_id)
        else:
            agents.append(record)
            index[agent_id] = len(agents) - 1
            added.append(agent_id)

    categories = list(target.get("categories") or [])
    known = {c.get("id") for c in categories}
    source_categories = {c["id"]: c for c in source.get("categories", []) if c.get("id")}
    needed = {agents[index[a]].get("category") for a in wanted}
    new_categories = []
    for category_id in sorted(c for c in needed if c and c not in known):
        if category_id in source_categories:
            categories.append(source_categories[category_id])
            new_categories.append(category_id)
        else:
            print(f"  warning: agent category {category_id!r} is not defined in the source catalog")

    merged = dict(target)
    merged["agents"] = agents
    merged["categories"] = categories
    if not merged.get("metadata"):
        merged["metadata"] = dict(source.get("metadata") or {})

    print(f"  added:    {', '.join(added) or '(none)'}")
    print(f"  replaced: {', '.join(replaced) or '(none)'}")
    print(f"  new categories: {', '.join(new_categories) or '(none)'}")
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("agent_ids", nargs="*", help="Agent ids to sync (default: every agent in the file)")
    parser.add_argument(
        "--catalog-file",
        type=Path,
        default=Path(__file__).resolve().parent / "agents_catalog.json",
        help="Source catalog JSON (default: ./agents_catalog.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without writing")
    args = parser.parse_args()

    if not args.catalog_file.is_file():
        print(f"Catalog file not found: {args.catalog_file}", file=sys.stderr)
        return 1

    # mongo_db reads its URI from the environment and does not load .env itself
    # (api.py does that at startup), so load the same files the server would.
    from dotenv import load_dotenv

    here = Path(__file__).resolve().parent
    load_dotenv(here / ".env")
    load_dotenv(here.parent / ".env")

    # Imported after the env is loaded, and here rather than at module scope so
    # the merge logic above stays importable (and testable) without MongoDB.
    # agents_catalog_db is the store the API serves from — see the module docstring.
    from agents_catalog_db import get_catalog, save_catalog

    source = _load_source(args.catalog_file)
    try:
        target = get_catalog()
    except Exception as exc:
        print(f"Could not read the catalog from MongoDB: {exc}", file=sys.stderr)
        return 1

    before = len(target.get("agents") or [])
    print(f"Catalog in MongoDB has {before} agents. Merging from {args.catalog_file.name}:")
    merged = _merge(target, source, args.agent_ids)

    if args.dry_run:
        print(f"Dry run: would end with {len(merged['agents'])} agents. Nothing written.")
        return 0

    save_catalog(merged)
    print(f"Saved. Catalog now has {len(merged['agents'])} agents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
