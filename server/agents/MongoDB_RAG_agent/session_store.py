"""Session store for the MongoDB Atlas KB Agent.

Backends: memory (thread-safe, TTL) and Redis (with memory fallback).

Each session stores:
  - uri_hash: SHA-256 of the MongoDB URI (never stored in plain text)
  - mongodb_uri: the actual URI for reconnection (held only in memory backend)
  - db_name, collection_name
  - files_ingested: list of ingested source names
  - conversation_history: list of {role, content} dicts

Redis backend stores everything except the raw URI (security).
The raw URI is re-supplied by the client on reconnect when using Redis.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from typing import Any, Dict, List, Optional

from .config import MongoRAGSettings


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------

class _InMemorySessionStore:
    def __init__(self, max_turns: int, ttl_seconds: int):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._max_turns = max_turns
        self._ttl = ttl_seconds

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return None
            if time.time() - entry["last_access"] > self._ttl:
                del self._store[session_id]
                return None
            entry["last_access"] = time.time()
            return dict(entry)

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        with self._lock:
            now = time.time()
            if session_id in self._store:
                self._store[session_id].update(data)
                self._store[session_id]["last_access"] = now
            else:
                self._store[session_id] = {**data, "last_access": now}

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return
            history = entry.setdefault("conversation_history", [])
            history.append({"role": role, "content": content})
            if len(history) > self._max_turns:
                entry["conversation_history"] = history[-self._max_turns:]
            entry["last_access"] = time.time()

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        with self._lock:
            entry = self._store.get(session_id)
            if entry is None:
                return []
            return list(entry.get("conversation_history", []))

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def clear_history(self, session_id: str) -> None:
        with self._lock:
            entry = self._store.get(session_id)
            if entry:
                entry["conversation_history"] = []


# ---------------------------------------------------------------------------
# Redis session store
# ---------------------------------------------------------------------------

class _RedisSessionStore:
    """Redis-backed sessions with memory fallback.

    The raw URI is NOT stored in Redis for security. The client must
    re-supply it on reconnect if the in-process MongoClient is evicted.
    """

    def __init__(self, redis_url: str, max_turns: int, ttl_seconds: int):
        self._prefix = "mongo_rag_session:"
        self._max_turns = max_turns
        self._ttl = ttl_seconds
        self._fallback = _InMemorySessionStore(max_turns, ttl_seconds)
        self._use_fallback = False
        try:
            import redis
            self._client = redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
        except Exception as e:
            print(f"[SessionStore] Redis unavailable ({e}), using in-memory")
            self._use_fallback = True

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        if self._use_fallback:
            return self._fallback.get(session_id)
        try:
            raw = self._client.get(self._key(session_id))
            return json.loads(raw) if raw else None
        except Exception:
            return self._fallback.get(session_id)

    def set(self, session_id: str, data: Dict[str, Any]) -> None:
        if self._use_fallback:
            self._fallback.set(session_id, data)
            return
        try:
            existing = self.get(session_id) or {}
            # Never persist the raw URI in Redis
            safe = {k: v for k, v in data.items() if k != "mongodb_uri"}
            existing.update(safe)
            self._client.setex(self._key(session_id), self._ttl, json.dumps(existing, default=str))
        except Exception:
            self._fallback.set(session_id, data)

    def append_turn(self, session_id: str, role: str, content: str) -> None:
        if self._use_fallback:
            self._fallback.append_turn(session_id, role, content)
            return
        try:
            existing = self.get(session_id) or {}
            history = existing.setdefault("conversation_history", [])
            history.append({"role": role, "content": content})
            if len(history) > self._max_turns:
                existing["conversation_history"] = history[-self._max_turns:]
            self._client.setex(self._key(session_id), self._ttl, json.dumps(existing, default=str))
        except Exception:
            self._fallback.append_turn(session_id, role, content)

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        data = self.get(session_id)
        return list(data.get("conversation_history", [])) if data else []

    def delete(self, session_id: str) -> None:
        if self._use_fallback:
            self._fallback.delete(session_id)
            return
        try:
            self._client.delete(self._key(session_id))
        except Exception:
            self._fallback.delete(session_id)

    def clear_history(self, session_id: str) -> None:
        if self._use_fallback:
            self._fallback.clear_history(session_id)
            return
        try:
            existing = self.get(session_id)
            if existing:
                existing["conversation_history"] = []
                self._client.setex(self._key(session_id), self._ttl, json.dumps(existing, default=str))
        except Exception:
            self._fallback.clear_history(session_id)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_session_store(settings: MongoRAGSettings):
    if settings.session_backend == "redis":
        return _RedisSessionStore(
            redis_url=settings.redis_url,
            max_turns=settings.session_max_turns,
            ttl_seconds=settings.session_ttl_seconds,
        )
    return _InMemorySessionStore(
        max_turns=settings.session_max_turns,
        ttl_seconds=settings.session_ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hash_uri(uri: str) -> str:
    """One-way hash for storing URI identity without storing the secret."""
    return hashlib.sha256(uri.encode()).hexdigest()[:16]
