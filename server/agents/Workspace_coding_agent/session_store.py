"""Persistent, file-backed session store for Workspace context Agent.

Survives server restarts and works across multiple workers pointing at shared
storage.  Falls back gracefully if the sessions directory is not writable —
in that case calls still work, sessions just aren't persisted.

Session TTL is configurable via the WCA_SESSION_TTL env var (default 24h).
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

_SESSIONS_DIR = Path(__file__).parent / "sessions"
_SESSION_TTL_SECONDS = int(os.getenv("WCA_SESSION_TTL", str(60 * 60 * 24)))  # 24 h
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sanitize_session_id(session_id: str) -> str:
    """Strip characters that could cause path traversal or OS issues."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)[:128]


def _session_path(session_id: str) -> Path:
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return _SESSIONS_DIR / f"{_sanitize_session_id(session_id)}.json"


def _default_session() -> Dict[str, Any]:
    now = time.time()
    return {
        "repo_path": None,
        "repo_name": None,
        "cloned": False,
        "modified_files": [],
        "local_workspace": True,
        "repo_url": None,
        "cli_session_id": None,
        "token_usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "calls": 0,
        },
        "created_at": now,
        "updated_at": now,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_session(session_id: str) -> Dict[str, Any]:
    """Load session from disk, or return a fresh default."""
    path = _session_path(session_id)
    with _lock:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                # Expire stale sessions
                if time.time() - data.get("updated_at", 0) > _SESSION_TTL_SECONDS:
                    path.unlink(missing_ok=True)
                    return _default_session()
                # Back-fill keys added in later versions
                defaults = _default_session()
                for k, v in defaults.items():
                    data.setdefault(k, v)
                return data
            except (json.JSONDecodeError, OSError):
                pass
    return _default_session()


def save_session(session_id: str, session: Dict[str, Any]) -> None:
    """Persist session to disk atomically (write-then-rename)."""
    session = dict(session)
    session["updated_at"] = time.time()
    path = _session_path(session_id)
    tmp = path.with_suffix(".tmp")
    with _lock:
        try:
            tmp.write_text(
                json.dumps(session, indent=2, default=str),
                encoding="utf-8",
            )
            tmp.replace(path)
        except OSError:
            pass  # best-effort; in-memory session still used


def bump_token_usage(
    session_id: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Increment token counters for a session (best-effort)."""
    s = get_session(session_id)
    tu = s.setdefault(
        "token_usage",
        {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0},
    )
    tu["prompt_tokens"] += prompt_tokens
    tu["completion_tokens"] += completion_tokens
    tu["calls"] += 1
    save_session(session_id, s)


def clear_session(session_id: str) -> None:
    """Delete a persisted session."""
    path = _session_path(session_id)
    with _lock:
        path.unlink(missing_ok=True)


def list_active_sessions() -> list:
    """Return session_ids whose files still exist on disk."""
    try:
        _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        return [
            p.stem
            for p in _SESSIONS_DIR.glob("*.json")
            if not p.name.endswith(".tmp")
        ]
    except OSError:
        return []
