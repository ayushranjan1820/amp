"""Intent analysis for user prompts.

Enterprise fix — three layers of defense against misclassification:

Layer 1 (this file):
  - Word-boundary regex matching (no more 'creat' matching 'created')
  - SEARCH takes priority when both SEARCH and CREATE signals are present
  - Explicit conflict resolution logic

Layer 2 (llm_intent_classifier):
  - LLM-based validation before any write operation
  - Called when rule-based returns a WRITE action (CREATE/UPDATE/etc.)

Layer 3 (jira_agent.py guardrails):
  - Final safety net — rejects write ops whose query looks like a read
"""
import re
import json
from typing import Dict, Any, List, Tuple

from .action_types import ActionType


# ------------------------------------------------------------------ #
# Word-boundary pattern helpers
# ------------------------------------------------------------------ #

def _compile_word_patterns(phrases: List[str]) -> re.Pattern:
    """Compile phrase patterns with word boundaries to avoid substring matches.

    'creat' matching 'created' was the root cause of the KYC bug —
    word-boundary patterns prevent this class of error entirely.
    """
    # Sort longest first so 'create ticket' matches before 'create'
    sorted_phrases = sorted(phrases, key=len, reverse=True)
    escaped = [re.escape(p) for p in sorted_phrases]
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


# ------------------------------------------------------------------ #
# Pattern definitions (all use word boundaries)
# ------------------------------------------------------------------ #

_CREATE_PHRASES = [
    "create a", "create ticket", "create jira", "create bug", "create story",
    "create task", "create issue", "create epic",
    "create tickets", "create jira tickets", "create new ticket",
    "create new tickets", "create new jira ticket", "create new jira tickets",
    "new ticket", "new task", "new bug", "new story", "new issue",
    "new tickets", "new tasks", "new bugs", "new stories", "new issues",
    "make a ticket", "make a task", "make a bug", "make an issue",
    "make tickets", "open a ticket", "open tickets", "raise a", "raise ticket",
    "raise tickets",
    "file a ticket", "file a bug", "file a task",
    "file tickets", "file bugs", "file tasks",
    "submit a ticket", "submit a bug", "submit a task",
    "submit tickets", "submit bugs", "submit tasks",
    "log a ticket", "log a bug", "log a task",
    "log tickets", "log bugs", "log tasks",
]

_UPDATE_PHRASES = [
    "update", "change", "modify", "set status", "mark as",
    "move to", "transition", "assign to", "reassign",
]

_SEARCH_PHRASES = [
    "find", "search", "show", "list", "get", "fetch", "retrieve",
    "what are", "which tickets", "show me", "give me",
    "look up", "look for", "pull up",
]

_CHAINED_PHRASES = [
    "and update", "and change", "then update", "then mark", "and mark",
]

_SUBTASK_PHRASES = [
    "create subtask", "add subtask", "add sub-task", "create sub-task",
    "create sub task", "add sub task", "child task",
]

_COMMENT_PHRASES = [
    "get comments", "fetch comments", "show comments", "list comments",
    "view comments", "read comments", "comments on", "comments for",
    "what comments", "ticket comments", "issue comments",
]

_LINK_PHRASES = [
    "link issues", "connect issues", "relate issues", "link tickets",
    "relates to", "blocks", "is blocked by", "duplicate of",
]

_ANALYTICS_PHRASES = [
    "dashboard", "analytics", "chart", "graph", "visualize", "stats",
    "statistics", "overview", "breakdown", "distribution",
    "burndown", "velocity", "trend", "metrics",
    "how many tickets", "how many issues", "count of", "total tickets",
    "project health", "status breakdown", "priority breakdown", "type breakdown",
]

_PROBLEM_PHRASES = [
    "can't see", "cannot see", "can't find", "cannot find",
    "not working", "doesn't work", "does not work", "isn't working",
    "not loading", "won't load", "will not load",
    "broken", "issue with", "problem with",
    "missing", "disappeared", "gone",
]

# BRD detection — explicit first-line triggers
_BRD_FIRST_LINE_PHRASES = [
    "process this brd", "process brd", "parse brd", "parse this brd",
    "process this business requirements", "business requirements document",
    "create epics and stories from", "create epics from this", "create stories from this",
    "this is a brd", "brd document", "process the following brd",
]

# Section names that strongly indicate a structured BRD document
_BRD_SECTION_RE = re.compile(
    r"\b(?:feature breakdown|functional requirements|solution overview|"
    r"acceptance criteria|user journey|tech stack|project overview|"
    r"definition of done|implementation steps|architectural details)\b",
    re.IGNORECASE,
)

_RE_BRD_FIRST_LINE = _compile_word_patterns(_BRD_FIRST_LINE_PHRASES)

# Compiled patterns
_RE_CREATE = _compile_word_patterns(_CREATE_PHRASES)
_RE_UPDATE = _compile_word_patterns(_UPDATE_PHRASES)
_RE_SEARCH = _compile_word_patterns(_SEARCH_PHRASES)
_RE_CHAINED = _compile_word_patterns(_CHAINED_PHRASES)
_RE_SUBTASK = _compile_word_patterns(_SUBTASK_PHRASES)
_RE_COMMENT = _compile_word_patterns(_COMMENT_PHRASES)
_RE_LINK = _compile_word_patterns(_LINK_PHRASES)
_RE_ANALYTICS = _compile_word_patterns(_ANALYTICS_PHRASES)
_RE_PROBLEM = _compile_word_patterns(_PROBLEM_PHRASES)

# Additional link pattern that needs special regex
_RE_LINK_TO = re.compile(r"\blink\b.*\bto\b", re.IGNORECASE)

# "Move the following tickets to In Review" — update phrases use word-boundary
# lists like "move to", which does NOT match when words appear between
# "move" and "to".
_RE_MOVE_TO = re.compile(r"\bmove\b.*\bto\b", re.IGNORECASE)

# Ticket key pattern
_RE_TICKET_KEY = re.compile(r"\b([A-Z]{2,10}-\d+)\b")

# Words that indicate the user is talking about an existing entity, NOT creating
_READ_SIGNAL_PHRASES = [
    "related to", "associated with", "about", "regarding",
    "involving", "pertaining to", "concerning",
    "all tickets", "all issues", "all bugs", "all stories", "all tasks",
    "existing", "current", "open",
]
_RE_READ_SIGNAL = _compile_word_patterns(_READ_SIGNAL_PHRASES)


def _is_brd_document(prompt: str) -> bool:
    """Return True when the prompt looks like a BRD document, not a JIRA query."""
    first_line = prompt.split("\n")[0][:300].lower()
    if _RE_BRD_FIRST_LINE.search(first_line):
        return True
    # Heuristic: long structured document with multiple BRD section names
    if len(prompt) > 1500:
        section_headers = re.findall(r"^#{1,3}\s+\w", prompt, re.MULTILINE)
        brd_sections = _BRD_SECTION_RE.findall(prompt)
        if len(section_headers) >= 3 and len(brd_sections) >= 2:
            return True
    return False


def is_explicit_create_ticket_request(user_prompt: str) -> bool:
    """Return True when the first instruction clearly asks to create tickets."""
    first_line = user_prompt.split("\n")[0][:300].lower()
    return bool(_RE_CREATE.search(first_line)) and not bool(_RE_SEARCH.search(first_line))


# ------------------------------------------------------------------ #
# Core analyzer
# ------------------------------------------------------------------ #

def analyze_intent(user_prompt: str) -> Dict[str, Any]:
    """Analyze user intent to determine the action type.

    Uses the first line/sentence of the prompt as the primary instruction,
    so that embedded content (like a BRD pasted into a create request)
    doesn't override the user's actual intent.

    Key safety rule: when both SEARCH and CREATE signals are present,
    SEARCH wins. A user who says "find all tickets created this week"
    is searching, not creating.
    """
    # BRD check first — a structured requirements document is never a JIRA query
    if _is_brd_document(user_prompt):
        return {"action": ActionType.BRD, "ticket_key": None, "ticket_keys": []}

    first_line = user_prompt.split("\n")[0][:300]
    first_lower = first_line.lower()

    ticket_keys = _RE_TICKET_KEY.findall(user_prompt)
    # Deduplicate while preserving order
    seen = set()
    ticket_keys = [k for k in ticket_keys if not (k in seen or seen.add(k))]
    specific_ticket = ticket_keys[0] if ticket_keys else None

    # Match patterns against first line
    is_subtask = bool(_RE_SUBTASK.search(first_lower))
    is_comment = bool(_RE_COMMENT.search(first_lower))
    is_link = bool(_RE_LINK.search(first_lower)) or bool(_RE_LINK_TO.search(first_lower))
    is_chained = bool(_RE_CHAINED.search(first_lower))
    is_search = bool(_RE_SEARCH.search(first_lower))
    is_create = bool(_RE_CREATE.search(first_lower))
    is_update = bool(_RE_UPDATE.search(first_lower))
    if not is_update and _RE_MOVE_TO.search(first_lower):
        is_update = True
    is_analytics = bool(_RE_ANALYTICS.search(first_lower))
    is_problem = bool(_RE_PROBLEM.search(first_lower))
    has_read_signal = bool(_RE_READ_SIGNAL.search(first_lower))

    # ---------------------------------------------------------- #
    # CRITICAL: Conflict resolution
    # ---------------------------------------------------------- #
    # When SEARCH and CREATE both match, the user is almost always
    # searching.  "Find all tickets created this week" or "list bugs
    # related to KYC" are searches, not creates.
    #
    # CREATE should ONLY win if there is NO search signal AND the
    # create phrase is unambiguous (e.g., "create a new bug for...").
    # ---------------------------------------------------------- #

    if is_search and is_create:
        # Search signal present → override CREATE to SEARCH
        is_create = False

    if has_read_signal and is_create:
        # "related to", "existing", "all tickets" → this is a read, not a write
        is_create = False

    # ---------------------------------------------------------- #
    # Priority routing (subtask > link > chained > analytics >
    # search > create > update > details > problem > unknown)
    # ---------------------------------------------------------- #

    if is_subtask:
        return {"action": ActionType.SUBTASK, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_comment and specific_ticket:
        return {"action": ActionType.GET_COMMENTS, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_link:
        return {"action": ActionType.LINK, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_search and is_chained:
        return {"action": ActionType.SEARCH_AND_UPDATE, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_analytics and not is_create and not is_update and not is_search:
        return {"action": ActionType.ANALYTICS, "ticket_key": None, "ticket_keys": []}

    # Key-focused read requests should return direct ticket details instead of
    # going through SEARCH summarization (which can truncate long descriptions
    # and, more importantly, treat the key as fuzzy summary text).
    #
    # Route to GET_DETAILS when explicit ticket keys are present AND the
    # prompt is not a write/subtask/link/comment AND there is no read-signal
    # phrase like "related to" / "associated with" (those mean: search for
    # OTHER issues that relate to this key, not fetch this key itself).
    if (
        specific_ticket
        and not is_create
        and not is_update
        and not is_chained
        and not is_subtask
        and not is_link
        and not is_comment
        and not has_read_signal
    ):
        return {"action": ActionType.GET_DETAILS, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    # SEARCH before CREATE — safer default
    if is_search:
        return {"action": ActionType.SEARCH, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_create:
        return {"action": ActionType.CREATE, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_update and specific_ticket:
        return {"action": ActionType.UPDATE, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if specific_ticket:
        return {"action": ActionType.GET_DETAILS, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    if is_problem and not is_search and not is_create:
        return {"action": ActionType.ISSUE_REPORT, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}

    return {"action": ActionType.UNKNOWN, "ticket_key": specific_ticket, "ticket_keys": ticket_keys}


# ------------------------------------------------------------------ #
# LLM-based intent classification (fallback + write-op validation)
# ------------------------------------------------------------------ #

_INTENT_CLASSIFICATION_PROMPT = """\
You are an intent classifier for a JIRA assistant. Your ONLY job is to classify
the user's query into exactly one action type.

CRITICAL RULES:
- If the user wants to FIND, LIST, SEARCH, SHOW, or RETRIEVE tickets → action is "search"
- If the user wants to CREATE a NEW ticket that doesn't exist yet → action is "create"
- If the user says "create new ticket(s)", "create JIRA ticket(s)", or
  "use jira_agent to create new tickets" → action is "create"
- If the user wants to MODIFY/UPDATE an existing ticket → action is "update"
- If the user pastes a full Business Requirements Document (BRD) to be parsed into epics/stories → action is "brd"
- Words like "created", "updated", "assigned" when used as FILTERS or ADJECTIVES
  mean the user is SEARCHING (e.g., "find tickets created this week" = search)
- When in doubt, prefer "search" over "create" — searching is safe, creating is not

Valid actions: search, create, update, get_details, get_comments, subtask, link, issue_report, analytics, brd

User query: {query}

Return ONLY a JSON object: {{"action": "<action>", "ticket_key": "<KEY-123 or null>", "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}
JSON:"""


async def analyze_intent_with_llm(user_prompt: str) -> Dict[str, Any]:
    """LLM-based intent classification as fallback when rule-based returns UNKNOWN."""
    from ..services.ai_service import AIService

    try:
        ai = AIService()
        prompt = _INTENT_CLASSIFICATION_PROMPT.replace("{query}", user_prompt[:500])
        raw = await ai.call_genai(prompt=prompt, temperature=0.0, max_tokens=256)

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3].rstrip()

        data = json.loads(raw)
        action_str = data.get("action", "unknown").lower()
        action_map = {
            "create": ActionType.CREATE,
            "update": ActionType.UPDATE,
            "search": ActionType.SEARCH,
            "get_details": ActionType.GET_DETAILS,
            "get_comments": ActionType.GET_COMMENTS,
            "subtask": ActionType.SUBTASK,
            "link": ActionType.LINK,
            "issue_report": ActionType.ISSUE_REPORT,
            "analytics": ActionType.ANALYTICS,
            "brd": ActionType.BRD,
        }
        action = action_map.get(action_str, ActionType.UNKNOWN)
        # Always re-extract keys from the raw prompt — the LLM commonly
        # returns only the first key, but multi-key requests are valid.
        ticket_keys = _RE_TICKET_KEY.findall(user_prompt)
        seen = set()
        ticket_keys = [k for k in ticket_keys if not (k in seen or seen.add(k))]
        ticket_key = data.get("ticket_key") or (ticket_keys[0] if ticket_keys else None)
        confidence = float(data.get("confidence", 0.5))

        return {
            "action": action,
            "ticket_key": ticket_key,
            "ticket_keys": ticket_keys,
            "confidence": confidence,
        }

    except Exception:
        return {"action": ActionType.UNKNOWN, "ticket_key": None, "ticket_keys": [], "confidence": 0.0}


# ------------------------------------------------------------------ #
# Write-operation validation (Layer 2)
# ------------------------------------------------------------------ #

_WRITE_VALIDATION_PROMPT = """\
A JIRA assistant classified the following user query as a "{detected_action}" operation.

Before executing this WRITE operation, verify: does the user ACTUALLY want to
{detected_action} a JIRA ticket? Or are they trying to search/read/list tickets?

CRITICAL: Many queries contain words like "create", "update", "report" as PARTS
of search criteria (e.g., "find tickets created last week"). These are SEARCH
queries, NOT create/update requests.

User query: {query}
Detected action: {detected_action}

Answer with ONLY a JSON object:
{{"is_write_intended": true/false, "correct_action": "search|create|update|...", "reasoning": "<one sentence>"}}
JSON:"""

# Actions that modify JIRA state and need validation
WRITE_ACTIONS = {ActionType.CREATE, ActionType.UPDATE, ActionType.SUBTASK, ActionType.LINK}


async def validate_write_intent(user_prompt: str, detected_action: ActionType) -> Dict[str, Any]:
    """LLM-based validation before any write operation.

    Returns the validated (possibly corrected) intent.  If the LLM
    determines the user actually wants a read, the action is overridden.
    """
    if detected_action not in WRITE_ACTIONS:
        return {"action": detected_action, "validated": True}

    explicit_create = (
        detected_action == ActionType.CREATE
        and is_explicit_create_ticket_request(user_prompt)
    )

    from ..services.ai_service import AIService

    try:
        ai = AIService()
        prompt = (
            _WRITE_VALIDATION_PROMPT
            .replace("{query}", user_prompt[:500])
            .replace("{detected_action}", detected_action.value)
        )
        raw = await ai.call_genai(prompt=prompt, temperature=0.0, max_tokens=200)

        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
        if raw.endswith("```"):
            raw = raw[:-3].rstrip()

        data = json.loads(raw)
        is_write = data.get("is_write_intended", True)

        if not is_write:
            if explicit_create:
                return {"action": ActionType.CREATE, "validated": True, "mandated": True}
            corrected = data.get("correct_action", "search").lower()
            action_map = {
                "search": ActionType.SEARCH,
                "get_details": ActionType.GET_DETAILS,
                "analytics": ActionType.ANALYTICS,
            }
            return {
                "action": action_map.get(corrected, ActionType.SEARCH),
                "validated": True,
                "overridden": True,
                "reasoning": data.get("reasoning", ""),
            }

        return {"action": detected_action, "validated": True}

    except Exception:
        # Unvalidated CREATE is dangerous; other writes failing validation are
        # left unchanged so a real update is not turned into a bogus search.
        if explicit_create:
            return {"action": ActionType.CREATE, "validated": False, "fallback": True, "mandated": True}
        if detected_action == ActionType.CREATE:
            return {"action": ActionType.SEARCH, "validated": False, "fallback": True}
        return {"action": detected_action, "validated": False, "fallback": True}
