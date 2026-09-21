"""Helpers for MCP codebase context parsing and ticket section validation."""
from __future__ import annotations

import re
from typing import List, Optional


CODEBASE_CONTEXT_MAX_CHARS = 100_000

_CODEBASE_BLOCK_RE = re.compile(
    r"\[Codebase Context\]\s*(.*?)\s*\[End Codebase Context\]",
    re.IGNORECASE | re.DOTALL,
)

_FILE_MARKER_RE = re.compile(r"^\s*---\s*(.+?)\s*---\s*$", re.MULTILINE)

REQUIRED_CODEBASE_SECTIONS: tuple[str, ...] = (
    "Technical Details",
    "Related Files and Folders",
    "Implementation Steps",
    "Acceptance Criteria",
    "Definition of Done",
)

_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "Technical Details": ("Technical Details",),
    "Related Files and Folders": ("Related Files and Folders", "Related Files & Folders"),
    "Implementation Steps": ("Implementation Steps", "Implementation Plan"),
    "Acceptance Criteria": ("Acceptance Criteria",),
    "Definition of Done": ("Definition of Done", "Defination of Done"),
}


def extract_codebase_context(text: str) -> str:
    """Extract codebase_context from an MCP wrapped query block."""
    if not text:
        return ""

    match = _CODEBASE_BLOCK_RE.search(text)
    if not match:
        return ""
    return (match.group(1) or "").strip()


def strip_codebase_context(text: str) -> str:
    """Remove MCP codebase_context wrapper from text, if present."""
    if not text:
        return ""

    stripped = _CODEBASE_BLOCK_RE.sub("", text)
    return stripped.strip()


def extract_related_paths(codebase_context: str, limit: Optional[int] = None) -> List[str]:
    """Extract file/folder paths from `--- path ---` markers in context."""
    paths: List[str] = []
    if not codebase_context:
        return paths

    for match in _FILE_MARKER_RE.finditer(codebase_context):
        raw = (match.group(1) or "").strip()
        if not raw:
            continue
        normalized = raw.replace("\\", "/")
        if normalized not in paths:
            paths.append(normalized)
        if limit is not None and len(paths) >= limit:
            break
    return paths


def has_verbatim_codebase_context(markdown_text: str, codebase_context: str) -> bool:
    """Return True when description includes the full codebase context content."""
    if codebase_context is None or codebase_context == "":
        return True
    if markdown_text is None or markdown_text == "":
        return False

    if codebase_context in markdown_text:
        return True

    # Accept platform newline differences while preserving all other characters.
    normalized_context = codebase_context.replace("\r\n", "\n").replace("\r", "\n")
    normalized_markdown = markdown_text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized_context in normalized_markdown


def missing_required_sections(markdown_text: str) -> List[str]:
    """Return required section names that are missing from markdown text."""
    if not markdown_text or not markdown_text.strip():
        return list(REQUIRED_CODEBASE_SECTIONS)

    missing: List[str] = []
    for section in REQUIRED_CODEBASE_SECTIONS:
        aliases = _SECTION_ALIASES.get(section, (section,))
        found = False
        for alias in aliases:
            heading_re = re.compile(rf"^\s*#{{2,6}}\s*{re.escape(alias)}\s*$", re.IGNORECASE | re.MULTILINE)
            bold_re = re.compile(rf"^\s*\*\*{re.escape(alias)}\*\*\s*$", re.IGNORECASE | re.MULTILINE)
            if heading_re.search(markdown_text) or bold_re.search(markdown_text):
                found = True
                break

        if not found:
            missing.append(section)

    return missing


def build_required_sections_fallback(
    summary: str,
    issue_type: str,
    codebase_context: str,
    existing_description: str = "",
) -> str:
    """Build deterministic fallback markdown with all required sections."""
    related_paths = extract_related_paths(codebase_context)

    full_context = codebase_context or ""

    lines: List[str] = [
        "## Technical Details",
        f"- Ticket type: {issue_type or 'Story'}",
        f"- Requested change: {summary or 'No summary provided'}",
        "- Source of truth: MCP codebase_context",
    ]
    if existing_description and existing_description.strip():
        lines.append(f"- Additional user notes: {existing_description.strip()}")
    if full_context:
        lines.extend([
            "- Full codebase context provided by MCP user (verbatim):",
            "```text",
            full_context,
            "```",
        ])

    lines.append("")
    lines.append("## Related Files and Folders")
    if related_paths:
        lines.extend([f"- {path}" for path in related_paths])
    else:
        lines.append(
            "- No explicit `--- path ---` markers were found in codebase_context. "
            "Provide file markers to improve precision."
        )

    lines.extend([
        "",
        "## Implementation Steps",
        "1. Review all files/folders listed above and confirm current behavior.",
        "2. Implement the required code changes for the requested summary.",
        "3. Add or update automated tests for impacted logic.",
        "4. Run linting and tests, and resolve all failures before merge.",
        "",
        "## Acceptance Criteria",
        "1. The change is implemented in the related code paths from codebase_context.",
        "2. Behavior matches the requested summary and does not break existing flows.",
        "3. Automated tests cover the new or changed behavior and pass consistently.",
        "",
        "## Definition of Done",
        "- Code changes are complete and reviewed.",
        "- Tests and quality checks pass.",
        "- Ticket description reflects final technical details, file references, and implementation steps.",
    ])

    return "\n".join(lines)
