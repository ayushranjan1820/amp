"""Service-layer behaviour: request shapes, caching and error handling."""
from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from agents.Zoho_workflow_agents.config import get_settings
from agents.Zoho_workflow_agents.services import (
    ZohoCalendarService,
    ZohoCliqService,
    ZohoCRMService,
    ZohoDeskService,
    ZohoMailService,
    strip_html,
)
from agents.Zoho_workflow_agents.zoho_client import ZohoAPIError, ZohoClient


def _client(fake, http) -> ZohoClient:
    return ZohoClient(get_settings(), http=http)


# ------------------------------------------------------------------ mail

def test_strip_html_flattens_markup_and_entities():
    html = "<p>Hi&nbsp;there</p><br><script>bad()</script><div>Line&amp;two</div>"
    text = strip_html(html)
    assert "bad()" not in text
    assert "Hi" in text and "Line&two" in text
    assert "<" not in text


@pytest.mark.asyncio
async def test_mail_account_id_is_fetched_once_and_cached(configured_env, fake_zoho):
    fake_zoho.json("GET", "/api/accounts", {"data": [{"accountId": "acc-9", "primaryEmailAddress": "me@ex.com"}]})
    fake_zoho.json("GET", "/messages/view", {"data": []})
    async with fake_zoho.client() as http:
        mail = ZohoMailService(_client(fake_zoho, http))
        await mail.list_messages()
        await mail.list_messages()
    assert len([u for u in fake_zoho.urls("GET") if u.endswith("/api/accounts")]) == 1


@pytest.mark.asyncio
async def test_mail_uses_primary_address_from_a_list_payload(configured_env, fake_zoho, monkeypatch):
    monkeypatch.delenv("ZOHO_FROM_ADDRESS", raising=False)
    fake_zoho.json(
        "GET",
        "/api/accounts",
        {"data": [{"accountId": "acc-1", "emailAddress": [
            {"mailId": "alias@ex.com", "isPrimary": False},
            {"mailId": "primary@ex.com", "isPrimary": True},
        ]}]},
    )
    async with fake_zoho.client() as http:
        mail = ZohoMailService(_client(fake_zoho, http))
        assert await mail.get_from_address() == "primary@ex.com"


@pytest.mark.asyncio
async def test_send_mail_posts_the_expected_payload(configured_env, fake_zoho):
    fake_zoho.json("GET", "/api/accounts", {"data": [{"accountId": "acc-1"}]})
    fake_zoho.json("POST", "/messages", {"data": {"messageId": "m-1"}})
    async with fake_zoho.client() as http:
        mail = ZohoMailService(_client(fake_zoho, http))
        result = await mail.send_mail(
            to=["a@ex.com", " b@ex.com "], subject="Hi", body="<p>x</p>", cc=["c@ex.com"]
        )
    body = fake_zoho.body_for("POST", "/messages")
    assert body["toAddress"] == "a@ex.com,b@ex.com"
    assert body["ccAddress"] == "c@ex.com"
    assert body["fromAddress"] == "ops@example.com"
    assert body["mailFormat"] == "html"
    assert result["message_id"] == "m-1"


@pytest.mark.asyncio
async def test_send_mail_requires_a_recipient(configured_env, fake_zoho):
    async with fake_zoho.client() as http:
        mail = ZohoMailService(_client(fake_zoho, http))
        with pytest.raises(ZohoAPIError, match="recipient"):
            await mail.send_mail(to=[], subject="x", body="y")


@pytest.mark.asyncio
async def test_get_message_merges_headers_and_body(configured_env, fake_zoho):
    fake_zoho.json("GET", "/api/accounts", {"data": [{"accountId": "acc-1"}]})
    fake_zoho.json(
        "GET",
        "/messages/555/details",
        {"data": {"subject": "Meet?", "fromAddress": "x@ex.com", "folderId": "7", "threadId": "t1"}},
    )
    fake_zoho.json("GET", "/folders/7/messages/555/content", {"data": {"content": "<p>Can we meet?</p>"}})
    async with fake_zoho.client() as http:
        mail = ZohoMailService(_client(fake_zoho, http))
        msg = await mail.get_message("555")
    assert msg["subject"] == "Meet?"
    assert msg["body"] == "Can we meet?"
    assert msg["thread_id"] == "t1"


# -------------------------------------------------------------- calendar

@pytest.mark.asyncio
async def test_create_event_sends_zoho_datetime_in_eventdata(configured_env, fake_zoho):
    fake_zoho.json("POST", "/calendars/cal-uid-1/events", {"events": [{"uid": "ev-1"}]})
    async with fake_zoho.client() as http:
        cal = ZohoCalendarService(_client(fake_zoho, http))
        result = await cal.create_event(
            title="Intro call",
            start=datetime(2026, 9, 18, 15, 0),
            duration_minutes=45,
            attendees=["a@ex.com"],
        )
    url = next(u for u in fake_zoho.urls("POST") if "events" in u)
    payload = json.loads(httpx.URL(url).params["eventdata"])
    assert payload["dateandtime"]["start"] == "20260918T150000Z"
    assert payload["dateandtime"]["end"] == "20260918T154500Z"
    assert payload["dateandtime"]["timezone"] == "Asia/Kolkata"
    assert payload["attendees"] == [{"email": "a@ex.com", "permission": 1}]
    assert result["event_uid"] == "ev-1"


@pytest.mark.asyncio
async def test_calendar_uid_falls_back_to_the_default_calendar(configured_env, fake_zoho, monkeypatch):
    monkeypatch.delenv("ZOHO_CALENDAR_ID", raising=False)
    fake_zoho.json(
        "GET",
        "/api/v1/calendars",
        {"calendars": [{"uid": "other"}, {"uid": "default-cal", "isdefault": True}]},
    )
    async with fake_zoho.client() as http:
        cal = ZohoCalendarService(_client(fake_zoho, http))
        assert await cal.get_calendar_uid() == "default-cal"


@pytest.mark.asyncio
async def test_calendar_with_no_calendars_is_actionable(configured_env, fake_zoho, monkeypatch):
    monkeypatch.delenv("ZOHO_CALENDAR_ID", raising=False)
    fake_zoho.json("GET", "/api/v1/calendars", {"calendars": []})
    async with fake_zoho.client() as http:
        cal = ZohoCalendarService(_client(fake_zoho, http))
        with pytest.raises(ZohoAPIError, match="ZOHO_CALENDAR_ID"):
            await cal.get_calendar_uid()


# ------------------------------------------------------------------- crm

@pytest.mark.asyncio
async def test_create_task_payload_includes_owner_and_links(configured_env, fake_zoho, monkeypatch):
    monkeypatch.setenv("ZOHO_CRM_OWNER_ID", "owner-1")
    fake_zoho.json("POST", "/crm/v6/Tasks", {"data": [{"code": "SUCCESS", "details": {"id": "task-9"}}]})
    async with fake_zoho.client() as http:
        crm = ZohoCRMService(_client(fake_zoho, http))
        result = await crm.create_task(
            subject="Prep",
            due_date=datetime(2026, 9, 18, 15, 0),
            related_contact_id="c-1",
        )
    record = fake_zoho.body_for("POST", "/Tasks")["data"][0]
    assert record["Subject"] == "Prep"
    assert record["Due_Date"] == "2026-09-18"
    assert record["Owner"] == {"id": "owner-1"}
    assert record["Who_Id"] == {"id": "c-1"}
    assert result["task_id"] == "task-9"


@pytest.mark.asyncio
async def test_create_task_surfaces_a_crm_rejection(configured_env, fake_zoho):
    fake_zoho.json(
        "POST", "/crm/v6/Tasks", {"data": [{"code": "MANDATORY_NOT_FOUND", "message": "Subject missing"}]}
    )
    async with fake_zoho.client() as http:
        crm = ZohoCRMService(_client(fake_zoho, http))
        with pytest.raises(ZohoAPIError, match="Subject missing"):
            await crm.create_task(subject="x")


@pytest.mark.asyncio
async def test_contact_search_with_no_hits_returns_empty(configured_env, fake_zoho):
    fake_zoho.json("GET", "/Contacts/search", {"message": "no data"}, status=204)
    async with fake_zoho.client() as http:
        crm = ZohoCRMService(_client(fake_zoho, http))
        assert await crm.search_contacts(email="nobody@ex.com") == []


@pytest.mark.asyncio
async def test_contact_search_requires_a_term(configured_env, fake_zoho):
    async with fake_zoho.client() as http:
        crm = ZohoCRMService(_client(fake_zoho, http))
        with pytest.raises(ZohoAPIError, match="email or name"):
            await crm.search_contacts()


# ------------------------------------------------------------------ desk

def test_normalize_ticket_flattens_the_contact_block():
    ticket = ZohoDeskService.normalize_ticket(
        {
            "id": "t-1",
            "ticketNumber": "1042",
            "subject": "API down",
            "priority": "Urgent",
            "contact": {"firstName": "Asha", "lastName": "Rao", "email": "asha@ex.com", "id": "c-7"},
            "account": {"accountName": "Acme"},
        }
    )
    assert ticket["contact_name"] == "Asha Rao"
    assert ticket["contact_email"] == "asha@ex.com"
    assert ticket["account_name"] == "Acme"
    assert ticket["ticket_number"] == "1042"


@pytest.mark.asyncio
async def test_desk_without_org_id_is_actionable(fake_zoho, monkeypatch):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")
    async with fake_zoho.client() as http:
        desk = ZohoDeskService(_client(fake_zoho, http))
        with pytest.raises(ZohoAPIError, match="ZOHO_ORG_ID"):
            await desk.list_tickets()


@pytest.mark.asyncio
async def test_latest_high_priority_prefers_high_then_urgent(configured_env, fake_zoho):
    def tickets(request):
        priority = httpx.URL(str(request.url)).params.get("priority")
        if priority == "High":
            return httpx.Response(200, json={"data": [{"id": "t-high"}]})
        return httpx.Response(200, json={"data": []})

    fake_zoho.route("GET", "/api/v1/tickets", tickets)
    fake_zoho.json("GET", "/api/v1/tickets/t-high", {"id": "t-high", "priority": "High", "subject": "S"})
    async with fake_zoho.client() as http:
        desk = ZohoDeskService(_client(fake_zoho, http))
        ticket = await desk.get_latest_high_priority_ticket()
    assert ticket["ticket_id"] == "t-high"


@pytest.mark.asyncio
async def test_send_reply_posts_html_to_send_reply(configured_env, fake_zoho):
    fake_zoho.json("POST", "/tickets/t-1/sendReply", {"id": "th-1"})
    async with fake_zoho.client() as http:
        desk = ZohoDeskService(_client(fake_zoho, http))
        result = await desk.send_reply(ticket_id="t-1", content="<p>ack</p>", to_address="a@ex.com")
    body = fake_zoho.body_for("POST", "sendReply")
    assert body["channel"] == "EMAIL"
    assert body["to"] == "a@ex.com"
    assert body["contentType"] == "html"
    assert result["thread_id"] == "th-1"


# ------------------------------------------------------------------ cliq

@pytest.mark.asyncio
async def test_cliq_posts_by_channel_name_with_oauth(configured_env, fake_zoho):
    fake_zoho.json("POST", "/channelsbyname/support/message", {"id": "msg-1"})
    async with fake_zoho.client() as http:
        cliq = ZohoCliqService(_client(fake_zoho, http))
        result = await cliq.post_message(text="hello", card_title="Alert")
    assert result["transport"] == "api"
    assert result["channel"] == "support"
    assert fake_zoho.body_for("POST", "channelsbyname")["card"]["title"] == "Alert"


@pytest.mark.asyncio
async def test_cliq_without_a_destination_is_actionable(configured_env, fake_zoho, monkeypatch):
    monkeypatch.delenv("ZOHO_CLIQ_CHANNEL", raising=False)
    async with fake_zoho.client() as http:
        cliq = ZohoCliqService(_client(fake_zoho, http))
        with pytest.raises(ZohoAPIError, match="ZOHO_CLIQ_CHANNEL"):
            await cliq.post_message(text="hello")
