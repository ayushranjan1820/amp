"""Direct processing dispatcher for JIRA agent with intelligent routing.

Enterprise improvements:
- Safe error responses — never leaks internal exceptions to users
- Structured logging of errors with tracebacks (server-side only)
"""
from __future__ import annotations

from typing import Dict, Any, Optional

from ..core.logging import log_error, log_info
from ..utils import ActionType
from . import (
    TicketToolsContext,
    get_details_tool,
    get_details_multi_tool,
    get_comments_tool,
    enrich_with_context,
    process_create_ticket,
    process_update_ticket,
    process_search_tickets,
    process_create_subtask,
    process_link_issues,
    process_issue_report,
    handle_info_response,
    process_without_conversation,
    process_analytics,
    process_brd_document,
)
from ..helpers.conversation_manager import ConversationContext, ConversationState
from ..helpers import extract_ticket_data_from_prompt

_enrich_with_context = enrich_with_context

# User-facing error message — never expose internals
_SAFE_ERROR = "Something went wrong while processing your request. Please try again or rephrase your query."


async def direct_process(
    user_prompt: str,
    intent: Dict[str, Any],
    jira_service,
    ai_service,
    context: TicketToolsContext,
    conversation_ctx: Optional[ConversationContext] = None,
    context_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Direct processing with intelligent information gathering and conversation memory."""
    action = intent.get("action", ActionType.UNKNOWN)
    ticket_key = intent.get("ticket_key")
    ticket_keys = intent.get("ticket_keys") or ([ticket_key] if ticket_key else [])
    original_prompt = intent.get("original_prompt") or user_prompt
    # Use the ORIGINAL (pre-rewrite) prompt for intent-style detection — the
    # rewriter strips terms like "description" while normalising filters.
    detect_prompt_lower = (original_prompt or "").lower()
    description_only_requested = (
        "description field text only" in detect_prompt_lower
        or "description text only" in detect_prompt_lower
        or "description only" in detect_prompt_lower
    )

    if conversation_ctx is None:
        return await process_without_conversation(
            user_prompt,
            intent,
            jira_service,
            ai_service,
            context,
            context_data=context_data,
        )

    log_info(
        f"Processing with conversation memory. State: {conversation_ctx.state}, "
        f"Messages: {len(conversation_ctx.messages)}",
        "direct_processor",
    )

    try:
        if conversation_ctx.state == ConversationState.AWAITING_INFO:
            return await handle_info_response(user_prompt, conversation_ctx, jira_service, ai_service, context)

        extracted_data = extract_ticket_data_from_prompt(user_prompt)
        conversation_ctx.update_collected_data(extracted_data)
        conversation_ctx.action_type = action.value
        conversation_ctx.original_intent = user_prompt

        log_info(f"Extracted data: {extracted_data}", "direct_processor")

        if action == ActionType.CREATE:
            return await process_create_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)

        if action == ActionType.UPDATE:
            return await process_update_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)

        if action in (ActionType.SEARCH, ActionType.UNKNOWN, ActionType.SEARCH_AND_UPDATE):
            return await process_search_tickets(
                user_prompt, conversation_ctx, jira_service, ai_service, context,
                original_prompt=original_prompt,
            )

        if action == ActionType.GET_DETAILS and ticket_keys:
            if description_only_requested:
                parts = []
                for key in ticket_keys:
                    issue = await jira_service.get_issue(key)
                    norm_key = key.strip().upper()
                    if issue is None:
                        parts.append(f"Ticket {norm_key} not found")
                    else:
                        desc = (issue.get("description") or "").strip()
                        parts.append(f"**{norm_key}**:\n{desc or '(Description is empty)'}")
                result = "\n\n---\n\n".join(parts)
            elif len(ticket_keys) == 1:
                result = await get_details_tool(jira_service, ticket_keys[0])
            else:
                result = await get_details_multi_tool(jira_service, ticket_keys)
            conversation_ctx.state = ConversationState.COMPLETED
            return {
                "success": True,
                "state": conversation_ctx.state.value,
                "session_id": conversation_ctx.session_id,
                "prompt": user_prompt,
                "intent": action.value,
                "response": result,
                "tickets": [],
                "collected_data": conversation_ctx.collected_data,
            }

        if action == ActionType.GET_COMMENTS and ticket_key:
            result = await get_comments_tool(jira_service, ticket_key)
            conversation_ctx.state = ConversationState.COMPLETED
            return {
                "success": True,
                "state": conversation_ctx.state.value,
                "session_id": conversation_ctx.session_id,
                "prompt": user_prompt,
                "intent": action.value,
                "response": result,
                "tickets": [],
                "collected_data": conversation_ctx.collected_data,
            }

        if action == ActionType.SUBTASK:
            return await process_create_subtask(user_prompt, conversation_ctx, jira_service, ai_service, context)

        if action == ActionType.LINK:
            return await process_link_issues(user_prompt, conversation_ctx, jira_service, ai_service, context)

        if action == ActionType.ISSUE_REPORT:
            return await process_issue_report(user_prompt, conversation_ctx, jira_service, ai_service, context)

        if action == ActionType.ANALYTICS:
            return await process_analytics(user_prompt, conversation_ctx, jira_service, ai_service, context)

        if action == ActionType.BRD:
            return await process_brd_document(user_prompt, conversation_ctx, jira_service, ai_service, context)

        # Fallback
        return await process_search_tickets(
            user_prompt, conversation_ctx, jira_service, ai_service, context,
            original_prompt=original_prompt,
        )

    except Exception as e:
        # Log full traceback server-side, return safe message to user
        log_error(f"Direct processing error: {e}", "direct_processor", e)
        return {
            "success": False,
            "state": ConversationState.INITIAL.value,
            "session_id": conversation_ctx.session_id if conversation_ctx else "unknown",
            "prompt": user_prompt,
            "intent": action.value,
            "response": _SAFE_ERROR,
            "tickets": [],
        }
