from server.agents.JIRA_agent.utils.action_types import ActionType
from server.agents.JIRA_agent.utils.intent_analyzer import (
    analyze_intent,
    is_explicit_create_ticket_request,
)


def test_create_new_tickets_instruction_routes_to_create() -> None:
    intent = analyze_intent(
        "use <jira_agent> to create new tickets for the project details page assignment edit work"
    )

    assert intent["action"] == ActionType.CREATE
    assert is_explicit_create_ticket_request("use jira_agent to create new tickets")


def test_created_filter_still_routes_to_search() -> None:
    intent = analyze_intent("find tickets created this week for assignment work")

    assert intent["action"] == ActionType.SEARCH
