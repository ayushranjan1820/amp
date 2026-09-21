"""Handle user responses to information requests during multi-turn conversations."""
from typing import Dict, Any

from ..core.logging import log_info
from ..utils import ActionType
from .ticket_tools import TicketToolsContext
from ..helpers.conversation_manager import ConversationContext, ConversationState
from ..helpers import merge_user_response, generate_info_request_message


async def handle_info_response(
    user_response: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: TicketToolsContext
) -> Dict[str, Any]:
    """Handle user's response to information request."""
    from .process_create import process_create_ticket
    from .process_update import process_update_ticket
    from .process_search import process_search_tickets
    from .process_subtask import process_create_subtask
    from .process_link import process_link_issues
    from .process_issue_report import process_issue_report

    log_info(f"Handling info response. Missing fields: {len(conversation_ctx.missing_fields)}", "direct_processor")

    cancel_phrases = ["cancel", "stop", "abort", "quit", "exit", "nevermind", "never mind"]
    if any(phrase in user_response.lower() for phrase in cancel_phrases):
        conversation_ctx.state = ConversationState.COMPLETED
        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_response,
            "intent": conversation_ctx.action_type,
            "response": "\U0001f44d Got it! Operation cancelled. Is there anything else I can help you with?",
            "tickets": []
        }

    if conversation_ctx.missing_fields:
        current_field = conversation_ctx.missing_fields[0]
        conversation_ctx.collected_data = merge_user_response(
            conversation_ctx.collected_data,
            user_response,
            current_field
        )

        conversation_ctx.missing_fields.pop(0)

    if conversation_ctx.missing_fields:
        message = generate_info_request_message(conversation_ctx.missing_fields)
        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_response,
            "intent": conversation_ctx.action_type,
            "response": message,
            "missing_fields": [f.to_dict() for f in conversation_ctx.missing_fields],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    conversation_ctx.clear_missing_fields()

    original = conversation_ctx.original_intent or user_response

    if conversation_ctx.action_type == ActionType.CREATE.value:
        return await process_create_ticket(original, conversation_ctx, jira_service, ai_service, context)
    elif conversation_ctx.action_type == ActionType.UPDATE.value:
        return await process_update_ticket(original, conversation_ctx, jira_service, ai_service, context)
    elif conversation_ctx.action_type == ActionType.SEARCH.value:
        return await process_search_tickets(original, conversation_ctx, jira_service, ai_service, context)
    elif conversation_ctx.action_type == ActionType.SUBTASK.value:
        return await process_create_subtask(original, conversation_ctx, jira_service, ai_service, context)
    elif conversation_ctx.action_type == ActionType.LINK.value:
        return await process_link_issues(original, conversation_ctx, jira_service, ai_service, context)
    elif conversation_ctx.action_type == ActionType.ISSUE_REPORT.value:
        return await process_issue_report(user_response, conversation_ctx, jira_service, ai_service, context)
    else:
        return await process_search_tickets(original, conversation_ctx, jira_service, ai_service, context)
