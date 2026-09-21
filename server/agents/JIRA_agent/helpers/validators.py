"""Validation functions for JIRA ticket data completeness."""
from typing import Dict, Any, List, Optional

from .conversation_manager import InfoRequest
from .codebase_context import has_verbatim_codebase_context, missing_required_sections


def validate_create_ticket_data(
    user_prompt: str,
    collected_data: Dict[str, Any],
    context_data: Optional[Dict[str, Any]] = None
) -> tuple[bool, List[InfoRequest]]:
    """Validate if we have all necessary information to create a ticket.
    Ask for information ONE field at a time for better UX.
    """
    missing = []

    if not collected_data.get("issue_type"):
        missing.append(InfoRequest(
            field="issue_type",
            description="What type of ticket would you like to create?",
            options=["Bug", "Story", "Task", "Epic"]
        ))
        return False, missing

    if not collected_data.get("summary") or len(collected_data.get("summary", "").strip()) < 5:
        missing.append(InfoRequest(
            field="summary",
            description="Great! Now, what's a brief summary or title for this ticket?\n(Example: 'Fix login button not responding on mobile')"
        ))
        return False, missing

    if not collected_data.get("description") or len(collected_data.get("description", "").strip()) < 10:
        missing.append(InfoRequest(
            field="description",
            description="Perfect! Can you provide more details about this? What's happening, steps to reproduce, or expected behavior?"
        ))
        return False, missing

    if context_data and context_data.get("require_codebase_sections"):
        required_missing = missing_required_sections(collected_data.get("description", ""))
        if required_missing:
            missing.append(InfoRequest(
                field="description_sections",
                description=(
                    "For MCP-based JIRA creation, the description must include these sections "
                    f"derived from codebase_context: {', '.join(required_missing)}."
                ),
            ))
            return False, missing

        codebase_context = str(context_data.get("codebase_context") or "")
        if codebase_context and not has_verbatim_codebase_context(
            collected_data.get("description", ""),
            codebase_context,
        ):
            missing.append(InfoRequest(
                field="description_context",
                description=(
                    "For MCP-based JIRA creation, the description must include the full codebase_context "
                    "verbatim in a formatted section."
                ),
            ))
            return False, missing

    if not collected_data.get("priority"):
        missing.append(InfoRequest(
            field="priority",
            description="How urgent is this?",
            options=["Critical", "High", "Medium", "Low"]
        ))
        return False, missing

    if not collected_data.get("additional_context_asked"):
        missing.append(InfoRequest(
            field="additional_context",
            description="Any additional information? (Team, affected users, related tickets, etc.)\n\nType 'none' or 'skip' if not applicable."
        ))
        collected_data["additional_context_asked"] = True
        return False, missing

    if not collected_data.get("confirmed"):
        summary_msg = f"""📋 **Ready to create ticket:**

**Type:** {collected_data.get('issue_type')}
**Summary:** {collected_data.get('summary')}
**Description:** {collected_data.get('description')}
**Priority:** {collected_data.get('priority')}
{f"**Additional Info:** {collected_data.get('additional_context')}" if collected_data.get('additional_context') and collected_data.get('additional_context').lower() not in ['none', 'skip', 'n/a'] else ''}

Shall I create this ticket? (yes/no)"""

        missing.append(InfoRequest(
            field="confirmed",
            description=summary_msg,
            options=["yes", "no"]
        ))
        return False, missing

    if collected_data.get("confirmed", "").lower() not in ["yes", "y", "confirm", "ok", "sure"]:
        return False, [InfoRequest(
            field="cancelled",
            description="Ticket creation cancelled. Is there anything else I can help you with?"
        )]

    return True, []


def validate_update_ticket_data(user_prompt: str, collected_data: Dict[str, Any]) -> tuple[bool, List[InfoRequest]]:
    """Validate if we have all necessary information to update a ticket."""
    missing = []

    if not collected_data.get("ticket_key"):
        missing.append(InfoRequest(
            field="ticket_key",
            description="Please provide the ticket ID (e.g., PROJ-123)"
        ))

    has_update = any([
        collected_data.get("status"),
        collected_data.get("priority"),
        collected_data.get("summary"),
        collected_data.get("description"),
        collected_data.get("comment")
    ])

    if not has_update:
        missing.append(InfoRequest(
            field="update_type",
            description="What would you like to update?",
            options=["Status", "Priority", "Description", "Add Comment"]
        ))

    return len(missing) == 0, missing


def validate_search_query(user_prompt: str, collected_data: Dict[str, Any]) -> tuple[bool, List[InfoRequest]]:
    """Validate if search query is specific enough."""
    missing = []

    vague_terms = ["tickets", "issues", "all", "show", "find", "search"]
    words = user_prompt.lower().split()

    if len(words) <= 2 and any(term in words for term in vague_terms):
        missing.append(InfoRequest(
            field="search_criteria",
            description="Please be more specific. What tickets are you looking for? (e.g., 'in progress', 'assigned to me', 'high priority bugs')"
        ))

    return len(missing) == 0, missing
