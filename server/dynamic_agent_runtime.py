"""Dynamic Agent Runtime — executes agents defined in the database.

Loads an agent definition from DB, constructs the tool list, builds
an LLM chain with system prompt + tools, and invokes with SSE streaming.

Supports a ReAct-style tool execution loop: the LLM can request tool calls,
the runtime executes them, feeds results back, and continues until the LLM
produces a final answer.
"""

import os
import json
import asyncio
import re
import uuid
import traceback
import httpx
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, AsyncGenerator

from agents.base_ai_service import BaseAIService
from agent_registry import (
    get_agent,
    get_agent_by_slug,
    get_agent_for_runtime,
    get_agent_by_slug_for_runtime,
    record_usage,
)


@contextmanager
def _inject_env(config: Dict[str, str]):
    """Temporarily inject agent credentials into os.environ."""
    if not config:
        yield
        return
    old = {}
    try:
        for k, v in config.items():
            if v and k not in ("LLM_PROVIDER",):  # LLM_PROVIDER is structural, not a credential
                old[k] = os.environ.get(k)
                os.environ[k] = v
        # LLM_PROVIDER needs to be set so local_llm.get_llm_provider() picks it up
        lp = config.get("LLM_PROVIDER", "")
        if lp:
            old["LLM_PROVIDER"] = os.environ.get("LLM_PROVIDER")
            os.environ["LLM_PROVIDER"] = lp
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_runtime_cache: Dict[str, "DynamicAgent"] = {}


async def _ensure_fresh_google_token() -> str:
    """Refresh GOOGLE_ACCESS_TOKEN via GOOGLE_REFRESH_TOKEN if expired.

    Reads/writes os.environ (the runtime injects agent.default_config into env before
    each turn). Returns the current valid access token, or "" if not connected.
    """
    import time as _time
    access = os.getenv("GOOGLE_ACCESS_TOKEN", "")
    refresh = os.getenv("GOOGLE_REFRESH_TOKEN", "")
    expires_at = int(os.getenv("GOOGLE_TOKEN_EXPIRES_AT", "0") or "0")
    if access and _time.time() < expires_at:
        return access
    if not refresh:
        return access  # nothing to refresh with — caller handles auth error

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return access

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            return access
        tok = resp.json()
        new_access = tok.get("access_token", access)
        new_exp = int(tok.get("expires_in", 3600))
        os.environ["GOOGLE_ACCESS_TOKEN"] = new_access
        os.environ["GOOGLE_TOKEN_EXPIRES_AT"] = str(int(_time.time()) + new_exp - 60)
        # Mirror to tool-specific keys
        os.environ["GMAIL_ACCESS_TOKEN"] = new_access
        os.environ["GOOGLE_DRIVE_ACCESS_TOKEN"] = new_access
        return new_access

async def _execute_zoho_tool(product: str, tool_input: Dict[str, Any]) -> str:
    """Run one Zoho tool call through the shared Zoho service layer.

    The same services back the Zoho workflow agents, so a custom agent gets
    identical transport selection, error messages and dry-run behaviour. With
    ``ZOHO_MCP_URL`` set, calls go through the pre-authorized Zoho MCP
    connection; otherwise they use the REST APIs with an OAuth refresh token.
    Writes are skipped while ``ZOHO_DRY_RUN`` is on.
    """
    from agents.Zoho_workflow_agents.base_workflow import WorkflowContext, parse_datetime_hint
    from agents.Zoho_workflow_agents.config import get_settings as _zoho_settings
    from agents.Zoho_workflow_agents.zoho_auth import ZohoAuthError
    from agents.Zoho_workflow_agents.zoho_client import ZohoAPIError, ZohoClient
    from agents.Zoho_workflow_agents.zoho_mcp import ZohoMCPClient, ZohoMCPError

    settings = _zoho_settings()
    missing = settings.missing_credentials()
    if missing:
        if settings.backend == "mcp":
            return (
                "Error: Zoho is not connected. Set " + ", ".join(missing) + " in this agent's credentials. "
                "Use the /message URL of a Zoho MCP connection that has Authorization via Connection enabled."
            )
        return (
            "Error: Zoho is not connected. Set " + ", ".join(missing) + " in this agent's credentials, "
            "or set ZOHO_MCP_URL to use a pre-authorized Zoho MCP connection instead. For REST, generate a "
            "refresh token in the Zoho API Console with access_type=offline and set ZOHO_DC to your "
            "account's region (us, eu, in, au, jp, ca, cn, sa)."
        )

    action = str(tool_input.get("action") or "").strip()
    if not action:
        return "Error: 'action' is required."

    # Writes are gated exactly as they are for the Zoho workflow agents.
    write_actions = {
        "mail": {"send"},
        "calendar": {"create_event"},
        "crm": {"create_task", "create_note"},
        "desk": {"reply", "comment"},
        "cliq": {"post"},
    }
    if settings.dry_run and action in write_actions.get(product, set()):
        return (
            f"[dry run] Zoho {product}.{action} was not executed because ZOHO_DRY_RUN is on. "
            f"Intended call: {json.dumps(tool_input)[:600]}\n"
            "Set ZOHO_DRY_RUN=false and ZOHO_CONFIRM_WRITES=true to execute for real."
        )

    client = ZohoMCPClient(settings.mcp_url) if settings.uses_mcp else ZohoClient(settings)
    ctx = WorkflowContext(settings=settings, client=client)
    try:
        if product == "mail":
            mail = ctx.mail
            if action in ("list", "search"):
                messages = await mail.list_messages(
                    limit=int(tool_input.get("max_results") or 10),
                    search=tool_input.get("query", ""),
                    folder_id=tool_input.get("folder_id", ""),
                    unread_only=bool(tool_input.get("unread_only")),
                )
                if not messages:
                    return "No Zoho Mail messages matched."
                lines = [
                    f"- [{m.get('messageId', '')}] {m.get('subject', '(no subject)')} "
                    f"from {m.get('fromAddress', '')} ({m.get('receivedTime', '')})"
                    for m in messages
                ]
                return "\n".join(lines)
            if action == "read":
                msg = await mail.get_message(
                    tool_input.get("message_id", ""), folder_id=tool_input.get("folder_id", "")
                )
                return (
                    f"From: {msg['from']}\nTo: {msg['to']}\nSubject: {msg['subject']}\n"
                    f"Received: {msg['received_time']}\n\n{msg['body'][:4000]}"
                )
            if action == "send":
                result = await mail.send_mail(
                    to=tool_input.get("to") or [],
                    subject=tool_input.get("subject", ""),
                    body=tool_input.get("body", ""),
                    cc=tool_input.get("cc"),
                )
                return f"Zoho Mail sent to {', '.join(result['to'])} (message id {result['message_id'] or 'n/a'})."
            return f"Unknown Zoho Mail action: {action}"

        if product == "calendar":
            cal = ctx.calendar
            if action == "list_calendars":
                calendars = await cal.list_calendars()
                return "\n".join(
                    f"- {c.get('name', '(unnamed)')} [{c.get('uid', '')}]" for c in calendars
                ) or "No calendars found."
            if action == "list_events":
                events = await cal.list_events(calendar_uid=tool_input.get("calendar_uid", ""))
                return "\n".join(
                    f"- {e.get('title', '(untitled)')} {(e.get('dateandtime') or {}).get('start', '')}"
                    for e in events
                ) or "No events in the window."
            if action == "create_event":
                start = parse_datetime_hint(tool_input.get("start"))
                if start is None:
                    return "Error: 'start' must be a parseable date/time, e.g. 2026-09-18T15:00:00."
                result = await cal.create_event(
                    title=tool_input.get("title", ""),
                    start=start,
                    end=parse_datetime_hint(tool_input.get("end")),
                    duration_minutes=tool_input.get("duration_minutes"),
                    description=tool_input.get("description", ""),
                    location=tool_input.get("location", ""),
                    attendees=tool_input.get("attendees") or [],
                    calendar_uid=tool_input.get("calendar_uid", ""),
                )
                return (
                    f"Zoho Calendar event created: {result['title']} "
                    f"{result['start']} to {result['end']} ({result['timezone']}), uid {result['event_uid'] or 'n/a'}."
                )
            return f"Unknown Zoho Calendar action: {action}"

        if product == "crm":
            crm = ctx.crm
            limit = int(tool_input.get("max_results") or 5)
            if action == "search_contacts":
                matches = await crm.search_contacts(
                    email=tool_input.get("email", ""), name=tool_input.get("name", ""), limit=limit
                )
                return "\n".join(
                    f"- {c.get('Full_Name', '(no name)')} <{c.get('Email', '')}> [{c.get('id', '')}]"
                    for c in matches
                ) or "No CRM contacts matched."
            if action == "get_contact":
                return json.dumps(await crm.get_contact(tool_input.get("contact_id", "")), default=str)[:4000]
            if action == "latest_contact":
                latest = await crm.get_latest_contact()
                return json.dumps(latest, default=str)[:4000] if latest else "No CRM contacts found."
            if action == "search_accounts":
                matches = await crm.search_accounts(name=tool_input.get("name", ""), limit=limit)
                return "\n".join(
                    f"- {a.get('Account_Name', '(no name)')} [{a.get('id', '')}]" for a in matches
                ) or "No CRM accounts matched."
            if action == "create_task":
                result = await crm.create_task(
                    subject=tool_input.get("subject", ""),
                    due_date=parse_datetime_hint(tool_input.get("due_date")),
                    description=tool_input.get("description", ""),
                    priority=tool_input.get("priority") or "High",
                    related_contact_id=tool_input.get("related_contact_id", ""),
                    related_account_id=tool_input.get("related_account_id", ""),
                )
                return f"Zoho CRM task created: {result['subject']} (id {result['task_id'] or 'n/a'}, due {result['due_date'] or 'unset'})."
            if action == "create_note":
                result = await crm.create_note(
                    parent_id=tool_input.get("parent_id", ""),
                    module=tool_input.get("module") or "Contacts",
                    title=tool_input.get("title", ""),
                    content=tool_input.get("content", ""),
                )
                return f"Zoho CRM note created: {result['title']} (id {result['note_id'] or 'n/a'})."
            return f"Unknown Zoho CRM action: {action}"

        if product == "desk":
            desk = ctx.desk
            if action == "list":
                tickets = await desk.list_tickets(
                    limit=int(tool_input.get("max_results") or 10),
                    priority=tool_input.get("priority", ""),
                    status=tool_input.get("status") or "Open",
                )
                return "\n".join(
                    f"- [{t.get('id', '')}] #{t.get('ticketNumber', '')} {t.get('subject', '')} "
                    f"({t.get('priority', '')}/{t.get('status', '')})"
                    for t in tickets
                ) or "No Desk tickets matched."
            if action == "read":
                ticket = await desk.get_ticket(tool_input.get("ticket_id", ""))
                return json.dumps(ticket, default=str)[:4000]
            if action == "latest_high_priority":
                ticket = await desk.get_latest_high_priority_ticket()
                return json.dumps(ticket, default=str)[:4000] if ticket else "No open High or Urgent ticket found."
            if action == "threads":
                threads = await desk.get_ticket_threads(
                    tool_input.get("ticket_id", ""), limit=int(tool_input.get("max_results") or 5)
                )
                return json.dumps(threads, default=str)[:4000]
            if action == "reply":
                result = await desk.send_reply(
                    ticket_id=tool_input.get("ticket_id", ""),
                    content=tool_input.get("content", ""),
                    to_address=tool_input.get("to_address", ""),
                )
                return f"Zoho Desk reply sent on ticket {result['ticket_id']} (thread {result['thread_id'] or 'n/a'})."
            if action == "comment":
                result = await desk.add_comment(
                    ticket_id=tool_input.get("ticket_id", ""),
                    content=tool_input.get("content", ""),
                    is_public=bool(tool_input.get("is_public")),
                )
                return f"Zoho Desk comment added to ticket {result['ticket_id']} (id {result['comment_id'] or 'n/a'})."
            return f"Unknown Zoho Desk action: {action}"

        if product == "cliq":
            cliq = ctx.cliq
            if action == "list_channels":
                channels = await cliq.list_channels(int(tool_input.get("max_results") or 25))
                return "\n".join(
                    f"- {c.get('name', '(unnamed)')}" for c in channels
                ) or "No Cliq channels visible."
            if action == "post":
                result = await cliq.post_message(
                    text=tool_input.get("text", ""),
                    channel=tool_input.get("channel", ""),
                    card_title=tool_input.get("card_title", ""),
                )
                return f"Zoho Cliq message posted to {result['channel']} via {result['transport']}."
            return f"Unknown Zoho Cliq action: {action}"

        return f"Unknown Zoho product: {product}"
    except (ZohoAPIError, ZohoAuthError, ZohoMCPError) as exc:
        return f"Error: {exc}"
    finally:
        await ctx.aclose()


# Persistent conversation store keyed by session_id.
# Lives at module level so it survives agent invalidation/reload between messages.
_session_history: Dict[str, List[Dict]] = {}


def _stream_text_chunks(text: str, chunk_size: int = 40):
    """Yield text in word-aware chunks for natural progressive rendering.

    The chunker breaks on word boundaries when possible so the user sees
    coherent words appearing instead of mid-word splits. Falls back to
    fixed-width slices for very long unbroken strings.
    """
    if not text:
        return
    i = 0
    n = len(text)
    while i < n:
        end = min(i + chunk_size, n)
        if end < n:
            # Try to break on whitespace within the next 12 chars to avoid mid-word cuts
            j = text.rfind(" ", i, min(end + 12, n))
            if j > i + chunk_size // 2:
                end = j + 1
        yield text[i:end]
        i = end


TOOL_PROMPT_TEMPLATE = """
You have access to the following tools.

To call a tool, output a line that starts with TOOL_CALL: followed by a JSON object:
TOOL_CALL: {{"tool": "<exact_tool_name>", "input": {{<parameters>}}}}

Rules:
- Use the EXACT parameter names listed below. Do not invent parameter names.
- After a tool result, continue reasoning or call another tool if needed.
- When you have enough information, respond normally WITHOUT a TOOL_CALL line.

Available tools:
{tool_list}
"""

MAX_TOOL_ITERATIONS = 6


# ---------------------------------------------------------------------------
# Lightweight tool executors (run in-process, no heavy imports at module level)
# ---------------------------------------------------------------------------

async def _execute_tool(tool_ref: Dict[str, Any], tool_input: Dict[str, Any]) -> str:
    """Dispatch a tool call based on its implementation config."""
    tool_id = tool_ref.get("id", "")
    impl = {}

    # Try to load implementation from the DB-stored tool definition
    try:
        from agent_registry import list_tools as _db_tools
        for t in _db_tools():
            if t.get("id") == tool_id:
                impl = t.get("implementation", {})
                break
    except Exception:
        pass

    # If not found in DB, fall back to in-memory registry
    if not impl:
        try:
            from tool_registry import BUILTIN_TOOLS
            for t in BUILTIN_TOOLS:
                if t["id"] == tool_id:
                    impl = t.get("implementation", {})
                    break
        except Exception:
            pass

    impl_type = impl.get("type", "")

    try:
        # ---------- Ollama Web Search ----------
        if impl_type == "ollama_web_search" or tool_id == "tool_web_search":
            query = tool_input.get("query", "")
            if not query:
                return "Error: 'query' parameter is required"
            api_key = os.getenv("OLLAMA_API_KEY") or os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or ""
            api_url = impl.get("api_url", "https://ollama.com/api/web_search")
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            payload = {"query": query}
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            # Parse Ollama web search response
            results = data.get("results") or data.get("web_results") or []
            answer = data.get("answer") or data.get("response") or ""
            lines = []
            if answer:
                lines.append(answer)
            if results:
                lines.append("\nSources:")
                for r in results[:8]:
                    title = r.get("title", "")
                    url = r.get("url", r.get("link", ""))
                    snippet = r.get("snippet", r.get("description", ""))
                    if title or url:
                        lines.append(f"• {title}" + (f" — {url}" if url else ""))
                    if snippet:
                        lines.append(f"  {snippet[:300]}")
            if not lines:
                lines.append(str(data)[:2000])
            return "\n".join(lines)

        # ---------- HTTP API Client ----------
        if impl_type == "http_client" or tool_id == "tool_http_api":
            url = tool_input.get("url", "")
            method = tool_input.get("method", "GET").upper()
            headers = tool_input.get("headers") or {}
            body = tool_input.get("body") or tool_input.get("params")
            auth_type = tool_input.get("auth_type", "none")
            auth_value = tool_input.get("auth_value", "")
            if auth_type == "bearer" and auth_value:
                headers["Authorization"] = f"Bearer {auth_value}"
            elif auth_type == "api_key" and auth_value:
                headers["X-API-Key"] = auth_value
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.request(method, url, headers=headers, json=body if method != "GET" else None, params=body if method == "GET" else None)
                text = resp.text[:8000]
                return f"HTTP {resp.status_code}\n{text}"

        # ---------- HTTP Scraper ----------
        if impl_type == "http_scraper" or tool_id == "tool_web_scrape":
            url = tool_input.get("url", "")
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                from html.parser import HTMLParser
                class _TextExtractor(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.parts: list = []
                        self._skip = False
                    def handle_starttag(self, tag, attrs):
                        if tag in ("script", "style", "noscript"):
                            self._skip = True
                    def handle_endtag(self, tag):
                        if tag in ("script", "style", "noscript"):
                            self._skip = False
                    def handle_data(self, data):
                        if not self._skip:
                            t = data.strip()
                            if t:
                                self.parts.append(t)
                ex = _TextExtractor()
                ex.feed(resp.text)
                return "\n".join(ex.parts)[:8000]

        # ---------- LLM Call ----------
        if impl_type == "llm_call" or tool_id == "tool_llm_call":
            prompt = tool_input.get("prompt", "")
            model = tool_input.get("model")
            temp = tool_input.get("temperature", 0.7)
            svc = BaseAIService(default_temperature=temp, agent_name="tool_llm_call")
            result = await asyncio.to_thread(svc.call_genai, prompt, model=model)
            return result[:8000]

        # ---------- Calculator ----------
        if impl_type == "calculator" or tool_id == "tool_calculator":
            expr = tool_input.get("expression", "")
            allowed = set("0123456789+-*/.() %,eE")
            clean = "".join(c for c in expr if c in allowed)
            if clean:
                val = eval(clean, {"__builtins__": {}}, {})
                return str(val)
            return "Invalid expression"

        # ---------- DateTime ----------
        if impl_type == "datetime_utils" or tool_id == "tool_datetime":
            op = tool_input.get("operation", "now")
            if op == "now":
                tz_name = tool_input.get("timezone", "UTC")
                return datetime.now(timezone.utc).isoformat()
            return f"Date operation '{op}' executed"

        # ---------- JSON Processor ----------
        if impl_type == "json_processor" or tool_id == "tool_json_processor":
            data = tool_input.get("json_data", "")
            op = tool_input.get("operation", "parse")
            parsed = json.loads(data)
            if op == "parse":
                return json.dumps(parsed, indent=2)[:4000]
            return json.dumps(parsed)[:4000]

        # ---------- Regex ----------
        if impl_type == "regex_processor" or tool_id == "tool_regex":
            text = tool_input.get("text", "")
            pattern = tool_input.get("pattern", "")
            op = tool_input.get("operation", "findall")
            if op == "findall":
                return json.dumps(re.findall(pattern, text)[:100])
            elif op == "replace":
                replacement = tool_input.get("replacement", "")
                return re.sub(pattern, replacement, text)
            elif op == "match":
                m = re.search(pattern, text)
                return json.dumps({"match": m.group() if m else None, "groups": list(m.groups()) if m else []})
            return "Unknown regex operation"

        # ---------- Slack Webhook ----------
        if impl_type == "slack_webhook" or tool_id == "tool_slack_notify":
            webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
            if not webhook_url:
                return "Error: SLACK_WEBHOOK_URL not configured"
            msg = tool_input.get("message", "")
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook_url, json={"text": msg})
                return f"Slack: {resp.status_code}"

        # ---------- Telegram Bot ----------
        if impl_type == "telegram_bot" or tool_id == "tool_telegram_notify":
            token = os.getenv("TELEGRAM_BOT_TOKEN", "")
            if not token:
                return "Error: TELEGRAM_BOT_TOKEN not configured"
            chat_id = tool_input.get("chat_id") or os.getenv("TELEGRAM_DEFAULT_CHAT_ID", "")
            if not chat_id:
                return "Error: chat_id required (or set TELEGRAM_DEFAULT_CHAT_ID)"
            payload = {
                "chat_id": chat_id,
                "text": tool_input.get("message", ""),
                "disable_notification": bool(tool_input.get("disable_notification", False)),
            }
            parse_mode = tool_input.get("parse_mode")
            if parse_mode:
                payload["parse_mode"] = parse_mode
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                ok = resp.status_code == 200 and resp.json().get("ok")
                return f"Telegram: {'sent' if ok else 'failed'} ({resp.status_code}) {resp.text[:300]}"

        # ---------- Google Drive ----------
        if impl_type == "google_drive" or tool_id == "tool_google_drive":
            token = await _ensure_fresh_google_token() or os.getenv("GOOGLE_DRIVE_ACCESS_TOKEN", "")
            if not token:
                return "Error: Google Drive not connected. Click 'Connect Google' on the tool to authorize."
            action = tool_input.get("action", "list")
            headers = {"Authorization": f"Bearer {token}"}
            base = "https://www.googleapis.com/drive/v3"
            upload_base = "https://www.googleapis.com/upload/drive/v3"
            async with httpx.AsyncClient(timeout=30) as client:
                if action in ("list", "search"):
                    params = {"pageSize": 25, "fields": "files(id,name,mimeType,size,modifiedTime,parents)"}
                    q_parts = []
                    folder_id = tool_input.get("folder_id")
                    if folder_id:
                        q_parts.append(f"'{folder_id}' in parents")
                    query = tool_input.get("query")
                    if query:
                        q_parts.append(query if action == "search" else f"name contains '{query}'")
                    if q_parts:
                        params["q"] = " and ".join(q_parts)
                    resp = await client.get(f"{base}/files", params=params, headers=headers)
                    return f"Drive {resp.status_code}: {resp.text[:4000]}"
                if action in ("read", "download"):
                    file_id = tool_input.get("file_id", "")
                    if not file_id:
                        return "Error: file_id required"
                    resp = await client.get(f"{base}/files/{file_id}", params={"alt": "media"}, headers=headers)
                    if resp.status_code != 200:
                        return f"Drive download failed {resp.status_code}: {resp.text[:500]}"
                    text = resp.text[:6000] if len(resp.content) < 200_000 else f"[binary {len(resp.content)} bytes]"
                    return f"Drive file {file_id}:\n{text}"
                if action == "upload":
                    import base64
                    name = tool_input.get("file_name", "untitled")
                    mime = tool_input.get("mime_type", "application/octet-stream")
                    b64 = tool_input.get("file_content_b64", "")
                    if not b64:
                        return "Error: file_content_b64 required"
                    data = base64.b64decode(b64)
                    metadata: Dict[str, Any] = {"name": name}
                    folder_id = tool_input.get("folder_id")
                    if folder_id:
                        metadata["parents"] = [folder_id]
                    boundary = "drive_upload_boundary"
                    body = (
                        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                        + json.dumps(metadata)
                        + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
                    ).encode() + data + f"\r\n--{boundary}--".encode()
                    up_headers = {**headers, "Content-Type": f"multipart/related; boundary={boundary}"}
                    resp = await client.post(f"{upload_base}/files?uploadType=multipart", content=body, headers=up_headers)
                    return f"Drive upload {resp.status_code}: {resp.text[:1000]}"
                if action == "delete":
                    file_id = tool_input.get("file_id", "")
                    resp = await client.delete(f"{base}/files/{file_id}", headers=headers)
                    return f"Drive delete {resp.status_code}"
            return f"Unknown Google Drive action: {action}"

        # ---------- SharePoint / OneDrive (Microsoft Graph) ----------
        if impl_type == "sharepoint_graph" or tool_id == "tool_sharepoint":
            token = os.getenv("MS_GRAPH_ACCESS_TOKEN", "")
            if not token:
                return "Error: MS_GRAPH_ACCESS_TOKEN not configured"
            action = tool_input.get("action", "list")
            headers = {"Authorization": f"Bearer {token}"}
            site_id = os.getenv("SHAREPOINT_SITE_ID", "")
            drive_id = tool_input.get("drive_id")
            if drive_id:
                drive_base = f"https://graph.microsoft.com/v1.0/drives/{drive_id}"
            elif site_id:
                drive_base = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
            else:
                drive_base = "https://graph.microsoft.com/v1.0/me/drive"
            async with httpx.AsyncClient(timeout=30) as client:
                if action == "list":
                    folder_path = tool_input.get("folder_path", "").strip("/")
                    url = f"{drive_base}/root/children" if not folder_path else f"{drive_base}/root:/{folder_path}:/children"
                    resp = await client.get(url, headers=headers)
                    return f"SharePoint {resp.status_code}: {resp.text[:4000]}"
                if action == "search":
                    q = tool_input.get("query", "")
                    resp = await client.get(f"{drive_base}/root/search(q='{q}')", headers=headers)
                    return f"SharePoint search {resp.status_code}: {resp.text[:4000]}"
                if action in ("read", "download"):
                    item_id = tool_input.get("item_id", "")
                    if not item_id:
                        return "Error: item_id required"
                    resp = await client.get(f"{drive_base}/items/{item_id}/content", headers=headers, follow_redirects=True)
                    if resp.status_code != 200:
                        return f"SharePoint download failed {resp.status_code}: {resp.text[:500]}"
                    text = resp.text[:6000] if len(resp.content) < 200_000 else f"[binary {len(resp.content)} bytes]"
                    return f"SharePoint item {item_id}:\n{text}"
                if action == "upload":
                    import base64
                    folder_path = tool_input.get("folder_path", "").strip("/")
                    name = tool_input.get("file_name", "untitled")
                    b64 = tool_input.get("file_content_b64", "")
                    if not b64:
                        return "Error: file_content_b64 required"
                    data = base64.b64decode(b64)
                    path = f"{folder_path}/{name}" if folder_path else name
                    url = f"{drive_base}/root:/{path}:/content"
                    resp = await client.put(url, content=data, headers={**headers, "Content-Type": "application/octet-stream"})
                    return f"SharePoint upload {resp.status_code}: {resp.text[:1000]}"
                if action == "delete":
                    item_id = tool_input.get("item_id", "")
                    resp = await client.delete(f"{drive_base}/items/{item_id}", headers=headers)
                    return f"SharePoint delete {resp.status_code}"
            return f"Unknown SharePoint action: {action}"

        # ---------- Gmail ----------
        if impl_type == "gmail_api" or tool_id == "tool_gmail":
            token = await _ensure_fresh_google_token() or os.getenv("GMAIL_ACCESS_TOKEN", "")
            if not token:
                return "Error: Gmail not connected. Click 'Connect Gmail' on the tool to authorize."
            action = tool_input.get("action", "list")
            headers = {"Authorization": f"Bearer {token}"}
            base = "https://gmail.googleapis.com/gmail/v1/users/me"
            async with httpx.AsyncClient(timeout=30) as client:
                if action in ("list", "search"):
                    params = {"maxResults": tool_input.get("max_results", 10)}
                    q = tool_input.get("query")
                    if q:
                        params["q"] = q
                    resp = await client.get(f"{base}/messages", params=params, headers=headers)
                    return f"Gmail {resp.status_code}: {resp.text[:4000]}"
                if action in ("read", "summarize"):
                    mid = tool_input.get("message_id", "")
                    if not mid:
                        return "Error: message_id required"
                    resp = await client.get(f"{base}/messages/{mid}", params={"format": "full"}, headers=headers)
                    if resp.status_code != 200:
                        return f"Gmail read failed {resp.status_code}: {resp.text[:500]}"
                    msg = resp.json()
                    snippet = msg.get("snippet", "")
                    hdrs = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
                    summary = (
                        f"From: {hdrs.get('From', '')}\nTo: {hdrs.get('To', '')}\n"
                        f"Subject: {hdrs.get('Subject', '')}\nDate: {hdrs.get('Date', '')}\n\n{snippet}"
                    )
                    if action == "summarize":
                        try:
                            svc = BaseAIService(agent_name="tool_gmail_summarize")
                            return await asyncio.to_thread(svc.call_genai, f"Summarize this email in 3 bullet points:\n\n{summary}")
                        except Exception as e:
                            return f"{summary}\n\n[summarize fallback: {e}]"
                    return summary
                if action in ("draft", "send_draft"):
                    import base64
                    to = tool_input.get("to") or []
                    subject = tool_input.get("subject", "")
                    body = tool_input.get("body", "")
                    raw_msg = f"To: {', '.join(to)}\r\nSubject: {subject}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{body}"
                    raw_b64 = base64.urlsafe_b64encode(raw_msg.encode()).decode().rstrip("=")
                    payload = {"message": {"raw": raw_b64}}
                    resp = await client.post(f"{base}/drafts", json=payload, headers=headers)
                    if resp.status_code not in (200, 201) or action == "draft":
                        return f"Gmail draft {resp.status_code}: {resp.text[:1000]}"
                    draft_id = resp.json().get("id")
                    send_resp = await client.post(f"{base}/drafts/send", json={"id": draft_id}, headers=headers)
                    return f"Gmail send_draft {send_resp.status_code}: {send_resp.text[:500]}"
            return f"Unknown Gmail action: {action}"

        # ---------- Outlook (Microsoft Graph) ----------
        if impl_type == "outlook_graph" or tool_id == "tool_outlook":
            token = os.getenv("MS_GRAPH_ACCESS_TOKEN", "")
            if not token:
                return "Error: MS_GRAPH_ACCESS_TOKEN not configured"
            action = tool_input.get("action", "list")
            headers = {"Authorization": f"Bearer {token}"}
            base = "https://graph.microsoft.com/v1.0/me"
            async with httpx.AsyncClient(timeout=30) as client:
                if action in ("list", "search"):
                    folder = tool_input.get("folder", "inbox")
                    params: Dict[str, Any] = {"$top": tool_input.get("max_results", 10)}
                    q = tool_input.get("query")
                    if q:
                        params["$search"] = f"\"{q}\""
                    resp = await client.get(f"{base}/mailFolders/{folder}/messages", params=params, headers=headers)
                    return f"Outlook {resp.status_code}: {resp.text[:4000]}"
                if action in ("read", "summarize"):
                    mid = tool_input.get("message_id", "")
                    if not mid:
                        return "Error: message_id required"
                    resp = await client.get(f"{base}/messages/{mid}", headers=headers)
                    if resp.status_code != 200:
                        return f"Outlook read failed {resp.status_code}: {resp.text[:500]}"
                    msg = resp.json()
                    summary = (
                        f"From: {msg.get('from', {}).get('emailAddress', {}).get('address', '')}\n"
                        f"Subject: {msg.get('subject', '')}\nReceived: {msg.get('receivedDateTime', '')}\n\n"
                        f"{msg.get('bodyPreview', '')}"
                    )
                    if action == "summarize":
                        try:
                            svc = BaseAIService(agent_name="tool_outlook_summarize")
                            return await asyncio.to_thread(svc.call_genai, f"Summarize this email in 3 bullet points:\n\n{summary}")
                        except Exception as e:
                            return f"{summary}\n\n[summarize fallback: {e}]"
                    return summary
                if action in ("draft", "send_draft"):
                    to = tool_input.get("to") or []
                    payload = {
                        "subject": tool_input.get("subject", ""),
                        "body": {"contentType": "Text", "content": tool_input.get("body", "")},
                        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
                    }
                    resp = await client.post(f"{base}/messages", json=payload, headers=headers)
                    if resp.status_code not in (200, 201) or action == "draft":
                        return f"Outlook draft {resp.status_code}: {resp.text[:1000]}"
                    draft_id = resp.json().get("id")
                    send_resp = await client.post(f"{base}/messages/{draft_id}/send", headers=headers)
                    return f"Outlook send_draft {send_resp.status_code}"
            return f"Unknown Outlook action: {action}"

        # ---------- Zoho suite (Mail / Calendar / CRM / Desk / Cliq) ----------
        if impl_type.startswith("zoho_") or tool_id.startswith("tool_zoho_"):
            product = impl_type[5:] if impl_type.startswith("zoho_") else tool_id[len("tool_zoho_"):]
            return await _execute_zoho_tool(product, tool_input)

        # ---------- Generic: delegate to source_agent ----------
        source_agent = impl.get("source_agent")
        if source_agent:
            return f"[Tool '{tool_ref.get('name', tool_id)}' linked to {source_agent} — would execute in production. Input: {json.dumps(tool_input)[:500]}]"

        return f"[Tool '{tool_ref.get('name', tool_id)}' acknowledged. Input: {json.dumps(tool_input)[:500]}]"

    except Exception as e:
        return f"Tool error: {e}"


# ---------------------------------------------------------------------------
# Dynamic Agent
# ---------------------------------------------------------------------------

class DynamicAgent:
    """A runtime wrapper for a DB-defined agent."""

    def __init__(self, agent_def: Dict[str, Any]):
        self.agent_id = agent_def["id"]
        self.name = agent_def["name"]
        self.slug = agent_def["slug"]
        self.system_prompt = agent_def.get("system_prompt", "")
        self.llm_model = agent_def.get("llm_model", "")
        self.llm_provider = agent_def.get("llm_provider", "pwc_genai")
        self.temperature = agent_def.get("temperature", 0.7)
        self.max_tokens = agent_def.get("max_tokens", 4096)
        self.tools_config: List[Dict] = agent_def.get("tools_config", [])
        self.example_prompts = agent_def.get("example_prompts", [])
        # Credentials stored in default_config by the user (from ConfigStep)
        self.default_config: Dict[str, str] = agent_def.get("default_config") or {}

        self.ai_service = BaseAIService(
            default_model=self._resolve_model(),
            default_temperature=self.temperature,
            default_max_tokens=self.max_tokens,
            agent_name=self.name,
        )

    def _resolve_model(self) -> str:
        """Return the model id from the agent's own config (llm_model field).

        No hardcoded provider→model mapping — the model is always what the user
        selected in the agent builder UI / API.  For ``pwc_genai`` and ``gemini``
        providers an empty string is fine: the backend picks the default model.
        """
        return self.llm_model or ""

    def _get_tool_schema(self, tool_id: str) -> dict:
        """Return the schema_config for a tool from the in-memory registry (fast, no DB)."""
        try:
            from tool_registry import BUILTIN_TOOLS
            for t in BUILTIN_TOOLS:
                if t.get("id") == tool_id:
                    return t.get("schema_config", {})
        except Exception:
            pass
        return {}

    def _build_tool_prompt_section(self) -> str:
        if not self.tools_config:
            return ""
        lines = []
        for t in self.tools_config:
            if not isinstance(t, dict):
                lines.append(f"  - {t}: no description")
                continue
            name = t.get("name", t.get("id", "tool"))
            tool_id = t.get("id", "")
            desc = t.get("description", "")

            # Load the schema to show exact parameter names to the LLM
            schema = self._get_tool_schema(tool_id)
            props = schema.get("input", {}).get("properties", {})
            required = schema.get("input", {}).get("required", [])

            if props:
                param_parts = []
                for pname, pdef in props.items():
                    pdesc = pdef.get("description", pdef.get("type", "string"))
                    req = "*" if pname in required else ""
                    param_parts.append(f'{pname}{req}: {pdesc}')
                params_str = ", ".join(param_parts)
                lines.append(f'  - {name}: {desc}\n    Parameters: {params_str}  (* = required)')
            else:
                lines.append(f"  - {name}: {desc}")

        return TOOL_PROMPT_TEMPLATE.format(tool_list="\n".join(lines))

    def _build_prompt(self, query: str, session_id: Optional[str] = None, extra_context: str = "") -> str:
        # Read from the global persistent store so history survives agent re-loads
        history = _session_history.get(session_id or "", [])[-12:]

        try:
            from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS
            _src = f"\n\n{MANDATORY_MARKDOWN_SOURCE_LINKS}"
        except Exception:
            _src = ""
        parts = [f"System: {self.system_prompt}{_src}"]

        tool_section = self._build_tool_prompt_section()
        if tool_section:
            parts.append(tool_section)

        if extra_context:
            parts.append(extra_context)

        if history:
            parts.append("\nConversation history:")
            for msg in history:
                role_label = "Assistant" if msg["role"] == "assistant" else "User"
                # Truncate very long assistant turns (tool results can be huge)
                content = msg["content"]
                if len(content) > 2000:
                    content = content[:2000] + "... [truncated]"
                parts.append(f"{role_label}: {content}")

        parts.append(f"\nUser: {query}")
        return "\n".join(parts)

    def _extract_tool_call(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract a tool call from LLM output. Tries multiple formats."""
        # 1. Primary: TOOL_CALL: {...} on its own line
        for line in text.split('\n'):
            stripped = line.strip()
            if stripped.upper().startswith('TOOL_CALL:'):
                json_part = stripped[len('TOOL_CALL:'):].strip()
                try:
                    parsed = json.loads(json_part)
                    if 'tool' in parsed:
                        return parsed
                except json.JSONDecodeError:
                    pass

        # 2. Legacy: ```tool_call ... ``` fenced block (kept for backward compat)
        m = re.search(r'```tool_call\s*\n?(.*?)\n?```', text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1).strip())
                if 'tool' in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        # 3. Last resort: any JSON object with a "tool" key
        for m2 in re.finditer(r'\{[^{}]{5,500}\}', text):
            try:
                parsed = json.loads(m2.group())
                if 'tool' in parsed and 'input' in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        return None

    def _find_tool_ref(self, tool_name: str) -> Optional[Dict]:
        for t in self.tools_config:
            if isinstance(t, dict):
                if t.get("name") == tool_name or t.get("id") == tool_name:
                    return t
        return None

    def refresh_config(self):
        """Reload default_config (decrypted credentials) from DB without recreating the agent.

        Called before each turn so the agent always uses the latest saved credentials,
        even if the agent instance is cached across saves.
        """
        try:
            latest = get_agent_for_runtime(self.agent_id)
            if latest:
                self.default_config = latest.get("default_config") or {}
        except Exception:
            pass

    async def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> AsyncGenerator:
        """Async generator yielding SSE events. Runs a ReAct loop if tools are configured.

        Records a row to agent_usage_events on completion (success or failure) so
        the UI can show per-agent telemetry: calls, latency, errors, tool calls,
        and a rough token count.
        """
        sid = session_id or str(uuid.uuid4())

        # Ensure the session exists in the global persistent store
        if sid not in _session_history:
            _session_history[sid] = []

        # Always reload credentials from DB — the agent instance is cached but
        # the user may have updated keys via ConfigStep since last load.
        self.refresh_config()

        # Telemetry counters for this turn
        started = datetime.now(timezone.utc)
        tool_call_count = 0
        success = True
        error_message: Optional[str] = None
        usage_input_chars = len(query)
        usage_output_chars = 0

        yield {"event": "thinking", "data": {"type": "thinking", "content": f"Processing with {self.name}..."}}

        extra_context = ""
        has_tools = bool(self.tools_config)
        response = ""

        try:
            for iteration in range(MAX_TOOL_ITERATIONS if has_tools else 1):
                prompt = self._build_prompt(query, sid, extra_context)
                usage_input_chars += len(prompt)

                yield {"event": "thinking", "data": {"type": "thinking", "content": f"Calling LLM ({self.llm_model})..."}}

                try:
                    def _call_with_creds(_p=prompt):
                        with _inject_env(self.default_config):
                            return self.ai_service.call_genai(_p)
                    response = await asyncio.to_thread(_call_with_creds)
                except ValueError as e:
                    err_str = str(e)
                    if "Unexpected response format" in err_str or "empty" in err_str.lower():
                        yield {"event": "thinking", "data": {"type": "thinking", "content": "Retrying with simplified prompt..."}}
                        try:
                            simple_prompt = f"System: {self.system_prompt}\n\nUser: {query}"
                            if extra_context:
                                simple_prompt += f"\n\nContext:\n{extra_context[:2000]}"
                            def _retry_call(_p=simple_prompt):
                                with _inject_env(self.default_config):
                                    return self.ai_service.call_genai(_p)
                            response = await asyncio.to_thread(_retry_call)
                        except Exception as retry_err:
                            success = False
                            error_message = f"LLM call failed after retry: {retry_err}"
                            yield {"event": "error", "data": {"message": error_message}}
                            return
                    else:
                        success = False
                        error_message = f"LLM call failed: {e}"
                        yield {"event": "error", "data": {"message": error_message}}
                        return
                except Exception as e:
                    success = False
                    error_message = f"LLM call failed: {e}"
                    yield {"event": "error", "data": {"message": error_message}}
                    return

                if not has_tools:
                    break

                tool_call = self._extract_tool_call(response)
                if not tool_call:
                    break

                tool_call_count += 1
                tool_name = tool_call.get("tool", "")
                tool_input = tool_call.get("input", {})
                tool_ref = self._find_tool_ref(tool_name)

                yield {
                    "event": "thinking",
                    "data": {
                        "type": "tool_call",
                        "content": f"Using tool: {tool_name}",
                        "tool_name": tool_name,
                        "tool_input": json.dumps(tool_input)[:500],
                    },
                }

                if tool_ref:
                    async def _run_tool_with_creds(_ref=tool_ref, _inp=tool_input):
                        with _inject_env(self.default_config):
                            return await _execute_tool(_ref, _inp)
                    tool_result = await _run_tool_with_creds()
                else:
                    tool_result = f"Unknown tool: {tool_name}"

                yield {
                    "event": "thinking",
                    "data": {
                        "type": "tool_result",
                        "content": tool_result[:1000],
                        "tool_name": tool_name,
                    },
                }

                extra_context += f"\n\nTool call: {tool_name}({json.dumps(tool_input)[:300]})\nTool result:\n{tool_result[:3000]}\n"

            # Strip any leftover tool_call blocks from the final response
            clean_response = re.sub(r'```tool_call.*?```', '', response, flags=re.DOTALL).strip()
            if not clean_response:
                clean_response = response
            usage_output_chars = len(clean_response)

            # Stream the final response token-by-token (real word-level chunking)
            # so the client sees text appear as it arrives, not in fake fixed slices.
            for chunk in _stream_text_chunks(clean_response):
                yield {"event": "response_chunk", "data": {"chunk": chunk}}

            # Persist conversation
            _session_history[sid].append({"role": "user", "content": query})
            _session_history[sid].append({"role": "assistant", "content": clean_response})
            if len(_session_history[sid]) > 40:
                _session_history[sid] = _session_history[sid][-40:]

            yield {
                "success": True,
                "response": clean_response,
                "agent": self.name,
                "session_id": sid,
            }
        finally:
            # Always log usage — success or failure. Don't block on it.
            try:
                duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
                # Approximate tokens at ~4 chars/token; the LLM doesn't return real counts here
                approx_in = max(1, usage_input_chars // 4)
                approx_out = max(0, usage_output_chars // 4)
                await asyncio.to_thread(
                    record_usage,
                    self.agent_id,
                    user_id=user_id,
                    session_id=sid,
                    duration_ms=duration_ms,
                    success=success,
                    error_message=error_message,
                    input_tokens=approx_in,
                    output_tokens=approx_out,
                    tool_calls=tool_call_count,
                    llm_provider=self.llm_provider,
                    llm_model=self.llm_model,
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Runtime Manager
# ---------------------------------------------------------------------------

class DynamicAgentRuntime:
    """Singleton that manages loading and caching dynamic agents."""

    def load_agent(self, agent_id: str) -> Optional[DynamicAgent]:
        if agent_id in _runtime_cache:
            return _runtime_cache[agent_id]

        # Use the runtime accessor so the cached instance has decrypted creds
        agent_def = get_agent_for_runtime(agent_id)
        if not agent_def:
            agent_def = get_agent_by_slug_for_runtime(agent_id)
        if not agent_def:
            return None
        if agent_def.get("agent_type") != "custom":
            return None
        if agent_def.get("status") not in ("testing", "deployed", "published"):
            return None

        dyn = DynamicAgent(agent_def)
        _runtime_cache[agent_id] = dyn
        return dyn

    def invalidate(self, agent_id: str):
        _runtime_cache.pop(agent_id, None)

    def invalidate_all(self):
        _runtime_cache.clear()

    def clear_session(self, session_id: str):
        """Wipe conversation history for a session (called from 'New Chat' UI action)."""
        _session_history.pop(session_id, None)

    def get_session_length(self, session_id: str) -> int:
        return len(_session_history.get(session_id, []))


dynamic_runtime = DynamicAgentRuntime()
