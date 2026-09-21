"""Lightweight session memory for multi-turn browser conversations.

Stores executed steps + outcomes per session so the planner can include
recent history context in subsequent requests.  This enables conversational
multi-turn workflows like:  "search for X" → "now search for Y instead".
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

MAX_SESSIONS = 64
MAX_HISTORY_PER_SESSION = 50


@dataclass
class MemoryEntry:
    """One completed interaction (query + steps + outcomes)."""

    query: str
    steps_summary: List[Dict[str, str]]
    timestamp: str
    final_url: str = ""
    notes: str = ""


class SessionMemory:
    """Thread-safe, LRU-capped session memory store."""

    def __init__(self, max_sessions: int = MAX_SESSIONS):
        self._lock = threading.Lock()
        self._max = max(1, max_sessions)
        self._store: OrderedDict[str, List[MemoryEntry]] = OrderedDict()

    # ── write ───────────────────────────────────────────────────────

    def record(
        self,
        session_id: str,
        query: str,
        results: List[Dict[str, Any]],
        final_url: str = "",
    ) -> None:
        """Record a completed interaction for this session."""
        summary = [
            {
                "step_number": str(r.get("step_number", "?")),
                "action": r.get("action", ""),
                "description": r.get("description", ""),
                "status": r.get("status", "unknown"),
            }
            for r in results
        ]
        entry = MemoryEntry(
            query=query,
            steps_summary=summary,
            timestamp=datetime.now().isoformat(),
            final_url=final_url,
        )
        with self._lock:
            if session_id not in self._store:
                while len(self._store) >= self._max:
                    self._store.popitem(last=False)
                self._store[session_id] = []
            self._store.move_to_end(session_id)
            history = self._store[session_id]
            history.append(entry)
            if len(history) > MAX_HISTORY_PER_SESSION:
                self._store[session_id] = history[-MAX_HISTORY_PER_SESSION:]

    # ── read ────────────────────────────────────────────────────────

    def get_history(self, session_id: str, max_entries: int = 5) -> List[MemoryEntry]:
        """Return recent history for a session (newest last)."""
        with self._lock:
            entries = self._store.get(session_id, [])
            return list(entries[-max_entries:])

    def format_for_planner(self, session_id: str, max_entries: int = 3) -> str:
        """Format session history as context for the LLM planner prompt."""
        entries = self.get_history(session_id, max_entries)
        if not entries:
            return ""

        parts = ["### Previous interactions in this session:\n"]
        for i, entry in enumerate(entries, 1):
            parts.append(f'**Turn {i}:** "{entry.query}"')
            if entry.final_url:
                parts.append(f"  Final URL: {entry.final_url}")
            for s in entry.steps_summary:
                tag = "OK" if s["status"] == "success" else "FAILED"
                parts.append(
                    f"  - Step {s['step_number']}: [{s['action']}] {s['description']} -> {tag}"
                )
            parts.append("")

        parts.append(
            "Use this history to understand what has already been done. "
            "Do NOT repeat completed steps unless the user explicitly asks. "
            "If the browser session is kept, you may already be on a relevant page.\n"
        )
        return "\n".join(parts)

    # ── management ──────────────────────────────────────────────────

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def has_history(self, session_id: str) -> bool:
        with self._lock:
            return bool(self._store.get(session_id))


# Module-level singleton
session_memory = SessionMemory()
