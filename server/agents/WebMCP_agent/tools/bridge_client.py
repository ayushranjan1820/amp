"""HTTP client for the local WebMCP bridge (Chrome extension + localhost server)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import httpx

WEBMCP_AGENT_VERSION = "1.0.0"


class WebMcpBridgeError(Exception):
    """Raised when the bridge returns an error or is unreachable."""


def _merge_tools_payload(raw: Any) -> List[Dict[str, Any]]:
    """Normalize GET /v1/tools JSON into a list of tool dicts."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    if isinstance(raw, dict):
        if "error" in raw and "tools" not in raw:
            return []
        tools = raw.get("tools", raw)
        if isinstance(tools, list):
            return [t for t in tools if isinstance(t, dict)]
    return []


class WebMcpBridgeClient:
    """Sync httpx client with Bearer auth and strict timeouts."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_sec: float = 60.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()
        self.timeout_sec = float(timeout_sec)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(self.timeout_sec, connect=10.0),
            headers={"Authorization": f"Bearer {self.token}"},
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()

    def __enter__(self) -> "WebMcpBridgeClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _raise_for_bridge(self, resp: httpx.Response, ctx: str) -> None:
        if resp.status_code < 400:
            return
        detail = resp.text[:2000]
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("detail"):
                detail = str(data["detail"])
        except Exception:
            pass
        raise WebMcpBridgeError(f"{ctx} failed ({resp.status_code}): {detail}")

    def health(self) -> Dict[str, Any]:
        """GET /health (no auth) — bridge process only."""
        try:
            r = self._client.get(self._url("/health"))
        except httpx.RequestError as e:
            raise WebMcpBridgeError(f"Bridge unreachable: {e}") from e
        self._raise_for_bridge(r, "health")
        return r.json()

    def session_info(self) -> Dict[str, Any]:
        r = self._client.get(self._url("/v1/session"))
        self._raise_for_bridge(r, "session")
        data = r.json()
        return data if isinstance(data, dict) else {}

    def list_tools_raw(self) -> Any:
        r = self._client.get(self._url("/v1/tools"))
        self._raise_for_bridge(r, "list_tools")
        return r.json()

    def list_tools(self) -> List[Dict[str, Any]]:
        raw = self.list_tools_raw()
        return _merge_tools_payload(raw)

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        payload = {"name": name, "arguments": arguments or {}}
        r = self._client.post(self._url("/v1/tools/call"), json=payload)
        self._raise_for_bridge(r, "call_tool")
        data = r.json()
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data

    def bridge_version(self) -> Dict[str, Any]:
        r = self._client.get(self._url("/v1/version"))
        self._raise_for_bridge(r, "version")
        data = r.json()
        return data if isinstance(data, dict) else {}


def host_allowed(
    session_url: str,
    allowed_hosts: Optional[List[str]],
    *,
    require_allowlist: bool,
) -> Union[bool, str]:
    """
    Returns True if allowed, or a string error message if blocked.

    - If ``require_allowlist`` is True, ``allowed_hosts`` must be non-empty and the
      session URL host must match (case-insensitive).
    - If ``require_allowlist`` is False and ``allowed_hosts`` is empty or None, any host is allowed.
    - If ``require_allowlist`` is False and ``allowed_hosts`` is non-empty, the host must match.
    """
    from urllib.parse import urlparse

    if require_allowlist and (not allowed_hosts or len(allowed_hosts) == 0):
        return "Host allowlist is required for this request but allowed_hosts is empty."

    if not allowed_hosts:
        return True

    try:
        host = (urlparse(session_url).hostname or "").lower()
    except Exception:
        return "Could not parse session URL for host check."

    if not host:
        return "Active tab has no HTTP(S) URL; host allowlist cannot be verified."

    allow = {h.strip().lower() for h in allowed_hosts if h and str(h).strip()}
    if host in allow:
        return True
    for h in allow:
        if h.startswith("*."):
            base = h[2:]
            if host == base or host.endswith("." + base):
                return True
    return f"Host {host!r} is not in allowed_hosts."
