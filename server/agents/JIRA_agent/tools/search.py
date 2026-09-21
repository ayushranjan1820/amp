"""Search logic for JIRA tickets.

Enterprise improvements:
- JQL-based search is the primary (and only scalable) path
- Keyword fallback now uses server-side JQL ``text ~`` instead of
  fetching all issues and scoring in memory
- Pagination support for large result sets
- Removed the fetch-all-then-score anti-pattern that capped at 100 issues
"""
from __future__ import annotations

import re
from typing import List, Dict, Any, Optional

from ..core.logging import log_info, log_error, log_debug
from ..prompts import prompt_loader
from ..utils.prompt_utils import safe_fmt


_TICKET_KEY_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")


async def rewrite_user_query(
    ai_service,
    user_prompt: str,
) -> str:
    """Rewrite a natural language query into proper JIRA terminology.

    Fixes typos, normalizes status/type/priority names, and makes the
    query more precise for downstream JQL generation or keyword search.
    Returns the original prompt unchanged if rewriting fails.

    Skips rewriting entirely when explicit ticket keys are present —
    keys are exact identifiers and must not be paraphrased into
    summary/text searches.
    """
    if _TICKET_KEY_RE.search(user_prompt):
        log_info("Ticket keys present; skipping query rewrite", "query_rewriter")
        return user_prompt

    try:
        log_info(f"Rewriting user query: {user_prompt}", "query_rewriter")

        prompt = safe_fmt(
            prompt_loader.get_prompt("tools.yml", "query_rewriter"),
            user_prompt=user_prompt,
        )

        rewritten = await ai_service.call_genai(
            prompt=prompt,
            temperature=0.1,
            max_tokens=300,
            task_name="jira_query_rewrite",
        )

        rewritten = rewritten.strip().strip('"').strip("'")
        if not rewritten or len(rewritten) < 3:
            log_info("Query rewriter returned empty result, using original", "query_rewriter")
            return user_prompt

        log_info(f"Rewritten query: {rewritten}", "query_rewriter")
        return rewritten

    except Exception as e:
        log_error(f"Query rewriting failed: {e}", "query_rewriter", e)
        return user_prompt


async def generate_jql_from_query(
    ai_service,
    query: str,
    project_key: Optional[str] = None,
) -> Optional[str]:
    """Use LLM to generate JQL from a natural language query.

    Returns a JQL string or ``None`` if generation fails.
    """
    try:
        log_info(f"Generating JQL for: {query}", "jql_generator")

        prompt = safe_fmt(
            prompt_loader.get_prompt("tools.yml", "jql_generation"),
            user_prompt=query,
        )

        jql = await ai_service.call_genai(
            prompt=prompt,
            temperature=0.1,
            max_tokens=200,
            task_name="jira_search",
        )

        # Clean common LLM artifacts from the response
        jql = jql.strip()
        # Remove markdown code fences
        if jql.startswith("```"):
            jql = jql.split("\n", 1)[-1] if "\n" in jql else jql[3:]
        if jql.endswith("```"):
            jql = jql[:-3]
        jql = jql.strip().strip("`")
        # Remove JQL: prefix
        if jql.lower().startswith("jql:"):
            jql = jql[4:].strip()
        # Only unwrap a single matching pair of wrapping quotes
        # Do NOT use .strip('"') — it corrupts JQL values like status = "In Progress"
        if len(jql) >= 2 and jql[0] in ('"', "'") and jql[0] == jql[-1]:
            jql = jql[1:-1].strip()

        # Add project filter if needed
        if project_key and "project" not in jql.lower():
            if "order by" in jql.lower():
                order_idx = jql.lower().index("order by")
                query_part = jql[:order_idx].strip()
                order_part = jql[order_idx:].strip()
                jql = f"project = {project_key} AND ({query_part}) {order_part}"
            else:
                jql = f"project = {project_key} AND ({jql})"

        log_info(f"Generated JQL: {jql}", "jql_generator")
        return jql

    except Exception as e:
        log_error(f"JQL generation failed: {e}", "jql_generator", e)
        return None


async def search_with_jql(
    jira_service,
    ai_service,
    query: str,
    project_key: Optional[str] = None,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Search JIRA using LLM-generated JQL, with keyword fallback.

    The fallback now uses server-side ``text ~ "…"`` JQL instead of
    fetching every issue and scoring locally.
    """
    try:
        jql = await generate_jql_from_query(ai_service, query, project_key)

        if not jql:
            log_info("JQL generation failed, falling back to keyword JQL search", "search")
            return await search_jira_tickets(jira_service, query, max_results=max_results)

        try:
            tickets = await jira_service.search_with_jql(jql, max_results=max_results)
            log_info(f"JQL search returned {len(tickets)} results", "search")
            return tickets
        except Exception as jql_error:
            log_error(f"JQL execution failed: {jql_error}, falling back to keyword search", "search")
            return await search_jira_tickets(jira_service, query, max_results=max_results)

    except Exception as e:
        log_error(f"Search error: {e}", "search", e)
        return await search_jira_tickets(jira_service, query, max_results=max_results)


async def search_jira_tickets(
    jira_service,
    query: str,
    max_results: int = 50,
) -> List[Dict[str, Any]]:
    """Keyword-based JIRA search using server-side JQL ``text ~`` operator.

    This replaces the old approach that fetched **all** project issues into
    memory and scored them locally.  The ``text`` pseudo-field in JQL searches
    across summary, description, comments, and environment fields server-side,
    which is both faster and scales to large projects.
    """
    try:
        log_info(f"Keyword JQL search: {query}", "search")

        project_key = getattr(jira_service.settings, "jira_project_key", None)
        jql_parts: list[str] = []

        if project_key:
            jql_parts.append(f"project = {project_key}")

        # Detect explicit filters from keywords
        query_lower = query.lower()
        issue_type = _detect_issue_type(query_lower)
        status = _detect_status(query_lower)

        if issue_type:
            jql_parts.append(f'issuetype = "{issue_type}"')
            log_debug(f"Detected issue type filter: {issue_type}", "search")

        if status:
            jql_parts.append(f'status = "{status}"')
            log_debug(f"Detected status filter: {status}", "search")

        # Strip known filter words from the free-text portion
        free_text = _strip_filter_keywords(query)
        if free_text:
            # JIRA ``text`` field does a full-text search across summary,
            # description, comments, and environment.
            escaped = free_text.replace('"', '\\"')
            jql_parts.append(f'text ~ "{escaped}"')

        jql = " AND ".join(jql_parts) + " ORDER BY created DESC" if jql_parts else "ORDER BY created DESC"

        log_debug(f"Keyword JQL: {jql}", "search")
        return await jira_service.search_with_jql(jql, max_results=max_results)

    except Exception as e:
        log_error(f"Error in keyword JQL search", "search", e)
        return []


# ------------------------------------------------------------------ #
# Keyword detection helpers
# ------------------------------------------------------------------ #

_ISSUE_TYPE_MAP: Dict[str, str] = {
    "bug": "Bug",
    "bugs": "Bug",
    "story": "Story",
    "stories": "Story",
    "task": "Task",
    "tasks": "Task",
    "sub-task": "Sub-task",
    "subtask": "Sub-task",
    "epic": "Epic",
}

_STATUS_MAP: Dict[str, str] = {
    "in progress": "In Progress",
    "in-progress": "In Progress",
    "progress": "In Progress",
    "todo": "To Do",
    "to do": "To Do",
    "done": "Done",
    "completed": "Done",
    "finished": "Done",
    "review": "In Review",
    "in review": "In Review",
    "blocked": "Blocked",
    "backlog": "Backlog",
}

# Words that map to filters and should be stripped from free-text search
_FILTER_WORDS = set(_ISSUE_TYPE_MAP.keys()) | {
    "in progress", "in-progress", "todo", "to do", "done",
    "completed", "finished", "review", "in review", "blocked", "backlog",
    "tickets", "issues", "jira", "show", "list", "find", "search",
    "get", "give", "me", "all", "the", "my",
}


def _detect_issue_type(query_lower: str) -> Optional[str]:
    for kw, it in _ISSUE_TYPE_MAP.items():
        if kw in query_lower:
            return it
    return None


def _detect_status(query_lower: str) -> Optional[str]:
    for kw, st in _STATUS_MAP.items():
        if kw in query_lower:
            return st
    return None


def _strip_filter_keywords(query: str) -> str:
    """Remove known filter words so the remaining text can be used as free-text search."""
    words = query.split()
    kept = [w for w in words if w.lower() not in _FILTER_WORDS]
    return " ".join(kept).strip()
