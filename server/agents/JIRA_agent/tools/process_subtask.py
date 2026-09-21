"""Process subtask creation requests."""
import json
import re
from typing import Dict, Any, Optional

from ..core.logging import log_info
from .ticket_tools import TicketToolsContext, create_subtask_tool
from ..helpers.conversation_manager import ConversationContext, ConversationState, InfoRequest


async def process_create_subtask(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: Optional[TicketToolsContext] = None
) -> Dict[str, Any]:
    """Process subtask creation request."""
    parent_key = conversation_ctx.collected_data.get('parent_key')
    if not parent_key:
        ticket_match = re.search(r'\b([A-Z]{2,10}-\d+)\b', user_prompt)
        if ticket_match:
            parent_key = ticket_match.group(1)
            conversation_ctx.collected_data['parent_key'] = parent_key

    summary = conversation_ctx.collected_data.get('summary')
    description = conversation_ctx.collected_data.get('description', '')

    if not parent_key:
        missing = [InfoRequest(field="parent_key", description="Parent ticket key")]
        conversation_ctx.set_missing_fields(missing)
        conversation_ctx.state = ConversationState.AWAITING_INFO
        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "subtask",
            "response": "I need to know which ticket to create the subtask under. Please provide the parent ticket key (e.g., PROJ-123).",
            "missing_fields": [f.to_dict() for f in missing],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    if not summary:
        missing = [InfoRequest(field="summary", description="Subtask summary")]
        conversation_ctx.set_missing_fields(missing)
        conversation_ctx.state = ConversationState.AWAITING_INFO
        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "subtask",
            "response": f"What should the subtask under **{parent_key}** be about? Please provide a summary.",
            "missing_fields": [f.to_dict() for f in missing],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    log_info(f"Creating subtask under {parent_key}: {summary}", "direct_processor")

    subtask_data = {
        "parent_key": parent_key,
        "summary": summary,
        "description": description,
        "priority": conversation_ctx.collected_data.get('priority', 'Medium')
    }

    conversation_ctx.state = ConversationState.PROCESSING
    result = await create_subtask_tool(jira_service, json.dumps(subtask_data))
    conversation_ctx.state = ConversationState.COMPLETED

    return {
        "success": "Failed" not in result,
        "state": conversation_ctx.state.value,
        "session_id": conversation_ctx.session_id,
        "prompt": user_prompt,
        "intent": "subtask",
        "response": result,
        "collected_data": conversation_ctx.collected_data,
        "tickets": []
    }
