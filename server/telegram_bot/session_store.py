"""MongoDB-backed session storage for the Telegram Bot.

Falls back to in-memory dicts when the database is unavailable.
Uses the shared ``mongo_db.get_db()`` client.

Migrated from PostgreSQL in 2026-05.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from . import config

logger = logging.getLogger(__name__)


SESSIONS_COLLECTION = "telegram_bot_sessions"


# ---------------------------------------------------------------------------
# In-memory fallback
# ---------------------------------------------------------------------------


class _InMemoryStore:
    """Dict-backed store used when MongoDB is unreachable."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}
        self._expires: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Dict]:
        exp = self._expires.get(key)
        if exp is not None and time.time() > exp:
            self._data.pop(key, None)
            self._expires.pop(key, None)
            return None
        return self._data.get(key)

    def set(self, key: str, data: Dict, ttl: Optional[int] = None) -> None:
        self._data[key] = data
        if ttl:
            self._expires[key] = time.time() + ttl
        else:
            self._expires.pop(key, None)

    def delete(self, key: str) -> bool:
        removed = key in self._data
        self._data.pop(key, None)
        self._expires.pop(key, None)
        return removed

    def cleanup_expired(self) -> int:
        now = time.time()
        expired = [k for k, exp in self._expires.items() if now > exp]
        for k in expired:
            self._data.pop(k, None)
            self._expires.pop(k, None)
        return len(expired)


# ---------------------------------------------------------------------------
# MongoDB store
# ---------------------------------------------------------------------------


def _get_db():
    """Import lazily so the module loads even if mongo_db isn't on sys.path yet."""
    from mongo_db import get_db
    return get_db()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class _MongoStore:
    """Store sessions in the telegram_bot_sessions collection."""

    def __init__(self) -> None:
        self._fallback = _InMemoryStore()
        self._db_available = True

    def init_db(self) -> None:
        try:
            db = _get_db()
            # TTL index — MongoDB will purge expired docs server-side using ``expires_at``.
            db[SESSIONS_COLLECTION].create_index(
                "expires_at",
                expireAfterSeconds=0,
                name="ttl_expires_at",
                sparse=True,
            )
            self._db_available = True
            logger.info("telegram_bot_sessions collection initialized")
        except Exception as exc:
            logger.warning("MongoDB unavailable for sessions, using in-memory fallback: %s", exc)
            self._db_available = False

    def get(self, key: str) -> Optional[Dict]:
        if not self._db_available:
            return self._fallback.get(key)
        try:
            db = _get_db()
            doc = db[SESSIONS_COLLECTION].find_one({"_id": key})
            if doc is None:
                return None
            expires_at = doc.get("expires_at")
            if expires_at is not None and expires_at <= _utcnow():
                # Stale doc the TTL monitor hasn't reaped yet — treat as missing.
                return None
            data = doc.get("data") or {}
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.warning("Session get failed (key=%s): %s", key, exc)
            return self._fallback.get(key)

    def set(self, key: str, data: Dict, ttl: Optional[int] = None) -> None:
        self._fallback.set(key, data, ttl)
        if not self._db_available:
            return
        try:
            now = _utcnow()
            expires_at = (now + timedelta(seconds=ttl)) if ttl else None
            db = _get_db()
            db[SESSIONS_COLLECTION].update_one(
                {"_id": key},
                {
                    "$set": {
                        "data": data,
                        "updated_at": now,
                        "expires_at": expires_at,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        except Exception as exc:
            logger.warning("Session set failed (key=%s): %s", key, exc)

    def delete(self, key: str) -> bool:
        self._fallback.delete(key)
        if not self._db_available:
            return True
        try:
            db = _get_db()
            res = db[SESSIONS_COLLECTION].delete_one({"_id": key})
            return res.deleted_count > 0
        except Exception as exc:
            logger.warning("Session delete failed (key=%s): %s", key, exc)
            return False

    def cleanup_expired(self) -> int:
        self._fallback.cleanup_expired()
        if not self._db_available:
            return 0
        try:
            db = _get_db()
            res = db[SESSIONS_COLLECTION].delete_many(
                {"expires_at": {"$ne": None, "$lt": _utcnow()}}
            )
            cleaned = int(res.deleted_count or 0)
            if cleaned:
                logger.info("Cleaned up %d expired session(s)", cleaned)
            return cleaned
        except Exception as exc:
            logger.warning("Session cleanup failed: %s", exc)
            return 0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: Optional[_MongoStore] = None


def get_store() -> _MongoStore:
    """Return the singleton session store (creates on first call)."""
    global _store
    if _store is None:
        _store = _MongoStore()
    return _store


def init_session_db() -> None:
    """Create the sessions collection / indexes if they don't exist."""
    get_store().init_db()


# ---------------------------------------------------------------------------
# Convenience helpers (mirror the old dict API)
# ---------------------------------------------------------------------------


def get_user_session(telegram_id: int) -> Optional[Dict]:
    return get_store().get(f"user:{telegram_id}")


def set_user_session(telegram_id: int, data: Dict) -> None:
    get_store().set(f"user:{telegram_id}", data, ttl=config.SESSION_TTL_SECONDS)


def delete_user_session(telegram_id: int) -> bool:
    return get_store().delete(f"user:{telegram_id}")


def get_chat_session(chat_id: int) -> Optional[str]:
    data = get_store().get(f"chat:{chat_id}")
    if data:
        return data.get("session_id")
    return None


def set_chat_session(chat_id: int, session_id: str) -> None:
    get_store().set(f"chat:{chat_id}", {"session_id": session_id})


def delete_chat_session(chat_id: int) -> bool:
    return get_store().delete(f"chat:{chat_id}")
