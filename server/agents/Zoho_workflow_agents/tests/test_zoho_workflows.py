"""End-to-end behaviour of the three Zoho workflow agents, with stubbed HTTP + LLM."""
from __future__ import annotations

import json
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx
import pytest

from agents.Zoho_workflow_agents.base_workflow import (
    extract_emails,
    next_business_hour,
    parse_datetime_hint,
)
from agents.Zoho_workflow_agents.email_meeting_agent import ZohoEmailMeetingAgent
from agents.Zoho_workflow_agents.new_customer_agent import ZohoNewCustomerAgent
from agents.Zoho_workflow_agents.support_ticket_agent import ZohoSupportTicketAgent


class StubAI:
    """Stands in for BaseAIService: returns canned JSON, records prompts."""

    def __init__(self, payload: Any, *, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.prompts: List[str] = []

    def call_genai(self, prompt: str, *_a, **_kw) -> str:
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("LLM service not configured")
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload)


def _future(hour: int = 15) -> datetime:
    base = datetime.now() + timedelta(days=3)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


# ------------------------------------------------------------- helpers

def test_extract_emails_dedupes_and_keeps_order():
    text = "ping a@x.com and b@y.com, then a@x.com again"
    assert extract_emails(text) == ["a@x.com", "b@y.com"]


@pytest.mark.parametrize(
    "value",
    ["2026-09-18T15:00:00", "2026-09-18 15:00", "18/09/2026 15:00"],
)
def test_parse_datetime_hint_accepts_common_shapes(value):
    parsed = parse_datetime_hint(value)
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day, parsed.hour) == (2026, 9, 18, 15)


def test_parse_datetime_hint_handles_relative_words():
    parsed = parse_datetime_hint("tomorrow at 3pm")
    assert parsed is not None
    assert parsed.hour == 15
    assert parsed.date() == (datetime.now() + timedelta(days=1)).date()


def test_parse_datetime_hint_returns_none_when_absent():
    assert parse_datetime_hint("") is None
    assert parse_datetime_hint("sometime soon-ish") is None


def test_next_business_hour_never_lands_on_a_weekend():
    slot = next_business_hour()
    assert slot.weekday() < 5
    assert slot.hour == 10


# --------------------------------------------------- credential gating

@pytest.mark.asyncio
async def test_unconfigured_agent_explains_what_is_missing(fake_zoho):
    agent = ZohoEmailMeetingAgent(ai_service=StubAI({}), http=fake_zoho.client())
    result = await agent.process_query("Book a meeting with a@x.com")
    assert result["success"] is False
    assert "ZOHO_CLIENT_ID" in result["response"]
    assert "ZOHO_REFRESH_TOKEN" in result["response"]
    assert fake_zoho.calls == [], "no Zoho call should be attempted without credentials"


# ------------------------------------------------- workflow 1: meeting

@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "Process my latest meeting email and book it.",
    "Read my last meeting email.",
    "Process the newest meeting email.",
])
async def test_meeting_command_reads_mailbox(query):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    message = {"subject": "Controlled test", "from": "test@example.com"}
    mail = SimpleNamespace(get_latest_message=AsyncMock(return_value=message))
    agent = ZohoEmailMeetingAgent(ai_service=StubAI({}))
    result = await agent._resolve_email(query, SimpleNamespace(mail=mail), lambda *args, **kwargs: None)
    assert result == message
    mail.get_latest_message.assert_awaited_once_with(search="")


MEETING_EMAIL = """From: Priya Sharma <priya@acme.com>
Subject: Can we meet about the data migration?

Hi team, could we get 45 minutes next week to walk through the migration plan?
Priya
"""


def _meeting_intent(**over) -> Dict[str, Any]:
    payload = {
        "is_meeting_request": True,
        "requester_name": "Priya",
        "requester_email": "priya@acme.com",
        "additional_attendees": [],
        "title": "Data migration walkthrough",
        "purpose": "walk through the migration plan",
        "proposed_datetime": _future().isoformat(timespec="minutes"),
        "duration_minutes": 45,
        "location": "",
        "follow_up_task": "Prepare the migration plan deck",
    }
    payload.update(over)
    return payload


def _mail_and_calendar_routes(fake_zoho):
    fake_zoho.json("GET", "/api/accounts", {"data": [{"accountId": "acc-1"}]})
    fake_zoho.json("POST", "/api/accounts/acc-1/messages", {"data": {"messageId": "m-1"}})
    fake_zoho.json("POST", "/calendars/cal-uid-1/events", {"events": [{"uid": "ev-1"}]})
    fake_zoho.json("GET", "/Contacts/search", {"data": [{"id": "c-1", "Full_Name": "Priya Sharma"}]})
    fake_zoho.json("POST", "/projects/456/tasks/", {"tasks": [{"id": "task-1"}]})


@pytest.mark.asyncio
async def test_meeting_workflow_dry_run_writes_nothing(monkeypatch, fake_zoho):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    _mail_and_calendar_routes(fake_zoho)

    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_zoho.client())
    result = await agent.process_query(MEETING_EMAIL)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert [a["label"] for a in result["actions"]] == [
        "Create Zoho Calendar event",
        "Send confirmation email",
        "Create Projects follow-up task",
    ]
    assert all(a["executed"] is False for a in result["actions"])
    assert all(a["skipped_reason"] == "dry_run" for a in result["actions"])
    assert fake_zoho.writes() == [], "dry run must not POST to Zoho"
    assert "Dry run" in result["response"]


@pytest.mark.asyncio
async def test_meeting_workflow_executes_all_three_writes(configured_env, fake_zoho):
    configured_env.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    _mail_and_calendar_routes(fake_zoho)

    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_zoho.client())
    result = await agent.process_query(MEETING_EMAIL)

    assert result["success"] is True
    assert result["dry_run"] is False
    assert all(a["executed"] for a in result["actions"])

    event = json.loads(httpx.URL(next(u for u in fake_zoho.urls("POST") if "events" in u)).params["eventdata"])
    assert event["title"] == "Data migration walkthrough"
    assert event["attendees"] == [{"email": "priya@acme.com", "permission": 1}]
    # 45-minute duration from the extracted intent, not the 30-minute default.
    start = datetime.strptime(event["dateandtime"]["start"], "%Y%m%dT%H%M%SZ")
    end = datetime.strptime(event["dateandtime"]["end"], "%Y%m%dT%H%M%SZ")
    assert (end - start) == timedelta(minutes=45)

    mail = fake_zoho.body_for("POST", "/messages")
    assert mail["toAddress"] == "priya@acme.com"
    assert "Confirmed:" in mail["subject"]
    assert "Location or joining details not specified." in mail["content"]
    assert "attached" not in mail["content"]

    task = parse_qs(fake_zoho.body_for("POST", "/tasks/")["_raw"])
    assert task["name"] == ["Prepare the migration plan deck"]
    assert not any("/crm/" in url for url in fake_zoho.urls())


@pytest.mark.asyncio
async def test_meeting_workflow_skips_non_meeting_email(configured_env, fake_zoho):
    _mail_and_calendar_routes(fake_zoho)
    agent = ZohoEmailMeetingAgent(
        ai_service=StubAI(_meeting_intent(is_meeting_request=False)), http=fake_zoho.client()
    )
    result = await agent.process_query("Just sharing the quarterly numbers, no action needed.")
    assert result["success"] is True
    assert result["actions"] == []
    assert fake_zoho.writes() == []


@pytest.mark.asyncio
async def test_meeting_workflow_defaults_the_slot_when_no_time_is_given(configured_env, fake_zoho):
    configured_env.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    _mail_and_calendar_routes(fake_zoho)
    agent = ZohoEmailMeetingAgent(
        ai_service=StubAI(_meeting_intent(proposed_datetime="")), http=fake_zoho.client()
    )
    result = await agent.process_query(MEETING_EMAIL)
    assert result["success"] is True
    event = json.loads(httpx.URL(next(u for u in fake_zoho.urls("POST") if "events" in u)).params["eventdata"])
    start = datetime.strptime(event["dateandtime"]["start"], "%Y%m%dT%H%M%SZ")
    assert start > datetime.now()
    assert start.weekday() < 5
    assert any("no specific time" in s["content"] for s in result["thinking_steps"])


@pytest.mark.asyncio
async def test_meeting_workflow_falls_back_when_the_llm_is_down(configured_env, fake_zoho):
    configured_env.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    _mail_and_calendar_routes(fake_zoho)
    agent = ZohoEmailMeetingAgent(ai_service=StubAI({}, fail=True), http=fake_zoho.client())
    result = await agent.process_query(MEETING_EMAIL)
    # Rule-based extraction still finds the sender and creates all three records.
    assert result["success"] is True
    assert all(a["executed"] for a in result["actions"])
    assert fake_zoho.body_for("POST", "/messages")["toAddress"] == "priya@acme.com"


@pytest.mark.asyncio
async def test_meeting_workflow_needs_something_to_work_from(configured_env, fake_zoho):
    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_zoho.client())
    result = await agent.process_query("do it")
    assert result["success"] is False
    assert "paste the meeting-request email" in result["response"].lower()


@pytest.mark.asyncio
async def test_meeting_workflow_reads_the_mailbox_on_request(configured_env, fake_zoho):
    configured_env.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    _mail_and_calendar_routes(fake_zoho)
    fake_zoho.json(
        "GET",
        "/messages/view",
        {"data": [{"messageId": "777", "folderId": "2"}]},
    )
    fake_zoho.json(
        "GET",
        "/messages/777/details",
        {"data": {"subject": "Meet?", "fromAddress": "priya@acme.com", "folderId": "2"}},
    )
    fake_zoho.json("GET", "/folders/2/messages/777/content", {"data": {"content": "<p>Can we meet?</p>"}})

    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_zoho.client())
    result = await agent.process_query("Process my latest email and book the meeting")
    assert result["success"] is True
    assert result["data"]["email"]["message_id"] == "777"


@pytest.mark.asyncio
async def test_meeting_workflow_reports_a_failed_write_without_aborting(configured_env, fake_zoho):
    configured_env.setenv("ZOHO_CALENDAR_ID", "cal-uid-1")
    _mail_and_calendar_routes(fake_zoho)
    fake_zoho.json("POST", "/calendars/cal-uid-1/events", {"message": "scope missing"}, status=403)

    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_zoho.client())
    result = await agent.process_query(MEETING_EMAIL)

    calendar_action = result["actions"][0]
    assert calendar_action["executed"] is False
    assert "scope" in calendar_action["error"].lower()
    # The confirmation email and CRM task still run.
    assert result["actions"][1]["executed"] is True
    assert result["actions"][2]["executed"] is True


# -------------------------------------------- workflow 2: support desk

def _triage(**over) -> Dict[str, Any]:
    payload = {
        "severity_summary": "Checkout API returning 500s for all customers",
        "customer_impact": "Customers cannot complete purchases",
        "suggested_owner_action": "Page the platform on-call engineer",
        "acknowledgement_message": "Hi Asha, we are on it and will update you within 2 hours.",
        "sla_hours": 2,
    }
    payload.update(over)
    return payload


def _desk_routes(fake_zoho, priority: str = "Urgent"):
    fake_zoho.json(
        "GET",
        "/api/v1/tickets/10420001",
        {
            "id": "10420001",
            "ticketNumber": "1042",
            "subject": "Checkout API failing",
            "description": "All checkout calls return HTTP 500 since 09:00.",
            "priority": priority,
            "status": "Open",
            "webUrl": "https://desk.zoho.com/t/1042",
            "contact": {"firstName": "Asha", "lastName": "Rao", "email": "asha@acme.com", "id": "c-7"},
            "account": {"accountName": "Acme"},
        },
    )
    fake_zoho.json("POST", "/api/v1/tickets/10420001/comments", {"id": "comment-1"})
    fake_zoho.json("GET", "/Contacts/search", {"data": [{"id": "c-7", "Full_Name": "Asha Rao"}]})
    fake_zoho.json("POST", "/projects/456/tasks/", {"tasks": [{"id": "task-2"}]})
    fake_zoho.json("POST", "/api/v1/tickets/10420001/sendReply", {"id": "th-1"})


@pytest.mark.asyncio
async def test_support_workflow_executes_alert_task_and_reply(configured_env, fake_zoho):
    _desk_routes(fake_zoho)
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("Triage ticket id 10420001 please")

    assert result["success"] is True
    assert [a["label"] for a in result["actions"]] == [
        "Add private Desk escalation note",
        "Create Projects follow-up task",
        "Send customer acknowledgement",
    ]
    assert all(a["executed"] for a in result["actions"])

    comment = fake_zoho.body_for("POST", "/comments")
    assert comment["isPublic"] == "false"
    alert = comment["content"]
    assert "1042" in alert and "Acme" in alert
    assert "Checkout API returning 500s" in alert

    task = parse_qs(fake_zoho.body_for("POST", "/tasks/")["_raw"])
    assert task["priority"] == ["High"]
    assert "1042" in task["name"][0]
    assert task["end_date"] == [(datetime.now() + timedelta(hours=2)).strftime("%m-%d-%Y")]
    assert not any("/crm/" in url for url in fake_zoho.urls())

    reply = fake_zoho.body_for("POST", "sendReply")
    assert reply["to"] == "asha@acme.com"
    assert reply["fromEmailAddress"] == "ops@example.com"
    assert "we are on it" in reply["content"]


@pytest.mark.asyncio
async def test_support_missing_reply_sender_prevents_writes(configured_env, fake_zoho):
    configured_env.delenv("ZOHO_FROM_ADDRESS", raising=False)
    _desk_routes(fake_zoho)
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("Triage ticket id 10420001")
    assert result["success"] is False
    assert "authorized Desk reply address" in result["response"]
    assert fake_zoho.writes() == []


@pytest.mark.asyncio
async def test_support_workflow_skips_low_priority_tickets(configured_env, fake_zoho):
    _desk_routes(fake_zoho, priority="Low")
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("Triage ticket id 10420001")
    assert result["success"] is True
    assert result["actions"] == []
    assert "below the escalation threshold" in result["response"]
    assert fake_zoho.writes() == []


@pytest.mark.asyncio
async def test_support_workflow_dry_run_plans_every_action(monkeypatch, fake_zoho):
    monkeypatch.setenv("ZOHO_CLIENT_ID", "cid")
    monkeypatch.setenv("ZOHO_CLIENT_SECRET", "sec")
    monkeypatch.setenv("ZOHO_REFRESH_TOKEN", "rt")
    monkeypatch.setenv("ZOHO_ORG_ID", "org1")
    monkeypatch.setenv("ZOHO_CLIQ_CHANNEL", "support")
    _desk_routes(fake_zoho)
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("Triage ticket id 10420001")
    assert result["dry_run"] is True
    assert len(result["actions"]) == 3
    assert fake_zoho.writes() == []
    assert "Planned (dry run)" in result["response"]


@pytest.mark.asyncio
async def test_support_live_workflow_requires_ticket_id_before_writes(configured_env, fake_zoho):
    fake_zoho.json("POST", "/channelsbyname/support/message", {"id": "cliq-1"})
    fake_zoho.json("GET", "/Contacts/search", {"data": []})
    fake_zoho.json("POST", "/projects/456/tasks/", {"tasks": [{"id": "task-3"}]})

    pasted = (
        "Subject: Production outage on checkout\n"
        "Priority: Urgent\n"
        "Customer: Asha Rao\n"
        "Email: asha@acme.com\n\n"
        "Checkout has been down since 09:00 for every customer."
    )
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query(pasted)

    assert result["success"] is False
    assert "Desk ticket ID is required" in result["response"]
    assert fake_zoho.writes() == []


@pytest.mark.asyncio
async def test_support_workflow_needs_a_ticket(configured_env, fake_zoho):
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("go")
    assert result["success"] is False
    assert "ticket" in result["response"].lower()


@pytest.mark.asyncio
async def test_support_missing_customer_email_prevents_writes(configured_env, fake_zoho):
    _desk_routes(fake_zoho)
    fake_zoho.json("GET", "/api/v1/tickets/10420001", {
        "id": "10420001", "priority": "High", "subject": "Controlled test",
    })
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("Triage ticket id 10420001")
    assert result["success"] is False
    assert "customer email" in result["response"]
    assert fake_zoho.writes() == []


@pytest.mark.asyncio
async def test_support_failed_private_note_is_not_success(configured_env, fake_zoho):
    _desk_routes(fake_zoho)
    fake_zoho.json("POST", "/api/v1/tickets/10420001/comments", {"message": "Denied"}, status=403)
    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_zoho.client())
    result = await agent.process_query("Triage ticket id 10420001")
    assert result["success"] is False
    assert result["actions"][0]["executed"] is False
    assert result["actions"][0]["error"]


# ------------------------------------------ workflow 3: new customer

def _onboarding(**over) -> Dict[str, Any]:
    payload = {
        "welcome_subject": "Welcome to the team, Rahul",
        "welcome_body_html": "<p>Welcome aboard.</p>",
        "intro_call_title": "Intro call: Northwind",
        "intro_call_agenda": "Goals\nOnboarding plan\nNext steps",
        "sales_notification": "Rahul Verma from Northwind signed up via the website.",
    }
    payload.update(over)
    return payload


def _customer_routes(fake_zoho):
    fake_zoho.json(
        "GET",
        "/crm/v6/Contacts/search",
        {
            "data": [
                {
                    "id": "c-42",
                    "First_Name": "Rahul",
                    "Last_Name": "Verma",
                    "Full_Name": "Rahul Verma",
                    "Email": "rahul@northwind.com",
                    "Account_Name": {"name": "Northwind"},
                    "Title": "CTO",
                    "Lead_Source": "Website",
                    "Owner": {"name": "Sales Ops"},
                }
            ]
        },
    )
    fake_zoho.json("GET", "/api/accounts", {"data": [{"accountId": "acc-1"}]})
    fake_zoho.json("POST", "/api/accounts/acc-1/messages", {"data": {"messageId": "m-2"}})
    fake_zoho.json("POST", "/calendars/cal-uid-1/events", {"events": [{"uid": "ev-2"}]})
    fake_zoho.json("POST", "/api/v1/tickets", {"id": "desk-2", "ticketNumber": "102"})


@pytest.mark.asyncio
async def test_new_customer_workflow_executes_all_three_steps(configured_env, fake_zoho):
    _customer_routes(fake_zoho)
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard new customer\nName: Rahul Verma\nEmail: rahul@northwind.com\nCompany: Northwind\nTitle: CTO")

    assert result["success"] is True
    assert [a["label"] for a in result["actions"]] == [
        "Send welcome email",
        "Schedule introduction call",
        "Create Desk onboarding follow-up ticket",
    ]
    assert all(a["executed"] for a in result["actions"])

    mail = fake_zoho.body_for("POST", "/messages")
    assert mail["toAddress"] == "rahul@northwind.com"
    assert mail["subject"] == "Welcome to the team, Rahul"

    event = json.loads(httpx.URL(next(u for u in fake_zoho.urls("POST") if "events" in u)).params["eventdata"])
    assert event["title"] == "Intro call: Northwind"
    assert event["attendees"] == [{"email": "rahul@northwind.com", "permission": 1}]

    ticket = fake_zoho.body_for("POST", "/api/v1/tickets")
    assert ticket["departmentId"] == "dept123"
    assert ticket["contact"] == {"email": "rahul@northwind.com"}
    assert result["actions"][-1]["result"]["ticket_id"] == "desk-2"
    assert not any("cliq" in url for url in fake_zoho.urls())
    note = ticket["description"]
    assert "Northwind" in note and "CTO" in note
    assert not any("/crm/" in url for url in fake_zoho.urls())


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_new_customer_missing_desk_destination_prevents_live_writes(configured_env, fake_zoho, dry_run):
    configured_env.setenv("ZOHO_DESK_DEPARTMENT_ID", "")
    configured_env.setenv("ZOHO_DRY_RUN", str(dry_run).lower())
    _customer_routes(fake_zoho)
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard rahul@northwind.com")

    assert result["success"] is dry_run
    assert fake_zoho.writes() == []
    if not dry_run:
        assert "Configure ZOHO_DESK_DEPARTMENT_ID" in result["response"]


@pytest.mark.asyncio
async def test_new_customer_workflow_requests_details_instead_of_crm(configured_env, fake_zoho):
    _customer_routes(fake_zoho)
    fake_zoho.json(
        "GET",
        "/crm/v6/Contacts",
        {"data": [{"id": "c-99", "Full_Name": "Ana Diaz", "First_Name": "Ana", "Email": "ana@globex.com"}]},
    )
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard the newest customer in CRM")
    assert result["success"] is False
    assert "does not read CRM contacts" in result["response"]
    assert fake_zoho.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [({"message": "Denied"}, 403), ({}, 200)])
async def test_onboarding_unconfirmed_desk_creation_is_not_success(configured_env, fake_zoho, payload, status):
    _customer_routes(fake_zoho)
    fake_zoho.json("POST", "/api/v1/tickets", payload, status=status)
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard rahul@northwind.com")
    assert result["success"] is False
    assert result["actions"][-1]["executed"] is False
    assert result["actions"][-1]["error"]


@pytest.mark.asyncio
async def test_new_customer_workflow_requires_an_email(configured_env, fake_zoho):
    fake_zoho.json("GET", "/crm/v6/Contacts", {"data": [{"id": "c-98", "Full_Name": "No Mail"}]})
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard the newest contact")
    assert result["success"] is False
    assert "no email address" in result["response"].lower()
    assert fake_zoho.writes() == []


@pytest.mark.asyncio
async def test_new_customer_workflow_accepts_details_from_the_prompt(configured_env, fake_zoho):
    _customer_routes(fake_zoho)
    fake_zoho.json("GET", "/crm/v6/Contacts/search", {"data": []})
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query(
        "Onboard new customer\nName: Ira Bose\nEmail: ira@fabrikam.com\nCompany: Fabrikam"
    )
    assert result["success"] is True
    customer = result["data"]["customer"]
    assert customer["name"] == "Ira Bose"
    assert customer["company"] == "Fabrikam"
    assert customer["source"] == "prompt"


@pytest.mark.asyncio
async def test_new_customer_intro_call_is_on_a_future_weekday(configured_env, fake_zoho):
    _customer_routes(fake_zoho)
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard rahul@northwind.com")
    start = datetime.fromisoformat(result["data"]["intro_call"]["start"])
    assert start > datetime.now()
    assert start.weekday() < 5


@pytest.mark.asyncio
@pytest.mark.parametrize("separator", [" at ", " ", "T"])
async def test_new_customer_honours_explicit_intro_time(configured_env, fake_zoho, separator):
    _customer_routes(fake_zoho)
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    target = datetime(datetime.now().year + 1, 9, 16, 15, 0)
    result = await agent.process_query(
        "Name: Ayush Ranjan\nEmail: rahul@northwind.com\n"
        "Description: Controlled self-test only.\n"
        f"Schedule the introduction call on {target:%Y-%m-%d}{separator}15:00 Asia/Kolkata."
    )
    assert result["success"] is True
    assert datetime.fromisoformat(result["data"]["intro_call"]["start"]) == target


@pytest.mark.asyncio
async def test_thinking_steps_are_streamed_to_the_callback(configured_env, fake_zoho):
    _customer_routes(fake_zoho)
    seen: List[Dict[str, Any]] = []
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query(
        "Onboard rahul@northwind.com", session_id="s1", on_thinking_step=seen.append
    )
    assert seen == result["thinking_steps"]
    assert any(s["type"] == "tool_call" for s in seen)


@pytest.mark.asyncio
async def test_a_raising_callback_does_not_break_the_workflow(configured_env, fake_zoho):
    _customer_routes(fake_zoho)

    def boom(_step):
        raise RuntimeError("UI went away")

    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_zoho.client())
    result = await agent.process_query("Onboard rahul@northwind.com", on_thinking_step=boom)
    assert result["success"] is True
