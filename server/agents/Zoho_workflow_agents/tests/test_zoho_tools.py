"""The Zoho built-in tools exposed to Agent Builder / custom agents."""
from __future__ import annotations

import pytest

from tool_registry import BUILTIN_TOOLS

ZOHO_TOOL_IDS = [
    "tool_zoho_mail",
    "tool_zoho_calendar",
    "tool_zoho_crm",
    "tool_zoho_desk",
    "tool_zoho_cliq",
]


def _tool(tool_id: str) -> dict:
    return next(t for t in BUILTIN_TOOLS if t["id"] == tool_id)


@pytest.mark.parametrize("tool_id", ZOHO_TOOL_IDS)
def test_every_zoho_tool_is_registered_and_well_formed(tool_id):
    tool = _tool(tool_id)
    schema = tool["schema_config"]
    assert schema["category"] == "integrations"
    assert schema["input"]["required"] == ["action"]
    assert schema["input"]["properties"]["action"]["enum"]
    for key in ("ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC"):
        assert key in schema["env_keys"], f"{tool_id} is missing {key}"
    assert tool["implementation"]["type"] == tool_id.replace("tool_", "")


def test_desk_tool_declares_the_org_id_it_cannot_work_without():
    assert "ZOHO_ORG_ID" in _tool("tool_zoho_desk")["schema_config"]["env_keys"]


# ---------------------------------------------------------------- executor

@pytest.mark.asyncio
async def test_tool_reports_missing_credentials(monkeypatch):
    from dynamic_agent_runtime import _execute_zoho_tool

    out = await _execute_zoho_tool("crm", {"action": "latest_contact"})
    assert out.startswith("Error: Zoho is not connected")
    assert "ZOHO_CLIENT_ID" in out


@pytest.mark.asyncio
async def test_tool_requires_an_action(monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")
    from dynamic_agent_runtime import _execute_zoho_tool

    assert "'action' is required" in await _execute_zoho_tool("mail", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "product,payload",
    [
        ("mail", {"action": "send", "to": ["a@x.com"], "subject": "s", "body": "b"}),
        ("calendar", {"action": "create_event", "title": "t", "start": "2026-09-18T15:00:00"}),
        ("crm", {"action": "create_task", "subject": "s"}),
        ("desk", {"action": "reply", "ticket_id": "1", "content": "c"}),
        ("cliq", {"action": "post", "text": "hi"}),
    ],
)
async def test_writes_are_blocked_while_dry_run_is_on(monkeypatch, product, payload):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")
    from dynamic_agent_runtime import _execute_zoho_tool

    out = await _execute_zoho_tool(product, payload)
    assert out.startswith("[dry run]")
    assert "ZOHO_CONFIRM_WRITES=true" in out


@pytest.mark.asyncio
async def test_unknown_action_is_named_rather_than_silently_ignored(configured_env, fake_zoho, monkeypatch):
    import dynamic_agent_runtime
    from agents.Zoho_workflow_agents import zoho_client as zc

    http = fake_zoho.client()
    real_init = zc.ZohoClient.__init__

    def patched_init(self, settings=None, *, http=http, timeout=30.0):
        real_init(self, settings, http=http, timeout=timeout)

    monkeypatch.setattr(zc.ZohoClient, "__init__", patched_init)
    out = await dynamic_agent_runtime._execute_zoho_tool("cliq", {"action": "explode"})
    assert out == "Unknown Zoho Cliq action: explode"
    await http.aclose()


@pytest.mark.asyncio
async def test_calendar_create_event_rejects_an_unparseable_start(configured_env, fake_zoho, monkeypatch):
    import dynamic_agent_runtime
    from agents.Zoho_workflow_agents import zoho_client as zc

    http = fake_zoho.client()
    real_init = zc.ZohoClient.__init__

    def patched_init(self, settings=None, *, http=http, timeout=30.0):
        real_init(self, settings, http=http, timeout=timeout)

    monkeypatch.setattr(zc.ZohoClient, "__init__", patched_init)
    out = await dynamic_agent_runtime._execute_zoho_tool(
        "calendar", {"action": "create_event", "title": "t", "start": "whenever"}
    )
    assert "must be a parseable date/time" in out
    await http.aclose()


@pytest.mark.asyncio
async def test_crm_task_creation_executes_when_writes_are_confirmed(configured_env, fake_zoho, monkeypatch):
    import dynamic_agent_runtime
    from agents.Zoho_workflow_agents import zoho_client as zc

    fake_zoho.json("POST", "/crm/v6/Tasks", {"data": [{"code": "SUCCESS", "details": {"id": "task-77"}}]})
    http = fake_zoho.client()
    real_init = zc.ZohoClient.__init__

    def patched_init(self, settings=None, *, http=http, timeout=30.0):
        real_init(self, settings, http=http, timeout=timeout)

    monkeypatch.setattr(zc.ZohoClient, "__init__", patched_init)
    out = await dynamic_agent_runtime._execute_zoho_tool(
        "crm", {"action": "create_task", "subject": "Call back", "due_date": "2026-09-20"}
    )
    assert "task-77" in out
    assert fake_zoho.body_for("POST", "/Tasks")["data"][0]["Due_Date"] == "2026-09-20"
    await http.aclose()
