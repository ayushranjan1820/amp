import asyncio
import importlib
import sys
import types

from server.agents.JIRA_agent.helpers.conversation_manager import ConversationContext, ConversationState


# The tools package transitively imports services.ai_service which expects
# agents.llm_continuation in this runtime; provide a minimal stub for tests.
_agents_mod = types.ModuleType("agents")
_agents_mod.__path__ = []  # mark as package for submodule imports
_llm_mod = types.ModuleType("agents.llm_continuation")
_local_llm_mod = types.ModuleType("agents.local_llm")


async def _stub_async_call_with_continuation(*args, **kwargs):
    return ""


_llm_mod.async_call_with_continuation = _stub_async_call_with_continuation


def _stub_get_llm_provider():
    return "local_llm"


def _stub_uses_pwc_genai_credentials():
    return False


_local_llm_mod.get_llm_provider = _stub_get_llm_provider
_local_llm_mod.uses_pwc_genai_credentials = _stub_uses_pwc_genai_credentials
_agents_mod.llm_continuation = _llm_mod
_agents_mod.local_llm = _local_llm_mod
sys.modules.setdefault("agents", _agents_mod)
sys.modules.setdefault("agents.llm_continuation", _llm_mod)
sys.modules.setdefault("agents.local_llm", _local_llm_mod)

pir_module = importlib.import_module("server.agents.JIRA_agent.tools.process_issue_report")


class _DummyAI:
    async def call_genai(self, **kwargs):
        return '{"search_query": "kyc dob", "issue_summary": "Add DOB field to KYC form"}'


class _DummyContext:
    def __init__(self):
        self.last_search_results = []


def test_issue_report_no_matches_continues_to_create(monkeypatch):
    async def _search_stub(jira_service, context, query, ai_service):
        context.last_search_results = []
        return "No JIRA issues matched this request"

    async def _create_stub(user_prompt, conversation_ctx, jira_service, ai_service, context=None):
        return {
            "success": True,
            "state": ConversationState.COMPLETED.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "create",
            "response": "auto-created",
            "tickets": [],
            "collected_data": conversation_ctx.collected_data,
        }

    monkeypatch.setattr(pir_module, "search_tickets_tool", _search_stub)
    monkeypatch.setattr("server.agents.JIRA_agent.tools.process_create.process_create_ticket", _create_stub)

    ctx = ConversationContext("session-no-match")
    result = asyncio.run(
        pir_module.process_issue_report(
            "DOB field missing in KYC form",
            ctx,
            jira_service=None,
            ai_service=_DummyAI(),
            context=_DummyContext(),
        )
    )

    assert result["intent"] == "create"
    assert result["response"] == "auto-created"
    assert ctx.state != ConversationState.AWAITING_INFO


def test_issue_report_with_matches_interrupts_for_choice(monkeypatch):
    async def _search_stub(jira_service, context, query, ai_service):
        context.last_search_results = [
            {"key": "KAN-101", "summary": "KYC field update", "status": "To Do"},
        ]
        return "Found 1 ticket"

    monkeypatch.setattr(pir_module, "search_tickets_tool", _search_stub)

    ctx = ConversationContext("session-match")
    context = _DummyContext()
    result = asyncio.run(
        pir_module.process_issue_report(
            "DOB field missing in KYC form",
            ctx,
            jira_service=None,
            ai_service=_DummyAI(),
            context=context,
        )
    )

    assert result["intent"] == "issue_report"
    assert result["tickets"]
    assert "What would you like to do?" in result["response"]
    assert ctx.state == ConversationState.AWAITING_INFO
