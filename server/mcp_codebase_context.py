"""Validation rules for MCP codebase_context payloads."""
from __future__ import annotations

from typing import Dict, List, Tuple


# Canonical section names and accepted aliases (case-insensitive substring match).
JIRA_CODEBASE_CONTEXT_SECTIONS: Dict[str, Tuple[str, ...]] = {
    "File and Folder Related": (
        "file and folder related",
        "files and folders",
        "file/folder",
        "project tree",
    ),
    "Current Project Validation Rules": (
        "current project validation rules",
        "validation rules",
        "validation logic",
        "validator rules",
    ),
    "Tech Stack Summary": (
        "tech stack summary",
        "technology stack",
        "stack summary",
    ),
    "UI Guidelines": (
        "ui guidelines",
        "ux guidelines",
        "design guidelines",
    ),
    "Other Relevant Info": (
        "other relevant info",
        "other relevant information",
        "additional relevant info",
    ),
}


def missing_jira_codebase_context_sections(codebase_context: str) -> List[str]:
    """Return canonical section names that are missing in Jira codebase_context."""
    text = (codebase_context or "").strip().lower()
    if not text:
        return list(JIRA_CODEBASE_CONTEXT_SECTIONS.keys())

    missing: List[str] = []
    for canonical, aliases in JIRA_CODEBASE_CONTEXT_SECTIONS.items():
        if not any(alias in text for alias in aliases):
            missing.append(canonical)
    return missing


def jira_codebase_context_template() -> str:
    """Human-readable template callers should follow for Jira MCP requests."""
    return (
        "Use this minimum structure in codebase_context:\n"
        "1) File and Folder Related\n"
        "2) Current Project Validation Rules\n"
        "3) Tech Stack Summary\n"
        "4) UI Guidelines\n"
        "5) Other Relevant Info\n\n"
        "Recommended format:\n"
        "## File and Folder Related\n"
        "- Project tree (top 2-3 levels)\n"
        "- Key paths\n"
        "- Code snippets as --- path/to/file ---\n\n"
        "## Current Project Validation Rules\n"
        "- Field-level and form-level validations\n"
        "- Required/optional constraints\n\n"
        "## Tech Stack Summary\n"
        "- Frontend, backend, database, libraries\n\n"
        "## UI Guidelines\n"
        "- Existing labels, patterns, layout and accessibility rules\n\n"
        "## Other Relevant Info\n"
        "- Dependencies, assumptions, risks, edge cases"
    )
