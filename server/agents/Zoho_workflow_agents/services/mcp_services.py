"""MCP-backed services, method-for-method compatible with the REST ones.

Each class mirrors the signature of its counterpart in this package, so
``WorkflowContext`` can swap transports and the three workflow agents need no
changes at all. Return shapes match the REST services too, which keeps the
dry-run gate and the action summaries identical.

Reads come back as text from the MCP tool rather than typed JSON, so list and
read methods return best-effort structures with the raw text preserved under
``mcp_text``. Writes are what these workflows mainly do, and those map cleanly.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..zoho_mcp import ZohoMCPClient, ZohoMCPError

_log = logging.getLogger("zoho_mcp_services")


def _as_records(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pull a record list out of an MCP tool result, however it is shaped."""
    structured = result.get("structured")
    candidates: List[Any] = []
    if isinstance(structured, dict):
        data = structured.get("data")
        if isinstance(data, dict):
            candidates.extend([data.get("data"), data.get("records"), data.get("tickets"),
                               data.get("messages"), data.get("contacts")])
        candidates.extend([data, structured.get("records"), structured.get("tickets"),
                           structured.get("messages"), structured.get("contacts")])
    for candidate in candidates:
        if isinstance(candidate, list):
            return [r for r in candidate if isinstance(r, dict)]
        if isinstance(candidate, dict) and candidate:
            return [candidate]

    text = (result.get("text") or "").strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return []
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict)]
        if isinstance(parsed, dict):
            for key in ("data", "records", "tickets", "messages", "contacts"):
                inner = parsed.get(key)
                if isinstance(inner, list):
                    return [r for r in inner if isinstance(r, dict)]
            return [parsed]
    return []


def _first_id(result: Dict[str, Any], *keys: str) -> str:
    """Best-effort id extraction from a write result."""
    structured = result.get("structured")
    pools: List[Dict[str, Any]] = []
    if isinstance(structured, dict):
        pools.append(structured)
        for nested in ("data", "details", "result"):
            inner = structured.get(nested)
            if isinstance(inner, dict):
                pools.append(inner)
                deeper = inner.get("details")
                if isinstance(deeper, dict):
                    pools.append(deeper)
    for pool in pools:
        for key in keys:
            value = pool.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value)
    match = re.search(r"\b(?:id|Id|ID)[\"']?\s*[:=]\s*[\"']?([\w-]{4,})", result.get("text") or "")
    return match.group(1) if match else ""


class _McpBacked:
    """Common base: holds the client and the settings the workflows read."""

    def __init__(self, client: ZohoMCPClient, settings: Any):
        self.client = client
        self.settings = settings

    async def _call(self, capability: str, **fields: Any) -> Dict[str, Any]:
        return await self.client.call_capability(capability, fields)


# --------------------------------------------------------------------------- #
# Mail
# --------------------------------------------------------------------------- #

class McpMailService(_McpBacked):
    """Zoho Mail over MCP."""

    async def get_account_id(self) -> str:
        account = getattr(self, "_account", None)
        if account is None:
            accounts = _as_records(await self._call("mail.accounts"))
            sender = self.settings.from_address.strip().lower()
            matches = []
            for candidate in accounts:
                addresses = candidate.get("emailAddress") or []
                if isinstance(addresses, str):
                    addresses = [addresses]
                emails = [entry.get("mailId", "") if isinstance(entry, dict) else entry for entry in addresses]
                emails.append(candidate.get("primaryEmailAddress") or "")
                if sender and sender in {str(email).strip().lower() for email in emails}:
                    matches.append(candidate)
            choices = matches if sender else accounts
            if len(choices) != 1:
                raise ZohoMCPError("Cannot select a mail account. Configure ZOHO_FROM_ADDRESS to identify one connected account.")
            account = choices[0]
            self._account = account
        account_id = str(account.get("accountId") or account.get("account_id") or "")
        if not account_id:
            raise ZohoMCPError("The mail accounts tool did not return an accountId.")
        return account_id

    async def get_from_address(self) -> str:
        if self.settings.from_address:
            return self.settings.from_address
        await self.get_account_id()
        account = self._account
        addresses = account.get("emailAddress") or []
        if isinstance(addresses, str):
            return addresses
        primary = [entry.get("mailId", "") for entry in addresses if isinstance(entry, dict) and entry.get("isPrimary")]
        return str(account.get("primaryEmailAddress") or (primary[0] if len(primary) == 1 else ""))

    async def _account_fields(self, capability: str) -> Dict[str, str]:
        _name, schema = await self.client.resolve(capability)
        path = schema.get("properties", {}).get("path_variables", {})
        if "accountId" in path.get("properties", {}):
            return {"account_id": await self.get_account_id()}
        return {}

    async def list_messages(
        self,
        *,
        limit: int = 10,
        search: str = "",
        folder_id: str = "",
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        result = await self._call(
            "mail.list", query=search, limit=max(1, min(int(limit), 50)), folder_id=folder_id,
            fields="subject,messageId,folderId,fromAddress,toAddress,ccAddress,receivedTime,threadId",
            **await self._account_fields("mail.list"),
        )
        records = _as_records(result)
        if not records and result.get("text"):
            return [{"mcp_text": result["text"]}]
        return records

    async def get_message(self, message_id: str, folder_id: str = "") -> Dict[str, Any]:
        if not message_id:
            raise ZohoMCPError("message_id is required to read a message.")
        result = await self._call("mail.read", message_id=message_id, folder_id=folder_id,
                      **await self._account_fields("mail.read"))
        records = _as_records(result)
        record = records[0] if records else {}
        text = result.get("text") or ""
        return {
            "message_id": message_id,
            "folder_id": folder_id or str(record.get("folderId") or ""),
            "subject": record.get("subject") or _header(text, "subject"),
            "from": record.get("fromAddress") or _header(text, "from"),
            "to": record.get("toAddress") or _header(text, "to"),
            "cc": record.get("ccAddress", ""),
            "received_time": record.get("receivedTime") or _header(text, "received") or _header(text, "date"),
            "summary": (record.get("summary") or text)[:300],
            "body": record.get("content") or record.get("body") or text,
            "thread_id": str(record.get("threadId") or ""),
            "mcp_text": text,
        }

    async def get_latest_message(self, search: str = "", unread_only: bool = False) -> Optional[Dict[str, Any]]:
        messages = await self.list_messages(limit=5, search=search, unread_only=unread_only)
        if not messages:
            return None
        head = messages[0]
        message_id = str(head.get("messageId") or head.get("message_id") or head.get("id") or "")
        if not message_id:
            # The list tool returned prose; treat it as the message body itself.
            text = head.get("mcp_text") or ""
            return {
                "message_id": "", "folder_id": "", "subject": _header(text, "subject"),
                "from": _header(text, "from"), "to": "", "cc": "",
                "received_time": "", "summary": text[:300], "body": text,
                "thread_id": "", "mcp_text": text,
            }
        message = await self.get_message(message_id, folder_id=str(head.get("folderId") or ""))
        metadata_fields = {
            "subject": "subject", "from": "fromAddress", "to": "toAddress",
            "cc": "ccAddress", "received_time": "receivedTime", "thread_id": "threadId",
        }
        for field, source in metadata_fields.items():
            if not message.get(field):
                message[field] = head.get(source) or ""
        return message

    async def send_mail(
        self,
        *,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        content_type: str = "html",
        from_address: str = "",
    ) -> Dict[str, Any]:
        recipients = [a.strip() for a in (to or []) if a and a.strip()]
        if not recipients:
            raise ZohoMCPError("At least one recipient is required to send mail.")
        result = await self._call(
            "mail.send",
            to=recipients,
            cc=[a.strip() for a in (cc or []) if a and a.strip()],
            subject=subject or "(no subject)",
            body=body or "",
            from_address=from_address or await self.get_from_address(),
            content_type=content_type,
            **await self._account_fields("mail.send"),
        )
        return {
            "sent": True,
            "message_id": _first_id(result, "messageId", "message_id", "id"),
            "to": recipients,
            "subject": subject or "(no subject)",
            "via": "mcp",
        }


def _header(text: str, name: str) -> str:
    match = re.search(rf"^\s*{name}\s*:\s*(.+)$", text or "", re.I | re.M)
    return match.group(1).strip() if match else ""


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #

class McpCalendarService(_McpBacked):
    """Zoho Calendar over MCP."""

    async def list_calendars(self) -> List[Dict[str, Any]]:
        return []

    async def get_calendar_uid(self) -> str:
        return self.settings.calendar_id or "mcp-default"

    async def create_event(
        self,
        *,
        title: str,
        start: datetime,
        end: Optional[datetime] = None,
        duration_minutes: Optional[int] = None,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        timezone: str = "",
        calendar_uid: str = "",
    ) -> Dict[str, Any]:
        if not title:
            raise ZohoMCPError("An event title is required.")
        minutes = duration_minutes or self.settings.meeting_duration_minutes
        finish = end or (start + timedelta(minutes=minutes))
        tz = timezone or self.settings.timezone
        invitees = [a.strip() for a in (attendees or []) if a and a.strip()]

        result = await self._call(
            "calendar.create_event",
            title=title,
            start=start.isoformat(timespec="seconds"),
            end=finish.isoformat(timespec="seconds"),
            description=description,
            location=location,
            attendees=invitees,
            timezone=tz,
            calendar_id=calendar_uid or self.settings.calendar_id,
        )
        return {
            "created": True,
            "event_uid": _first_id(result, "uid", "eventId", "event_id", "id"),
            "calendar_uid": calendar_uid or self.settings.calendar_id or "mcp-default",
            "title": title,
            "start": start.isoformat(),
            "end": finish.isoformat(),
            "timezone": tz,
            "attendees": invitees,
            "via": "mcp",
        }

    async def list_events(
        self,
        *,
        calendar_uid: str = "",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        window_start = start or datetime.now()
        window_end = end or (window_start + timedelta(days=7))
        result = await self._call(
            "calendar.list_events",
            start=window_start.isoformat(timespec="seconds"),
            end=window_end.isoformat(timespec="seconds"),
            calendar_id=calendar_uid or self.settings.calendar_id,
        )
        return _as_records(result)


# --------------------------------------------------------------------------- #
# CRM
# --------------------------------------------------------------------------- #

class McpCRMService(_McpBacked):
    """Zoho CRM over MCP."""

    async def search_contacts(self, *, email: str = "", name: str = "", limit: int = 5) -> List[Dict[str, Any]]:
        if not email and not name:
            raise ZohoMCPError("Provide an email or name to search CRM contacts.")
        try:
            result = await self._call(
                "crm.search_contacts", email=email, name=name, module="Contacts", limit=limit
            )
        except ZohoMCPError as exc:
            # A lookup miss must not abort a workflow; the task still gets created.
            _log.info("CRM contact search unavailable over MCP: %s", exc)
            return []
        return _as_records(result)

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        if not contact_id:
            raise ZohoMCPError("contact_id is required.")
        result = await self._call("crm.search_contacts", name=contact_id, module="Contacts", limit=1)
        records = _as_records(result)
        if not records:
            raise ZohoMCPError(f"CRM contact {contact_id} not found over the MCP connection.")
        return records[0]

    async def get_latest_contact(self) -> Optional[Dict[str, Any]]:
        result = await self._call(
            "crm.get_records", module="Contacts", limit=1, sort_by="Created_Time", sort_order="desc"
        )
        records = _as_records(result)
        return records[0] if records else None

    async def search_accounts(self, *, name: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not name:
            raise ZohoMCPError("An account name is required.")
        try:
            result = await self._call("crm.search_contacts", name=name, module="Accounts", limit=limit)
        except ZohoMCPError:
            return []
        return _as_records(result)

    async def create_task(
        self,
        *,
        subject: str,
        due_date: Optional[datetime] = None,
        description: str = "",
        priority: str = "High",
        status: str = "Not Started",
        owner_id: str = "",
        related_contact_id: str = "",
        related_account_id: str = "",
    ) -> Dict[str, Any]:
        if not subject:
            raise ZohoMCPError("A task subject is required.")
        result = await self._call(
            "crm.create_task",
            subject=subject,
            due_date=due_date.strftime("%Y-%m-%d") if due_date else "",
            description=description,
            priority=priority,
            status=status,
            owner_id=owner_id or self.settings.crm_owner_id,
            related_contact_id=related_contact_id,
            module="Tasks",
        )
        return {
            "created": True,
            "task_id": _first_id(result, "id", "taskId", "task_id", "taskID"),
            "subject": subject,
            "due_date": due_date.strftime("%Y-%m-%d") if due_date else "",
            "priority": priority,
            "via": "mcp",
        }

    async def create_note(self, *, parent_id: str, module: str, title: str, content: str) -> Dict[str, Any]:
        raise ZohoMCPError(
            "Creating CRM notes is not mapped to an MCP capability. Use the REST transport for notes, "
            "or pin a tool with ZOHO_MCP_TOOL_PROJECTS_CREATE_TASK and adapt the workflow."
        )


# --------------------------------------------------------------------------- #
# Desk
# --------------------------------------------------------------------------- #

class McpProjectsService(_McpBacked):
    """Create follow-up tasks in the configured Projects destination."""

    async def create_task(
        self, *, subject: str, due_date: Optional[datetime] = None,
        description: str = "", priority: str = "High",
    ) -> Dict[str, Any]:
        from .projects_service import project_destination

        portal_id, project_id = project_destination(self.settings)
        if not subject:
            raise ZohoMCPError("A task subject is required.")
        result = await self._call(
            "projects.create_task", name=subject, description=description, priority=priority,
            portal_id=portal_id, project_id=project_id,
            due_date=due_date.strftime("%Y-%m-%d") if due_date else "",
        )
        return {
            "created": True, "task_id": _first_id(result, "id", "taskId", "task_id"),
            "subject": subject, "priority": priority,
            "due_date": due_date.strftime("%Y-%m-%d") if due_date else "", "via": "mcp",
        }

class McpDeskService(_McpBacked):
    """Zoho Desk over MCP."""

    # Kept so callers can reuse the REST normalizer.
    from .desk_service import ZohoDeskService as _Rest

    normalize_ticket = staticmethod(_Rest.normalize_ticket)

    async def create_ticket(self, *, subject: str, description: str, email: str) -> Dict[str, Any]:
        if not self.settings.desk_department_id or not subject or not email:
            raise ZohoMCPError("Desk department, subject and contact email are required to create a ticket.")
        result = await self._call(
            "desk.create_ticket", subject=subject[:255], description=description,
            department_id=self.settings.desk_department_id, contact={"email": email},
            email=email, status="Open", org_id=self.settings.org_id,
        )
        records = _as_records(result)
        ticket = self.normalize_ticket(records[0] if records else {})
        if not ticket["ticket_id"]:
            raise ZohoMCPError("Desk returned no created ticket ID. Check Desk before retrying.")
        return {"created": True, **ticket, "via": "mcp"}

    def is_escalation(self, ticket: Dict[str, Any]) -> bool:
        from .desk_service import ESCALATION_PRIORITIES

        return (ticket.get("priority") or "") in ESCALATION_PRIORITIES

    async def list_tickets(
        self,
        *,
        limit: int = 10,
        priority: str = "",
        status: str = "Open",
        department_id: str = "",
    ) -> List[Dict[str, Any]]:
        result = await self._call(
            "desk.list_tickets",
            priority=priority,
            status=status,
            limit=max(1, min(int(limit), 100)),
            department_id=department_id or self.settings.desk_department_id,
            sort_by="-createdTime",
        )
        return _as_records(result)

    async def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        if not ticket_id:
            raise ZohoMCPError("ticket_id is required to read a Desk ticket.")
        result = await self._call("desk.get_ticket", ticket_id=ticket_id)
        records = _as_records(result)
        if records:
            ticket = self.normalize_ticket(records[0])
        else:
            ticket = self.normalize_ticket({})
        if not ticket["ticket_id"]:
            raise ZohoMCPError("Desk did not return a real ticket record. No writes were attempted.")
        ticket["mcp_text"] = result.get("text", "")
        if not ticket.get("description") and ticket["mcp_text"]:
            ticket["description"] = ticket["mcp_text"]
        return ticket

    async def get_latest_high_priority_ticket(self) -> Optional[Dict[str, Any]]:
        from .desk_service import ESCALATION_PRIORITIES

        for priority in ESCALATION_PRIORITIES:
            tickets = await self.list_tickets(limit=5, priority=priority, status="Open")
            if tickets:
                ticket_id = str(tickets[0].get("id") or tickets[0].get("ticketId") or "")
                if ticket_id:
                    return await self.get_ticket(ticket_id)
                ticket = self.normalize_ticket(tickets[0])
                if ticket.get("ticket_id") or ticket.get("subject"):
                    return ticket
        return None

    async def get_ticket_threads(self, ticket_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        result = await self._call("desk.get_ticket", ticket_id=ticket_id, include="threads")
        return _as_records(result)

    async def send_reply(
        self,
        *,
        ticket_id: str,
        content: str,
        to_address: str = "",
        from_address: str = "",
        channel: str = "EMAIL",
    ) -> Dict[str, Any]:
        if not ticket_id:
            raise ZohoMCPError("ticket_id is required to send a Desk reply.")
        if not content:
            raise ZohoMCPError("Reply content is required.")
        result = await self._call(
            "desk.send_reply",
            ticket_id=ticket_id,
            body=content,
            to_address=to_address,
            channel=channel,
            from_address=from_address,
            send_immediately=True,
            org_id=self.settings.org_id,
        )
        return {
            "sent": True,
            "thread_id": _first_id(result, "id", "threadId", "thread_id"),
            "ticket_id": ticket_id,
            "to": to_address,
            "via": "mcp",
        }

    async def add_comment(self, *, ticket_id: str, content: str, is_public: bool = False) -> Dict[str, Any]:
        if not ticket_id or not content:
            raise ZohoMCPError("ticket_id and content are required.")
        result = await self._call(
            "desk.add_comment", ticket_id=ticket_id, body=content, is_public=is_public
        )
        return {
            "created": True,
            "comment_id": _first_id(result, "id", "commentId", "comment_id"),
            "ticket_id": ticket_id,
            "via": "mcp",
        }


# --------------------------------------------------------------------------- #
# Cliq
# --------------------------------------------------------------------------- #

class McpCliqService(_McpBacked):
    """Zoho Cliq over MCP."""

    def target_channel(self, channel: str = "") -> str:
        return channel or self.settings.cliq_channel

    async def post_message(
        self,
        *,
        text: str,
        channel: str = "",
        card_title: str = "",
        buttons: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        if not text:
            raise ZohoMCPError("Message text is required to post to Cliq.")
        target = self.target_channel(channel)
        if not target:
            raise ZohoMCPError(
                "No Cliq destination configured. Set ZOHO_CLIQ_CHANNEL to the channel name."
            )
        result = await self._call(
            "cliq.post_message", text=text, channel=target, card_title=card_title
        )
        return {
            "posted": True,
            "transport": "mcp",
            "channel": target,
            "message_id": _first_id(result, "id", "messageId", "message_id"),
        }

    async def list_channels(self, limit: int = 25) -> List[Dict[str, Any]]:
        return []


__all__ = [
    "McpCRMService",
    "McpCalendarService",
    "McpCliqService",
    "McpDeskService",
    "McpMailService",
]
