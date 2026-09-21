"""Production-grade conversation state management for multi-turn JIRA agent.

Enterprise improvements:
- SessionStore abstraction with Redis backend + in-memory fallback
- Proper asyncio.Lock usage on all mutable operations
- Monotonic time for timeout checks (not wall clock)
- Configurable limits via Settings
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from enum import Enum

from ..core.logging import log_info, log_warning

# ------------------------------------------------------------------ #
# Configuration
# ------------------------------------------------------------------ #

MAX_ACTIVE_SESSIONS = 500
MAX_MESSAGES_PER_SESSION = 100
SESSION_TIMEOUT_SECONDS = 1800  # 30 minutes


# ------------------------------------------------------------------ #
# State machine
# ------------------------------------------------------------------ #

class ConversationState(str, Enum):
    INITIAL = "initial"
    AWAITING_INFO = "awaiting_info"
    PROCESSING = "processing"
    COMPLETED = "completed"


class InfoRequest:
    """Represents a request for missing information."""

    def __init__(self, field: str, description: str, options: Optional[List[str]] = None):
        self.field = field
        self.description = description
        self.options = options or []

    def to_dict(self) -> Dict[str, Any]:
        return {"field": self.field, "description": self.description, "options": self.options}


# ------------------------------------------------------------------ #
# Conversation context
# ------------------------------------------------------------------ #

class ConversationContext:
    """Stores context for a single conversation."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = ConversationState.INITIAL
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self._last_active = time.monotonic()

        # Conversation data
        self.original_intent: Optional[str] = None
        self.action_type: Optional[str] = None
        self.collected_data: Dict[str, Any] = {}
        self.missing_fields: List[InfoRequest] = []

        # History
        self.messages: List[Dict[str, Any]] = []

    def add_message(self, role: str, content: str):
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        if len(self.messages) > MAX_MESSAGES_PER_SESSION:
            self.messages = self.messages[-MAX_MESSAGES_PER_SESSION:]
        self._touch()

    def update_collected_data(self, data: Dict[str, Any]):
        self.collected_data.update(data)
        self._touch()

    def set_missing_fields(self, fields: List[InfoRequest]):
        self.missing_fields = fields
        self.state = ConversationState.AWAITING_INFO
        self._touch()

    def clear_missing_fields(self):
        self.missing_fields = []
        self.state = ConversationState.PROCESSING
        self._touch()

    def is_expired(self, timeout_seconds: int = SESSION_TIMEOUT_SECONDS) -> bool:
        return (time.monotonic() - self._last_active) > timeout_seconds

    def _touch(self):
        self.updated_at = datetime.now()
        self._last_active = time.monotonic()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "original_intent": self.original_intent,
            "action_type": self.action_type,
            "collected_data": self.collected_data,
            "missing_fields": [f.to_dict() for f in self.missing_fields],
            "messages": self.messages,
        }

    def get_conversation_history(self, max_messages: int = 10) -> str:
        if not self.messages:
            return "(No previous conversation)"
        recent = self.messages[-max_messages:]
        return "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in recent
        )

    def get_summary(self) -> str:
        parts: list[str] = []
        if self.action_type:
            parts.append(f"Action: {self.action_type}")
        if self.collected_data:
            parts.append(f"Data collected: {', '.join(self.collected_data.keys())}")
        if self.messages:
            parts.append(f"Messages: {len(self.messages)}")
        return " | ".join(parts) if parts else "New conversation"


# ------------------------------------------------------------------ #
# Session store abstraction
# ------------------------------------------------------------------ #

class SessionStore:
    """Abstract session store interface."""

    async def get(self, session_id: str) -> Optional[ConversationContext]:
        raise NotImplementedError

    async def put(self, ctx: ConversationContext) -> None:
        raise NotImplementedError

    async def delete(self, session_id: str) -> None:
        raise NotImplementedError

    async def active_count(self) -> int:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """In-memory session store with eviction (single-process deployments)."""

    def __init__(self):
        self._contexts: Dict[str, ConversationContext] = {}
        self._lock = asyncio.Lock()

    async def get(self, session_id: str) -> Optional[ConversationContext]:
        async with self._lock:
            self._cleanup_expired()
            return self._contexts.get(session_id)

    async def put(self, ctx: ConversationContext) -> None:
        async with self._lock:
            self._cleanup_expired()
            if ctx.session_id not in self._contexts and len(self._contexts) >= MAX_ACTIVE_SESSIONS:
                oldest_id = min(self._contexts, key=lambda sid: self._contexts[sid]._last_active)
                log_warning(f"Max sessions ({MAX_ACTIVE_SESSIONS}) reached — evicting {oldest_id}", "session_store")
                del self._contexts[oldest_id]
            self._contexts[ctx.session_id] = ctx

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._contexts.pop(session_id, None)

    async def active_count(self) -> int:
        async with self._lock:
            self._cleanup_expired()
            return len(self._contexts)

    def _cleanup_expired(self):
        expired = [sid for sid, ctx in self._contexts.items() if ctx.is_expired()]
        for sid in expired:
            del self._contexts[sid]
        if expired:
            log_info(f"Cleaned up {len(expired)} expired sessions", "session_store")


class RedisSessionStore(SessionStore):
    """Redis-backed session store for horizontally scaled deployments.

    Requires ``redis[hiredis]`` package.  Falls back to in-memory if Redis
    is unavailable.
    """

    def __init__(self, redis_url: str):
        self._redis_url = redis_url
        self._redis = None
        self._fallback = InMemorySessionStore()
        self._prefix = "jira_session:"
        self._ttl = SESSION_TIMEOUT_SECONDS

    async def _ensure_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            log_info("Redis session store connected", "session_store")
            return self._redis
        except Exception as e:
            log_warning(f"Redis unavailable ({e}), falling back to in-memory sessions", "session_store")
            self._redis = None
            return None

    async def get(self, session_id: str) -> Optional[ConversationContext]:
        r = await self._ensure_redis()
        if r is None:
            return await self._fallback.get(session_id)

        try:
            raw = await r.get(f"{self._prefix}{session_id}")
            if raw is None:
                return None
            return self._deserialize(raw)
        except Exception:
            return await self._fallback.get(session_id)

    async def put(self, ctx: ConversationContext) -> None:
        r = await self._ensure_redis()
        if r is None:
            return await self._fallback.put(ctx)

        try:
            await r.setex(f"{self._prefix}{ctx.session_id}", self._ttl, self._serialize(ctx))
        except Exception:
            await self._fallback.put(ctx)

    async def delete(self, session_id: str) -> None:
        r = await self._ensure_redis()
        if r is None:
            return await self._fallback.delete(session_id)
        try:
            await r.delete(f"{self._prefix}{session_id}")
        except Exception:
            await self._fallback.delete(session_id)

    async def active_count(self) -> int:
        r = await self._ensure_redis()
        if r is None:
            return await self._fallback.active_count()
        try:
            keys = await r.keys(f"{self._prefix}*")
            return len(keys)
        except Exception:
            return await self._fallback.active_count()

    @staticmethod
    def _serialize(ctx: ConversationContext) -> str:
        return json.dumps(ctx.to_dict())

    @staticmethod
    def _deserialize(raw: str) -> ConversationContext:
        data = json.loads(raw)
        ctx = ConversationContext(session_id=data["session_id"])
        ctx.state = ConversationState(data.get("state", "initial"))
        ctx.original_intent = data.get("original_intent")
        ctx.action_type = data.get("action_type")
        ctx.collected_data = data.get("collected_data", {})
        ctx.messages = data.get("messages", [])
        ctx.missing_fields = [
            InfoRequest(f["field"], f["description"], f.get("options", []))
            for f in data.get("missing_fields", [])
        ]
        return ctx


# ------------------------------------------------------------------ #
# Conversation manager
# ------------------------------------------------------------------ #

class ConversationManager:
    """Manages conversation sessions via a pluggable SessionStore."""

    def __init__(self, store: Optional[SessionStore] = None):
        self._store = store or InMemorySessionStore()

    async def get_or_create(self, session_id: str) -> ConversationContext:
        ctx = await self._store.get(session_id)
        if ctx is None:
            ctx = ConversationContext(session_id)
            await self._store.put(ctx)
        return ctx

    async def save(self, ctx: ConversationContext) -> None:
        await self._store.put(ctx)

    async def delete(self, session_id: str) -> None:
        await self._store.delete(session_id)

    async def active_count(self) -> int:
        return await self._store.active_count()


# ------------------------------------------------------------------ #
# Factory
# ------------------------------------------------------------------ #

def create_conversation_manager(redis_url: Optional[str] = None) -> ConversationManager:
    """Create a ConversationManager with the appropriate store."""
    if redis_url:
        store = RedisSessionStore(redis_url)
    else:
        store = InMemorySessionStore()
    return ConversationManager(store=store)


# Global default instance (in-memory)
conversation_manager = create_conversation_manager()
