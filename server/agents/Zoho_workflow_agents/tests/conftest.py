"""Shared fixtures: a fake Zoho HTTP transport and clean credential env."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import pytest

# Server modules are imported as top-level names (``agents.…``, ``tool_registry``),
# so the tests work whether pytest is run from ``server/`` or the repo root.
_SERVER_DIR = Path(__file__).resolve().parents[3]
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

ZOHO_ENV_KEYS = (
    "ZOHO_MCP_URL",
    "ZOHO_MCP_SERVER_URL",
    "ZOHO_BACKEND",
    "ZOHO_CLIENT_ID",
    "ZOHO_CLIENT_SECRET",
    "ZOHO_REFRESH_TOKEN",
    "ZOHO_ACCESS_TOKEN",
    "ZOHO_TOKEN_EXPIRES_AT",
    "ZOHO_DC",
    "ZOHO_ACCOUNTS_BASE_URL",
    "ZOHO_ORG_ID",
    "ZOHO_CALENDAR_ID",
    "ZOHO_PROJECTS_PORTAL_ID",
    "ZOHO_PROJECTS_PROJECT_ID",
    "ZOHO_CRM_OWNER_ID",
    "ZOHO_CLIQ_CHANNEL",
    "ZOHO_CLIQ_WEBHOOK_URL",
    "ZOHO_DESK_DEPARTMENT_ID",
    "ZOHO_TIMEZONE",
    "ZOHO_MEETING_DURATION_MINUTES",
    "ZOHO_FROM_ADDRESS",
    "ZOHO_DRY_RUN",
    "ZOHO_CONFIRM_WRITES",
)


@pytest.fixture(autouse=True)
def clean_zoho_env(monkeypatch):
    """Start every test from a known-empty Zoho environment."""
    for key in ZOHO_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ZOHO_PROJECTS_PORTAL_ID", "123")
    monkeypatch.setenv("ZOHO_PROJECTS_PROJECT_ID", "456")
    yield


@pytest.fixture
def configured_env(monkeypatch):
    """Credentials present, live writes enabled, US data center."""
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rtoken")
    monkeypatch.setenv("ZOHO_ORG_ID", "org123")
    monkeypatch.setenv("ZOHO_DESK_DEPARTMENT_ID", "dept123")
    monkeypatch.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    monkeypatch.setenv("ZOHO_CLIQ_CHANNEL", "support")
    monkeypatch.setenv("ZOHO_FROM_ADDRESS", "ops@example.com")
    monkeypatch.setenv("ZOHO_TIMEZONE", "Asia/Kolkata")
    monkeypatch.setenv("ZOHO_DRY_RUN", "false")
    monkeypatch.setenv("ZOHO_CONFIRM_WRITES", "true")
    return monkeypatch


class FakeZoho:
    """Records requests and answers them from registered route handlers."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, str, Dict[str, Any]]] = []
        self._routes: List[Tuple[str, str, Callable[[httpx.Request], httpx.Response]]] = []

    def route(self, method: str, url_contains: str, handler) -> "FakeZoho":
        """Register a handler. Re-registering the same method+fragment replaces it,
        so a test can override a route set up by a shared helper."""
        key = (method.upper(), url_contains)
        self._routes = [r for r in self._routes if (r[0], r[1]) != key]
        self._routes.append((method.upper(), url_contains, handler))
        return self

    def json(self, method: str, url_contains: str, payload: Any, status: int = 200) -> "FakeZoho":
        return self.route(
            method, url_contains, lambda _req: httpx.Response(status, json=payload)
        )

    # -- transport -------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        body: Dict[str, Any] = {}
        raw = request.content or b""
        if raw:
            try:
                body = json.loads(raw)
            except ValueError:
                body = {"_raw": raw.decode(errors="replace")}
        self.calls.append((request.method, str(request.url), body))

        # Most specific route wins: Zoho URLs nest ("/api/accounts" is a prefix of
        # "/api/accounts/1/messages/2/details"), so matching on registration order
        # would answer detail calls with the account payload.
        matches = [
            (fragment, handler)
            for method, fragment, handler in self._routes
            if request.method == method and fragment in str(request.url)
        ]
        if matches:
            matches.sort(key=lambda pair: len(pair[0]), reverse=True)
            return matches[0][1](request)
        return httpx.Response(404, json={"message": f"no fake route for {request.method} {request.url}"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    # -- assertions ------------------------------------------------------
    def urls(self, method: str = "") -> List[str]:
        return [u for m, u, _ in self.calls if not method or m == method.upper()]

    def writes(self) -> List[str]:
        """POST/PUT/PATCH/DELETE URLs, excluding the OAuth token exchange.

        The token endpoint is a POST but it is authentication, not a business
        write, so dry-run assertions must ignore it.
        """
        return [
            u
            for m, u, _ in self.calls
            if m in ("POST", "PUT", "PATCH", "DELETE") and "/oauth/v2/token" not in u
        ]

    def called(self, method: str, fragment: str) -> bool:
        return any(m == method.upper() and fragment in u for m, u, _ in self.calls)

    def body_for(self, method: str, fragment: str) -> Dict[str, Any]:
        for m, u, b in self.calls:
            if m == method.upper() and fragment in u:
                return b
        return {}


@pytest.fixture
def fake_zoho() -> FakeZoho:
    fake = FakeZoho()
    # Token refresh always succeeds unless a test overrides it.
    fake.json("POST", "/oauth/v2/token", {"access_token": "at-1", "expires_in": 3600})
    return fake


# --------------------------------------------------------------------------- #
# Fake Zoho MCP server
# --------------------------------------------------------------------------- #

MCP_URL = "https://agent-test.zohomcp.in/mcp/testkey/message"


class FakeMCP:
    """A minimal in-process Zoho MCP server over an httpx MockTransport.

    Tools are registered with a name, an input schema and a handler, which lets
    tests assert on the exact arguments the services bind.
    """

    def __init__(self) -> None:
        self.tools: List[Dict[str, Any]] = []
        self.handlers: Dict[str, Any] = {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.initialized = False

    def add_tool(
        self,
        name: str,
        *,
        properties: Optional[Dict[str, Any]] = None,
        required: Optional[List[str]] = None,
        description: str = "",
        result: Any = None,
        handler: Optional[Any] = None,
    ) -> "FakeMCP":
        self.tools.append({
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": properties or {},
                "required": required or [],
            },
        })
        self.handlers[name] = handler or (lambda _args: result if result is not None else {"ok": True})
        return self

    # -- transport -------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        method = body.get("method")
        rid = body.get("id")

        def ok(result: Any) -> httpx.Response:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": result})

        if method == "initialize":
            self.initialized = True
            return ok({
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "zoho-mcp", "version": "1.0.0"},
            })
        if method == "notifications/initialized":
            return httpx.Response(202, json={})
        if method == "tools/list":
            return ok({"tools": self.tools})
        if method == "tools/call":
            params = body.get("params") or {}
            name = params.get("name", "")
            args = params.get("arguments") or {}
            self.calls.append((name, args))
            if name not in self.handlers:
                # Mirrors the real server: business failure, isError false.
                return ok({
                    "content": [{"type": "text", "text": f"Tool not found: {name}"}],
                    "isError": False,
                    "structuredContent": {"status": "failure", "data": {"message": f"Tool not found: {name}"}},
                })
            outcome = self.handlers[name](args)
            if isinstance(outcome, httpx.Response):
                return outcome
            return ok({
                "content": [{"type": "text", "text": json.dumps(outcome)}],
                "isError": False,
                "structuredContent": {"status": "success", "data": outcome},
            })
        return httpx.Response(200, json={
            "jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    # -- assertions ------------------------------------------------------
    def args_for(self, name: str) -> Dict[str, Any]:
        for called, args in self.calls:
            if called == name:
                return args
        return {}

    def called_names(self) -> List[str]:
        return [n for n, _ in self.calls]


@pytest.fixture
def fake_mcp() -> FakeMCP:
    return FakeMCP()


@pytest.fixture
def mcp_env(monkeypatch):
    """MCP transport configured, live writes enabled, no OAuth credentials."""
    monkeypatch.setenv("ZOHO_MCP_URL", MCP_URL)
    monkeypatch.setenv("ZOHO_DESK_DEPARTMENT_ID", "dept123")
    monkeypatch.setenv("ZOHO_CLIQ_CHANNEL", "support")
    monkeypatch.setenv("ZOHO_FROM_ADDRESS", "ops@example.com")
    monkeypatch.setenv("ZOHO_TIMEZONE", "Asia/Kolkata")
    monkeypatch.setenv("ZOHO_DRY_RUN", "false")
    monkeypatch.setenv("ZOHO_CONFIRM_WRITES", "true")
    return monkeypatch
