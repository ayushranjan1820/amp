"""Action type definitions for JIRA agent operations."""
from enum import Enum


class ActionType(Enum):
    SEARCH = "search"
    CREATE = "create"
    UPDATE = "update"
    SUBTASK = "subtask"
    LINK = "link"
    SEARCH_AND_UPDATE = "search_and_update"
    GET_DETAILS = "get_details"
    GET_COMMENTS = "get_comments"
    ISSUE_REPORT = "issue_report"
    ANALYTICS = "analytics"
    BRD = "brd"
    UNKNOWN = "unknown"
