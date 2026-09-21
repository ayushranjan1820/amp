import httpx
import pytest

from agents.WebMCP_agent.tools.bridge_client import WebMcpBridgeClient, WebMcpBridgeError, host_allowed


def test_host_allowed_empty_list_allows_when_not_required():
    assert host_allowed("https://example.com/x", None, require_allowlist=False) is True
    assert host_allowed("https://example.com/x", [], require_allowlist=False) is True


def test_host_allowed_required_empty_is_error():
    msg = host_allowed("https://example.com/x", [], require_allowlist=True)
    assert msg is not True


def test_host_allowed_explicit():
    assert host_allowed("https://foo.com/a", ["foo.com"], require_allowlist=False) is True
    assert host_allowed("https://evil.com/", ["foo.com"], require_allowlist=False) != True


def test_host_allowed_wildcard_subdomain():
    assert host_allowed("https://app.foo.com/", ["*.foo.com"], require_allowlist=False) is True
    assert host_allowed("https://foo.com/", ["*.foo.com"], require_allowlist=False) is True


def test_list_tools_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tools":
            return httpx.Response(200, json={"tools": [{"name": "demo.echo", "description": "x"}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, headers={"Authorization": "Bearer tok"})
    client = WebMcpBridgeClient("http://127.0.0.1:9", "tok", client=inner)
    tools = client.list_tools()
    assert len(tools) == 1
    assert tools[0]["name"] == "demo.echo"


def test_call_tool_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tools/call" and request.method == "POST":
            return httpx.Response(200, json={"result": {"ok": True}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, headers={"Authorization": "Bearer tok"})
    client = WebMcpBridgeClient("http://127.0.0.1:9", "tok", client=inner)
    assert client.call_tool("demo.echo", {"message": "hi"}) == {"ok": True}


def test_bridge_error_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "no extension"})

    transport = httpx.MockTransport(handler)
    inner = httpx.Client(transport=transport, headers={"Authorization": "Bearer tok"})
    client = WebMcpBridgeClient("http://127.0.0.1:9", "tok", client=inner)
    with pytest.raises(WebMcpBridgeError):
        client.list_tools()
