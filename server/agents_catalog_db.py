"""Agents catalog — MongoDB-backed single source of truth.

Replaces ``agents_catalog.json``. The full catalog document lives in the
``agents_catalog`` collection with ``_id: "main"`` and fields
``metadata``, ``categories``, and ``agents``.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from mongo_db import get_async_db, get_db, utcnow

_log = logging.getLogger("agents_catalog_db")

COLLECTION = "agents_catalog"
DOC_ID = "main"

_LEGACY_JSON = Path(__file__).resolve().parent / "agents_catalog.json"


class CatalogNotFoundError(Exception):
    """Raised when the catalog document is missing from MongoDB."""


def _doc_to_catalog(doc: Optional[dict]) -> Dict[str, Any]:
    if not doc:
        return {"metadata": {}, "categories": [], "agents": []}
    out = {k: v for k, v in doc.items() if k != "_id"}
    return out


def _fetch_from_db() -> Optional[dict]:
    return get_db()[COLLECTION].find_one({"_id": DOC_ID})


def _seed_from_legacy_json() -> bool:
    """One-time migration: import legacy agents_catalog.json when present."""
    if not _LEGACY_JSON.exists():
        return False
    try:
        with open(_LEGACY_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        save_catalog(data, touch_metadata=False)
        _log.info(
            "Seeded agents catalog from legacy JSON (%d agents)",
            len(data.get("agents", [])),
        )
        return True
    except Exception as e:
        _log.error("Failed to seed catalog from legacy JSON: %s", e)
        return False


def init_agents_catalog_db() -> None:
    """Ensure the catalog collection exists; seed from legacy JSON on first run."""
    try:
        db = get_db()
        existing = db[COLLECTION].find_one({"_id": DOC_ID}, projection={"_id": 1})
        if not existing:
            if not _seed_from_legacy_json():
                _log.warning(
                    "Agents catalog is empty and no legacy agents_catalog.json found. "
                    "Import catalog data via PUT /api/catalog."
                )
    except Exception as e:
        _log.warning("agents_catalog_db init failed: %s", e)


def get_catalog(*, required: bool = True) -> Dict[str, Any]:
    """Load the full catalog document from MongoDB."""
    doc = _fetch_from_db()
    if not doc and required:
        raise CatalogNotFoundError("Agents catalog not found in MongoDB")
    return _doc_to_catalog(doc)


async def async_get_catalog(*, required: bool = True) -> Dict[str, Any]:
    """Async catalog load from MongoDB."""
    db = get_async_db()
    doc = await db[COLLECTION].find_one({"_id": DOC_ID})
    if not doc and required:
        raise CatalogNotFoundError("Agents catalog not found in MongoDB")
    return _doc_to_catalog(doc)


def save_catalog(data: dict, *, touch_metadata: bool = True) -> None:
    """Persist the full catalog document and refresh dependent registries."""
    payload = {k: v for k, v in data.items() if k not in ("_id", "updated_at")}
    payload["updated_at"] = utcnow()
    if touch_metadata and isinstance(payload.get("metadata"), dict):
        payload["metadata"] = {
            **payload["metadata"],
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_agents": len(payload.get("agents") or []),
        }

    get_db()[COLLECTION].replace_one(
        {"_id": DOC_ID},
        {"_id": DOC_ID, **payload},
        upsert=True,
    )
    _refresh_dependent_registries()


async def async_save_catalog(data: dict) -> None:
    import asyncio

    await asyncio.to_thread(save_catalog, data)


def get_agent_by_id(agent_id: str) -> Optional[Dict[str, Any]]:
    for agent in get_catalog(required=False).get("agents", []):
        if agent.get("id") == agent_id:
            return agent
    return None


def get_all_agent_ids() -> List[str]:
    return [
        a["id"]
        for a in get_catalog(required=False).get("agents", [])
        if a.get("id")
    ]


def get_api_path_to_agent_id() -> Dict[str, str]:
    """Map ``/api/...`` paths to catalog agent ids (for access middleware)."""
    mapping: Dict[str, str] = {}
    for agent in get_catalog(required=False).get("agents", []):
        ep = (agent.get("usage") or {}).get("api_endpoint") or ""
        ep = ep.replace("POST ", "").strip()
        if ep.startswith("/api/") and agent.get("id"):
            mapping[ep] = agent["id"]
    mapping["/api/company-research/extract-charts"] = "company_research"
    mapping["/api/mongodb-rag/context"] = "mongodb_rag"
    mapping["/api/browser-agent/html-report"] = "browser_agent"
    return mapping


def _refresh_dependent_registries() -> None:
    """Refresh module-level registries that depend on catalog content."""
    try:
        from workflow.components.catalog import reload_agent_catalog

        reload_agent_catalog()
    except Exception:
        pass
