"""Message generation utilities for JIRA agent responses."""
from typing import List

from .conversation_manager import InfoRequest


def generate_info_request_message(missing_fields: List[InfoRequest]) -> str:
    """Generate a conversational message requesting missing information.
    Always shows ONE field at a time for better UX.
    """
    if not missing_fields:
        return ""

    field = missing_fields[0]
    msg = f"\U0001f4ac {field.description}"

    if field.options:
        msg += f"\n\n**Options:**\n"
        for i, option in enumerate(field.options, 1):
            msg += f"  {i}. {option}\n"

    return msg
