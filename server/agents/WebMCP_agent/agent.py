"""Orchestrator: user goal → bridge tool catalog → LLM loop → tool calls in the user's tab."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .ai_service import webmcp_ai_service
from .tools.bridge_client import WEBMCP_AGENT_VERSION, WebMcpBridgeClient, WebMcpBridgeError, host_allowed

logger = logging.getLogger(__name__)

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

SSEEmit = Optional[Callable[[str, Dict[str, Any]], None]]

_AGENT_ENABLED_RAW = os.environ.get("WEBMCP_AGENT_ENABLED", "true").strip().lower()
WEBMCP_AGENT_ENABLED = _AGENT_ENABLED_RAW in ("1", "true", "yes", "on")

_TOOL_DESC_MAX = 800


def _extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("No JSON object found in model output")


def _arg_digest(arguments: Dict[str, Any]) -> str:
    raw = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _truncate(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 3] + "..."


def _validate_required(schema: Any, arguments: Dict[str, Any]) -> Optional[str]:
    if not isinstance(schema, dict):
        return None
    req = schema.get("required")
    if not isinstance(req, list):
        return None
    for k in req:
        if k not in arguments:
            return f"missing required argument {k!r}"
    return None


def _tools_for_prompt(tools: List[Dict[str, Any]]) -> str:
    slim: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if not name:
            continue
        desc = _truncate(str(t.get("description") or ""), _TOOL_DESC_MAX)
        slim.append(
            {
                "name": name,
                "description": desc,
                "inputSchema": t.get("inputSchema"),
            }
        )
    return json.dumps(slim, indent=2, default=str)[:48_000]


def _append_audit(line: Dict[str, Any]) -> None:
    path = LOGS_DIR / "audit.jsonl"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except OSError as e:
        logger.warning("audit log write failed: %s", e)


class WebMcpAgent:
    def __init__(self):
        self._sessions: Dict[str, List[Dict[str, str]]] = {}
        self.ai = webmcp_ai_service

    def clear_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def process_chat(self, request: Dict[str, Any]) -> Dict[str, Any]:
        stream_emit: SSEEmit = request.get("_sse_emit")
        thinking: List[Dict[str, Any]] = []

        def emit_thinking(content: str, tool_name: Optional[str] = None) -> None:
            entry: Dict[str, Any] = {"type": "thinking", "content": content}
            if tool_name:
                entry["tool_name"] = tool_name
            thinking.append(entry)
            if stream_emit:
                try:
                    stream_emit("thinking", entry)
                except Exception:
                    logger.debug("stream_emit failed", exc_info=True)

        def emit_progress(message: str, stage: str = "progress") -> None:
            if stream_emit:
                try:
                    stream_emit("progress", {"stage": stage, "message": message})
                except Exception:
                    logger.debug("stream_emit progress failed", exc_info=True)

        if not WEBMCP_AGENT_ENABLED:
            return {
                "success": False,
                "response": "**WebMCP Agent is disabled** on this server (`WEBMCP_AGENT_ENABLED=false`).",
                "query": request.get("query", ""),
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": request.get("session_id") or "",
                "tool_calls": 0,
                "webmcp_agent_version": WEBMCP_AGENT_VERSION,
            }

        query = (request.get("query") or "").strip()
        session_id = request.get("session_id") or str(uuid.uuid4())
        clear_history = bool(request.get("clear_history", False))
        if clear_history:
            self.clear_session(session_id)

        bridge_url = (request.get("bridge_base_url") or "").strip()
        bridge_token = (request.get("bridge_token") or "").strip()
        allowed_hosts = request.get("allowed_hosts")
        if allowed_hosts is not None and not isinstance(allowed_hosts, list):
            allowed_hosts = None
        require_allow = bool(request.get("require_host_allowlist", False))
        max_steps = int(request.get("max_steps", 20))
        bridge_timeout = float(request.get("bridge_timeout_sec", 60.0))
        wall_time = float(request.get("wall_time_sec", 300.0))
        t0 = time.monotonic()

        if not query:
            return {
                "success": True,
                "response": "Session cleared." if clear_history else "Send a message describing what to do in your open browser tab.",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "tool_calls": 0,
                "webmcp_agent_version": WEBMCP_AGENT_VERSION,
            }

        if not bridge_url or not bridge_token:
            return {
                "success": False,
                "response": (
                    "**Bridge not configured.** The request must include non-empty **bridge_base_url** and **bridge_token** "
                    "(e.g. from the chat panel). Run `python -m browser.webmcp_bridge.run_server` from the repo root and "
                    "use the printed token in the UI and Chrome extension."
                ),
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "tool_calls": 0,
                "webmcp_agent_version": WEBMCP_AGENT_VERSION,
            }

        emit_progress("Connecting to local WebMCP bridge…", "init")
        bridge_meta: Optional[str] = None
        session_url: Optional[str] = None

        try:
            with WebMcpBridgeClient(bridge_url, bridge_token, timeout_sec=bridge_timeout) as bridge:
                try:
                    ver = bridge.bridge_version()
                    bridge_meta = str((ver or {}).get("bridge_version") or "")
                except Exception:
                    bridge_meta = None

                emit_progress("Reading active tab and tool catalog…", "tools")
                sess = bridge.session_info()
                session_url = sess.get("url") if isinstance(sess, dict) else None
                host_chk = host_allowed(str(session_url or ""), allowed_hosts, require_allowlist=require_allow)
                if host_chk is not True:
                    return {
                        "success": False,
                        "response": f"**Host policy blocked this run:** {host_chk}",
                        "query": query,
                        "thinking_steps": thinking,
                        "timestamp": datetime.now().isoformat(),
                        "session_id": session_id,
                        "tool_calls": 0,
                        "webmcp_agent_version": WEBMCP_AGENT_VERSION,
                        "bridge_version": bridge_meta,
                        "session_url": session_url,
                    }

                tools = bridge.list_tools()
                if isinstance(tools, dict) and tools.get("error"):
                    return {
                        "success": False,
                        "response": f"**No tools available in this tab:** {tools.get('message', tools)}",
                        "query": query,
                        "thinking_steps": thinking,
                        "timestamp": datetime.now().isoformat(),
                        "session_id": session_id,
                        "tool_calls": 0,
                        "webmcp_agent_version": WEBMCP_AGENT_VERSION,
                        "bridge_version": bridge_meta,
                        "session_url": session_url,
                    }
                if (
                    isinstance(tools, list)
                    and len(tools) == 1
                    and isinstance(tools[0], dict)
                    and tools[0].get("_error")
                ):
                    return {
                        "success": False,
                        "response": f"**Could not list WebMCP tools:** {tools[0].get('message', tools[0])}",
                        "query": query,
                        "thinking_steps": thinking,
                        "timestamp": datetime.now().isoformat(),
                        "session_id": session_id,
                        "tool_calls": 0,
                        "webmcp_agent_version": WEBMCP_AGENT_VERSION,
                        "bridge_version": bridge_meta,
                        "session_url": session_url,
                    }
                if not tools:
                    return {
                        "success": False,
                        "response": (
                            "**No WebMCP tools were listed** for the active tab. Open a page that registers "
                            "`navigator.modelContext` tools, or use the demo page "
                            "`browser/webmcp_bridge/demo/index.html` with the bridge extension connected."
                        ),
                        "query": query,
                        "thinking_steps": thinking,
                        "timestamp": datetime.now().isoformat(),
                        "session_id": session_id,
                        "tool_calls": 0,
                        "webmcp_agent_version": WEBMCP_AGENT_VERSION,
                        "bridge_version": bridge_meta,
                        "session_url": session_url,
                    }

                tool_names = {str(t.get("name")) for t in tools if isinstance(t, dict) and t.get("name")}
                history = self._sessions.setdefault(session_id, [])
                transcript = _tools_for_prompt(tools)
                observations: List[str] = []
                tool_calls = 0
                final_answer = ""

                emit_thinking(f"Active tab: {_truncate(str(session_url), 200)} — {len(tools)} tool(s) available.")

                for step_i in range(max_steps):
                    if time.monotonic() - t0 > wall_time:
                        final_answer = "**Stopped:** wall time limit reached."
                        break

                    sys_prompt = (
                        "You are a WebMCP agent. The user is working in their real browser; tools run in the active tab "
                        "via a local bridge. Obey site policy and the user; never ask for passwords or MFA codes.\n"
                        "Reply with a single JSON object only, no markdown fences.\n"
                        'Schema: {"done": true, "final_answer": "markdown for the user"} OR '
                        '{"done": false, "tool": "<name>", "arguments": { ... }} OR '
                        '{"done": false, "need_user": "short question"}.\n'
                        "Use only tool names from the TOOLS list. If the goal is satisfied, set done true."
                    )
                    user_prompt = (
                        f"TOOLS (names must match exactly):\n{transcript}\n\n"
                        f"USER_GOAL:\n{query}\n\n"
                        f"TAB_URL:\n{session_url}\n\n"
                        f"PRIOR_OBSERVATIONS:\n{json.dumps(observations[-12:], default=str)[:12000]}\n\n"
                        f"CHAT_MEMORY (recent):\n{json.dumps(history[-6:], default=str)[:6000]}\n"
                    )

                    emit_progress(f"Planning step {step_i + 1}…", "llm")
                    raw = self.ai.call_genai(
                        f"System: {sys_prompt}\n\nUser: {user_prompt}",
                        temperature=0.15,
                        max_tokens=2048,
                    )
                    try:
                        plan = _extract_json_object(raw)
                    except Exception as exc:
                        emit_thinking(f"Model returned non-JSON; asking for retry. ({exc})")
                        observations.append(f"parse_error: {exc}")
                        continue

                    if plan.get("need_user"):
                        nu = str(plan.get("need_user"))
                        final_answer = nu
                        break

                    if plan.get("done"):
                        final_answer = str(plan.get("final_answer") or plan.get("summary") or "Done.")
                        break

                    tname = plan.get("tool")
                    if not tname or str(tname) not in tool_names:
                        observations.append(f"invalid_tool_proposal: {tname!r}")
                        emit_thinking(f"Ignored invalid tool name: {tname!r}")
                        continue

                    args = plan.get("arguments") if isinstance(plan.get("arguments"), dict) else {}
                    schema = next(
                        (t.get("inputSchema") for t in tools if isinstance(t, dict) and t.get("name") == str(tname)),
                        None,
                    )
                    miss = _validate_required(schema, args)
                    if miss:
                        observations.append(f"validation_error:{tname}:{miss}")
                        emit_thinking(f"Skipped {tname}: {miss}")
                        continue

                    emit_thinking(f"Calling tool `{tname}`", tool_name=str(tname))
                    emit_progress(f"Executing `{tname}` in your browser…", "tool")
                    digest = _arg_digest(args)
                    _append_audit(
                        {
                            "ts": datetime.now().isoformat(),
                            "session_id": session_id,
                            "tool": str(tname),
                            "arg_digest": digest,
                            "step": step_i,
                        }
                    )
                    try:
                        result = bridge.call_tool(str(tname), args)
                        tool_calls += 1
                        obs = _truncate(json.dumps(result, default=str), 4000)
                        observations.append(f"{tname} -> {obs}")
                        emit_thinking(f"Result from `{tname}`: {_truncate(obs, 500)}")
                    except WebMcpBridgeError as e:
                        observations.append(f"{tname} ERROR: {e}")
                        emit_thinking(f"Tool error `{tname}`: {e}")

                if not final_answer:
                    final_answer = (
                        "**Incomplete:** step or time limit reached. "
                        "Check the active tab, bridge connection, and try a narrower goal."
                    )

                history.append({"user": query, "assistant": final_answer[:2000]})
                if len(history) > 40:
                    del history[:-40]

                return {
                    "success": True,
                    "response": final_answer,
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session_id,
                    "tool_calls": tool_calls,
                    "webmcp_agent_version": WEBMCP_AGENT_VERSION,
                    "bridge_version": bridge_meta,
                    "session_url": session_url,
                }

        except WebMcpBridgeError as e:
            logger.exception("WebMCP bridge error")
            return {
                "success": False,
                "response": f"**Bridge error:** {e}",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "tool_calls": 0,
                "webmcp_agent_version": WEBMCP_AGENT_VERSION,
                "session_url": session_url,
            }
        except Exception as exc:
            logger.exception("WebMCP agent error")
            return {
                "success": False,
                "response": f"**Error:** {exc}",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "tool_calls": 0,
                "webmcp_agent_version": WEBMCP_AGENT_VERSION,
            }


webmcp_agent = WebMcpAgent()
