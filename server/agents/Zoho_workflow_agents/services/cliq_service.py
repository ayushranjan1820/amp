"""Zoho Cliq - post workflow notifications to a channel.

Two delivery paths are supported, in this order:

1. An incoming-webhook URL (``ZOHO_CLIQ_WEBHOOK_URL``). No OAuth scope needed,
   which is the easiest thing for a team to set up for demos.
2. The Cliq REST API with the OAuth token, posting by channel name.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from ..zoho_client import ZohoAPIError, ZohoClient

_log = logging.getLogger("zoho_cliq")


class ZohoCliqService:
    """Post messages into Zoho Cliq channels."""

    def __init__(self, client: ZohoClient):
        self.client = client

    @property
    def base(self) -> str:
        return self.client.settings.cliq_base

    def target_channel(self, channel: str = "") -> str:
        return channel or self.client.settings.cliq_channel

    async def post_message(
        self,
        *,
        text: str,
        channel: str = "",
        card_title: str = "",
        buttons: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Post a message, preferring the webhook when one is configured."""
        if not text:
            raise ZohoAPIError("Message text is required to post to Cliq.")

        payload: Dict[str, Any] = {"text": text}
        if card_title:
            payload["card"] = {"title": card_title, "theme": "modern-inline"}
        if buttons:
            payload["buttons"] = buttons

        webhook = self.client.settings.cliq_webhook_url
        if webhook:
            return await self._post_webhook(webhook, payload)

        target = self.target_channel(channel)
        if not target:
            raise ZohoAPIError(
                "No Cliq destination configured. Set ZOHO_CLIQ_CHANNEL (channel name) "
                "or ZOHO_CLIQ_WEBHOOK_URL (incoming webhook)."
            )
        url = f"{self.base}/channelsbyname/{quote(target, safe='')}/message"
        result = await self.client.post(url, json_body=payload)
        return {
            "posted": True,
            "transport": "api",
            "channel": target,
            "message_id": str((result or {}).get("id") or ""),
        }

    async def _post_webhook(self, webhook_url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Incoming webhooks carry their own token in the URL, so no OAuth header."""
        async with httpx.AsyncClient(timeout=20) as http:
            resp = await http.post(webhook_url, json=payload)
        if resp.status_code >= 400:
            raise ZohoAPIError(
                f"Cliq webhook post failed: {resp.text[:300]}",
                status=resp.status_code,
                url=webhook_url,
            )
        return {"posted": True, "transport": "webhook", "channel": "(webhook)", "message_id": ""}

    async def list_channels(self, limit: int = 25) -> List[Dict[str, Any]]:
        payload = await self.client.get(f"{self.base}/channels", params={"limit": max(1, min(int(limit), 100))})
        if isinstance(payload, dict):
            return payload.get("channels") or payload.get("data") or []
        return []


__all__ = ["ZohoCliqService"]
