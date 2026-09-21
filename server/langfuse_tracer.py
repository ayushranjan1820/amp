"""
Langfuse LLM call tracer — app-wide observability for every LLM generation.

Design goals
------------
* **Zero-blocking**: all Langfuse SDK calls happen in a daemon background thread,
  so the LLM response path is never delayed.
* **Context-variable propagation**: ``set_langfuse_context`` is called once at the
  API-request entry point; ContextVars carry user_id / session_id / agent_name
  automatically through the entire async (and threaded-sync) call stack.
* **Feature-flag gated**: set ``LANGFUSE_ENABLED=true`` in server/.env to enable;
  any other value (or the key being absent) skips tracing (see startup + first-call console lines).
* **Console mirror**: by default prints ``[Langfuse] ...`` lines to stdout; set
  ``LANGFUSE_CONSOLE_LOG=false`` to disable. API lifespan calls ``log_langfuse_boot_status()``.

Quick usage
-----------
At request entry (e.g. ``_stream_agent_response`` in api.py)::

    from langfuse_tracer import set_langfuse_context
    set_langfuse_context(user_id="alice", session_id="sess-abc", agent_name="JIRA Agent")

LLM call sites (handled automatically by the instrumented llm_continuation.py)::

    from langfuse_tracer import trace_llm_call
    trace_llm_call(
        model="",
        prompt="...",
        completion="...",
        prompt_tokens=512,
        completion_tokens=128,
        latency_ms=1234.5,
    )
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import traceback
from contextvars import ContextVar
from typing import Any, Dict, Optional

logger = logging.getLogger("langfuse_tracer")

# One-time notices (avoid spamming console)
_logged_disabled_once = False
_logged_missing_keys_once = False


def _console_logs_on() -> bool:
    """Mirror tracing to stdout when true (default: on). Set LANGFUSE_CONSOLE_LOG=false to disable."""
    v = (os.getenv("LANGFUSE_CONSOLE_LOG") or "true").strip().lower()
    return v not in ("0", "false", "no", "off")


def _lf_console(msg: str) -> None:
    """Guaranteed console line (uvicorn log level independent)."""
    if not _console_logs_on():
        return
    line = f"[Langfuse] {msg}"
    print(line, file=sys.stdout, flush=True)
    try:
        logger.info(line)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Context storage — dual-layer for maximum compatibility
#
# Layer 1: contextvars.ContextVar  — works across asyncio tasks and any thread
#   that was spawned via asyncio.run_in_executor (which copies the context).
# Layer 2: threading.local fallback — covers plain threading.Thread workers
#   that do NOT inherit ContextVar (e.g. sync agent calls from thread pools
#   that were created before set_langfuse_context was called).
# ---------------------------------------------------------------------------

_ctx_user_id: ContextVar[str] = ContextVar("langfuse_user_id", default="")
_ctx_session_id: ContextVar[str] = ContextVar("langfuse_session_id", default="")
_ctx_agent_name: ContextVar[str] = ContextVar("langfuse_agent_name", default="")

_tl = threading.local()  # thread-local fallback storage


def _tl_get(key: str, default: str = "") -> str:
    return getattr(_tl, key, default)


def _tl_set(key: str, value: str) -> None:
    setattr(_tl, key, value)


def _read_user_id() -> str:
    return _ctx_user_id.get() or _tl_get("user_id")


def _read_session_id() -> str:
    return _ctx_session_id.get() or _tl_get("session_id")


def _read_agent_name() -> str:
    return _ctx_agent_name.get() or _tl_get("agent_name") or "unknown"


def set_langfuse_context(
    *,
    user_id: str = "",
    session_id: str = "",
    agent_name: str = "",
) -> None:
    """Bind tracing context to the current execution scope.

    Writes to both ContextVar (propagated to async tasks and run_in_executor
    threads) and thread-local storage (for plain Thread workers).

    Always writes ``user_id`` and ``session_id`` (including empty strings) so
    thread-local fallbacks do not leak values from a previous request on the
    same event-loop thread (common for MCP calls that omit ``user_id``).
    """
    uid = user_id or ""
    sid = session_id or ""
    _ctx_user_id.set(uid)
    _tl_set("user_id", uid)
    _ctx_session_id.set(sid)
    _tl_set("session_id", sid)

    if agent_name:
        _ctx_agent_name.set(agent_name)
        _tl_set("agent_name", agent_name)
    else:
        _ctx_agent_name.set("")
        _tl_set("agent_name", "")


# Compatibility shims — dispatch.py and api.py import these from llm_continuation,
# which now re-exports them from here.

def set_current_agent(name: str) -> None:
    """Update agent_name in both ContextVar and thread-local (compat shim)."""
    if name:
        _ctx_agent_name.set(name)
        _tl_set("agent_name", name)


def set_current_user(user_id: str) -> None:
    """Update user_id in both ContextVar and thread-local (compat shim)."""
    uid = user_id or ""
    _ctx_user_id.set(uid)
    _tl_set("user_id", uid)


def set_current_session(session_id: str) -> None:
    """Update session_id in both ContextVar and thread-local (compat shim)."""
    sid = session_id or ""
    _ctx_session_id.set(sid)
    _tl_set("session_id", sid)


# ---------------------------------------------------------------------------
# Langfuse client — lazy singleton, initialised once on first use
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_langfuse_client: Optional[Any] = None
_client_init_done = False


def _is_enabled() -> bool:
    return os.getenv("LANGFUSE_ENABLED", "").lower() in ("true", "1", "yes")


def _get_client() -> Optional[Any]:
    """Return shared Langfuse client, creating it on first call. Thread-safe."""
    global _langfuse_client, _client_init_done, _logged_missing_keys_once
    if _client_init_done:
        return _langfuse_client
    with _client_lock:
        if _client_init_done:
            return _langfuse_client
        _client_init_done = True
        try:
            from langfuse import Langfuse  # noqa: PLC0415

            public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
            secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
            host = (
                os.getenv("LANGFUSE_BASE_URL", "").strip()
                or os.getenv("LANGFUSE_HOST", "").strip()
                or "https://cloud.langfuse.com"
            )
            if not public_key or not secret_key:
                logger.warning(
                    "[Langfuse] LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set — "
                    "LLM tracing is disabled"
                )
                if not _logged_missing_keys_once:
                    _logged_missing_keys_once = True
                    _lf_console(
                        "client: missing LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY — "
                        "ingestion will not run."
                    )
                return None
            _langfuse_client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            logger.info("[Langfuse] Client ready (host=%s)", host)
            _lf_console(f"client: Langfuse SDK ready (host={host})")
        except ImportError:
            logger.warning(
                "[Langfuse] 'langfuse' package not installed — "
                "LLM tracing is disabled"
            )
            _lf_console("client: python package 'langfuse' not installed — pip install langfuse")
        except Exception as exc:
            logger.warning("[Langfuse] Client init failed: %s", exc, exc_info=True)
            _lf_console(f"client: init failed: {exc!s}")
    return _langfuse_client


def log_langfuse_boot_status() -> None:
    """Print Langfuse configuration once at API startup (call from FastAPI lifespan)."""
    raw_flag = os.getenv("LANGFUSE_ENABLED", "")
    enabled = _is_enabled()
    pk = bool(os.getenv("LANGFUSE_PUBLIC_KEY", "").strip())
    sk = bool(os.getenv("LANGFUSE_SECRET_KEY", "").strip())
    host = (
        os.getenv("LANGFUSE_BASE_URL", "").strip()
        or os.getenv("LANGFUSE_HOST", "").strip()
        or "https://cloud.langfuse.com"
    )
    _lf_console(
        f"boot: LANGFUSE_ENABLED={raw_flag!r} → active={enabled} | "
        f"keys public={pk} secret={sk} | host={host} | "
        f"console_mirror={_console_logs_on()}"
    )
    if not enabled:
        _lf_console(
            "boot: Tracing is OFF. Set LANGFUSE_ENABLED=true (and keys) in server/.env to record LLM calls."
        )
        return
    if not pk or not sk:
        _lf_console(
            "boot: Tracing requested but LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY missing — "
            "no events will be sent."
        )
        return
    client = _get_client()
    if client is None:
        _lf_console("boot: Langfuse client failed to initialize (see warnings above).")
    else:
        _lf_console("boot: Langfuse client initialized OK.")


# ---------------------------------------------------------------------------
# Background push
# ---------------------------------------------------------------------------


def _push_in_background(
    *,
    agent_name: str,
    model: str,
    prompt: str,
    completion: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: float,
    user_id: str,
    session_id: str,
    metadata: Dict[str, Any],
    error: Optional[str],
) -> None:
    """Spawn a daemon thread that pushes one LLM generation to Langfuse.

    The calling thread returns immediately; all Langfuse I/O happens in the
    background using the SDK v4 ingestion batch API.
    """

    def _push() -> None:
        client = _get_client()
        if client is None:
            _lf_console(
                f"ingestion: skipped (no client) agent={agent_name!r} model={model!r} — "
                "check boot lines and LANGFUSE_* env"
            )
            return
        try:
            import datetime
            import uuid

            from langfuse.api.ingestion.types import (
                CreateGenerationBody,
                IngestionEvent_GenerationCreate,
                IngestionEvent_TraceCreate,
                TraceBody,
            )

            now = datetime.datetime.now(datetime.timezone.utc)
            # Back-calculate generation start from measured latency so timing is accurate
            start_time = (
                now - datetime.timedelta(milliseconds=latency_ms)
                if latency_ms > 0
                else now
            )
            now_iso = now.isoformat()
            start_iso = start_time.isoformat()

            trace_id = str(uuid.uuid4())
            gen_id = str(uuid.uuid4())

            # Trace carries the user / session identity
            trace_body = TraceBody(
                id=trace_id,
                name=agent_name,
                user_id=user_id or None,
                session_id=session_id or None,
                metadata=metadata,
                timestamp=start_iso,
            )
            trace_event = IngestionEvent_TraceCreate(
                type="trace-create",
                id=str(uuid.uuid4()),
                timestamp=now_iso,
                body=trace_body,
            )

            # Generation carries model / token / IO details
            gen_meta = {**metadata, "latency_ms": round(latency_ms, 1)}
            gen_body_kwargs: Dict[str, Any] = dict(
                id=gen_id,
                trace_id=trace_id,
                name=f"{agent_name} — LLM call",
                model=model,
                input=prompt[:12_000],
                output=completion[:12_000],
                usage_details={
                    "input": prompt_tokens,
                    "output": completion_tokens,
                    "total": prompt_tokens + completion_tokens,
                },
                metadata=gen_meta,
                start_time=start_iso,
                end_time=now_iso,
            )
            if error:
                gen_body_kwargs["level"] = "ERROR"
                gen_body_kwargs["status_message"] = error

            gen_body = CreateGenerationBody(**gen_body_kwargs)
            gen_event = IngestionEvent_GenerationCreate(
                type="generation-create",
                id=str(uuid.uuid4()),
                timestamp=now_iso,
                body=gen_body,
            )

            client.api.ingestion.batch(batch=[trace_event, gen_event])

            logger.info(
                "[Langfuse] ingestion ok trace_id=%s agent=%s model=%s tokens=%d+%d",
                trace_id,
                agent_name,
                model,
                prompt_tokens,
                completion_tokens,
            )
            _lf_console(
                f"ingestion: OK trace_id={trace_id} agent={agent_name!r} model={model!r} "
                f"tokens in={prompt_tokens} out={completion_tokens}"
            )
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error(
                "[Langfuse] ingestion FAILED agent=%s model=%s: %s\n%s",
                agent_name,
                model,
                exc,
                tb,
            )
            _lf_console(f"ingestion: FAILED agent={agent_name!r} — {exc!s}")
            _lf_console(f"ingestion: traceback:\n{tb}")

    thread = threading.Thread(
        target=_push,
        daemon=True,
        name=f"langfuse-{agent_name[:20]}",
    )
    thread.start()


# ---------------------------------------------------------------------------
# Public tracing API
# ---------------------------------------------------------------------------


def trace_llm_call(
    *,
    model: str,
    prompt: str,
    completion: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: float = 0.0,
    agent_name: Optional[str] = None,
    error: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one LLM completion to Langfuse. Always non-blocking.

    Reads ``user_id``, ``session_id``, and ``agent_name`` from ContextVars that
    were populated by ``set_langfuse_context`` at the API-request entry point.
    Silently no-ops when ``LANGFUSE_ENABLED`` is not ``true``.
    """
    global _logged_disabled_once
    if not _is_enabled():
        if not _logged_disabled_once:
            _logged_disabled_once = True
            raw = os.getenv("LANGFUSE_ENABLED", "")
            logger.warning(
                "[Langfuse] trace_llm_call skipped: LANGFUSE_ENABLED is not true (raw=%r). "
                "Set LANGFUSE_ENABLED=true in server/.env",
                raw,
            )
            _lf_console(
                f"trace_llm_call: SKIPPED (LANGFUSE_ENABLED not true, raw={raw!r}). "
                "No Langfuse events will be recorded until enabled."
            )
        return

    user_id = _read_user_id()
    session_id = _read_session_id()
    resolved_agent = agent_name or _read_agent_name()
    provider = _detect_provider(model)

    metadata: Dict[str, Any] = {
        "agent": resolved_agent,
        "provider": provider,
        "model": model,
        **(extra_metadata or {}),
    }

    logger.info(
        "[Langfuse] Queuing generation — agent=%s model=%s user=%s "
        "tokens=%d+%d latency=%.0fms",
        resolved_agent,
        model,
        user_id or "anonymous",
        prompt_tokens,
        completion_tokens,
        latency_ms,
    )
    _lf_console(
        f"trace_llm_call: queue agent={resolved_agent!r} model={model!r} "
        f"user={user_id or '(none)'} session={session_id or '(none)'} "
        f"tokens={prompt_tokens}+{completion_tokens} latency_ms={latency_ms:.0f}"
    )

    _push_in_background(
        agent_name=resolved_agent,
        model=model,
        prompt=prompt,
        completion=completion,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
        error=error,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_provider(model: str) -> str:
    m = model.lower()
    if "gemini" in m or "vertex_ai" in m:
        return "pwc_genai_gemini"
    if "anthropic" in m or "claude" in m:
        return "pwc_genai_claude"
    if "deepseek" in m or "llama" in m or "mistral" in m or "phi" in m:
        return "local_llm"
    if "ollama" in m:
        return "ollama"
    return "pwc_genai"
