from server.mcp_codebase_context import (
    jira_codebase_context_template,
    missing_jira_codebase_context_sections,
)


def test_missing_sections_returns_all_for_empty_context() -> None:
    missing = missing_jira_codebase_context_sections("")
    assert len(missing) == 5
    assert "File and Folder Related" in missing
    assert "Current Project Validation Rules" in missing
    assert "Tech Stack Summary" in missing
    assert "UI Guidelines" in missing
    assert "Other Relevant Info" in missing


def test_missing_sections_detects_complete_context() -> None:
    context = """
    ## File and Folder Related
    - Project tree

    ## Current Project Validation Rules
    - Required fields in KYCModel

    ## Tech Stack Summary
    - React, Node, MongoDB

    ## UI Guidelines
    - Keep consistent label/input style

    ## Other Relevant Info
    - API payload and edge cases
    """
    assert missing_jira_codebase_context_sections(context) == []


def test_template_mentions_all_required_sections() -> None:
    tmpl = jira_codebase_context_template().lower()
    assert "file and folder related" in tmpl
    assert "current project validation rules" in tmpl
    assert "tech stack summary" in tmpl
    assert "ui guidelines" in tmpl
    assert "other relevant info" in tmpl


def test_template_mentions_query_vs_codebase_context_split() -> None:
    tmpl = jira_codebase_context_template().lower()
    assert "project tree" in tmpl
    assert "key paths" in tmpl
