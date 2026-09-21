"""Production-ready orchestrator for JIRA agent — enterprise grade.

Enterprise improvements over previous version:
- Dependency injection: JiraService, AIService, ConversationManager are
  constructor args, not module-level singletons.  Enables multi-tenancy and
  testing with stubs.
- Request-scoped TicketToolsContext prevents concurrent requests from
  overwriting each other's search results.
- Consistent, typed error envelopes — never leaks internal tracebacks to users.
- Structured metrics ready for Prometheus / OpenTelemetry export.
- Graceful client shutdown hook.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, Any, Optional

try:
    from langchain.agents import AgentExecutor, create_react_agent
    from langchain_core.prompts import PromptTemplate
    HAS_LANGCHAIN_AGENTS = True
except ImportError:
    try:
        from langchain_community.agents import AgentExecutor, create_react_agent
        from langchain_core.prompts import PromptTemplate
        HAS_LANGCHAIN_AGENTS = True
    except ImportError:
        HAS_LANGCHAIN_AGENTS = False
        AgentExecutor = None
        create_react_agent = None
        PromptTemplate = None

from .services.jira_service import JiraService
from .services.ai_service import AIService
from .services.langchain_llm import PwCGenAILLM
from .core.config import get_settings
from .core.logging import log_info, log_error, log_warning
from .core.llm_config import get_llm_config
from .tools.ticket_tools import TicketToolsContext
from .tools.tool_factory import create_jira_tools
from .utils import (
    ActionType,
    handle_parsing_error,
    analyze_intent,
    analyze_intent_with_llm,
    validate_prompt,
    validate_write_intent,
    WRITE_ACTIONS,
    InputValidationError,
    BRD_MAX_PROMPT_LENGTH,
    MAX_PROMPT_LENGTH,
)
from .tools.direct_processor import direct_process
from .tools.search import rewrite_user_query
from .tools.process_brd import process_brd_document
from .prompts import prompt_loader
from .helpers.conversation_manager import ConversationContext, ConversationManager, create_conversation_manager

# ------------------------------------------------------------------ #
# Configuration constants
# ------------------------------------------------------------------ #

AGENT_MAX_ITERATIONS = 5
AGENT_MAX_EXECUTION_TIME = 120  # seconds
AGENT_RUN_TIMEOUT = 90          # asyncio timeout for a single _run_agent call

# User-facing error messages (never expose internals)
_ERR_VALIDATION = "Invalid input: {detail}"
_ERR_GENERIC = "I encountered an error processing your request. Please try rephrasing."
_ERR_TIMEOUT = "The request took too long. Please simplify your query and try again."

# Read-heavy intents: handle via direct_process first so the ReAct loop cannot
# call create/update tools on search-style prompts. SEARCH_AND_UPDATE is
# routed the same way (direct path runs search; interactive flow matches
# legacy_processor behavior).
_DIRECT_FIRST_ACTIONS = frozenset({
    ActionType.SEARCH,
    ActionType.SEARCH_AND_UPDATE,
    ActionType.ANALYTICS,
    ActionType.UNKNOWN,
    ActionType.GET_DETAILS,
    ActionType.ISSUE_REPORT,
    ActionType.BRD,
})


class JiraAgent:
    """Enterprise-grade JIRA agent orchestrator.

    All external dependencies are injected via constructor, making the class
    testable and multi-tenant friendly.
    """

    def __init__(
        self,
        jira_service: Optional[JiraService] = None,
        ai_service: Optional[AIService] = None,
        conversation_manager: Optional[ConversationManager] = None,
    ):
        self.jira_service = jira_service or JiraService()
        self.ai_service = ai_service or AIService()
        self.conversation_manager = conversation_manager or create_conversation_manager(
            redis_url=get_settings().redis_url,
        )

        _jira_cfg = get_llm_config().get("jira_agent")
        self.llm = PwCGenAILLM(
            temperature=_jira_cfg.temperature,
            max_tokens=_jira_cfg.max_tokens,
            task_name="jira_agent",
        )
        # Shared tools for the LangChain agent (stateless, context is per-request)
        self._base_context = TicketToolsContext()
        self._tools = create_jira_tools(self.jira_service, self._base_context)
        self._agent = self._create_agent() if HAS_LANGCHAIN_AGENTS else None

        # Metrics counters (swap for Prometheus/OpenTelemetry in prod)
        self._metrics: Dict[str, int] = {
            "requests_total": 0,
            "requests_success": 0,
            "requests_failed": 0,
            "agent_fallbacks": 0,
            "validation_errors": 0,
        }

    async def _finalize_write_intent(
        self, user_prompt: str, intent: Dict[str, Any]
    ) -> Dict[str, Any]:
        """LLM check before any write path; can downgrade CREATE to SEARCH."""
        action = intent.get("action", ActionType.UNKNOWN)
        if action not in WRITE_ACTIONS:
            return intent
        result = await validate_write_intent(user_prompt, action)
        new_action = result["action"]
        if new_action is not action:
            reason = result.get("reasoning", "")
            log_warning(
                f"Write intent reclassified {action.value} -> {new_action.value}"
                + (f": {reason}" if reason else ""),
                "jira_agent",
            )
        elif result.get("fallback"):
            log_warning(
                f"Write intent validation inconclusive; using {new_action.value}",
                "jira_agent",
            )
        return {**intent, "action": new_action}

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def shutdown(self):
        """Cleanly close underlying HTTP clients."""
        await self.jira_service.close()

    def _is_brd_mode(self, context_data: Optional[Dict[str, Any]] = None) -> bool:
        """Return True if BRD mode is enabled via env config or per-request context_data."""
        if context_data and str(context_data.get("brd_mode", "")).lower() in ("true", "1", "yes"):
            return True
        return get_settings().brd_mode

    def _is_explicit_brd_request(self, context_data: Optional[Dict[str, Any]] = None) -> bool:
        """Return True only when the *request* explicitly sets brd_mode (not just global config)."""
        return bool(
            context_data
            and str(context_data.get("brd_mode", "")).lower() in ("true", "1", "yes")
        )

    # ------------------------------------------------------------------ #
    # Agent construction
    # ------------------------------------------------------------------ #

    def _create_agent(self):
        prompt_template = prompt_loader.get_prompt("jira_agent.yml", "agent_prompt")
        prompt = PromptTemplate(
            template=prompt_template,
            input_variables=["input", "tools", "tool_names", "agent_scratchpad"],
        )
        agent = create_react_agent(llm=self.llm, tools=self._tools, prompt=prompt)
        return AgentExecutor(
            agent=agent,
            tools=self._tools,
            verbose=True,
            handle_parsing_errors=handle_parsing_error,
            max_iterations=AGENT_MAX_ITERATIONS,
            max_execution_time=AGENT_MAX_EXECUTION_TIME,
            return_intermediate_steps=True,
        )

    # ------------------------------------------------------------------ #
    # Public API — legacy single-turn
    # ------------------------------------------------------------------ #

    async def process_query(self, user_prompt: str) -> Dict[str, Any]:
        """Legacy single-turn processing with validation & metrics."""
        start = time.monotonic()
        self._metrics["requests_total"] += 1

        try:
            allow_large = self._is_brd_mode()
            user_prompt = validate_prompt(
                user_prompt,
                max_length=BRD_MAX_PROMPT_LENGTH if allow_large else MAX_PROMPT_LENGTH,
            )
            original_prompt = user_prompt
            log_info(f"Processing query (legacy): {user_prompt[:120]}", "jira_agent")

            # Legacy path: same read-intent guard
            _READ_INTENTS = {
                ActionType.SEARCH, ActionType.GET_DETAILS, ActionType.GET_COMMENTS,
                ActionType.ANALYTICS, ActionType.SEARCH_AND_UPDATE,
            }
            is_brd = allow_large and analyze_intent(user_prompt)["action"] not in _READ_INTENTS
            if is_brd:
                log_info("BRD intent detected — routing to BRD processor", "jira_agent")
                tctx = TicketToolsContext()
                from .helpers.conversation_manager import ConversationContext
                conv = ConversationContext(session_id="brd-legacy")
                result = await process_brd_document(user_prompt, conv, self.jira_service, self.ai_service, tctx)
                result["duration_ms"] = self._elapsed_ms(start)
                self._metrics["requests_success"] += 1
                return result

            # Rewrite user query into proper JIRA terminology before processing
            user_prompt = await rewrite_user_query(self.ai_service, user_prompt)
            log_info(f"Rewritten query: {user_prompt[:120]}", "jira_agent")

            intent = analyze_intent(user_prompt)
            if intent["action"].value in ("unknown", "brd"):
                intent = await analyze_intent_with_llm(user_prompt)
            intent = await self._finalize_write_intent(user_prompt, intent)
            intent["original_prompt"] = original_prompt
            log_info(f"Detected intent: {intent['action'].value}", "jira_agent")

            if intent["action"] in _DIRECT_FIRST_ACTIONS:
                result = await direct_process(
                    user_prompt,
                    intent,
                    self.jira_service,
                    self.ai_service,
                    self._base_context,
                    conversation_ctx=None,
                )
                result["duration_ms"] = self._elapsed_ms(start)
                self._metrics["requests_success"] += 1
                return result

            try:
                if not self._agent:
                    raise RuntimeError("LangChain agent not available")

                result = await self._run_agent(user_prompt)
                agent_output = result.get("output", "")

                if agent_output and len(agent_output) > 20:
                    self._metrics["requests_success"] += 1
                    return {
                        "success": True,
                        "prompt": user_prompt,
                        "intent": intent["action"].value,
                        "response": agent_output,
                        "tickets": self._base_context.last_search_results,
                        "intermediate_steps": result.get("intermediate_steps", []),
                        "duration_ms": self._elapsed_ms(start),
                    }
                raise RuntimeError("Agent produced empty response")

            except Exception:
                self._metrics["agent_fallbacks"] += 1
                log_warning("Agent error, falling back to direct processing", "jira_agent")
                result = await direct_process(
                    user_prompt, intent, self.jira_service, self.ai_service, self._base_context,
                )
                result["duration_ms"] = self._elapsed_ms(start)
                self._metrics["requests_success"] += 1
                return result

        except InputValidationError as ve:
            self._metrics["validation_errors"] += 1
            return self._error_envelope(user_prompt, _ERR_VALIDATION.format(detail=ve), start)

        except Exception as e:
            self._metrics["requests_failed"] += 1
            log_error("Error processing query", "jira_agent", e)
            return self._error_envelope(user_prompt, _ERR_GENERIC, start)

    # ------------------------------------------------------------------ #
    # Public API — interactive multi-turn
    # ------------------------------------------------------------------ #

    async def process_query_interactive(
        self,
        user_prompt: str,
        conversation_ctx: Optional[ConversationContext] = None,
        context_data: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        ticket_tools_context: Optional[TicketToolsContext] = None,
    ) -> Dict[str, Any]:
        """Interactive multi-turn processing with validation, timeouts, metrics.

        When ``ticket_tools_context`` is provided (e.g. from workflow
        orchestration) it is used instead of a new per-request context so
        concurrent runs don't overwrite each other.
        """
        start = time.monotonic()
        self._metrics["requests_total"] += 1

        # Per-request context — prevents shared-state corruption
        tctx = ticket_tools_context or TicketToolsContext()
        if project_id:
            tctx.project_id = project_id

        # Propagate RBAC info if present in context_data
        if context_data:
            tctx.user_id = context_data.get("user_id")
            tctx.user_role = context_data.get("user_role")

        try:
            # Allow large prompts when brd_mode is on (BRD docs can be huge)
            allow_large = self._is_brd_mode(context_data)
            user_prompt = validate_prompt(
                user_prompt,
                max_length=BRD_MAX_PROMPT_LENGTH if allow_large else MAX_PROMPT_LENGTH,
            )
            original_prompt = user_prompt
            log_info(f"Processing interactive query: {user_prompt[:120]}", "jira_agent")

            # When brd_mode is active, use intent analysis only to detect read operations
            # (search/fetch/get). Those go through the normal path. Everything else is
            # treated as a BRD document — this restores the original multi-ticket behaviour
            # while preventing plain queries from being mis-routed into BRD.
            _READ_INTENTS = {
                ActionType.SEARCH, ActionType.GET_DETAILS, ActionType.GET_COMMENTS,
                ActionType.ANALYTICS, ActionType.SEARCH_AND_UPDATE,
            }
            if allow_large:
                quick_intent = analyze_intent(user_prompt)["action"]
                is_brd = quick_intent not in _READ_INTENTS
            else:
                is_brd = False

            if is_brd:
                log_info("BRD request — routing to BRD processor", "jira_agent")
                result = await process_brd_document(
                    user_prompt, conversation_ctx, self.jira_service, self.ai_service, tctx
                )
                if conversation_ctx:
                    try:
                        result["conversation_summary"] = conversation_ctx.get_summary()
                        result["message_count"] = len(conversation_ctx.messages)
                        await self.conversation_manager.save(conversation_ctx)
                    except Exception as _e:
                        log_error("BRD: session save failed (non-fatal)", "jira_agent", _e)
                result["duration_ms"] = self._elapsed_ms(start)
                self._metrics["requests_success"] += 1
                return result

            # Rewrite user query into proper JIRA terminology before processing
            user_prompt = await rewrite_user_query(self.ai_service, user_prompt)
            log_info(f"Rewritten query: {user_prompt[:120]}", "jira_agent")

            intent = analyze_intent(user_prompt)
            if intent["action"].value in ("unknown", "brd"):
                intent = await analyze_intent_with_llm(user_prompt)
            intent = await self._finalize_write_intent(user_prompt, intent)
            intent["original_prompt"] = original_prompt
            log_info(f"Detected intent: {intent['action'].value}", "jira_agent")

            result = await direct_process(
                user_prompt, intent, self.jira_service, self.ai_service,
                tctx, conversation_ctx=conversation_ctx, context_data=context_data,
            )

            if conversation_ctx:
                result["conversation_summary"] = conversation_ctx.get_summary()
                result["message_count"] = len(conversation_ctx.messages)
                # Persist updated session
                await self.conversation_manager.save(conversation_ctx)

            result["duration_ms"] = self._elapsed_ms(start)
            self._metrics["requests_success"] += 1
            return result

        except InputValidationError as ve:
            self._metrics["validation_errors"] += 1
            return {
                "success": False,
                "state": "initial",
                "session_id": conversation_ctx.session_id if conversation_ctx else "unknown",
                "prompt": user_prompt,
                "error": str(ve),
                "response": _ERR_VALIDATION.format(detail=ve),
                "tickets": [],
                "duration_ms": self._elapsed_ms(start),
            }

        except Exception as e:
            self._metrics["requests_failed"] += 1
            log_error("Error in interactive processing", "jira_agent", e)
            return {
                "success": False,
                "state": "initial",
                "session_id": conversation_ctx.session_id if conversation_ctx else "unknown",
                "prompt": user_prompt,
                "response": _ERR_GENERIC,
                "tickets": [],
                "duration_ms": self._elapsed_ms(start),
            }

    # ------------------------------------------------------------------ #
    # Agent execution with timeout
    # ------------------------------------------------------------------ #

    async def _run_agent(self, query: str) -> Dict[str, Any]:
        """Run the LangChain agent with a hard asyncio timeout."""

        def run_sync():
            return self._agent.invoke({"input": query})

        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, run_sync),
                timeout=AGENT_RUN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log_error(f"Agent execution timed out after {AGENT_RUN_TIMEOUT}s", "jira_agent")
            raise RuntimeError(_ERR_TIMEOUT)

    # ------------------------------------------------------------------ #
    # Metrics
    # ------------------------------------------------------------------ #

    def get_metrics(self) -> Dict[str, Any]:
        return dict(self._metrics)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)

    @staticmethod
    def _error_envelope(prompt: str, message: str, start: float) -> Dict[str, Any]:
        return {
            "success": False,
            "prompt": prompt,
            "response": message,
            "tickets": [],
            "duration_ms": int((time.monotonic() - start) * 1000),
        }


# ------------------------------------------------------------------ #
# Default instance (backward compat — prefer DI in new code)
# ------------------------------------------------------------------ #

jira_agent = JiraAgent()
