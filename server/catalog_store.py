"""MongoDB-backed agents catalog store."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection

_env_dir = Path(__file__).resolve().parent
load_dotenv(_env_dir / ".env")
load_dotenv(_env_dir.parent / ".env")

CATALOG_DOC_ID = "default"
DEFAULT_DB_NAME = "agents_platform"
CATALOG_COLLECTION = "agents_catalog"

_client: Optional[MongoClient] = None


def _get_uri() -> str:
    uri = os.environ.get("MONGODB_URI") or os.environ.get("CORE_SYSTEM_MONGO_DB")
    if not uri:
        raise RuntimeError(
            "MONGODB_URI (or CORE_SYSTEM_MONGO_DB) must be set to use the agents catalog"
        )
    return uri


def _db_name() -> str:
    return os.environ.get("MONGODB_DB_NAME", DEFAULT_DB_NAME)


def _collection() -> Collection:
    global _client
    if _client is None:
        _client = MongoClient(_get_uri(), serverSelectionTimeoutMS=5000)
    return _client[_db_name()][CATALOG_COLLECTION]


def _empty_catalog() -> Dict[str, Any]:
    return {
        "metadata": {
            "version": "1.0.0",
            "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_agents": 0,
            "primary_colors": {},
        },
        "categories": [],
        "agents": [],
    }


def _doc_to_catalog(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if k not in ("_id", "updated_at")}


def get_catalog() -> Dict[str, Any]:
    doc = _collection().find_one({"_id": CATALOG_DOC_ID})
    if not doc:
        return _empty_catalog()
    return _doc_to_catalog(doc)


def save_catalog(data: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    payload = {
        **data,
        "_id": CATALOG_DOC_ID,
        "updated_at": timestamp,
    }
    if "metadata" in payload and isinstance(payload["metadata"], dict):
        payload["metadata"] = {
            **payload["metadata"],
            "last_updated": now.strftime("%Y-%m-%d"),
        }
    _collection().replace_one({"_id": CATALOG_DOC_ID}, payload, upsert=True)
    return _doc_to_catalog(payload)


def get_all_agent_ids() -> List[str]:
    catalog = get_catalog()
    return [a["id"] for a in catalog.get("agents", []) if a.get("id")]


def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None
