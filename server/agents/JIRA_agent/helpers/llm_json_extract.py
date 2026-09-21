"""Parse JSON objects from LLM output (fenced blocks, extra prose, nesting)."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def parse_llm_json_object(text: str) -> Dict[str, Any]:
    """Return the first JSON object found in *text*.

    Handles markdown fences and nested braces (unlike ``\\{[^}]+\\}``).
    """
    if not text or not str(text).strip():
        raise ValueError("empty LLM output")

    s = str(text).strip()
    if s.startswith("```"):
        lines = s.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()

    start = s.find("{")
    if start < 0:
        raise ValueError("no JSON object start")

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(s)):
        c = s[i]
        if in_string:
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = False
            continue
        if c == '"':
            in_string = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])

    raise ValueError("unbalanced JSON braces")


def normalize_jira_update_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten legacy ``updates`` nesting to match ``update_ticket_tool`` / validators."""
    if not isinstance(data, dict):
        return {}
    out = {k: v for k, v in data.items() if k != "updates"}
    nested = data.get("updates")
    if isinstance(nested, dict):
        for key in ("status", "priority", "summary", "description", "labels", "comment", "assignee"):
            inner = nested.get(key)
            if inner is not None and out.get(key) is None:
                out[key] = inner
    return out


def heuristic_jira_status_from_prompt(user_prompt: str) -> Optional[str]:
    """Best-effort status text from phrases like ``to 'In Review' status``."""
    if not user_prompt:
        return None
    m = re.search(r"\bto\s+(.+?)\s+status\b", user_prompt, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    s = m.group(1).strip().strip("'\"")
    return s if s else None
