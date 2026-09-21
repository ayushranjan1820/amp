"""JIRA API operations for creating and updating tickets.

Enterprise improvements:
- All HTTP calls go through JiraService (shared client, retry, circuit breaker)
- Centralised priority mapping (single source of truth)
- No duplicated auth header computation
- Direct ``GET /issue/{key}`` for ticket details (not fetch-all-then-filter)
"""
from __future__ import annotations

import os
from typing import Dict, Any, List, Optional

from ..core.logging import log_info, log_error
from ..services.jira_service import JiraApiError

# ------------------------------------------------------------------ #
# Shared priority mapping — single source of truth
# ------------------------------------------------------------------ #

PRIORITY_MAP: Dict[str, str] = {
    "critical": "Highest",
    "highest": "Highest",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "lowest": "Lowest",
}


def map_priority(priority: str) -> str:
    """Normalise a user-supplied priority to a JIRA-compatible name."""
    return PRIORITY_MAP.get(priority.lower(), priority)


# Subtask type names vary across JIRA project configurations
SUBTASK_TYPE_NAMES = ("Subtask", "Sub-task", "Sub Task", "subtask")

# Preview limits for read responses surfaced by MCP/UI.
_DETAIL_DESCRIPTION_PREVIEW_CHARS = int(os.environ.get("JIRA_DETAIL_DESCRIPTION_PREVIEW_CHARS", "4000"))
_COMMENT_PREVIEW_CHARS = int(os.environ.get("JIRA_COMMENT_PREVIEW_CHARS", "4000"))


def _preview_text(value: str, limit: int) -> str:
    """Return a clipped preview with an explicit truncation marker."""
    if len(value) <= limit:
        return value
    return value[:limit] + "\n... [truncated]"


# ------------------------------------------------------------------ #
# Operations
# ------------------------------------------------------------------ #

async def create_jira_issue(
    jira_service,
    summary: str,
    description: str,
    issue_type: str = "Story",
    priority: str = "Medium",
    labels: Optional[List[str]] = None,
) -> str:
    """Create a JIRA issue.

    Args:
        jira_service: JiraService instance (owns the shared HTTP client)
        summary: Ticket summary / title
        description: Ticket description (supports markdown → ADF)
        issue_type: Issue type (Story, Bug, Task)
        priority: Priority level
        labels: List of labels

    Returns:
        Human-readable success / failure message
    """
    settings = jira_service.settings
    adf_description = markdown_to_adf(description)
    mapped_priority = map_priority(priority)

    issue_data: Dict[str, Any] = {
        "fields": {
            "project": {"key": settings.jira_project_key},
            "summary": summary,
            "description": adf_description,
            "issuetype": {"name": issue_type},
            "labels": labels or [],
            "priority": {"name": mapped_priority},
        }
    }

    log_info(f"Setting priority: {priority} -> {mapped_priority}", "jira_operations")

    try:
        data = await jira_service.create_issue(issue_data)
        ticket_key = data.get("key")
        return f"Successfully created ticket **{ticket_key}**: {summary}"
    except JiraApiError as exc:
        log_error(f"JIRA create error: {exc.detail}", "jira_operations")
        return f"Failed to create ticket: {exc.status_code} - {exc.detail}"


async def update_jira_issue(
    jira_service,
    ticket_key: str,
    fields: Optional[Dict[str, Any]] = None,
    status: Optional[str] = None,
    comment: Optional[str] = None,
) -> str:
    """Update a JIRA issue (fields, status transition, comment).

    Args:
        jira_service: JiraService instance
        ticket_key: JIRA ticket key (e.g., PROJ-123)
        fields: Dictionary of fields to update
        status: New status to transition to
        comment: Comment to add

    Returns:
        Human-readable status message
    """
    ticket_key = ticket_key.strip().upper()
    results: List[str] = []

    # --- Field updates ---
    if fields:
        update_payload: Dict[str, Any] = {"fields": {}}
        if fields.get("summary"):
            update_payload["fields"]["summary"] = fields["summary"]
        if fields.get("description"):
            update_payload["fields"]["description"] = markdown_to_adf(fields["description"])
        if fields.get("priority"):
            update_payload["fields"]["priority"] = {"name": map_priority(fields["priority"])}
        if fields.get("labels") is not None:
            update_payload["fields"]["labels"] = fields["labels"]

        if update_payload["fields"]:
            ok = await jira_service.update_issue(ticket_key, update_payload)
            results.append("Fields updated" if ok else "Field update failed")

    # --- Status transition ---
    if status:
        msg = await jira_service.transition_issue(ticket_key, status)
        results.append(msg)

    # --- Comment ---
    if comment:
        msg = await jira_service.add_comment(ticket_key, comment)
        results.append(msg)

    if results:
        return f"{ticket_key}: " + ", ".join(results)
    return f"{ticket_key}: No changes requested"


async def get_ticket_details(jira_service, ticket_key: str) -> str:
    """Get detailed information about a specific JIRA ticket.

    Now uses direct ``GET /issue/{key}`` instead of fetching all project
    issues and filtering in memory.
    """
    ticket_key = ticket_key.strip().upper()
    log_info(f"Getting details for: {ticket_key}", "jira_operations")

    ticket = await jira_service.get_issue(ticket_key)
    if ticket is None:
        return f"Ticket {ticket_key} not found"

    parts = [
        f"**{ticket.get('key')}**: {ticket.get('summary')}\n",
        f"**Type:** {ticket.get('issueType', 'Unknown')}",
        f"**Status:** {ticket.get('status')}",
        f"**Priority:** {ticket.get('priority')}",
    ]
    if ticket.get("assignee"):
        parts.append(f"**Assignee:** {ticket['assignee']}")
    if ticket.get("reporter"):
        parts.append(f"**Reporter:** {ticket['reporter']}")
    if ticket.get("labels"):
        parts.append(f"**Labels:** {', '.join(ticket['labels'])}")
    if ticket.get("components"):
        parts.append(f"**Components:** {', '.join(ticket['components'])}")
    if ticket.get("description"):
        description = _preview_text(ticket["description"], _DETAIL_DESCRIPTION_PREVIEW_CHARS)
        parts.append(f"\n**Description:**\n{description}")
    if ticket.get("subtaskCount"):
        parts.append(f"\n**Subtasks:** {ticket['subtaskCount']}")
    if ticket.get("created"):
        parts.append(f"**Created:** {ticket['created']}")
    if ticket.get("updated"):
        parts.append(f"**Updated:** {ticket['updated']}")

    return "\n".join(parts)


async def get_ticket_comments(jira_service, ticket_key: str, max_results: int = 50) -> str:
    """Get comments for a specific JIRA ticket.

    Args:
        jira_service: JiraService instance
        ticket_key: JIRA ticket key (e.g., PROJ-123)
        max_results: Maximum number of comments to return

    Returns:
        Human-readable formatted comments
    """
    ticket_key = ticket_key.strip().upper()
    log_info(f"Getting comments for: {ticket_key}", "jira_operations")

    try:
        comments = await jira_service.get_comments(ticket_key, max_results)
    except JiraApiError as exc:
        log_error(f"JIRA get comments error: {exc.detail}", "jira_operations")
        return f"Failed to fetch comments for {ticket_key}: {exc.status_code} - {exc.detail}"

    if not comments:
        return f"No comments found on {ticket_key}"

    parts = [f"**Comments on {ticket_key}** ({len(comments)} comment(s)):\n"]
    for idx, c in enumerate(comments, 1):
        parts.append(f"**{idx}. {c['author']}** — {c['created']}")
        body = _preview_text(c["body"], _COMMENT_PREVIEW_CHARS)
        parts.append(f"{body}\n")
    return "\n".join(parts)


async def create_subtask(
    jira_service,
    parent_key: str,
    summary: str,
    description: str = "",
    priority: str = "Medium",
) -> str:
    """Create a subtask under an existing JIRA issue.

    Tries multiple subtask type names since JIRA project configs vary.
    """
    settings = jira_service.settings
    parent_key = parent_key.strip().upper()
    log_info(f"Creating subtask under {parent_key}: {summary}", "jira_operations")

    adf_description = markdown_to_adf(description)
    mapped_priority = map_priority(priority)

    for subtask_type in SUBTASK_TYPE_NAMES:
        issue_data: Dict[str, Any] = {
            "fields": {
                "project": {"key": settings.jira_project_key},
                "parent": {"key": parent_key},
                "summary": summary,
                "description": adf_description,
                "issuetype": {"name": subtask_type},
                "priority": {"name": mapped_priority},
            }
        }

        try:
            data = await jira_service.create_issue(issue_data)
            ticket_key = data.get("key")
            return f"Created subtask **{ticket_key}** under {parent_key}: {summary}"
        except JiraApiError as exc:
            if "issuetype" in exc.detail.lower():
                log_info(f"Subtask type '{subtask_type}' not valid, trying next...", "jira_operations")
                continue
            log_error(f"JIRA subtask create error: {exc.detail}", "jira_operations")
            return f"Failed to create subtask: {exc.status_code} - {exc.detail}"

    return "Failed to create subtask: Could not find a valid subtask issue type in your JIRA project"


async def link_issues(
    jira_service,
    source_key: str,
    target_key: str,
    link_type: str = "Relates",
) -> str:
    """Link two JIRA issues together."""
    source_key = source_key.strip().upper()
    target_key = target_key.strip().upper()
    log_info(f"Linking {source_key} -> {target_key} ({link_type})", "jira_operations")

    # Normalise link type name
    link_type_map = {
        "relates": "Relates",
        "relates to": "Relates",
        "blocks": "Blocks",
        "is blocked by": "Blocks",
        "blocked by": "Blocks",
        "duplicates": "Duplicate",
        "duplicate": "Duplicate",
        "is duplicated by": "Duplicate",
        "clones": "Cloners",
        "is cloned by": "Cloners",
        "causes": "Problem/Incident",
        "is caused by": "Problem/Incident",
    }
    normalised = link_type_map.get(link_type.lower(), link_type)

    link_data = {
        "type": {"name": normalised},
        "inwardIssue": {"key": source_key},
        "outwardIssue": {"key": target_key},
    }

    ok = await jira_service.link_issues(link_data)
    if ok:
        return f"Linked **{source_key}** to **{target_key}** ({normalised})"

    # Fetch available types for a better error message
    available = await jira_service.get_link_types()
    if available:
        return f"Invalid link type '{link_type}'. Available types: {', '.join(available)}"
    return f"Failed to link issues {source_key} -> {target_key}"


# ------------------------------------------------------------------ #
# Markdown → ADF converter
# ------------------------------------------------------------------ #

def markdown_to_adf(markdown_text: str) -> Dict[str, Any]:
    """Convert markdown text to Atlassian Document Format (ADF).

    Supports: headings (h1-h3), bullet lists, numbered lists, code blocks,
    bold text, and plain paragraphs.
    """
    if not markdown_text:
        return {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": "No description provided"}]}],
        }

    content: list[Dict[str, Any]] = []
    lines = markdown_text.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # --- Headings ---
        for level, prefix in ((3, "### "), (2, "## "), (1, "# ")):
            if line.startswith(prefix):
                content.append({
                    "type": "heading",
                    "attrs": {"level": level},
                    "content": [{"type": "text", "text": line[len(prefix):].strip()}],
                })
                i += 1
                break
        else:
            # --- Numbered list ---
            if _is_numbered_item(line):
                list_items: list[Dict[str, Any]] = []
                while i < len(lines) and _is_numbered_item(lines[i]):
                    item_text = _strip_numbered_prefix(lines[i])
                    list_items.append({
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": item_text}]}],
                    })
                    i += 1
                content.append({"type": "orderedList", "content": list_items})
                continue

            # --- Bullet list ---
            if line.strip().startswith("- ") or line.strip().startswith("* "):
                list_items = []
                while i < len(lines) and (lines[i].strip().startswith("- ") or lines[i].strip().startswith("* ")):
                    item_text = lines[i].strip()[2:].strip()
                    list_items.append({
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": item_text}]}],
                    })
                    i += 1
                content.append({"type": "bulletList", "content": list_items})
                continue

            # --- Code block ---
            if line.strip().startswith("```"):
                code_lines: list[str] = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # skip closing ```
                content.append({"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code_lines)}]})
                continue

            # --- Regular paragraph with inline bold ---
            text_content = _parse_inline_formatting(line)
            if text_content:
                content.append({"type": "paragraph", "content": text_content})
            i += 1

    return {
        "type": "doc",
        "version": 1,
        "content": content or [{"type": "paragraph", "content": [{"type": "text", "text": markdown_text}]}],
    }


# ------------------------------------------------------------------ #
# Inline formatting helpers
# ------------------------------------------------------------------ #

def _is_numbered_item(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    dot_idx = stripped.find(".")
    return dot_idx > 0 and stripped[:dot_idx].isdigit()


def _strip_numbered_prefix(line: str) -> str:
    stripped = line.strip()
    dot_idx = stripped.find(".")
    return stripped[dot_idx + 1:].strip()


def _parse_inline_formatting(line: str) -> list[Dict[str, Any]]:
    """Parse bold (``**text**``) within a line."""
    parts: list[Dict[str, Any]] = []
    remaining = line

    while remaining:
        bold_start = remaining.find("**")
        if bold_start != -1:
            bold_end = remaining.find("**", bold_start + 2)
            if bold_end != -1:
                if bold_start > 0:
                    parts.append({"type": "text", "text": remaining[:bold_start]})
                parts.append({
                    "type": "text",
                    "text": remaining[bold_start + 2:bold_end],
                    "marks": [{"type": "strong"}],
                })
                remaining = remaining[bold_end + 2:]
                continue

        if remaining:
            parts.append({"type": "text", "text": remaining})
        break

    return parts
