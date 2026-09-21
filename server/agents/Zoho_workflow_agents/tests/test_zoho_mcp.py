"""The MCP transport: config, protocol, capability resolution, argument binding."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from agents.Zoho_workflow_agents.config import get_settings
from agents.Zoho_workflow_agents.email_meeting_agent import ZohoEmailMeetingAgent
from agents.Zoho_workflow_agents.new_customer_agent import ZohoNewCustomerAgent
from agents.Zoho_workflow_agents.support_ticket_agent import ZohoSupportTicketAgent
from agents.Zoho_workflow_agents.zoho_mcp import (
    CAPABILITIES,
    ZohoMCPClient,
    ZohoMCPError,
    bind_arguments,
    capabilities_for_agent,
)

from .conftest import MCP_URL
from .test_zoho_workflows import StubAI, _meeting_intent, _onboarding, _triage


# --------------------------------------------------------------- config

@pytest.mark.asyncio
@pytest.mark.parametrize("capability", ["mail.list", "mail.read"])
async def test_missing_mail_reads_never_resolve_to_send_tools(fake_mcp, capability):
    fake_mcp.add_tool("ZohoCliq_send_message_to_user")
    fake_mcp.add_tool("ZohoMail_sendEmail")
    fake_mcp.add_tool("ZohoMail_getMailAccounts")
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        tools = await client.list_tools()
        tools[0]["description"] = "Get email details or list emails for a user before sending a message"
        with pytest.raises(ZohoMCPError, match="No tool"):
            await client.resolve(capability)


@pytest.mark.asyncio
async def test_mail_account_discovery_unwraps_live_response(monkeypatch):
    from agents.Zoho_workflow_agents.services.mcp_services import McpMailService

    monkeypatch.setenv("ZOHO_FROM_ADDRESS", "person@example.com")
    client = AsyncMock(spec=ZohoMCPClient)
    client.call_capability.return_value = {"structured": {
        "status": "success", "data": {"status": {"code": 200}, "data": [{
            "accountId": 123, "emailAddress": [{"mailId": "person@example.com", "isPrimary": True}],
        }]},
    }}
    service = McpMailService(client, get_settings())
    assert await service.get_account_id() == "123"
    assert await service.get_from_address() == "person@example.com"


@pytest.mark.asyncio
async def test_mail_listing_supplies_required_metadata_fields(fake_mcp, monkeypatch):
    from agents.Zoho_workflow_agents.services.mcp_services import McpMailService

    monkeypatch.setenv("ZOHO_FROM_ADDRESS", "person@example.com")
    fake_mcp.add_tool("ZohoMail_getMailAccounts", result=[{
        "accountId": "123", "primaryEmailAddress": "person@example.com",
    }])
    fake_mcp.add_tool("ZohoMail_listEmails", properties={
        "path_variables": {"properties": {"accountId": {"type": "string"}}},
        "query_params": {"properties": {
            "fields": {"type": "string"}, "limit": {"type": "integer"},
        }, "required": ["fields"]},
    }, result=[{"messageId": "456"}])
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        records = await McpMailService(client, get_settings()).list_messages(limit=5)
    assert records == [{"messageId": "456"}]
    assert fake_mcp.args_for("ZohoMail_listEmails") == {
        "path_variables": {"accountId": "123"},
        "query_params": {
            "limit": 5,
            "fields": "subject,messageId,folderId,fromAddress,toAddress,ccAddress,receivedTime,threadId",
        },
    }


@pytest.mark.asyncio
async def test_latest_mail_preserves_list_metadata_for_content_only_response():
    from agents.Zoho_workflow_agents.services.mcp_services import McpMailService

    client = AsyncMock(spec=ZohoMCPClient)
    client.resolve.return_value = ("mail_tool", {})
    client.call_capability.side_effect = [
        {"structured": {"data": [{
            "messageId": "123", "folderId": "456", "subject": "Meeting request",
            "fromAddress": "sender@example.com", "toAddress": "team@example.com",
            "receivedTime": "123456789", "threadId": "789",
        }]}},
        {"structured": {"data": {"content": "Please meet tomorrow.", "toAddress": "updated@example.com"}}},
    ]
    message = await McpMailService(client, get_settings()).get_latest_message()
    assert message is not None
    assert message["subject"] == "Meeting request"
    assert message["from"] == "sender@example.com"
    assert message["to"] == "updated@example.com"
    assert message["body"] == "Please meet tomorrow."
    assert message["received_time"] == "123456789"
    assert message["thread_id"] == "789"
    assert message["folder_id"] == "456"


@pytest.mark.asyncio
@pytest.mark.parametrize("address,expected", [
    ("person@example.com", "123"),
    (" PERSON@EXAMPLE.COM ", "123"),
    ("son@example.com", None),
    ("missing@example.com", None),
])
async def test_mail_account_selection_requires_an_exact_address(monkeypatch, address, expected):
    from agents.Zoho_workflow_agents.services.mcp_services import McpMailService

    monkeypatch.setenv("ZOHO_FROM_ADDRESS", address)
    client = AsyncMock(spec=ZohoMCPClient)
    client.call_capability.return_value = {"structured": {"data": [{
        "accountId": "123", "emailAddress": [{"mailId": "person@example.com", "isPrimary": True}],
        "displayName": "missing@example.com",
    }]}}
    service = McpMailService(client, get_settings())
    if expected:
        assert await service.get_account_id() == expected
    else:
        with pytest.raises(ZohoMCPError, match="Cannot select a mail account"):
            await service.get_account_id()


@pytest.mark.asyncio
async def test_desk_reply_requests_immediate_delivery(fake_mcp, monkeypatch):
    from agents.Zoho_workflow_agents.services.mcp_services import McpDeskService

    monkeypatch.setenv("ZOHO_ORG_ID", "123")
    fake_mcp.add_tool("ZohoDesk_sendReply", properties={
        "body": {"properties": {"content": {"type": "string"}}},
        "path_variables": {"properties": {"ticketId": {"type": "string"}}},
        "query_params": {"properties": {
            "sendImmediately": {"type": "boolean", "default": "false"},
            "orgId": {"type": "string"},
        }},
    }, result={"id": "789"})
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        await McpDeskService(client, get_settings()).send_reply(ticket_id="456", content="Acknowledged")
    assert fake_mcp.args_for("ZohoDesk_sendReply") == {
        "body": {"content": "Acknowledged"},
        "path_variables": {"ticketId": "456"},
        "query_params": {"sendImmediately": True, "orgId": "123"},
    }


@pytest.mark.parametrize("capability,fields,schema,expected", [
    (
        "mail.send",
        {"body": "Hello", "to": ["customer@example.com"], "account_id": "123"},
        {"properties": {
            "body": {"properties": {"content": {"type": "string"}, "toAddress": {"type": "string"}}},
            "path_variables": {"properties": {"accountId": {"type": "string"}}},
        }},
        {"body": {"content": "Hello", "toAddress": "customer@example.com"}, "path_variables": {"accountId": "123"}},
    ),
    (
        "desk.send_reply",
        {"body": "We are investigating", "ticket_id": "456", "channel": "EMAIL"},
        {"properties": {
            "body": {"oneOf": [{"properties": {
                "content": {"type": "string"}, "channel": {"type": "string"},
            }}], "properties": {"isPrivate": {"type": "string"}}},
            "path_variables": {"properties": {"ticketId": {"type": "string"}}},
        }},
        {"body": {"content": "We are investigating", "channel": "EMAIL"},
         "path_variables": {"ticketId": "456"}},
    ),
    (
        "cliq.post_message",
        {"text": "Ticket escalated", "channel": "support"},
        {"properties": {
            "body": {"properties": {"text": {"type": "string"}}},
            "path_variables": {"properties": {"CHANNEL_UNIQUE_NAME": {"type": "string"}}},
        }},
        {"body": {"text": "Ticket escalated"}, "path_variables": {"CHANNEL_UNIQUE_NAME": "support"}},
    ),
])
def test_nested_live_argument_shapes(capability, fields, schema, expected):
    assert bind_arguments(CAPABILITIES[capability], fields, schema) == expected


def test_calendar_nested_dates_and_attendees():
    schema = {"properties": {"body": {"properties": {
        "dateandtime": {"properties": {"start": {"type": "string"}, "end": {"type": "string"}, "timezone": {"type": "string"}}},
        "caluid": {"type": "string"},
        "attendees": {"type": "array", "items": {"properties": {"email": {"type": "string"}}}},
    }}}}
    fields = {"start": "2026-05-10T09:00:00", "end": "2026-05-10T09:30:00",
              "timezone": "Asia/Kolkata", "calendar_id": "cal-1", "attendees": ["person@example.com"]}
    assert bind_arguments(CAPABILITIES["calendar.create_event"], fields, schema) == {"body": {
        "dateandtime": {"start": "20260510T090000", "end": "20260510T093000", "timezone": "Asia/Kolkata"},
        "caluid": "cal-1", "attendees": [{"email": "person@example.com"}],
    }}


@pytest.mark.asyncio
async def test_projects_service_uses_numeric_destination_and_live_schema(fake_mcp, monkeypatch):
    from agents.Zoho_workflow_agents.services.mcp_services import McpProjectsService

    monkeypatch.setenv("ZOHO_PROJECTS_PORTAL_ID", "123")
    monkeypatch.setenv("ZOHO_PROJECTS_PROJECT_ID", "456")
    fake_mcp.add_tool("ZohoProjects_create_a_task", properties={
        "body": {"properties": {"created_by": {"properties": {"name": {"type": "string"}}},
                                 "name": {"type": "string"}, "end_date": {"type": "string"},
                                 "priority": {"type": "string", "enum": ["low", "medium", "high"]}}},
        "path_variables": {"properties": {"portal_id": {"type": "string"}, "project_id": {"type": "string"}}},
    }, result={"id": "789"})
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        await McpProjectsService(client, get_settings()).create_task(subject="Follow up", due_date=datetime(2026, 5, 10))
    assert fake_mcp.args_for("ZohoProjects_create_a_task") == {
        "body": {"name": "Follow up", "end_date": "2026-05-10", "priority": "high"},
        "path_variables": {"portal_id": "123", "project_id": "456"},
    }

def test_an_mcp_url_switches_the_transport(monkeypatch):
    assert get_settings().backend == "rest"
    monkeypatch.setenv("ZOHO_MCP_URL", MCP_URL)
    settings = get_settings()
    assert settings.backend == "mcp"
    assert settings.uses_mcp is True


def test_mcp_mode_needs_no_oauth_credentials(monkeypatch):
    monkeypatch.setenv("ZOHO_MCP_URL", MCP_URL)
    # The connection is pre-authorized, so no client id / secret / refresh token.
    assert get_settings().missing_credentials() == []


def test_mcp_mode_still_requires_the_url(monkeypatch):
    monkeypatch.setenv("ZOHO_BACKEND", "mcp")
    assert get_settings().missing_credentials() == ["ZOHO_MCP_URL"]


def test_backend_can_be_forced_back_to_rest(monkeypatch):
    monkeypatch.setenv("ZOHO_MCP_URL", MCP_URL)
    monkeypatch.setenv("ZOHO_BACKEND", "rest")
    settings = get_settings()
    assert settings.backend == "rest"
    assert "ZOHO_CLIENT_ID" in settings.missing_credentials()


def test_the_legacy_env_name_is_accepted(monkeypatch):
    monkeypatch.setenv("ZOHO_MCP_SERVER_URL", MCP_URL)
    assert get_settings().uses_mcp is True


def test_every_agent_declares_its_capabilities():
    for agent_id in (
        "zoho_email_meeting_agent",
        "zoho_support_ticket_agent",
        "zoho_new_customer_agent",
    ):
        groups = capabilities_for_agent(agent_id)
        assert groups["required"], f"{agent_id} declares no required capabilities"
        for key in groups["required"] + groups["optional"]:
            assert key in CAPABILITIES, f"{agent_id} references unknown capability {key}"


def test_email_meeting_requires_projects_instead_of_crm():
    groups = capabilities_for_agent("zoho_email_meeting_agent")
    assert "projects.create_task" in groups["required"]
    assert "crm.create_task" not in groups["required"]


@pytest.mark.asyncio
async def test_projects_does_not_resolve_to_crm_or_read_tools(fake_mcp):
    fake_mcp.add_tool("zohocrm_create_task")
    fake_mcp.add_tool("ZohoProjects_get_tasks")
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        with pytest.raises(ZohoMCPError, match="No tool"):
            await client.resolve("projects.create_task")


@pytest.mark.asyncio
async def test_cliq_uses_channel_not_user_or_bot(fake_mcp):
    for name in ("ZohoCliq_send_message_to_user", "ZohoCliq_send_message_to_bot",
                 "ZohoCliq_send_message_to_chat", "ZohoCliq_send_message_to_channel"):
        fake_mcp.add_tool(name)
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        name, _schema = await client.resolve("cliq.post_message")
        assert name == "ZohoCliq_send_message_to_channel"


# ------------------------------------------------------------- protocol

@pytest.mark.asyncio
async def test_handshake_runs_once_and_caches_the_tool_list(fake_mcp):
    fake_mcp.add_tool("zohomail_send_email")
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        await client.list_tools()
        await client.list_tools()
    assert fake_mcp.initialized is True


@pytest.mark.asyncio
async def test_a_business_failure_with_iserror_false_is_still_an_error(fake_mcp):
    """Zoho reports 'Tool not found' with isError false; that must not pass silently."""
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        with pytest.raises(ZohoMCPError, match="Tool not found"):
            await client.call_tool("nope", {})


@pytest.mark.asyncio
async def test_a_jsonrpc_error_is_surfaced(fake_mcp):
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        with pytest.raises(ZohoMCPError, match="Method not found"):
            await client._rpc("prompts/list")


def test_an_sse_framed_body_is_parsed():
    from agents.Zoho_workflow_agents.zoho_mcp import _parse_rpc_body

    frame = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
    assert _parse_rpc_body(frame)["result"] == {"tools": []}


def test_a_missing_url_is_refused_immediately():
    with pytest.raises(ZohoMCPError, match="ZOHO_MCP_URL"):
        ZohoMCPClient("")


# --------------------------------------------------- capability resolution

@pytest.mark.asyncio
async def test_capabilities_resolve_against_published_names(fake_mcp):
    fake_mcp.add_tool("zohomail_send_email")
    fake_mcp.add_tool("zohocalendar_create_event")
    fake_mcp.add_tool("zohocrm_create_task")
    fake_mcp.add_tool("zohocliq_post_message")
    fake_mcp.add_tool("zohodesk_send_reply")
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        for key, expected in [
            ("mail.send", "zohomail_send_email"),
            ("calendar.create_event", "zohocalendar_create_event"),
            ("crm.create_task", "zohocrm_create_task"),
            ("cliq.post_message", "zohocliq_post_message"),
            ("desk.send_reply", "zohodesk_send_reply"),
        ]:
            name, _schema = await client.resolve(key)
            assert name == expected, key


@pytest.mark.asyncio
async def test_resolution_tolerates_other_naming_styles(fake_mcp):
    fake_mcp.add_tool("Zoho_Mail_SendMail")
    fake_mcp.add_tool("create-calendar-event")
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        assert (await client.resolve("mail.send"))[0] == "Zoho_Mail_SendMail"
        assert (await client.resolve("calendar.create_event"))[0] == "create-calendar-event"


@pytest.mark.asyncio
async def test_an_override_pins_the_tool(fake_mcp, monkeypatch):
    fake_mcp.add_tool("zohomail_send_email")
    fake_mcp.add_tool("custom_mailer")
    monkeypatch.setenv("ZOHO_MCP_TOOL_MAIL_SEND", "custom_mailer")
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        assert (await client.resolve("mail.send"))[0] == "custom_mailer"


@pytest.mark.asyncio
async def test_an_override_naming_a_missing_tool_says_so(fake_mcp, monkeypatch):
    fake_mcp.add_tool("zohomail_send_email")
    monkeypatch.setenv("ZOHO_MCP_TOOL_MAIL_SEND", "typo_tool")
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        with pytest.raises(ZohoMCPError) as excinfo:
            await client.resolve("mail.send")
    message = str(excinfo.value)
    assert "typo_tool" in message
    assert "zohomail_send_email" in message, "the error should list what is available"


@pytest.mark.asyncio
async def test_an_empty_connection_tells_the_operator_what_to_enable(fake_mcp):
    """This is the state of a console connection with no services added."""
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        with pytest.raises(ZohoMCPError) as excinfo:
            await client.resolve("mail.send")
    message = str(excinfo.value)
    assert "publishes no tools" in message
    assert "Zoho MCP console" in message
    assert "Zoho Mail" in message


@pytest.mark.asyncio
async def test_a_partly_configured_connection_names_the_missing_service(fake_mcp):
    fake_mcp.add_tool("zohomail_send_email")
    async with fake_mcp.client() as http:
        client = ZohoMCPClient(MCP_URL, http=http)
        with pytest.raises(ZohoMCPError) as excinfo:
            await client.resolve("desk.send_reply")
    message = str(excinfo.value)
    assert "Zoho Desk" in message
    assert "ZOHO_MCP_TOOL_DESK_SEND_REPLY" in message


# ---------------------------------------------------- argument binding

def test_arguments_bind_to_the_schema_property_names():
    cap = CAPABILITIES["mail.send"]
    schema = {"properties": {"toAddress": {"type": "string"}, "subject": {"type": "string"},
                             "content": {"type": "string"}}}
    args = bind_arguments(cap, {"to": ["a@x.com", "b@x.com"], "subject": "Hi", "body": "<p>x</p>"}, schema)
    # A schema asking for a string gets a joined string, not a list.
    assert args == {"toAddress": "a@x.com, b@x.com", "subject": "Hi", "content": "<p>x</p>"}


def test_arguments_bind_case_insensitively():
    cap = CAPABILITIES["crm.create_task"]
    schema = {"properties": {"subject": {"type": "string"}, "due_date": {"type": "string"}}}
    args = bind_arguments(cap, {"subject": "Call back", "due_date": "2026-09-20"}, schema)
    assert args == {"subject": "Call back", "due_date": "2026-09-20"}


def test_a_list_schema_receives_a_list():
    cap = CAPABILITIES["mail.send"]
    schema = {"properties": {"to": {"type": "array", "items": {"type": "string"}}}}
    assert bind_arguments(cap, {"to": "solo@x.com"}, schema) == {"to": ["solo@x.com"]}


def test_unknown_arguments_are_dropped_not_sent():
    """Zoho rejects unexpected arguments, so a field the tool cannot take is omitted."""
    cap = CAPABILITIES["mail.send"]
    schema = {"properties": {"toAddress": {"type": "string"}}}
    args = bind_arguments(cap, {"to": ["a@x.com"], "subject": "Hi", "body": "x"}, schema)
    assert args == {"toAddress": "a@x.com"}


def test_empty_values_are_never_sent():
    cap = CAPABILITIES["mail.send"]
    schema = {"properties": {"toAddress": {"type": "string"}, "ccAddress": {"type": "string"}}}
    args = bind_arguments(cap, {"to": ["a@x.com"], "cc": []}, schema)
    assert args == {"toAddress": "a@x.com"}


def test_without_a_schema_the_first_candidate_name_is_used():
    cap = CAPABILITIES["cliq.post_message"]
    assert bind_arguments(cap, {"text": "hi"}, {}) == {"text": "hi"}


def test_numeric_and_boolean_coercion_follows_the_schema():
    cap = CAPABILITIES["desk.list_tickets"]
    schema = {"properties": {"limit": {"type": "integer"}}}
    assert bind_arguments(cap, {"limit": "25"}, schema) == {"limit": 25}

    comment = CAPABILITIES["desk.add_comment"]
    bool_schema = {"properties": {"isPublic": {"type": "string"}}}
    assert bind_arguments(comment, {"is_public": True}, bool_schema) == {"isPublic": "true"}


# ------------------------------------------- workflows over the transport

def _mail_calendar_crm_tools(fake_mcp):
    fake_mcp.add_tool(
        "zohomail_send_email",
        properties={"toAddress": {"type": "string"}, "ccAddress": {"type": "string"},
                    "subject": {"type": "string"}, "content": {"type": "string"},
                    "fromAddress": {"type": "string"}},
        required=["toAddress", "subject"],
        result={"messageId": "mcp-mail-1"},
    )
    fake_mcp.add_tool(
        "zohocalendar_create_event",
        properties={"title": {"type": "string"}, "start": {"type": "string"},
                    "end": {"type": "string"}, "description": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "timezone": {"type": "string"}},
        result={"uid": "mcp-event-1"},
    )
    fake_mcp.add_tool(
        "zoho_projects_create_task",
        properties={"name": {"type": "string"}, "description": {"type": "string"},
                    "start_date": {"type": "string"}, "due_date": {"type": "string"},
                    "priority": {"type": "string"}},
        result={"details": {"id": "mcp-task-1"}},
    )
    fake_mcp.add_tool(
        "zohocrm_search_records",
        properties={"email": {"type": "string"}, "module": {"type": "string"}},
        result=[{"id": "mcp-contact-1", "Full_Name": "Priya Sharma", "Email": "priya@acme.com"}],
    )


MEETING_EMAIL = (
    "From: Priya Sharma <priya@acme.com>\n"
    "Subject: Can we meet about the data migration?\n\n"
    "Could we get 45 minutes next week to walk through the migration plan?"
)


@pytest.mark.asyncio
async def test_meeting_workflow_runs_entirely_over_mcp(mcp_env, fake_mcp):
    _mail_calendar_crm_tools(fake_mcp)
    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_mcp.client())
    result = await agent.process_query(MEETING_EMAIL)

    assert result["success"] is True
    assert all(a["executed"] for a in result["actions"]), result["actions"]
    assert fake_mcp.called_names() == [
        "zohocalendar_create_event",
        "zohomail_send_email",
        "zoho_projects_create_task",
    ]

    event = fake_mcp.args_for("zohocalendar_create_event")
    assert event["title"] == "Data migration walkthrough"
    assert event["attendees"] == ["priya@acme.com"]
    # 45 minutes of intent, expressed in ISO 8601 for MCP rather than Zoho's compact form.
    start = datetime.fromisoformat(event["start"])
    assert (datetime.fromisoformat(event["end"]) - start) == timedelta(minutes=45)

    mail = fake_mcp.args_for("zohomail_send_email")
    assert mail["toAddress"] == "priya@acme.com"
    assert "Confirmed:" in mail["subject"]
    assert mail["fromAddress"] == "ops@example.com"

    task = fake_mcp.args_for("zoho_projects_create_task")
    assert task["name"] == "Prepare the migration plan deck"
    assert task["priority"] == "High"


@pytest.mark.asyncio
async def test_mcp_dry_run_calls_no_tools(monkeypatch, fake_mcp):
    monkeypatch.setenv("ZOHO_MCP_URL", MCP_URL)
    monkeypatch.setenv("ZOHO_CLIQ_CHANNEL", "support")
    _mail_calendar_crm_tools(fake_mcp)

    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_mcp.client())
    result = await agent.process_query(MEETING_EMAIL)

    assert result["dry_run"] is True
    assert len(result["actions"]) == 3
    assert all(a["skipped_reason"] == "dry_run" for a in result["actions"])
    # Reads are not gated in either transport, only writes. A CRM contact
    # lookup during a dry run is expected; sending or creating anything is not.
    write_tools = {"zohomail_send_email", "zohocalendar_create_event", "zoho_projects_create_task"}
    assert write_tools.isdisjoint(fake_mcp.called_names()), "dry run must not call a write tool"


@pytest.mark.asyncio
async def test_a_missing_capability_is_reported_per_step(mcp_env, fake_mcp):
    """Only Mail is enabled: the calendar step fails, the rest still run."""
    _mail_calendar_crm_tools(fake_mcp)
    fake_mcp.tools = [t for t in fake_mcp.tools if "calendar" not in t["name"]]

    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_mcp.client())
    result = await agent.process_query(MEETING_EMAIL)

    calendar_action = result["actions"][0]
    assert calendar_action["executed"] is False
    assert "Zoho Calendar" in calendar_action["error"]
    assert result["actions"][1]["executed"] is True, "the confirmation email still sends"
    assert result["actions"][2]["executed"] is True, "the Projects task is still created"


@pytest.mark.asyncio
async def test_support_workflow_runs_over_mcp(mcp_env, fake_mcp):
    fake_mcp.add_tool(
        "zohodesk_get_ticket",
        properties={"ticketId": {"type": "string"}, "include": {"type": "string"}},
        result={
            "id": "10420001", "ticketNumber": "1042", "subject": "Checkout API failing",
            "description": "All checkout calls return HTTP 500 since 09:00.",
            "priority": "Urgent", "status": "Open",
            "contact": {"firstName": "Asha", "lastName": "Rao", "email": "asha@acme.com", "id": "c-7"},
            "account": {"accountName": "Acme"},
        },
    )
    fake_mcp.add_tool(
        "ZohoDesk_createTicketComment",
        properties={"ticketId": {"type": "string"}, "content": {"type": "string"}, "isPublic": {"type": "boolean"}},
        result={"id": "comment-1"},
    )
    fake_mcp.add_tool(
        "ZohoProjects_create_a_task",
        properties={"name": {"type": "string"}, "due_date": {"type": "string"}},
        result={"details": {"id": "mcp-task-2"}},
    )
    fake_mcp.add_tool(
        "zohodesk_send_reply",
        properties={"ticketId": {"type": "string"}, "content": {"type": "string"},
                    "to": {"type": "string"}, "channel": {"type": "string"},
                    "fromEmailAddress": {"type": "string"}},
        result={"id": "thread-1"},
    )

    agent = ZohoSupportTicketAgent(ai_service=StubAI(_triage()), http=fake_mcp.client())
    result = await agent.process_query("Triage ticket id 10420001")

    assert result["success"] is True
    assert all(a["executed"] for a in result["actions"]), result["actions"]

    assert fake_mcp.args_for("zohodesk_get_ticket") == {"ticketId": "10420001"}
    alert = fake_mcp.args_for("ZohoDesk_createTicketComment")
    assert "1042" in alert["content"] and alert["ticketId"] == "10420001"
    assert alert["isPublic"] is False
    assert not any("cliq" in name.lower() for name in fake_mcp.called_names())
    reply = fake_mcp.args_for("zohodesk_send_reply")
    assert reply["ticketId"] == "10420001"
    assert reply["to"] == "asha@acme.com"
    assert reply["fromEmailAddress"] == "ops@example.com"


@pytest.mark.asyncio
async def test_new_customer_workflow_runs_over_mcp(mcp_env, fake_mcp):
    _mail_calendar_crm_tools(fake_mcp)
    fake_mcp.add_tool(
        "ZohoDesk_createTicket",
        properties={"body": {"type": "object", "properties": {
            "subject": {"type": "string"}, "description": {"type": "string"},
            "departmentId": {"type": "string"}, "email": {"type": "string"},
            "contact": {"type": "object", "properties": {"email": {"type": "string"}}},
        }}},
        result={"data": {"id": "desk-2", "ticketNumber": "102"}},
    )
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_mcp.client())
    result = await agent.process_query("Onboard priya@acme.com")

    assert result["success"] is True
    assert [a["label"] for a in result["actions"]] == [
        "Send welcome email",
        "Schedule introduction call",
        "Create Desk onboarding follow-up ticket",
    ]
    assert all(a["executed"] for a in result["actions"]), result["actions"]
    assert fake_mcp.args_for("zohomail_send_email")["toAddress"] == "priya@acme.com"
    ticket = fake_mcp.args_for("ZohoDesk_createTicket")["body"]
    assert ticket["contact"] == {"email": "priya@acme.com"}
    assert ticket["departmentId"] == "dept123"
    assert result["actions"][-1]["result"]["ticket_id"] == "desk-2"
    assert not any("cliq" in name.lower() for name in fake_mcp.called_names())


@pytest.mark.asyncio
async def test_the_transport_is_named_in_the_thinking_steps(mcp_env, fake_mcp):
    _mail_calendar_crm_tools(fake_mcp)
    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_mcp.client())
    result = await agent.process_query(MEETING_EMAIL)
    first = result["thinking_steps"][0]["content"]
    assert "MCP connection" in first
    assert "no local Zoho tokens" in first


@pytest.mark.asyncio
async def test_onboarding_missing_ticket_creation_stops_before_writes(mcp_env, fake_mcp):
    _mail_calendar_crm_tools(fake_mcp)
    fake_mcp.add_tool("ZohoDesk_createTicketComment")
    fake_mcp.tools[-1]["description"] = "Create ticket and add comments"
    agent = ZohoNewCustomerAgent(ai_service=StubAI(_onboarding()), http=fake_mcp.client())
    result = await agent.process_query("Onboard priya@acme.com")
    assert result["success"] is False
    assert "Zoho Desk" in result["response"]
    assert fake_mcp.called_names() == []


@pytest.mark.asyncio
async def test_desk_read_requires_an_actual_record(mcp_env, fake_mcp):
    from agents.Zoho_workflow_agents.services.mcp_services import McpDeskService

    fake_mcp.add_tool("ZohoDesk_getTicket", result={"message": "No ticket found"})
    async with ZohoMCPClient(MCP_URL, http=fake_mcp.client()) as client:
        with pytest.raises(ZohoMCPError, match="real ticket record"):
            await McpDeskService(client, get_settings()).get_ticket("10420001")


@pytest.mark.asyncio
async def test_an_unconfigured_agent_offers_both_setup_routes(fake_mcp):
    agent = ZohoEmailMeetingAgent(ai_service=StubAI(_meeting_intent()), http=fake_mcp.client())
    result = await agent.process_query(MEETING_EMAIL)
    assert result["success"] is False
    assert "ZOHO_MCP_URL" in result["response"]
    assert "Authorization via Connection" in result["response"]
    assert fake_mcp.calls == []
