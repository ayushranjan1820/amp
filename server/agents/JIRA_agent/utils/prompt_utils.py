"""Safe prompt formatting utilities for JIRA agent.

Prompt YAML templates often contain JSON example blocks with literal { } braces.
Python's str.format() treats those as template variables and raises KeyError.
Use safe_fmt() instead — it only substitutes the named placeholders you pass,
leaving all other braces untouched.
"""


def safe_fmt(template: str, **kwargs) -> str:
    """Substitute {placeholders} in a prompt template without touching other braces.

    Unlike str.format(), this function performs simple sequential replacements
    so that JSON example blocks in the prompt (e.g. '{"key": "value"}') are
    never interpreted as format variables.

    Args:
        template: The raw prompt string loaded from a YAML file.
        **kwargs: Placeholder names and their replacement values.

    Returns:
        The prompt with all named placeholders replaced.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", str(value) if value is not None else "")
    return result
