"""Process BRD (Business Requirements Document) input into JIRA Epic + User Stories."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from ..core.logging import log_error, log_info
from ..services.jira_service import JiraApiError
from .jira_operations import markdown_to_adf
from ..helpers.conversation_manager import ConversationContext, ConversationState

# ------------------------------------------------------------------ #
# LLM prompt — extract structured features from a BRD document
# ------------------------------------------------------------------ #

_BRD_EXTRACT_PROMPT = """\
You are a senior JIRA project manager and technical analyst. Carefully read the Business Requirements Document (BRD) below and extract every distinct feature or requirement into a structured JSON object.

Look in ALL sections: Feature Breakdown, Functional Requirements, Solution Overview, User Journey, Architecture, etc.

Return ONLY a valid JSON object with this exact structure — no markdown fences, no explanation:

{{
  "project_name": "The overall project name from the BRD",
  "project_description": "2-3 sentence executive summary of the project",
  "features": [
    {{
      "feature_name": "Short, actionable feature title (e.g. 'Admin Screen — Role-Based Access Control')",
      "feature_description": "Clear description of what this feature does and its business value",
      "Technical_Details": "Backend logic, API endpoints, data models, controller/service responsibilities",
      "archetictral_Details": "Component interactions, data flow, frontend-backend contract, patterns used",
      "tech_stack": "Specific frameworks, libraries, and tools required for this feature",
      "related_folders_and_files": "Exact file paths and directories from the codebase involved",
      "ui_guidelines": "UI/UX requirements, color palette, typography, component layout, branding rules",
      "Implementation_Steps": "Ordered step-by-step developer guide from setup to deployment",
      "Acceptance_Criteria": "Bullet-point list of specific, testable acceptance criteria",
      "Definition_of_Done": "Checklist of everything that must be true before this story is closed",
      "referance_files": "Key reference files, external docs, or prior tickets",
      "relivent_information": "Constraints, assumptions, dependencies, or non-functional requirements"
    }}
  ]
}}

BRD Document:
{brd_content}
"""


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _build_story_description(feature: Dict[str, Any]) -> str:
    """Format a feature dict into a rich professional markdown description."""
    sections: List[str] = []

    if feature.get("feature_description"):
        sections.append(f"## Overview\n{feature['feature_description']}")

    if feature.get("Technical_Details"):
        sections.append(f"## Technical Details\n{feature['Technical_Details']}")

    if feature.get("archetictral_Details"):
        sections.append(f"## Architecture\n{feature['archetictral_Details']}")

    if feature.get("tech_stack"):
        sections.append(f"## Technology Stack\n{feature['tech_stack']}")

    if feature.get("related_folders_and_files"):
        sections.append(f"## Related Files & Folders\n{feature['related_folders_and_files']}")

    if feature.get("ui_guidelines"):
        sections.append(f"## UI & Design Guidelines\n{feature['ui_guidelines']}")

    if feature.get("Implementation_Steps"):
        sections.append(f"## Implementation Steps\n{feature['Implementation_Steps']}")

    if feature.get("Acceptance_Criteria"):
        sections.append(f"## Acceptance Criteria\n{feature['Acceptance_Criteria']}")

    if feature.get("Definition_of_Done"):
        sections.append(f"## Definition of Done\n{feature['Definition_of_Done']}")

    if feature.get("referance_files"):
        sections.append(f"## Reference Files\n{feature['referance_files']}")

    if feature.get("relivent_information"):
        sections.append(f"## Additional Information\n{feature['relivent_information']}")

    return "\n\n".join(sections) if sections else feature.get("feature_name", "No description provided")


async def _create_epic(
    jira_service,
    project_name: str,
    project_description: str,
) -> Optional[str]:
    """Create a JIRA Epic, or return existing one with the same summary."""
    existing = await _find_existing_issue(jira_service, project_name, "Epic")
    if existing:
        log_info(f"Epic already exists: {existing} — skipping creation", "process_brd")
        return existing

    settings = jira_service.settings
    epic_description_md = f"## Project Overview\n{project_description}\n\n_Auto-generated from BRD document._"
    issue_data: Dict[str, Any] = {
        "fields": {
            "project": {"key": settings.jira_project_key},
            "summary": project_name,
            "description": markdown_to_adf(epic_description_md),
            "issuetype": {"name": "Epic"},
        }
    }
    try:
        data = await jira_service.create_issue(issue_data)
        return data.get("key")
    except JiraApiError as exc:
        log_error(f"Failed to create Epic: {exc.detail}", "process_brd")
        return None


async def _create_story_under_epic(
    jira_service,
    epic_key: str,
    feature: Dict[str, Any],
) -> Optional[str]:
    """Create a User Story linked to an Epic, or return existing one with the same summary.

    Tries `parent` field first (JIRA Cloud next-gen / team-managed projects),
    then falls back to `customfield_10014` (classic Epic Link), then creates
    the story without an epic link as a last resort.
    """
    summary = feature.get("feature_name", "User Story")

    existing = await _find_existing_issue(jira_service, summary, "Story")
    if existing:
        log_info(f"Story already exists: {existing} — skipping creation", "process_brd")
        return existing

    settings = jira_service.settings
    description_md = _build_story_description(feature)
    adf_description = markdown_to_adf(description_md)

    base_fields: Dict[str, Any] = {
        "project": {"key": settings.jira_project_key},
        "summary": summary,
        "description": adf_description,
        "issuetype": {"name": "Story"},
        "priority": {"name": "High"},
    }

    # Attempt 1: parent field (next-gen / team-managed)
    try:
        data = await jira_service.create_issue({"fields": {**base_fields, "parent": {"key": epic_key}}})
        return data.get("key")
    except JiraApiError as exc:
        log_info(f"parent field rejected ({exc.status_code}), trying Epic Link field", "process_brd")

    # Attempt 2: customfield_10014 (classic Epic Link)
    try:
        data = await jira_service.create_issue({"fields": {**base_fields, "customfield_10014": epic_key}})
        return data.get("key")
    except JiraApiError as exc:
        log_info(f"Epic Link field rejected ({exc.status_code}), creating story without epic link", "process_brd")

    # Attempt 3: no epic link — story is orphaned but still created
    try:
        data = await jira_service.create_issue({"fields": base_fields})
        return data.get("key")
    except JiraApiError as exc:
        log_error(f"Failed to create story '{summary}': {exc.detail}", "process_brd")
        return None


def _parse_brd_json(raw: str) -> Dict[str, Any]:
    """Strip markdown fences and parse the JSON returned by the LLM."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned.strip(), flags=re.MULTILINE)
    return json.loads(cleaned.strip())


def _dedup_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove features with duplicate names (case-insensitive, keeping first occurrence)."""
    seen: set = set()
    result: List[Dict[str, Any]] = []
    for f in features:
        key = (f.get("feature_name") or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(f)
    return result


async def _find_existing_issue(jira_service, summary: str, issue_type: str) -> Optional[str]:
    """Search JIRA for an issue with an exact summary match. Returns the key or None."""
    settings = jira_service.settings
    safe = summary.replace('"', '\\"')
    jql = (
        f'project = {settings.jira_project_key} AND issuetype = "{issue_type}"'
        f' AND summary ~ "{safe}" ORDER BY created DESC'
    )
    try:
        issues = await jira_service.search_with_jql(jql, max_results=10)
        for issue in issues:
            if (issue.get("summary") or "").strip().lower() == summary.strip().lower():
                return issue.get("key")
    except Exception as exc:
        log_info(f"Duplicate check failed ({exc}), proceeding with creation", "process_brd")
    return None


# ------------------------------------------------------------------ #
# Public entrypoint
# ------------------------------------------------------------------ #

async def process_brd_document(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context=None,
) -> Dict[str, Any]:
    """Parse a BRD document and create a JIRA Epic with User Stories beneath it.

    Flow:
      1. LLM extracts structured features from the BRD markdown.
      2. One Epic is created for the overall project.
      3. One User Story per feature is created under the Epic.
      4. Returns a summary response with all ticket keys.
    """
    log_info("BRD mode: extracting features from document", "process_brd")

    # ── Step 1: Extract features via LLM ──────────────────────────── #
    extract_prompt = _BRD_EXTRACT_PROMPT.format(brd_content=user_prompt)
    try:
        raw = await ai_service.call_genai(
            prompt=extract_prompt,
            temperature=0.1,
            max_tokens=8000,
            task_name="brd_extraction",
        )
    except Exception as exc:
        log_error(f"BRD LLM extraction failed: {exc}", "process_brd")
        return _error_response(conversation_ctx, user_prompt, "Failed to parse the BRD document with AI.")

    print(f"\n[BRD DEBUG] Raw LLM output (first 2000 chars):\n{raw[:2000]}\n")
    log_info(f"BRD raw LLM output (first 2000 chars): {raw[:2000]}", "process_brd")

    # ── Step 2: Parse JSON ─────────────────────────────────────────── #
    try:
        brd_data = _parse_brd_json(raw)
    except Exception as exc:
        log_error(f"BRD JSON parse failed: {exc}\nRaw output (first 500): {raw[:500]}", "process_brd")
        return _error_response(
            conversation_ctx,
            user_prompt,
            "AI returned an invalid JSON structure. Please verify the BRD format and retry.",
        )

    print(f"\n[BRD DEBUG] Parsed project_name: {brd_data.get('project_name')}")
    print(f"[BRD DEBUG] Number of features before dedup: {len(brd_data.get('features') or [])}")

    project_name: str = brd_data.get("project_name") or "BRD Project"
    project_description: str = brd_data.get("project_description") or ""
    features: List[Dict[str, Any]] = _dedup_features(brd_data.get("features") or [])

    print(f"[BRD DEBUG] Number of features after dedup: {len(features)}")
    for i, f in enumerate(features):
        print(f"[BRD DEBUG]   feature[{i}]: {f.get('feature_name')}")

    if not features:
        return _error_response(conversation_ctx, user_prompt, "No features were identified in the BRD document.")

    log_info(f"BRD: {len(features)} feature(s) extracted for '{project_name}'", "process_brd")

    # ── Step 3: Create Epic ────────────────────────────────────────── #
    epic_key = await _create_epic(jira_service, project_name, project_description)
    if not epic_key:
        return _error_response(
            conversation_ctx,
            user_prompt,
            f"Failed to create JIRA Epic for project '{project_name}'. Check JIRA configuration.",
        )

    log_info(f"Epic created: {epic_key}", "process_brd")

    # ── Step 4: Create User Stories ────────────────────────────────── #
    created_stories: List[Dict[str, str]] = []
    failed_features: List[str] = []

    for feature in features:
        story_key = await _create_story_under_epic(jira_service, epic_key, feature)
        feature_name = feature.get("feature_name", "Unknown")
        if story_key:
            created_stories.append({"key": story_key, "name": feature_name})
            log_info(f"Story created: {story_key} — {feature_name}", "process_brd")
        else:
            failed_features.append(feature_name)
            log_error(f"Story creation failed for: {feature_name}", "process_brd")

    # ── Step 5: Build response ─────────────────────────────────────── #
    story_lines = "\n".join(f"  - **{s['key']}**: {s['name']}" for s in created_stories)

    response_parts = [
        "## BRD Processing Complete",
        "",
        f"**Project:** {project_name}",
        f"**Epic Created:** **{epic_key}**",
        f"**User Stories Created:** {len(created_stories)} / {len(features)}",
        "",
        "### Created Stories",
        story_lines,
    ]

    if failed_features:
        failed_lines = "\n".join(f"  - {name}" for name in failed_features)
        response_parts += ["", "### Failed Stories (could not be created)", failed_lines]

    if conversation_ctx is not None:
        conversation_ctx.state = ConversationState.COMPLETED

    all_tickets = [
        {"key": epic_key, "summary": project_name, "issueType": "Epic"},
        *[{"key": s["key"], "summary": s["name"], "issueType": "Story"} for s in created_stories],
    ]

    return {
        "success": len(created_stories) > 0,
        "state": conversation_ctx.state.value if conversation_ctx is not None else ConversationState.COMPLETED.value,
        "session_id": conversation_ctx.session_id if conversation_ctx is not None else None,
        "prompt": user_prompt,
        "intent": "brd",
        "response": "\n".join(response_parts),
        "tickets": all_tickets,
        "collected_data": {
            "epic_key": epic_key,
            "project_name": project_name,
            "stories": created_stories,
            "failed": failed_features,
        },
    }


def _error_response(
    conversation_ctx: ConversationContext,
    prompt: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "success": False,
        "state": ConversationState.INITIAL.value,
        "session_id": conversation_ctx.session_id,
        "prompt": prompt,
        "intent": "brd",
        "response": message,
        "tickets": [],
        "collected_data": {},
    }
