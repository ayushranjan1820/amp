"""JIRA integration service — enterprise-grade.

Improvements:
- Shared, long-lived httpx.AsyncClient with connection pooling
- Centralised auth via AuthProvider (Basic / OAuth / PAT)
- Direct ``GET /issue/{key}`` instead of fetch-all-then-filter
- Paginated search (handles projects with >100 issues)
- No duplicate auth computation — all goes through JiraHttpClient
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..core.config import Settings, get_settings
from ..core.auth import AuthProvider, create_auth_provider
from ..core.http_client import JiraHttpClient
from ..core.logging import log_info, log_error, log_debug


# ------------------------------------------------------------------ #
# Shared constants
# ------------------------------------------------------------------ #

# Fields requested for list / search views (lightweight)
_LIST_FIELDS = "summary,description,status,priority,labels,subtasks,issuetype"
# Fields requested for detail / search_with_jql views (richer)
_DETAIL_FIELDS = (
    "summary,description,status,priority,labels,subtasks,issuetype,"
    "assignee,reporter,created,updated,components"
)
# Default page size — JIRA Cloud allows up to 100
_DEFAULT_PAGE_SIZE = 100
# Maximum total issues we'll paginate through (safety ceiling)
_MAX_TOTAL_ISSUES = 1000


class JiraService:
    """Service for JIRA API interactions.

    Accepts an optional ``Settings`` object for multi-tenant support.
    When omitted it reads the current environment (``get_settings()``).
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings: Settings = settings or get_settings()
        self._auth: AuthProvider = create_auth_provider(self.settings)
        self._base_url = f"https://{self.settings.jira_instance_url}/rest/api/3"
        self._client = JiraHttpClient(
            base_url=self._base_url,
            auth_provider=self._auth,
        )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def close(self):
        """Shut down the underlying HTTP client (call on app shutdown)."""
        await self._client.close()

    # ------------------------------------------------------------------ #
    # Issue CRUD
    # ------------------------------------------------------------------ #

    async def get_issue(self, key: str, fields: str = _DETAIL_FIELDS) -> Optional[Dict[str, Any]]:
        """Fetch a single issue by key via ``GET /issue/{key}``.

        Returns the parsed issue dict or ``None`` if not found.
        """
        key = key.strip().upper()
        log_debug(f"GET /issue/{key}", "jira_service")
        response = await self._client.get(
            f"/issue/{key}",
            params={"fields": fields},
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            log_error(f"Get issue error ({response.status_code}): {response.text}", "jira_service")
            return None
        return self._parse_issue(response.json())

    async def create_issue(self, issue_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a JIRA issue. Returns the raw API response body."""
        response = await self._client.post("/issue", json_body=issue_data)
        if response.status_code == 201:
            return response.json()
        error = response.text
        log_error(f"Create issue error ({response.status_code}): {error}", "jira_service")
        raise JiraApiError(f"Failed to create issue: {response.status_code}", response.status_code, error)

    async def update_issue(self, key: str, payload: Dict[str, Any]) -> bool:
        """Update issue fields. Returns True on success."""
        key = key.strip().upper()
        response = await self._client.put(f"/issue/{key}", json_body=payload)
        if response.status_code == 204:
            return True
        log_error(f"Update issue error ({response.status_code}): {response.text}", "jira_service")
        return False

    async def transition_issue(self, key: str, status: str) -> str:
        """Transition an issue to a new status. Returns a status message."""
        key = key.strip().upper()
        response = await self._client.get(f"/issue/{key}/transitions")
        if response.status_code != 200:
            return f"Failed to get transitions: {response.status_code}"

        transitions = response.json().get("transitions", [])
        target = None
        status_lower = status.lower()
        for t in transitions:
            if (t.get("name", "").lower() == status_lower
                    or t.get("to", {}).get("name", "").lower() == status_lower):
                target = t
                break

        if not target:
            available = [t.get("name") for t in transitions]
            return f"Status '{status}' not available. Options: {available}"

        resp = await self._client.post(
            f"/issue/{key}/transitions",
            json_body={"transition": {"id": target["id"]}},
        )
        if resp.status_code == 204:
            return f"Status changed to '{status}'"
        return f"Transition failed: {resp.text}"

    async def get_comments(self, key: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Fetch comments for an issue via ``GET /issue/{key}/comment``.

        Returns a list of parsed comment dicts, or raises ``JiraApiError``
        so callers can surface the real error instead of empty results.
        """
        key = key.strip().upper()
        log_debug(f"GET /issue/{key}/comment", "jira_service")
        resp = await self._client.get(
            f"/issue/{key}/comment",
            params={"maxResults": max_results},
        )
        if resp.status_code != 200:
            log_error(f"Get comments error ({resp.status_code}): {resp.text}", "jira_service")
            raise JiraApiError(
                f"Failed to fetch comments: {resp.status_code}",
                resp.status_code,
                resp.text,
            )
        data = resp.json()
        comments = []
        for c in data.get("comments", []):
            body_text = self.extract_text_from_adf(c.get("body", {})) if isinstance(c.get("body"), dict) else str(c.get("body", ""))
            comments.append({
                "id": c.get("id"),
                "author": c.get("author", {}).get("displayName", "Unknown"),
                "body": body_text,
                "created": c.get("created", ""),
                "updated": c.get("updated", ""),
            })
        return comments

    async def add_comment(self, key: str, comment: str) -> str:
        """Add a comment to an issue."""
        key = key.strip().upper()
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": comment}]}
                ],
            }
        }
        resp = await self._client.post(f"/issue/{key}/comment", json_body=payload)
        if resp.status_code == 201:
            return "Comment added"
        return f"Comment failed: {resp.text}"

    async def link_issues(self, link_data: Dict[str, Any]) -> bool:
        """Create an issue link. Returns True on success."""
        resp = await self._client.post("/issueLink", json_body=link_data)
        if resp.status_code == 201:
            return True
        log_error(f"Link issues error ({resp.status_code}): {resp.text}", "jira_service")
        return False

    async def get_link_types(self) -> List[str]:
        """Fetch available issue link types."""
        resp = await self._client.get("/issueLinkType")
        if resp.status_code == 200:
            return [t.get("name") for t in resp.json().get("issueLinkTypes", [])]
        return []

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    async def search_with_jql(self, jql: str, max_results: int = 50) -> List[Dict[str, Any]]:
        """Execute a JQL query with pagination.

        Returns up to ``max_results`` issues.
        """
        log_info(f"Executing JQL: {jql}", "jira_service")
        issues: List[Dict[str, Any]] = []
        start_at = 0
        page_size = min(max_results, _DEFAULT_PAGE_SIZE)

        while len(issues) < max_results:
            response = await self._client.get(
                "/search/jql",
                params={
                    "jql": jql,
                    "fields": _DETAIL_FIELDS,
                    "maxResults": page_size,
                    "startAt": start_at,
                },
            )
            if response.status_code != 200:
                log_error(f"JQL search error: {response.text}", "jira_service")
                raise JiraApiError(f"JQL search failed: {response.status_code}", response.status_code, response.text)

            data = response.json()
            raw_issues = data.get("issues", [])
            if not raw_issues:
                break

            issues.extend(self._parse_issue(i) for i in raw_issues)
            total = data.get("total", 0)
            start_at += len(raw_issues)
            if start_at >= total:
                break

        log_info(f"JQL search returned {len(issues)} issues", "jira_service")
        return issues[:max_results]

    async def get_project_issues(
        self,
        max_results: int = _DEFAULT_PAGE_SIZE,
        issue_type: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch project issues with optional filters, with pagination.

        Replaces the old ``get_jira_stories()`` which fetched at most 100 issues
        with no pagination.
        """
        project_key = self.settings.jira_project_key
        log_debug(f"Fetching issues for project {project_key}", "jira_service")

        jql_parts = [f"project = {project_key}"]
        if issue_type:
            jql_parts.append(f'issuetype = "{issue_type}"')
        if status:
            jql_parts.append(f'status = "{status}"')
        jql_parts.append("ORDER BY created DESC")
        jql = " AND ".join(jql_parts[:-1]) + " " + jql_parts[-1]

        return await self.search_with_jql(jql, max_results=min(max_results, _MAX_TOTAL_ISSUES))

    # Keep backward compat alias
    async def get_jira_stories(self) -> List[Dict[str, Any]]:
        """Backward-compatible wrapper. Prefer ``get_project_issues()``."""
        return await self.get_project_issues()

    # ------------------------------------------------------------------ #
    # Story sync (bulk)
    # ------------------------------------------------------------------ #

    async def sync_stories_to_jira(self, user_stories: List[Any], storage) -> Dict[str, Any]:
        """Sync user stories to JIRA."""
        results = []
        for story in user_stories:
            try:
                description = self._build_story_description(story)
                is_subtask = bool(story.parentJiraKey)
                issue_type_name = "Sub-task" if is_subtask else "Story"

                issue_data: Dict[str, Any] = {
                    "fields": {
                        "project": {"key": self.settings.jira_project_key},
                        "summary": story.title,
                        "description": description,
                        "issuetype": {"name": issue_type_name},
                        "labels": story.labels or [],
                    }
                }
                if is_subtask and story.parentJiraKey:
                    issue_data["fields"]["parent"] = {"key": story.parentJiraKey}

                resp = await self._client.post("/issue", json_body=issue_data)
                if resp.status_code == 201:
                    data = resp.json()
                    info: Dict[str, Any] = {"storyKey": story.storyKey, "jiraKey": data.get("key")}
                    if is_subtask:
                        info.update(parentKey=story.parentJiraKey, isSubtask=True)
                    results.append(info)
                else:
                    log_error(f"JIRA API error for {story.storyKey}: {resp.text}", "jira")
                    results.append({"storyKey": story.storyKey, "error": f"Failed: {resp.status_code}"})
            except Exception as err:
                log_error(f"Error syncing story {story.storyKey}", "jira", err)
                results.append({"storyKey": story.storyKey, "error": str(err)})

        ok = len([r for r in results if r.get("jiraKey")])
        fail = len([r for r in results if r.get("error")])
        log_info(f"Synced {ok} stories to JIRA ({fail} failed)", "jira")
        return {
            "message": f"Synced {ok} stories to JIRA. {f'{fail} failed.' if fail else ''}",
            "results": results,
        }

    # ------------------------------------------------------------------ #
    # Parent story context
    # ------------------------------------------------------------------ #

    async def get_parent_story_context(self, parent_jira_key: str) -> Optional[str]:
        """Fetch context from parent JIRA story using direct issue GET."""
        issue = await self.get_issue(parent_jira_key, fields="summary,description")
        if issue is None:
            return None
        parent_context = f"Parent Story [{parent_jira_key}]: {issue.get('summary', '')}"
        desc = issue.get("description", "")
        if desc:
            parent_context += f"\n\nDescription: {desc}"
        return parent_context

    # ------------------------------------------------------------------ #
    # ADF helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def extract_text_from_adf(adf: Any) -> str:
        """Extract plain text from Atlassian Document Format, preserving block structure.

        Headings, paragraphs, list items, and code blocks are separated by
        newlines so multi-section descriptions arrive as readable text instead
        of one collapsed line.
        """
        if not adf:
            return ""
        if isinstance(adf, str):
            return adf

        import re as _re

        BLOCK_TYPES = {
            "paragraph", "heading", "blockquote", "codeBlock",
            "rule", "table", "tableRow", "tableHeader", "tableCell",
            "mediaSingle", "panel",
        }
        parts: list[str] = []

        def _ensure_block_break():
            if parts and not parts[-1].endswith("\n"):
                parts.append("\n")

        def _walk(node: Any, list_marker: str = ""):
            if isinstance(node, list):
                for item in node:
                    _walk(item, list_marker)
                return
            if not isinstance(node, dict):
                return

            ntype = node.get("type")

            if ntype == "text":
                parts.append(node.get("text", ""))
                return
            if ntype == "hardBreak":
                parts.append("\n")
                return
            if ntype == "bulletList":
                _ensure_block_break()
                for child in node.get("content", []):
                    _walk(child, "- ")
                _ensure_block_break()
                return
            if ntype == "orderedList":
                _ensure_block_break()
                for idx, child in enumerate(node.get("content", []), 1):
                    _walk(child, f"{idx}. ")
                _ensure_block_break()
                return
            if ntype == "listItem":
                parts.append(f"\n{list_marker}")
                for child in node.get("content", []):
                    _walk(child, "")
                return
            if ntype in BLOCK_TYPES:
                _ensure_block_break()
                for child in node.get("content", []):
                    _walk(child, list_marker)
                _ensure_block_break()
                return

            for key in ("content", "children"):
                if key in node:
                    for child in node[key]:
                        _walk(child, list_marker)

        _walk(adf)
        text = "".join(parts)
        # Collapse 3+ consecutive newlines down to 2 (one blank line).
        text = _re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _parse_issue(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise a raw JIRA API issue into a flat dict."""
        fields = raw.get("fields", {})
        return {
            "key": raw.get("key"),
            "summary": fields.get("summary"),
            "description": self.extract_text_from_adf(fields.get("description")),
            "status": (fields.get("status") or {}).get("name", "Unknown"),
            "priority": (fields.get("priority") or {}).get("name", "Medium"),
            "labels": fields.get("labels", []),
            "issueType": (fields.get("issuetype") or {}).get("name", "Story"),
            "subtaskCount": len(fields.get("subtasks", [])),
            "assignee": (fields.get("assignee") or {}).get("displayName") if fields.get("assignee") else None,
            "reporter": (fields.get("reporter") or {}).get("displayName") if fields.get("reporter") else None,
            "created": fields.get("created"),
            "updated": fields.get("updated"),
            "components": [c.get("name") for c in fields.get("components", [])],
        }

    @staticmethod
    def _build_story_description(story: Any) -> Dict[str, Any]:
        """Build JIRA story description in ADF format."""
        description: Dict[str, Any] = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": f"As a {story.asA}, I want {story.iWant}, so that {story.soThat}"}
                    ],
                },
                {
                    "type": "heading",
                    "attrs": {"level": 3},
                    "content": [{"type": "text", "text": "Acceptance Criteria"}],
                },
                {
                    "type": "bulletList",
                    "content": [
                        {
                            "type": "listItem",
                            "content": [{"type": "paragraph", "content": [{"type": "text", "text": c}]}],
                        }
                        for c in story.acceptanceCriteria
                    ],
                },
            ],
        }
        if story.description:
            description["content"].insert(
                1,
                {"type": "paragraph", "content": [{"type": "text", "text": story.description}]},
            )
        if story.technicalNotes:
            description["content"].extend([
                {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Technical Notes"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": story.technicalNotes}]},
            ])
        return description


class JiraApiError(Exception):
    """Raised when a JIRA API call fails."""

    def __init__(self, message: str, status_code: int = 0, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)
