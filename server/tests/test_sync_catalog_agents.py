"""Merge behaviour of sync_catalog_agents: additive, never destructive."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.sync_catalog_agents import _merge

SERVER_DIR = Path(__file__).resolve().parents[1]
ZOHO_AGENT_IDS = [
    "zoho_email_meeting_agent",
    "zoho_support_ticket_agent",
    "zoho_new_customer_agent",
]


def _source():
    return {
        "metadata": {"version": "1.0.0", "total_agents": 2},
        "categories": [
            {"id": "general", "name": "General"},
            {"id": "business_integrations", "name": "Business Integrations"},
        ],
        "agents": [
            {"id": "keeper", "name": "Keeper", "category": "general"},
            {"id": "zoho_new", "name": "Zoho New", "category": "business_integrations"},
        ],
    }


def _target():
    return {
        "metadata": {"version": "1.0.0", "total_agents": 2},
        "categories": [{"id": "general", "name": "General"}],
        "agents": [
            {"id": "keeper", "name": "Keeper (edited in admin UI)", "category": "general"},
            {"id": "db_only", "name": "Added straight to the database", "category": "general"},
        ],
    }


def test_named_agent_is_added_without_touching_the_others():
    merged = _merge(_target(), _source(), ["zoho_new"])
    by_id = {a["id"]: a for a in merged["agents"]}
    assert set(by_id) == {"keeper", "db_only", "zoho_new"}
    # An agent that exists only in the database survives the merge.
    assert by_id["db_only"]["name"] == "Added straight to the database"
    # An agent not named in the sync keeps its database edits.
    assert by_id["keeper"]["name"] == "Keeper (edited in admin UI)"


def test_a_named_agent_that_already_exists_is_replaced_from_source():
    merged = _merge(_target(), _source(), ["keeper"])
    by_id = {a["id"]: a for a in merged["agents"]}
    assert by_id["keeper"]["name"] == "Keeper"
    assert len(merged["agents"]) == 2, "replacing must not duplicate the record"


def test_the_category_an_agent_needs_comes_along():
    merged = _merge(_target(), _source(), ["zoho_new"])
    assert [c["id"] for c in merged["categories"]] == ["general", "business_integrations"]


def test_an_existing_category_is_not_duplicated():
    merged = _merge(_target(), _source(), ["keeper"])
    assert [c["id"] for c in merged["categories"]] == ["general"]


def test_no_ids_syncs_everything_in_the_source():
    merged = _merge(_target(), _source(), [])
    assert {a["id"] for a in merged["agents"]} == {"keeper", "db_only", "zoho_new"}


def test_an_unknown_agent_id_stops_the_run():
    with pytest.raises(SystemExit, match="nope"):
        _merge(_target(), _source(), ["nope"])


def test_the_shipped_catalog_carries_the_three_zoho_agents():
    """The JSON that seeds MongoDB must actually contain what we tell operators to sync."""
    catalog = json.loads((SERVER_DIR / "agents_catalog.json").read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in catalog["agents"]}
    category_ids = {c["id"] for c in catalog["categories"]}

    for agent_id in ZOHO_AGENT_IDS:
        agent = by_id.get(agent_id)
        assert agent is not None, f"{agent_id} is missing from agents_catalog.json"
        assert agent["category"] in category_ids, f"{agent_id} points at an undefined category"
        assert agent["dispatch"]["getter_key"] == agent_id
        assert agent["usage"]["api_endpoint"].startswith("POST /api/zoho-")

        required = {s["key"] for s in agent["configuration"]["required_settings"]}
        optional = {s["key"] for s in agent["configuration"]["optional_settings"]}
        # The MCP connection is the primary transport: its URL is the only Zoho
        # credential required, because the connection itself is pre-authorized.
        assert "ZOHO_MCP_URL" in required
        assert required.isdisjoint({"ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN"})
        # The REST transport stays available, so its keys are offered as optional.
        assert {"ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_BACKEND"} <= optional
        assert {"ZOHO_DRY_RUN", "ZOHO_CONFIRM_WRITES"} <= optional

    assert catalog["metadata"]["total_agents"] == len(catalog["agents"])


def test_zoho_catalog_uses_crm_free_tools_and_actionable_samples():
    catalog = json.loads((SERVER_DIR / "agents_catalog.json").read_text(encoding="utf-8"))
    by_id = {agent["id"]: agent for agent in catalog["agents"]}
    for agent_id in ZOHO_AGENT_IDS:
        agent = by_id[agent_id]
        assert "crm" not in json.dumps(agent).lower()
        settings = agent["configuration"]["required_settings"] + agent["configuration"]["optional_settings"]
        by_key = {setting["key"]: setting for setting in settings}
        assert "visible_when" not in by_key["ZOHO_DRY_RUN"]
        assert "visible_when" not in by_key["ZOHO_CONFIRM_WRITES"]
        prompts = agent["usage"]["example_prompts"]
        assert len(prompts) == 3
        if agent_id == "zoho_support_ticket_agent":
            assert "<your real Desk ticket ID>" in prompts[0]
            assert "private Desk escalation note" in prompts[0]
        else:
            assert "example.com" in prompts[0]
        if agent_id in {"zoho_support_ticket_agent", "zoho_new_customer_agent"}:
            assert "cliq" not in json.dumps(agent).lower()
            assert any(tool["name"] == "zoho_desk" for tool in agent["tools"])
            assert "visible_when" not in by_key["ZOHO_DESK_DEPARTMENT_ID"]
        assert "1234567890" not in " ".join(prompts)
        if agent_id != "zoho_new_customer_agent":
            assert {"ZOHO_PROJECTS_PORTAL_ID", "ZOHO_PROJECTS_PROJECT_ID"} <= by_key.keys()
            assert any(tool["name"] == "zoho_projects" for tool in agent["tools"])


def test_every_catalog_endpoint_and_getter_is_wired_in_the_api():
    """A catalog entry nobody can call is worse than no entry at all."""
    api_source = (SERVER_DIR / "api.py").read_text(encoding="utf-8")
    catalog = json.loads((SERVER_DIR / "agents_catalog.json").read_text(encoding="utf-8"))
    by_id = {a["id"]: a for a in catalog["agents"]}

    for agent_id in ZOHO_AGENT_IDS:
        agent = by_id[agent_id]
        path = agent["usage"]["api_endpoint"].removeprefix("POST ")
        assert f'@app.post("{path}")' in api_source, f"{path} has no route in api.py"
        # AGENT_API_PATHS is written with single quotes; accept either style.
        mapping = {
            f'"{path}": "{agent["name"]}"',
            f"'{path}': '{agent['name']}'",
        }
        assert any(m in api_source for m in mapping), f"{path} missing from AGENT_API_PATHS"
        assert f'name == "{agent_id}"' in api_source, f"{agent_id} missing from _get_agent"
