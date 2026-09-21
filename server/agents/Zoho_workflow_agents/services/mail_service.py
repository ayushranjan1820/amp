"""Zoho Mail — read messages and send mail.

Zoho Mail scopes every call to an ``accountId`` that must be looked up once per
account, so the id is cached on the service instance for the life of a run.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any, Dict, List, Optional

from ..zoho_client import ZohoAPIError, ZohoClient

_log = logging.getLogger("zoho_mail")

_TAG_RE = re.compile(r"<[^>]+>")
# "Name <user@example.com>" - an address, not markup.
_ANGLE_ADDR_RE = re.compile(r"<\s*([\w.+-]+@[\w-]+\.[\w.-]+)\s*>")
_HTML_HINT_RE = re.compile(
    r"(?i)<\s*(?:/?\s*(?:p|div|br|span|table|tr|td|th|ul|ol|li|a|b|i|strong|em|h[1-6]"
    r"|html|body|head|meta|style|script|img|font|blockquote)\b|!--)"
)


def looks_like_html(value: str) -> bool:
    """True when the text contains real markup, not just angle brackets."""
    return bool(value) and bool(_HTML_HINT_RE.search(value))


def strip_html(value: str) -> str:
    """Flatten an HTML mail body to readable plain text.

    Angle-bracketed email addresses are unwrapped rather than stripped, so a
    plain-text header line like ``From: Priya <priya@acme.com>`` keeps its
    address instead of losing it to tag removal.
    """
    if not value:
        return ""
    text = _ANGLE_ADDR_RE.sub(r"\1", value)
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def to_plain_text(value: str) -> str:
    """Normalize user-supplied content, leaving plain text untouched."""
    if not value:
        return ""
    return strip_html(value) if looks_like_html(value) else _ANGLE_ADDR_RE.sub(r"\1", value).strip()


def _extract_primary_address(account: Dict[str, Any]) -> str:
    """Pull the mailbox's own send-as address out of an account record.

    Zoho returns the address as a plain field on some plans and as a list of
    ``emailAddress`` entries (with one flagged primary) on others.
    """
    for key in ("primaryEmailAddress", "mailboxAddress", "incomingUserName"):
        value = account.get(key)
        if isinstance(value, str) and "@" in value:
            return value
    entries = account.get("emailAddress")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and entry.get("isPrimary") and entry.get("mailId"):
                return str(entry["mailId"])
        for entry in entries:
            if isinstance(entry, dict) and entry.get("mailId"):
                return str(entry["mailId"])
    return ""


class ZohoMailService:
    """Read and send mail through the Zoho Mail REST API."""

    def __init__(self, client: ZohoClient):
        self.client = client
        self._account_id: Optional[str] = None
        self._primary_address: str = ""

    @property
    def base(self) -> str:
        return self.client.settings.mail_base

    # -- account ---------------------------------------------------------
    async def get_account_id(self) -> str:
        """Resolve (and cache) the primary Zoho Mail account id."""
        if self._account_id:
            return self._account_id
        payload = await self.client.get(f"{self.base}/accounts")
        accounts = payload.get("data") or []
        if not accounts:
            raise ZohoAPIError("No Zoho Mail account is associated with these credentials.")
        account = accounts[0]
        self._account_id = str(account.get("accountId") or account.get("accountid") or "")
        self._primary_address = _extract_primary_address(account)
        if not self._account_id:
            raise ZohoAPIError("Zoho Mail account response contained no accountId.")
        return self._account_id

    async def get_from_address(self) -> str:
        """Sender address: explicit config wins, else the mailbox's own address."""
        configured = self.client.settings.from_address
        if configured:
            return configured
        if not self._primary_address:
            await self.get_account_id()
        return self._primary_address

    # -- read ------------------------------------------------------------
    async def list_messages(
        self,
        *,
        limit: int = 10,
        search: str = "",
        folder_id: str = "",
        unread_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List message headers from the mailbox, newest first."""
        account_id = await self.get_account_id()
        params: Dict[str, Any] = {"limit": max(1, min(int(limit), 50)), "start": 1}
        if folder_id:
            params["folderId"] = folder_id
        if unread_only:
            params["status"] = "unread"
        if search:
            params["searchKey"] = search
        payload = await self.client.get(f"{self.base}/accounts/{account_id}/messages/view", params=params)
        return payload.get("data") or []

    async def get_message(self, message_id: str, folder_id: str = "") -> Dict[str, Any]:
        """Fetch one message with its body content flattened to text."""
        if not message_id:
            raise ZohoAPIError("message_id is required to read a Zoho Mail message.")
        account_id = await self.get_account_id()
        detail = await self.client.get(f"{self.base}/accounts/{account_id}/messages/{message_id}/details")
        data = detail.get("data") or {}

        folder = folder_id or str(data.get("folderId") or "")
        content = ""
        if folder:
            try:
                body_payload = await self.client.get(
                    f"{self.base}/accounts/{account_id}/folders/{folder}/messages/{message_id}/content"
                )
                content = (body_payload.get("data") or {}).get("content", "")
            except ZohoAPIError as exc:
                _log.info("Zoho Mail content fetch failed for %s: %s", message_id, exc)

        return {
            "message_id": message_id,
            "folder_id": folder,
            "subject": data.get("subject", ""),
            "from": data.get("fromAddress", ""),
            "to": data.get("toAddress", ""),
            "cc": data.get("ccAddress", ""),
            "received_time": data.get("receivedTime", ""),
            "summary": data.get("summary", ""),
            "body": strip_html(content) or strip_html(data.get("summary", "")),
            "thread_id": str(data.get("threadId") or ""),
        }

    async def get_latest_message(self, search: str = "", unread_only: bool = False) -> Optional[Dict[str, Any]]:
        """Convenience read for 'process my newest matching email'."""
        messages = await self.list_messages(limit=5, search=search, unread_only=unread_only)
        if not messages:
            return None
        head = messages[0]
        return await self.get_message(
            str(head.get("messageId") or head.get("messageid") or ""),
            folder_id=str(head.get("folderId") or ""),
        )

    # -- write -----------------------------------------------------------
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
        """Send an email from the authenticated Zoho mailbox."""
        recipients = [a.strip() for a in (to or []) if a and a.strip()]
        if not recipients:
            raise ZohoAPIError("At least one recipient is required to send mail.")
        account_id = await self.get_account_id()
        sender = from_address or await self.get_from_address()
        if not sender:
            raise ZohoAPIError(
                "No sender address available. Set ZOHO_FROM_ADDRESS to the Zoho mailbox that should send."
            )
        payload: Dict[str, Any] = {
            "fromAddress": sender,
            "toAddress": ",".join(recipients),
            "subject": subject or "(no subject)",
            "content": body or "",
            "mailFormat": content_type,
        }
        if cc:
            cc_list = [a.strip() for a in cc if a and a.strip()]
            if cc_list:
                payload["ccAddress"] = ",".join(cc_list)
        result = await self.client.post(f"{self.base}/accounts/{account_id}/messages", json_body=payload)
        data = result.get("data") or {}
        return {
            "sent": True,
            "message_id": str(data.get("messageId") or ""),
            "to": recipients,
            "subject": payload["subject"],
        }


__all__ = ["ZohoMailService", "looks_like_html", "strip_html", "to_plain_text"]
