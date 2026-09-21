"""Process issue report requests.

Behavior:
- If related tickets are found, interrupt and ask user how to proceed.
- If no related tickets are found, continue directly with create flow.
"""
import json
import re
from typing import Dict, Any, Optional

from ..core.logging import log_error, log_info
from ..prompts import prompt_loader
from .ticket_tools import TicketToolsContext, search_tickets_tool, get_details_tool
from ..helpers.conversation_manager import ConversationContext, ConversationState


async def process_issue_report(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: Optional[TicketToolsContext] = None
) -> Dict[str, Any]:
    """Process issue report - search for related tickets first, then ask what to do."""
    from .process_create import process_create_ticket
    from .process_update import process_update_ticket

    log_info(f"Processing issue report: {user_prompt}", "direct_processor")

    pending_action = conversation_ctx.collected_data.get('pending_action_choice')
    if pending_action:
        return await _handle_pending_action(
            user_prompt, conversation_ctx, jira_service, ai_service, context
        )

    # Use simple replace instead of .format() — the prompt contains raw JSON
    # curly braces in its example block which confuse Python's format engine.
    extract_prompt = prompt_loader.get_prompt(
        "direct_processor.yml", "extract_search_query"
    ).replace("{message}", user_prompt)

    try:
        extracted = await ai_service.call_genai(
            prompt=extract_prompt,
            temperature=0.1,
            max_tokens=200,
            task_name="jira_ticket_extraction"
        )

        json_match = re.search(r'\{[^}]*\}', extracted, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            search_query = data.get('search_query', user_prompt)
            issue_summary = data.get('issue_summary', user_prompt)
        else:
            search_query = user_prompt
            issue_summary = user_prompt
    except Exception as e:
        log_error(f"Issue extraction failed: {e}", "direct_processor")
        search_query = user_prompt
        issue_summary = user_prompt

    conversation_ctx.collected_data['issue_description'] = issue_summary
    conversation_ctx.collected_data['original_report'] = user_prompt

    log_info(f"Searching for related tickets: {search_query}", "direct_processor")
    await search_tickets_tool(jira_service, context, search_query, ai_service)

    related_tickets = context.last_search_results if context else []

    if related_tickets:
        conversation_ctx.collected_data['pending_action_choice'] = True
        conversation_ctx.state = ConversationState.AWAITING_INFO

        tickets_list = "\n".join([
            f"- **{t.get('key')}**: {t.get('summary')} ({t.get('status')})"
            for t in related_tickets[:5]
        ])

        response = f"""I found **{len(related_tickets)}** related ticket(s) that might be relevant:

{tickets_list}

**What would you like to do?**
1. **Create a new ticket** for this issue
2. **Update an existing ticket** from the list above (add a comment or change status)
3. **View details** of a specific ticket (just tell me the ticket key)

Please let me know how you'd like to proceed."""

        return {
            "success": True,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "issue_report",
            "response": response,
            "collected_data": conversation_ctx.collected_data,
            "tickets": related_tickets[:5],
            "action_choices": ["create_new", "update_existing", "view_details"]
        }
    # No related tickets found -> continue without interrupting the flow.
    conversation_ctx.collected_data['summary'] = issue_summary
    conversation_ctx.collected_data.pop('pending_action_choice', None)
    conversation_ctx.action_type = "create"
    return await process_create_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)


async def _handle_pending_action(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context: Optional[TicketToolsContext] = None
) -> Dict[str, Any]:
    """Handle user's response to pending action choice from issue report."""
    from .process_create import process_create_ticket
    from .process_update import process_update_ticket

    response_lower = user_prompt.lower()

    if any(word in response_lower for word in ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'please', 'go ahead']):
        conversation_ctx.collected_data['summary'] = conversation_ctx.collected_data.get('issue_description', user_prompt)
        conversation_ctx.collected_data.pop('pending_action_choice', None)
        conversation_ctx.action_type = "create"
        return await process_create_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)

    elif any(word in response_lower for word in ['no', 'nope', 'cancel', 'nevermind', 'never mind']):
        conversation_ctx.collected_data.pop('pending_action_choice', None)
        conversation_ctx.state = ConversationState.COMPLETED
        return {
            "success": True,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "issue_report",
            "response": "No problem! Let me know if there's anything else I can help you with.",
            "collected_data": {},
            "tickets": []
        }

    elif any(word in response_lower for word in ['create', 'new', 'open', 'file', 'raise']):
        conversation_ctx.collected_data['summary'] = conversation_ctx.collected_data.get('issue_description', user_prompt)
        conversation_ctx.collected_data.pop('pending_action_choice', None)
        conversation_ctx.action_type = "create"
        return await process_create_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)

    elif any(word in response_lower for word in ['update', 'add', 'comment']):
        if not conversation_ctx.collected_data.get('ticket_key'):
            conversation_ctx.state = ConversationState.AWAITING_INFO
            return {
                "success": False,
                "state": conversation_ctx.state.value,
                "session_id": conversation_ctx.session_id,
                "prompt": user_prompt,
                "intent": "issue_report",
                "response": "Which ticket would you like to update? Please provide the ticket key (e.g., PROJ-123) from the list above.",
                "missing_fields": [{"field": "ticket_key", "description": "Ticket to update"}],
                "collected_data": conversation_ctx.collected_data,
                "tickets": context.last_search_results if context else []
            }
        conversation_ctx.collected_data.pop('pending_action_choice', None)
        conversation_ctx.action_type = "update"
        return await process_update_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)

    elif any(word in response_lower for word in ['view', 'details', 'show', 'see']):
        ticket_match = re.search(r'\b([A-Z]{2,10}-\d+)\b', user_prompt)
        if ticket_match:
            ticket_key = ticket_match.group(1)
            conversation_ctx.collected_data.pop('pending_action_choice', None)
            conversation_ctx.state = ConversationState.COMPLETED
            result = await get_details_tool(jira_service, ticket_key)
            return {
                "success": True,
                "state": conversation_ctx.state.value,
                "session_id": conversation_ctx.session_id,
                "prompt": user_prompt,
                "intent": "get_details",
                "response": result,
                "collected_data": conversation_ctx.collected_data,
                "tickets": []
            }
        else:
            conversation_ctx.state = ConversationState.AWAITING_INFO
            return {
                "success": False,
                "state": conversation_ctx.state.value,
                "session_id": conversation_ctx.session_id,
                "prompt": user_prompt,
                "intent": "issue_report",
                "response": "Which ticket would you like to view? Please provide the ticket key (e.g., PROJ-123).",
                "missing_fields": [{"field": "ticket_key", "description": "Ticket to view"}],
                "collected_data": conversation_ctx.collected_data,
                "tickets": context.last_search_results if context else []
            }

    elif re.search(r'\b([A-Z]{2,10}-\d+)\b', user_prompt):
        ticket_key = re.search(r'\b([A-Z]{2,10}-\d+)\b', user_prompt).group(1)
        conversation_ctx.collected_data['ticket_key'] = ticket_key
        conversation_ctx.collected_data.pop('pending_action_choice', None)
        conversation_ctx.state = ConversationState.COMPLETED
        result = await get_details_tool(jira_service, ticket_key)
        return {
            "success": True,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "get_details",
            "response": result,
            "collected_data": conversation_ctx.collected_data,
            "tickets": []
        }

    conversation_ctx.collected_data['summary'] = conversation_ctx.collected_data.get('issue_description', user_prompt)
    conversation_ctx.collected_data.pop('pending_action_choice', None)
    conversation_ctx.action_type = "create"
    return await process_create_ticket(user_prompt, conversation_ctx, jira_service, ai_service, context)
