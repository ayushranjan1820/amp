from server.agents.JIRA_agent.utils.input_validator import (
    InputValidationError,
    MAX_PROMPT_LENGTH,
    validate_prompt,
)


def test_validate_prompt_accepts_max_length_boundary() -> None:
    prompt = "a" * MAX_PROMPT_LENGTH
    assert validate_prompt(prompt) == prompt


def test_validate_prompt_rejects_over_max_with_guidance() -> None:
    prompt = "a" * (MAX_PROMPT_LENGTH + 1)

    try:
        validate_prompt(prompt)
        assert False, "Expected InputValidationError"
    except InputValidationError as exc:
        message = str(exc)
        assert "maximum length" in message.lower()
        assert "codebase_context" in message
        assert "received" in message
