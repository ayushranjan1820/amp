from server.agents.JIRA_agent.helpers.codebase_context import (
    build_required_sections_fallback,
    extract_codebase_context,
    has_verbatim_codebase_context,
    missing_required_sections,
    strip_codebase_context,
)
from server.agents.JIRA_agent.helpers.validators import validate_create_ticket_data


def _complete_description(definition_header: str = "## Definition of Done") -> str:
    return "\n".join(
        [
            "## Technical Details",
            "- API endpoint is defined in auth router.",
            "",
            "## Related Files and Folders",
            "- server/api.py",
            "- server/agents/JIRA_agent/tools/process_create.py",
            "",
            "## Implementation Steps",
            "1. Update request model.",
            "2. Add validation.",
            "",
            "## Acceptance Criteria",
            "1. Request validates required data.",
            "2. Unit tests pass.",
            "",
            definition_header,
            "- Code reviewed.",
            "- Tests green.",
        ]
    )


def test_extract_and_strip_codebase_context_block() -> None:
    query = """create jira ticket\n\n[Codebase Context]\n--- src/app.py ---\nprint(1)\n[End Codebase Context]"""
    extracted = extract_codebase_context(query)
    stripped = strip_codebase_context(query)

    assert "src/app.py" in extracted
    assert stripped == "create jira ticket"


def test_missing_required_sections_accepts_complete_description() -> None:
    assert missing_required_sections(_complete_description()) == []


def test_missing_required_sections_accepts_defination_spelling() -> None:
    assert missing_required_sections(_complete_description("## Defination of Done")) == []


def test_build_required_sections_fallback_contains_required_headers() -> None:
    context = """--- server/api.py ---\n@app.post('/api/jira-agent')\n\n--- server/mcp_server.py ---\n@server.call_tool(validate_input=False)"""
    result = build_required_sections_fallback(
        summary="Create strict MCP Jira ticket format",
        issue_type="Story",
        codebase_context=context,
    )

    assert "## Technical Details" in result
    assert "## Related Files and Folders" in result
    assert "## Implementation Steps" in result
    assert "## Acceptance Criteria" in result
    assert "## Definition of Done" in result
    assert "server/api.py" in result
    assert "server/mcp_server.py" in result
    assert has_verbatim_codebase_context(result, context)


def test_build_required_sections_fallback_keeps_full_context_without_truncation() -> None:
    tail_marker = "UNIQUE_CONTEXT_END_MARKER_94711"
    context = f"Project tree...\nline a\nline b\n{tail_marker}"
    result = build_required_sections_fallback(
        summary="Context retention test",
        issue_type="Task",
        codebase_context=context,
    )

    assert tail_marker in result
    assert has_verbatim_codebase_context(result, context)


def test_build_required_sections_fallback_preserves_raw_whitespace() -> None:
    raw_context = "\n  LeadingSpaceLine\ncontent-line\nTrailingSpaceLine  \n"
    result = build_required_sections_fallback(
        summary="Whitespace retention",
        issue_type="Task",
        codebase_context=raw_context,
    )

    assert raw_context in result
    assert has_verbatim_codebase_context(result, raw_context)


def test_validate_create_ticket_data_requires_sections_for_codebase_context() -> None:
    collected_data = {
        "summary": "Create strict ticket",
        "description": "Only one paragraph",
        "issue_type": "Story",
        "priority": "Medium",
        "additional_context_asked": True,
        "confirmed": "yes",
    }

    is_complete, missing = validate_create_ticket_data(
        "create jira ticket",
        collected_data,
        {"require_codebase_sections": True},
    )

    assert not is_complete
    assert missing
    assert missing[0].field == "description_sections"
    assert "Technical Details" in missing[0].description


def test_validate_create_ticket_data_requires_full_context_verbatim() -> None:
    full_context = "Project tree\n--- src/pages/KYCPage.js ---\nconst x = 1;"
    collected_data = {
        "summary": "Create strict ticket",
        "description": _complete_description(),
        "issue_type": "Story",
        "priority": "Medium",
        "additional_context_asked": True,
        "confirmed": "yes",
    }

    is_complete, missing = validate_create_ticket_data(
        "create jira ticket",
        collected_data,
        {"require_codebase_sections": True, "codebase_context": full_context},
    )

    assert not is_complete
    assert missing
    assert missing[0].field == "description_context"
