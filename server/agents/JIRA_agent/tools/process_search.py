"""Process search ticket requests with contextual awareness and conversation memory."""
from typing import Dict, Any, Optional

from ..core.logging import log_info
from ..prompts import prompt_loader
from ..utils.prompt_utils import safe_fmt
from .ticket_tools import TicketToolsContext, search_tickets_tool
from .helpers import (
    format_tickets_for_agent,
    format_tickets_verbatim,
    is_description_fetch_request,
)
from .enrich_context import enrich_with_context
from ..helpers.conversation_manager import ConversationContext, ConversationState
from ..helpers import validate_search_query, generate_info_request_message


async def process_search_tickets(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: TicketToolsContext,
    original_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """Process search ticket request with contextual awareness and conversation memory."""
    log_info("Enriching search with KB and Jira context", "direct_processor")
    enriched_context = await enrich_with_context(user_prompt, jira_service, ai_service, context)

    conversation_history = conversation_ctx.get_conversation_history(5)
    has_previous_context = len(conversation_ctx.messages) > 2

    is_complete, missing_fields = validate_search_query(user_prompt, conversation_ctx.collected_data)

    if not is_complete:
        conversation_ctx.set_missing_fields(missing_fields)
        message = generate_info_request_message(missing_fields)

        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "search",
            "response": message,
            "missing_fields": [f.to_dict() for f in missing_fields],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    conversation_ctx.state = ConversationState.PROCESSING
    result = await search_tickets_tool(jira_service, context, user_prompt, ai_service)

    if context.last_search_results:
        if is_description_fetch_request(original_prompt or user_prompt):
            log_info(
                "Description fetch detected; returning verbatim ticket descriptions",
                "direct_processor",
            )
            response = format_tickets_verbatim(context.last_search_results)
        else:
            tickets_summary = format_tickets_for_agent(context.last_search_results)

            context_info = ""
            if enriched_context.get("has_context"):
                context_parts = []
                if enriched_context.get("jira_context"):
                    context_parts.append(f"Related: {enriched_context['jira_context']}")

                if context_parts:
                    context_info = f"\n\n{context_parts[0]}"

            history_context = ""
            if has_previous_context:
                history_context = f"\n\nConversation History:\n{conversation_history}"

            analysis_prompt = safe_fmt(
                prompt_loader.get_prompt("direct_processor.yml", "analyze_search_results"),
                user_prompt=user_prompt,
                tickets_summary=tickets_summary,
                context_info=context_info,
                history_context=history_context,
                history_note='- Reference to previous conversation context if relevant' if has_previous_context else ''
            )

            response = await ai_service.call_genai(
                prompt=analysis_prompt,
                temperature=0.3,
                max_tokens=2000,
                task_name="jira_search",
            )
    else:
        response = result

    conversation_ctx.state = ConversationState.COMPLETED

    return {
        "success": True,
        "state": conversation_ctx.state.value,
        "session_id": conversation_ctx.session_id,
        "prompt": user_prompt,
        "intent": "search",
        "response": response,
        "tickets": context.last_search_results,
        "collected_data": conversation_ctx.collected_data
    }
