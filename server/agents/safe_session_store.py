"""Thread-safe session store with TTL and LRU eviction.

Replaces bare ``dict`` session storage in agents (Shannon, GitHub, Basic, JIRA)
with a thread-safe, bounded, TTL-aware store suitable for anonymous multi-user
concurrency at enterprise scale.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Optional


class SafeSessionStore:
    """Thread-safe session store with max-size (LRU) and TTL eviction.

    Parameters
    ----------
    max_sessions : int
        Maximum number of sessions to keep. When exceeded, the oldest session
        (least-recently used) is evicted.
    ttl_seconds : int
        Time-to-live for each session entry in seconds. Entries older than this
        are considered expired and removed on next access or cleanup.
    """

    def __init__(self, max_sessions: int = 500, ttl_seconds: int = 3600):
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_sessions = max_sessions
        self._ttl_seconds = ttl_seconds

    def get(self, session_id: str) -> Optional[Any]:
        """Get session data by session_id. Returns None if missing or expired."""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return None
            if self._ttl_seconds and (time.monotonic() - entry["_ts"]) > self._ttl_seconds:
                del self._sessions[session_id]
                return None
            # Move to end (most recently used)
            self._sessions.move_to_end(session_id)
            return entry["data"]

    def set(self, session_id: str, data: Any) -> None:
        """Store or update session data."""
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id] = {"data": data, "_ts": time.monotonic()}
                self._sessions.move_to_end(session_id)
            else:
                # Evict oldest if at capacity
                while len(self._sessions) >= self._max_sessions:
                    self._sessions.popitem(last=False)
                self._sessions[session_id] = {"data": data, "_ts": time.monotonic()}

    def get_or_create(self, session_id: str, factory: Callable[[], Any]) -> Any:
        """Get existing session or create a new one using factory function."""
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is not None:
                if not self._ttl_seconds or (time.monotonic() - entry["_ts"]) <= self._ttl_seconds:
                    self._sessions.move_to_end(session_id)
                    return entry["data"]
                else:
                    del self._sessions[session_id]
            # Create new
            while len(self._sessions) >= self._max_sessions:
                self._sessions.popitem(last=False)
            data = factory()
            self._sessions[session_id] = {"data": data, "_ts": time.monotonic()}
            return data

    def delete(self, session_id: str) -> bool:
        """Remove a session. Returns True if it existed."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    def clear(self) -> None:
        """Remove all sessions."""
        with self._lock:
            self._sessions.clear()

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        if not self._ttl_seconds:
            return 0
        now = time.monotonic()
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, v in self._sessions.items()
                if (now - v["_ts"]) > self._ttl_seconds
            ]
            for k in expired_keys:
                del self._sessions[k]
                removed += 1
        return removed

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)

    def __contains__(self, session_id: str) -> bool:
        with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return False
            if self._ttl_seconds and (time.monotonic() - entry["_ts"]) > self._ttl_seconds:
                del self._sessions[session_id]
                return False
            return True
