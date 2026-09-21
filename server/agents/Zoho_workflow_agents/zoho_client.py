"""Thin authenticated HTTP client for Zoho REST APIs.

One client instance serves a whole workflow run: it holds the resolved
settings, attaches the OAuth header, retries once on a 401 (token revoked
mid-run), and normalizes Zoho's assorted error envelopes into
:class:`ZohoAPIError`.

Services never touch ``httpx`` directly, which keeps them trivially testable
with a stub client.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx

from .config import ZohoSettings, get_settings
from .zoho_auth import ZohoAuthError, ensure_access_token, refresh_access_token

_log = logging.getLogger("zoho_client")

DEFAULT_TIMEOUT = 30.0


class ZohoAPIError(RuntimeError):
    """A Zoho API call failed. Carries status and the trimmed response body."""

    def __init__(self, message: str, *, status: int = 0, body: str = "", url: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body
        self.url = url

    def __str__(self) -> str:  # pragma: no cover - formatting only
        base = super().__str__()
        if self.status:
            return f"{base} (HTTP {self.status})"
        return base


class ZohoClient:
    """Authenticated async HTTP client for every Zoho product API."""

    def __init__(
        self,
        settings: Optional[ZohoSettings] = None,
        *,
        http: Optional[httpx.AsyncClient] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.settings = settings or get_settings()
        self._http = http
        self._owns_http = http is None
        self._timeout = timeout

    # -- lifecycle -------------------------------------------------------
    async def __aenter__(self) -> "ZohoClient":
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

    # -- core request ----------------------------------------------------
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        expect_json: bool = True,
    ) -> Any:
        """Perform an authenticated Zoho request and return the parsed body.

        Retries exactly once after refreshing the token on a 401, which is the
        only transient auth failure worth retrying automatically.
        """
        token = await ensure_access_token(self.settings, client=self._client())
        for attempt in (1, 2):
            headers = {
                "Authorization": f"Zoho-oauthtoken {token}",
                "Accept": "application/json",
            }
            if self.settings.org_id:
                headers["orgId"] = self.settings.org_id
            if extra_headers:
                headers.update(extra_headers)

            resp = await self._client().request(
                method.upper(), url, params=params, json=json_body, data=data, headers=headers
            )

            if resp.status_code == 401 and attempt == 1:
                _log.info("Zoho returned 401 for %s — refreshing token and retrying once", url)
                try:
                    token = await refresh_access_token(self.settings, client=self._client())
                except ZohoAuthError as exc:
                    raise ZohoAPIError(str(exc), status=401, url=url) from exc
                continue

            return self._parse(resp, url, expect_json)

        raise ZohoAPIError("Zoho request failed after token refresh", url=url)  # pragma: no cover

    def _parse(self, resp: httpx.Response, url: str, expect_json: bool) -> Any:
        if resp.status_code >= 400:
            raise ZohoAPIError(
                _friendly_error(resp, url),
                status=resp.status_code,
                body=resp.text[:1000],
                url=url,
            )
        if resp.status_code == 204 or not resp.content:
            return {}
        if not expect_json:
            return resp.text
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError):
            return {"raw": resp.text[:2000]}

    # -- verb helpers ----------------------------------------------------
    async def get(self, url: str, **kw) -> Any:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw) -> Any:
        return await self.request("POST", url, **kw)

    async def put(self, url: str, **kw) -> Any:
        return await self.request("PUT", url, **kw)

    async def patch(self, url: str, **kw) -> Any:
        return await self.request("PATCH", url, **kw)

    async def delete(self, url: str, **kw) -> Any:
        return await self.request("DELETE", url, **kw)


def _friendly_error(resp: httpx.Response, url: str) -> str:
    """Turn Zoho's several error shapes into one readable sentence."""
    detail = ""
    try:
        payload = resp.json()
    except Exception:
        payload = None

    if isinstance(payload, dict):
        # CRM: {"code": "...", "message": "..."}; Desk: {"errorCode", "message"}
        detail = str(payload.get("message") or payload.get("errorCode") or payload.get("code") or "")
        # Mail: {"status": {"code": 404, "description": "..."}}
        status_obj = payload.get("status")
        if not detail and isinstance(status_obj, dict):
            detail = str(status_obj.get("description") or "")
        data = payload.get("data")
        if not detail and isinstance(data, list) and data and isinstance(data[0], dict):
            detail = str(data[0].get("message") or "")
    if not detail:
        detail = resp.text[:200]

    if resp.status_code == 401:
        return "Zoho rejected the access token. Reconnect the Zoho account or check ZOHO_DC."
    if resp.status_code == 403:
        return f"Zoho denied the request — the OAuth scope for this call is missing. {detail}".strip()
    if resp.status_code == 404:
        return f"Zoho resource not found at {url}. {detail}".strip()
    if resp.status_code == 429:
        return "Zoho API rate limit reached. Retry in a minute."
    return f"Zoho API error: {detail}".strip()


__all__ = ["DEFAULT_TIMEOUT", "ZohoAPIError", "ZohoClient"]
