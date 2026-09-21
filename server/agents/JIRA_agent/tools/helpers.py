"""Helper functions for JIRA agent operations."""
import os
import re
from typing import List, Dict, Any


_SEARCH_SUMMARY_DESCRIPTION_CHARS = int(
    os.environ.get("JIRA_SEARCH_SUMMARY_DESCRIPTION_CHARS", "0")
)

_DESCRIPTION_REQUEST_PATTERNS = (
    re.compile(r"\bdescriptions?\b", re.IGNORECASE),
    re.compile(r"\bfull\s+details?\b", re.IGNORECASE),
    re.compile(r"\bticket\s+details?\b", re.IGNORECASE),
    re.compile(r"\bdetails?\s+of\s+(all|the|each)\b", re.IGNORECASE),
    re.compile(r"\bwith\s+descriptions?\b", re.IGNORECASE),
)


def is_description_fetch_request(user_prompt: str) -> bool:
    """Return True when the user is asking for raw ticket descriptions/details.

    Used to bypass LLM summarization on multi-ticket search results so
    descriptions are returned verbatim, paired with their respective ticket.
    """
    if not user_prompt:
        return False
    return any(p.search(user_prompt) for p in _DESCRIPTION_REQUEST_PATTERNS)


def format_tickets_verbatim(tickets: List[Dict[str, Any]]) -> str:
    """Format tickets for the UI without any LLM summarization.

    Each ticket renders its raw description as-is, paired with its key.
    Tickets are separated by a horizontal rule so the UI can split cleanly.
    """
    if not tickets:
        return "No tickets found."

    blocks: List[str] = []
    for ticket in tickets:
        key = ticket.get("key", "UNKNOWN")
        summary = ticket.get("summary", "") or ""
        status = ticket.get("status", "") or ""
        priority = ticket.get("priority", "") or ""
        assignee = ticket.get("assignee") or "Unassigned"
        labels = ticket.get("labels") or []
        labels_str = ", ".join(labels) if labels else "None"
        description = (ticket.get("description") or "").strip()

        block = (
            f"**{key}**: {summary}\n"
            f"Status: {status} | Priority: {priority} | Assignee: {assignee}\n"
            f"Labels: {labels_str}\n\n"
            f"Description:\n{description if description else '(Description is empty)'}"
        )
        blocks.append(block)

    return "\n\n---\n\n".join(blocks)


def format_tickets_for_agent(tickets: List[Dict[str, Any]]) -> str:
    """Format tickets data for agent tool output.

    Args:
        tickets: List of JIRA ticket dictionaries

    Returns:
        Formatted string representation of tickets
    """
    formatted = []
    for idx, ticket in enumerate(tickets, 1):
        description = ticket.get("description") or ""
        if _SEARCH_SUMMARY_DESCRIPTION_CHARS > 0:
            rendered_description = description[:_SEARCH_SUMMARY_DESCRIPTION_CHARS]
            clipped_suffix = "..." if len(description) > _SEARCH_SUMMARY_DESCRIPTION_CHARS else ""
            rendered_description = f"{rendered_description}{clipped_suffix}"
        else:
            rendered_description = description
        formatted.append(
            f"[{ticket['key']}] {ticket['summary']}\n"
            f"Status: {ticket['status']} | Priority: {ticket['priority']}\n"
            f"Labels: {', '.join(ticket.get('labels', [])) if ticket.get('labels') else 'None'}\n"
            f"Description: {rendered_description}\n"
        )
    return '\n'.join(formatted)
