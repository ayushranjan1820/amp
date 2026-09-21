#!/usr/bin/env python3
"""
MCP (Model Context Protocol) Server — exposes agents from agents_catalog.json
as callable tools in Cursor / VS Code.

**Remote HTTP (recommended when the API is already running)**  
Point Cursor ``mcp.json`` at the Streamable HTTP endpoint (same origin as the API):

- ``http://localhost:<port>/mcp`` (local)
- ``https://<your-domain>/mcp`` (production)

Cursor uses GET/POST/DELETE on that URL. Do **not** use ``/mcp/sse`` as the primary URL unless you rely on legacy SSE only; the root ``/mcp`` path matches what Cursor expects for Streamable HTTP.

Optional JSON in header ``X-Marketplace-Agent-Env`` (remote): include ``AGENTS_API_BASE`` and agent credentials. When ``MCP_ALLOWED_AGENT_IDS`` is set (comma-separated or JSON array), only those catalog ids are listed and invocable; otherwise every active agent is exposed.

**Stdio (standalone process)**  
Run: ``python mcp_server.py``  
Configure Cursor with the stdio command transport and put env vars in ``mcp.json`` ``env``.

Requirements: pip install "mcp[cli]" httpx
"""

import json
import sys
import os
import re
import asyncio
import base64
import binascii
import logging
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from mcp_codebase_context import (
    jira_codebase_context_template,
    missing_jira_codebase_context_sections,
)
from user_config import (
    apply_auto_llm_provider_for_mcp,
    get_agent_display_name_by_id,
    get_catalog_env_keys_for_agent,
)

_mcp_logger = logging.getLogger("mcp.tool_calls")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CATALOG_PATH = SCRIPT_DIR / "agents_catalog.json"
_PORT = os.environ.get("PORT", "8000")
API_BASE = os.environ.get("AGENTS_API_BASE", f"http://localhost:{_PORT}")
_MCP_HTTP_CONNECT_TIMEOUT_SEC = float(os.environ.get("MCP_HTTP_CONNECT_TIMEOUT_SEC", "10"))
_MCP_HTTP_READ_TIMEOUT_SEC = float(os.environ.get("MCP_HTTP_READ_TIMEOUT_SEC", "900"))
_MCP_HTTP_WRITE_TIMEOUT_SEC = float(os.environ.get("MCP_HTTP_WRITE_TIMEOUT_SEC", "30"))
_MCP_HTTP_POOL_TIMEOUT_SEC = float(os.environ.get("MCP_HTTP_POOL_TIMEOUT_SEC", "60"))
REQUEST_TIMEOUT = httpx.Timeout(
    connect=_MCP_HTTP_CONNECT_TIMEOUT_SEC,
    read=_MCP_HTTP_READ_TIMEOUT_SEC,
    write=_MCP_HTTP_WRITE_TIMEOUT_SEC,
    pool=_MCP_HTTP_POOL_TIMEOUT_SEC,
)

# Max wall-clock duration to consume one agent SSE stream through MCP.
# Increase for long-running agents (Jira searches with large context, report generation, etc.).
_MCP_SSE_MAX_DURATION_SEC = float(os.environ.get("MCP_SSE_MAX_DURATION_SEC", "900"))

# Render cap for ticket list entries in MCP text response.
_MCP_RENDER_TICKETS_LIMIT = int(os.environ.get("MCP_RENDER_TICKETS_LIMIT", "200"))

# Shared HTTP client — reuses TCP connections instead of creating one per tool call.
# Closed gracefully via close_http_client() called from api.py lifespan shutdown.
# Pool sized for 1000 concurrent users: each MCP tool_call holds one connection
# while streaming the SSE response (~3-180s). 100 slots balances throughput vs OS limits.
_http_client = httpx.AsyncClient(
    timeout=REQUEST_TIMEOUT,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
)

# Global cap: prevents a single flood from exhausting the backend.
_call_semaphore = asyncio.Semaphore(25)
# Per-session cap: prevents one user from monopolising all global slots.
_SESSION_CONCURRENCY = int(os.environ.get("MCP_SESSION_CONCURRENCY", "3"))
# Bounded LRU dict so memory is capped even if LLM generates unique session_ids per call.
# Max entries = MCP_MAX_SESSIONS * 4 (generous; each Semaphore is ~200 bytes).
_SESSION_SEM_MAX = int(os.environ.get("MCP_MAX_SESSIONS", "500")) * 4
_session_semaphores: OrderedDict[str, asyncio.Semaphore] = OrderedDict()

# Raw codebase_context cap used only when appending context into non-Jira query text.
# Jira create flow keeps codebase_context separate (context_data) and untruncated.
_CODEBASE_CONTEXT_MAX_CHARS = 100_000

# Comma-separated catalog ids or JSON array string; limits tools/calls when non-empty (SSE header or stdio env).
MCP_ALLOWLIST_KEY = "MCP_ALLOWED_AGENT_IDS"

# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

# Headers that catalog-defined external agents are allowed to send.
_SAFE_EXTERNAL_HEADERS: frozenset[str] = frozenset({
    "accept", "content-type", "user-agent", "authorization",
    "x-api-key", "x-auth-token",
})

# Private/loopback IP ranges blocked for external agent URLs (SSRF guard).
_PRIVATE_IP_RE = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|::1$|fc|fd)",
    re.IGNORECASE,
)


def _validate_external_url(url: str) -> str | None:
    """Return an error string if the URL is unsafe, else None."""
    try:
        p = urlparse(url)
    except Exception:
        return "unparseable URL"
    if p.scheme not in ("http", "https"):
        return f"scheme '{p.scheme}' not allowed (use http/https)"
    host = p.hostname or ""
    if not host:
        return "missing hostname"
    if _PRIVATE_IP_RE.match(host):
        return f"host '{host}' resolves to a private/loopback address"
    return None


def _sanitize_external_headers(raw: dict | None) -> dict[str, str]:
    """Strip any headers not in the safe allowlist."""
    if not raw:
        return {}
    return {k: str(v) for k, v in raw.items() if str(k).lower() in _SAFE_EXTERNAL_HEADERS}


def _scrub_creds(text: str, merged_config: dict[str, str]) -> str:
    """Replace credential values in text with *** to prevent log leakage."""
    for v in merged_config.values():
        if v and len(v) > 8:
            text = text.replace(v, "***")
    return text


def _get_session_semaphore(session_id: str | None) -> asyncio.Semaphore:
    """Return the per-session semaphore (LRU-bounded), creating it on first use.

    The dict is capped at _SESSION_SEM_MAX entries. LRU eviction removes the
    least-recently-used entry. In-flight tasks that already hold a reference to
    an evicted semaphore continue to work correctly; only future callers with the
    same key get a fresh semaphore. There is no await between check and insert so
    asyncio's single-threaded model makes this race-free.
    """
    if not session_id:
        return _call_semaphore
    if session_id in _session_semaphores:
        _session_semaphores.move_to_end(session_id)
        return _session_semaphores[session_id]
    sem = asyncio.Semaphore(_SESSION_CONCURRENCY)
    _session_semaphores[session_id] = sem
    if len(_session_semaphores) > _SESSION_SEM_MAX:
        _session_semaphores.popitem(last=False)  # evict LRU
    return sem


# How long a caller waits for a semaphore slot before we return a clean "busy"
# error instead of letting the client's HTTP request time out and disconnect.
_ACQUIRE_TIMEOUT_SEC = float(os.environ.get("MCP_ACQUIRE_TIMEOUT_SEC", "45"))


class _SemaphoreBusyError(Exception):
    """Raised when a semaphore could not be acquired within the timeout."""


@asynccontextmanager
async def _acquire_or_busy(sem: asyncio.Semaphore, label: str):
    """Acquire ``sem`` within _ACQUIRE_TIMEOUT_SEC or raise _SemaphoreBusyError.

    Without a bounded wait, a saturated server leaves callers hanging until the
    client (Cursor / VS Code) aborts the HTTP request — which the user sees as
    a disconnect. With it, we return a clean JSON-RPC error telling them to retry.
    """
    try:
        await asyncio.wait_for(sem.acquire(), timeout=_ACQUIRE_TIMEOUT_SEC)
    except asyncio.TimeoutError:
        raise _SemaphoreBusyError(label)
    try:
        yield
    finally:
        sem.release()


async def close_http_client() -> None:
    """Gracefully close the shared HTTP client. Called from api.py lifespan shutdown."""
    await _http_client.aclose()

# ---------------------------------------------------------------------------
# Load catalog
# ---------------------------------------------------------------------------

with open(CATALOG_PATH, "r", encoding="utf-8") as _f:
    _catalog = json.load(_f)

AGENTS: dict[str, dict] = {a["id"]: a for a in _catalog.get("agents", [])}

# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

server = Server("multi-agent-mcp")


def _get_api_path(agent: dict) -> str | None:
    """Extract the HTTP path (e.g. '/api/jira-agent') from the catalog entry."""
    raw = agent.get("usage", {}).get("api_endpoint", "") or agent.get("api_endpoint", "")
    if not raw:
        return None
    parts = raw.strip().split()
    return parts[-1] if parts else None


def _catalog_credential_hint(agent: dict) -> str:
    """Short text listing env keys from the catalog for tool descriptions."""
    name = agent.get("name") or ""
    keys = get_catalog_env_keys_for_agent(name) if name else []
    if not keys:
        return ""
    preview = ", ".join(keys[:6])
    more = f" (+{len(keys) - 6} more)" if len(keys) > 6 else ""
    return (
        f"\n\nCatalog credentials: {preview}{more}. "
        "URL/SSE: send JSON in HTTP header X-Marketplace-Agent-Env (include AGENTS_API_BASE). "
        "stdio: set the same keys in mcp.json env."
    )


def _env_user_config_for_agent(agent_id: str) -> dict[str, str]:
    """Pick up catalog-listed keys from this process environment (stdio MCP: mcp.json `env`)."""
    display = get_agent_display_name_by_id(agent_id)
    if not display:
        return {}
    out: dict[str, str] = {}
    for key in get_catalog_env_keys_for_agent(display):
        if not key:
            continue
        val = os.environ.get(key)
        if val and isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def _mcp_request_is_http() -> bool:
    """True when this tool call was triggered via SSE/HTTP (not stdio)."""
    try:
        from mcp.server.lowlevel.server import request_ctx

        ctx = request_ctx.get()
        return getattr(ctx, "request", None) is not None
    except LookupError:
        return False


def _parse_marketplace_agent_env_header(raw: str) -> dict[str, str]:
    """Parse X-Marketplace-Agent-Env: plain JSON object or base64url-encoded JSON."""
    raw = (raw or "").strip()
    if not raw:
        return {}
    blob = raw
    if not raw.startswith("{"):
        pad = "=" * ((4 - len(raw) % 4) % 4)
        try:
            blob = base64.urlsafe_b64decode(raw + pad).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return {}
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if k is None or v is None:
            continue
        ks = str(k).strip()
        if not ks:
            continue
        vs = str(v).strip()
        if vs:
            out[ks] = vs
    return out


def _ide_credentials_from_http_request() -> dict[str, str]:
    """Credentials supplied by the IDE for this HTTP MCP session (header only)."""
    try:
        from mcp.server.lowlevel.server import request_ctx

        ctx = request_ctx.get()
        req = getattr(ctx, "request", None)
        if req is None:
            return {}
        # Starlette: headers are case-insensitive
        raw = req.headers.get("x-marketplace-agent-env") or req.headers.get("X-Marketplace-Agent-Env")
        if not raw:
            return {}
        return _parse_marketplace_agent_env_header(raw)
    except LookupError:
        return {}


def _parse_allowed_agent_ids_raw(raw: str) -> set[str] | None:
    """Return allowed catalog agent ids, or None if unset / empty (no restriction)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(arr, list):
            return None
        out = {str(x).strip() for x in arr if x is not None and str(x).strip()}
        return out or None
    out = {x.strip() for x in raw.split(",") if x.strip()}
    return out or None


def _allowed_agent_ids_for_session() -> set[str] | None:
    """Restrict MCP tools when MCP_ALLOWED_AGENT_IDS is set (HTTP header JSON or stdio env)."""
    if _mcp_request_is_http():
        creds = _ide_credentials_from_http_request()
        return _parse_allowed_agent_ids_raw(creds.get(MCP_ALLOWLIST_KEY, ""))
    return _parse_allowed_agent_ids_raw(os.environ.get(MCP_ALLOWLIST_KEY, ""))


def _normalize_user_config(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k is None:
            continue
        ks = str(k).strip()
        if not ks or v is None:
            continue
        vs = str(v).strip()
        if vs:
            out[ks] = vs
    return out


def _merge_user_config(agent_id: str, from_tool: dict[str, str]) -> dict[str, str]:
    """Merge credential layers. Tool arguments always win.

    - **HTTP / SSE MCP** (in-process): use **only** ``X-Marketplace-Agent-Env`` on the POST
      request plus ``user_config`` from the tool call. Server ``os.environ`` / ``.env`` is
      **not** used for agent credentials (avoids leaking the host's JIRA keys to every IDE).
    - **stdio MCP** (subprocess): use catalog keys from **this process** ``os.environ``
      (Cursor/VS Code inject ``mcp.json`` ``env`` here) plus tool ``user_config``.
    """
    if _mcp_request_is_http():
        base = _ide_credentials_from_http_request()
    else:
        base = _env_user_config_for_agent(agent_id)
    return {**base, **from_tool}


# Agents that benefit from receiving codebase context from the IDE.
# Only these get the `codebase_context` parameter (required) in their MCP schema.
_CODEBASE_CONTEXT_AGENT_IDS: frozenset[str] = frozenset({
    "jira_agent",          # ticket creation is far better with actual code references
    "brd_generation",      # BRDs need to describe real components
    "bpmn_generator",      # process flows derived from code structure
    "unit_test_agent",     # must see the source code to generate tests
    "code_sandbox",        # code execution/analysis
    "claude_code",         # coding agent (also has workspace_root/context_files)
    "workspace_coding",    # workspace context agent (also has workspace_root/context_files)
    "github_repo",         # repo operations benefit from local context
    "trace_debugger",      # debugging needs code context
    "shannon_security",    # security analysis of code
    "web_test_agent",      # test generation for the app
    "browser_agent",       # browser automation needs to know the app
    "codex_sdlc",         # SDLC orchestration depends on repository context
})


def _build_input_schema(agent: dict) -> dict:
    """Build a JSON-Schema for the tool's input parameters."""
    properties: dict[str, Any] = {
        "query": {
            "type": "string",
            "description": (
                "The user's question or instruction for this agent. "
                "Keep this focused on WHAT the user wants done."
            ),
        },
        "session_id": {
            "type": "string",
            "description": "Optional session ID to maintain conversation context across calls.",
        },
        "user_config": {
            "type": "object",
            "description": (
                "Optional per-call credentials (catalog env keys). Overrides IDE-provided config. "
                "For URL/SSE MCP, set credentials on HTTP header X-Marketplace-Agent-Env (JSON or base64 JSON); "
                "for stdio MCP, use mcp.json env block."
            ),
            # Allow any JSON type — strict string-only additionalProperties caused some
            # clients to fail SDK jsonschema validation before our handler ran.
            "additionalProperties": True,
        },
    }
    required: list[str] = ["query"]
    aid = agent.get("id") or ""

    # Jira agent has strict prompt validation in API layer.
    if aid == "jira_agent":
        properties["query"]["maxLength"] = 4000
        properties["query"]["description"] = (
            "The user intent/instruction for Jira. Keep this concise (max 4000 chars). "
            "Put large repository details, file trees, and code snippets in `codebase_context`, "
            "not in `query`."
        )

    # Only code-aware agents get the codebase_context parameter.
    if aid in _CODEBASE_CONTEXT_AGENT_IDS:
        properties["codebase_context"] = {
            "type": "string",
            "description": (
                "REQUIRED — You MUST always populate this field before calling this tool. "
                "Gather relevant context from the user's open workspace and include it here. "
                "Steps: (1) List the project directory tree (top 2-3 levels). "
                "(2) Read files that are relevant to the user's request — e.g. if they mention "
                "'login feature', read the auth/login source files; if they say 'App Guide page', "
                "read the App Guide component files. "
                "(3) Format each file as '--- path/to/file.ext ---' followed by its content. "
                "If no specific files are referenced, include the project tree and README. "
                "This context is critical — without it the agent produces generic results. Max ~100KB."
            ),
        }
        if aid == "jira_agent":
            properties["codebase_context"]["description"] = (
                "REQUIRED for jira_agent. Include enough implementation context to create a high-quality ticket. "
                "Must include these sections: File and Folder Related, Current Project Validation Rules, "
                "Tech Stack Summary, UI Guidelines, Other Relevant Info. "
                "Keep large details here (not in query). For jira_agent, the create flow stores this value "
                "verbatim in the ticket description; LLM extraction should use the query only. "
                "No character-limit truncation is applied for Jira create flow at MCP layer.\n\n"
                + jira_codebase_context_template()
            )
        required.append("codebase_context")
    if aid == "webmcp_agent":
        properties["bridge_base_url"] = {
            "type": "string",
            "description": "Local WebMCP bridge base URL (required), e.g. http://127.0.0.1:3847",
        }
        properties["bridge_token"] = {
            "type": "string",
            "description": "Bearer token from the bridge server / Chrome extension (required).",
        }
        properties["clear_history"] = {
            "type": "boolean",
            "description": "Clear server-side session memory for this session_id.",
        }
        required.extend(["bridge_base_url", "bridge_token"])
    if aid in ("claude_code", "workspace_coding", "codex_sdlc"):
        root_desc = (
            "Absolute path to the project root on the machine where the agents API runs "
            "(often the same PC as the IDE)."
        )
        if aid == "claude_code":
            root_desc += (
                " Claude Code CLI uses this as the working directory for local projects; "
                "omit when only cloning from GitHub."
            )
        else:
            root_desc += (
                " Pass on the first call per session_id (or whenever you change projects). "
                "Code is generated/edited with your configured LLM_PROVIDER (no clone/push)."
            )
        properties["workspace_root"] = {"type": "string", "description": root_desc}
        properties["context_files"] = {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Optional paths to read and inject into the prompt. Use paths relative to workspace_root, "
                "or absolute paths that still lie under workspace_root. Max ~40 files, ~200KB each."
            ),
        }
    if aid == "codex_sdlc":
        properties["dry_run"] = {
            "type": "boolean",
            "description": "Preview changes without writing to disk when true.",
        }
        properties["create_pr"] = {
            "type": "boolean",
            "description": "Generate a pull request payload after a successful run.",
        }
        properties["max_retries"] = {
            "type": "integer",
            "description": "Maximum retry attempts for validation failures per executable step.",
        }
        properties["target_coverage"] = {
            "type": "integer",
            "description": "Optional target coverage percentage for coverage-improvement requests.",
        }
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ---- list_tools ----------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    tools: list[Tool] = []
    allowed = _allowed_agent_ids_for_session()
    for agent in _catalog.get("agents", []):
        if agent.get("status") != "active":
            continue
        aid = agent.get("id")
        if allowed is not None and aid not in allowed:
            continue
        path = _get_api_path(agent)
        if not path and not agent.get("external_api_url"):
            continue

        examples = agent.get("usage", {}).get("example_prompts", [])
        example_block = ""
        if examples:
            example_block = "\n\nExample prompts:\n" + "\n".join(f"  - {e}" for e in examples[:4])

        caps = agent.get("capabilities", [])
        caps_block = ""
        if caps:
            caps_block = "\n\nCapabilities: " + ", ".join(caps[:8])

        context_hint = ""
        if aid in _CODEBASE_CONTEXT_AGENT_IDS:
            context_hint = (
                "\n\n** BEFORE calling this tool: You MUST read relevant files from the user's "
                "workspace and pass them in the `codebase_context` parameter. "
                "Include the project directory structure and any source files related to the request. "
                "For example, if the user says 'create a ticket for adding dob field on App Guide page', "
                "you must first find and read the App Guide page source files, then include that code "
                "in `codebase_context`. Without this context, results will be generic and unhelpful. **"
            )

        tools.append(
            Tool(
                name=agent["id"],
                description=(
                    f"{agent['name']} — {agent.get('type', 'Agent')}\n"
                    f"{agent['description']}"
                    f"{caps_block}{example_block}"
                    f"{context_hint}"
                    f"{_catalog_credential_hint(agent)}"
                ),
                inputSchema=_build_input_schema(agent),
            )
        )
    return tools


# ---- SSE helpers ---------------------------------------------------------

async def _consume_sse(response: httpx.Response) -> dict[str, Any]:
    """Read the full SSE stream and return the final result dict.

    Capped by MCP_SSE_MAX_DURATION_SEC so a backend that never sends a "done"
    event cannot block a semaphore slot forever.
    """
    final: dict[str, Any] = {}
    chunks: list[str] = []

    try:
        async with asyncio.timeout(_MCP_SSE_MAX_DURATION_SEC):
            async for raw_line in response.aiter_lines():
                line = raw_line.strip()
                if not line.startswith("data: "):
                    continue
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    _mcp_logger.debug("SSE: skipping non-JSON line: %.120s", line)
                    continue

                event = payload.get("event")
                data = payload.get("data", {})

                if event == "done":
                    final = data if isinstance(data, dict) else {"response": str(data)}
                elif event == "response_chunk":
                    chunk = data.get("chunk", "") if isinstance(data, dict) else str(data)
                    chunks.append(chunk)
                elif event == "error":
                    msg = data.get("message", "Unknown error") if isinstance(data, dict) else str(data)
                    return {"success": False, "response": f"Error: {msg}"}
    except asyncio.TimeoutError:
        _mcp_logger.warning(
            "SSE stream exceeded %.1f s limit; returning partial result",
            _MCP_SSE_MAX_DURATION_SEC,
        )
        if chunks:
            return {
                "success": True,
                "response": (
                    "".join(chunks)
                    + "\n\n[Response truncated: stream timeout "
                    + f"({_MCP_SSE_MAX_DURATION_SEC:.0f}s)]"
                ),
            }
        return {"success": False, "response": "Agent response timed out (stream never completed)."}
    except Exception as stream_err:
        _mcp_logger.error("SSE stream read failed: %s", stream_err)
        if final:
            return final
        if chunks:
            return {"success": True, "response": "".join(chunks)}
        return {"success": False, "response": f"Stream interrupted: {type(stream_err).__name__}"}

    if final:
        return final
    if chunks:
        return {"success": True, "response": "".join(chunks)}
    return {"success": False, "response": "No response received from agent."}


def _format_result(result: dict, agent: dict) -> str:
    """Turn the agent result dict into readable Markdown text."""
    parts: list[str] = []

    response = result.get("response", "")
    if response:
        parts.append(str(response))

    tickets = result.get("tickets") or []
    if tickets:
        parts.append(f"\n\n**Tickets ({len(tickets)}):**")
        for t in tickets[:_MCP_RENDER_TICKETS_LIMIT]:
            key = t.get("key", "?")
            summary = t.get("summary", "No summary")
            status = t.get("status", "?")
            parts.append(f"- **{key}** — {summary} `{status}`")
        if len(tickets) > _MCP_RENDER_TICKETS_LIMIT:
            parts.append(
                f"- ... and {len(tickets) - _MCP_RENDER_TICKETS_LIMIT} more "
                "(increase MCP_RENDER_TICKETS_LIMIT to show more)"
            )

    chart = result.get("chart_data") or {}
    summary = chart.get("summary") or {}
    if summary:
        parts.append(
            f"\n\n**Project Analytics:**  "
            f"Total {summary.get('total', 0)} | "
            f"Open {summary.get('open', 0)} | "
            f"In Progress {summary.get('in_progress', 0)} | "
            f"Done {summary.get('done', 0)} | "
            f"Unassigned {summary.get('unassigned', 0)}"
        )

    dl = result.get("download_url")
    if dl:
        full = dl if dl.startswith("http") else f"{API_BASE}{dl}"
        parts.append(f"\n**Download:** {full}")

    bpmn = result.get("bpmn_xml")
    if bpmn:
        parts.append("\n\n<details><summary>BPMN XML</summary>\n\n```xml\n" + bpmn[:3000] + "\n```\n</details>")

    # ── SQL DB Agent: pagination, EXPLAIN warnings, cache status ──
    if result.get("cached"):
        parts.append("\n\n> _Cached result (identical query within 5-min TTL)._")

    page_info = result.get("page_info")
    if page_info and isinstance(page_info, dict):
        p = page_info
        parts.append(
            f"\n\n**Page {p.get('page', 1)} of {p.get('total_pages', 1)}** "
            f"({p.get('total_rows', 0)} total rows, {p.get('page_size', 500)} per page)"
        )
        if p.get("has_next"):
            parts.append(f"  _Use `page: {p['page'] + 1}` to see the next page._")

    explain_warnings = result.get("explain_warnings") or []
    if explain_warnings:
        parts.append("\n\n**Performance Warnings:**")
        for ew in explain_warnings:
            if isinstance(ew, dict):
                parts.append(f"- Step {ew.get('step', '?')}: {ew.get('warning', 'unknown')}")
                scans = ew.get("seq_scans") or []
                if scans:
                    parts.append(f"  - Sequential scans on: {', '.join(scans)}")

    if not parts:
        return "Agent completed but returned no content."

    return "\n".join(parts)


# ---- call_tool -----------------------------------------------------------

@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    allowed = _allowed_agent_ids_for_session()
    if allowed is not None and name not in allowed:
        _mcp_logger.warning("Blocked call to agent not in allowlist: %s", name)
        return [
            TextContent(
                type="text",
                text=(
                    f"Agent `{name}` is not in your MCP allowlist (`{MCP_ALLOWLIST_KEY}`). "
                    "Update your IDE MCP header or env to include this id, or remove the allowlist to expose every agent."
                ),
            )
        ]

    agent = AGENTS.get(name)
    if not agent:
        _mcp_logger.warning("call_tool: unknown agent '%s'", name)
        return [TextContent(type="text", text=f"Unknown agent: {name}")]

    query = arguments.get("query", "")
    codebase_context = str(arguments.get("codebase_context") or "")
    session_id = arguments.get("session_id")
    tool_user_config = _normalize_user_config(arguments.get("user_config"))
    merged_config = _merge_user_config(name, tool_user_config)
    merged_config = apply_auto_llm_provider_for_mcp(merged_config, agent)

    if name == "jira_agent":
        missing = missing_jira_codebase_context_sections(codebase_context)
        if missing:
            return [
                TextContent(
                    type="text",
                    text=(
                        "jira_agent requires a richer `codebase_context`. Missing sections: "
                        + ", ".join(missing)
                        + "\n\n"
                        + jira_codebase_context_template()
                    ),
                )
            ]

    # Append codebase context for non-Jira agents. Jira receives it in context_data to
    # avoid exceeding Jira's 4000-char prompt validation limit.
    if codebase_context and name != "jira_agent":
        query = (
            f"{query}\n\n[Codebase Context]\n{codebase_context[:_CODEBASE_CONTEXT_MAX_CHARS]}\n"
            f"[End Codebase Context]"
        )

    _mcp_logger.info(
        "tool_call agent=%s session=%s query_len=%d",
        name,
        (session_id or "none")[:16],
        len(query),
    )

    # External-API agents (proxied through a third-party URL)
    if agent.get("external_api_url"):
        return await _call_external(agent, query, session_id)

    path = _get_api_path(agent)
    if not path:
        return [TextContent(type="text", text=f"No API endpoint configured for {agent['name']}.")]

    api_base = (merged_config.get("AGENTS_API_BASE") or API_BASE).rstrip("/")
    url = f"{api_base}{path}"
    payload: dict[str, Any] = {"query": query}
    if session_id:
        payload["session_id"] = session_id
    if name == "jira_agent" and codebase_context:
        payload["context_data"] = {"codebase_context": codebase_context}
    if name == "webmcp_agent":
        bu = str(arguments.get("bridge_base_url") or "").strip()
        bt = str(arguments.get("bridge_token") or "").strip()
        if not bu or not bt:
            return [
                TextContent(
                    type="text",
                    text=(
                        "**webmcp_agent** requires non-empty **bridge_base_url** and **bridge_token** in the tool "
                        "arguments (same values as in the web UI)."
                    ),
                )
            ]
        payload["bridge_base_url"] = bu
        payload["bridge_token"] = bt
        if "clear_history" in arguments:
            payload["clear_history"] = bool(arguments.get("clear_history"))
        if arguments.get("allowed_hosts") is not None:
            payload["allowed_hosts"] = arguments.get("allowed_hosts")
        if arguments.get("require_host_allowlist") is not None:
            payload["require_host_allowlist"] = bool(arguments.get("require_host_allowlist"))
        for num_key in ("max_steps", "bridge_timeout_sec", "wall_time_sec"):
            if arguments.get(num_key) is not None:
                payload[num_key] = arguments.get(num_key)
    if name in ("claude_code", "workspace_coding", "codex_sdlc"):
        wr = str(arguments.get("workspace_root") or "").strip()
        if wr:
            payload["workspace_root"] = wr
        cf = arguments.get("context_files")
        if isinstance(cf, list) and cf:
            payload["context_files"] = [str(x).strip() for x in cf if str(x).strip()]
    if name == "codex_sdlc":
        for key in ("dry_run", "create_pr", "max_retries", "target_coverage"):
            if arguments.get(key) is not None:
                payload[key] = arguments.get(key)
    # API user_config: strip MCP-only keys (routing / tool discovery, not agent env)
    cfg_for_api = {
        k: v
        for k, v in merged_config.items()
        if k not in ("AGENTS_API_BASE", MCP_ALLOWLIST_KEY)
    }
    if cfg_for_api:
        payload["user_config"] = cfg_for_api

    if _mcp_request_is_http() and not _ide_credentials_from_http_request() and not tool_user_config:
        need = get_catalog_env_keys_for_agent(agent.get("name") or "")
        if need:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"**{agent['name']}** requires credentials, but none were sent for this URL/SSE connection.\n\n"
                        "With `url` MCP transport, `mcp.json` `env` is **not** applied to the server. "
                        "Send a JSON object in the HTTP header **`X-Marketplace-Agent-Env`** (same keys as catalog), "
                        "or use **stdio** MCP (`command` + `args` + `env`) so your IDE env is used.\n\n"
                        f"Example header value (plain JSON): `{{\"AGENTS_API_BASE\":\"http://localhost:8000\","
                        f'\"{need[0]}\":\"…\"}}`\n\n'
                        "You can also pass `user_config` on each tool call."
                    ),
                )
            ]

    # Phase 3: Retry with exponential backoff for transient failures.
    _MAX_RETRIES = 3
    _RETRYABLE_STATUSES = {429, 503}

    try:
        # Bounded acquire: per-session slot first, then global slot. If either is
        # saturated we return a clean "busy" message instead of letting the client
        # HTTP request time out and appear as a disconnect.
        async with _acquire_or_busy(_get_session_semaphore(session_id), "per-session"):
            async with _acquire_or_busy(_call_semaphore, "global"):
                last_err = None
                for _attempt in range(_MAX_RETRIES):
                    try:
                        # X-Internal header lets BackpressureMiddleware exempt MCP loopback
                        headers = {"X-Internal": "mcp"}
                        async with _http_client.stream("POST", url, json=payload, headers=headers) as resp:
                            if resp.status_code in _RETRYABLE_STATUSES and _attempt < _MAX_RETRIES - 1:
                                _mcp_logger.warning(
                                    "agent=%s attempt=%d status=%d — retrying",
                                    name, _attempt + 1, resp.status_code,
                                )
                                await asyncio.sleep(2 ** _attempt)  # 1s, 2s
                                continue
                            if resp.status_code != 200:
                                body = (await resp.aread()).decode(errors="replace")[:500]
                                _mcp_logger.error("agent=%s http_status=%d", name, resp.status_code)
                                return [TextContent(type="text", text=f"API error ({resp.status_code}): {body}")]
                            result = await _consume_sse(resp)
                        break  # success
                    except httpx.ConnectError as ce:
                        last_err = ce
                        if _attempt < _MAX_RETRIES - 1:
                            _mcp_logger.warning("agent=%s connect error attempt=%d — retrying", name, _attempt + 1)
                            await asyncio.sleep(2 ** _attempt)
                        else:
                            return [
                                TextContent(
                                    type="text",
                                    text=(
                                        f"Cannot connect to the agents server at {API_BASE} after {_MAX_RETRIES} attempts.\n"
                                        "Make sure the FastAPI server is running:  python api.py"
                                    ),
                                )
                            ]
    except _SemaphoreBusyError as busy:
        _mcp_logger.warning(
            "tool_call busy agent=%s session=%s slot=%s",
            name, (session_id or "none")[:16], busy,
        )
        return [TextContent(
            type="text",
            text=(
                f"Server is temporarily at capacity ({busy} queue full after "
                f"{int(_ACQUIRE_TIMEOUT_SEC)} s). Please retry in a few seconds."
            ),
        )]
    except asyncio.CancelledError:
        # Client disconnected mid-call — propagate so Starlette/uvicorn cleans up.
        _mcp_logger.info("tool_call cancelled (client disconnect) agent=%s", name)
        raise
    except Exception as exc:
        # Scrub credential values before they reach logs or the caller.
        safe_msg = _scrub_creds(str(exc), merged_config)
        _mcp_logger.error("tool_call failed agent=%s error=%s", name, safe_msg)
        return [TextContent(type="text", text=f"Error calling {agent['name']}: {safe_msg}")]

    _mcp_logger.info("tool_call done agent=%s session=%s", name, (session_id or "none")[:16])
    text = _format_result(result, agent)
    return [TextContent(type="text", text=text)]


async def _call_external(agent: dict, query: str, session_id: str | None) -> list[TextContent]:
    """Handle agents that proxy to an external URL."""
    url = agent["external_api_url"]

    # SSRF guard: reject private/loopback destinations.
    url_err = _validate_external_url(url)
    if url_err:
        _mcp_logger.error("external agent '%s' has unsafe URL: %s", agent.get("id"), url_err)
        return [TextContent(type="text", text=f"External agent configuration error: {url_err}")]

    method = agent.get("external_method", "POST").upper()
    payload_format = agent.get("external_payload_format", "json")
    # Only forward safe headers to prevent header injection.
    headers = _sanitize_external_headers(agent.get("external_headers"))

    template = agent.get("external_payload_template", '{"prompt":"{{query}}"}')
    # Use safe substitution via explicit JSON encoding to avoid template injection.
    body_str = template.replace("{{query}}", json.dumps(query)).replace(
        "{{session_id}}", json.dumps(session_id or "")
    )

    try:
        body = json.loads(body_str)
    except json.JSONDecodeError:
        body = {"prompt": query}

    try:
        # Bounded per-session + global acquire (same pattern as internal agents).
        async with _acquire_or_busy(_get_session_semaphore(session_id), "per-session"):
            async with _acquire_or_busy(_call_semaphore, "global"):
                normalized_format = str(payload_format or "json").lower().replace("-", "_")
                if normalized_format in {"form", "form_data", "multipart", "multipart_form_data"}:
                    form_body = body if isinstance(body, dict) else {"value": body}
                    form_fields = {}
                    for key, value in form_body.items():
                        form_fields[str(key)] = (
                            None if value is None else (
                                json.dumps(value, separators=(",", ":"))
                                if isinstance(value, (dict, list)) else str(value)
                            )
                        )
                    headers = {
                        key: value for key, value in headers.items()
                        if key.lower() != "content-type"
                    }
                    resp = await _http_client.request(
                        method, url, files={key: (None, value or "") for key, value in form_fields.items()},
                        headers=headers,
                    )
                else:
                    resp = await _http_client.request(method, url, json=body, headers=headers)
                data = resp.json()
                text = data.get("response") or data.get("answer") or json.dumps(data, indent=2)
                return [TextContent(type="text", text=text)]
    except _SemaphoreBusyError as busy:
        _mcp_logger.warning("external agent '%s' busy (%s)", agent.get("id"), busy)
        return [TextContent(
            type="text",
            text=f"Server temporarily at capacity ({busy} queue). Please retry.",
        )]
    except asyncio.CancelledError:
        _mcp_logger.info("external agent '%s' cancelled (client disconnect)", agent.get("id"))
        raise
    except Exception as exc:
        _mcp_logger.error("external agent '%s' call failed: %s", agent.get("id"), exc)
        return [TextContent(type="text", text=f"Error calling external agent: {type(exc).__name__}")]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
