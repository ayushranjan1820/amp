"""Tool wrapper functions for JIRA ticket operations.

Enterprise improvements:
- Removed nest_asyncio — all tools are async-native
- Bulk operations are bounded (max items, concurrent limit)
- RBAC guard checks before write operations
- Cleaner separation of async tool functions
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import List, Dict, Any, Optional


_TICKET_KEY_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")

from ..core.config import get_settings
from ..core.logging import log_info, log_error, log_warning
from ..helpers.codebase_context import has_verbatim_codebase_context, missing_required_sections
from .search import search_jira_tickets, search_with_jql
from .jira_operations import (
    create_jira_issue,
    update_jira_issue,
    get_ticket_details,
    get_ticket_comments,
    create_subtask,
    link_issues,
)


# ------------------------------------------------------------------ #
# Shared context
# ------------------------------------------------------------------ #

class TicketToolsContext:
    """Shared state for tool calls within a single request."""

    def __init__(self, project_id: str = "global"):
        self.last_search_results: List[Dict[str, Any]] = []
        self.project_id: str = project_id
        self.user_id: Optional[str] = None
        self.user_role: Optional[str] = None


# ------------------------------------------------------------------ #
# Bulk operation limits
# ------------------------------------------------------------------ #

BULK_MAX_ITEMS = 50          # hard cap on tickets in one bulk operation
BULK_CONCURRENCY = 5         # max parallel JIRA API calls during bulk ops


# ------------------------------------------------------------------ #
# RBAC guard
# ------------------------------------------------------------------ #

_WRITE_ACTIONS = {"create", "update", "bulk_update", "subtask", "link"}


def _check_rbac(context: TicketToolsContext, action: str) -> Optional[str]:
    """Return an error message if the user lacks permission, else ``None``."""
    settings = get_settings()
    if not settings.rbac_enabled:
        return None

    role = (context.user_role or "viewer").lower()
    if action in _WRITE_ACTIONS and role in ("viewer", "readonly"):
        log_warning(
            f"RBAC denied: user={context.user_id} role={role} action={action}",
            "rbac",
        )
        return (
            f"Permission denied: your role ({role}) does not allow "
            f"write operations. Contact your JIRA administrator."
        )
    return None


# ------------------------------------------------------------------ #
# Tool functions (all async)
# ------------------------------------------------------------------ #

async def search_tickets_tool(
    jira_service,
    context: TicketToolsContext,
    query: str,
    ai_service=None,
) -> str:
    """Search for JIRA tickets using LLM-generated JQL."""
    try:
        log_info(f"Searching tickets: {query}", "ticket_tools")

        if ai_service:
            project_key = getattr(jira_service.settings, "jira_project_key", None)
            tickets = await search_with_jql(jira_service, ai_service, query, project_key)
        else:
            tickets = await search_jira_tickets(jira_service, query)

        # Empty-result fallback: if the query contains explicit ticket keys
        # but the JQL/keyword search returned nothing, retry with a direct
        # ``key in (...)`` lookup. This recovers from cases where the LLM
        # misclassified the keys as summary text.
        if not tickets:
            seen: set = set()
            keys_in_query = [
                k for k in _TICKET_KEY_RE.findall(query)
                if not (k in seen or seen.add(k))
            ]
            if keys_in_query:
                log_info(
                    f"No results; retrying as key lookup for {keys_in_query}",
                    "ticket_tools",
                )
                try:
                    key_list = ", ".join(keys_in_query)
                    jql = f"key in ({key_list})"
                    tickets = await jira_service.search_with_jql(jql, max_results=len(keys_in_query))
                except Exception as e:
                    log_error(f"Key fallback failed: {e}", "ticket_tools", e)

        context.last_search_results = tickets

        if not tickets:
            return (
                "No JIRA issues matched this request. Your message is used as search "
                f'criteria (e.g. keywords / JQL), not as an exact ticket title. Request: "{query}"'
            )

        result = f"Found {len(tickets)} ticket(s):\n\n"
        for ticket in tickets:
            result += f"- **{ticket.get('key')}**: {ticket.get('summary')}\n"
            result += f"  Type: {ticket.get('issueType', 'Unknown')} | Status: {ticket.get('status')} | Priority: {ticket.get('priority')}\n"
            if ticket.get("assignee"):
                result += f"  Assignee: {ticket['assignee']}\n"
            if ticket.get("labels"):
                result += f"  Labels: {', '.join(ticket['labels'])}\n"
            if ticket.get("components"):
                result += f"  Components: {', '.join(ticket['components'])}\n"
            result += "\n"

        return result

    except Exception as e:
        log_error(f"Search error: {e}", "ticket_tools", e)
        return f"Error searching tickets: {str(e)}"


async def get_details_tool(jira_service, ticket_key: str) -> str:
    """Get details for a specific ticket (direct API call)."""
    try:
        return await get_ticket_details(jira_service, ticket_key)
    except Exception as e:
        log_error(f"Get details error: {e}", "ticket_tools", e)
        return f"Error getting ticket details: {str(e)}"


async def get_details_multi_tool(jira_service, ticket_keys: List[str]) -> str:
    """Fetch details for multiple tickets concurrently and concatenate.

    Falls back gracefully on individual failures so one bad key doesn't
    break the entire response. Bounded by ``BULK_CONCURRENCY``.
    """
    keys = [k.strip().upper() for k in ticket_keys if k and k.strip()]
    # Deduplicate, preserve order
    seen = set()
    keys = [k for k in keys if not (k in seen or seen.add(k))]
    if not keys:
        return "No ticket keys provided."

    if len(keys) == 1:
        return await get_details_tool(jira_service, keys[0])

    sem = asyncio.Semaphore(BULK_CONCURRENCY)

    async def _one(key: str) -> str:
        async with sem:
            try:
                return await get_ticket_details(jira_service, key)
            except Exception as e:
                log_error(f"Get details error for {key}: {e}", "ticket_tools", e)
                return f"Error fetching {key}: {str(e)}"

    results = await asyncio.gather(*(_one(k) for k in keys))
    return "\n\n---\n\n".join(results)


async def get_comments_tool(jira_service, ticket_key: str) -> str:
    """Get comments for a specific ticket (direct API call)."""
    try:
        return await get_ticket_comments(jira_service, ticket_key)
    except Exception as e:
        log_error(f"Get comments error: {e}", "ticket_tools", e)
        return f"Error getting ticket comments: {str(e)}"


async def create_ticket_tool(jira_service, input_json: str, context: Optional[TicketToolsContext] = None) -> str:
    """Create a new JIRA ticket with RBAC check."""
    if context:
        denied = _check_rbac(context, "create")
        if denied:
            return denied

    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json

        summary = data.get("summary")
        if not summary:
            return "Error: 'summary' is required to create a ticket"

        codebase_context = str(data.get("codebase_context") or "")
        if codebase_context.strip():
            missing_sections = missing_required_sections(data.get("description", ""))
            if missing_sections:
                return (
                    "Error: description is missing mandatory sections for MCP codebase-context ticket creation: "
                    + ", ".join(missing_sections)
                )
            if not has_verbatim_codebase_context(data.get("description", ""), codebase_context):
                return (
                    "Error: description must include the full codebase_context verbatim in a formatted section "
                    "for MCP codebase-context ticket creation"
                )

        log_info(f"Creating ticket: {summary}", "ticket_tools")
        return await create_jira_issue(
            jira_service=jira_service,
            summary=summary,
            description=data.get("description", ""),
            issue_type=data.get("issue_type", "Story"),
            priority=data.get("priority", "Medium"),
            labels=data.get("labels", []),
        )
    except json.JSONDecodeError as e:
        return f"Error parsing input JSON: {e}. Please provide valid JSON."
    except Exception as e:
        log_error(f"Create ticket error: {e}", "ticket_tools", e)
        return f"Error creating ticket: {str(e)}"


async def update_ticket_tool(jira_service, input_json: str, context: Optional[TicketToolsContext] = None) -> str:
    """Update an existing JIRA ticket with RBAC check."""
    if context:
        denied = _check_rbac(context, "update")
        if denied:
            return denied

    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json

        ticket_key = data.get("ticket_key")
        if not ticket_key:
            return "Error: 'ticket_key' is required to update a ticket"

        ticket_key = ticket_key.strip().upper()
        log_info(f"Updating ticket: {ticket_key}", "ticket_tools")

        update_fields: Dict[str, Any] = {}
        for field in ("summary", "description", "priority", "labels"):
            if data.get(field):
                update_fields[field] = data[field]

        return await update_jira_issue(
            jira_service=jira_service,
            ticket_key=ticket_key,
            fields=update_fields,
            status=data.get("status"),
            comment=data.get("comment"),
        )
    except json.JSONDecodeError as e:
        return f"Error parsing input JSON: {e}. Please provide valid JSON."
    except Exception as e:
        log_error(f"Update ticket error: {e}", "ticket_tools", e)
        return f"Error updating ticket: {str(e)}"


async def bulk_update_tool(
    jira_service,
    context: TicketToolsContext,
    input_json: str,
) -> str:
    """Update multiple tickets from last search results.

    Enterprise improvements:
    - Capped at BULK_MAX_ITEMS to prevent runaway updates
    - Concurrent execution with bounded parallelism
    - Reports partial failures without aborting
    """
    denied = _check_rbac(context, "bulk_update")
    if denied:
        return denied

    if not context.last_search_results:
        return "No previous search results. Please search for tickets first."

    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json
    except json.JSONDecodeError as e:
        return f"Error parsing input JSON: {e}. Please provide valid JSON."

    tickets = context.last_search_results
    if len(tickets) > BULK_MAX_ITEMS:
        return (
            f"Bulk update capped at {BULK_MAX_ITEMS} tickets. "
            f"Your search returned {len(tickets)}. Please narrow your search first."
        )

    log_info(f"Bulk updating {len(tickets)} tickets (concurrency={BULK_CONCURRENCY})", "ticket_tools")

    semaphore = asyncio.Semaphore(BULK_CONCURRENCY)
    results: List[str] = []

    async def _update_one(ticket: Dict[str, Any]) -> str:
        key = ticket.get("key", "UNKNOWN")
        async with semaphore:
            try:
                update_data = {"ticket_key": key, **data}
                result = await update_ticket_tool(jira_service, json.dumps(update_data))
                return f"{key}: Updated successfully" if "failed" not in result.lower() else f"{key}: {result}"
            except Exception as e:
                return f"{key}: {e}"

    results = await asyncio.gather(*[_update_one(t) for t in tickets])
    return "Bulk update completed:\n" + "\n".join(results)


def get_last_results_tool(context: TicketToolsContext, _: str = "") -> str:
    """Get the last search results."""
    if not context.last_search_results:
        return "No previous search results available."

    result = f"Last search found {len(context.last_search_results)} ticket(s):\n\n"
    for ticket in context.last_search_results:
        result += f"- **{ticket.get('key')}**: {ticket.get('summary')} ({ticket.get('status')})\n"
    return result


async def create_subtask_tool(jira_service, input_json: str, context: Optional[TicketToolsContext] = None) -> str:
    """Create a subtask under an existing JIRA ticket with RBAC check."""
    if context:
        denied = _check_rbac(context, "subtask")
        if denied:
            return denied

    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json

        parent_key = data.get("parent_key")
        summary = data.get("summary")
        if not parent_key:
            return "Error: 'parent_key' is required to create a subtask"
        if not summary:
            return "Error: 'summary' is required to create a subtask"

        log_info(f"Creating subtask under {parent_key}: {summary}", "ticket_tools")
        return await create_subtask(
            jira_service=jira_service,
            parent_key=parent_key,
            summary=summary,
            description=data.get("description", ""),
            priority=data.get("priority", "Medium"),
        )
    except json.JSONDecodeError as e:
        return f"Error parsing input JSON: {e}. Please provide valid JSON."
    except Exception as e:
        log_error(f"Create subtask error: {e}", "ticket_tools", e)
        return f"Error creating subtask: {str(e)}"


async def link_issues_tool(jira_service, input_json: str, context: Optional[TicketToolsContext] = None) -> str:
    """Link two JIRA issues together with RBAC check."""
    if context:
        denied = _check_rbac(context, "link")
        if denied:
            return denied

    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json

        source_key = data.get("source_key")
        target_key = data.get("target_key")
        if not source_key:
            return "Error: 'source_key' is required to link issues"
        if not target_key:
            return "Error: 'target_key' is required to link issues"

        log_info(f"Linking {source_key} to {target_key}", "ticket_tools")
        return await link_issues(
            jira_service=jira_service,
            source_key=source_key,
            target_key=target_key,
            link_type=data.get("link_type", "Relates"),
        )
    except json.JSONDecodeError as e:
        return f"Error parsing input JSON: {e}. Please provide valid JSON."
    except Exception as e:
        log_error(f"Link issues error: {e}", "ticket_tools", e)
        return f"Error linking issues: {str(e)}"
