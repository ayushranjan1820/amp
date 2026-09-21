"""
FastAPI server to expose agents via SSE-streaming APIs.
All agent endpoints return Server-Sent Events for progressive UI updates.
"""
import sys
import os
import json
import uuid
import asyncio
import httpx
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect
from pydantic import BaseModel, Field, field_validator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime
import logging
import queue
import threading
import contextvars
from typing import Dict, List, Optional, Any

# Add paths to sys.path for imports
base_path = Path(__file__).parent
sys.path.insert(0, str(base_path))

# Frontend build output paths (used by static-file serving routes)
frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
frontend_public = Path(__file__).resolve().parent.parent / "frontend" / "public"

from user_config import (
    apply_auto_llm_provider_for_mcp,
    apply_user_config,
    apply_user_config_concurrent,
    get_catalog_agent_by_display_name,
    merge_configs,
    merge_configs_for_agent_id,
    get_catalog_env_keys_for_agent,
    load_dotenv_then_scrub_pwc,
    with_server_config_status,
)
from agents_catalog_db import (
    CatalogNotFoundError,
    async_get_catalog,
    async_save_catalog,
    get_agent_by_id,
    init_agents_catalog_db,
)
from agents.local_llm import normalize_ollama_cloud_api_token
from agents.llm_activity_stream import (
    register_llm_sse_bridge,
    reset_llm_activity_loop,
    reset_llm_activity_queue,
    set_llm_activity_loop,
    set_llm_activity_queue,
    unregister_llm_sse_bridge,
)

# Capture PwC GenAI credentials from .env before they are scrubbed.
# Used as server-side defaults for callers that send no user_config (e.g. scripts).
from dotenv import dotenv_values as _dotenv_values
_env_file = Path(__file__).parent / ".env"
_env_file_vals = _dotenv_values(_env_file) if _env_file.exists() else {}
_SERVER_GLOBAL_CHAT_CONFIG: dict = {
    k: v for k, v in _env_file_vals.items()
    if k in ("PWC_GENAI_API_KEY", "PWC_GENAI_BEARER_TOKEN", "PWC_GENAI_ENDPOINT_URL", "LLM_PROVIDER", "PREMIUM_MODEL")
    and v
}
del _dotenv_values, _env_file, _env_file_vals

# Load server .env for non-agent secrets; PWC GenAI keys are stripped (agent config only).
load_dotenv_then_scrub_pwc()

# Signal to agent modules that the API server manages config injection per-request;
# prevents module-level load_dotenv_then_scrub_pwc from wiping injected PwC keys.
import os as _os
_os.environ["_AGENTSERVER_RUNNING"] = "1"


# ---------------------------------------------------------------------------
# Phase 3: Global LLM concurrency semaphore
# ---------------------------------------------------------------------------
# Caps the total number of concurrent LLM calls across ALL agents. Prevents one
# burst of traffic from exhausting rate limits or starving other requests.
_LLM_SEMAPHORE_LIMIT = int(_os.getenv("LLM_SEMAPHORE_LIMIT", "50"))
LLM_SEMAPHORE = asyncio.Semaphore(_LLM_SEMAPHORE_LIMIT)

# Phase 1: Agent-level overall timeout (seconds). Prevents stuck agents from
# holding a session lock (and LLM semaphore slot) forever.
AGENT_STREAM_TIMEOUT_SEC = float(_os.getenv("AGENT_STREAM_TIMEOUT_SEC", "3000"))
# PPT pipeline (planner + parallel search per slide + per-slide LLM + images + build)
# routinely exceeds the global default; use a separate ceiling unless overridden.
# Compact providers (Ollama Cloud / local) are slower per call — keep the
# ceiling generous so a 10–14-slide deck completes even at ~60s per LLM call.
PPT_AGENT_STREAM_TIMEOUT_SEC = float(_os.getenv("PPT_AGENT_STREAM_TIMEOUT_SEC", "1800"))
JIRA_AGENT_STREAM_TIMEOUT_SEC = float(_os.getenv("JIRA_AGENT_STREAM_TIMEOUT_SEC", "900"))


def _effective_agent_stream_timeout_sec(agent_name: str) -> float:
    if agent_name == "PPT Generator Agent":
        return PPT_AGENT_STREAM_TIMEOUT_SEC
    if agent_name == "JIRA Agent":
        return JIRA_AGENT_STREAM_TIMEOUT_SEC
    return AGENT_STREAM_TIMEOUT_SEC

# Session storage for conversation contexts
from agents.safe_session_store import SafeSessionStore
conversation_sessions_store = SafeSessionStore(max_sessions=1000, ttl_seconds=3600)
# Ephemeral full-document HTML for shareable preview links (Coder agent standalone HTML, etc.)
_standalone_html_preview_store = SafeSessionStore(
    max_sessions=int(_os.getenv("STANDALONE_HTML_PREVIEW_MAX_ITEMS", "400")),
    ttl_seconds=int(_os.getenv("STANDALONE_HTML_PREVIEW_TTL_SEC", str(7 * 24 * 3600))),
)
_STANDALONE_HTML_PREVIEW_MAX_BYTES = int(_os.getenv("STANDALONE_HTML_PREVIEW_MAX_KB", "768")) * 1024
# Legacy alias — new code should use conversation_sessions_store
conversation_sessions: Dict[str, any] = {}

# Agent runs mutate global os.environ per-agent catalog keys; serialize per agent name so
# different agent types run concurrently while same-agent calls don't interleave credentials.
_agent_locks: Dict[str, asyncio.Lock] = {}

def _agent_lock(agent_name: str) -> asyncio.Lock:
    if agent_name not in _agent_locks:
        _agent_locks[agent_name] = asyncio.Lock()
    return _agent_locks[agent_name]

# Per-session locks: prevent two concurrent requests to the same session from racing.
# Different sessions run fully in parallel even for the same agent type.
_session_locks: Dict[str, asyncio.Lock] = {}
_session_locks_meta_lock = asyncio.Lock()

async def _session_lock(session_id: str) -> asyncio.Lock:
    """Return (or create) an asyncio.Lock scoped to a specific session_id.
    
    This allows concurrent requests to DIFFERENT sessions of the SAME agent type.
    Only requests to the SAME session are serialized (to prevent conversation 
    history corruption).
    """
    if session_id not in _session_locks:
        async with _session_locks_meta_lock:
            if session_id not in _session_locks:
                _session_locks[session_id] = asyncio.Lock()
    return _session_locks[session_id]

# Import models (lightweight - no heavy dependencies)
from agents.Basic_agent.models import BasicAgentRequest, BasicAgentResponse
from agents.JIRA_agent.models import JIRAAgentRequest, JIRAAgentResponse
from agents.BRD_generation.models import BRDAgentRequest, BRDAgentResponse
from agents.RBI_circular_agent.models import RBIAgentRequest, RBIAgentResponse
from agents.SEBI_circular_agent.models import SEBIAgentRequest, SEBIAgentResponse
from agents.BPMN_generator_agent.models import BPMNAgentRequest, BPMNAgentResponse
from agents.Market_research_agent.models import MarketResearchRequest, MarketResearchResponse
from agents.Company_research_agent.models import CompanyResearchRequest, CompanyResearchResponse
from agents.Company_solution_agent.models import CompanySolutionRequest, CompanySolutionResponse
from agents.GitHub_repo_agent.models import GitHubRepoRequest, GitHubRepoResponse
from agents.Sonarqube_agent.models import SonarqubeRequest
from agents.Unit_test_agent.models import UnitTestRequest, UnitTestResponse, TaskStatusResponse
from agents.QA_automation_agent.models import QAAutomationRequest, QAAutomationResponse
from agents.Code_sandbox_agent.models import SandboxRequest, SandboxResponse
from agents.Web_test_agent.models import (
    WebTestPlaywrightRunRequest,
    WebTestPlaywrightRunResponse,
    WebTestRequest,
    WebTestResponse,
)
from agents.Shannon_security_agent.models import ShannonSecurityRequest, ShannonSecurityResponse
from agents.MongoDB_RAG_agent.models import MongoRAGChatRequest, MongoRAGChatResponse
from agents.SQL_DB_agent.models import SqlDbChatRequest
from agents.Browser_agent.models import BrowserChatRequest
from agents.WebMCP_agent.models import WebMcpChatRequest
from agents.Meeting_prep_agent.models import MeetingPrepRequest, MeetingPrepResponse
from agents.Email_agent.models import EmailAgentRequest, EmailAgentResponse
from agents.Trace_debugger_agent.models import TraceDebuggerRequest, TraceDebuggerResponse
from agents.Document_formatter_agent.models import DocumentFormatterRequest, DocumentFormatterResponse
from agents.PPT_generator_agent.models import PPTGeneratorRequest, PPTGeneratorResponse
from agents.Router_agent.models import GlobalChatRequest, GlobalChatResponse
from agents.Web_search_agent.models import WebSearchRequest, WebSearchResponse
from agents.Codex_sdlc_agent.models import CodexSDLCRequest, CodexSDLCResponse
from agents.Coder_agent.models import CoderAgentRequest, CoderAgentResponse
from agents.Zoho_workflow_agents.models import ZohoWorkflowRequest
from agents.Codex_sdlc_agent.services.preflight_service import run_codex_sdlc_preflight
import chat_db
import admin_auth
import cost_tracker
import usage_tracker

# Lazy agent loader - defers heavy imports until first use for fast server startup
_agent_cache = {}

def _get_agent(name):
    if name in _agent_cache:
        return _agent_cache[name]

    if name == "basic_agent":
        from agents.Basic_agent.agent import basic_agent as inst
    elif name == "jira_agent":
        from agents.JIRA_agent.jira_agent import jira_agent as inst
    elif name == "brd_agent":
        from agents.BRD_generation.agent import BRDGenerationAgent
        inst = BRDGenerationAgent()
    elif name == "rbi_agent":
        from agents.RBI_circular_agent.agent import rbi_agent as inst
    elif name == "sebi_agent":
        from agents.SEBI_circular_agent.agent import sebi_agent as inst
    elif name == "bpmn_agent":
        from agents.BPMN_generator_agent.agent import bpmn_agent as inst
    elif name == "market_research_agent":
        from agents.Market_research_agent.agent import MarketResearchAgent
        inst = MarketResearchAgent()
    elif name == "company_research_agent":
        from agents.Company_research_agent.agent import company_research_agent as inst
    elif name == "company_solution_agent":
        from agents.Company_solution_agent.agent import company_solution_agent as inst
    elif name == "github_repo_agent":
        from agents.GitHub_repo_agent.agent import github_repo_agent as inst
    elif name == "sonarqube_agent":
        from agents.Sonarqube_agent.agent import sonarqube_agent as inst
    elif name == "unit_test_agent":
        from agents.Unit_test_agent.agent import unit_test_agent as inst
    elif name == "qa_automation_agent":
        from agents.QA_automation_agent.agent import qa_automation_agent as inst
    elif name == "code_sandbox_agent":
        from agents.Code_sandbox_agent.agent import code_sandbox_agent as inst
    elif name == "web_test_agent":
        from agents.Web_test_agent.agent import web_test_agent as inst
    elif name == "shannon_security_agent":
        from agents.Shannon_security_agent.agent import shannon_security_agent as inst
    elif name == "mongodb_rag_agent":
        from agents.MongoDB_RAG_agent.agent import mongodb_rag_agent as inst
    elif name == "sql_db_agent":
        from agents.SQL_DB_agent.agent import sql_db_agent as inst
    elif name == "meeting_prep_agent":
        from agents.Meeting_prep_agent.agent import meeting_prep_agent as inst
    elif name == "email_agent":
        from agents.Email_agent.agent import email_agent as inst
    elif name == "zoho_email_meeting_agent":
        from agents.Zoho_workflow_agents.email_meeting_agent import zoho_email_meeting_agent as inst
    elif name == "zoho_support_ticket_agent":
        from agents.Zoho_workflow_agents.support_ticket_agent import zoho_support_ticket_agent as inst
    elif name == "zoho_new_customer_agent":
        from agents.Zoho_workflow_agents.new_customer_agent import zoho_new_customer_agent as inst
    elif name == "trace_debugger_agent":
        from agents.Trace_debugger_agent.agent import trace_debugger_agent as inst
    elif name == "document_formatter_agent":
        from agents.Document_formatter_agent.agent import document_formatter_agent as inst
    elif name == "ppt_generator_agent":
        from agents.PPT_generator_agent.agent import ppt_generator_agent as inst
    elif name == "claude_code_agent":
        from agents.Claude_code_agent.agent import claude_code_agent as inst
    elif name == "workspace_coding_agent":
        from agents.Workspace_coding_agent.agent import workspace_coding_agent as inst
    elif name == "coder_agent":
        from agents.Coder_agent.agent import coder_agent as inst
    elif name == "codex_sdlc_agent":
        from agents.Codex_sdlc_agent.agent import codex_sdlc_agent as inst
    elif name == "router_agent":
        from agents.Router_agent.agent import router_agent as inst
    elif name == "web_search_agent":
        from agents.Web_search_agent.agent import web_search_agent as inst
    elif name == "browser_agent":
        from agents.Browser_agent.agent import browser_agent as inst
    elif name == "webmcp_agent":
        from agents.WebMCP_agent.agent import webmcp_agent as inst
    elif name == "conversation_manager":
        from agents.JIRA_agent.conversation_manager import ConversationContext, ConversationManager
        inst = (ConversationContext, ConversationManager)
    elif name == "set_current_agent":
        from agents.llm_continuation import set_current_agent as inst
    else:
        from dynamic_agent_runtime import dynamic_runtime
        dyn = dynamic_runtime.load_agent(name)
        if dyn is not None:
            inst = dyn
        else:
            raise ValueError(f"Unknown agent: {name}")

    _agent_cache[name] = inst
    return inst


# ===================== SSE Streaming Helpers =====================

def _format_sse(event: str, data: dict) -> str:
    """Format a single Server-Sent Event line."""
    return f"data: {json.dumps({'event': event, 'data': data}, default=str)}\n\n"


def _chunk_text(text: str, target_size: int = 100) -> list:
    """Split response text into natural chunks for progressive streaming."""
    if not text:
        return []
    paragraphs = text.split('\n\n')
    chunks = []
    for i, para in enumerate(paragraphs):
        suffix = '\n\n' if i < len(paragraphs) - 1 else ''
        if len(para) <= target_size:
            chunks.append(para + suffix)
        else:
            lines = para.split('\n')
            buf = []
            buf_len = 0
            for line in lines:
                buf.append(line)
                buf_len += len(line) + 1
                if buf_len >= target_size:
                    chunks.append('\n'.join(buf) + '\n')
                    buf = []
                    buf_len = 0
            if buf:
                chunks.append('\n'.join(buf) + suffix)
    return chunks or [text]


async def _merge_async_generator_with_llm_queue(agent_gen, llm_queue: asyncio.Queue):
    """Interleave LLM trace steps (async queue) with items from an async agent generator.

    Yields:
      ``("llm", step_dict)`` — push to thinking trace / SSE
      ``("agent", item)`` — same shapes as the agent generator (event dict or final payload)
    """
    agen = agent_gen.__aiter__()
    ag_task = asyncio.create_task(agen.__anext__())
    q_task = asyncio.create_task(llm_queue.get())
    try:
        while True:
            done, _ = await asyncio.wait(
                {ag_task, q_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if q_task in done:
                step = q_task.result()
                yield "llm", step
                q_task = asyncio.create_task(llm_queue.get())
            if ag_task in done:
                try:
                    item = ag_task.result()
                except StopAsyncIteration:
                    break
                yield "agent", item
                ag_task = asyncio.create_task(agen.__anext__())
    finally:
        ag_task.cancel()
        q_task.cancel()
        try:
            await ag_task
        except BaseException:
            pass
        try:
            await q_task
        except BaseException:
            pass
        while True:
            try:
                step = llm_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            yield "llm", step


async def _stream_agent_response(agent_name: str, process_fn, user_config=None,
                                  session_id=None, user_id=None, input_text=None,
                                  request: Optional[Request] = None):
    """Generic SSE streaming wrapper for any agent endpoint.

    Yields events: start, thinking, progress, routing, response_chunk, done, error.

    ``process_fn`` can be:
    1. A regular/async function returning a dict — thinking steps + response chunked.
    2. An async generator yielding SSE event dicts in real-time. Each yielded
       dict should have ``event`` ('thinking'|'progress'|'response_chunk'|'routing')
       and ``data``. The final yield should be the complete result dict (no 'event'
       key) which becomes the 'done' payload.
    """
    # Fall back to server-level PwC credentials captured from .env before scrub.
    # Without this, agents whose endpoint doesn't explicitly pass _SERVER_GLOBAL_CHAT_CONFIG
    # would fail the credential check (keys are stripped from os.environ at startup).
    if user_config is None and _SERVER_GLOBAL_CHAT_CONFIG:
        user_config = _SERVER_GLOBAL_CHAT_CONFIG

    # Bind Langfuse context immediately — before any await / lock so the
    # ContextVar is set in the outer async task that run_in_executor will copy.
    try:
        from langfuse_tracer import set_langfuse_context
        set_langfuse_context(
            user_id=user_id or "",
            session_id=session_id or "",
            agent_name=agent_name,
        )
    except Exception as _lf_ctx_exc:
        _api_log.warning(
            "Langfuse set_langfuse_context failed (agent=%r): %s",
            agent_name,
            _lf_ctx_exc,
            exc_info=True,
        )

    async def event_stream():
        # Re-bind here so context is set on the same async generator task that runs
        # the agent (covers edge cases where the route handler task differs from the
        # streaming task) and after any thread-local leakage from other requests.
        try:
            from langfuse_tracer import set_langfuse_context as _lf_bind
            _lf_bind(
                user_id=user_id or "",
                session_id=session_id or "",
                agent_name=agent_name,
            )
        except Exception as _lf_ctx2_exc:
            _api_log.warning(
                "Langfuse context re-bind failed (agent=%r): %s",
                agent_name,
                _lf_ctx2_exc,
                exc_info=True,
            )
        yield _format_sse('start', {'agent': agent_name, 'timestamp': datetime.now().isoformat()})
        await asyncio.sleep(0)

        try:
            # Phase 3: acquire the global LLM semaphore — limits total concurrent LLM calls
            # across all agents. Acquired BEFORE session lock so a stuck session doesn't
            # hold a semaphore slot while queuing behind another request.
            async with LLM_SEMAPHORE:
                # Per-session lock: only serialize requests to the SAME session.
                # Different sessions (even for the same agent type) run fully concurrently.
                _sess_lock = await _session_lock(session_id or agent_name)
                async with _sess_lock:
                    _effective_config = merge_configs(agent_name, user_config)
                    _effective_config = apply_auto_llm_provider_for_mcp(
                        _effective_config,
                        get_catalog_agent_by_display_name(agent_name),
                    )
                    _isolate_env = bool(get_catalog_env_keys_for_agent(agent_name))
                    with apply_user_config_concurrent(
                        _effective_config,
                        agent_cache=_agent_cache,
                        agent_display_name=agent_name,
                        isolate_catalog_environment=_isolate_env,
                    ):
                        is_generator = hasattr(process_fn, '__aiter__')
                        llm_q = asyncio.Queue()
                        _run_loop = asyncio.get_running_loop()
                        llm_tok = set_llm_activity_queue(llm_q)
                        llm_loop_tok = set_llm_activity_loop(_run_loop)
                        bridge_tok, bridge_id = register_llm_sse_bridge(_run_loop, llm_q)
                        collected_thinking: List = []
                        final_result = None
                        emit_reset_before_final = False
                        result: dict = {}
                        defer_llm_trace_until_after_agent_steps = agent_name == "PPT Generator Agent"
                        deferred_llm_thinking: List = []

                        try:
                            merged = None
                            if is_generator:
                                merged = _merge_async_generator_with_llm_queue(process_fn, llm_q)
                            elif asyncio.iscoroutinefunction(process_fn):

                                async def _async_fn_single_yield():
                                    r = await process_fn()
                                    yield r

                                merged = _merge_async_generator_with_llm_queue(_async_fn_single_yield(), llm_q)

                            if merged is not None:
                                _stream_start = asyncio.get_event_loop().time()
                                _stream_limit = _effective_agent_stream_timeout_sec(agent_name)
                                async for branch, payload in merged:
                                    # Phase 1: enforce overall agent timeout
                                    if (asyncio.get_event_loop().time() - _stream_start) > _stream_limit:
                                        yield _format_sse(
                                            'error',
                                            {'message': f'Agent timed out after {int(_stream_limit)}s'},
                                        )
                                        break
                                    # Phase 3: SSE disconnect detection — stop processing if client left
                                    if request is not None and await request.is_disconnected():
                                        _api_log.info("SSE client disconnected, stopping agent=%s session=%s", agent_name, session_id)
                                        break
                                    if branch == 'llm':
                                        s = payload if isinstance(payload, dict) else {'type': 'info', 'content': str(payload)}
                                        if defer_llm_trace_until_after_agent_steps:
                                            deferred_llm_thinking.append(s)
                                        else:
                                            collected_thinking.append(s)
                                            yield _format_sse('thinking', s)
                                            await asyncio.sleep(0.02)
                                    else:
                                        item = payload
                                        if isinstance(item, dict) and 'event' in item:
                                            evt_type = item['event']
                                            evt_data = item.get('data', {})
                                            if evt_type == 'thinking':
                                                step = evt_data if isinstance(evt_data, dict) else {'type': 'info', 'content': str(evt_data)}
                                                collected_thinking.append(step)
                                                yield _format_sse('thinking', step)
                                            elif evt_type == 'progress':
                                                yield _format_sse('progress', evt_data)
                                                collected_thinking.append({
                                                    'type': 'thinking',
                                                    'content': (
                                                        (evt_data.get('message') or evt_data.get('stage') or 'Progress')
                                                        if isinstance(evt_data, dict)
                                                        else str(evt_data)
                                                    ),
                                                    'tool_name': None,
                                                    'tool_input': None,
                                                })
                                            elif evt_type == 'routing':
                                                yield _format_sse('routing', evt_data)
                                            elif evt_type == 'response_chunk':
                                                yield _format_sse('response_chunk', evt_data if isinstance(evt_data, dict) else {'chunk': str(evt_data)})
                                            else:
                                                yield _format_sse(evt_type, evt_data)
                                            await asyncio.sleep(0.02)
                                        else:
                                            final_result = item

                                result = _normalize_result(final_result)
                                emit_reset_before_final = bool(
                                    result.pop("_emit_reset_before_response_chunks", False)
                                )

                                extra_thinking = result.pop('thinking_steps', []) or []

                                def _trace_step_key(s: dict) -> tuple:
                                    return (
                                        s.get('type'),
                                        s.get('tool_name'),
                                        (s.get('content') or '')[:240],
                                    )

                                _seen_trace_keys = {_trace_step_key(s) for s in collected_thinking if isinstance(s, dict)}
                                for step in extra_thinking:
                                    s = step if isinstance(step, dict) else {'type': 'info', 'content': str(step)}
                                    if not isinstance(s, dict):
                                        continue
                                    tk = _trace_step_key(s)
                                    if tk in _seen_trace_keys:
                                        continue
                                    _seen_trace_keys.add(tk)
                                    collected_thinking.append(s)
                                    yield _format_sse('thinking', s)
                                    await asyncio.sleep(0.02)
                                if defer_llm_trace_until_after_agent_steps:
                                    for s in deferred_llm_thinking:
                                        collected_thinking.append(s)
                                        yield _format_sse('thinking', s)
                                        await asyncio.sleep(0.02)
                            else:
                                raw = await asyncio.to_thread(process_fn)
                                result = _normalize_result(raw)
                                emit_reset_before_final = bool(
                                    result.pop("_emit_reset_before_response_chunks", False)
                                )
                                collected_thinking = []
                                thinking_steps = result.pop('thinking_steps', []) or []
                                for step in thinking_steps:
                                    s = step if isinstance(step, dict) else {'type': 'info', 'content': str(step)}
                                    collected_thinking.append(s)
                                    yield _format_sse('thinking', s)
                                    await asyncio.sleep(0.04)
                        finally:
                            reset_llm_activity_queue(llm_tok)
                            reset_llm_activity_loop(llm_loop_tok)
                            unregister_llm_sse_bridge(bridge_tok, bridge_id)

                        routed_to = result.get('routed_to')
                        if routed_to:
                            yield _format_sse('routing', routed_to)
                            await asyncio.sleep(0.02)

                        response_text = result.get('response', '')
                        skip_final_response_chunking = bool(
                            result.pop('_skip_final_response_chunking', False)
                        )

                        if response_text and not skip_final_response_chunking:
                            if emit_reset_before_final:
                                yield _format_sse(
                                    'response_chunk',
                                    {'chunk': '', 'reset': True},
                                )
                                await asyncio.sleep(0.02)
                            for chunk in _chunk_text(str(response_text)):
                                yield _format_sse('response_chunk', {'chunk': chunk})
                                await asyncio.sleep(0.03)

                        result['thinking_steps'] = collected_thinking
                        yield _format_sse('done', result)

        except asyncio.TimeoutError:
            yield _format_sse('error', {'message': f'Agent timed out after {int(AGENT_STREAM_TIMEOUT_SEC)}s'})
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield _format_sse('error', {'message': str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


def _normalize_result(raw):
    """Convert a raw agent result into a dict."""
    if raw is None:
        return {}
    if hasattr(raw, 'model_dump'):
        return raw.model_dump()
    if hasattr(raw, 'dict'):
        return raw.dict()
    if not isinstance(raw, dict):
        return {'response': str(raw)}
    return raw


_api_log = logging.getLogger("uvicorn.error")
# Set when MCP mount succeeds; drives Streamable HTTP session task group for Cursor.
_mcp_streamable_run = None


@asynccontextmanager
async def _app_lifespan(fastapi_app: FastAPI):
    """Application startup/shutdown lifecycle."""
    _idle_sweeper_task: Optional[asyncio.Task] = None

    # MongoDB: initialise the motor (async) client early
    try:
        await chat_db.init_pool()
    except Exception as _pool_err:
        _api_log.warning("MongoDB async client init failed: %s", _pool_err)

    # FastAPI does not run @app.on_event("startup") handlers when an explicit
    # lifespan is configured. Keep critical MongoDB bootstrap work here so a
    # newly configured cluster has an admin account and agents catalog before
    # the first request is served.
    try:
        await asyncio.to_thread(admin_auth.init_admin_db)
        await asyncio.to_thread(admin_auth.seed_default_admin)
        await asyncio.to_thread(init_agents_catalog_db)
    except Exception as _db_init_err:
        _api_log.warning("Critical MongoDB bootstrap failed: %s", _db_init_err)

    # Remaining indexes and registries may initialize in the background.
    _init_databases()

    async with AsyncExitStack() as stack:
        if _mcp_streamable_run is not None:
            await stack.enter_async_context(_mcp_streamable_run())
            _api_log.info("MCP Streamable HTTP session manager started.")
            # Start background sweeper that terminates idle MCP sessions. Without this,
            # sessions leak when clients (Cursor) close without sending DELETE /mcp.
            try:
                from mcp_sse import _idle_session_sweeper, streamable_session_manager as _ssm
                _idle_sweeper_task = asyncio.create_task(
                    _idle_session_sweeper(_ssm), name="mcp-idle-sweeper"
                )
                _api_log.info("MCP idle-session sweeper task started.")
            except Exception as _sw_err:
                _api_log.warning("MCP idle-session sweeper failed to start: %s", _sw_err)

        try:
            from langfuse_tracer import log_langfuse_boot_status

            log_langfuse_boot_status()
        except Exception as _lf_boot_exc:
            _api_log.warning("Langfuse boot status could not be printed: %s", _lf_boot_exc)

        # Background task: periodic session cleanup (every 5 minutes)
        _session_cleanup_task: Optional[asyncio.Task] = None

        async def _periodic_session_cleanup():
            """Clean up expired sessions and stale session locks."""
            while True:
                try:
                    await asyncio.sleep(300)  # 5 minutes
                    conversation_sessions_store.cleanup_expired()
                    # Also prune session locks for sessions no longer active
                    stale_keys = [k for k, v in _session_locks.items() if not v.locked()]
                    if len(stale_keys) > 500:
                        for k in stale_keys[:len(stale_keys) - 100]:
                            _session_locks.pop(k, None)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    _api_log.warning("Session cleanup error: %s", e)

        _session_cleanup_task = asyncio.create_task(
            _periodic_session_cleanup(), name="session-cleanup"
        )

        yield

        # Stop the idle-session sweeper before closing the HTTP client. asyncio.Task.cancel
        # triggers the CancelledError branch inside the sweeper loop which logs and exits.
        if _idle_sweeper_task is not None:
            _idle_sweeper_task.cancel()
            try:
                await _idle_sweeper_task
            except (asyncio.CancelledError, Exception) as _sw_stop_err:
                if not isinstance(_sw_stop_err, asyncio.CancelledError):
                    _api_log.warning("MCP idle-session sweeper stop error: %s", _sw_stop_err)

        # Stop the session cleanup task
        if _session_cleanup_task is not None:
            _session_cleanup_task.cancel()
            try:
                await _session_cleanup_task
            except (asyncio.CancelledError, Exception):
                pass

        # Close the shared MCP HTTP client so in-flight connections drain cleanly.
        try:
            from mcp_server import close_http_client
            await close_http_client()
            _api_log.info("MCP HTTP client closed.")
        except Exception as _close_err:
            _api_log.warning("MCP HTTP client close error: %s", _close_err)

        # MongoDB: close the motor (async) client and the shared sync pymongo client
        try:
            await chat_db.close_pool()
        except Exception as _pool_close_err:
            _api_log.warning("MongoDB async client close error: %s", _pool_close_err)

        try:
            from agent_registry import close_pool as _close_agent_pool
            _close_agent_pool()
        except Exception as _agent_pool_err:
            _api_log.warning("agent_registry pool close error: %s", _agent_pool_err)

        try:
            from mongo_db import close_client as _close_mongo_sync
            _close_mongo_sync()
        except Exception as _mongo_close_err:
            _api_log.warning("MongoDB sync client close error: %s", _mongo_close_err)


# FastAPI app initialization
# Keep /docs free for the React SPA (MCP documentation). Default FastAPI /docs would override
# the catch-all and show Swagger on hard refresh instead of DocsPage.
app = FastAPI(
    title="Multi-Agent API",
    description="API to trigger Basic Agent and JIRA Agent",
    version="1.0.0",
    lifespan=_app_lifespan,
    docs_url="/api/swagger-ui",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

images_dir = Path(__file__).parent.parent / "frontend" / "public" / "images"
if images_dir.exists():
    app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")

class McpStreamablePathMiddleware(BaseHTTPMiddleware):
    """Starlette ``Mount('/mcp', ...)`` only matches ``/mcp/...`` (slash after ``mcp``). A bare
    ``/mcp`` returns 307 → ``/mcp/``; many MCP clients do not retry POST correctly. Mutate
    ``path`` in place — ``BaseHTTPMiddleware`` forwards the same ``scope`` dict to the app."""

    async def dispatch(self, request: Request, call_next):
        if request.scope["type"] == "http" and request.scope.get("path") == "/mcp":
            request.scope["path"] = "/mcp/"
        return await _safe_call_next(request, call_next)


async def _safe_call_next(request: Request, call_next):
    """Normalize client-abort behavior in BaseHTTPMiddleware chains.

    Starlette can raise RuntimeError("No response returned.") when the client
    disconnects while middleware still awaits call_next.
    """
    try:
        return await call_next(request)
    except ClientDisconnect:
        return JSONResponse({"detail": "Client disconnected"}, status_code=499)
    except RuntimeError as exc:
        if "No response returned." in str(exc):
            return JSONResponse({"detail": "Client disconnected"}, status_code=499)
        raise


# Enable CORS.
# allow_credentials=True requires explicit origin list — the CORS spec disallows
# credentials with the wildcard origin and browsers will reject such responses.
# We keep allow_origins=["*"] for a public API but disable credentials to stay spec-compliant.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(McpStreamablePathMiddleware)

# Mount MCP: Streamable HTTP at /mcp (Cursor default) and legacy SSE at /mcp/sse
try:
    from mcp_sse import mcp_starlette_app, streamable_session_manager

    app.mount("/mcp", mcp_starlette_app)
    _mcp_streamable_run = streamable_session_manager.run
    print("[MCP] Streamable HTTP: http://localhost:8000/mcp  |  SSE: http://localhost:8000/mcp/sse")
except Exception as _mcp_err:
    print(f"[MCP] MCP transport not available: {_mcp_err}")

AGENT_API_PATHS = {
    '/api/basic-agent': 'Basic Agent',
    '/api/jira-agent': 'JIRA Agent',
    '/api/brd-generation': 'BRD Generation Agent',
    '/api/rbi-circular': 'RBI Circular Agent',
    '/api/sebi-circular': 'SEBI Circular Agent',
    '/api/bpmn-generator': 'BPMN Generator Agent',
    '/api/market-research': 'Market Research Agent',
    '/api/company-research': 'Company Research Agent',
    '/api/company-ai-solutions': 'Company AI Solutions Agent',
    '/api/github-repo': 'GitHub Repo Agent',
    '/api/unit-test': 'Unit Test Agent',
    '/api/qa-automation': 'QA Automation Agent',
    '/api/web-test': 'Web Test Agent',
    '/api/code-sandbox': 'Code Sandbox Agent',
    '/api/mongodb-rag': 'MongoDB Atlas KB Agent',
    '/api/global-chat': 'Global Chat',
    '/api/meeting-prep': 'Meeting Prep Agent',
    '/api/document-formatter': 'Document Formatter Agent',
    '/api/shannon-security': 'Shannon Security Agent',
    '/api/email-agent': 'Email Agent',
    '/api/zoho-email-meeting-agent': 'Zoho Email Meeting Agent',
    '/api/zoho-support-ticket-agent': 'Zoho Support Ticket Agent',
    '/api/zoho-new-customer-agent': 'Zoho New Customer Agent',
    '/api/debug-trace': 'Langfuse agent',
    '/api/claude-code': 'Claude Code Agent',
    '/api/workspace-coding': 'Workspace context Agent',
    '/api/coder-agent': 'Coder Agent',
    '/api/web-search': 'Web Search Agent',
    '/api/ppt-generator': 'PPT Generator Agent',
    '/api/browser-agent': 'Browser Automation Agent',
    '/api/webmcp-agent': 'WebMCP Agent',
}


def _api_path_to_agent_id() -> Dict[str, str]:
    from agents_catalog_db import get_api_path_to_agent_id

    return get_api_path_to_agent_id()


def _optional_verify_user(authorization: Optional[str]) -> Optional[Dict]:
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "", 1) if authorization.startswith("Bearer ") else authorization
    return admin_auth.verify_token(token)


class AgentAccessMiddleware(BaseHTTPMiddleware):
    """When Authorization is present, restrict agent POST endpoints to assigned catalog agent IDs."""

    async def dispatch(self, request: Request, call_next):
        if request.method != "POST":
            return await _safe_call_next(request, call_next)
        path = request.url.path
        if path.startswith("/api/admin/") or path.startswith("/api/chat/"):
            return await _safe_call_next(request, call_next)
        user = _optional_verify_user(request.headers.get("authorization"))
        if not user:
            return await _safe_call_next(request, call_next)
        allowed = admin_auth.effective_agent_ids(
            user.get("role", "user"),
            user.get("agent_permissions"),
        )
        if path == "/api/external-agent":
            body = await request.body()

            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(request.scope, receive)
            try:
                data = json.loads(body)
                aid = data.get("agent_id")
            except Exception:
                aid = None
            if aid:
                if len(allowed) == 0 or aid not in allowed:
                    return JSONResponse({"detail": "No access to this agent"}, status_code=403)
            return await _safe_call_next(request, call_next)
        if path == "/api/global-chat":
            if len(allowed) == 0:
                return JSONResponse(
                    {"detail": "No agents assigned to your account. Ask your administrator to grant agent access."},
                    status_code=403,
                )
            return await _safe_call_next(request, call_next)
        agent_id = _api_path_to_agent_id().get(path)
        if agent_id:
            if len(allowed) == 0 or agent_id not in allowed:
                return JSONResponse({"detail": "No access to this agent"}, status_code=403)
        return await _safe_call_next(request, call_next)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get('x-forwarded-for')
    if forwarded:
        return forwarded.split(',')[0].strip()
    real_ip = request.headers.get('x-real-ip')
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else 'unknown'

class UsageTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await _safe_call_next(request, call_next)
        
        if request.method == 'POST':
            path = request.url.path
            agent_name = AGENT_API_PATHS.get(path)
            if agent_name and response.status_code == 200:
                try:
                    ip = _get_client_ip(request)
                    user_agent = request.headers.get('user-agent', '')
                    location = usage_tracker.resolve_ip_location(ip)
                    
                    body_bytes = getattr(request.state, '_body', None)
                    query_preview = None
                    if body_bytes:
                        try:
                            body = json.loads(body_bytes)
                            query_preview = body.get('query') or body.get('message') or body.get('prompt')
                        except Exception:
                            pass
                    
                    usage_tracker.log_usage(
                        agent_name=agent_name,
                        agent_id=path.split('/api/')[-1].replace('/', '_'),
                        ip_address=ip,
                        city=location.get('city', ''),
                        region=location.get('region', ''),
                        country=location.get('country', ''),
                        user_agent=user_agent[:500] if user_agent else None,
                        query_preview=query_preview[:200] if query_preview else None,
                        latitude=location.get('lat'),
                        longitude=location.get('lon'),
                        zipcode=location.get('zip', ''),
                        timezone=location.get('timezone', ''),
                        isp=location.get('isp', ''),
                        org=location.get('org', ''),
                    )
                except Exception as e:
                    print(f"[UsageTracker] Middleware error: {e}")
        
        return response

app.add_middleware(UsageTrackingMiddleware)
app.add_middleware(AgentAccessMiddleware)


# ---------------------------------------------------------------------------
# Phase 3: Backpressure middleware — caps concurrent agent requests per user IP
# ---------------------------------------------------------------------------
# Prevents a single user/IP from flooding the server. MCP loopback calls are
# exempted because MCP has its own semaphores (_call_semaphore + per-session).
_BACKPRESSURE_PER_USER = int(_os.getenv("BACKPRESSURE_PER_USER", "3"))


class BackpressureMiddleware(BaseHTTPMiddleware):
    """Limit concurrent in-flight agent POST requests per client IP.

    Non-agent paths (admin, chat CRUD, health) are excluded. Internal MCP
    loopback requests (identified by ``X-Internal: mcp`` header) are excluded
    since MCP already rate-limits via its own semaphores.
    """

    def __init__(self, app, max_concurrent: int = _BACKPRESSURE_PER_USER):
        super().__init__(app)
        self._max = max_concurrent
        self._counts: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next):
        # Only apply to agent POST endpoints
        if request.method != "POST":
            return await _safe_call_next(request, call_next)
        path = request.url.path
        if not path.startswith("/api/") or path.startswith("/api/admin/") or path.startswith("/api/chat/"):
            return await _safe_call_next(request, call_next)
        if path.startswith("/api/preview/"):
            return await _safe_call_next(request, call_next)
        # Exempt MCP loopback calls
        if request.headers.get("x-internal") == "mcp":
            return await _safe_call_next(request, call_next)

        ip = _get_client_ip(request)
        async with self._lock:
            current = self._counts.get(ip, 0)
            if current >= self._max:
                return JSONResponse(
                    {"detail": f"Too many concurrent requests (limit {self._max}). Please wait and retry."},
                    status_code=429,
                )
            self._counts[ip] = current + 1

        try:
            return await _safe_call_next(request, call_next)
        finally:
            async with self._lock:
                self._counts[ip] = max(self._counts.get(ip, 1) - 1, 0)
                if self._counts[ip] == 0:
                    self._counts.pop(ip, None)


app.add_middleware(BackpressureMiddleware)


# ---------------------------------------------------------------------------
# Maintenance mode enforcement
# ---------------------------------------------------------------------------
# When maintenance_mode["enabled"] is True, all /api/* requests are rejected
# with 503 UNLESS the caller is the super_admin. A short allowlist keeps
# login/status/health reachable so the super_admin can sign in and toggle it
# off, and so the frontend can poll the maintenance banner.
maintenance_mode = {"enabled": False, "message": "We're performing scheduled maintenance. Please check back shortly."}

_MAINTENANCE_ALLOWLIST = {
    "/api/maintenance",
    "/api/admin/login",
    "/api/admin/me",
    "/api/admin/maintenance",
    "/api/health",
}


class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    """Block every /api/* request from non-super_admin callers while maintenance mode is on."""

    async def dispatch(self, request: Request, call_next):
        if not maintenance_mode["enabled"]:
            return await _safe_call_next(request, call_next)
        if request.method == "OPTIONS":
            return await _safe_call_next(request, call_next)
        path = request.url.path
        if not path.startswith("/api/"):
            return await _safe_call_next(request, call_next)
        if path in _MAINTENANCE_ALLOWLIST:
            return await _safe_call_next(request, call_next)

        user = _optional_verify_user(request.headers.get("authorization"))
        if user and user.get("role") == "super_admin":
            return await _safe_call_next(request, call_next)

        return JSONResponse(
            {
                "detail": "Service is in maintenance mode. Only the super admin can access the application right now.",
                "maintenance": True,
                "message": maintenance_mode["message"],
            },
            status_code=503,
        )


app.add_middleware(MaintenanceModeMiddleware)


# Serve static files from frontend build (for production)
print(f"[Static Files] Checking frontend dist: {frontend_dist} (exists: {frontend_dist.exists()})")
if frontend_dist.exists():
    if (frontend_dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")
    images_dir = frontend_dist / "images"
    if images_dir.exists():
        app.mount("/images", StaticFiles(directory=str(images_dir)), name="images")
        print(f"[Static Files] Mounted /images from {images_dir}")
    elif frontend_public.exists() and (frontend_public / "images").exists():
        app.mount("/images", StaticFiles(directory=str(frontend_public / "images")), name="images")
        print(f"[Static Files] Mounted /images from {frontend_public / 'images'} (fallback)")
elif frontend_public.exists() and (frontend_public / "images").exists():
    app.mount("/images", StaticFiles(directory=str(frontend_public / "images")), name="images")
    print(f"[Static Files] Mounted /images from {frontend_public / 'images'} (no dist)")


# API Endpoints
class AdminLoginRequest(BaseModel):
    username: str
    password: str

class AdminChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

def _init_databases():
    """Initialize non-admin databases in background thread."""
    import threading
    def _do_init():
        try:
            chat_db.init_db()
            cost_tracker.init_cost_tracking_db()
            usage_tracker.init_usage_tracking_db()
            from agent_builder_db import init_agent_builder_db
            init_agent_builder_db()
            init_agents_catalog_db()
            from tool_registry import seed_builtin_tools
            seed_builtin_tools()
            print("Database initialized successfully")
        except Exception as e:
            print(f"Warning: Database init failed - {e}")
    t = threading.Thread(target=_do_init, daemon=True)
    t.start()

@app.post("/api/admin/login")
async def admin_login(request: AdminLoginRequest):
    user = admin_auth.authenticate_admin(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = admin_auth.generate_token(user)
    return {
        "token": token,
        "username": user["username"],
        "role": user.get("role", "user"),
        "menu_permissions": user.get("menu_permissions", []),
        "agent_permissions": admin_auth.effective_agent_ids(
            user.get("role", "user"), user.get("agent_permissions")
        ),
    }

@app.get("/api/admin/me")
async def admin_me(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="No token provided")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user.get("role", "user"),
        "menu_permissions": user.get("menu_permissions", []),
        "agent_permissions": user.get("agent_permissions", []),
    }

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    menu_permissions: List[str] = []
    agent_permissions: Optional[List[str]] = None

class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    menu_permissions: Optional[List[str]] = None
    agent_permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None

def _require_admin(authorization: Optional[str]) -> Dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="No token provided")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user.get("role") not in ("admin", "super_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def _require_super_admin(authorization: Optional[str]) -> Dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="No token provided")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can perform this action")
    return user

def _require_auth(authorization: Optional[str]) -> Dict:
    if not authorization:
        raise HTTPException(status_code=401, detail="No token provided")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return user

def _require_permission(authorization: Optional[str], permission: str) -> Dict:
    user = _require_auth(authorization)
    if user.get("role") in ("admin", "super_admin"):
        return user
    perms = user.get("menu_permissions", [])
    if permission not in perms:
        raise HTTPException(status_code=403, detail=f"No access to '{permission}'")
    return user

@app.get("/api/admin/users")
async def list_users(authorization: Optional[str] = Header(None)):
    _require_admin(authorization)
    try:
        users = admin_auth.list_users()
        for u in users:
            if isinstance(u.get("created_at"), datetime):
                u["created_at"] = u["created_at"].isoformat()
        return {"success": True, "users": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/users")
async def create_user(request: CreateUserRequest, authorization: Optional[str] = Header(None)):
    caller = _require_admin(authorization)
    if request.role == "admin" and caller.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can create admin accounts")
    if request.agent_permissions is not None and caller.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can assign agent access")
    try:
        agent_perms = request.agent_permissions if caller.get("role") == "super_admin" else None
        user = admin_auth.create_user(
            request.username, request.password,
            request.role, request.menu_permissions,
            agent_permissions=agent_perms,
        )
        if isinstance(user.get("created_at"), datetime):
            user["created_at"] = user["created_at"].isoformat()
        return {"success": True, "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/admin/users/{user_id}")
async def update_user(user_id: int, payload: UpdateUserRequest, authorization: Optional[str] = Header(None)):
    caller = _require_admin(authorization)
    if payload.role == "admin" and caller.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can assign the admin role")
    if payload.menu_permissions is not None and caller.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can change feature permissions")
    if "agent_permissions" in payload.model_fields_set and caller.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can change agent access")
    try:
        updates = {}
        if payload.role is not None:
            updates["role"] = payload.role
        if payload.menu_permissions is not None:
            updates["menu_permissions"] = payload.menu_permissions
        if "agent_permissions" in payload.model_fields_set:
            updates["agent_permissions"] = payload.agent_permissions
        if payload.is_active is not None:
            updates["is_active"] = payload.is_active
        if payload.password is not None:
            updates["password"] = payload.password
        user = admin_auth.update_user(user_id, updates)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if isinstance(user.get("created_at"), datetime):
            user["created_at"] = user["created_at"].isoformat()
        return {"success": True, "user": user}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/users/{user_id}")
async def delete_user(user_id: int, authorization: Optional[str] = Header(None)):
    caller = _require_admin(authorization)
    try:
        target = admin_auth.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if target.get("role") in ("admin", "super_admin") and caller.get("role") != "super_admin":
            raise HTTPException(status_code=403, detail="Only the super admin can delete admin accounts")
        deleted = admin_auth.delete_user(user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="User not found")
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/change-password")
async def admin_change_password(request: AdminChangePasswordRequest, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="No token provided")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    success = admin_auth.change_password(user["username"], request.old_password, request.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    return {"message": "Password changed successfully"}

@app.get("/api/admin/cost-summary")
async def admin_cost_summary(authorization: Optional[str] = Header(None)):
    _require_permission(authorization, "costs")
    try:
        summary = cost_tracker.get_cost_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch cost summary: {str(e)}")

@app.get("/api/admin/usage-summary")
async def admin_usage_summary(authorization: Optional[str] = Header(None)):
    _require_permission(authorization, "usage")
    try:
        summary = usage_tracker.get_usage_summary()
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch usage summary: {str(e)}")

@app.get("/api/admin/usage-logs")
async def admin_usage_logs(
    limit: int = 100, 
    offset: int = 0, 
    agent: Optional[str] = None,
    authorization: Optional[str] = Header(None)
):
    _require_permission(authorization, "usage")
    try:
        total = usage_tracker.count_usage_logs(agent_filter=agent)
        logs = usage_tracker.get_usage_logs(limit=limit, offset=offset, agent_filter=agent)
        for log in logs:
            for key, val in log.items():
                if isinstance(val, datetime):
                    log[key] = val.isoformat()
        return {"logs": logs, "limit": limit, "offset": offset, "total": total}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch usage logs: {str(e)}")

# -----------------------------------------agent core --------------------------------------------------

@app.post("/api/basic-agent")
async def trigger_basic_agent(request: BasicAgentRequest):
    """Trigger the Basic Agent with a query (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing your request..."}}
        result = await asyncio.to_thread(
            _get_agent("basic_agent").process_query,
            request.query,
            clear_history=request.clear_history,
            session_id=request.session_id,
        )
        if isinstance(result, dict):
            yield {"success": True, "query": request.query, "response": result.get("response", ""), "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat()}
        else:
            yield {"success": True, "query": request.query, "response": str(result), "thinking_steps": [], "timestamp": datetime.now().isoformat()}

    return await _stream_agent_response("Basic Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


def extract_thinking_steps(intermediate_steps: list) -> list:
    """Extract thinking steps from LangChain intermediate_steps or custom dicts."""
    thinking_steps = []
    
    for step in intermediate_steps:
        # Handle our custom dictionary format (from JIRA/Basic agent)
        if isinstance(step, dict) and "type" in step:
            thinking_steps.append(step)
            continue
            
        # Handle LangChain tuple format (action, observation)
        if isinstance(step, (list, tuple)) and len(step) >= 2:
            action = step[0]
            observation = step[1]
            
            # Extract tool call info
            if hasattr(action, 'tool') and hasattr(action, 'tool_input'):
                thinking_steps.append({
                    "type": "tool_call",
                    "content": f"Using {action.tool}",
                    "tool_name": action.tool,
                    "tool_input": str(action.tool_input) if action.tool_input else ""
                })
                
                # Add the observation/result
                obs_text = str(observation) if observation else "No result"
                thinking_steps.append({
                    "type": "tool_result",
                    "content": obs_text[:16000] + ("… [truncated]" if len(obs_text) > 16000 else ""),
                    "tool_name": action.tool,
                    "tool_input": None
                })
            elif hasattr(action, 'log'):
                # Agent's thinking/reasoning (full scratchpad for UI trace; scrollable client-side)
                log_text = action.log or ""
                thinking_steps.append({
                    "type": "thinking",
                    "content": log_text[:32000] + ("… [truncated]" if len(log_text) > 32000 else ""),
                    "tool_name": None,
                    "tool_input": None
                })
    
    return thinking_steps


@app.post("/api/jira-agent")
async def trigger_jira_agent(request: JIRAAgentRequest):
    """Trigger the JIRA Agent with a query (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing JIRA request..."}}

        conversation_ctx = None
        if request.session_id:
            if request.session_id in conversation_sessions:
                conversation_ctx = conversation_sessions[request.session_id]
            else:
                ConversationContext = _get_agent("conversation_manager")[0]
                conversation_ctx = ConversationContext(session_id=request.session_id)
                conversation_sessions[request.session_id] = conversation_ctx
            if request.context_data:
                conversation_ctx.update_collected_data(request.context_data)

        yield {"event": "thinking", "data": {"type": "thinking", "content": "Detecting intent and processing JIRA operation..."}}

        result = await _get_agent("jira_agent").process_query_interactive(
            user_prompt=request.query, conversation_ctx=conversation_ctx, context_data=request.context_data
        )

        if request.session_id and conversation_ctx:
            conversation_sessions[request.session_id] = conversation_ctx

        thinking_steps = []
        if "intermediate_steps" in result:
            thinking_steps = extract_thinking_steps(result.get("intermediate_steps", []))
        if result.get("intent"):
            thinking_steps.insert(0, {"type": "thinking", "content": f"Detected intent: {result.get('intent')}", "tool_name": None, "tool_input": None})

        final_data: dict = {
            "success": result.get("success", False), "query": request.query, "response": result.get("response", ""),
            "state": result.get("state"), "session_id": result.get("session_id"), "tickets": result.get("tickets", []),
            "missing_fields": result.get("missing_fields", []), "collected_data": result.get("collected_data", {}),
            "thinking_steps": thinking_steps, "timestamp": datetime.now().isoformat(),
        }
        if result.get("chart_data"):
            final_data["chart_data"] = result["chart_data"]
        yield final_data

    return await _stream_agent_response("JIRA Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/brd-generation")
async def trigger_brd_agent(request: BRDAgentRequest):
    """Generate a BRD (SSE stream)."""

    async def process():
        q: queue.Queue = queue.Queue()

        def sse_emit(ev: str, data: dict):
            q.put(("stream", ev, data))

        def worker():
            try:
                result = _get_agent("brd_agent").process_query(
                    request.query,
                    clear_history=request.clear_history,
                    session_id=request.session_id,
                    emit=sse_emit,
                )
                q.put(("final", result))
            except Exception as exc:
                q.put(("fatal", exc))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            kind, *rest = await asyncio.to_thread(q.get)
            if kind == "stream":
                ev, data = rest[0], rest[1]
                if ev == "thinking":
                    yield {"event": "thinking", "data": data}
                elif ev == "progress":
                    yield {"event": "progress", "data": data}
                elif ev == "response_chunk":
                    yield {"event": "response_chunk", "data": data}
                await asyncio.sleep(0)
            elif kind == "final":
                result = rest[0]
                break
            elif kind == "fatal":
                raise rest[0]

        yield {
            "success": True,
            "query": request.query,
            "response": result.get("response", ""),
            "thinking_steps": result.get("thinking_steps", []),
            "timestamp": datetime.now().isoformat(),
            "brd_file_path": result.get("brd_file_path"),
            "_emit_reset_before_response_chunks": result.get(
                "_emit_reset_before_response_chunks", False
            ),
        }

    return await _stream_agent_response("BRD Generation Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/rbi-circular")
async def trigger_rbi_agent(request: RBIAgentRequest):
    """Query RBI circulars (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Searching RBI circulars and notifications..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Running parallel searches across RBI domains..."}}
        result = await _get_agent("rbi_agent").process_query(request.query, session_id=request.session_id)
        yield {"event": "progress", "data": {"stage": "synthesis", "message": "Synthesizing regulatory findings..."}}
        yield {"success": True, "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "notifications": result.get("notifications", []), "session_id": result.get("session_id")}

    return await _stream_agent_response("RBI Circular Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/sebi-circular")
async def trigger_sebi_agent(request: SEBIAgentRequest):
    """Query SEBI circulars (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Searching SEBI circulars..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Running parallel searches across SEBI domains..."}}
        result = await _get_agent("sebi_agent").process_query(request.query, session_id=request.session_id)
        yield {"event": "progress", "data": {"stage": "synthesis", "message": "Synthesizing regulatory findings..."}}
        yield {"success": True, "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "notifications": result.get("notifications", []), "session_id": result.get("session_id")}

    return await _stream_agent_response("SEBI Circular Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/bpmn-generator")
async def trigger_bpmn_agent(request: BPMNAgentRequest):
    """Generate BPMN diagrams (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing process for BPMN generation..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Parsing document and extracting process flow..."}}
        result = await asyncio.to_thread(
            _get_agent("bpmn_agent").process_query,
            query=request.query, session_id=request.session_id,
            file_content=request.file_content, file_type=request.file_type, clear_history=request.clear_history
        )
        yield {"event": "progress", "data": {"stage": "rendering", "message": "Generating BPMN 2.0 diagram..."}}
        yield {"success": result.get("success", False), "query": request.query, "response": result.get("response", ""),
                "bpmn_xml": result.get("bpmn_xml"), "session_id": result.get("session_id"),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat()}

    return await _stream_agent_response("BPMN Generator Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


# --------------------------------------------------Market Research Agent --------------------------------------------------
@app.post("/api/market-research")
async def trigger_market_research_agent(request: MarketResearchRequest):
    """Perform market research (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Starting market research..."}}

        stream_events: asyncio.Queue = asyncio.Queue()

        async def _stream_callback(evt: Dict[str, Any]):
            await stream_events.put(evt)

        research_task = asyncio.create_task(
            _get_agent("market_research_agent").research(
                query=request.query,
                email_recipients=request.email_recipients,
                session_id=request.session_id,
                stream_callback=_stream_callback,
            )
        )

        while True:
            if research_task.done() and stream_events.empty():
                break
            try:
                evt = await asyncio.wait_for(stream_events.get(), timeout=0.2)
                if isinstance(evt, dict) and evt.get("event"):
                    yield evt
            except asyncio.TimeoutError:
                continue

        result = await research_task
        yield {"event": "progress", "data": {"stage": "final", "message": "Compiling final response..."}}
        yield result

    return await _stream_agent_response("Market Research Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/company-research")
async def trigger_company_research_agent(request: CompanyResearchRequest):
    """Perform company research (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Starting company research..."}}
        result = await _get_agent("company_research_agent").research(
            query=request.query, email_recipients=request.email_recipients, session_id=request.session_id)
        yield {"event": "progress", "data": {"stage": "synthesis", "message": "Synthesizing executive report with charts..."}}
        yield result

    return await _stream_agent_response("Company Research Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/company-ai-solutions")
async def trigger_company_solution_agent(request: CompanySolutionRequest):
    """Analyze detailed company context and propose AI/agentic AI solutions (SSE stream)."""

    # Normalize single-file upload (from in-app chat) into uploaded_files list.
    merged_uploads = list(request.uploaded_files or [])
    if request.file_content and request.file_type and not any(
        (u.file_name or "") == (request.file_name or "") for u in merged_uploads
    ):
        from agents.Company_solution_agent.models import UploadedSolutionFile
        merged_uploads.append(
            UploadedSolutionFile(
                file_content=request.file_content,
                file_type=request.file_type,
                file_name=request.file_name,
            )
        )

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Reading detailed company context..."}}
        if merged_uploads:
            yield {"event": "thinking", "data": {"type": "thinking", "content": f"Received {len(merged_uploads)} uploaded file(s) — will prefer matching solutions from your catalog."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Splitting company details into chunks for deep analysis..."}}
        result = await _get_agent("company_solution_agent").analyze(
            query=request.query,
            company_name=request.company_name,
            company_details=request.company_details,
            uploaded_files=merged_uploads or None,
            session_id=request.session_id,
        )
        yield {"event": "progress", "data": {"stage": "synthesis", "message": "Generating prioritized AI and agentic AI recommendations..."}}
        yield result

    return await _stream_agent_response("Company AI Solutions Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/meeting-prep")
async def trigger_meeting_prep_agent(request: MeetingPrepRequest):
    """Meeting prep (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Preparing meeting brief..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Analyzing context and running multi-dimensional research..."}}
        result = await _get_agent("meeting_prep_agent").prepare(
            query=request.query, session_id=request.session_id,
            clear_history=request.clear_history or False, email_recipients=request.email_recipients)
        yield {"event": "progress", "data": {"stage": "synthesis", "message": "Generating strategic talking points..."}}
        yield result

    return await _stream_agent_response("Meeting Prep Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/document-formatter")
async def trigger_document_formatter_agent(request: DocumentFormatterRequest):
    """Document formatting (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Processing document..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Extracting text, tables, and images from document..."}}
        result = await _get_agent("document_formatter_agent").process(
            query=request.query, file_content=request.file_content, file_type=request.file_type,
            file_name=request.file_name, session_id=request.session_id, output_format=request.output_format or "markdown")
        yield {"event": "progress", "data": {"stage": "formatting", "message": "Reformatting content with LLM..."}}
        yield result

    return await _stream_agent_response("Document Formatter Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.post("/api/ppt-generator")
async def trigger_ppt_generator_agent(request: PPTGeneratorRequest):
    """Generate a professional PowerPoint presentation (SSE stream)."""

    # Determine at route level whether web search will run and which provider
    # is selected so we can emit accurate initial thinking/progress steps.
    def _web_search_mode() -> tuple[bool, str, str]:
        if request.file_content and (request.file_type or request.file_name):
            return False, "", ""

        provider = "perplexity"
        if request.web_search_enabled is True:
            merged = merge_configs_for_agent_id("ppt_generator", request.user_config or {})
            raw_provider = str(merged.get("PPT_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
            if raw_provider in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
                provider = "free_ollama"
            elif raw_provider in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
                provider = "free_duckduckgo"
            else:
                provider = "perplexity"
            if provider == "free_ollama":
                return True, "Ollama free web search", "ollama_web_search"
            if provider == "free_duckduckgo":
                return True, "DuckDuckGo free web search", "duckduckgo_web_search"
            return True, "Perplexity web search", "perplexity_search"
        if request.web_search_enabled is False:
            return False, "", ""
        merged = merge_configs_for_agent_id("ppt_generator", request.user_config or {})
        raw_provider = str(merged.get("PPT_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw_provider in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            provider = "free_ollama"
        elif raw_provider in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            provider = "free_duckduckgo"
        else:
            provider = "perplexity"
        raw = str(merged.get("PPT_WEB_SEARCH_ENABLED") or "").strip().lower()
        active = raw in ("1", "true", "yes", "on")
        if not active:
            return False, "", ""
        if provider == "free_ollama":
            return True, "Ollama free web search", "ollama_web_search"
        if provider == "free_duckduckgo":
            return True, "DuckDuckGo free web search", "duckduckgo_web_search"
        return True, "Perplexity web search", "perplexity_search"

    async def process():
        search_on, search_label, search_tool = _web_search_mode()
        has_uploaded_file = bool(request.file_content and (request.file_type or request.file_name))
        if search_on:
            yield {"event": "progress", "data": {"stage": "search", "message": "Searching the web for current facts and data..."}}
            yield {"event": "thinking", "data": {"type": "tool_call", "content": f"Running {search_label} to ground slides in real, up-to-date information", "tool_name": search_tool, "tool_input": request.query[:150]}}
        elif has_uploaded_file:
            label = request.file_name or "uploaded file"
            yield {"event": "progress", "data": {"stage": "file_ingest", "message": f"Processing uploaded file: {label}"}}
            yield {"event": "thinking", "data": {"type": "tool_call", "content": "Uploaded file detected; skipping web search and extracting business insights from document content.", "tool_name": "file_ingest", "tool_input": label[:150]}}
        else:
            yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing presentation request..."}}
            yield {"event": "thinking", "data": {"type": "thinking", "content": "Planner agent: slide count, sequence, layouts, and research prompts…"}}

        ag = _get_agent("ppt_generator_agent")
        async for item in ag.process_stream(
            query=request.query,
            session_id=request.session_id,
            slide_count=request.slide_count,
            theme=request.theme or "professional",
            file_content=request.file_content,
            file_type=request.file_type,
            file_name=request.file_name,
            web_search_enabled=request.web_search_enabled,
            user_config=request.user_config,
        ):
            yield item

    return await _stream_agent_response("PPT Generator Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


@app.get("/api/ppt-generator/download/{filename}")
async def download_ppt_file(filename: str):
    """Download a generated PPT file."""
    import pathlib
    safe_name = pathlib.Path(filename).name
    if not safe_name.endswith(".pptx") or safe_name != filename or ".." in filename:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})
    generated_dir = pathlib.Path(__file__).parent / "generated_files"
    file_path = (generated_dir / safe_name).resolve()
    if not str(file_path).startswith(str(generated_dir.resolve())):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=400, content={"error": "Invalid filename"})
    if not file_path.exists() or not file_path.is_file():
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"error": "File not found"})
    return FileResponse(
        str(file_path),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=safe_name,
    )


@app.post("/api/web-search")
async def trigger_web_search_agent(request: WebSearchRequest):
    """Perform advanced web search (Perplexity, Ollama free search, or DuckDuckGo free search) (SSE stream)."""

    def _web_search_provider_label() -> tuple[str, str]:
        merged = merge_configs_for_agent_id("web_search_agent", request.user_config or {})
        raw_provider = str(merged.get("WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw_provider in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "Ollama free web search", "ollama_web_search"
        if raw_provider in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "DuckDuckGo free web search", "duckduckgo_web_search"
        return "Perplexity web search", "perplexity_search"

    async def process():
        provider_label, provider_tool = _web_search_provider_label()
        yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing search query..."}}
        yield {"event": "thinking", "data": {"type": "tool_call", "content": f"Classifying intent and optimizing query for {provider_label}...", "tool_name": provider_tool, "tool_input": request.query[:150]}}
        result = await _get_agent("web_search_agent").search(
            query=request.query, search_focus=request.search_focus,
            session_id=request.session_id, clear_history=request.clear_history or False)
        yield {"event": "progress", "data": {"stage": "formatting", "message": "Formatting results..."}}
        yield result

    return await _stream_agent_response("Web Search Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


class ChartExtractionRequest(BaseModel):
    report_text: str = Field(..., description="The full company research report text to extract chart data from")

@app.post("/api/company-research/extract-charts")
async def extract_company_charts(request: ChartExtractionRequest):
    """Extract structured chart data from a company research report via a separate LLM call."""
    try:
        chart_data = await _get_agent("company_research_agent").extract_chart_data(request.report_text)
        return {"success": True, "chart_data": chart_data}
    except Exception as e:
        print(f"❌ Chart extraction error: {str(e)}")
        return {"success": False, "chart_data": {}, "error": str(e)}


# -------------------------------------------------- Chat Sessions API --------------------------------------------------

class ChatSessionResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int

class ChatMessageResponse(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    thinking_steps: Optional[List[Dict[str, Any]]] = None
    routed_to: Optional[Dict[str, Any]] = None
    bpmn_xml: Optional[str] = None
    created_at: str

class UpdateTitleRequest(BaseModel):
    title: str

@app.get("/api/chat/sessions")
async def list_chat_sessions():
    try:
        sessions = await chat_db.async_list_sessions(limit=50)
        return [
            {
                **s,
                "created_at": s["created_at"].isoformat() if hasattr(s["created_at"], 'isoformat') else str(s["created_at"]),
                "updated_at": s["updated_at"].isoformat() if hasattr(s["updated_at"], 'isoformat') else str(s["updated_at"]),
            }
            for s in sessions
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/sessions")
async def create_chat_session():
    try:
        session_id = str(uuid.uuid4())
        session = await chat_db.async_create_session(session_id, "New Chat")
        return {
            **session,
            "created_at": session["created_at"].isoformat() if hasattr(session["created_at"], 'isoformat') else str(session["created_at"]),
            "updated_at": session["updated_at"].isoformat() if hasattr(session["updated_at"], 'isoformat') else str(session["updated_at"]),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/sessions/{session_id}/messages")
async def get_chat_messages(session_id: str):
    try:
        messages = await chat_db.async_get_messages(session_id)
        return [
            {
                **m,
                "created_at": m["created_at"].isoformat() if hasattr(m["created_at"], 'isoformat') else str(m["created_at"]),
            }
            for m in messages
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/chat/sessions/{session_id}/title")
async def update_chat_session_title(session_id: str, request: UpdateTitleRequest):
    try:
        session = await chat_db.async_update_session_title(session_id, request.title)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            **session,
            "created_at": session["created_at"].isoformat() if hasattr(session["created_at"], 'isoformat') else str(session["created_at"]),
            "updated_at": session["updated_at"].isoformat() if hasattr(session["updated_at"], 'isoformat') else str(session["updated_at"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    try:
        deleted = await chat_db.async_delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SaveConversationMessage(BaseModel):
    role: str
    content: str
    thinking_steps: Optional[List[Dict[str, Any]]] = None
    routed_to: Optional[Dict[str, Any]] = None
    bpmn_xml: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None

class SaveConversationRequest(BaseModel):
    messages: List[SaveConversationMessage]
    title: Optional[str] = None

@app.post("/api/chat/sessions/save")
async def save_conversation(request: SaveConversationRequest):
    try:
        session_id = str(uuid.uuid4())
        title = request.title
        if not title:
            first_user = next((m.content for m in request.messages if m.role == "user"), "New Chat")
            title = chat_db.generate_title_from_query(first_user)
        session = await chat_db.async_create_session(session_id, title)

        for msg in request.messages:
            await chat_db.async_save_message(
                session_id=session_id,
                role=msg.role,
                content=msg.content,
                thinking_steps=msg.thinking_steps,
                routed_to=msg.routed_to,
                bpmn_xml=msg.bpmn_xml,
                metadata=msg.metadata,
            )

        return {
            "success": True,
            "session_id": session_id,
            "title": title,
            "created_at": session["created_at"].isoformat() if hasattr(session["created_at"], 'isoformat') else str(session["created_at"]),
            "updated_at": session["updated_at"].isoformat() if hasattr(session["updated_at"], 'isoformat') else str(session["updated_at"]),
            "message_count": len(request.messages),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------------------------------------- GitHub Repo Agent --------------------------------------------------
@app.post("/api/github-repo")
async def trigger_github_repo_agent(request: GitHubRepoRequest):
    """GitHub Repo Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Processing GitHub repository request..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Detecting intent: clone, analyze, generate docs, or push..."}}
        result = await asyncio.to_thread(
            _get_agent("github_repo_agent").process_query,
            query=request.query, session_id=session_id, github_token=request.github_token
        )
        yield {"event": "progress", "data": {"stage": "complete", "message": "Repository operation complete"}}
        yield {"success": result.get("success", False), "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "requires_token": result.get("requires_token", False), "repo_url": result.get("repo_url"),
                "architecture_diagram": result.get("architecture_diagram")}

    return await _stream_agent_response("GitHub Repo Agent", process(), user_config=request.user_config, session_id=session_id, input_text=request.query)


# -------------------------------------------------- Sonarqube Agent --------------------------------------------------
@app.post("/api/sonarqube")
async def trigger_sonarqube_agent(request: SonarqubeRequest):
    """Sonarqube Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Preparing Sonarqube analysis..."}}
        if request.clear_history:
            _get_agent("sonarqube_agent").clear_session(session_id)
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Connecting to GitHub repository and running static analysis..."}}
        result = await asyncio.to_thread(
            _get_agent("sonarqube_agent").process_query,
            query=request.query,
            session_id=session_id,
            github_token=request.github_token,
            user_config=request.user_config,
        )
        yield {
            "success": result.get("success", False),
            "query": request.query,
            "response": result.get("response", ""),
            "thinking_steps": result.get("thinking_steps", []),
            "timestamp": datetime.now().isoformat(),
            "repo_url": result.get("repo_url"),
            "requires_token": result.get("requires_token", False),
        }

    return await _stream_agent_response(
        "Sonarqube Agent",
        process(),
        user_config=request.user_config,
        session_id=session_id,
        input_text=request.query,
    )


# -------------------------------------------------- Claude Code Agent --------------------------------------------------
@app.post("/api/claude-code")
async def trigger_claude_code_agent(request: Request):
    """Claude Code Agent (SSE stream).

    End-to-end: clone configured repo, run Claude Code CLI with adaptive
    memory, push to a new branch, open a PR against base.

    Required body fields (or env fallbacks):
    - ``anthropic_api_key`` (or env ``ANTHROPIC_API_KEY``)
    - ``github_token``     (or env ``GITHUB_PERSONAL_ACCESS_TOKEN``)
    - ``repo_url``         (or env ``GITHUB_REPO_URL``)
    """
    body = await request.json()
    query = body.get("query", "")
    session_id = body.get("session_id") or str(uuid.uuid4())
    anthropic_api_key = body.get("anthropic_api_key")
    github_token = body.get("github_token")
    repo_url = body.get("repo_url")
    base_branch = body.get("base_branch")
    review_enabled = body.get("review_enabled")
    model = body.get("model")

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Cloning repo & preparing memory..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Workflow: clone -> inject memory -> Claude Code CLI -> push -> PR"}}
        loop = asyncio.get_running_loop()
        step_queue: asyncio.Queue = asyncio.Queue()

        def push_step(step):
            asyncio.run_coroutine_threadsafe(step_queue.put(step), loop)

        agent_inst = _get_agent("claude_code_agent")
        run_task = asyncio.create_task(
            agent_inst.process_query(
                query=query,
                session_id=session_id,
                anthropic_api_key=anthropic_api_key,
                github_token=github_token,
                repo_url=repo_url,
                base_branch=base_branch,
                review_enabled=review_enabled,
                model=model,
                on_thinking_step=push_step,
            )
        )
        try:
            while not run_task.done():
                try:
                    step = await asyncio.wait_for(step_queue.get(), timeout=0.1)
                    yield {"event": "thinking", "data": step}
                except asyncio.TimeoutError:
                    pass
            while True:
                try:
                    step = step_queue.get_nowait()
                    yield {"event": "thinking", "data": step}
                except asyncio.QueueEmpty:
                    break
            result = await run_task
        except Exception:
            if not run_task.done():
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass
            raise

        yield {"event": "progress", "data": {"stage": "complete", "message": "Claude Code operation complete"}}
        yield {"success": result.get("success", False), "query": query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "requires_token": result.get("requires_token", False), "repo_url": result.get("repo_url"),
                "generated_files": result.get("generated_files", []),
                "pr_url": result.get("pr_url"), "branch": result.get("branch")}

    return await _stream_agent_response(
        "Claude Code Agent",
        process(),
        user_config=body.get("user_config"),
        session_id=session_id,
        input_text=query,
        request=request,
    )


@app.get("/api/claude-code/models")
async def list_claude_code_models(request: Request, anthropic_api_key: Optional[str] = None):
    """Return Claude models available for the supplied Anthropic API key.

    Calls Anthropic's ``GET https://api.anthropic.com/v1/models`` so the UI
    can populate a model picker with the exact set this key can access. The
    key may be supplied via the ``anthropic_api_key`` query param or the
    ``X-Anthropic-Api-Key`` header; falls back to the ``ANTHROPIC_API_KEY``
    env var.
    """
    import httpx

    api_key = (
        (anthropic_api_key or "").strip()
        or (request.headers.get("X-Anthropic-Api-Key") or "").strip()
        or (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    )
    if not api_key:
        return {
            "success": False,
            "error": "Anthropic API key is required (query param, X-Anthropic-Api-Key header, or ANTHROPIC_API_KEY env).",
            "models": [],
        }

    models: List[Dict[str, Any]] = []
    next_after: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(10):  # safety cap on pagination
                params: Dict[str, Any] = {"limit": 100}
                if next_after:
                    params["after_id"] = next_after
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    params=params,
                )
                if resp.status_code != 200:
                    err_text = resp.text
                    return {
                        "success": False,
                        "error": f"Anthropic API returned {resp.status_code}: {err_text[:400]}",
                        "models": [],
                    }
                payload = resp.json()
                for m in payload.get("data", []) or []:
                    mid = m.get("id") or ""
                    if not mid:
                        continue
                    models.append({
                        "id": mid,
                        "display_name": m.get("display_name") or mid,
                        "created_at": m.get("created_at") or "",
                        "type": m.get("type") or "",
                    })
                if not payload.get("has_more"):
                    break
                next_after = payload.get("last_id")
                if not next_after:
                    break
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}", "models": []}

    return {"success": True, "models": models, "count": len(models)}


@app.get("/api/claude-code/memory")
async def list_claude_code_memory(repo_url: Optional[str] = None):
    """Return saved per-repo memory records for the Claude Code Agent.

    Without `repo_url`, returns a lightweight summary list of every memory
    file. With `repo_url`, returns the full memory record for that repo.
    """
    from agents.Claude_code_agent import memory_service

    if repo_url:
        record = memory_service.load_memory(repo_url)
        if not record:
            return {"success": False, "error": "No memory found for that repo_url", "memory": None}
        return {"success": True, "memory": record}

    MEMORY_DIR = memory_service.MEMORY_DIR
    items: List[Dict[str, Any]] = []
    if MEMORY_DIR.exists():
        for path in sorted(MEMORY_DIR.glob("*.json")):
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            notes = rec.get("run_notes") or []
            last_run = notes[-1] if notes else None
            items.append({
                "repo_url": rec.get("repo_url", ""),
                "repo_name": rec.get("repo_name", ""),
                "language": rec.get("language", ""),
                "refreshed_at": rec.get("refreshed_at", ""),
                "run_notes_count": len(notes),
                "last_run_at": (last_run or {}).get("at", ""),
                "last_run_summary": ((last_run or {}).get("summary") or "")[:200],
                "last_run_changed_files": ((last_run or {}).get("changed_files") or [])[:20],
            })
    items.sort(key=lambda x: x.get("refreshed_at", ""), reverse=True)
    return {"success": True, "count": len(items), "memories": items}


# -------------------------------------------------- Workspace context Agent (read-only repo context) --------------------------------------------------
@app.post("/api/workspace-coding")
async def trigger_workspace_coding_agent(request: Request):
    """Workspace context Agent — read-only repo context + feature-plan reports (SSE stream).

    Body params:
        query          : natural-language request
        session_id     : optional session key
        repo_url       : optional remote git URL to clone for this session
        repo_branch    : optional branch
        repo_token     : optional auth token (PAT / OAuth) for private repos
        workspace_root : optional absolute path to an already-cloned local checkout
        context_files  : optional list of paths to inject as prompt context

    The agent never writes, modifies, or pushes code.
    """
    body = await request.json()
    query = body.get("query", "")
    session_id = body.get("session_id") or str(uuid.uuid4())
    workspace_root = body.get("workspace_root")
    context_files = body.get("context_files")
    repo_url = body.get("repo_url")
    repo_branch = body.get("repo_branch")
    repo_token = body.get("repo_token")

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Initializing workspace context agent..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Binding workspace and running semantic indexer..."}}
        result = await _get_agent("workspace_coding_agent").process_query(
            query=query,
            session_id=session_id,
            workspace_root=workspace_root,
            context_files=context_files,
            repo_url=repo_url,
            repo_branch=repo_branch,
            repo_token=repo_token,
        )
        yield {"event": "progress", "data": {"stage": "complete", "message": "Workspace context lookup complete"}}
        yield {
            "success": result.get("success", False),
            "query": query,
            "response": result.get("response", ""),
            "thinking_steps": result.get("thinking_steps", []),
            "timestamp": datetime.now().isoformat(),
            "feature_plan": result.get("feature_plan"),
            "tech_stack": result.get("tech_stack"),
            "features": result.get("features"),
        }

    return await _stream_agent_response(
        "Workspace context Agent", process(), user_config=body.get("user_config"), session_id=session_id, input_text=query
    )


# -------------------------------------------------- Coder Agent --------------------------------------------------
@app.post("/api/coder-agent")
async def trigger_coder_agent(request: CoderAgentRequest):
    """Coder Agent - problem-to-standalone-HTML multi-agent pipeline (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Starting Coder Agent pipeline..."}}
        yield {
            "event": "thinking",
            "data": {
                "type": "thinking",
                "content": "Running query rewrite, architecture design, section coding, and review/test stages.",
            },
        }
        result = await _get_agent("coder_agent").process_query(
            query=request.query,
            file_content=request.file_content,
            file_type=request.file_type,
            file_name=request.file_name,
            session_id=session_id,
        )
        yield {"event": "progress", "data": {"stage": "complete", "message": "Standalone HTML generated and validated."}}
        yield {
            "success": result.success,
            "query": request.query,
            "response": result.response,
            "thinking_steps": [s.model_dump() for s in result.thinking_steps],
            "timestamp": result.timestamp,
            "session_id": result.session_id,
            "standalone_html": result.standalone_html,
            "architecture": result.architecture,
            "business_outcomes": result.business_outcomes,
        }

    return await _stream_agent_response(
        "Coder Agent",
        process(),
        user_config=request.user_config,
        session_id=session_id,
        input_text=request.query,
    )


# -------------------------------------------------- Codex SDLC Agent --------------------------------------------------
@app.post("/api/codex-sdlc")
async def trigger_codex_sdlc_agent(request: CodexSDLCRequest):
    """Codex SDLC Agent - planner + execution loop + validation + PR drafting."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Initializing Codex SDLC orchestrator..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Building task graph and binding workspace..."}}
        result = await _get_agent("codex_sdlc_agent").process_query(
            query=request.query,
            session_id=session_id,
            user_id=request.user_id,
            run_id=request.run_id,
            workspace_root=request.workspace_root,
            context_files=request.context_files,
            dry_run=request.dry_run,
            create_pr=request.create_pr,
            github_token=request.github_token,
            max_retries=request.max_retries,
            target_coverage=request.target_coverage,
        )
        yield {"event": "progress", "data": {"stage": "complete", "message": "Codex SDLC run complete"}}
        yield {
            "success": result.get("success", False),
            "query": request.query,
            "response": result.get("response", ""),
            "thinking_steps": result.get("thinking_steps", []),
            "timestamp": result.get("timestamp", datetime.now().isoformat()),
            "session_id": session_id,
            "user_id": result.get("user_id"),
            "run_id": result.get("run_id"),
            "plan": result.get("plan", []),
            "validation_summary": result.get("validation_summary", {}),
            "pr_payload": result.get("pr_payload"),
            "files_changed": result.get("files_changed", []),
            "diff": result.get("diff"),
        }

    return await _stream_agent_response(
        "Codex SDLC Agent",
        process(),
        user_config=request.user_config,
        session_id=session_id,
        input_text=request.query,
    )


# -------------------------------------------------- Unit Test Generator Agent --------------------------------------------------
@app.post("/api/unit-test")
async def trigger_unit_test_agent(request: UnitTestRequest):
    """Unit Test Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Initializing unit test agent..."}}

        ut_session = _get_agent("unit_test_agent")._get_session(session_id)
        query_lower = (request.query or "").lower()
        is_pr_query = ("github.com/" in query_lower and "/pull/" in query_lower)

        if not ut_session.get("cloned") and not is_pr_query:
            repo_url = _get_agent("github_repo_agent")._extract_repo_url(request.query)
            if repo_url:
                yield {"event": "thinking", "data": {"type": "tool_call", "content": f"Cloning repository: {repo_url}", "tool_name": "clone_repo"}}
                clone_result = await asyncio.to_thread(_get_agent("github_repo_agent")._clone_repo, repo_url, session_id)
                if clone_result["success"]:
                    gh_session = _get_agent("github_repo_agent")._get_session(session_id)
                    gh_session.update({"repo_url": repo_url, "repo_path": clone_result["path"], "repo_name": clone_result["name"], "cloned": True})
                    _get_agent("unit_test_agent").set_repo(session_id=session_id, repo_url=repo_url, repo_path=clone_result["path"], repo_name=clone_result["name"])
                    yield {"event": "thinking", "data": {"type": "tool_result", "content": f"Repository cloned: {clone_result['name']}", "tool_name": "clone_repo"}}
            else:
                gh_session = _get_agent("github_repo_agent").sessions.get(session_id)
                if gh_session and gh_session.get("cloned"):
                    _get_agent("unit_test_agent").set_repo(session_id=session_id, repo_url=gh_session["repo_url"], repo_path=gh_session["repo_path"], repo_name=gh_session.get("repo_name", "unknown"))

        if any(k in query_lower for k in ['push', 'commit', 'deploy']) and not is_pr_query:
            yield {"event": "thinking", "data": {"type": "thinking", "content": "Push intent detected — delegating to GitHub Agent"}}
            r = await asyncio.to_thread(
                _get_agent("github_repo_agent").process_query,
                query=request.query, session_id=session_id, github_token=request.github_token
            )
            yield {"success": r.get("success", False), "query": request.query, "response": r.get("response", ""),
                    "thinking_steps": r.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                    "requires_token": r.get("requires_token", False), "repo_url": r.get("repo_url")}
            return

        yield {"event": "thinking", "data": {"type": "thinking", "content": "Analyzing codebase and generating unit tests..."}}
        result = await asyncio.to_thread(
            _get_agent("unit_test_agent").process_query,
            query=request.query,
            session_id=session_id,
            github_token=request.github_token,
            user_config=request.user_config,
        )
        yield {"success": result.get("success", False), "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "repo_url": result.get("repo_url"), "task_id": result.get("task_id"),
                "requires_token": result.get("requires_token", False)}

    return await _stream_agent_response("Unit Test Agent", process(), user_config=request.user_config, session_id=session_id, input_text=request.query)


@app.get("/api/unit-test/task/{task_id}")
async def get_unit_test_task_status(task_id: str):
    """Poll the status of a long-running unit test generation task."""
    status = _get_agent("unit_test_agent").get_task_status(task_id)
    if not status:
        return {"task_id": task_id, "status": "not_found", "progress": "", "thinking_steps": []}
    return TaskStatusResponse(
        task_id=status["task_id"],
        status=status["status"],
        progress=status.get("progress", ""),
        thinking_steps=status.get("thinking_steps", []),
        response=status.get("response"),
        success=status.get("success"),
    )


# -------------------------------------------------- QA Automation Agent --------------------------------------------------
@app.post("/api/qa-automation")
async def trigger_qa_automation_agent(request: QAAutomationRequest):
    """QA Automation Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Processing QA automation request..."}}
        yield {
            "event": "thinking",
            "data": {
                "type": "thinking",
                "content": "Extracting PR URL, cloning repo at the PR branch, then driving Claude Code CLI to learn the automation suite and add tests.",
            },
        }
        result = await _get_agent("qa_automation_agent").process_query(
            query=request.query,
            session_id=session_id,
            github_token=request.github_token,
            anthropic_api_key=request.anthropic_api_key,
            user_config=request.user_config,
        )
        yield {"event": "progress", "data": {"stage": "complete", "message": "QA automation run complete"}}
        yield {
            "success": result.get("success", False),
            "query": request.query,
            "response": result.get("response", ""),
            "thinking_steps": result.get("thinking_steps", []),
            "timestamp": result.get("timestamp", datetime.now().isoformat()),
            "pr_url": result.get("pr_url"),
            "branch": result.get("branch"),
            "pushed_files": result.get("pushed_files", []),
            "files_changed": result.get("files_changed", []),
            "requires_token": result.get("requires_token", False),
        }

    return await _stream_agent_response(
        "QA Automation Agent",
        process(),
        user_config=request.user_config,
        session_id=session_id,
        input_text=request.query,
    )


# -------------------------------------------------- Web Test Agent --------------------------------------------------


# -------------------------------------------------- Shannon Security Agent --------------------------------------------------
@app.post("/api/shannon-security")
async def trigger_shannon_security_agent(request: ShannonSecurityRequest):
    """Shannon Security Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing security query..."}}
        if request.clear_history:
            _get_agent("shannon_security_agent").clear_session(session_id)
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Running security analysis..."}}
        result = await asyncio.to_thread(
            _get_agent("shannon_security_agent").process_query, query=request.query, session_id=session_id
        )
        yield {"success": result.get("success", True), "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(), "session_id": session_id}

    return await _stream_agent_response("Shannon Security Agent", process(), user_config=request.user_config, session_id=session_id, input_text=request.query)


# -------------------------------------------------- Email Agent --------------------------------------------------
@app.post("/api/email-agent")
async def trigger_email_agent(request: EmailAgentRequest):
    """Email Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Processing email request..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Extracting email details from your message..."}}
        result = await asyncio.to_thread(
            _get_agent("email_agent").process_query, user_input=request.query, session_id=session_id
        )
        yield {"success": result.get("success", True), "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "session_id": session_id, "email_sent": result.get("email_sent", False), "email_id": result.get("email_id"),
                "email_preview": result.get("email_preview")}

    return await _stream_agent_response("Email Agent", process(), user_config=request.user_config, session_id=session_id, input_text=request.query)


# -------------------------------------------------- Zoho workflow agents --------------------------------------------------
async def _stream_zoho_workflow(agent_key: str, display_name: str, request: ZohoWorkflowRequest):
    """Shared SSE runner for the three Zoho workflow agents.

    Each agent is natively async and streams its own thinking steps through the
    ``on_thinking_step`` callback, so steps reach the UI as the workflow runs
    rather than all at once at the end.
    """
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": f"Starting {display_name}..."}}

        agent = _get_agent(agent_key)
        step_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_step(step: dict):
            loop.call_soon_threadsafe(step_queue.put_nowait, step)

        task = asyncio.create_task(
            agent.process_query(request.query, session_id=session_id, on_thinking_step=on_step)
        )
        while True:
            drain = asyncio.ensure_future(step_queue.get())
            done, _pending = await asyncio.wait({drain, task}, return_when=asyncio.FIRST_COMPLETED)
            if drain in done:
                yield {"event": "thinking", "data": drain.result()}
                continue
            drain.cancel()
            break

        result = await task
        while not step_queue.empty():
            yield {"event": "thinking", "data": step_queue.get_nowait()}

        yield {
            "success": result.get("success", True),
            "query": request.query,
            "response": result.get("response", ""),
            "thinking_steps": result.get("thinking_steps", []),
            "actions": result.get("actions", []),
            "dry_run": result.get("dry_run", True),
            "workflow": result.get("workflow", ""),
            "data": result.get("data", {}),
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
        }

    return await _stream_agent_response(
        display_name,
        process(),
        user_config=request.user_config,
        session_id=session_id,
        input_text=request.query,
    )


@app.post("/api/zoho-email-meeting-agent")
async def trigger_zoho_email_meeting_agent(request: ZohoWorkflowRequest):
    """Zoho Email Meeting Agent (SSE stream): email -> calendar event, confirmation, CRM task."""
    return await _stream_zoho_workflow("zoho_email_meeting_agent", "Zoho Email Meeting Agent", request)


@app.post("/api/zoho-support-ticket-agent")
async def trigger_zoho_support_ticket_agent(request: ZohoWorkflowRequest):
    """Zoho Support Ticket Agent (SSE stream): Desk ticket -> Cliq alert, CRM task, customer reply."""
    return await _stream_zoho_workflow("zoho_support_ticket_agent", "Zoho Support Ticket Agent", request)


@app.post("/api/zoho-new-customer-agent")
async def trigger_zoho_new_customer_agent(request: ZohoWorkflowRequest):
    """Zoho New Customer Agent (SSE stream): CRM contact -> welcome email, intro call, Cliq notice."""
    return await _stream_zoho_workflow("zoho_new_customer_agent", "Zoho New Customer Agent", request)


# -------------------------------------------------- Langfuse agent --------------------------------------------------
@app.post("/api/debug-trace")
@app.post("/debug-trace")
async def trigger_trace_debugger_agent(request: TraceDebuggerRequest):
    """Langfuse agent (SSE stream). Accepts any open-ended query: search, debug, inspect, browse, etc."""
    query = (request.trace_id or request.query or "").strip()

    async def process():
        query_fallback = (
            query
            if query
            else "Show me the latest traces and a summary of recent activity"
        )
        async for item in _get_agent("trace_debugger_agent").debug_trace_stream(query_fallback):
            if isinstance(item, dict) and item.get("event"):
                yield item
                continue
            if isinstance(item, dict):
                operation = item.get("operation", "")
                stage_msg = f"Completed: {operation}" if operation else "Processing complete"
                yield {"event": "progress", "data": {"stage": "done", "message": stage_msg}}
                if not item.get("timestamp"):
                    item["timestamp"] = datetime.now().isoformat()
                yield item

    return await _stream_agent_response("Langfuse agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=query)



# -------------------------------------------------- Code Sandbox Agent --------------------------------------------------
@app.post("/api/code-sandbox")
async def trigger_code_sandbox_agent(request: SandboxRequest):
    """Code Sandbox Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Setting up code sandbox..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Cloning repository and installing dependencies..."}}
        result = await asyncio.to_thread(
            _get_agent("code_sandbox_agent").process_query, query=request.query, session_id=session_id
        )
        yield {"event": "progress", "data": {"stage": "complete", "message": "Sandbox ready"}}
        yield {"success": result.get("success", False), "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "stackblitz_repo": result.get("stackblitz_repo"), "status": result.get("status")}

    return await _stream_agent_response("Code Sandbox Agent", process(), user_config=request.user_config, session_id=session_id, input_text=request.query)


@app.post("/api/web-test")
async def trigger_web_test_agent(request: WebTestRequest):
    """Web Test Agent (SSE stream)."""
    session_id = request.session_id or str(uuid.uuid4())

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing webpage..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Scraping page structure and extracting features..."}}
        result = await asyncio.to_thread(
            _get_agent("web_test_agent").process_query, query=request.query, session_id=session_id, clear_history=request.clear_history
        )
        yield {"event": "progress", "data": {"stage": "generating", "message": "Generating test cases and scripts..."}}
        yield {"success": result.get("success", True), "query": request.query, "response": result.get("response", ""),
                "thinking_steps": result.get("thinking_steps", []), "timestamp": datetime.now().isoformat(),
                "session_id": result.get("session_id", session_id)}

    return await _stream_agent_response("Web Test Agent", process(), user_config=request.user_config or _SERVER_GLOBAL_CHAT_CONFIG or None, session_id=session_id, input_text=request.query)


@app.post("/api/web-test/run-playwright-spec", response_model=WebTestPlaywrightRunResponse)
async def run_web_test_playwright_spec(request: WebTestPlaywrightRunRequest):
    """Run a Playwright TypeScript spec (Web Test Agent output) via ``npx`` on the server host.

    Requires Node.js on PATH. Opens a real browser when *headed* is true (on the machine
    running the API, not the user's laptop unless that is the same machine).
    """
    from agents.Web_test_agent.playwright_spec_runner import run_playwright_typescript_spec

    result = await asyncio.to_thread(
        run_playwright_typescript_spec,
        request.spec_source,
        headed=request.headed,
        timeout_sec=request.timeout_sec,
    )
    return WebTestPlaywrightRunResponse(**result)


# -------------------------------------------------- MongoDB Atlas KB Agent --------------------------------------------------
@app.post("/api/mongodb-rag")
async def trigger_mongodb_rag_agent(request: MongoRAGChatRequest):
    """MongoDB Atlas KB Agent (SSE stream)."""

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Processing MongoDB RAG request..."}}
        if request.mongodb_uri:
            yield {"event": "thinking", "data": {"type": "tool_call", "content": "Connecting to MongoDB Atlas...", "tool_name": "mongodb_connect"}}
        elif request.file_content or request.raw_text:
            yield {"event": "thinking", "data": {"type": "thinking", "content": "Chunking and embedding document content..."}}
        else:
            yield {"event": "thinking", "data": {"type": "thinking", "content": "Performing semantic search and generating answer..."}}

        result = await asyncio.to_thread(
            _get_agent("mongodb_rag_agent").process_chat, {
                "query": request.query, "session_id": request.session_id or f"mongo-{uuid.uuid4().hex[:8]}",
                "mongodb_uri": request.mongodb_uri, "file_content": request.file_content,
                "file_type": request.file_type, "file_name": request.file_name,
                "raw_text": request.raw_text, "collection_name": request.collection_name or "rag_documents",
                "top_k": request.top_k,
            }
        )
        yield {"success": result.get("success", False), "response": result.get("response", "No response generated"),
                "query": result.get("query", request.query), "thinking_steps": result.get("thinking_steps", []),
                "timestamp": result.get("timestamp", datetime.now().isoformat()), "phase": result.get("phase", ""),
                "databases": result.get("databases", []), "chunks_count": result.get("chunks_count", 0),
                "sources": result.get("sources", []), "requires_uri": result.get("requires_uri", False),
                "requires_upload": result.get("requires_upload", False), "connected": result.get("connected", False),
                "ingested": result.get("ingested", False)}

    return await _stream_agent_response("MongoDB Atlas KB Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


# -------------------------------------------------- SQL DB Agent --------------------------------------------------
@app.post("/api/sql-db")
async def trigger_sql_db_agent(request: SqlDbChatRequest):
    """SQL DB Agent — NL→SQL, ERD, governed CRUD (SSE stream with per-step progress)."""
    # Pre-load outside the generator so the lazy import (and its module-level
    # dotenv load) runs before apply_user_config injects per-request env vars.
    sql_agent = _get_agent("sql_db_agent")

    async def process():
        req_data = {
            "query": request.query,
            "session_id": request.session_id or f"sql-{uuid.uuid4().hex[:10]}",
            "show_sql": request.show_sql,
            "clear_history": request.clear_history,
            "page": request.page,
            "page_size": request.page_size,
        }
        gen = sql_agent.process_chat_stream(req_data)

        q: queue.Queue = queue.Queue()
        _SENTINEL = object()
        # Inherit LLM trace ContextVars (queue + loop) in the worker thread so
        # sync_call_with_continuation can emit llm_call / llm_response to SSE.
        _stream_ctx = contextvars.copy_context()

        def _produce():
            def _run_gen():
                try:
                    for item in gen:
                        q.put(item)
                except Exception as exc:
                    q.put(exc)
                finally:
                    q.put(_SENTINEL)

            _stream_ctx.run(_run_gen)

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _produce)

        while True:
            try:
                item = await asyncio.to_thread(q.get, timeout=0.15)
            except Exception:
                await asyncio.sleep(0.05)
                continue
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            if isinstance(item, dict) and "event" in item:
                yield item
            else:
                result = item
                final = {
                    "success": result.get("success", False),
                    "response": result.get("response", ""),
                    "query": result.get("query", request.query),
                    "thinking_steps": result.get("thinking_steps", []),
                    "timestamp": result.get("timestamp", datetime.now().isoformat()),
                    "generated_sql": result.get("generated_sql"),
                    "result_preview": result.get("result_preview"),
                    "mermaid_erd": result.get("mermaid_erd"),
                    "large_result": result.get("large_result"),
                    "page_info": result.get("page_info"),
                    "explain_warnings": result.get("explain_warnings", []),
                    "cached": result.get("cached", False),
                }
                if result.get("_emit_reset_before_response_chunks"):
                    final["_emit_reset_before_response_chunks"] = True
                yield final

    return await _stream_agent_response("SQL DB Agent", process(), user_config=request.user_config, session_id=request.session_id, input_text=request.query)


# Browser automation HTML reports live here (same as Browser_executor.LOGS_DIR)
_BROWSER_AGENT_LOGS_DIR = (base_path / "agents" / "Browser_agent" / "logs").resolve()


@app.get("/api/browser-agent/html-report")
async def download_browser_html_report(file: str):
    """Download a saved browser automation HTML report. Only basenames under Browser_agent/logs are allowed."""
    raw = (file or "").strip()
    name = Path(raw).name
    if not raw or name != raw or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid report path")
    if not (name.startswith("report_") and name.endswith(".html")):
        raise HTTPException(status_code=400, detail="Invalid report filename")
    allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.")
    if not all(c in allowed_chars for c in name):
        raise HTTPException(status_code=400, detail="Invalid report filename")
    path = (_BROWSER_AGENT_LOGS_DIR / name).resolve()
    try:
        path.relative_to(_BROWSER_AGENT_LOGS_DIR)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid report location")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    # inline: so the chat iframe (Full Report) can render; attachment forces download in many browsers
    return FileResponse(
        path,
        media_type="text/html; charset=utf-8",
        filename=name,
        headers={"Content-Disposition": f'inline; filename="{name}"'},
    )


class StandaloneHtmlPreviewPayload(BaseModel):
    html: str


@app.post("/api/preview/standalone-html")
async def publish_standalone_html_preview(payload: StandaloneHtmlPreviewPayload):
    """Store HTML temporarily and return a path for a shareable GET URL (same origin as the API)."""
    html = payload.html or ""
    encoded = html.encode("utf-8")
    if len(encoded) == 0:
        raise HTTPException(status_code=400, detail="HTML is empty.")
    if len(encoded) > _STANDALONE_HTML_PREVIEW_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"HTML exceeds maximum size ({_STANDALONE_HTML_PREVIEW_MAX_BYTES // 1024}KB).",
        )
    preview_id = uuid.uuid4().hex
    _standalone_html_preview_store.set(preview_id, html)
    return {"preview_id": preview_id, "path": f"/api/preview/standalone-html/{preview_id}"}


@app.get("/api/preview/standalone-html/{preview_id}")
async def serve_standalone_html_preview(preview_id: str):
    token = (preview_id or "").strip().lower()
    if len(token) != 32 or any(ch not in "0123456789abcdef" for ch in token):
        raise HTTPException(status_code=400, detail="Invalid preview id")
    html = _standalone_html_preview_store.get(token)
    if html is None:
        raise HTTPException(status_code=404, detail="Preview not found or expired.")
    return HTMLResponse(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="preview.html"'},
    )


@app.post("/api/browser-agent/close")
async def close_browser_agent():
    """Force-close all browser instances managed by the Browser Automation Agent."""
    from agents.Browser_agent.tools.browser_pool import (
        BrowserPool,
        _kill_playwright_browser_processes,
        _kill_stale_chrome_for_profile,
    )
    from agents.Browser_agent.agent import _default_persistent_profile_dir
    try:
        # Close sync branches (thread-safe)
        BrowserPool.force_close_all_sync()
        # Close async branches
        await BrowserPool.async_force_close_all()
        # As a final safety net, kill any Chrome using the default profile dir
        # (covers cases where the pool lost track of the process)
        killed_count = 0
        try:
            _kill_stale_chrome_for_profile(str(_default_persistent_profile_dir()))
            killed_count += _kill_playwright_browser_processes(str(_default_persistent_profile_dir()))
        except Exception:
            pass
        return {
            "success": True,
            "message": (
                "All browser sessions closed."
                if killed_count <= 0
                else f"All browser sessions closed (terminated {killed_count} lingering process(es))."
            ),
        }
    except Exception as exc:
        _api_log.warning("browser-agent/close error: %s", exc)
        # Even if pool cleanup failed, still try the direct kill
        try:
            _kill_stale_chrome_for_profile(str(_default_persistent_profile_dir()))
            _kill_playwright_browser_processes(str(_default_persistent_profile_dir()))
        except Exception:
            pass
        return {"success": True, "message": f"Browser cleanup attempted (some errors: {exc})."}


# -------------------------------------------------- Browser Automation Agent --------------------------------------------------
def _browser_headless_from_user_config(
    user_config: Optional[dict], request_headless: bool
) -> tuple[bool, Optional[dict]]:
    """Strip BROWSER_HEADLESS from user_config (not an env var) and return resolved headless flag."""
    if not user_config:
        return request_headless, user_config
    uc = dict(user_config)
    raw = uc.pop("BROWSER_HEADLESS", None)
    if raw is None:
        return request_headless, uc
    s = str(raw).strip().lower()
    if not s:
        return request_headless, uc
    headless = s in ("true", "1", "yes")
    return headless, uc


@app.post("/api/browser-agent")
async def trigger_browser_agent(request: BrowserChatRequest):
    """Browser Automation Agent — natural language to real browser execution (SSE stream)."""
    # Force a brand-new browser session per incoming prompt.
    session_id = str(uuid.uuid4())
    headless, user_config_sanitized = _browser_headless_from_user_config(
        request.user_config, request.headless
    )

    reset_warning: Optional[str] = None
    try:
        from agents.Browser_agent.tools.browser_pool import (
            BrowserPool,
            _kill_playwright_browser_processes,
            _kill_stale_chrome_for_profile,
        )
        from agents.Browser_agent.agent import _default_persistent_profile_dir

        # Hard reset all tracked Playwright branches before handling the new prompt.
        BrowserPool.force_close_all_sync()
        await BrowserPool.async_force_close_all()
        try:
            _kill_stale_chrome_for_profile(str(_default_persistent_profile_dir()))
            _kill_playwright_browser_processes(str(_default_persistent_profile_dir()))
        except Exception:
            pass
    except Exception as exc:
        reset_warning = str(exc)

    async def process():
        if reset_warning:
            yield {
                "event": "progress",
                "data": {
                    "stage": "init",
                    "message": f"Attempted to reset prior browser sessions before starting a new session (warning: {reset_warning}).",
                },
            }

        if (request.rerun_standalone_script or "").strip():
            if request.replay_steps_executed:
                yield {
                    "event": "progress",
                    "data": {
                        "stage": "init",
                        "message": "Replaying recorded browser steps (live screenshots + HTML report)…",
                    },
                }
            else:
                yield {"event": "progress", "data": {"stage": "init", "message": "Running exported Playwright script…"}}
        else:
            yield {"event": "progress", "data": {"stage": "init", "message": "Analyzing your browser task…"}}

        q: queue.Queue = queue.Queue()

        def sse_emit(ev: str, data: dict):
            q.put(("stream", ev, data))

        def worker():
            try:
                result = _get_agent("browser_agent").process_chat(
                    {
                        "query": request.query,
                        "session_id": session_id,
                        "clear_history": True,
                        "headless": headless,
                        "keep_browser_session": False,
                        "remember_logins": request.remember_logins,
                        "persistent_profile_dir": request.persistent_profile_dir,
                        "cdp_endpoint": request.cdp_endpoint,
                        "enable_step_critic": request.enable_step_critic,
                        "use_vision": request.use_vision,
                        "use_grounded_verifier": request.use_grounded_verifier,
                        "rerun_standalone_script": request.rerun_standalone_script,
                        "replay_steps_executed": request.replay_steps_executed,
                        "_sse_emit": sse_emit,
                    }
                )
                q.put(("final", result))
            except Exception as exc:
                q.put(("fatal", exc))

        threading.Thread(target=worker, daemon=True).start()

        result = None
        while True:
            kind, *rest = await asyncio.to_thread(q.get)
            if kind == "stream":
                ev, data = rest[0], rest[1]
                if ev == "thinking":
                    yield {"event": "thinking", "data": data}
                elif ev == "progress":
                    yield {"event": "progress", "data": data}
                elif ev == "browser_screenshot":
                    yield {"event": "browser_screenshot", "data": data}
                await asyncio.sleep(0)
            elif kind == "final":
                result = rest[0]
                break
            elif kind == "fatal":
                raise rest[0]

        if result is None:
            raise RuntimeError("Browser agent finished without result")

        yield {"event": "progress", "data": {"stage": "complete", "message": "Browser automation complete."}}
        _hr = result.get("html_report") or ""
        _hr_name = Path(_hr).name if _hr else None
        yield {
            "success": result.get("success", False),
            "response": result.get("response", ""),
            "query": request.query,
            "thinking_steps": [],
            "timestamp": result.get("timestamp", datetime.now().isoformat()),
            "steps_executed": result.get("steps_executed", []),
            "generated_script": result.get("generated_script"),
            "execution_log": result.get("execution_log"),
            "session_id": result.get("session_id", session_id),
            "session_history_preview": result.get("session_history_preview"),
            "html_report_file": _hr_name,
        }

    return await _stream_agent_response(
        "Browser Automation Agent", process(), user_config=user_config_sanitized, session_id=session_id,
        input_text=request.query,
    )


@app.get("/api/webmcp-agent/health")
async def webmcp_agent_health():
    """Whether the WebMCP agent feature flag is on (does not call the local bridge)."""
    from agents.WebMCP_agent.agent import WEBMCP_AGENT_ENABLED
    from agents.WebMCP_agent.tools.bridge_client import WEBMCP_AGENT_VERSION

    return {
        "enabled": WEBMCP_AGENT_ENABLED,
        "agent_version": WEBMCP_AGENT_VERSION,
    }


class WebMcpBridgePingRequest(BaseModel):
    bridge_base_url: str
    bridge_token: str

    @field_validator("bridge_base_url", "bridge_token")
    @classmethod
    def _strip_nonempty_bridge_ping(cls, v: str) -> str:
        if v is None:
            raise ValueError("bridge_base_url and bridge_token are required")
        s = str(v).strip()
        if not s:
            raise ValueError("bridge_base_url and bridge_token are required")
        return s


@app.post("/api/webmcp-agent/bridge-ping")
async def webmcp_bridge_ping(body: WebMcpBridgePingRequest):
    """Test connectivity from the API host to the user's local WebMCP bridge (extension must be connected)."""

    def _ping() -> dict:
        from agents.WebMCP_agent.tools.bridge_client import WebMcpBridgeClient, WebMcpBridgeError

        url = body.bridge_base_url.strip()
        tok = body.bridge_token.strip()
        try:
            with WebMcpBridgeClient(url, tok, timeout_sec=20.0) as client:
                health = client.health()
                session = client.session_info()
                tools = client.list_tools()
                return {
                    "ok": True,
                    "health": health,
                    "session": session,
                    "tool_count": len(tools),
                }
        except WebMcpBridgeError as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return await asyncio.to_thread(_ping)


@app.post("/api/webmcp-agent")
async def trigger_webmcp_agent(request: WebMcpChatRequest):
    """WebMCP Agent — natural language goals via tools in the user's active Chrome tab (local bridge)."""
    session_id = request.session_id or str(uuid.uuid4())
    uc = dict(request.user_config or {})
    bridge_url = request.bridge_base_url
    bridge_token = request.bridge_token
    user_config_sanitized = uc

    async def process():
        yield {"event": "progress", "data": {"stage": "init", "message": "Connecting to WebMCP bridge…"}}
        q: queue.Queue = queue.Queue()

        def sse_emit(ev: str, data: dict):
            q.put(("stream", ev, data))

        def worker():
            try:
                result = _get_agent("webmcp_agent").process_chat(
                    {
                        "query": request.query,
                        "session_id": session_id,
                        "clear_history": request.clear_history,
                        "bridge_base_url": bridge_url,
                        "bridge_token": bridge_token,
                        "allowed_hosts": request.allowed_hosts,
                        "require_host_allowlist": request.require_host_allowlist,
                        "max_steps": request.max_steps,
                        "bridge_timeout_sec": request.bridge_timeout_sec,
                        "wall_time_sec": request.wall_time_sec,
                        "_sse_emit": sse_emit,
                    }
                )
                q.put(("final", result))
            except Exception as exc:
                q.put(("fatal", exc))

        threading.Thread(target=worker, daemon=True).start()

        result = None
        while True:
            kind, *rest = await asyncio.to_thread(q.get)
            if kind == "stream":
                ev, data = rest[0], rest[1]
                if ev == "thinking":
                    yield {"event": "thinking", "data": data}
                elif ev == "progress":
                    yield {"event": "progress", "data": data}
                await asyncio.sleep(0)
            elif kind == "final":
                result = rest[0]
                break
            elif kind == "fatal":
                raise rest[0]

        if result is None:
            raise RuntimeError("WebMCP agent finished without result")

        yield {"event": "progress", "data": {"stage": "complete", "message": "WebMCP run complete."}}
        yield {
            "success": result.get("success", False),
            "response": result.get("response", ""),
            "query": request.query,
            "thinking_steps": [],
            "timestamp": result.get("timestamp", datetime.now().isoformat()),
            "session_id": result.get("session_id", session_id),
            "tool_calls": result.get("tool_calls", 0),
            "webmcp_agent_version": result.get("webmcp_agent_version"),
            "bridge_version": result.get("bridge_version"),
            "session_url": result.get("session_url"),
        }

    return await _stream_agent_response(
        "WebMCP Agent",
        process(),
        user_config=user_config_sanitized,
        session_id=session_id,
        input_text=request.query,
    )


# -------------------------------------------------- MongoDB RAG Context Retrieval --------------------------------------------------
class MongoRAGContextRequest(BaseModel):
    query: str
    session_id: str
    collection_name: Optional[str] = "rag_documents"
    top_k: Optional[int] = 5

@app.post("/api/mongodb-rag/context")
async def retrieve_mongo_rag_context(request: MongoRAGContextRequest):
    """Lightweight endpoint: retrieves relevant RAG context chunks without LLM generation."""
    try:
        result = _get_agent("mongodb_rag_agent").retrieve_context(
            session_id=request.session_id,
            user_query=request.query,
            collection_name=request.collection_name or "rag_documents",
            top_k=request.top_k or 5,
        )
        return result
    except Exception as e:
        return {"success": False, "context": "", "chunks": 0, "error": str(e)}


# -------------------------------------------------- External Agent Proxy --------------------------------------------------

def _build_external_payload(template: str, query: str, session_id: str) -> dict:
    """Build payload from template with safe JSON value substitution."""
    import json as _json
    if template and template.strip():
        parsed = _json.loads(template)
        def _replace_placeholders(obj):
            if isinstance(obj, str):
                return obj.replace("{{query}}", query).replace("{{session_id}}", session_id)
            elif isinstance(obj, dict):
                return {k: _replace_placeholders(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_replace_placeholders(item) for item in obj]
            return obj
        return _replace_placeholders(parsed)
    return {"query": query, "session_id": session_id}


def _external_request_kwargs(payload: Any, payload_format: str, headers: dict) -> tuple[dict, dict]:
    """Return headers and httpx request kwargs for an external agent call.

    Form-data templates use the same JSON-shaped object in the catalog, but
    are sent as multipart form fields so external services can receive them
    through regular form parsing.
    """
    import json as _json

    normalized_format = (payload_format or "json").strip().lower().replace("-", "_")
    if normalized_format in {"form", "form_data", "multipart", "multipart_form_data"}:
        form_payload = payload if isinstance(payload, dict) else {"value": payload}
        fields = {}
        for key, value in form_payload.items():
            if isinstance(value, (dict, list)):
                fields[str(key)] = _json.dumps(value, separators=(",", ":"))
            elif value is None:
                fields[str(key)] = ""
            else:
                fields[str(key)] = str(value)
        form_headers = {
            str(key): str(value)
            for key, value in (headers or {}).items()
            if str(key).lower() != "content-type"
        }
        return form_headers, {
            "files": {key: (None, value) for key, value in fields.items()},
        }

    json_headers = dict(headers or {})
    json_headers.setdefault("Content-Type", "application/json")
    return json_headers, {"json": payload}


def _extract_external_response(ext_response) -> str:
    """Extract response text from an external API response."""
    import json as _json
    try:
        result = ext_response.json()
        response_text = result.get("response") or result.get("result") or result.get("output") or result.get("answer") or result.get("text") or result.get("message") or result.get("data") or _json.dumps(result, indent=2)
        if isinstance(response_text, (dict, list)):
            response_text = _json.dumps(response_text, indent=2)
        return str(response_text)
    except Exception:
        return ext_response.text


def _get_external_agent_config(agent_id: str) -> Optional[dict]:
    """Load external agent config from catalog. Returns None if not found or not external."""
    try:
        from agents_catalog_db import get_agent_by_id

        agent = get_agent_by_id(agent_id)
        if agent and agent.get("external_api_url"):
            return agent
    except Exception:
        pass
    return None


class ExternalAgentRequest(BaseModel):
    query: str
    agent_id: str
    session_id: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None

async def _llm_call_async(
    prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    model: Optional[str] = None,
) -> str:
    """Lightweight async LLM call for the external agent layer."""
    from agents.llm_continuation import async_call_with_continuation, set_current_agent
    set_current_agent("External Agent LLM")
    api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
    bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN")
    endpoint_url = os.getenv("PWC_GENAI_ENDPOINT_URL") or os.getenv(
        "GEMINI_API_ENDPOINT", "https://genai-sharedservice-americas.pwc.com/completions"
    )
    if not api_key:
        raise ValueError(
            "LLM API key not configured — set PWC_GENAI_API_KEY (and bearer token) in agent configuration "
            "(not server .env)."
        )
    headers = {"accept": "application/json", "API-Key": api_key, "Content-Type": "application/json"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request_body = {
        "model": model or "",
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 1,
        "stream": False,
    }
    return await async_call_with_continuation(endpoint_url, headers, request_body, prompt)


def _build_payload_adaptation_prompt(user_query: str, agent_name: str, agent_description: str,
                                      payload_template: str, external_url: str, session_id: str = "default") -> str:
    """Build LLM prompt to adapt user query into the external API's payload format."""
    return f"""You are an intelligent API adapter. Your job is to take a user's natural language query and produce the correct JSON payload for an external API.

**External Agent**: {agent_name}
**Agent Description**: {agent_description}
**API Endpoint**: {external_url}
**Payload Template** (with placeholders):
```json
{payload_template if payload_template else '{"query": "{{{{query}}}}"}'}
```

The template uses `{{{{query}}}}` as a placeholder for the user's message and `{{{{session_id}}}}` for the session identifier.

**User's Query**: {user_query}
**Session ID**: {session_id}

Your task:
1. Analyze the user's query and the payload template
2. Replace `{{{{query}}}}` with the user's query text (keep it faithful to what the user asked)
3. Replace `{{{{session_id}}}}` with "{session_id}"
4. Keep all other fields from the template as-is
5. If the template has specific fields that need adapting beyond simple substitution, adapt them intelligently

Return ONLY the final JSON payload — no explanation, no markdown fences, just the raw JSON object."""


def _build_response_formatting_prompt(raw_response: str, agent_name: str, user_query: str) -> str:
    """Build LLM prompt to format the external API's raw response into a user-friendly answer."""
    truncated = raw_response[:8000] if len(raw_response) > 8000 else raw_response
    return f"""You are a response formatter. Present the following API response to the user exactly as the agent intended it.

**Raw API Response**:
{truncated}

Rules:
1. Present the response content faithfully — do NOT change the meaning, do NOT add new information, do NOT answer the user's question yourself
2. If the response is already readable text, present it as-is with only light markdown formatting (headings, lists, code blocks where appropriate)
3. If the response is JSON, extract the main content field (response/message/answer/text/output/data) and present it
4. If the response contains a follow-up question from the agent, present that question exactly as-is
5. Do NOT merge the user's query text into the response
6. Do NOT mention "external API" or "raw response"
7. Keep the response concise and clean

Formatted response:"""


@app.post("/api/external-agent")
async def trigger_external_agent(request: ExternalAgentRequest):
    """LLM-powered proxy for external agents. Uses LLM to adapt queries and format responses."""
    import json as _json

    agent_config = _get_external_agent_config(request.agent_id)
    if not agent_config:
        async def error_stream():
            yield f"data: {_json.dumps({'event': 'error', 'data': {'message': f'Agent {request.agent_id} is not configured as an external agent.'}})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    agent_name = agent_config.get("name", request.agent_id)
    agent_description = agent_config.get("description", "External AI agent")
    external_url = agent_config["external_api_url"]
    payload_template = agent_config.get("external_payload_template", "")
    external_headers = agent_config.get("external_headers", {})
    external_method = agent_config.get("external_method", "POST").upper()
    payload_format = agent_config.get("external_payload_format", "json")

    async def event_stream():
        try:
            async with _agent_lock(agent_name):
                from agents.llm_continuation import set_current_session, set_current_user
                set_current_session(request.session_id)
                set_current_user(None)

                _ext_effective = merge_configs(agent_name, request.user_config)
                _ext_effective = apply_auto_llm_provider_for_mcp(
                    _ext_effective,
                    get_catalog_agent_by_display_name(agent_name),
                )
                _ext_isolate = bool(get_catalog_env_keys_for_agent(agent_name))
                with apply_user_config(
                    _ext_effective,
                    agent_cache=_agent_cache,
                    agent_display_name=agent_name,
                    isolate_catalog_environment=_ext_isolate,
                ):
                    yield f"data: {_json.dumps({'event': 'start', 'data': {'agent': agent_name}})}\n\n"

                    try:
                        if payload_template and payload_template.strip() and "{{query}}" in payload_template:
                            payload = _build_external_payload(payload_template, request.query, request.session_id or "default")
                        else:
                            yield f"data: {_json.dumps({'event': 'thinking', 'data': {'content': f'Analyzing your query for {agent_name}...'}})}\n\n"
                            try:
                                adapt_prompt = _build_payload_adaptation_prompt(
                                    request.query, agent_name, agent_description, payload_template, external_url, request.session_id or "default"
                                )
                                llm_payload_text = await _llm_call_async(adapt_prompt, max_tokens=1024, temperature=0.1)
                                llm_payload_text = llm_payload_text.strip()
                                if llm_payload_text.startswith("```"):
                                    lines = llm_payload_text.split("\n")
                                    lines = [l for l in lines if not l.strip().startswith("```")]
                                    llm_payload_text = "\n".join(lines)
                                payload = _json.loads(llm_payload_text)
                            except Exception as e:
                                print(f"[ExternalAgent] LLM payload adaptation failed ({e}), falling back to default payload")
                                payload = {"query": request.query, "session_id": request.session_id or "default"}

                        yield f"data: {_json.dumps({'event': 'thinking', 'data': {'content': f'Calling {agent_name} API...'}})}\n\n"

                        req_headers = {"Content-Type": "application/json"}
                        if external_headers and isinstance(external_headers, dict):
                            req_headers.update(external_headers)
                        req_headers, request_kwargs = _external_request_kwargs(
                            payload, payload_format, req_headers
                        )

                        async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
                            ext_response = await client.request(
                                external_method, external_url, headers=req_headers, **request_kwargs
                            )
                            ext_response.raise_for_status()

                        raw_response = _extract_external_response(ext_response)
                        print(f"[ExternalAgent] Payload sent: {_json.dumps(payload)[:500]}")
                        print(f"[ExternalAgent] Raw response: {raw_response[:500]}")

                        is_json_blob = raw_response.strip().startswith("{") or raw_response.strip().startswith("[")
                        needs_formatting = is_json_blob or len(raw_response) > 2000

                        if needs_formatting:
                            yield f"data: {_json.dumps({'event': 'thinking', 'data': {'content': 'Formatting response...'}})}\n\n"
                            try:
                                format_prompt = _build_response_formatting_prompt(raw_response, agent_name, request.query)
                                formatted_response = await _llm_call_async(format_prompt, max_tokens=4096, temperature=0.3)
                            except Exception as e:
                                print(f"[ExternalAgent] LLM response formatting failed ({e}), using raw response")
                                formatted_response = raw_response
                        else:
                            formatted_response = raw_response

                        chunk_size = 80
                        for i in range(0, len(formatted_response), chunk_size):
                            chunk = formatted_response[i:i + chunk_size]
                            yield f"data: {_json.dumps({'event': 'response_chunk', 'data': {'chunk': chunk}})}\n\n"
                            await asyncio.sleep(0.02)

                        yield f"data: {_json.dumps({'event': 'done', 'data': {'response': formatted_response, 'agent': agent_name}})}\n\n"

                    except httpx.HTTPStatusError as e:
                        error_msg = f"External API returned status {e.response.status_code}: {e.response.text[:500]}"
                        yield f"data: {_json.dumps({'event': 'error', 'data': {'message': error_msg}})}\n\n"
                    except httpx.ConnectError:
                        from urllib.parse import urlparse
                        external_host = urlparse(external_url).netloc or external_url
                        error_msg = (
                            f"Cannot reach external agent at {external_host}. "
                            "The endpoint refused or blocked the server connection. "
                            "Make the endpoint reachable from the deployed server, "
                            "or update the agent configuration to a public HTTPS URL."
                        )
                        print(f"[ExternalAgent] Connection failed: {external_host}")
                        yield f"data: {_json.dumps({'event': 'error', 'data': {'message': error_msg}})}\n\n"
                    except httpx.TimeoutException:
                        from urllib.parse import urlparse
                        external_host = urlparse(external_url).netloc or external_url
                        error_msg = (
                            f"External agent at {external_host} timed out before responding. "
                            "Check that the endpoint is healthy and reachable from the deployed server."
                        )
                        print(f"[ExternalAgent] Request timed out: {external_host}")
                        yield f"data: {_json.dumps({'event': 'error', 'data': {'message': error_msg}})}\n\n"
                    except httpx.RequestError as e:
                        error_msg = f"External agent request failed: {str(e)}"
                        print(f"[ExternalAgent] Request error: {error_msg}")
                        yield f"data: {_json.dumps({'event': 'error', 'data': {'message': error_msg}})}\n\n"
                    except _json.JSONDecodeError as e:
                        yield f"data: {_json.dumps({'event': 'error', 'data': {'message': f'Invalid payload JSON template: {str(e)}'}})}\n\n"
                    except Exception as e:
                        yield f"data: {_json.dumps({'event': 'error', 'data': {'message': f'Error calling external agent: {str(e)}'}})}\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'event': 'error', 'data': {'message': str(e)}})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# -------------------------------------------------- Global Chat Router --------------------------------------------------
@app.post("/api/global-chat")
async def trigger_global_chat(request: GlobalChatRequest, authorization: Optional[str] = Header(None)):
    """Smart routing agent (SSE stream). Analyzes query, routes to best agent, persists to DB."""

    user = _optional_verify_user(authorization)
    allowed_agent_ids = None
    if user:
        allowed_agent_ids = user.get("agent_permissions") or []

    session_id = request.session_id
    skip_save = request.skip_save
    conversation_history = None

    if not skip_save:
        session = await chat_db.async_get_session(session_id) if session_id else None
        if not session:
            session_id = session_id or str(uuid.uuid4())
            title = chat_db.generate_title_from_query(request.query)
            session = await chat_db.async_create_session(session_id, title)
        import re
        safe_query = re.sub(r'(ghp_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})', '[GITHUB_TOKEN]', request.query)
        await chat_db.async_save_message(session_id, "user", safe_query)
        previous_messages = await chat_db.async_get_messages(session_id)
        conversation_history = [
            {"role": m["role"], "content": m["content"], "routed_to": m.get("routed_to")}
            for m in previous_messages[:-1]
        ] if len(previous_messages) > 1 else None
    else:
        session_id = session_id or str(uuid.uuid4())
        session = {"title": "New Chat"}

    async def process():
        yield {"event": "progress", "data": {"stage": "routing", "message": "Analyzing your query and selecting the best agent..."}}
        yield {"event": "thinking", "data": {"type": "thinking", "content": "Using AI to intelligently analyze query intent..."}}

        result = await _get_agent("router_agent").route_and_respond(
            query=request.query, session_id=session_id,
            conversation_history=conversation_history, github_token=request.github_token,
            file_content=request.file_content, file_type=request.file_type,
            file_name=request.file_name, target_agent=request.target_agent,
            allowed_agent_ids=allowed_agent_ids)

        if not skip_save:
            metadata = {}
            if result.get("latest_news_cards"):
                metadata["latest_news_cards"] = result["latest_news_cards"]
            await chat_db.async_save_message(
                session_id=session_id, role="assistant", content=result.get("response", ""),
                thinking_steps=result.get("thinking_steps"), routed_to=result.get("routed_to"),
                bpmn_xml=result.get("bpmn_xml"), metadata=metadata if metadata else None)
            if session.get("title") == "New Chat":
                await chat_db.async_update_session_title(session_id, chat_db.generate_title_from_query(request.query))

        result["session_id"] = session_id
        if "timestamp" not in result:
            result["timestamp"] = datetime.now().isoformat()
        yield result

    return await _stream_agent_response(
        "Global Chat", process(), user_config=request.user_config or _SERVER_GLOBAL_CHAT_CONFIG or None,
        session_id=session_id, user_id=user.get("username") if user else None,
        input_text=request.query,
    )


# --------------------------------------------------app core --------------------------------------------------
# ``maintenance_mode`` is defined alongside MaintenanceModeMiddleware above.

@app.get("/api/maintenance")
async def get_maintenance_status():
    return {"enabled": maintenance_mode["enabled"], "message": maintenance_mode["message"]}

@app.post("/api/admin/maintenance")
async def toggle_maintenance(request: Request, authorization: Optional[str] = Header(None)):
    _require_super_admin(authorization)
    body = await request.json()
    maintenance_mode["enabled"] = bool(body.get("enabled", False))
    if "message" in body:
        maintenance_mode["message"] = body["message"]
    return {"success": True, "enabled": maintenance_mode["enabled"], "message": maintenance_mode["message"]}

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
    }


class OllamaCloudTagsRequest(BaseModel):
    """Bearer token for Ollama Cloud (same as ON_PREM_CLOUD_ACCESS_TOKEN). Not logged or persisted."""

    token: str = Field(..., min_length=1)


def _ollama_cloud_error_detail(response_text: str) -> str:
    """Turn Ollama JSON error bodies into a short string (avoid raw ``{\"error\":...}`` in UI)."""
    raw = (response_text or "").strip()
    if not raw:
        return "ollama cloud error"
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict) and obj.get("error") is not None:
            return str(obj["error"])
    except Exception:
        pass
    return raw[:500]


@app.post("/api/ollama-cloud/tags")
async def ollama_cloud_list_models(body: OllamaCloudTagsRequest):
    """Proxy GET https://ollama.com/api/tags so the UI can populate model choices (Bearer required)."""
    tok = normalize_ollama_cloud_api_token(body.token)
    if not tok:
        raise HTTPException(status_code=400, detail="token required")
    url = (os.getenv("OLLAMA_CLOUD_TAGS_URL") or "https://ollama.com/api/tags").strip()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {tok}"})
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail="ollama cloud unreachable") from e
    if r.status_code != 200:
        detail = _ollama_cloud_error_detail(r.text)
        raise HTTPException(status_code=r.status_code, detail=detail)
    try:
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail="invalid json from ollama cloud") from e
    if isinstance(data, dict) and data.get("error"):
        raise HTTPException(status_code=401, detail=str(data.get("error")))
    models_raw = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models_raw, list):
        models_raw = []
    names: List[str] = []
    for m in models_raw:
        if not isinstance(m, dict):
            continue
        name = (m.get("model") or m.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    names.sort(key=lambda s: s.lower())
    return {"models": names}


class PwcGenAIModelsRequest(BaseModel):
    """Credentials used to probe the PwC GenAI /models endpoint. Not stored or logged."""

    api_key: str = Field(..., min_length=1)
    bearer_token: str = Field(default="")
    endpoint_url: str = Field(default="")


# Static fallback model list for PwC GenAI (used when /models is unavailable)
_PWC_GENAI_STATIC_MODELS = [
    "vertex_ai.gemini-2.5-flash-image",
    "vertex_ai.gemini-2.5-pro",
    "vertex_ai.gpt-4o-mini",
    "vertex_ai.gpt-4o",
    "vertex_ai.anthropic.claude-sonnet-4-6",
    "vertex_ai.anthropic.claude-3.5-sonnet",
    "vertex_ai.anthropic.claude-3-haiku",
]


@app.post("/api/pwc-genai/models")
async def pwc_genai_list_models(body: PwcGenAIModelsRequest):
    """Probe the PwC GenAI /models endpoint using the caller-supplied API key.

    Derives the models URL from the completions endpoint (strips the last path
    segment and appends ``/models``).  Falls back to the static catalogue when
    the upstream does not expose a ``/models`` route.
    """
    base_endpoint = (body.endpoint_url.strip() or "https://genai-sharedservice-americas.pwc.com/completions").rstrip("/")
    # Derive base: strip trailing path component to get the service root
    parsed = urlparse(base_endpoint)
    # Models URL: same origin + /models
    models_url = urlunparse(parsed._replace(path="/models"))

    headers: dict = {
        "accept": "application/json",
        "API-Key": body.api_key,
        "Content-Type": "application/json",
    }
    if body.bearer_token:
        headers["Authorization"] = f"Bearer {body.bearer_token}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(models_url, headers=headers)
    except httpx.RequestError:
        # Network error — return static list so UI still works offline
        return {"models": _PWC_GENAI_STATIC_MODELS, "source": "static"}

    if r.status_code not in (200, 201):
        # Endpoint may not exist — return static list
        return {"models": _PWC_GENAI_STATIC_MODELS, "source": "static"}

    try:
        data = r.json()
    except Exception:
        return {"models": _PWC_GENAI_STATIC_MODELS, "source": "static"}

    # OpenAI-compatible: {"data": [{"id": "model-name"}, ...]}
    names: List[str] = []
    raw_list = None
    if isinstance(data, dict):
        raw_list = data.get("data") or data.get("models") or data.get("result")
    elif isinstance(data, list):
        raw_list = data

    if isinstance(raw_list, list):
        for m in raw_list:
            mid = ""
            if isinstance(m, dict):
                mid = (m.get("id") or m.get("model") or m.get("name") or "").strip()
            elif isinstance(m, str):
                mid = m.strip()
            if mid and mid not in names:
                names.append(mid)

    if not names:
        return {"models": _PWC_GENAI_STATIC_MODELS, "source": "static"}

    names.sort(key=lambda s: s.lower())
    return {"models": names, "source": "live"}


@app.get("/api/system/check")
async def system_check():
    """Detailed system check including dependencies."""
    checks = {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "components": {}
    }
    
    try:
        import playwright
        import shutil as _shutil
        _sys_cr = _shutil.which("chromium") or _shutil.which("chromium-browser")
        if _sys_cr:
            checks["components"]["playwright"] = {
                "status": "available",
                "message": f"Playwright and system Chromium ready ({_sys_cr})",
                "spa_support": True
            }
        else:
            checks["components"]["playwright"] = {
                "status": "missing_browser",
                "message": "Playwright installed but Chromium not found in PATH",
                "spa_support": False
            }
            checks["status"] = "degraded"
    except ImportError:
        checks["components"]["playwright"] = {
            "status": "missing_package",
            "message": "Playwright package not installed",
            "spa_support": False
        }
        checks["status"] = "degraded"
    
    # Check tiktoken
    try:
        import tiktoken
        checks["components"]["tiktoken"] = {
            "status": "available",
            "message": "Token counting available"
        }
    except ImportError:
        checks["components"]["tiktoken"] = {
            "status": "missing",
            "message": "tiktoken not installed (fallback mode active)",
            "install_instructions": "pip install tiktoken"
        }
    
    return checks


@app.get("/api/codex-sdlc/preflight")
async def codex_sdlc_preflight(include_smoke: bool = False):
    """Deployment preflight checks for Codex SDLC runtime dependencies."""
    return run_codex_sdlc_preflight(include_smoke=include_smoke, cwd=str(Path(__file__).parent))


@app.get("/api/agents")
async def get_agents_catalog(authorization: Optional[str] = Header(None)):
    """Get agents catalog; optional auth filters to the caller's assigned agents (marketplace)."""
    try:
        catalog = await async_get_catalog()
        user = _optional_verify_user(authorization)
        if user:
            allowed = admin_auth.effective_agent_ids(
                user.get("role", "user"),
                user.get("agent_permissions"),
            )
            if len(allowed) == 0:
                catalog = {**catalog, "agents": []}
            else:
                allow_set = set(allowed)
                catalog = {
                    **catalog,
                    "agents": [a for a in catalog.get("agents", []) if a.get("id") in allow_set],
                }
        return {**catalog, "agents": [with_server_config_status(agent) for agent in catalog.get("agents", [])]}
    except CatalogNotFoundError:
        raise HTTPException(status_code=404, detail="Agents catalog not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading catalog: {str(e)}")


@app.get("/api/agents/{agent_id}")
async def get_agent_details(agent_id: str, authorization: Optional[str] = Header(None)):
    """Get detailed information about a specific agent.

    Checks the MongoDB catalog first (built-in agents), then falls back to the
    agent_definitions DB table (custom/community agents).
    """
    try:
        agent = get_agent_by_id(agent_id)

        # ── Fall back to DB (custom agents) ─────────────────────────────
        if not agent:
            try:
                from agent_registry import get_agent as _get_custom_agent, get_agent_by_slug
                custom = _get_custom_agent(agent_id) or get_agent_by_slug(agent_id)
                if custom:
                    # Public/unlisted agents: anyone can view
                    # Private agents: owner can still view (they know the ID)
                    agent = _custom_agent_to_catalog(custom)
            except Exception:
                pass

        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # ── 3. Permission check — ONLY for built-in catalog agents ───────────
        # Custom agents (id starts with "custom_" or _is_custom flag) are exempt:
        # they have their own visibility model and are not in the catalog ACL.
        is_custom = agent.get("_is_custom") or agent_id.startswith("custom_")
        if not is_custom:
            user = _optional_verify_user(authorization)
            if user:
                allowed = admin_auth.effective_agent_ids(
                    user.get("role", "user"),
                    user.get("agent_permissions"),
                )
                if allowed and agent_id not in allowed:
                    raise HTTPException(status_code=403, detail="No access to this agent")

        return with_server_config_status(agent)

    except CatalogNotFoundError:
        raise HTTPException(status_code=404, detail="Agents catalog not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading agent details: {str(e)}")


def _custom_agent_to_catalog(ca: dict) -> dict:
    """Convert an agent_definitions row to a catalog-compatible dict for AgentPage."""
    return {
        "id": ca["id"],
        "name": ca["name"],
        "type": "custom",
        "category": ca.get("category_id", "general"),
        "status": ca.get("status", "deployed"),
        "admin_only": False,
        "autonomy_quotient": 60,
        "description": ca.get("description", ""),
        "logo": ca.get("logo_url", ""),
        "version": ca.get("version", "1.0.0"),
        "path": f"agents/{ca.get('slug', ca['id'])}",
        "capabilities": ca.get("capabilities") or [],
        "tools": [
            {"name": t.get("name", t) if isinstance(t, dict) else t,
             "description": t.get("description", "") if isinstance(t, dict) else "",
             "module": ""}
            for t in (ca.get("tools_config") or [])
        ],
        "llm_providers": [
            {
                "name": ca.get("llm_provider", "PwC GenAI"),
                "type": ca.get("llm_provider", "pwc_genai"),
                "default": True,
                "cost": "medium",
                "description": f"Powered by {ca.get('llm_model', 'Gemini')}",
                "models": [ca.get("llm_model", "")],
            }
        ],
        "configuration": {
            # Credentials are pre-configured by the agent builder and stored
            # securely in the DB (default_config). End-users do not need to
            # supply any API keys to chat with a custom agent.
            "required_settings": [],
            "optional_settings": [],
        },
        "usage": {
            "entry_point": f"agents/{ca.get('slug', ca['id'])}/agent.py",
            "class_name": "DynamicAgent",
            "example_prompts": ca.get("example_prompts") or [],
            "api_endpoint": f"POST /api/agent-builder/invoke/{ca.get('slug', ca['id'])}",
        },
        "routing": {"keywords": [], "confidence": 0.5},
        "_is_custom": True,
        "_slug": ca.get("slug", ""),
    }


@app.get("/api/catalog")
async def get_catalog(authorization: Optional[str] = Header(None)):
    """Full catalog for the admin catalog editor — not filtered by per-user agent access."""
    _require_permission(authorization, "agents")
    try:
        return await async_get_catalog()
    except CatalogNotFoundError:
        raise HTTPException(status_code=404, detail="Agents catalog not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading catalog: {str(e)}")


@app.put("/api/catalog")
async def update_catalog(catalog_data: dict, authorization: Optional[str] = Header(None)):
    """Update the agents catalog in MongoDB. Requires admin authentication."""
    _require_permission(authorization, "agents")
    try:
        await async_save_catalog(catalog_data)
        return {
            "success": True,
            "message": "Catalog updated successfully",
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating catalog: {str(e)}",
        )


# ==================== 3GPP AGENT ENDPOINTS ====================

@app.post("/api/3gpp/build-inventory")
async def build_3gpp_inventory(background_tasks: BackgroundTasks):
    """Trigger full 3GPP FTP inventory build (runs in background)."""
    from agents.ThreeGPP_agent.tools.inventory_builder import get_inventory_status, build_full_inventory
    status = get_inventory_status()
    if status.get("building"):
        return {"success": False, "message": "Build already in progress", "status": status}

    background_tasks.add_task(build_full_inventory)
    return {"success": True, "message": "Inventory build started in background. Check /api/3gpp/inventory-status for progress."}


@app.get("/api/3gpp/inventory-status")
async def get_3gpp_inventory_status():
    """Check 3GPP inventory status and build progress."""
    from agents.ThreeGPP_agent.tools.inventory_builder import get_inventory_status
    return get_inventory_status()


@app.get("/api/3gpp/search")
async def search_3gpp_index(q: str = "", max_results: int = 50):
    """Search 3GPP inventory index."""
    from agents.ThreeGPP_agent.tools.inventory_builder import search_index
    if not q:
        return {"results": [], "query": q}
    results = await search_index(q, max_results=min(max_results, 100))
    return {"results": results, "query": q, "count": len(results)}


@app.get("/api/3gpp/structure")
async def get_3gpp_structure():
    """Get 3GPP directory structure (working groups and meetings)."""
    from agents.ThreeGPP_agent.tools.inventory_builder import load_inventory
    data = load_inventory()
    if not data or not data.get("structure"):
        return {"exists": False, "structure": {}}
    summary = {}
    for wg_name, wg_data in data["structure"].items():
        meetings = list(wg_data.get("meetings", {}).keys())
        meetings.sort()
        summary[wg_name] = {
            "meeting_count": len(meetings),
            "meetings": meetings,
        }
    return {"exists": True, "structure": summary, "metadata": data.get("metadata", {})}


# ===== Workflow Orchestrator Endpoints (moved to workflow/routes.py) =====
from workflow.routes import router as workflow_router
app.include_router(workflow_router)

# ===== Agent Builder Endpoints =====
from agent_builder_routes import router as agent_builder_router
app.include_router(agent_builder_router)


class TTSRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None

@app.post("/api/tts")
async def text_to_speech(req: TTSRequest):
    import httpx
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ElevenLabs API key not configured")

    cleaned = req.text.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="No text provided")

    if len(cleaned) > 2000:
        cleaned = cleaned[:2000]

    voice_id = req.voice_id or "pFZP5JQG7iQjIQuC4Bku"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": cleaned,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.4,
            "use_speaker_boost": True,
        }
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                detail = resp.text[:200] if resp.text else "ElevenLabs API error"
                raise HTTPException(status_code=resp.status_code, detail=detail)
            return StreamingResponse(
                iter([resp.content]),
                media_type="audio/mpeg",
                headers={"Content-Disposition": "inline; filename=speech.mp3"}
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="ElevenLabs API timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/tts/voices")
async def list_tts_voices():
    import httpx
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ElevenLabs API key not configured")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": api_key}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Failed to fetch voices")
            data = resp.json()
            voices = [{"voice_id": v["voice_id"], "name": v["name"], "labels": v.get("labels", {})} for v in data.get("voices", [])]
            return {"voices": voices}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def get_current_admin(authorization: Optional[str] = Header(None)):
    return _require_permission(authorization, "knowledge-base")

# ─── Knowledge Base Management ────────────────────────────────────────────────

from knowledge_base_manager import kb_manager

@app.get("/api/admin/knowledge-base/status")
async def kb_status(admin: dict = Depends(get_current_admin)):
    try:
        success, msg = kb_manager.connect()
        return {"connected": success, "message": msg}
    except Exception as e:
        return {"connected": False, "message": str(e)}


@app.get("/api/admin/knowledge-base/databases")
async def kb_list_databases(admin: dict = Depends(get_current_admin)):
    try:
        databases = kb_manager.list_databases()
        return {"databases": databases}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/knowledge-base/collections/{db_name}")
async def kb_list_collections(db_name: str, admin: dict = Depends(get_current_admin)):
    try:
        collections = kb_manager.list_collections(db_name)
        return {"database": db_name, "collections": collections}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/knowledge-base/indexes/{db_name}/{collection_name}")
async def kb_list_indexes(db_name: str, collection_name: str, admin: dict = Depends(get_current_admin)):
    try:
        indexes = kb_manager.list_indexes(db_name, collection_name)
        return {"database": db_name, "collection": collection_name, "indexes": indexes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/knowledge-base/stats/{db_name}/{collection_name}")
async def kb_collection_stats(db_name: str, collection_name: str, admin: dict = Depends(get_current_admin)):
    try:
        stats = kb_manager.get_collection_stats(db_name, collection_name)
        return {"database": db_name, "collection": collection_name, **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateIndexRequest(BaseModel):
    db_name: str
    collection_name: str
    index_name: str = "vector_index"
    embedding_field: str = "embedding"
    dimensions: int = 384
    similarity: str = "cosine"


@app.post("/api/admin/knowledge-base/indexes")
async def kb_create_index(request: CreateIndexRequest, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.create_vector_index(
            db_name=request.db_name,
            collection_name=request.collection_name,
            index_name=request.index_name,
            embedding_field=request.embedding_field,
            dimensions=request.dimensions,
            similarity=request.similarity,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/knowledge-base/indexes/{db_name}/{collection_name}/{index_name}")
async def kb_delete_index(db_name: str, collection_name: str, index_name: str, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.delete_search_index(db_name, collection_name, index_name)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class IngestFileRequest(BaseModel):
    db_name: str
    project_id: str
    file_name: str
    file_type: str
    file_content_b64: str


@app.post("/api/admin/knowledge-base/ingest")
async def kb_ingest_file(request: IngestFileRequest, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.ingest_file(
            db_name=request.db_name,
            project_id=request.project_id,
            file_content_b64=request.file_content_b64,
            file_name=request.file_name,
            file_type=request.file_type,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/knowledge-base/files/{db_name}/{collection_name}/{file_name}")
async def kb_delete_file(db_name: str, collection_name: str, file_name: str, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.delete_file_chunks(db_name, collection_name, file_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CreateCollectionRequest(BaseModel):
    db_name: str
    collection_name: str


@app.post("/api/admin/knowledge-base/collections")
async def kb_create_collection(request: CreateCollectionRequest, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.create_database_and_collection(request.db_name, request.collection_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/knowledge-base/documents/{db_name}/{collection_name}")
async def kb_browse_documents(
    db_name: str,
    collection_name: str,
    page: int = 1,
    page_size: int = 20,
    search: str = "",
    admin: dict = Depends(get_current_admin),
):
    try:
        result = kb_manager.browse_documents(db_name, collection_name, page, page_size, search)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/knowledge-base/all-indexes/{db_name}")
async def kb_all_indexes(db_name: str, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.list_all_indexes(db_name)
        return {"database": db_name, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/knowledge-base/all-vector-indexes")
async def kb_all_vector_indexes(admin: dict = Depends(get_current_admin)):
    try:
        all_indexes = []
        client = kb_manager.get_client()
        db_names = [d for d in client.list_database_names() if d not in ("admin", "local", "config")]
        for db_name in db_names:
            try:
                result = kb_manager.list_all_indexes(db_name)
                for idx in result.get("search_indexes", []):
                    if idx.get("type") == "vectorSearch" and idx.get("queryable"):
                        all_indexes.append({
                            "db_name": db_name,
                            "collection": idx["collection"],
                            "index_name": idx["name"],
                            "status": idx.get("status", ""),
                            "fields": idx.get("fields", []),
                            "label": f"{db_name}.{idx['collection']}.{idx['name']}",
                        })
            except Exception:
                pass
        return {"indexes": all_indexes}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class VectorSearchRequest(BaseModel):
    db_name: str
    collection_name: str
    query: str
    index_name: str = "vector_index"
    limit: int = 10


@app.post("/api/admin/knowledge-base/vector-search")
async def kb_vector_search(request: VectorSearchRequest, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.vector_search_query(
            db_name=request.db_name,
            collection_name=request.collection_name,
            query_text=request.query,
            index_name=request.index_name,
            limit=request.limit,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/admin/knowledge-base/collections/{db_name}/{collection_name}")
async def kb_delete_collection(db_name: str, collection_name: str, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.delete_collection(db_name, collection_name)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RenameCollectionRequest(BaseModel):
    new_name: str


@app.put("/api/admin/knowledge-base/collections/{db_name}/{collection_name}/rename")
async def kb_rename_collection(db_name: str, collection_name: str, request: RenameCollectionRequest, admin: dict = Depends(get_current_admin)):
    try:
        result = kb_manager.rename_collection(db_name, collection_name, request.new_name)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", include_in_schema=False)
async def root():
    """Serve the React frontend root."""
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="Frontend not built. Run 'npm run build' in the frontend directory.")


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Fallback to index.html for React Router SPA routing."""
    # Let API 404s pass through as JSON
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), media_type="text/html", headers={"Cache-Control": "no-cache"})
    return JSONResponse({"detail": "Not Found"}, status_code=404)


# Catch-all route to serve frontend for client-side routing (must be last)
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    """Serve the frontend application for all non-API routes."""
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    
    if full_path and frontend_dist.exists():
        static_file = frontend_dist / full_path
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))
    
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file), headers={"Cache-Control": "no-cache"})
    
    raise HTTPException(
        status_code=404,
        detail="Frontend not built. Run 'npm run build' in the frontend directory."
    )


# Main Entry Point
if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*60)
    print("🚀 Starting Multi-Agent API Server")
    print("="*60)
    print("\n🤖 Available Agent Endpoints:")
    print("   • POST /api/basic-agent - Multi-tool AI Agent")
    print("   • POST /api/jira-agent - JIRA Integration Agent")
    print("   • POST /api/brd-generation - BRD Generation Agent")
    print("   • POST /api/rbi-circular - RBI Circular Agent")
    print("   • POST /api/sebi-circular - SEBI Circular Agent")
    print("   • POST /api/bpmn-generator - BPMN Generator Agent")
    print("   • POST /api/market-research - Market Research Agent")
    print("   • POST /api/company-research - Company Research Agent")
    print("   • POST /api/company-ai-solutions - Company AI Solutions Agent")
    print("   • POST /api/web-search - Web Search Agent (Perplexity)")
    print("   • POST /api/mongodb-rag - MongoDB Atlas KB Agent")
    print("\n🔌 MCP (Cursor/VS Code) Integration:")
    print("   • Streamable HTTP (recommended): http://localhost:8000/mcp")
    print("   • SSE (legacy): http://localhost:8000/mcp/sse")
    print("="*60 + "\n")
    
    _port = int(os.environ.get("PORT", "8000"))
    _debug_mode = os.environ.get("DEBUG", "1").lower() in {"1", "true", "yes", "on"}

    if _debug_mode:
        print("🔄 Debug mode enabled: auto-reload is ON")
        uvicorn.run(
            "api:app",
            host="0.0.0.0",
            port=_port,
            reload=True,
            reload_dirs=[str(Path(__file__).resolve().parent)],
        )
    else:
        print("✅ Debug mode disabled: running without auto-reload")
        uvicorn.run(app, host="0.0.0.0", port=_port)
