"""Zoho Desk - read tickets and send customer replies.

Every Desk call needs the ``orgId`` header, which :class:`ZohoClient` attaches
from ``ZOHO_ORG_ID``. Without it Desk answers 404 rather than 401, so the
service checks for it up front and says so plainly.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..zoho_client import ZohoAPIError, ZohoClient

_log = logging.getLogger("zoho_desk")

# Desk priority values that count as "needs immediate attention".
ESCALATION_PRIORITIES = ("High", "Urgent")


class ZohoDeskService:
    """Read Zoho Desk tickets and reply to customers."""

    def __init__(self, client: ZohoClient):
        self.client = client

    @property
    def base(self) -> str:
        return self.client.settings.desk_base

    def _require_org(self) -> None:
        if not self.client.settings.org_id:
            raise ZohoAPIError(
                "ZOHO_ORG_ID is required for Zoho Desk calls. Find it in Desk under "
                "Setup > Developer Space > API, then add it to this agent's settings."
            )

    # -- reads -----------------------------------------------------------
    async def list_tickets(
        self,
        *,
        limit: int = 10,
        priority: str = "",
        status: str = "Open",
        department_id: str = "",
    ) -> List[Dict[str, Any]]:
        """List tickets, newest first, optionally filtered by priority/status."""
        self._require_org()
        params: Dict[str, Any] = {
            "limit": max(1, min(int(limit), 100)),
            "sortBy": "-createdTime",
        }
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        dept = department_id or self.client.settings.desk_department_id
        if dept:
            params["departmentId"] = dept
        payload = await self.client.get(f"{self.base}/tickets", params=params)
        return payload.get("data") or [] if isinstance(payload, dict) else []

    async def get_ticket(self, ticket_id: str) -> Dict[str, Any]:
        """Fetch one ticket, including its contact block."""
        if not ticket_id:
            raise ZohoAPIError("ticket_id is required to read a Desk ticket.")
        self._require_org()
        payload = await self.client.get(
            f"{self.base}/tickets/{ticket_id}", params={"include": "contacts,assignee,departments"}
        )
        return self.normalize_ticket(payload)

    async def get_latest_high_priority_ticket(self) -> Optional[Dict[str, Any]]:
        """Newest open ticket at High or Urgent priority, if there is one."""
        for priority in ESCALATION_PRIORITIES:
            tickets = await self.list_tickets(limit=5, priority=priority, status="Open")
            if tickets:
                return await self.get_ticket(str(tickets[0].get("id") or ""))
        return None

    async def get_ticket_threads(self, ticket_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Recent conversation threads on a ticket."""
        self._require_org()
        payload = await self.client.get(
            f"{self.base}/tickets/{ticket_id}/threads", params={"limit": max(1, min(int(limit), 50))}
        )
        return payload.get("data") or [] if isinstance(payload, dict) else []

    @staticmethod
    def normalize_ticket(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Flatten a Desk ticket into the fields the workflows actually use."""
        contact = raw.get("contact") or {}
        if not contact and isinstance(raw.get("contacts"), list) and raw["contacts"]:
            contact = raw["contacts"][0]
        first = contact.get("firstName") or ""
        last = contact.get("lastName") or ""
        contact_name = (f"{first} {last}").strip() or contact.get("name") or ""
        return {
            "ticket_id": str(raw.get("id") or ""),
            "ticket_number": str(raw.get("ticketNumber") or ""),
            "subject": raw.get("subject", ""),
            "description": raw.get("description", "") or "",
            "priority": raw.get("priority", "") or "",
            "status": raw.get("status", "") or "",
            "category": raw.get("category", "") or "",
            "created_time": raw.get("createdTime", ""),
            "due_date": raw.get("dueDate", ""),
            "web_url": raw.get("webUrl", ""),
            "department_id": str(raw.get("departmentId") or ""),
            "contact_name": contact_name,
            "contact_email": contact.get("email", "") or raw.get("email", "") or "",
            "contact_id": str(contact.get("id") or ""),
            "account_name": (raw.get("account") or {}).get("accountName", ""),
            "assignee": (raw.get("assignee") or {}).get("firstName", ""),
        }

    def is_escalation(self, ticket: Dict[str, Any]) -> bool:
        return (ticket.get("priority") or "") in ESCALATION_PRIORITIES

    # -- writes ----------------------------------------------------------
    async def create_ticket(self, *, subject: str, description: str, email: str) -> Dict[str, Any]:
        self._require_org()
        department_id = self.client.settings.desk_department_id
        if not department_id or not subject or not email:
            raise ZohoAPIError("Desk department, subject and contact email are required to create a ticket.")
        result = await self.client.post(
            f"{self.base}/tickets",
            json_body={
                "subject": subject[:255], "description": description,
                "departmentId": department_id, "contact": {"email": email},
                "email": email, "status": "Open",
            },
        )
        ticket = self.normalize_ticket(result or {})
        if not ticket["ticket_id"]:
            raise ZohoAPIError("Desk returned no created ticket ID. Check Desk before retrying.")
        return {"created": True, **ticket}

    async def send_reply(
        self,
        *,
        ticket_id: str,
        content: str,
        to_address: str = "",
        from_address: str = "",
        channel: str = "EMAIL",
    ) -> Dict[str, Any]:
        """Send an email reply on a ticket through Desk itself.

        Replying via Desk (rather than plain mail) keeps the response on the
        ticket timeline, which is what a support team expects to see.
        """
        if not ticket_id:
            raise ZohoAPIError("ticket_id is required to send a Desk reply.")
        if not content:
            raise ZohoAPIError("Reply content is required.")
        self._require_org()
        payload: Dict[str, Any] = {
            "channel": channel,
            "content": content,
            "contentType": "html",
            "isForward": "false",
        }
        if to_address:
            payload["to"] = to_address
        if from_address:
            payload["fromEmailAddress"] = from_address
        result = await self.client.post(f"{self.base}/tickets/{ticket_id}/sendReply", json_body=payload)
        return {
            "sent": True,
            "thread_id": str((result or {}).get("id") or ""),
            "ticket_id": ticket_id,
            "to": to_address,
        }

    async def add_comment(self, *, ticket_id: str, content: str, is_public: bool = False) -> Dict[str, Any]:
        """Add an internal (or public) comment to a ticket."""
        if not ticket_id or not content:
            raise ZohoAPIError("ticket_id and content are required to comment on a ticket.")
        self._require_org()
        result = await self.client.post(
            f"{self.base}/tickets/{ticket_id}/comments",
            json_body={"content": content, "isPublic": "true" if is_public else "false"},
        )
        return {"created": True, "comment_id": str((result or {}).get("id") or ""), "ticket_id": ticket_id}


__all__ = ["ESCALATION_PRIORITIES", "ZohoDeskService"]
