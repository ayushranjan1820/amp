"""Zoho CRM - contact/account lookup and task creation (API v6)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..zoho_client import ZohoAPIError, ZohoClient

_log = logging.getLogger("zoho_crm")


def _first_record(payload: Any) -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list) and data:
            return data[0]
    return None


def _records(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
    return []


class ZohoCRMService:
    """Read contacts/accounts and create follow-up tasks in Zoho CRM."""

    def __init__(self, client: ZohoClient):
        self.client = client

    @property
    def base(self) -> str:
        return self.client.settings.crm_base

    # -- reads -----------------------------------------------------------
    async def search_contacts(self, *, email: str = "", name: str = "", limit: int = 5) -> List[Dict[str, Any]]:
        """Search Contacts by email (exact) or name (partial)."""
        params: Dict[str, Any] = {"per_page": max(1, min(int(limit), 50))}
        if email:
            params["email"] = email
        elif name:
            params["word"] = name
        else:
            raise ZohoAPIError("Provide an email or name to search CRM contacts.")
        try:
            payload = await self.client.get(f"{self.base}/Contacts/search", params=params)
        except ZohoAPIError as exc:
            # A search with no hits is a normal outcome, not a failure.
            if exc.status in (204, 404):
                return []
            raise
        return _records(payload)

    async def get_contact(self, contact_id: str) -> Dict[str, Any]:
        if not contact_id:
            raise ZohoAPIError("contact_id is required.")
        payload = await self.client.get(f"{self.base}/Contacts/{contact_id}")
        record = _first_record(payload)
        if not record:
            raise ZohoAPIError(f"CRM contact {contact_id} not found.")
        return record

    async def get_latest_contact(self) -> Optional[Dict[str, Any]]:
        """Most recently created contact - the "a new customer just landed" read."""
        payload = await self.client.get(
            f"{self.base}/Contacts",
            params={"per_page": 1, "sort_by": "Created_Time", "sort_order": "desc"},
        )
        return _first_record(payload)

    async def search_accounts(self, *, name: str, limit: int = 5) -> List[Dict[str, Any]]:
        if not name:
            raise ZohoAPIError("An account name is required to search CRM accounts.")
        try:
            payload = await self.client.get(
                f"{self.base}/Accounts/search",
                params={"word": name, "per_page": max(1, min(int(limit), 50))},
            )
        except ZohoAPIError as exc:
            if exc.status in (204, 404):
                return []
            raise
        return _records(payload)

    # -- writes ----------------------------------------------------------
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
        """Create a CRM Task, optionally linked to a contact or account."""
        if not subject:
            raise ZohoAPIError("A task subject is required.")
        record: Dict[str, Any] = {
            "Subject": subject,
            "Status": status,
            "Priority": priority,
        }
        if due_date:
            record["Due_Date"] = due_date.strftime("%Y-%m-%d")
        if description:
            record["Description"] = description
        owner = owner_id or self.client.settings.crm_owner_id
        if owner:
            record["Owner"] = {"id": owner}
        if related_contact_id:
            record["Who_Id"] = {"id": related_contact_id}
        if related_account_id:
            record["What_Id"] = {"id": related_account_id}
            record["$se_module"] = "Accounts"

        payload = await self.client.post(f"{self.base}/Tasks", json_body={"data": [record]})
        entry = _first_record(payload) or {}
        code = entry.get("code")
        if code and code != "SUCCESS":
            raise ZohoAPIError(f"CRM task creation failed: {entry.get('message') or code}")
        details = entry.get("details") or {}
        return {
            "created": True,
            "task_id": str(details.get("id") or ""),
            "subject": subject,
            "due_date": record.get("Due_Date", ""),
            "priority": priority,
        }

    async def create_note(self, *, parent_id: str, module: str, title: str, content: str) -> Dict[str, Any]:
        """Attach a note to a CRM record, used to log what a workflow did."""
        if not parent_id:
            raise ZohoAPIError("parent_id is required to create a CRM note.")
        record = {
            "Note_Title": title,
            "Note_Content": content,
            "Parent_Id": {"id": parent_id},
            "se_module": module,
        }
        payload = await self.client.post(f"{self.base}/Notes", json_body={"data": [record]})
        entry = _first_record(payload) or {}
        details = entry.get("details") or {}
        return {"created": True, "note_id": str(details.get("id") or ""), "title": title}


__all__ = ["ZohoCRMService"]
