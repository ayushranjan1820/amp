import asyncio
import json
import logging
import os
import time
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from mcp_server import server as _mcp_server

_sse_transport = SseServerTransport("/messages/")

_logger = logging.getLogger("mcp_sse")

# Hard cap on concurrent sessions. Each session holds an in-memory task + buffers;
# unbounded growth enables OOM attacks. Tune via MCP_MAX_SESSIONS env var.
_MAX_SESSIONS = int(os.environ.get("MCP_MAX_SESSIONS", "500"))

# Idle timeout: a session is considered abandoned if no request has touched it
# for this many seconds. The SDK has NO built-in idle timeout, so without this,
# sessions survive forever when Cursor closes/crashes without sending DELETE /mcp.
# The sweeper runs every _IDLE_SWEEP_INTERVAL seconds.
_SESSION_IDLE_TIMEOUT_SEC = int(os.environ.get("MCP_SESSION_IDLE_TIMEOUT_SEC", "1800"))  # 30 min
_IDLE_SWEEP_INTERVAL = int(os.environ.get("MCP_SESSION_SWEEP_INTERVAL_SEC", "300"))  # 5 min

# session_id → last-active UNIX timestamp. Updated inside _handle_stateful_request.
_session_last_active: dict[str, float] = {}


async def _send_json_error(send: Send, http_status: int, code: int, message: str) -> None:
    """Send a minimal JSON-RPC error response and close the HTTP exchange."""
    body = json.dumps(
        {"jsonrpc": "2.0", "id": None, "error": {"code": code, "message": message}},
        separators=(",", ":"),
    ).encode()
    await send({
        "type": "http.response.start",
        "status": http_status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


# Cap how much of the request body we will buffer to inspect the JSON-RPC
# method. Real `initialize` payloads are <2 KB; this guard prevents a malicious
# client from forcing us to load an arbitrarily large body into memory just to
# decide whether to run the stale-session recovery path.
_INITIALIZE_PEEK_MAX_BYTES = 64 * 1024


async def _buffer_body_then_replay(
    receive: Receive,
) -> tuple[bytes, Receive, bool]:
    """Drain the request body into memory and return (body, replay_receive, truncated).

    ``replay_receive`` re-emits the buffered body as one ``http.request`` message,
    then forwards every later message from the original ``receive`` (e.g. the
    eventual ``http.disconnect``). If the body exceeds ``_INITIALIZE_PEEK_MAX_BYTES``
    we stop buffering and stream the *remaining* chunks straight from the original
    receive on replay so we never hold a giant body in memory.
    """
    buffered = bytearray()
    truncated = False
    pending_tail: list[dict[str, Any]] = []
    while True:
        msg = await receive()
        if msg.get("type") != "http.request":
            pending_tail.append(msg)
            break
        chunk = msg.get("body") or b""
        if not truncated:
            if len(buffered) + len(chunk) > _INITIALIZE_PEEK_MAX_BYTES:
                truncated = True
                pending_tail.append({
                    "type": "http.request",
                    "body": chunk,
                    "more_body": bool(msg.get("more_body", False)),
                })
            else:
                buffered.extend(chunk)
        else:
            pending_tail.append({
                "type": "http.request",
                "body": chunk,
                "more_body": bool(msg.get("more_body", False)),
            })
        if not msg.get("more_body", False):
            break

    body = bytes(buffered)
    replayed = False
    tail_iter = iter(pending_tail)
    tail_done = False

    async def replay() -> dict[str, Any]:
        nonlocal replayed, tail_done
        if not replayed:
            replayed = True
            return {
                "type": "http.request",
                "body": body,
                # If we had to truncate, more chunks follow from the original receive.
                "more_body": truncated or bool(pending_tail),
            }
        if not tail_done:
            try:
                return next(tail_iter)
            except StopIteration:
                tail_done = True
        return await receive()

    return body, replay, truncated


def _peek_jsonrpc_method(body: bytes) -> str | None:
    """Return the ``method`` of the first JSON-RPC message in ``body``, or None."""
    if not body:
        return None
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        m = data.get("method")
        return m if isinstance(m, str) else None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            m = first.get("method")
            return m if isinstance(m, str) else None
    return None


class ResilientStreamableHTTPSessionManager(StreamableHTTPSessionManager):
    """Stateful Streamable HTTP with stale-session recovery, session cap, idle tracking.

    1. **Stale-session recovery**: when an unknown ``mcp-session-id`` header arrives
       on an ``initialize`` request (the typical pattern after the server restarts
       or Cursor caches a session id across reloads), the header is stripped and the
       SDK creates a fresh session — returning a clean 200 instead of a 404 the
       client never recovers from. For non-initialize requests with an unknown id we
       still return 404 because that is the only safe answer.
    2. **Session cap**: rejects new-session requests when ``_MAX_SESSIONS`` is reached
       with HTTP 429 / JSON-RPC -32000 to prevent OOM under load.
    3. **Idle tracking**: records last-active timestamp per session so the sweeper
       can terminate abandoned sessions (Cursor closed without DELETE /mcp).
    """

    async def _handle_stateful_request(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") == "http":
            headers = list(scope.get("headers") or [])
            sid_hdr = MCP_SESSION_ID_HEADER.lower().encode("ascii")
            current: str | None = None
            sid_idx: int | None = None
            for i, (k, v) in enumerate(headers):
                if k.lower() == sid_hdr:
                    try:
                        current = v.decode("latin-1")
                    except UnicodeDecodeError:
                        current = None
                    sid_idx = i
                    break

            if current is not None and current not in self._server_instances:
                # Unknown session id. Two recovery paths:
                #   (a) The client is starting fresh (POST /mcp with method=initialize)
                #       but is sending a stale id from a previous server lifetime.
                #       Strip the header and let the SDK create a new session, so the
                #       very first reconnect succeeds without manual intervention.
                #   (b) Anything else (tools/list, tools/call, GET, DELETE, …) — we
                #       can't safely answer without an initialized session, so return
                #       404 and let the client kick off a fresh `initialize`.
                method = scope.get("method", "").upper()
                recover = False
                rebuilt_receive: Receive = receive
                if method == "POST":
                    # Only POST carries a JSON-RPC body; other verbs cannot be initialize.
                    body, rebuilt_receive, _truncated = await _buffer_body_then_replay(receive)
                    if _peek_jsonrpc_method(body) == "initialize":
                        recover = True

                if recover and sid_idx is not None:
                    _logger.info(
                        "MCP: stale mcp-session-id with initialize; stripping header "
                        "to allow fresh session (was prefix=%s)",
                        (current[:12] + "...") if len(current) > 12 else current,
                    )
                    _session_last_active.pop(current, None)
                    new_headers = headers[:sid_idx] + headers[sid_idx + 1:]
                    new_scope = {**scope, "headers": new_headers}
                    # Apply the same session-cap guard we apply below for brand-new
                    # sessions, since we are about to create one.
                    if len(self._server_instances) >= _MAX_SESSIONS:
                        _logger.warning(
                            "MCP: session cap reached (%d/%d); rejecting recovery init",
                            len(self._server_instances),
                            _MAX_SESSIONS,
                        )
                        await _send_json_error(
                            send, 429, -32000,
                            f"Server at capacity ({_MAX_SESSIONS} active sessions). Try again later.",
                        )
                        return
                    await super()._handle_stateful_request(new_scope, rebuilt_receive, send)
                    if scope.get("type") == "http":
                        now = time.time()
                        for sid in self._server_instances:
                            _session_last_active.setdefault(sid, now)
                    return

                _logger.info(
                    "MCP: unknown mcp-session-id (restart/reload?); returning 404 so "
                    "client re-initializes (dropped id prefix=%s)",
                    (current[:12] + "...") if len(current) > 12 else current,
                )
                _session_last_active.pop(current, None)
                # Return HTTP 404 — the MCP spec signal for "session not found".
                # Clients (Cursor, VS Code, etc.) handle 404 by creating a fresh
                # session (starting with `initialize`).  The old approach of
                # stripping the header caused the SDK to create a new transport
                # for a non-initialize request, which then failed with
                # "Missing session ID".
                await _send_json_error(
                    send, 404, -32600,
                    "Not Found: Session expired or server restarted. Please reconnect.",
                )
                return

            # Enforce session cap only for new-session requests (no valid session ID).
            if current is None and len(self._server_instances) >= _MAX_SESSIONS:
                _logger.warning(
                    "MCP: session cap reached (%d/%d); rejecting new session",
                    len(self._server_instances),
                    _MAX_SESSIONS,
                )
                await _send_json_error(
                    send, 429, -32000,
                    f"Server at capacity ({_MAX_SESSIONS} active sessions). Try again later.",
                )
                return

            # Record activity for this session (existing or about-to-be-created).
            if current is not None:
                _session_last_active[current] = time.time()

        await super()._handle_stateful_request(scope, receive, send)

        # After the handler runs, if a new session was created, record it.
        # The SDK assigns mcp_session_id during handle_request — look it up by scanning.
        if scope.get("type") == "http":
            now = time.time()
            for sid in self._server_instances:
                _session_last_active.setdefault(sid, now)


async def _idle_session_sweeper(manager: "ResilientStreamableHTTPSessionManager") -> None:
    """Background task: terminate sessions idle longer than _SESSION_IDLE_TIMEOUT_SEC.

    Runs every _IDLE_SWEEP_INTERVAL seconds. Cancelled automatically by the
    lifespan context manager on shutdown.
    """
    _logger.info(
        "MCP idle-session sweeper started (timeout=%ds, interval=%ds)",
        _SESSION_IDLE_TIMEOUT_SEC,
        _IDLE_SWEEP_INTERVAL,
    )
    try:
        while True:
            await asyncio.sleep(_IDLE_SWEEP_INTERVAL)
            now = time.time()
            # Snapshot keys so we can mutate during iteration.
            to_terminate: list[str] = []
            for sid, last in list(_session_last_active.items()):
                if sid not in manager._server_instances:
                    # Already gone; purge tracking entry.
                    _session_last_active.pop(sid, None)
                    continue
                if now - last > _SESSION_IDLE_TIMEOUT_SEC:
                    to_terminate.append(sid)

            for sid in to_terminate:
                transport = manager._server_instances.get(sid)
                if transport is None:
                    _session_last_active.pop(sid, None)
                    continue
                try:
                    await transport.terminate()
                    _logger.info(
                        "MCP: terminated idle session %s (idle %.0fs)",
                        (sid[:12] + "...") if len(sid) > 12 else sid,
                        now - _session_last_active.get(sid, now),
                    )
                except Exception as exc:
                    _logger.warning("MCP: idle session terminate failed sid=%s: %s", sid[:12], exc)
                finally:
                    _session_last_active.pop(sid, None)
    except asyncio.CancelledError:
        _logger.info("MCP idle-session sweeper stopping.")
        raise


# Cursor uses Streamable HTTP (POST) on the configured URL; use https://host/mcp (api normalizes
# bare /mcp → /mcp/ so Mount matches). Legacy SSE: GET https://host/mcp/sse + POST …/mcp/messages/?…
#
# **Multi-instance / App Engine:** Streamable HTTP sessions live in process memory. If the load
# balancer sends the next POST to a different instance, ``mcp-session-id`` is unknown → 404
# ("Session expired or server restarted"). Set ``MCP_STREAMABLE_STATELESS=1`` so each POST is
# handled by a fresh transport with ``ServerSession(stateless=True)`` (no sticky sessions).
# Trade-off: slightly more work per request; benefit: works with autoscaling. Alternatively keep
# stateful mode and run **max_instances: 1** (or enable instance affinity) on App Engine.
_STREAMABLE_STATELESS = (os.environ.get("MCP_STREAMABLE_STATELESS") or "").strip().lower() in (
    "1", "true", "yes", "on",
)
if _STREAMABLE_STATELESS:
    _logger.info(
        "MCP_STREAMABLE_STATELESS=1 — streamable HTTP uses stateless mode (safe behind multi-instance LB)."
    )

streamable_session_manager = ResilientStreamableHTTPSessionManager(
    app=_mcp_server,
    event_store=None,
    json_response=False,
    stateless=_STREAMABLE_STATELESS,
)


class _StreamableHttpAsgi:
    """Delegates to StreamableHTTPSessionManager (same pattern as FastMCP's StreamableHTTPASGIApp)."""

    def __init__(self, session_manager: StreamableHTTPSessionManager):
        self._session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._session_manager.handle_request(scope, receive, send)


_streamable_http_asgi = _StreamableHttpAsgi(streamable_session_manager)


class _McpSseAsgiApp:
    """Raw ASGI app for GET /mcp/sse (not ``async def(request)`` — avoids request_response wrapper)."""

    def __init__(self, transport: SseServerTransport, mcp_server):
        self._transport = transport
        self._mcp_server = mcp_server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        async with self._transport.connect_sse(scope, receive, send) as (read_stream, write_stream):
            await self._mcp_server.run(
                read_stream,
                write_stream,
                self._mcp_server.create_initialization_options(),
            )


_mcp_sse_asgi = _McpSseAsgiApp(_sse_transport, _mcp_server)


class _McpJsonRpcCompatAsgi:
    """Pure-ASGI middleware that normalises JSON-RPC bodies before the MCP SDK parses them.

    JSON-RPC **notifications** must not include an ``id``. Some clients (including some
    Cursor builds) send ``notifications/initialized`` with an ``id`` field. The message
    is then parsed as a **request**, but ``ClientRequest`` has no such method → SDK
    returns ``-32602 Invalid request parameters``.

    We strip ``id`` from any message whose ``method`` starts with ``notifications/`` by
    wrapping the ASGI ``receive`` callable — the only reliable interception point.
    ``BaseHTTPMiddleware`` ignores body modifications because it calls
    ``self.app(scope, original_receive, …)`` regardless of the ``Request`` object
    passed to ``call_next``.

    Optional: set ``MCP_LOG_JSONRPC_COMPAT=1`` to log when this runs.
    """

    _PREFIX = "notifications/"

    def __init__(self, app: Any) -> None:
        self._app = app

    def _normalize(self, data: Any) -> tuple[Any, bool]:
        changed = False
        if isinstance(data, dict):
            m = data.get("method")
            if isinstance(m, str) and m.startswith(self._PREFIX) and "id" in data:
                data = {k: v for k, v in data.items() if k != "id"}
                changed = True
            return data, changed
        if isinstance(data, list):
            out: list[Any] = []
            for item in data:
                ni, c = self._normalize(item)
                out.append(ni)
                changed = changed or c
            return out, changed
        return data, False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method", "").upper() != "POST":
            await self._app(scope, receive, send)
            return

        ct = ""
        for k, v in scope.get("headers", []):
            if k.lower() == b"content-type":
                ct = v.decode("latin-1", errors="replace").lower()
                break
        if "application/json" not in ct:
            await self._app(scope, receive, send)
            return

        # Wrap receive: intercept the first http.request message and patch the body.
        _patched = False
        _original: dict[str, Any] = {}

        async def patched_receive() -> dict[str, Any]:
            nonlocal _patched, _original
            msg = await receive()
            if msg.get("type") != "http.request" or _patched:
                return msg
            _patched = True
            _original = msg
            body: bytes = msg.get("body", b"") or b""
            if not body.strip():
                return msg
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                return msg
            fixed, changed = self._normalize(parsed)
            if not changed:
                return msg
            if (os.getenv("MCP_LOG_JSONRPC_COMPAT") or "").strip().lower() in (
                "1",
                "true",
                "yes",
            ):
                _logger.info("MCP JSON-RPC compat: stripped id from notification-shaped message(s)")
            new_body = json.dumps(fixed, separators=(",", ":")).encode("utf-8")
            return {**msg, "body": new_body, "more_body": False}

        await self._app(scope, patched_receive, send)


class _SseImmediateFlushAsgi:
    """Force upstream proxies to flush SSE response headers immediately.

    Symptom: behind Google Frontend (App Engine / Cloud Run), Cloudflare, and
    some CDNs, the long-lived ``GET /mcp`` SSE channel returns headers to the
    client only after the *first body byte* arrives from the backend. The MCP
    SDK's GET handler is silent until either a server-initiated notification
    is pushed or sse_starlette's keepalive ping fires (default 15 seconds).
    Result: Cursor's MCP client opens GET /mcp, sees nothing for 15 s, and
    its UI is stuck on "Loading tools..." even though POST initialize and
    POST tools/list have already succeeded.

    Workaround: as soon as the inner app sends ``http.response.start`` for any
    ``text/event-stream`` response, follow it with a single SSE *comment* line
    (``: ok\\r\\n\\r\\n``). The comment is ignored by SSE clients per the spec
    but is a body byte from the proxy's perspective, so the proxy flushes the
    headers + comment to the client immediately. Subsequent body events stream
    through unchanged.

    Override the comment payload via ``MCP_SSE_FLUSH_COMMENT`` (rarely needed).
    Disable entirely with ``MCP_SSE_FLUSH_DISABLE=1`` if a downstream consumer
    is intolerant of unsolicited comment lines.
    """

    _SSE_FLUSH_BYTES = (
        os.environ.get("MCP_SSE_FLUSH_COMMENT", ": ok").encode("utf-8") + b"\r\n\r\n"
    )
    _DISABLED = (os.environ.get("MCP_SSE_FLUSH_DISABLE") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._DISABLED or scope.get("type") != "http":
            await self._app(scope, receive, send)
            return

        flushed = False

        async def wrapped_send(msg: Any) -> None:
            nonlocal flushed
            if msg.get("type") == "http.response.start" and not flushed:
                is_sse = False
                for k, v in msg.get("headers") or []:
                    if k.lower() == b"content-type":
                        if b"text/event-stream" in v.lower():
                            is_sse = True
                        break
                await send(msg)
                if is_sse:
                    await send({
                        "type": "http.response.body",
                        "body": self._SSE_FLUSH_BYTES,
                        "more_body": True,
                    })
                    flushed = True
                return
            await send(msg)

        await self._app(scope, receive, wrapped_send)


_inner_mcp_starlette = Starlette(
    debug=False,
    routes=[
        Route("/sse", endpoint=_mcp_sse_asgi, methods=["GET"]),
        Mount("/messages/", app=_sse_transport.handle_post_message),
        Route("/", endpoint=_streamable_http_asgi, methods=["GET", "POST", "DELETE"]),
    ],
)

# Wrap with pure-ASGI compat middleware (body patching requires wrapping `receive` directly;
# Starlette's BaseHTTPMiddleware calls self.app with the original receive and ignores any
# Request object you pass to call_next, so BaseHTTPMiddleware cannot modify request bodies).
# Also wrap with _SseImmediateFlushAsgi so SSE response headers reach the client without
# waiting for upstream proxies (Google Frontend, Cloudflare, …) to forward the first
# 15-second sse_starlette keepalive ping — which made deployed MCP appear to hang
# on "Loading tools…" even though every POST returned 200 in <1 second.
mcp_starlette_app = _McpJsonRpcCompatAsgi(_SseImmediateFlushAsgi(_inner_mcp_starlette))
