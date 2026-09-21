"""Centralised MongoDB connection helpers for the core system database.

Replaces the PostgreSQL connection pool layer that previously lived in chat_db.
Provides:
- get_client()      sync pymongo client, lazy-initialised, singleton.
- get_db()          sync Database handle.
- get_async_client()/ get_async_db()  motor (async) equivalents.
- next_seq(name)    atomic auto-incrementing counter (replaces PostgreSQL SERIAL).

All callers should obtain collections via get_db() / get_async_db() rather than
constructing their own clients, so we keep one connection pool per process.

The connection string is read from CORE_SYSTEM_MONGO_DB (preferred) or, as a
fallback for backward compat with prior deployments, MONGODB_URI. The database
name defaults to ``core_system`` and can be overridden via CORE_SYSTEM_MONGO_DBNAME.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import MongoClient, ReturnDocument
from pymongo.database import Database

_log = logging.getLogger("mongo_db")

DEFAULT_DB_NAME = "core_system"

_sync_client: Optional[MongoClient] = None
_sync_lock = threading.Lock()

_async_client = None  # motor.motor_asyncio.AsyncIOMotorClient
_async_lock = threading.Lock()
_async_loop: Optional[asyncio.AbstractEventLoop] = None


def _mongo_uri() -> str:
    uri = (
        os.environ.get("CORE_SYSTEM_MONGO_DB")
        or os.environ.get("MONGODB_URI")
    )
    if not uri:
        raise ValueError(
            "No MongoDB URI configured. Set CORE_SYSTEM_MONGO_DB (preferred) or MONGODB_URI."
        )
    # Tolerate accidental whitespace from .env quoting
    return uri.strip()


def _db_name() -> str:
    return os.environ.get("CORE_SYSTEM_MONGO_DBNAME", DEFAULT_DB_NAME)


# ---------------------------------------------------------------------------
# Sync (pymongo)
# ---------------------------------------------------------------------------


def get_client() -> MongoClient:
    """Return the process-wide pymongo client (lazy, thread-safe)."""
    global _sync_client
    if _sync_client is not None:
        return _sync_client
    with _sync_lock:
        if _sync_client is None:
            _sync_client = MongoClient(
                _mongo_uri(),
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                appname="agents-core-system",
            )
            _log.info("pymongo client created")
    return _sync_client


def get_db() -> Database:
    return get_client()[_db_name()]


def close_client() -> None:
    global _sync_client
    with _sync_lock:
        if _sync_client is not None:
            try:
                _sync_client.close()
            finally:
                _sync_client = None
                _log.info("pymongo client closed")


# ---------------------------------------------------------------------------
# Async (motor)
# ---------------------------------------------------------------------------


def get_async_client():
    """Return the process-wide motor client.

    motor's client must be created on the running asyncio loop. We bind to the
    first loop we see; subsequent calls assert that loop matches. If the loop
    has changed (test reload, etc.), we transparently rebuild.
    """
    global _async_client, _async_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    with _async_lock:
        if _async_client is not None and _async_loop is loop:
            return _async_client
        # Either first init, or loop changed — (re)create
        from motor.motor_asyncio import AsyncIOMotorClient

        if _async_client is not None:
            try:
                _async_client.close()
            except Exception:
                pass
        _async_client = AsyncIOMotorClient(
            _mongo_uri(),
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            appname="agents-core-system-async",
        )
        _async_loop = loop
        _log.info("motor client created")
        return _async_client


def get_async_db():
    return get_async_client()[_db_name()]


async def init_async_client() -> None:
    """Force motor client creation and ping the server. Safe to call multiple times."""
    try:
        client = get_async_client()
        await client.admin.command("ping")
        _log.info("motor client connected (ping ok)")
    except Exception as e:
        _log.warning("motor client ping failed: %s", e)


async def close_async_client() -> None:
    global _async_client, _async_loop
    if _async_client is not None:
        try:
            _async_client.close()
        finally:
            _async_client = None
            _async_loop = None
            _log.info("motor client closed")


# ---------------------------------------------------------------------------
# Auto-incrementing counters (SERIAL replacement)
# ---------------------------------------------------------------------------


def next_seq(name: str) -> int:
    """Atomically increment and return the next integer for ``name``.

    Backed by a single-document upsert on the ``_counters`` collection.
    Used wherever PostgreSQL SERIAL/BIGSERIAL primary keys were exposed
    (e.g. ``admin_users.id``, ``pipeline_steps.id``, ``cost_events.id``).
    """
    db = get_db()
    doc = db["_counters"].find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


async def async_next_seq(name: str) -> int:
    """Async sibling of :func:`next_seq`."""
    db = get_async_db()
    doc = await db["_counters"].find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


# ---------------------------------------------------------------------------
# Misc helpers used across modules
# ---------------------------------------------------------------------------


def utcnow() -> datetime:
    """Return a tz-aware UTC datetime suitable for storing in MongoDB."""
    return datetime.now(timezone.utc)


def strip_id(doc: Optional[dict]) -> Optional[dict]:
    """Drop the raw Mongo ``_id`` if our domain object already exposes ``id``.

    Several callers store both a domain ``id`` (TEXT in PostgreSQL) and rely on
    the document being free of ``_id`` before JSON-serialising. Use this in
    accessors that previously did ``dict(row)`` over psycopg2 RealDictCursor.
    """
    if doc is None:
        return None
    out = dict(doc)
    out.pop("_id", None)
    return out
