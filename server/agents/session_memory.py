"""Per-session LangChain buffers for singleton agents (Basic, BRD, etc.)."""

from __future__ import annotations

import threading
from typing import Dict, Optional

from langchain_classic.memory import ConversationBufferMemory

DEFAULT_MAX_SESSIONS = 500

# Thread-safe lock for session store access
_session_lock = threading.Lock()


def memory_for_session(
    store: Dict[str, ConversationBufferMemory],
    session_id: Optional[str],
    *,
    max_sessions: int = DEFAULT_MAX_SESSIONS,
) -> ConversationBufferMemory:
    """Return an isolated buffer for *session_id*, or a one-shot buffer when *session_id* is None.
    
    Thread-safe: uses a lock to protect concurrent access to the store dict.
    """
    if not session_id:
        return ConversationBufferMemory()
    with _session_lock:
        if session_id not in store:
            while len(store) >= max_sessions:
                store.pop(next(iter(store)))
            store[session_id] = ConversationBufferMemory()
        return store[session_id]
