"""LLM-backed intent classifier with keyword fallback.

The Workspace context Agent is **read-only** — it never modifies, generates,
or pushes code. Its job is to give the caller deep context about an existing
codebase. The classifier therefore only ever returns one of four intents:

  analyze          — answer a question about the code (Q&A over the repo)
  explain          — explain a concept / pattern observed in the code
  feature_plan     — produce a structured implementation-plan report for one
                     or more product features described by the user
                     (tech stack, related files per feature, architecture,
                     coding patterns, reference files)
  generate_context — split input into features, then surface what already
                     exists in the codebase for each feature (relevant files,
                     symbols, LLM-written context summary per feature)

Anything that *sounds like* a write request ("add an endpoint", "refactor
this", "implement X") is routed to ``feature_plan`` so the user gets the
context and references needed to do the work themselves.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

_CLASSIFY_PROMPT = """\
You are an intent classifier for a READ-ONLY codebase context agent. The
agent never writes, modifies, or pushes code — it only returns context and
references about an existing repository.

Classify the user request as exactly one of:

- analyze          : the user is asking a question about the code that can be
                     answered from the repo (architecture, where something is
                     defined, how a flow works, what a module does)
- explain          : the user wants a concept / pattern explained, possibly
                     grounded in the code
- feature_plan     : the user describes one or more product features they want
                     to add (e.g. "an admin page should be created", "user
                     management portal must be there", "we need OAuth login").
                     Return this whenever the user is *thinking about adding
                     functionality*, even if they phrase it like "add", "build",
                     "implement", or "create" — the agent does not actually
                     write code, it only produces a plan and references.
- generate_context : the user provides a description or list of features and
                     wants to know what ALREADY EXISTS in the codebase for each
                     one (e.g. "generate context for these features",
                     "what exists for user auth and payments", "codebase context
                     for: login, dashboard, reports"). Return this when the user
                     explicitly asks for context, existing code, or a feature
                     breakdown without framing it as something new to build.

Return ONLY valid JSON — no markdown fences, no extra text.

Schema:
{{
  "intent": "analyze" | "explain" | "feature_plan" | "generate_context",
  "confidence": <float 0.0-1.0>,
  "target_files": [<file paths explicitly mentioned, or []>],
  "change_description": "<one sentence summary>"
}}

User request:
{query}

JSON:"""

_VALID_INTENTS = frozenset({"analyze", "explain", "feature_plan", "generate_context"})

_GENERATE_CONTEXT_KEYWORDS = (
    "generate context", "codebase context", "context for features",
    "context for:", "what exists for", "existing code for",
    "show me context", "context per feature", "feature context",
    "break it into features", "break into features",
)

# Phrases that strongly imply a feature-plan report.
_FEATURE_PLAN_KEYWORDS = (
    "feature plan", "implementation plan", "plan to implement",
    "need to be create", "needs to be create", "must be there",
    "must have", "should have an admin", "users management", "user management portal",
    "admin pages", "admin panel", "add the following features",
    "list of features", "and so on",
    # Verbs that classically meant "modify/generate" — for a read-only
    # context agent these all map to feature_plan.
    "add ", "implement", "build a", "build the", "create a", "create the",
    "scaffold", "develop a", "i need a", "i want a", "we need", "we want",
    "refactor", "extend ", "introduce", "support for",
)

_EXPLAIN_KEYWORDS = (
    "explain", "what is", "what's the difference", "describe the concept",
    "how do you", "how would i",
)

_ANALYZE_KEYWORDS = (
    "analyze", "analyse", "what does", "how does", "where is",
    "where do", "which file", "which files", "find ", "locate ",
    "review", "code review", "architecture", "structure",
    "tech stack", "dependencies", "walk me through", "summarize",
    "audit", "overview of", "list ", "show me",
)


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------

def _keyword_fallback(query: str) -> Dict[str, Any]:
    """Deterministic keyword-match classifier used when LLM is unavailable."""
    q = query.lower().strip()

    if any(kw in q for kw in _GENERATE_CONTEXT_KEYWORDS):
        return _result("generate_context", 0.85)

    if any(kw in q for kw in _FEATURE_PLAN_KEYWORDS):
        return _result("feature_plan", 0.85)

    if any(kw in q for kw in _EXPLAIN_KEYWORDS):
        return _result("explain", 0.7)

    if any(kw in q for kw in _ANALYZE_KEYWORDS):
        return _result("analyze", 0.7)

    # Default: treat ambiguous requests as analysis (read-only Q&A)
    return _result("analyze", 0.4)


def _result(
    intent: str,
    confidence: float,
    target_files: List[str] | None = None,
    change_description: str = "",
) -> Dict[str, Any]:
    return {
        "intent": intent,
        "confidence": confidence,
        "target_files": target_files or [],
        "change_description": change_description,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_intent(query: str, use_llm: bool = True) -> Dict[str, Any]:
    """Classify the user's intent into one of the three read-only buckets.

    Returns a dict:
        intent            : "analyze" | "explain" | "feature_plan" | "generate_context"
        confidence        : float
        target_files      : List[str]
        change_description: str
    """
    if not use_llm:
        return _keyword_fallback(query)

    try:
        from agents.Workspace_coding_agent.ai_service import ai_service  # local import

        prompt = _CLASSIFY_PROMPT.format(query=query[:2_000])
        raw = ai_service.call_genai(prompt, max_tokens=256, temperature=0.0)

        raw = re.sub(r"^```[^\n]*\n", "", raw.strip())
        raw = re.sub(r"```$", "", raw.strip())

        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object found in LLM response")

        data = json.loads(json_match.group(0))
        intent = str(data.get("intent", "analyze")).lower().strip()
        if intent not in _VALID_INTENTS:
            intent = "analyze"

        # Deterministic overrides: keyword signals beat LLM classification.
        q_lower = query.lower()
        if any(kw in q_lower for kw in _GENERATE_CONTEXT_KEYWORDS):
            intent = "generate_context"
        elif any(kw in q_lower for kw in _FEATURE_PLAN_KEYWORDS):
            intent = "feature_plan"

        result = {
            "intent": intent,
            "confidence": float(data.get("confidence", 0.5)),
            "target_files": [
                str(f) for f in data.get("target_files", []) if f
            ],
            "change_description": str(data.get("change_description", "")),
        }
        print(
            f"[IntentClassifier] LLM: intent={result['intent']} "
            f"confidence={result['confidence']:.0%}"
        )
        return result

    except Exception as exc:
        print(f"[IntentClassifier] LLM failed ({exc}); using keyword fallback")
        return _keyword_fallback(query)
