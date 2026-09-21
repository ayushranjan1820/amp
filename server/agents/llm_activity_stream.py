"""Optional asyncio.Queue (ContextVar) so LLM layers can emit thinking steps during agent SSE streams.

When ``_stream_agent_response`` sets a queue, ``async_call_with_continuation`` and async local/Ollama
callers push ``llm_call`` / ``llm_response`` dicts that merge into the same SSE ``thinking`` events.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from contextvars import ContextVar, Token
from typing import Any, Dict, Optional, Tuple

_log = logging.getLogger("uvicorn.error")

# Request-scoped bridge so worker threads always resolve the correct loop+queue
# (ContextVar alone can be fragile with default ThreadPoolExecutor + nested tasks).
_bridges_lock = threading.Lock()
_bridges: Dict[str, Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = {}
_llm_bridge_id: ContextVar[Optional[str]] = ContextVar("llm_bridge_id", default=None)

_llm_activity_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "llm_activity_queue", default=None
)

# Event loop that created ``llm_activity_queue`` — used with ``emit_llm_activity_sync`` from worker threads.
_llm_activity_loop: ContextVar[Optional[asyncio.AbstractEventLoop]] = ContextVar(
    "llm_activity_loop", default=None
)

# Tunable preview sizes for the reasoning trace UI
PROMPT_PREVIEW_CHARS = 12_000
RESPONSE_LOG_CHARS = 64_000


def set_llm_activity_queue(q: asyncio.Queue) -> Token:
    return _llm_activity_queue.set(q)


def reset_llm_activity_queue(token: Token) -> None:
    _llm_activity_queue.reset(token)


def set_llm_activity_loop(loop: asyncio.AbstractEventLoop) -> Token:
    return _llm_activity_loop.set(loop)


def reset_llm_activity_loop(token: Token) -> None:
    _llm_activity_loop.reset(token)


def get_llm_activity_queue() -> Optional[asyncio.Queue]:
    return _llm_activity_queue.get()


def get_llm_activity_loop() -> Optional[asyncio.AbstractEventLoop]:
    return _llm_activity_loop.get()


def register_llm_sse_bridge(
    loop: asyncio.AbstractEventLoop, q: asyncio.Queue,
) -> Tuple[Token, str]:
    """Bind ``(loop, q)`` for the current streaming request; copy context into worker threads."""
    bid = uuid.uuid4().hex
    with _bridges_lock:
        _bridges[bid] = (loop, q)
    tok = _llm_bridge_id.set(bid)
    return tok, bid


def unregister_llm_sse_bridge(token: Token, bid: str) -> None:
    _llm_bridge_id.reset(token)
    with _bridges_lock:
        _bridges.pop(bid, None)


def _resolve_llm_sse_queue() -> Optional[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]]:
    bid = _llm_bridge_id.get()
    if bid:
        with _bridges_lock:
            pair = _bridges.get(bid)
        if pair:
            return pair
    q = get_llm_activity_queue()
    loop = get_llm_activity_loop()
    if q is not None and loop is not None:
        return loop, q
    return None


def _log_llm_activity_step(step: Dict[str, Any]) -> None:
    t = step.get("type")
    model = step.get("model") or ""
    if t == "llm_call":
        _log.info(
            "LLM activity [call] model=%s provider=%s prompt_chars=%s",
            model,
            step.get("provider") or "",
            step.get("prompt_length") or "",
        )
    elif t == "llm_response":
        _log.info(
            "LLM activity [response] model=%s provider=%s response_chars=%s",
            model,
            step.get("provider") or "",
            step.get("response_length") or "",
        )


def emit_llm_activity_sync(step: Dict[str, Any]) -> None:
    """Schedule ``step`` on the streaming queue from a sync context (e.g. thread pool).

    Uses ``asyncio.run_coroutine_threadsafe`` so the queue is written on the event-loop
    thread (required for asyncio.Queue thread-safety).
    """
    pair = _resolve_llm_sse_queue()
    if pair is None:
        return
    loop, q = pair

    async def _put() -> None:
        await q.put(step)

    try:
        asyncio.run_coroutine_threadsafe(_put(), loop)
    except RuntimeError:
        _log.debug("emit_llm_activity_sync run_coroutine_threadsafe failed", exc_info=True)
    _log_llm_activity_step(step)


async def emit_llm_activity(step: Dict[str, Any]) -> None:
    pair = _resolve_llm_sse_queue()
    if pair is None:
        q = get_llm_activity_queue()
        if q is None:
            return
        try:
            await q.put(step)
        except Exception:
            _log.debug("emit_llm_activity failed", exc_info=True)
        _log_llm_activity_step(step)
        return
    _loop, q = pair
    try:
        await q.put(step)
    except Exception:
        _log.debug("emit_llm_activity failed", exc_info=True)
    _log_llm_activity_step(step)


def build_llm_call_step(
    *,
    provider: str,
    model: str,
    prompt: str,
    phase_note: str = "",
) -> Dict[str, Any]:
    preview = prompt if len(prompt) <= PROMPT_PREVIEW_CHARS else (
        prompt[:PROMPT_PREVIEW_CHARS] + "\n… [truncated for trace preview]"
    )
    note = f" ({phase_note})" if phase_note else ""
    return {
        "type": "llm_call",
        "content": f"LLM request{note} · {provider} · {model}",
        "model": model,
        "provider": provider,
        "tool_input": preview,
        "prompt_length": len(prompt),
    }


def build_llm_response_step(
    *,
    provider: str,
    model: str,
    text: str,
) -> Dict[str, Any]:
    if len(text) <= RESPONSE_LOG_CHARS:
        body = text
        truncated = False
    else:
        body = text[:RESPONSE_LOG_CHARS] + "\n… [truncated for trace preview]"
        truncated = True
    return {
        "type": "llm_response",
        "content": body,
        "model": model,
        "provider": provider,
        "response_length": len(text),
        "truncated": truncated,
    }
