"""Zoho OAuth token handling.

Mirrors the intent of ``dynamic_agent_runtime._ensure_fresh_google_token`` but
uses Zoho's region-specific accounts host and its ``refresh_token`` grant.

Zoho access tokens live one hour. The refresh token is long lived and is the
credential an operator pastes into the agent configuration.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import httpx

from .config import ZohoSettings, get_settings

_log = logging.getLogger("zoho_auth")

# Refresh this many seconds before the real expiry so an in-flight workflow
# never trips over a token that dies mid-sequence.
_EXPIRY_SKEW_SEC = 120

_refresh_lock = asyncio.Lock()


class ZohoAuthError(RuntimeError):
    """Raised when no usable Zoho access token can be obtained."""


def _token_is_fresh(settings: ZohoSettings) -> bool:
    return bool(settings.access_token) and time.time() < (settings.token_expires_at - _EXPIRY_SKEW_SEC)


def _persist(access_token: str, expires_in: int) -> None:
    """Write the refreshed token back to the environment.

    The marketplace injects per-user config into ``os.environ`` for the
    duration of a request, so writing here keeps every later call in the same
    workflow on the same token.
    """
    os.environ["ZOHO_ACCESS_TOKEN"] = access_token
    os.environ["ZOHO_TOKEN_EXPIRES_AT"] = str(int(time.time()) + int(expires_in))


async def refresh_access_token(
    settings: Optional[ZohoSettings] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Exchange the refresh token for a new access token.

    Raises :class:`ZohoAuthError` when Zoho rejects the exchange so the caller
    can surface an actionable message instead of a bare HTTP error.
    """
    settings = settings or get_settings()
    if not settings.refresh_token:
        raise ZohoAuthError(
            "ZOHO_REFRESH_TOKEN is not configured. Generate one in the Zoho API "
            "Console (Self Client or Server-based app) and add it to this agent's settings."
        )
    if not settings.client_id or not settings.client_secret:
        raise ZohoAuthError("ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET are required to refresh the access token.")

    data = {
        "refresh_token": settings.refresh_token,
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "grant_type": "refresh_token",
    }

    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=20)
    try:
        resp = await http.post(settings.token_url, data=data)
    finally:
        if owns_client:
            await http.aclose()

    if resp.status_code != 200:
        raise ZohoAuthError(
            f"Zoho token refresh failed ({resp.status_code}) at {settings.token_url}: {resp.text[:300]}"
        )

    payload = resp.json()
    # Zoho returns HTTP 200 with an "error" body for invalid grants.
    if payload.get("error"):
        raise ZohoAuthError(
            f"Zoho token refresh rejected: {payload['error']}. "
            "Check the refresh token, client credentials, and that ZOHO_DC matches the account region."
        )

    access_token = payload.get("access_token", "")
    if not access_token:
        raise ZohoAuthError(f"Zoho token response contained no access_token: {str(payload)[:300]}")

    expires_in = int(payload.get("expires_in") or 3600)
    _persist(access_token, expires_in)
    _log.info("Zoho access token refreshed (dc=%s, ttl=%ss)", settings.dc, expires_in)
    return access_token


async def ensure_access_token(
    settings: Optional[ZohoSettings] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Return a valid access token, refreshing only when needed."""
    settings = settings or get_settings()
    if _token_is_fresh(settings):
        return settings.access_token

    async with _refresh_lock:
        # Re-read: another coroutine may have refreshed while we waited.
        current = get_settings()
        if _token_is_fresh(current):
            return current.access_token
        # Keep the caller's DC/credentials but pick up any token just written.
        current.client_id = current.client_id or settings.client_id
        current.client_secret = current.client_secret or settings.client_secret
        current.refresh_token = current.refresh_token or settings.refresh_token
        return await refresh_access_token(current, client=client)


def build_authorize_url(redirect_uri: str, scope: Optional[str] = None, settings: Optional[ZohoSettings] = None) -> str:
    """Build the consent URL for an offline (refresh-token) Zoho grant."""
    from urllib.parse import urlencode

    from .config import all_scopes

    settings = settings or get_settings()
    params = {
        "scope": scope or all_scopes(),
        "client_id": settings.client_id,
        "response_type": "code",
        "access_type": "offline",
        "redirect_uri": redirect_uri,
        "prompt": "consent",
    }
    return f"{settings.authorize_url}?{urlencode(params)}"


async def exchange_authorization_code(
    code: str,
    redirect_uri: str,
    settings: Optional[ZohoSettings] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    settings = settings or get_settings()
    data = {
        "grant_type": "authorization_code",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=20)
    try:
        resp = await http.post(settings.token_url, data=data)
    finally:
        if owns_client:
            await http.aclose()

    payload = resp.json() if resp.content else {}
    if resp.status_code != 200 or payload.get("error"):
        raise ZohoAuthError(
            f"Zoho code exchange failed ({resp.status_code}): {payload.get('error') or resp.text[:300]}"
        )
    if payload.get("access_token"):
        _persist(payload["access_token"], int(payload.get("expires_in") or 3600))
    return payload


__all__ = [
    "ZohoAuthError",
    "build_authorize_url",
    "ensure_access_token",
    "exchange_authorization_code",
    "refresh_access_token",
]
