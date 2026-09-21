"""Zoho MCP transport - call Zoho through a pre-authorized MCP connection.

Zoho's MCP console can hold the authorization for every Zoho service ("Authorization
via Connection"), in which case this platform needs no client id, secret or refresh
token at all: it just calls tools on the connection's URL, which carries its own key.

Two problems make a naive client brittle, and both are handled here:

1. **Tool names are not fixed.** They depend on which services the console operator
   added to the connection. So capabilities are resolved at runtime against
   ``tools/list``, with an env override per capability for exact pinning.
2. **Argument names are not fixed either.** Each tool publishes an ``inputSchema``,
   so arguments are bound by matching our canonical field names against the schema's
   actual properties rather than hard-coding a guess.

Run ``python -m agents.Zoho_workflow_agents.discover_mcp`` to see what a connection
publishes and how it resolves.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

_log = logging.getLogger("zoho_mcp")

PROTOCOL_VERSION = "2025-06-18"
_JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class ZohoMCPError(RuntimeError):
    """An MCP call failed, or the connection cannot serve a needed capability."""


# --------------------------------------------------------------------------- #
# Capabilities
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Capability:
    """One operation a workflow needs from the MCP connection.

    ``patterns`` are matched (case-insensitively, as regexes) against published
    tool names. ``service`` is the Zoho product, used for error messages that
    tell an operator which service to add in the console.
    """

    key: str
    service: str
    summary: str
    patterns: Sequence[str]
    # Canonical field -> candidate argument names, best first. The schema decides.
    arguments: Dict[str, Sequence[str]] = field(default_factory=dict)

    @property
    def env_key(self) -> str:
        return f"ZOHO_MCP_TOOL_{self.key.upper().replace('.', '_')}"


_TEXT = ("content", "body", "text", "message", "html", "description")

CAPABILITIES: Dict[str, Capability] = {c.key: c for c in [
    Capability(
        key="mail.accounts",
        service="Zoho Mail",
        summary="List connected mail accounts",
        patterns=[r"mail.*(get|list).*accounts"],
    ),
    # ---- Mail -----------------------------------------------------------
    Capability(
        key="mail.list",
        service="Zoho Mail",
        summary="List or search mailbox messages",
        patterns=[r"mail.*(list|search|fetch|get).*(mail|message|email)", r"(list|search)_?e?mails?"],
        arguments={
            "query": ("searchKey", "search", "query", "keyword"),
            "limit": ("limit", "maxResults", "max_results", "count"),
            "fields": ("fields",),
            "folder_id": ("folderId", "folder_id", "folder"),
            "account_id": ("accountId", "account_id"),
        },
    ),
    Capability(
        key="mail.read",
        service="Zoho Mail",
        summary="Read one message with its body",
        patterns=[r"mail.*(read|detail|content|get).*(mail|message|email)", r"get_?e?mail(_?content|_?detail)?"],
        arguments={
            "message_id": ("messageId", "message_id", "mailId", "id"),
            "folder_id": ("folderId", "folder_id", "folder"),
            "account_id": ("accountId", "account_id"),
        },
    ),
    Capability(
        key="mail.send",
        service="Zoho Mail",
        summary="Send an email from the connected mailbox",
        patterns=[r"mail.*send", r"send_?e?mail"],
        arguments={
            "to": ("toAddress", "to", "recipients", "toRecipients"),
            "cc": ("ccAddress", "cc"),
            "subject": ("subject", "title"),
            "body": _TEXT,
            "from_address": ("fromAddress", "from", "sender"),
            "account_id": ("accountId", "account_id"),
            "content_type": ("mailFormat", "content_type"),
        },
    ),
    # ---- Calendar -------------------------------------------------------
    Capability(
        key="calendar.create_event",
        service="Zoho Calendar",
        summary="Create a calendar event",
        patterns=[r"calendar.*(create|add|book|schedule).*event", r"(create|add|schedule)_?(calendar_?)?event"],
        arguments={
            "title": ("title", "subject", "eventTitle", "summary", "name"),
            "start": ("start", "startTime", "start_time", "from", "startDateTime"),
            "end": ("end", "endTime", "end_time", "to", "endDateTime"),
            "description": ("description", "notes", "body", "agenda"),
            "location": ("location", "venue", "place"),
            "attendees": ("attendees", "participants", "invitees", "guests"),
            "timezone": ("timezone", "timeZone", "tz"),
            "calendar_id": ("calendarId", "calendar_id", "calendarUid", "caluid", "calendar"),
        },
    ),
    Capability(
        key="calendar.list_events",
        service="Zoho Calendar",
        summary="List calendar events in a window",
        patterns=[r"calendar.*(list|get|fetch).*event", r"(list|get)_?events?"],
        arguments={
            "start": ("start", "startTime", "from"),
            "end": ("end", "endTime", "to"),
            "calendar_id": ("calendarId", "calendar_id", "calendarUid"),
        },
    ),
    # ---- CRM ------------------------------------------------------------
    Capability(
        key="crm.search_contacts",
        service="Zoho CRM",
        summary="Find a CRM contact by email or name",
        patterns=[r"crm.*(search|find|get|lookup).*(contact|record|lead)", r"search_?(crm_?)?contacts?"],
        arguments={
            "email": ("email", "emailAddress", "email_address"),
            "name": ("name", "word", "keyword", "query", "search"),
            "module": ("module", "moduleName", "module_name"),
            "limit": ("limit", "perPage", "per_page", "max_results"),
        },
    ),
    Capability(
        key="crm.get_records",
        service="Zoho CRM",
        summary="List CRM records, newest first",
        patterns=[r"crm.*(list|get|fetch).*(record|contact)", r"get_?records?"],
        arguments={
            "module": ("module", "moduleName", "module_name"),
            "limit": ("limit", "perPage", "per_page", "max_results"),
            "sort_by": ("sortBy", "sort_by", "orderBy"),
            "sort_order": ("sortOrder", "sort_order", "order"),
        },
    ),
    Capability(
        key="crm.create_task",
        service="Zoho CRM",
        summary="Create a CRM follow-up task",
        patterns=[r"crm.*(create|add|insert).*(task|activity)", r"create_?(crm_?)?task"],
        arguments={
            "subject": ("Subject", "subject", "title", "name"),
            "due_date": ("Due_Date", "dueDate", "due_date", "date"),
            "description": ("Description", "description", "notes", "body"),
            "priority": ("Priority", "priority"),
            "status": ("Status", "status"),
            "owner_id": ("Owner", "ownerId", "owner_id", "assignee"),
            "related_contact_id": ("Who_Id", "contactId", "contact_id", "relatedContactId"),
            "module": ("module", "moduleName", "module_name"),
        },
    ),
    Capability(
        key="projects.create_task",
        service="Zoho Projects",
        summary="Create a Zoho Projects task",
        patterns=[r"projects?.*(create|add|insert).*task", r"create_?projects?_?task"],
        arguments={
            "name": ("name", "taskName", "task_name", "subject", "title"),
            "description": ("description", "notes", "body", "content"),
            "start_date": ("startDate", "start_date", "start"),
            "due_date": ("dueDate", "due_date", "end_date", "end", "deadline"),
            "priority": ("priority",),
            "owner_id": ("ownerId", "owner_id", "assignee"),
            "project_id": ("projectId", "project_id", "project", "portalProjectId"),
            "portal_id": ("portal_id", "portalId"),
        },
    ),
    # ---- Desk -----------------------------------------------------------
    Capability(
        key="desk.create_ticket",
        service="Zoho Desk",
        summary="Create a Desk follow-up ticket with contact details",
        patterns=[r"desk.*create_?ticket$", r"^create_?ticket$"],
        arguments={
            "subject": ("subject",),
            "description": ("description",),
            "department_id": ("departmentId", "department_id"),
            "contact": ("contact",),
            "email": ("email",),
            "status": ("status",),
            "org_id": ("orgId", "org_id"),
        },
    ),
    Capability(
        key="desk.list_tickets",
        service="Zoho Desk",
        summary="List Desk tickets, filterable by priority",
        patterns=[r"desk.*(list|search|get|fetch).*ticket", r"(list|search)_?tickets?"],
        arguments={
            "priority": ("priority", "Priority"),
            "status": ("status", "Status"),
            "limit": ("limit", "maxResults", "max_results", "count"),
            "department_id": ("departmentId", "department_id", "department"),
            "sort_by": ("sortBy", "sort_by", "orderBy"),
        },
    ),
    Capability(
        key="desk.get_ticket",
        service="Zoho Desk",
        summary="Read one Desk ticket with its contact",
        patterns=[r"desk.*(get|read|detail|fetch).*ticket", r"get_?ticket(_?detail)?"],
        arguments={
            "ticket_id": ("ticketId", "ticket_id", "id", "ticketNumber"),
            "include": ("include", "fields"),
        },
    ),
    Capability(
        key="desk.send_reply",
        service="Zoho Desk",
        summary="Send an email reply on a Desk ticket",
        patterns=[r"desk.*(reply|respond|answer)", r"send_?reply", r"ticket.*reply"],
        arguments={
            "ticket_id": ("ticketId", "ticket_id", "id"),
            "body": _TEXT,
            "to_address": ("to", "toAddress", "to_address", "email"),
            "channel": ("channel", "medium"),
            "from_address": ("fromEmailAddress", "fromAddress", "from"),
            "send_immediately": ("sendImmediately", "send_immediately"),
            "org_id": ("orgId", "org_id"),
        },
    ),
    Capability(
        key="desk.add_comment",
        service="Zoho Desk",
        summary="Add a comment to a Desk ticket",
        patterns=[r"desk.*comment", r"(add|create)_?comment"],
        arguments={
            "ticket_id": ("ticketId", "ticket_id", "id"),
            "body": _TEXT,
            "is_public": ("isPublic", "is_public", "public"),
        },
    ),
    # ---- Cliq -----------------------------------------------------------
    Capability(
        key="cliq.post_message",
        service="Zoho Cliq",
        summary="Post a message to a Cliq channel",
        patterns=[r"cliq.*(post|send).*channel", r"cliq_?(post|send)_?message$", r"^(post|send)_?(cliq_?)?message$", r"send_?channel_?message"],
        arguments={
            "text": ("text", "message", "content", "body"),
            "channel": ("channel", "channelName", "channel_name", "chatId", "to"),
            "card_title": ("title", "cardTitle", "card_title"),
        },
    ),
]}

# Which capabilities each workflow agent needs to run end to end.
AGENT_CAPABILITIES: Dict[str, Dict[str, List[str]]] = {
    "zoho_email_meeting_agent": {
        "required": ["calendar.create_event", "mail.send", "projects.create_task"],
        "optional": ["mail.list", "mail.read"],
    },
    "zoho_support_ticket_agent": {
        "required": ["desk.get_ticket", "desk.add_comment", "projects.create_task", "desk.send_reply"],
        "optional": ["desk.list_tickets"],
    },
    "zoho_new_customer_agent": {
        "required": ["mail.send", "calendar.create_event", "desk.create_ticket"],
        "optional": ["mail.accounts"],
    },
}


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #

class ZohoMCPClient:
    """JSON-RPC client for a Zoho MCP connection over streamable HTTP."""

    def __init__(
        self,
        url: str,
        *,
        http: Optional[httpx.AsyncClient] = None,
        timeout: float = 60.0,
    ):
        if not url:
            raise ZohoMCPError("A Zoho MCP server URL is required. Set ZOHO_MCP_URL.")
        self.url = url
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout
        self._initialized = False
        self._session_id: Optional[str] = None
        self._tools: Optional[List[Dict[str, Any]]] = None
        self._lock = asyncio.Lock()
        self._rid = 0

    # -- lifecycle -------------------------------------------------------
    async def __aenter__(self) -> "ZohoMCPClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout, follow_redirects=True)
            self._owns_http = True
        return self._http

    def _headers(self) -> Dict[str, str]:
        headers = dict(_JSON_HEADERS)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    # -- transport -------------------------------------------------------
    async def _rpc(self, method: str, params: Optional[Dict[str, Any]] = None, *, notify: bool = False) -> Any:
        body: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._rid += 1
            body["id"] = self._rid

        try:
            resp = await self._client().post(self.url, json=body, headers=self._headers())
        except httpx.HTTPError as exc:
            raise ZohoMCPError(f"Could not reach the Zoho MCP server: {exc}") from exc

        session = resp.headers.get("mcp-session-id")
        if session:
            self._session_id = session

        if notify:
            return None

        if resp.status_code >= 400:
            raise ZohoMCPError(
                f"Zoho MCP {method} failed (HTTP {resp.status_code}). "
                f"Check that ZOHO_MCP_URL is the full /message endpoint. {resp.text[:300]}"
            )

        payload = _parse_rpc_body(resp.text)
        if not isinstance(payload, dict):
            raise ZohoMCPError(f"Zoho MCP {method} returned an unreadable body: {resp.text[:300]}")
        if payload.get("error"):
            err = payload["error"]
            raise ZohoMCPError(
                f"Zoho MCP {method} error {err.get('code', '')}: {err.get('message', str(err))}"
            )
        return payload.get("result")

    async def initialize(self) -> Dict[str, Any]:
        """Perform the MCP handshake once per client."""
        async with self._lock:
            if self._initialized:
                return {}
            result = await self._rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "agent-marketplace-zoho", "version": "1.0.0"},
                },
            )
            await self._rpc("notifications/initialized", notify=True)
            self._initialized = True
            server = (result or {}).get("serverInfo") or {}
            _log.info("Zoho MCP connected: %s %s", server.get("name", "?"), server.get("version", ""))
            return result or {}

    # -- tools -----------------------------------------------------------
    async def list_tools(self, *, refresh: bool = False) -> List[Dict[str, Any]]:
        """Published tools, paged through and cached for the client's life."""
        if self._tools is not None and not refresh:
            return self._tools
        await self.initialize()

        tools: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        while True:
            params = {"cursor": cursor} if cursor else None
            result = await self._rpc("tools/list", params) or {}
            batch = result.get("tools") or []
            tools.extend(t for t in batch if isinstance(t, dict))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        self._tools = tools
        return tools

    async def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call one tool and normalize its result.

        Zoho returns business failures with ``isError`` false and a
        ``structuredContent.status`` of ``failure``, so both are checked.
        """
        await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}

        text = _collect_text(result.get("content"))
        structured = result.get("structuredContent")
        failed = bool(result.get("isError"))
        if isinstance(structured, dict) and str(structured.get("status", "")).lower() == "failure":
            failed = True

        if failed:
            detail = ""
            if isinstance(structured, dict):
                data = structured.get("data")
                if isinstance(data, dict):
                    detail = str(data.get("message") or data.get("error") or "")
            raise ZohoMCPError(f"Zoho MCP tool '{name}' failed: {detail or text or 'no detail returned'}")

        return {"tool": name, "text": text, "structured": structured, "raw": result}

    # -- capability resolution -------------------------------------------
    async def resolve(self, capability_key: str) -> Tuple[str, Dict[str, Any]]:
        """Find the published tool serving *capability_key*.

        Returns ``(tool_name, input_schema)``. An explicit env override wins;
        otherwise names are scored against the capability's patterns.
        """
        cap = CAPABILITIES.get(capability_key)
        if cap is None:
            raise ZohoMCPError(f"Unknown Zoho capability '{capability_key}'")

        tools = await self.list_tools()
        by_name = {str(t.get("name", "")): t for t in tools}

        override = (os.environ.get(cap.env_key) or "").strip()
        if override:
            tool = by_name.get(override)
            if tool is None:
                raise ZohoMCPError(
                    f"{cap.env_key} is set to '{override}', but the MCP connection does not publish "
                    f"a tool by that name. Published tools: {', '.join(sorted(by_name)) or 'none'}."
                )
            return override, tool.get("inputSchema") or {}

        if not tools:
            raise ZohoMCPError(
                "The Zoho MCP connection publishes no tools at all. Add the Zoho services you need "
                "to the connection in the Zoho MCP console, then try again. "
                f"This workflow step needs: {cap.service} - {cap.summary}."
            )

        match = _best_match(cap, tools)
        if match is None:
            raise ZohoMCPError(
                f"No tool on the MCP connection matches '{cap.key}' ({cap.service} - {cap.summary}). "
                f"Enable {cap.service} in the Zoho MCP console, or pin the tool with {cap.env_key}=<tool name>. "
                f"Published tools: {', '.join(sorted(by_name))}."
            )
        name, tool = match
        _log.info("Zoho MCP capability %s -> tool %s", cap.key, name)
        return name, tool.get("inputSchema") or {}

    async def call_capability(self, capability_key: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve a capability and call it, binding arguments to its real schema."""
        cap = CAPABILITIES[capability_key]
        name, schema = await self.resolve(capability_key)
        arguments = bind_arguments(cap, fields, schema)
        _log.debug("Zoho MCP call %s(%s)", name, list(arguments))
        return await self.call_tool(name, arguments)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _parse_rpc_body(text: str) -> Any:
    """Parse a JSON-RPC body that may arrive as plain JSON or as an SSE frame."""
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.startswith("{") or raw.startswith("["):
        try:
            return json.loads(raw)
        except ValueError:
            pass
    # Streamable HTTP may answer with "event: message\ndata: {...}".
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            candidate = line[5:].strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except ValueError:
                    continue
    return None


def _collect_text(content: Any) -> str:
    """Flatten an MCP content array into text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for item in content:
        if isinstance(item, dict):
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
            elif item.get("text"):
                parts.append(str(item["text"]))
        elif isinstance(item, str):
            parts.append(item)
    return "\n".join(parts).strip()


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def _best_match(cap: Capability, tools: List[Dict[str, Any]]) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Score published tools against a capability's patterns; best wins.

    A tool's description is considered too, but at lower weight than its name,
    so a name match is never beaten by prose.
    """
    best: Optional[Tuple[int, str, Dict[str, Any]]] = None
    for tool in tools:
        raw_name = str(tool.get("name", ""))
        if not raw_name:
            continue
        name = _normalize(raw_name)
        if cap.key in ("mail.list", "mail.read") and "account" in name:
            continue
        haystacks = ((name, 10), (_normalize(tool.get("description", "")), 3))
        if cap.key in ("mail.list", "mail.read", "desk.create_ticket"):
            haystacks = ((name, 10),)
        score = 0
        for pattern in cap.patterns:
            compiled = re.compile(pattern.replace(".*", "[a-z0-9_]*"), re.I)
            for text, weight in haystacks:
                if compiled.search(text):
                    score += weight
                    break
        if score and cap.service:
            # Prefer a tool whose name mentions the product, e.g. "zohomail_…".
            product = _normalize(cap.service).replace("zoho_", "")
            if product and product in name:
                score += 4
        if score and (best is None or score > best[0]):
            best = (score, raw_name, tool)
    if best is None:
        return None
    return best[1], best[2]


def _schema_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
    props: Dict[str, Any] = {}
    for keyword in ("allOf", "anyOf", "oneOf"):
        for branch in (schema or {}).get(keyword, []):
            props.update(_schema_properties(branch))
    props.update((schema or {}).get("properties") or {})
    return props


def _argument_paths(schema: Dict[str, Any], prefix: Tuple[str, ...] = (), *, include_objects: bool = False) -> Dict[Tuple[str, ...], Any]:
    paths = {}
    for name, prop in _schema_properties(schema).items():
        path = prefix + (name,)
        if _schema_properties(prop):
            if include_objects:
                paths[path] = prop
            paths.update(_argument_paths(prop, path, include_objects=include_objects))
        else:
            paths[path] = prop
    return paths


def bind_arguments(cap: Capability, fields: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Map canonical workflow fields onto a tool's real argument names.

    Resolution per field: an exact schema property from the candidate list, then
    a case-insensitive match, then a substring match. Fields the schema does not
    accept are dropped rather than sent, because Zoho rejects unknown arguments.
    When the tool publishes no schema, candidate names are used as-is.
    """
    paths = dict(sorted(_argument_paths(schema).items(), key=lambda item: len(item[0])))
    out: Dict[str, Any] = {}

    for field_name, value in fields.items():
        if value is None or value == "" or value == []:
            continue
        candidates = cap.arguments.get(field_name) or (field_name,)
        if isinstance(value, dict):
            object_paths = _argument_paths(schema, include_objects=True)
            target = next((path for candidate in candidates for path in object_paths if path[-1] == candidate), None)
            if target:
                container = out
                for segment in target[:-1]:
                    container = container.setdefault(segment, {})
                container[target[-1]] = value
                continue

        if not paths:
            out[candidates[0]] = value
            continue

        target = None
        for candidate in candidates:
            target = next((path for path in paths if path[-1] == candidate), None)
            if target:
                break
        if target is None:
            for candidate in candidates:
                target = next((path for path in paths if path[-1].lower() == candidate.lower()), None)
                if target:
                    break
        if target is None:
            for candidate in candidates:
                needle = _normalize(candidate)
                for path in paths:
                    if needle and needle in _normalize(path[-1]):
                        target = path
                        break
                if target:
                    break
        if target is None:
            _log.info(
                "Zoho MCP: tool for %s accepts no argument like %r; dropping it",
                cap.key, candidates[0],
            )
            continue
        container = out
        for segment in target[:-1]:
            container = container.setdefault(segment, {})
        if cap.key == "calendar.create_event" and "dateandtime" in target and field_name in ("start", "end"):
            value = datetime.fromisoformat(value).strftime("%Y%m%dT%H%M%S")
        container[target[-1]] = _coerce(value, paths[target])

    return out


def _coerce(value: Any, prop_schema: Any) -> Any:
    """Reshape a value to the type the schema asks for (lists vs strings, mostly)."""
    if not isinstance(prop_schema, dict):
        return value
    wanted = prop_schema.get("type")
    if isinstance(value, str):
        for option in prop_schema.get("enum", []):
            if isinstance(option, str) and value.lower() == option.lower():
                return option
    if wanted == "array" and isinstance(value, (list, tuple)):
        item_schema = prop_schema.get("items", {})
        if "email" in _schema_properties(item_schema):
            return [{"email": item} if isinstance(item, str) else item for item in value]
    if wanted == "string" and isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if wanted == "array" and not isinstance(value, (list, tuple)):
        return [value]
    if wanted in ("integer", "number") and isinstance(value, str) and value.isdigit():
        return int(value)
    if wanted == "boolean" and isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if wanted == "string" and isinstance(value, bool):
        return "true" if value else "false"
    return value


def capabilities_for_agent(agent_id: str) -> Dict[str, List[str]]:
    """Required and optional capability keys for one catalog agent id."""
    return AGENT_CAPABILITIES.get(agent_id, {"required": [], "optional": []})


__all__ = [
    "AGENT_CAPABILITIES",
    "CAPABILITIES",
    "Capability",
    "PROTOCOL_VERSION",
    "ZohoMCPClient",
    "ZohoMCPError",
    "bind_arguments",
    "capabilities_for_agent",
]
