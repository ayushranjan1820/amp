"""Chat DB module — MongoDB-backed.

Migrated from PostgreSQL (psycopg2 / asyncpg) to MongoDB (pymongo / motor)
in 2026-05. Public function signatures are preserved so all existing callers
work unchanged. The legacy ``get_connection``/``_db_url`` helpers are kept as
thin shims that now resolve to MongoDB to avoid breaking imports across the
codebase.

Collections:
- chat_sessions       (id TEXT PK)
- chat_messages       (id INT auto, session_id TEXT)
- pipeline_steps      (id INT auto, unique on session_id+agent_name+input_hash)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from mongo_db import (
    async_next_seq,
    close_async_client,
    get_async_db,
    get_db,
    init_async_client,
    next_seq,
    utcnow,
)

_log = logging.getLogger("chat_db")

SESSIONS = "chat_sessions"
MESSAGES = "chat_messages"
STEPS = "pipeline_steps"


# ---------------------------------------------------------------------------
# Backwards-compatible shims (the old psycopg2 helpers are still imported by
# other modules — they keep working but now resolve to MongoDB).
# ---------------------------------------------------------------------------


def _db_url() -> str:
    """Compatibility shim — returns the configured MongoDB URI."""
    uri = (
        os.environ.get("CORE_SYSTEM_MONGO_DB")
        or os.environ.get("MONGODB_URI")
    )
    if not uri:
        raise ValueError(
            "No MongoDB URI configured. Set CORE_SYSTEM_MONGO_DB or MONGODB_URI."
        )
    return uri.strip()


def get_connection():
    """Compatibility shim — older callers still expect a context-manager-like
    "connection" object. We now return the pymongo Database itself, which
    most callers used only to fetch ``.cursor()`` from. Any such caller has
    been migrated to direct MongoDB queries; this helper is preserved so a
    stray import doesn't break startup.
    """
    return get_db()


# ---------------------------------------------------------------------------
# Async pool lifecycle (preserved name; now drives motor)
# ---------------------------------------------------------------------------


async def init_pool() -> None:
    """Initialise the async MongoDB client. Idempotent."""
    await init_async_client()


async def close_pool() -> None:
    await close_async_client()


# ---------------------------------------------------------------------------
# Schema bootstrap — creates indexes that mirror prior PG constraints.
# ---------------------------------------------------------------------------


def init_db() -> None:
    """Create indexes for chat_sessions, chat_messages, pipeline_steps."""
    try:
        db = get_db()
        db[SESSIONS].create_index([("updated_at", DESCENDING)])
        db[MESSAGES].create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
        db[STEPS].create_index(
            [("session_id", ASCENDING), ("agent_name", ASCENDING), ("input_hash", ASCENDING)],
            unique=True,
            name="uq_pipeline_step",
        )
        db[STEPS].create_index([("session_id", ASCENDING), ("agent_name", ASCENDING)])
        print("Chat database collections initialized successfully")
    except Exception as e:
        print(f"Database init: {e}")


# ---------------------------------------------------------------------------
# Internal serialisation helpers
# ---------------------------------------------------------------------------


def _session_doc_to_api(doc: Optional[dict]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    return {
        "id": doc.get("id") or doc.get("_id"),
        "title": doc.get("title", "New Chat"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "message_count": int(doc.get("message_count", 0)),
    }


def _message_doc_to_api(doc: Optional[dict]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    out = {
        "id": doc.get("id"),
        "session_id": doc.get("session_id"),
        "role": doc.get("role"),
        "content": doc.get("content"),
        "thinking_steps": doc.get("thinking_steps"),
        "routed_to": doc.get("routed_to"),
        "bpmn_xml": doc.get("bpmn_xml"),
        "metadata": doc.get("metadata"),
        "created_at": doc.get("created_at"),
    }
    return out


def _step_doc_to_api(doc: Optional[dict]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    return {
        "id": doc.get("id"),
        "session_id": doc.get("session_id"),
        "agent_name": doc.get("agent_name"),
        "input_hash": doc.get("input_hash"),
        "status": doc.get("status"),
        "result": doc.get("result"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


# ---------------------------------------------------------------------------
# Public ASYNC API (motor) — drop-in replacements for the prior asyncpg paths
# ---------------------------------------------------------------------------


async def async_create_session(session_id: str, title: str = "New Chat") -> Dict[str, Any]:
    db = get_async_db()
    now = utcnow()
    doc = {
        "_id": session_id,
        "id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }
    try:
        await db[SESSIONS].insert_one(doc)
    except DuplicateKeyError:
        # Already exists — return the existing one
        existing = await db[SESSIONS].find_one({"_id": session_id})
        return _session_doc_to_api(existing)
    return _session_doc_to_api(doc)


async def async_list_sessions(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    db = get_async_db()
    cursor = (
        db[SESSIONS]
        .find({})
        .sort("updated_at", DESCENDING)
        .skip(int(offset))
        .limit(int(limit))
    )
    rows = []
    async for doc in cursor:
        rows.append(_session_doc_to_api(doc))
    return rows


async def async_get_session(session_id: str) -> Optional[Dict[str, Any]]:
    db = get_async_db()
    doc = await db[SESSIONS].find_one({"_id": session_id})
    return _session_doc_to_api(doc)


async def async_update_session_title(session_id: str, title: str) -> Optional[Dict[str, Any]]:
    db = get_async_db()
    doc = await db[SESSIONS].find_one_and_update(
        {"_id": session_id},
        {"$set": {"title": title, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return _session_doc_to_api(doc)


async def async_delete_session(session_id: str) -> bool:
    db = get_async_db()
    res = await db[SESSIONS].delete_one({"_id": session_id})
    # Cascade — mirrors PG ON DELETE CASCADE
    if res.deleted_count:
        await db[MESSAGES].delete_many({"session_id": session_id})
    return res.deleted_count > 0


async def async_save_message(
    session_id: str,
    role: str,
    content: str,
    thinking_steps: Optional[List[Dict]] = None,
    routed_to: Optional[Dict] = None,
    bpmn_xml: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    db = get_async_db()
    msg_id = await async_next_seq("chat_messages")
    now = utcnow()
    doc = {
        "_id": msg_id,
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "thinking_steps": thinking_steps,
        "routed_to": routed_to,
        "bpmn_xml": bpmn_xml,
        "metadata": metadata,
        "created_at": now,
    }
    await db[MESSAGES].insert_one(doc)
    await db[SESSIONS].update_one(
        {"_id": session_id},
        {"$set": {"updated_at": now}, "$inc": {"message_count": 1}},
    )
    return _message_doc_to_api(doc)


async def async_get_messages(session_id: str) -> List[Dict[str, Any]]:
    db = get_async_db()
    cursor = db[MESSAGES].find({"session_id": session_id}).sort("created_at", ASCENDING)
    messages: List[Dict[str, Any]] = []
    async for doc in cursor:
        msg = _message_doc_to_api(doc)
        if msg and msg.get("metadata") and isinstance(msg["metadata"], dict):
            msg.update(msg["metadata"])
        messages.append(msg)
    return messages


# ---------------------------------------------------------------------------
# Pipeline step checkpointing (idempotent) — async only
# ---------------------------------------------------------------------------


def compute_input_hash(query: str, user_config: Optional[dict] = None) -> str:
    payload = json.dumps({"q": query, "c": user_config or {}}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


async def get_or_create_pipeline_step(
    session_id: str, agent_name: str, input_hash: str
) -> Dict[str, Any]:
    """Return the existing step (idempotent) or create a new 'pending' row.

    Uses upsert with $setOnInsert / $set to be race-safe under concurrent calls
    — mirroring the prior INSERT ... ON CONFLICT DO UPDATE behaviour.
    """
    db = get_async_db()
    key = {"session_id": session_id, "agent_name": agent_name, "input_hash": input_hash}
    now = utcnow()

    # Need a deterministic id on insert — generate one from the counter when missing.
    # Use a two-step approach: try update-existing first, then insert if absent.
    existing = await db[STEPS].find_one(key)
    if existing is not None:
        # Touch updated_at and return
        await db[STEPS].update_one({"_id": existing["_id"]}, {"$set": {"updated_at": now}})
        existing["updated_at"] = now
        return _step_doc_to_api(existing)

    new_id = await async_next_seq("pipeline_steps")
    doc = {
        "_id": new_id,
        "id": new_id,
        **key,
        "status": "pending",
        "result": None,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db[STEPS].insert_one(doc)
        return _step_doc_to_api(doc)
    except DuplicateKeyError:
        # Lost a race — fetch the winner.
        existing = await db[STEPS].find_one(key)
        return _step_doc_to_api(existing)


async def update_pipeline_step(
    step_id: int, status: str, result: Optional[dict] = None
) -> None:
    db = get_async_db()
    await db[STEPS].update_one(
        {"_id": step_id},
        {"$set": {"status": status, "result": result, "updated_at": utcnow()}},
    )


async def get_cached_pipeline_result(
    session_id: str, agent_name: str, input_hash: str
) -> Optional[Dict[str, Any]]:
    db = get_async_db()
    doc = await db[STEPS].find_one(
        {
            "session_id": session_id,
            "agent_name": agent_name,
            "input_hash": input_hash,
            "status": "done",
        },
        {"result": 1, "_id": 0},
    )
    if doc and doc.get("result") is not None:
        r = doc["result"]
        return json.loads(r) if isinstance(r, str) else r
    return None


# ---------------------------------------------------------------------------
# Public SYNC API — backward-compatible (now uses pymongo)
# ---------------------------------------------------------------------------


def create_session(session_id: str, title: str = "New Chat") -> Dict[str, Any]:
    db = get_db()
    now = utcnow()
    doc = {
        "_id": session_id,
        "id": session_id,
        "title": title,
        "created_at": now,
        "updated_at": now,
        "message_count": 0,
    }
    try:
        db[SESSIONS].insert_one(doc)
    except DuplicateKeyError:
        existing = db[SESSIONS].find_one({"_id": session_id})
        return _session_doc_to_api(existing)
    return _session_doc_to_api(doc)


def list_sessions(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = (
        db[SESSIONS]
        .find({})
        .sort("updated_at", DESCENDING)
        .skip(int(offset))
        .limit(int(limit))
    )
    return [_session_doc_to_api(d) for d in cursor]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    return _session_doc_to_api(db[SESSIONS].find_one({"_id": session_id}))


def update_session_title(session_id: str, title: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    doc = db[SESSIONS].find_one_and_update(
        {"_id": session_id},
        {"$set": {"title": title, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return _session_doc_to_api(doc)


def delete_session(session_id: str) -> bool:
    db = get_db()
    res = db[SESSIONS].delete_one({"_id": session_id})
    if res.deleted_count:
        db[MESSAGES].delete_many({"session_id": session_id})
    return res.deleted_count > 0


def save_message(
    session_id: str,
    role: str,
    content: str,
    thinking_steps: Optional[List[Dict]] = None,
    routed_to: Optional[Dict] = None,
    bpmn_xml: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> Dict[str, Any]:
    db = get_db()
    msg_id = next_seq("chat_messages")
    now = utcnow()
    doc = {
        "_id": msg_id,
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "thinking_steps": thinking_steps,
        "routed_to": routed_to,
        "bpmn_xml": bpmn_xml,
        "metadata": metadata,
        "created_at": now,
    }
    db[MESSAGES].insert_one(doc)
    db[SESSIONS].update_one(
        {"_id": session_id},
        {"$set": {"updated_at": now}, "$inc": {"message_count": 1}},
    )
    return _message_doc_to_api(doc)


def get_messages(session_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = db[MESSAGES].find({"session_id": session_id}).sort("created_at", ASCENDING)
    out: List[Dict[str, Any]] = []
    for r in cursor:
        msg = _message_doc_to_api(r)
        if msg and msg.get("metadata") and isinstance(msg["metadata"], dict):
            msg.update(msg["metadata"])
        out.append(msg)
    return out


def generate_title_from_query(query: str) -> str:
    title = query.strip()
    if len(title) > 60:
        title = title[:57] + "..."
    return title
