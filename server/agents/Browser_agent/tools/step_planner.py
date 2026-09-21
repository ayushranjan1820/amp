"""LLM-powered step planner: breaks a natural-language browser task into
structured, executable steps.

Two modes:
1. **Roadmap planner** — generates a high-level outline of goals (no element
   guessing) from the user prompt alone.  Called once at the start.
2. **Step refiner** — given the LIVE page (DOM + screenshot) and the next
   goal from the roadmap, produces a precise, grounded step with real
   element hints drawn from the accessibility tree.  Called before every step.

Supports:
- Session history context for multi-turn conversations
- Observation-aware replanning (closed-loop feedback)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1) Roadmap planner — produces high-level goals WITHOUT page context
# ---------------------------------------------------------------------------

ROADMAP_SYSTEM_PROMPT = """\
You are a browser-automation planner.  The user will describe one or more
actions they want performed inside a web browser.

Your job is to produce a **JSON array** of high-level goal objects.  Each goal
is a short description of WHAT needs to happen — you do NOT need to specify
exact CSS selectors, element names, or ARIA roles because you cannot see the
page yet.

### Goal schema
```json
{
  "step_number": <int>,
  "action": "<navigate | search | click | type | scroll | select | wait | verify | extract | add_to_cart | custom>",
  "description": "<human-readable description of the goal — be specific about WHAT to click/type but do NOT guess element selectors>",
  "target_url": "<url or null — only for navigate>",
  "search_query": "<text to type into a search box, if applicable>",
  "value": "<value to type/select, if applicable>",
  "condition": "<optional condition to check, e.g. 'price < 10000'>",
  "expected_outcome": "<what should be true after this goal succeeds>"
}
```

### Rules
1. First goal should always be `navigate` to the target website (full URL).
   **Exception:** If session history shows the browser is already on the right page, skip.
2. Break complex actions into small, atomic goals (one click = one goal).
3. Include explicit `wait` goals after page loads or searches.
4. **Do NOT guess CSS selectors, ARIA roles, or element names.** You cannot
   see the page.  Just describe the goal in plain English.  A downstream
   system with full page visibility will handle the exact selectors.
5. For **dropdown / combobox** interactions, split into TWO separate goals:
   (a) "Open the <name> dropdown/combobox" (b) "Select <value> from the
   open dropdown".  Never combine open + select into one goal.
6. Return ONLY the JSON array — no markdown fences, no commentary.
7. Every goal MUST have an `expected_outcome`.

### AI chatbot interaction (ChatGPT, Claude, Gemini, etc.)
When the task involves typing into an AI chatbot and reading its response:
1. `navigate` to the chatbot URL.
2. `wait` — "Wait for the chat interface to fully load" (these are heavy SPAs).
3. `type` — "Type the message into the chat composer". AI chatbot composers are
   **contenteditable / rich-text editors** — `fill` WILL NOT work.  Always use `type`.
4. `click` — "Click the Send button" OR use action `type` with description "Press Enter to send".
5. `wait` — "Wait for the AI response to finish streaming". This is CRITICAL — AI
   responses stream for 10–120+ seconds.  The downstream system has a
   `wait_for_text_stable` action specifically for this.
6. `extract` — "Extract the full text of the AI response".

### Cross-site data transfer
When the task requires reading content from one website and using it on another:
- Use action `wait` with description "Wait for dynamic content to finish loading/streaming"
  before extracting (e.g. for ChatGPT or AI chatbot responses).
- Use action `extract` with description "Extract/remember the <content> from the page"
  to capture text for use on another site.  Be specific about WHAT to extract.
- When typing extracted content on the target site, use action `type` with description
  "Type the previously extracted content into the <editor/field>".
  The downstream system will handle variable injection automatically.

### Rich text / contenteditable editors
**ChatGPT, Claude, LinkedIn, Gmail, Notion, Medium, Slack** and most modern web
apps use `contenteditable` divs (NOT `<textarea>` or `<input>`).
- Always use action `type` (not `search` or `click`) to input content.
- The downstream system will use `type_text` which works on contenteditable editors.
"""

# ---------------------------------------------------------------------------
# 2) Step refiner — takes a roadmap goal + LIVE page → precise step
# ---------------------------------------------------------------------------

REFINER_SYSTEM_PROMPT = """\
You are a browser-automation step refiner.  You are given:
- A high-level **goal** describing what needs to happen
- The **current page state**: URL, accessibility tree, visible text, key
  interactive elements with bounding boxes, form state
- A **viewport screenshot** of the current browser state (if attached).
  **LOOK AT THE SCREENSHOT FIRST.** It is your most reliable source of
  truth — use what you SEE to identify the right elements, their exact
  labels, and the current page state (loading, streaming, modal open, etc.).
- The **original user task** for broader context

Your job: refine the goal into a **precise, grounded step** that references
real elements visible on the current page.

### Output schema (JSON object)
```json
{
  "step_number": <int>,
  "action": "<navigate | search | click | type | scroll | select | wait | verify | extract | add_to_cart | custom>",
  "description": "<precise description using actual element text from the page>",
  "target_url": "<url or null>",
  "search_query": "<text or null>",
  "element_hint": "<actual element text, label, or CSS selector you found in the snapshot>",
  "value": "<value or null>",
  "condition": "<condition or null>",
  "expected_outcome": "<what should be true after this step>"
}
```

### Rules
1. **Ground every element reference in the page context.**  If the goal says
   "click Repositories in the sidebar" — find the actual link/button in the
   accessibility tree or key_elements list that matches.  Use its exact text.
2. Set `element_hint` to the **real text, ARIA label, or CSS selector** you
   found in the snapshot.  Never invent selectors.
3. If the goal cannot be accomplished on the current page (e.g. the element
   doesn't exist), return `"action": "scroll"` to reveal more content, or
   adjust the step to what IS possible (e.g. navigate first).
4. For **dropdowns**: if the goal is "open the dropdown", look for combobox /
   button with `aria-expanded`, `aria-haspopup`, `data-state`, or similar.
   Set `element_hint` to the exact selector or name.  If the goal is "select
   from open dropdown", look for the actual `role=option` / `role=menuitem`
   elements NOW visible in the tree.
5. For **extract** goals: set `element_hint` to the CSS selector or ARIA name
   of the element whose text should be extracted.  Be precise — the downstream
   system will use `extract_text` on this exact element.
6. For **type** goals on rich text editors (contenteditable): set `element_hint`
   to the editor element selector.  The downstream system will use `type_text`
   instead of `fill` for these editors.  Look for elements with
   `contenteditable="true"` or `role="textbox"` in the key_elements list.
7. For **wait** goals on streaming AI content (ChatGPT, Claude, etc.): set
   `element_hint` to the CSS selector of the response container so the
   downstream system can use `wait_for_text_stable` on it.
8. Return ONLY the JSON object — no markdown fences, no commentary.
"""

# ---------------------------------------------------------------------------
# 3) Observation replanner (unchanged logic, better prompt)
# ---------------------------------------------------------------------------

REPLAN_SYSTEM_PROMPT = """\
You are a browser-automation re-planner. After executing some steps, the page
state has changed. Given the current observation (URL, visible text, form state)
and the remaining goals, decide:

1. Are the remaining goals still valid for the current page state?
2. If not, produce a corrected JSON array of goals.

**Return ONLY a JSON object** with this shape:
{
  "needs_replan": true or false,
  "reason": "short explanation",
  "steps": [ /* corrected goal objects if needs_replan is true, else empty */ ]
}

If the remaining goals are still valid, return {"needs_replan": false, "reason": "...", "steps": []}.
No markdown fences, no commentary — JSON only.

**Each object in `steps` MUST use these field names:**
- `step_number` (int), `action` (navigate|search|click|type|scroll|select|wait|verify|add_to_cart|custom),
- `description` (required, non-empty string — what to do).
- optional: `target_url`, `search_query`, `element_hint`, `value`, `condition`, `expected_outcome`.
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json_array(text: str) -> List[Dict[str, Any]]:
    """Best-effort extraction of a JSON array from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.error("Failed to parse step plan from LLM output:\n%s", text[:500])
    return []


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Best-effort extraction of a JSON object from LLM output."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    return {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def plan_roadmap(
    ai_service,
    user_prompt: str,
    session_history: str = "",
) -> List[Dict[str, Any]]:
    """Generate a high-level roadmap of goals (no page context needed).

    This replaces the old ``parse_steps_from_prompt`` as the initial planner.
    The roadmap is a sequence of *what* to do; the step refiner later grounds
    each goal against the live page.
    """
    context_block = ""
    if session_history:
        context_block = f"\n{session_history}\n"

    full_prompt = (
        f"System: {ROADMAP_SYSTEM_PROMPT}\n\n"
        f"{context_block}"
        f"User: {user_prompt}"
    )
    print(f"[BrowserPlanner] Planning roadmap for: {user_prompt[:120]}")
    raw = ai_service.call_genai(full_prompt, temperature=0.2, max_tokens=4096)
    goals = _extract_json_array(raw)

    for i, goal in enumerate(goals):
        goal.setdefault("step_number", i + 1)
        goal.setdefault("expected_outcome", "")

    print(f"[BrowserPlanner] Roadmap: {len(goals)} goal(s) planned")
    for g in goals:
        print(f"  [{g.get('action', '?')}] {g.get('description', '?')[:100]}")
    return goals


# Keep backward-compatible alias
parse_steps_from_prompt = plan_roadmap


def refine_step_with_page_context(
    ai_service,
    goal: Dict[str, Any],
    page_context: str,
    original_query: str = "",
    screenshot_png: bytes = None,
) -> Dict[str, Any]:
    """Refine a roadmap goal into a precise step using LIVE page context + vision.

    *page_context* is the formatted snapshot string from ``format_snapshot_for_llm``.
    *screenshot_png* is the raw viewport screenshot bytes (sent via vision API).

    Returns a refined step dict with grounded element_hint.
    """
    step_num = goal.get("step_number", 0)
    action = goal.get("action", "custom")
    description = goal.get("description", "")

    user_msg = (
        f"Original user task: {original_query}\n\n"
        f"Current goal (step {step_num}): [{action}] {description}\n"
    )
    if goal.get("target_url"):
        user_msg += f"Target URL: {goal['target_url']}\n"
    if goal.get("search_query"):
        user_msg += f"Search query: {goal['search_query']}\n"
    if goal.get("value"):
        user_msg += f"Value: {goal['value']}\n"
    if goal.get("condition"):
        user_msg += f"Condition: {goal['condition']}\n"
    if goal.get("expected_outcome"):
        user_msg += f"Expected outcome: {goal['expected_outcome']}\n"

    user_msg += f"\n--- LIVE page context ---\n{page_context}\n"

    full_prompt = f"System: {REFINER_SYSTEM_PROMPT}\n\nUser: {user_msg}"

    print(
        f"[BrowserPlanner] Refining step {step_num} [{action}] with LIVE page context "
        f"({'+ screenshot' if screenshot_png else 'text-only'}) | "
        f"prompt={len(full_prompt)} chars"
    )

    raw = ai_service.call_genai(
        full_prompt,
        temperature=0.1,
        max_tokens=2048,
        screenshot_png=screenshot_png,
    )

    refined = _extract_json_object(raw)
    if not refined:
        print(f"[BrowserPlanner] WARNING: refiner returned no JSON, using original goal")
        return goal

    # Carry over fields from the original goal that the refiner didn't set
    for key in ("step_number", "action", "target_url", "search_query", "value",
                "condition", "expected_outcome"):
        if key not in refined or refined[key] is None:
            refined[key] = goal.get(key)

    # Ensure required fields
    refined.setdefault("step_number", step_num)
    refined.setdefault("action", action)
    refined.setdefault("description", description)

    hint = refined.get("element_hint", "")
    print(
        f"[BrowserPlanner] Refined step {step_num}: [{refined.get('action')}] "
        f"{refined.get('description', '')[:100]} | element_hint={hint[:80] if hint else '(none)'}"
    )
    return refined


def check_observation_replan(
    ai_service,
    observation_summary: str,
    remaining_steps: List[Dict[str, Any]],
    original_query: str,
) -> tuple[bool, List[Dict[str, Any]]]:
    """Ask LLM whether the remaining goals are still valid given the observation.

    Returns (needs_replan, new_steps).
    """
    remaining_desc = "\n".join(
        f"  {s.get('step_number')}. [{s.get('action')}] {s.get('description')}"
        for s in remaining_steps
    )
    prompt = (
        f"System: {REPLAN_SYSTEM_PROMPT}\n\n"
        f"User:\n"
        f"Original task: {original_query}\n\n"
        f"--- Current page observation ---\n{observation_summary}\n\n"
        f"--- Remaining planned goals ---\n{remaining_desc}\n\n"
        "Should the remaining goals be adjusted for the current page state?"
    )
    try:
        raw = ai_service.call_genai(prompt, temperature=0.15, max_tokens=4096)
        data = _extract_json_object(raw)

        if not data.get("needs_replan", False):
            print(f"[BrowserPlanner] Observation check: remaining goals still valid")
            return False, remaining_steps

        new_steps = data.get("steps", [])
        if not isinstance(new_steps, list) or not new_steps:
            print(f"[BrowserPlanner] Replan returned empty — keeping original")
            return False, remaining_steps

        base = remaining_steps[0].get("step_number", 1) if remaining_steps else 1
        for i, s in enumerate(new_steps):
            s["step_number"] = base + i
            s.setdefault("expected_outcome", "")

        print(
            f"[BrowserPlanner] Observation replan: {len(remaining_steps)} goals -> "
            f"{len(new_steps)} | reason: {data.get('reason', '?')[:100]}"
        )
        return True, new_steps

    except Exception as exc:
        print(f"[BrowserPlanner] Observation replan failed: {exc} — keeping original")
        return False, remaining_steps
