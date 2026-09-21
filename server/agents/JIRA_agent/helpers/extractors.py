"""Data extraction and merging utilities for JIRA ticket information."""
import re
from typing import Dict, Any, List

from .conversation_manager import InfoRequest


def extract_ticket_data_from_prompt(user_prompt: str) -> Dict[str, Any]:
    """Extract ticket information from user prompt using pattern matching."""
    extracted = {}

    ticket_keys = re.findall(r'\b([A-Z]{2,10}-\d+)\b', user_prompt)
    if ticket_keys:
        seen = set()
        ticket_keys = [k for k in ticket_keys if not (k in seen or seen.add(k))]
        extracted["ticket_key"] = ticket_keys[0]
        extracted["ticket_keys"] = ticket_keys

    priority_patterns = {
        "critical": ["critical", "urgent", "blocker"],
        "high": ["high", "important"],
        "medium": ["medium", "normal"],
        "low": ["low", "minor", "trivial"]
    }
    for priority, keywords in priority_patterns.items():
        if any(keyword in user_prompt.lower() for keyword in keywords):
            extracted["priority"] = priority.capitalize()
            break

    if "bug" in user_prompt.lower() or "defect" in user_prompt.lower():
        extracted["issue_type"] = "Bug"
    elif "story" in user_prompt.lower() or "feature" in user_prompt.lower():
        extracted["issue_type"] = "Story"
    elif "task" in user_prompt.lower():
        extracted["issue_type"] = "Task"

    status_patterns = {
        "To Do": ["to do", "todo", "backlog"],
        "In Progress": ["in progress", "working on", "started"],
        "Done": ["done", "complete", "completed", "finished"],
        "Blocked": ["blocked", "stuck"]
    }
    for status, keywords in status_patterns.items():
        if any(keyword in user_prompt.lower() for keyword in keywords):
            extracted["status"] = status
            break

    command_patterns = [
        r'^(create|make|add|show|list|find|search|get|update)\s+(a\s+)?(bug|task|story|ticket|issue)',
        r'^(show|list|find|get)\s+',
    ]
    is_command_only = any(re.match(pattern, user_prompt.lower()) for pattern in command_patterns)

    if not is_command_only and len(user_prompt.split()) >= 3:
        problem_indicators = [
            "can't see", "cannot see", "can't find", "cannot find",
            "not working", "doesn't work", "does not work", "isn't working",
            "not loading", "won't load", "will not load",
            "broken", "error", "issue", "problem", "failed", "failing",
            "missing", "disappeared", "gone"
        ]
        if any(indicator in user_prompt.lower() for indicator in problem_indicators):
            extracted["summary"] = user_prompt.strip()
            extracted["description"] = user_prompt.strip()

    return extracted


def merge_user_response(collected_data: Dict[str, Any], user_response: str, missing_field: InfoRequest) -> Dict[str, Any]:
    """Intelligently merge user's response into collected data."""
    field = missing_field.field
    user_lower = user_response.lower().strip()

    if missing_field.options:
        for option in missing_field.options:
            if option.lower() == user_lower:
                collected_data[field] = option
                return collected_data

        for option in missing_field.options:
            if option.lower() in user_lower or user_lower in option.lower():
                collected_data[field] = option
                return collected_data

        if user_response.strip().isdigit():
            index = int(user_response.strip()) - 1
            if 0 <= index < len(missing_field.options):
                collected_data[field] = missing_field.options[index]
                return collected_data

    if field == "confirmed":
        if user_lower in ["yes", "y", "yeah", "yep", "confirm", "ok", "okay", "sure", "go ahead", "proceed"]:
            collected_data[field] = "yes"
        elif user_lower in ["no", "n", "nope", "cancel", "stop", "abort"]:
            collected_data[field] = "no"
        else:
            collected_data[field] = user_response.strip()
        return collected_data

    collected_data[field] = user_response.strip()
    return collected_data
