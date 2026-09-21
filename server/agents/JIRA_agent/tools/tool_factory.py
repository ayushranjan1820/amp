"""Factory for creating LangChain tools for JIRA operations.

Enterprise improvements:
- All tools are async-native — no more nest_asyncio or make_async_sync
- Tools use LangChain's ``coroutine`` parameter exclusively
- Sync ``func`` provided as a thin wrapper via asyncio.run() for
  environments that call tools synchronously
"""
from __future__ import annotations

import asyncio
import json
from typing import List

from langchain_core.tools import Tool

from .ticket_tools import (
    TicketToolsContext,
    search_tickets_tool,
    get_details_tool,
    get_comments_tool,
    create_ticket_tool,
    update_ticket_tool,
    bulk_update_tool,
    get_last_results_tool,
    create_subtask_tool,
    link_issues_tool,
)
from .knowledge_base import (
    search_knowledge_base_tool,
    get_knowledge_stats_tool,
    query_mongodb_tool,
)


def _sync_fallback(async_func):
    """Create a sync wrapper that runs an async tool in the current event loop.

    LangChain ``Tool`` requires a sync ``func`` even when ``coroutine`` is set.
    This wrapper tries to use the running loop (via ``loop.run_until_complete``
    with nest_asyncio if available) or falls back to ``asyncio.run()``.
    """
    def wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already inside an async context — need nested execution
            try:
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(async_func(*args, **kwargs))
            except ImportError:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, async_func(*args, **kwargs)).result()
        else:
            return asyncio.run(async_func(*args, **kwargs))

    return wrapper


def create_jira_tools(jira_service, context: TicketToolsContext) -> List[Tool]:
    """Create LangChain tools for JIRA operations.

    Args:
        jira_service: JiraService instance for API calls
        context: Shared context for storing state between tool calls

    Returns:
        List of configured LangChain Tool instances
    """

    # --- Async tool closures ------------------------------------------ #

    async def _search(q: str) -> str:
        return await search_tickets_tool(jira_service, context, q)

    async def _get_details(k: str) -> str:
        return await get_details_tool(jira_service, k)

    async def _get_comments(k: str) -> str:
        return await get_comments_tool(jira_service, k)

    async def _create(j: str) -> str:
        return await create_ticket_tool(jira_service, j, context)

    async def _update(j: str) -> str:
        return await update_ticket_tool(jira_service, j, context)

    async def _bulk_update(j: str) -> str:
        return await bulk_update_tool(jira_service, context, j)

    async def _create_subtask(j: str) -> str:
        return await create_subtask_tool(jira_service, j, context)

    async def _link_issues(j: str) -> str:
        return await link_issues_tool(jira_service, j, context)

    async def _search_kb(q: str) -> str:
        return await search_knowledge_base_tool(q, context.project_id or "global", 10)

    async def _kb_stats(p: str) -> str:
        return await get_knowledge_stats_tool(context.project_id or "global")

    async def _query_mongo(input_json: str) -> str:
        try:
            params = json.loads(input_json)
            collection = params.get("collection")
            query = params.get("query", "{}")
            limit = params.get("limit", 10)
            if not collection:
                return "Error: 'collection' parameter is required"
            return await query_mongodb_tool(collection, query, limit)
        except json.JSONDecodeError as e:
            return f"Error parsing JSON input: {e}"
        except Exception as e:
            return f"Error: {e}"

    # --- Tool definitions --------------------------------------------- #

    return [
        Tool(
            name="search_jira_tickets",
            description=(
                "Search for JIRA tickets based on query criteria. "
                "Use for: finding tickets by keywords, status, priority, or labels. "
                "Input: a search query string. Examples: 'in progress tickets', 'bugs related to login'"
            ),
            func=_sync_fallback(_search),
            coroutine=_search,
        ),
        Tool(
            name="get_ticket_details",
            description=(
                "Get detailed information about a specific JIRA ticket by key. "
                "Input: the ticket key (e.g., 'PROJ-123')."
            ),
            func=_sync_fallback(_get_details),
            coroutine=_get_details,
        ),
        Tool(
            name="get_ticket_comments",
            description=(
                "Get comments on a specific JIRA ticket by key. "
                "Input: the ticket key (e.g., 'PROJ-123')."
            ),
            func=_sync_fallback(_get_comments),
            coroutine=_get_comments,
        ),
        Tool(
            name="create_jira_ticket",
            description=(
                "Create a new JIRA ticket (story, bug, or task). "
                "Input: JSON string with summary (required), description (required), "
                "issue_type (Story/Bug/Task, default: Story), priority (Low/Medium/High/Critical), labels (list). "
                'Example: {"summary": "Implement login", "description": "Add OAuth2", "issue_type": "Story"}'
            ),
            func=_sync_fallback(_create),
            coroutine=_create,
        ),
        Tool(
            name="update_jira_ticket",
            description=(
                "Update an existing JIRA ticket. "
                "Input: JSON string with ticket_key (required), and any of: "
                "summary, description, status, priority, labels, comment. "
                'Example: {"ticket_key": "PROJ-123", "status": "In Progress"}'
            ),
            func=_sync_fallback(_update),
            coroutine=_update,
        ),
        Tool(
            name="bulk_update_tickets",
            description=(
                "Update multiple JIRA tickets from the last search results. "
                "Input: JSON with fields to apply (status, priority, labels, comment). "
                f"Capped at {50} tickets per operation. "
                'Example: {"status": "Done", "comment": "Sprint cleanup"}'
            ),
            func=_sync_fallback(_bulk_update),
            coroutine=_bulk_update,
        ),
        Tool(
            name="get_last_search_results",
            description=(
                "Get tickets from the most recent search for follow-up questions or updates. "
                "No input required."
            ),
            func=lambda _: get_last_results_tool(context, _),
            coroutine=lambda _: asyncio.coroutine(lambda: get_last_results_tool(context, _))()
            if False else None,  # sync-only tool
        ),
        Tool(
            name="search_knowledge_base",
            description=(
                "Search the knowledge base for documentation, guidelines, or requirements. "
                "Input: search query string. "
                "After receiving results, synthesize into structured output — don't copy-paste raw chunks."
            ),
            func=_sync_fallback(_search_kb),
            coroutine=_search_kb,
        ),
        Tool(
            name="get_knowledge_stats",
            description=(
                "Get statistics about the knowledge base (document count, size). "
                "No input required (use 'default')."
            ),
            func=_sync_fallback(_kb_stats),
            coroutine=_kb_stats,
        ),
        Tool(
            name="query_mongodb",
            description=(
                "Query MongoDB directly with custom filters. "
                "Input: JSON with collection (required), query (JSON string), limit (default: 10). "
                "Prefer search_knowledge_base for KB searches."
            ),
            func=_sync_fallback(_query_mongo),
            coroutine=_query_mongo,
        ),
        Tool(
            name="create_subtask",
            description=(
                "Create a subtask under an existing JIRA ticket. "
                "Input: JSON with parent_key (required), summary (required), description, priority. "
                'Example: {"parent_key": "PROJ-123", "summary": "Unit tests"}'
            ),
            func=_sync_fallback(_create_subtask),
            coroutine=_create_subtask,
        ),
        Tool(
            name="link_issues",
            description=(
                "Link two JIRA issues together. "
                "Input: JSON with source_key (required), target_key (required), "
                "link_type (Relates/Blocks/Duplicates, default: Relates). "
                'Example: {"source_key": "PROJ-123", "target_key": "PROJ-456", "link_type": "Blocks"}'
            ),
            func=_sync_fallback(_link_issues),
            coroutine=_link_issues,
        ),
    ]


# Fix the get_last_search_results tool — it's sync-only, patch after creation
def _patch_last_results_tool(tools: List[Tool], context: TicketToolsContext):
    """Replace the coroutine=None stub with a proper sync func."""
    for tool in tools:
        if tool.name == "get_last_search_results":
            tool.func = lambda _: get_last_results_tool(context, _)
            tool.coroutine = None
            break
