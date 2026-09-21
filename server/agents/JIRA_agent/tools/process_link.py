"""Process issue linking requests."""
import json
import re
from typing import Dict, Any, Optional

from ..core.logging import log_info
from .ticket_tools import TicketToolsContext, link_issues_tool
from ..helpers.conversation_manager import ConversationContext, ConversationState, InfoRequest


async def process_link_issues(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: Optional[TicketToolsContext] = None
) -> Dict[str, Any]:
    """Process issue linking request."""
    ticket_keys = re.findall(r'\b([A-Z]{2,10}-\d+)\b', user_prompt)

    source_key = conversation_ctx.collected_data.get('source_key')
    target_key = conversation_ctx.collected_data.get('target_key')

    if len(ticket_keys) >= 2 and not source_key and not target_key:
        source_key = ticket_keys[0]
        target_key = ticket_keys[1]
        conversation_ctx.collected_data['source_key'] = source_key
        conversation_ctx.collected_data['target_key'] = target_key
    elif len(ticket_keys) == 1:
        if not source_key:
            source_key = ticket_keys[0]
            conversation_ctx.collected_data['source_key'] = source_key
        elif not target_key:
            target_key = ticket_keys[0]
            conversation_ctx.collected_data['target_key'] = target_key

    link_type = conversation_ctx.collected_data.get('link_type', 'Relates')
    prompt_lower = user_prompt.lower()
    if 'block' in prompt_lower:
        link_type = 'Blocks'
    elif 'duplicate' in prompt_lower:
        link_type = 'Duplicate'
    elif 'relate' in prompt_lower:
        link_type = 'Relates'

    conversation_ctx.collected_data['link_type'] = link_type

    if not source_key:
        missing = [InfoRequest(field="source_key", description="Source ticket key")]
        conversation_ctx.set_missing_fields(missing)
        conversation_ctx.state = ConversationState.AWAITING_INFO
        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "link",
            "response": "Which ticket would you like to link from? Please provide the source ticket key (e.g., PROJ-123).",
            "missing_fields": [f.to_dict() for f in missing],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    if not target_key:
        missing = [InfoRequest(field="target_key", description="Target ticket key")]
        conversation_ctx.set_missing_fields(missing)
        conversation_ctx.state = ConversationState.AWAITING_INFO
        return {
            "success": False,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "link",
            "response": f"Which ticket would you like to link **{source_key}** to? Please provide the target ticket key.",
            "missing_fields": [f.to_dict() for f in missing],
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    log_info(f"Linking {source_key} to {target_key} ({link_type})", "direct_processor")

    link_data = {
        "source_key": source_key,
        "target_key": target_key,
        "link_type": link_type
    }

    conversation_ctx.state = ConversationState.PROCESSING
    result = await link_issues_tool(jira_service, json.dumps(link_data))
    conversation_ctx.state = ConversationState.COMPLETED

    return {
        "success": "Failed" not in result,
        "state": conversation_ctx.state.value,
        "session_id": conversation_ctx.session_id,
        "prompt": user_prompt,
        "intent": "link",
        "response": result,
        "collected_data": conversation_ctx.collected_data,
        "tickets": []
    }
