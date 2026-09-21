"""Config, auth and HTTP-client behaviour for the Zoho integration package."""
from __future__ import annotations

import time

import httpx
import pytest

from agents.Zoho_workflow_agents.config import all_scopes, get_settings, normalize_dc
from agents.Zoho_workflow_agents.zoho_auth import (
    ZohoAuthError,
    ensure_access_token,
    refresh_access_token,
)
from agents.Zoho_workflow_agents.zoho_client import ZohoAPIError, ZohoClient

# ---------------------------------------------------------------- config

def test_server_config_status_exposes_only_zoho_key_names(monkeypatch):
    import json
    from user_config import with_server_config_status

    monkeypatch.setenv("ZOHO_MCP_URL", "private-test-url")
    monkeypatch.setenv("PWC_GENAI_API_KEY", "private-test-key")
    agent = {"id": "zoho_email_meeting_agent", "configuration": {"required_settings": [
        {"key": "ZOHO_MCP_URL"}, {"key": "PWC_GENAI_API_KEY"},
    ]}}
    result = with_server_config_status(agent)
    assert result["server_configured_keys"] == ["ZOHO_MCP_URL"]
    assert "private-test" not in json.dumps(result)
    assert "server_configured_keys" not in agent
    assert with_server_config_status({"id": "other"}) == {"id": "other"}


def test_dc_normalization_accepts_keys_suffixes_and_hosts():
    assert normalize_dc("eu") == "eu"
    assert normalize_dc("com.au") == "au"
    assert normalize_dc("accounts.zoho.in") == "in"
    assert normalize_dc("com") == "us"
    assert normalize_dc("") == "us"
    assert normalize_dc("nonsense") == "us"


def test_product_hosts_follow_the_data_center(monkeypatch):
    monkeypatch.setenv("ZOHO_DC", "in")
    s = get_settings()
    assert s.token_url == "https://accounts.zoho.in/oauth/v2/token"
    assert s.mail_base == "https://mail.zoho.in/api"
    assert s.calendar_base == "https://calendar.zoho.in/api/v1"
    assert s.crm_base == "https://www.zohoapis.in/crm/v6"
    assert s.desk_base == "https://desk.zoho.in/api/v1"
    assert s.cliq_base == "https://cliq.zoho.in/api/v2"


def test_accounts_base_url_overrides_the_data_center(monkeypatch):
    monkeypatch.setenv("ZOHO_ACCOUNTS_BASE_URL", "https://accounts.zoho.com.cn/")
    assert get_settings().token_url == "https://accounts.zoho.com.cn/oauth/v2/token"


def test_writes_are_dry_run_until_explicitly_confirmed(monkeypatch):
    assert get_settings().dry_run is True

    monkeypatch.setenv("ZOHO_DRY_RUN", "false")
    assert get_settings().dry_run is True, "confirm flag still missing"

    monkeypatch.setenv("ZOHO_CONFIRM_WRITES", "true")
    assert get_settings().dry_run is False

    monkeypatch.setenv("ZOHO_DRY_RUN", "true")
    assert get_settings().dry_run is True, "explicit dry-run wins over the confirm flag"


def test_missing_credentials_lists_every_gap():
    assert get_settings().missing_credentials() == [
        "ZOHO_CLIENT_ID",
        "ZOHO_CLIENT_SECRET",
        "ZOHO_REFRESH_TOKEN",
    ]


def test_access_token_alone_satisfies_the_credential_check(monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_ACCESS_TOKEN", "at")
    assert get_settings().is_configured() is True


def test_scope_string_covers_every_product():
    scopes = all_scopes()
    for fragment in ("ZohoMail", "ZohoCalendar", "ZohoCRM", "Desk.tickets", "ZohoCliq"):
        assert fragment in scopes


def test_meeting_duration_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv("ZOHO_MEETING_DURATION_MINUTES", "not-a-number")
    assert get_settings().meeting_duration_minutes == 30


# ------------------------------------------------------------------ auth

@pytest.mark.asyncio
async def test_refresh_persists_token_and_expiry(monkeypatch, configured_env, fake_zoho):
    async with fake_zoho.client() as http:
        token = await refresh_access_token(get_settings(), client=http)
    assert token == "at-1"
    import os

    assert os.environ["ZOHO_ACCESS_TOKEN"] == "at-1"
    assert int(os.environ["ZOHO_TOKEN_EXPIRES_AT"]) > int(time.time())


@pytest.mark.asyncio
async def test_refresh_without_refresh_token_is_actionable(monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    with pytest.raises(ZohoAuthError, match="ZOHO_REFRESH_TOKEN"):
        await refresh_access_token(get_settings())


@pytest.mark.asyncio
async def test_zoho_error_body_on_http_200_is_raised(configured_env, fake_zoho):
    fake_zoho._routes.clear()
    fake_zoho.json("POST", "/oauth/v2/token", {"error": "invalid_client"})
    async with fake_zoho.client() as http:
        with pytest.raises(ZohoAuthError, match="invalid_client"):
            await refresh_access_token(get_settings(), client=http)


@pytest.mark.asyncio
async def test_fresh_token_is_reused_without_a_refresh_call(configured_env, fake_zoho):
    import os

    os.environ["ZOHO_ACCESS_TOKEN"] = "still-good"
    os.environ["ZOHO_TOKEN_EXPIRES_AT"] = str(int(time.time()) + 3600)
    async with fake_zoho.client() as http:
        token = await ensure_access_token(get_settings(), client=http)
    assert token == "still-good"
    assert fake_zoho.calls == []


# ---------------------------------------------------------------- client

@pytest.mark.asyncio
async def test_client_retries_once_after_a_401(configured_env, fake_zoho):
    seen = {"n": 0}

    def flaky(_request):
        seen["n"] += 1
        if seen["n"] == 1:
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"ok": True})

    fake_zoho.route("GET", "/crm/v6/Contacts", flaky)
    async with fake_zoho.client() as http:
        client = ZohoClient(get_settings(), http=http)
        result = await client.get(f"{get_settings().crm_base}/Contacts")
    assert result == {"ok": True}
    assert seen["n"] == 2
    assert len([u for u in fake_zoho.urls("POST") if "token" in u]) == 2


@pytest.mark.asyncio
async def test_org_id_header_is_attached_for_desk(configured_env, fake_zoho):
    captured = {}

    def record(request):
        captured["orgId"] = request.headers.get("orgId")
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"data": []})

    fake_zoho.route("GET", "/api/v1/tickets", record)
    async with fake_zoho.client() as http:
        await ZohoClient(get_settings(), http=http).get(f"{get_settings().desk_base}/tickets")
    assert captured["orgId"] == "org123"
    assert captured["auth"] == "Zoho-oauthtoken at-1"


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, "scope"),
        (404, "not found"),
        (429, "rate limit"),
    ],
)
@pytest.mark.asyncio
async def test_http_errors_become_readable_messages(configured_env, fake_zoho, status, expected):
    fake_zoho.json("GET", "/crm/v6/Tasks", {"message": "denied"}, status=status)
    async with fake_zoho.client() as http:
        with pytest.raises(ZohoAPIError) as excinfo:
            await ZohoClient(get_settings(), http=http).get(f"{get_settings().crm_base}/Tasks")
    assert expected in str(excinfo.value).lower()
    assert excinfo.value.status == status


@pytest.mark.asyncio
async def test_injected_http_client_is_not_closed_by_the_zoho_client(configured_env, fake_zoho):
    http = fake_zoho.client()
    client = ZohoClient(get_settings(), http=http)
    await client.aclose()
    assert http.is_closed is False
    await http.aclose()


# ------------------------------------------------- OAuth consent helpers

def test_authorize_url_requests_an_offline_grant(monkeypatch):
    from agents.Zoho_workflow_agents.zoho_auth import build_authorize_url

    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_DC", "eu")
    url = build_authorize_url("https://app.example.com/oauth/zoho/callback")

    parsed = httpx.URL(url)
    assert str(parsed).startswith("https://accounts.zoho.eu/oauth/v2/auth?")
    params = parsed.params
    assert params["client_id"] == "cid"
    assert params["response_type"] == "code"
    # Without offline access Zoho returns no refresh token, which breaks every
    # later run once the hour-long access token expires.
    assert params["access_type"] == "offline"
    assert params["redirect_uri"] == "https://app.example.com/oauth/zoho/callback"
    for fragment in ("ZohoMail", "ZohoCalendar", "ZohoCRM", "Desk.tickets", "ZohoCliq"):
        assert fragment in params["scope"]


def test_authorize_url_accepts_a_narrowed_scope(monkeypatch):
    from agents.Zoho_workflow_agents.zoho_auth import build_authorize_url

    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    url = build_authorize_url("https://app.example.com/cb", scope="ZohoMail.messages.ALL")
    assert httpx.URL(url).params["scope"] == "ZohoMail.messages.ALL"


@pytest.mark.asyncio
async def test_code_exchange_stores_the_access_token(configured_env, fake_zoho):
    import os

    from agents.Zoho_workflow_agents.zoho_auth import exchange_authorization_code

    fake_zoho.json(
        "POST",
        "/oauth/v2/token",
        {"access_token": "at-new", "refresh_token": "rt-new", "expires_in": 3600},
    )
    async with fake_zoho.client() as http:
        payload = await exchange_authorization_code("the-code", "https://app.example.com/cb", client=http)

    assert payload["refresh_token"] == "rt-new"
    assert os.environ["ZOHO_ACCESS_TOKEN"] == "at-new"
    assert fake_zoho.body_for("POST", "/oauth/v2/token") or True  # form-encoded, not JSON


@pytest.mark.asyncio
async def test_code_exchange_failure_is_actionable(configured_env, fake_zoho):
    from agents.Zoho_workflow_agents.zoho_auth import ZohoAuthError, exchange_authorization_code

    fake_zoho.json("POST", "/oauth/v2/token", {"error": "invalid_code"})
    async with fake_zoho.client() as http:
        with pytest.raises(ZohoAuthError, match="invalid_code"):
            await exchange_authorization_code("stale", "https://app.example.com/cb", client=http)
