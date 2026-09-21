"""Playwright execution: LLM emits **JSON DSL only**; a deterministic mapper runs actions.

Closed-loop plan–act–observe: periodic observation replanning, grounded post-condition checks,
and native async Playwright when using ``BrowserPool.async_acquire_page``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# (event, data) -> None; event is "thinking" | "progress" for SSE UI
SSEEmit = Optional[Callable[[str, Dict[str, Any]], None]]

from .action_dsl import (
    MAX_ACTIONS_PER_STEP,
    DSLBundle,
    async_execute_dsl_actions,
    execute_dsl_actions,
    parse_dsl_bundle,
    resolve_bundle_variables,
    ExtractTextAction,
    TypeTextAction,
    WaitForSelectorAction,
    WaitForTextStableAction,
)
from .page_snapshot import (
    async_capture_page_snapshot,
    capture_page_snapshot,
    format_snapshot_for_llm,
    summarize_observation,
)
from .step_planner import check_observation_replan, refine_step_with_page_context

logger = logging.getLogger(__name__)

REPLAN_AFTER_EVERY_N_STEPS = 2
MAX_OBSERVATION_REPLANS = 6

LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

SCREENSHOT_DIR = LOGS_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def screenshot_overlays_from_observation(obs: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build UI overlay payloads from DSL action records (viewport pixel coords)."""
    if not obs:
        return []
    executed = obs.get("executed")
    if not isinstance(executed, list):
        return []
    out: List[Dict[str, Any]] = []
    for ea in executed:
        rect = ea.get("target_rect")
        if not isinstance(rect, dict):
            continue
        if not all(k in rect for k in ("x", "y", "width", "height")):
            continue
        try:
            out.append(
                {
                    "kind": str(ea.get("target_kind", "click")),
                    "label": ea.get("target_label"),
                    "x": float(rect["x"]),
                    "y": float(rect["y"]),
                    "width": float(rect["width"]),
                    "height": float(rect["height"]),
                }
            )
        except (TypeError, ValueError):
            continue
    # If the step navigated, earlier bounding boxes refer to the old document — keep only the last hit.
    url_before = (obs or {}).get("url_before") or ""
    url_after = (obs or {}).get("url_after") or ""
    if url_before != url_after and len(out) > 1:
        return [out[-1]]
    return out

DSL_GEN_SYSTEM = """\
You are a browser automation planner that outputs **only valid JSON** (no markdown fences).

Given:
- One high-level step (action + description) from a larger plan
- Current page URL
- Accessibility tree (truncated) + visible text + rough interactive element counts
- Optionally, a **stored data** section listing variables extracted from previous steps

Output a single JSON object:
{
  "actions": [ /* ordered list of primitive actions */ ],
  "notes": "optional short reasoning",
  "parallel": false
}
Optional: set `"parallel": true` only when several **independent** `fill_placeholder` / `fill_role` / `fill_label` actions can run together (same page, no ordering dependency).

### Allowed primitive types (use only these `type` values)

1. `goto` — { "type": "goto", "url": "https://..." }
2. `wait_ms` — { "type": "wait_ms", "ms": 500 }  (ms must be 0–30000)
3. `wait_load` — { "type": "wait_load", "state": "domcontentloaded" | "load" | "networkidle" }
4. `click_role` — { "type": "click_role", "role": "button"|"link"|"textbox"|"combobox"|"checkbox"|"radio"|"tab"|"menuitem"|"option"|"listbox"|"menu"|"switch", "name": "visible label", "exact": false, "nth": 0 } — optional `nth` (0-based) when several nodes share the same role+name
5. `click_text` — { "type": "click_text", "text": "substring on page", "exact": false, "nth": 0 } — optional `nth` when the same visible text appears more than once
6. `fill_placeholder` — { "type": "fill_placeholder", "placeholder": "placeholder attr", "value": "text to type" } — **ONLY works on `<input>` and `<textarea>` elements with an actual HTML `placeholder` attribute.** Does NOT work on contenteditable divs (LinkedIn, ChatGPT, Notion, etc.) even if they show placeholder-like text — use `type_text` instead.
7. `fill_role` — { "type": "fill_role", "role": "textbox"|"searchbox"|"combobox", "name": "optional accessible name", "value": "text" } — **ONLY for native `<input>`/`<textarea>`.** NOT for contenteditable editors — use `type_text`.
8. `fill_label` — { "type": "fill_label", "label": "label text e.g. Search Amazon.in", "value": "query", "exact": false } — **ONLY for native `<input>`/`<textarea>`.** NOT for contenteditable editors — use `type_text`.
9. `press` — { "type": "press", "key": "Enter" } — supports key combos: "Control+a", "Control+c", "Control+v", "Meta+a", "Shift+Enter", etc.
10. `scroll` — { "type": "scroll", "delta_y": 400 }
11. `assert_text_contains` — { "type": "assert_text_contains", "text": "substring that must appear" }
12. `select_option` — { "type": "select_option", "selector": "#sort-select", "label": "Price: Low to High" } — for native <select> dropdowns. Use `value`, `label`, or `index`.
13. `click_css` — { "type": "click_css", "selector": ".a-dropdown-container .a-button-dropdown", "force": false } — fallback for custom widgets when role/text selectors fail.
14. `hover` — { "type": "hover", "selector": ".dropdown-trigger" } or { "type": "hover", "role": "button", "name": "Sort" } — trigger menus/dropdowns/tooltips before clicking.
15. `evaluate_condition` — { "type": "evaluate_condition", "condition": "price is under 10000", "extract_selector": ".a-price .a-offscreen" } — complex conditions evaluated by LLM post-execution.
16. `extract_text` — { "type": "extract_text", "selector": ".response-content", "store_as": "my_var_name" } — extract inner text from an element and store it for later steps. Use `{{my_var_name}}` in any string field of later actions to inject the stored text. Optional `max_length` (default 50000).
17. `type_text` — { "type": "type_text", "text": "text or {{var}}", "selector": ".editor", "delay_ms": 0 } — type text character-by-character into the focused element. Works on contenteditable / rich text editors where `fill_*` fails. `selector` (optional) clicks to focus first. `delay_ms` 0 = instant paste, >0 = simulated typing speed. Use `{{var_name}}` to inject stored data.
18. `wait_for_selector` — { "type": "wait_for_selector", "selector": ".result-text", "state": "visible", "timeout_ms": 30000 } — wait up to timeout for an element to become visible/attached/hidden/detached.
19. `wait_for_text_stable` — { "type": "wait_for_text_stable", "selector": ".streaming-response", "timeout_ms": 120000, "stable_ms": 8000 } — wait until the text inside an element stops changing (ideal for streaming AI responses). Polls every 500ms; considers text stable when unchanged for `stable_ms`. For AI chatbots use `timeout_ms` 90000–120000 and `stable_ms` 6000–10000 (they pause mid-stream).
20. Optional on `click_role` / `click_text`: `"force": true` if a cookie bar or overlay blocks clicks; `"nth": 0` (or 1, 2, …) to pick the Nth match when duplicates exist.

### Cross-step data variables
- `extract_text` stores text under a variable name (e.g. `store_as: "ai_response"`).
- In ANY later action, use `{{ai_response}}` in string fields (`text`, `value`, `url`, etc.) to inject the stored text.
- The **Stored data** section in the page context shows available variables and a preview of their contents.
- For cross-site workflows (e.g. read from site A, paste on site B): extract_text on site A → navigate to site B → type_text with `{{var_name}}`.

### Rules
- At most """ + str(MAX_ACTIONS_PER_STEP) + """ actions. Prefer fewer, robust steps.
- Use `click_role` / `fill_placeholder` / `fill_label` / `fill_role` with `searchbox` when the page has real `<input>` / `<textarea>` elements.
- **⚠️ CRITICAL — contenteditable / rich text editors: NEVER use `fill_placeholder`, `fill_role`, or `fill_label` on them.**
  Sites like **LinkedIn, ChatGPT, Claude, Gmail, Notion, Medium, Slack** use `contenteditable` divs.
  These may display placeholder-like text (e.g. "What do you want to talk about?") but it is NOT an HTML `placeholder` attribute — `fill_placeholder` will time out.
  The key_elements list will show `"contenteditable": "true"` for these elements.
  **Always use `type_text`** with a CSS `selector` targeting the contenteditable element or its container (e.g. `[contenteditable="true"]`, `[role="textbox"]`, `.editor-container`).
- For **streaming / dynamic content** (ChatGPT, Claude, Gemini, AI chatbots): use `wait_for_text_stable` to wait for the response to finish streaming before extracting. Use `timeout_ms: 120000` (2 min) and `stable_ms: 8000` (8 sec) for AI responses — they can pause mid-stream.
- **AI chatbot composers** (ChatGPT, Claude, etc.) are `contenteditable` divs, NOT `<textarea>`. Use `type_text` with `selector` pointing to the contenteditable element. After typing, send with `press Enter` or `click_role button "Send"`.
- For **clipboard operations**, use `press` with combos: `"Control+a"` (select all), `"Control+c"` (copy), `"Control+v"` (paste).
- After `goto`, include `wait_ms` (1500–4000) for heavy sites.
- **Dropdowns / Sort controls:** Use `select_option` for native `<select>`. For custom dropdowns, use the combobox/option strategy below.
- **Custom triage / status / filter dropdowns (NOT `<select>`):** Do **not** use `select_option` unless the snapshot shows a real HTML `<select>`. Strategy:
  (1) Open the trigger: `click_role combobox` or `click_css` on the trigger.
  (2) `wait_ms` 500–1000.
  (3) `click_role option` → `click_role menuitem` → `click_text` → `click_css`.
  Use `nth` to disambiguate when trigger and option share text.
- For **price/condition checks**, prefer `evaluate_condition` with `extract_selector`.
- Do not invent URLs; use the step's target_url only when the step is navigate.
- Output **raw JSON only** — no ``` fences, no commentary.
"""

DSL_VISION_ADDON = """
### Vision (screenshot attached — USE IT as your PRIMARY signal)
A **viewport screenshot** of the current browser state is attached. This is your most reliable source of truth.

**IMPORTANT — How to use the screenshot:**
1. First LOOK at the screenshot carefully. Identify what page/site you're on, what UI elements are visible, where the input fields / buttons / editors are.
2. Reason about the CURRENT state: Is there a chat composer? Is it a rich-text `contenteditable` editor or a plain `<textarea>`? Is there a loading spinner? Is content still streaming? Is there a modal/overlay blocking the page?
3. Based on what you SEE, decide the best action. The screenshot is ground truth — if an element looks like X in the screenshot, trust that over the accessibility tree.

**Priority order for deciding selectors:**
1. **What you SEE in the screenshot** — button labels, search fields, dropdown triggers, product titles, chat input areas as they visually appear
2. **Accessibility tree** — ARIA roles and names that match what you see
3. **Key interactive elements list** — CSS selectors with bounding boxes

**Critical rules when using vision:**
- If the screenshot shows a **chat composer / message input** (ChatGPT, Claude, Slack, etc.), it is almost certainly a `contenteditable` div. Use `type_text` with the appropriate selector, NOT `fill_*`.
- If you see a **streaming/typing indicator** (animated dots, cursor blinking in a response area), the page content is still loading — use `wait_for_text_stable` before extracting.
- If a dropdown LOOKS like a custom styled widget (not a plain `<select>`), use `hover` on the visible trigger first, then `click_css` or `click_role` on the revealed option.
- For **triage/status** style controls: open with `combobox` + current label, then `menuitem` + desired label; insert `wait_ms` between open and pick; use `nth` if duplicate text confuses the locator.
- If you see a `<select>` dropdown, use `select_option` with its CSS selector — NEVER `click_text` on `<option>` elements.
- Match button/link text EXACTLY as you see it rendered (including case, icons, special characters).
- If the element you need is below the fold (not visible in screenshot), `scroll` first.

Use `notes` in your JSON to briefly explain what you saw in the screenshot and why you chose these actions.

Output **only** the same JSON object shape as above.
"""


def _safe_page_text(page, max_chars: int = 2500) -> str:
    try:
        text = page.inner_text("body")
        return text[:max_chars]
    except Exception:
        return "(unable to read page text)"


async def _async_safe_page_text(page, max_chars: int = 2500) -> str:
    try:
        text = await page.inner_text("body")
        return text[:max_chars]
    except Exception:
        return "(unable to read page text)"


def build_dom_context(page) -> str:
    """Structured page snapshot for LLM prompts (sync Page)."""
    snap = capture_page_snapshot(page)
    return format_snapshot_for_llm(snap)


async def build_dom_context_async(page) -> str:
    snap = await async_capture_page_snapshot(page)
    return format_snapshot_for_llm(snap)


_STOPWORDS = frozenset({
    "the", "and", "for", "page", "that", "with", "from", "this", "should", "shows", "show",
    "user", "can", "see", "have", "been", "will", "after", "step", "must", "would", "could",
    "http", "https", "www", "com",
})


def grounded_verify_postcondition(
    expected_outcome: str,
    visible_text: str,
    title: str = "",
) -> Tuple[bool, str]:
    """Check page text/title against planner ``expected_outcome`` (quoted phrases or keyword overlap)."""
    exp = (expected_outcome or "").strip()
    if not exp:
        return True, ""

    hay = f"{title}\n{visible_text}".lower()
    text_lower = visible_text.lower()

    quoted = re.findall(r"['\"]([^'\"]{2,120})['\"]", exp)
    if quoted:
        for q in quoted:
            if q.lower() in hay:
                return True, f"found expected phrase: {q[:80]}"
        return False, f"page missing expected text from plan: {quoted[:5]}"

    alternatives = re.split(r"\s+or\s+", exp, flags=re.I)
    best_hit = 0
    best_total = 0
    for alt in alternatives:
        alt = alt.strip()
        if len(alt) < 4:
            continue
        words = [w.lower() for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]{3,}", alt)]
        words = [w for w in words if w not in _STOPWORDS][:10]
        if not words:
            continue
        hit = sum(1 for w in words if w in hay)
        if hit > best_hit:
            best_hit = hit
            best_total = len(words)
        need = max(1, (len(words) + 2) // 3)
        if hit >= need:
            return True, f"keyword match {hit}/{len(words)} for clause"

    if best_total and best_hit >= max(1, best_total // 4):
        return True, f"weak keyword match {best_hit}/{best_total}"

    if len(exp) <= 100 and exp.lower() in hay:
        return True, "full expected_outcome substring present"

    return False, f"post-condition not met (expected: {exp[:120]})"


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("No JSON object found in model output")


def _dsl_linkedin_stored_text_hint(page_url: str, action: str, data_store_ctx: str) -> str:
    """On the first DSL attempt, steer the model away from fill_* on LinkedIn post composers."""
    if action != "type" or not (data_store_ctx or "").strip():
        return ""
    try:
        u = (page_url or "").lower()
    except Exception:
        return ""
    if "linkedin.com" not in u:
        return ""
    return (
        "\n**LinkedIn + stored extract:** The post composer is **contenteditable** — do NOT use "
        "fill_placeholder, fill_role, or fill_label. Use **type_text** with `text` set to the "
        "`{{variable_name}}` from **Stored data** (exact name) and a CSS `selector` for the "
        "editor inside the **post modal** (visible `[contenteditable=\"true\"]` / main post body). "
        "If the modal may still be opening, add **wait_for_selector** for that editor first. "
        "Use `delay_ms`: 0 for long pasted content.\n"
    )


def _critic_ok(
    ai_service,
    step: Dict[str, Any],
    observation: Dict[str, Any],
    page_text_snippet: str,
) -> bool:
    """Lightweight LLM check: did the step likely succeed? Default True on parse failure."""
    prompt = (
        "You validate a single browser automation step. Reply with JSON only: "
        '{"ok": true or false, "reason": "one short sentence"}\n\n'
        f"Step action: {step.get('action')}\n"
        f"Step description: {step.get('description')}\n"
        f"URL before: {observation.get('url_before')}\n"
        f"URL after: {observation.get('url_after')}\n"
        f"condition_met (if any): {observation.get('condition_met')}\n"
        f"Executed action types: {[e.get('type') for e in observation.get('executed', [])]}\n"
        f"Visible text snippet:\n{page_text_snippet[:1500]}\n"
    )
    try:
        raw = ai_service.call_genai(
            f"System: You only output valid JSON.\n\nUser: {prompt}",
            temperature=0,
            max_tokens=256,
        )
        data = extract_json_object(raw)
        return bool(data.get("ok", True))
    except Exception:
        return True


_VAR_RE = re.compile(r"\{\{([a-zA-Z_][a-zA-Z0-9_]*)\}\}")


def _py_value_for_text(text: str, known_vars: Optional[set] = None) -> str:
    """Return a Python expression string for a text value.

    If the text is exactly ``{{var}}`` and var is known, returns the bare
    variable name.  If the text contains ``{{var}}`` mixed with other
    content, returns an f-string.  Otherwise returns a json.dumps literal.
    """
    if not known_vars or not _VAR_RE.search(text):
        return json.dumps(text)

    refs = _VAR_RE.findall(text)
    recognized = [r for r in refs if r in known_vars]
    if not recognized:
        return json.dumps(text)

    stripped = text.strip()
    if _VAR_RE.fullmatch(stripped) and stripped[2:-2] in known_vars:
        return stripped[2:-2]

    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    for var in recognized:
        escaped = escaped.replace("{{" + var + "}}", "{" + var + "}")
    return f'f"{escaped}"'


def bundle_to_playwright_lines(
    bundle: DSLBundle,
    indent: str = "        ",
    known_vars: Optional[set] = None,
) -> List[str]:
    """Emit Playwright Python lines equivalent to the DSL (for export script).

    *known_vars*: set of Python variable names created by earlier
    ``extract_text`` actions. When present, ``{{var}}`` references in
    ``type_text`` / ``fill_*`` actions are emitted as live Python variable
    references instead of resolved string literals.
    """
    from .action_dsl import (
        AssertTextContainsAction,
        ClickCssAction,
        ClickRoleAction,
        ClickTextAction,
        EvaluateConditionAction,
        FillLabelAction,
        FillPlaceholderAction,
        FillRoleAction,
        GotoAction,
        HoverAction,
        PressAction,
        ScrollAction,
        SelectOptionAction,
        WaitLoadAction,
        WaitMsAction,
    )

    lines: List[str] = []
    for act in bundle.actions:
        if isinstance(act, GotoAction):
            lines.append(
                f"{indent}page.goto({json.dumps(act.url)}, wait_until=\"domcontentloaded\", timeout=30000)"
            )
        elif isinstance(act, WaitMsAction):
            lines.append(f"{indent}page.wait_for_timeout({act.ms})")
        elif isinstance(act, WaitLoadAction):
            lines.append(
                f"{indent}page.wait_for_load_state({json.dumps(act.state)}, timeout=30000)"
            )
        elif isinstance(act, ClickRoleAction):
            _tgt = f".nth({act.nth})" if act.nth is not None else ".first"
            lines.append(
                f"{indent}page.get_by_role({json.dumps(act.role)}, name={json.dumps(act.name)}, "
                f"exact={act.exact}){_tgt}.scroll_into_view_if_needed(timeout=30000)"
            )
            lines.append(
                f"{indent}page.get_by_role({json.dumps(act.role)}, name={json.dumps(act.name)}, "
                f"exact={act.exact}){_tgt}.click(timeout=30000, force={act.force})"
            )
        elif isinstance(act, ClickTextAction):
            _tgt = f".nth({act.nth})" if act.nth is not None else ".first"
            lines.append(
                f"{indent}page.get_by_text({json.dumps(act.text)}, exact={act.exact}){_tgt}.scroll_into_view_if_needed(timeout=30000)"
            )
            lines.append(
                f"{indent}page.get_by_text({json.dumps(act.text)}, exact={act.exact}){_tgt}.click(timeout=30000, force={act.force})"
            )
        elif isinstance(act, FillPlaceholderAction):
            val_expr = _py_value_for_text(act.value, known_vars)
            lines.append(
                f"{indent}page.get_by_placeholder({json.dumps(act.placeholder)}).first.scroll_into_view_if_needed(timeout=30000)"
            )
            lines.append(
                f"{indent}page.get_by_placeholder({json.dumps(act.placeholder)}).first.fill("
                f"{val_expr}, timeout=30000)"
            )
        elif isinstance(act, FillRoleAction):
            val_expr = _py_value_for_text(act.value, known_vars)
            if act.name:
                lines.append(
                    f"{indent}page.get_by_role({json.dumps(act.role)}, name={json.dumps(act.name)}).first.scroll_into_view_if_needed(timeout=30000)"
                )
                lines.append(
                    f"{indent}page.get_by_role({json.dumps(act.role)}, name={json.dumps(act.name)}).first.fill("
                    f"{val_expr}, timeout=30000)"
                )
            else:
                lines.append(
                    f"{indent}page.get_by_role({json.dumps(act.role)}).first.scroll_into_view_if_needed(timeout=30000)"
                )
                lines.append(
                    f"{indent}page.get_by_role({json.dumps(act.role)}).first.fill("
                    f"{val_expr}, timeout=30000)"
                )
        elif isinstance(act, FillLabelAction):
            val_expr = _py_value_for_text(act.value, known_vars)
            lines.append(
                f"{indent}page.get_by_label({json.dumps(act.label)}, exact={act.exact}).first.scroll_into_view_if_needed(timeout=30000)"
            )
            lines.append(
                f"{indent}page.get_by_label({json.dumps(act.label)}, exact={act.exact}).first.fill("
                f"{val_expr}, timeout=30000)"
            )
        elif isinstance(act, PressAction):
            lines.append(f"{indent}page.keyboard.press({json.dumps(act.key)})")
        elif isinstance(act, ScrollAction):
            lines.append(f"{indent}page.mouse.wheel(0, {act.delta_y})")
        elif isinstance(act, AssertTextContainsAction):
            # Runtime does not hard-fail this action; keep export behavior aligned.
            lines.append(
                f"{indent}_contains = {json.dumps(act.text)} in page.locator(\"body\").inner_text(timeout=10000)"
            )
            lines.append(
                f"{indent}print('assert_text_contains:', 'OK' if _contains else 'MISS', {json.dumps(act.text)})"
            )
        elif isinstance(act, SelectOptionAction):
            kwargs_parts = []
            if act.value is not None:
                kwargs_parts.append(f"value={json.dumps(act.value)}")
            elif act.label is not None:
                kwargs_parts.append(f"label={json.dumps(act.label)}")
            elif act.index is not None:
                kwargs_parts.append(f"index={act.index}")
            lines.append(f"{indent}_sel = page.locator({json.dumps(act.selector)}).first")
            lines.append(f"{indent}_sel.wait_for(state=\"visible\", timeout=30000)")
            lines.append(
                f"{indent}page.locator({json.dumps(act.selector)}).select_option({', '.join(kwargs_parts)}, timeout=30000)"
            )
        elif isinstance(act, ClickCssAction):
            lines.append(
                f"{indent}page.locator({json.dumps(act.selector)}).first.scroll_into_view_if_needed(timeout=30000)"
            )
            lines.append(
                f"{indent}page.locator({json.dumps(act.selector)}).first.click(timeout=30000, force={act.force})"
            )
        elif isinstance(act, HoverAction):
            if act.selector:
                lines.append(f"{indent}page.locator({json.dumps(act.selector)}).first.hover(timeout=15000)")
            elif act.role and act.name:
                lines.append(
                    f"{indent}page.get_by_role({json.dumps(act.role)}, name={json.dumps(act.name)}).first.hover(timeout=15000)"
                )
            elif act.text:
                lines.append(f"{indent}page.get_by_text({json.dumps(act.text)}).first.hover(timeout=15000)")
        elif isinstance(act, EvaluateConditionAction):
            lines.append(f"{indent}# evaluate_condition: {act.condition}")
            if act.extract_selector:
                lines.append(
                    f"{indent}print('Condition text:', page.locator({json.dumps(act.extract_selector)}).first.inner_text(timeout=10000))"
                )
        elif isinstance(act, ExtractTextAction):
            lines.append(
                f"{indent}{act.store_as} = page.locator({json.dumps(act.selector)}).first.inner_text(timeout=30000)[:{act.max_length}]"
            )
            lines.append(f"{indent}print(f'{act.store_as} = {{{act.store_as}[:200]}}')")
        elif isinstance(act, TypeTextAction):
            text_expr = _py_value_for_text(act.text, known_vars)
            if act.selector:
                lines.append(
                    f"{indent}page.wait_for_selector({json.dumps(act.selector)}, state=\"visible\", timeout=30000)"
                )
                lines.append(
                    f"{indent}page.locator({json.dumps(act.selector)}).first.click(timeout=30000)"
                )
                lines.append(f"{indent}page.wait_for_timeout(500)  # wait for editor init")
            if act.delay_ms > 0:
                lines.append(
                    f"{indent}page.keyboard.type({text_expr}, delay={act.delay_ms})"
                )
            else:
                # Use execCommand for contenteditable editors (LinkedIn, ChatGPT, etc.)
                lines.append(f"{indent}_is_ce = page.evaluate('() => document.activeElement?.isContentEditable === true')")
                lines.append(f"{indent}if _is_ce:")
                lines.append(f"{indent}    _ok = page.evaluate('(t) => document.execCommand(\"insertText\", false, t)', {text_expr})")
                lines.append(f"{indent}    if not _ok:")
                lines.append(f"{indent}        page.keyboard.type({text_expr}, delay=0)")
                lines.append(f"{indent}else:")
                lines.append(f"{indent}    page.keyboard.insert_text({text_expr})")
        elif isinstance(act, WaitForSelectorAction):
            lines.append(
                f"{indent}page.wait_for_selector({json.dumps(act.selector)}, state={json.dumps(act.state)}, timeout={act.timeout_ms})"
            )
        elif isinstance(act, WaitForTextStableAction):
            lines.append(f"{indent}# wait_for_text_stable: {act.selector} (timeout={act.timeout_ms}ms, stable={act.stable_ms}ms)")
            lines.append(f"{indent}import time as _t")
            lines.append(f"{indent}_start, _last_text, _last_change = _t.time(), '', _t.time()")
            lines.append(f"{indent}while _t.time() - _start < {act.timeout_ms / 1000}:")
            lines.append(f"{indent}    try:")
            lines.append(f"{indent}        _cur = page.locator({json.dumps(act.selector)}).first.inner_text(timeout=5000)")
            lines.append(f"{indent}    except Exception:")
            lines.append(f'{indent}        _cur = ""')
            lines.append(f"{indent}    if _cur != _last_text: _last_text, _last_change = _cur, _t.time()")
            lines.append(f"{indent}    if _t.time() - _last_change >= {act.stable_ms / 1000} and _last_text: break")
            lines.append(f"{indent}    page.wait_for_timeout(500)")
    return lines


class BrowserExecutor:
    """Runs DSL steps against a Playwright Page (sync or async). Prefer async pool + ``run_all_async``."""

    def __init__(
        self,
        page,
        use_step_critic: bool = False,
        use_vision: bool = True,
        use_grounded_verifier: bool = True,
        on_sse: SSEEmit = None,
    ):
        self._page = page
        self._use_step_critic = use_step_critic
        self._use_vision = use_vision
        self._use_grounded_verifier = use_grounded_verifier
        self._on_sse = on_sse
        self._step_log: List[Dict[str, Any]] = []
        self._data_store: Dict[str, str] = {}

    @property
    def data_store(self) -> Dict[str, str]:
        """Variables extracted by ``extract_text`` actions, available to later steps via ``{{name}}``."""
        return dict(self._data_store)

    def _update_data_store_from_observation(self, obs: Dict[str, Any]) -> None:
        """Pull ``store_as`` / ``extracted_text`` pairs from executed actions into the data store."""
        for rec in obs.get("executed", []):
            store_key = rec.get("store_as")
            if store_key and "extracted_text" in rec:
                self._data_store[store_key] = rec["extracted_text"]
                logger.info(
                    "Data store updated: %s = %d chars",
                    store_key, len(rec["extracted_text"]),
                )

    def _data_store_context_for_llm(self) -> str:
        """Format stored variables for inclusion in DSL generation prompts."""
        if not self._data_store:
            return ""
        parts = ["\n## Stored data (use {{var_name}} to inject into text/value fields)\n"]
        for key, val in self._data_store.items():
            preview = val[:200].replace("\n", " ")
            parts.append(f"- `{key}`: \"{preview}{'…' if len(val) > 200 else ''}\" ({len(val)} chars)")
        return "\n".join(parts) + "\n"

    def _sse(self, event: str, data: Dict[str, Any]) -> None:
        if self._on_sse:
            try:
                self._on_sse(event, data)
            except Exception:
                logger.debug("on_sse callback failed", exc_info=True)

    def _sse_progress(self, stage: str, message: str) -> None:
        self._sse("progress", {"stage": stage, "message": message})

    def _sse_thinking(self, typ: str, content: str) -> None:
        self._sse("thinking", {"type": typ, "content": content})

    async def _sse_screenshot_async(
        self,
        step_num,
        status: str = "success",
        observation: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Capture current page state and emit it as a base64 JPEG via SSE."""
        if not self._on_sse:
            return
        try:
            import base64

            data = await self._page.screenshot(type="jpeg", quality=70, full_page=False)
            b64 = base64.b64encode(data).decode("utf-8")
            vp = self._page.viewport_size
            if not vp:
                vp = await self._page.evaluate(
                    "() => ({ width: window.innerWidth, height: window.innerHeight })"
                )
            payload: Dict[str, Any] = {
                "step": step_num,
                "status": status,
                "image": b64,
                "mime": "image/jpeg",
                "viewport": {"width": int(vp["width"]), "height": int(vp["height"])},
                "overlays": screenshot_overlays_from_observation(observation),
            }
            self._sse("browser_screenshot", payload)
        except Exception as exc:
            logger.debug("_sse_screenshot_async failed: %s", exc)

    def _sse_screenshot_sync(
        self,
        step_num,
        status: str = "success",
        observation: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Sync Playwright page: emit viewport JPEG + overlays (used by recorded-DSL replay)."""
        if not self._on_sse:
            return
        if self._is_async_page(self._page):
            return
        try:
            import base64

            data = self._page.screenshot(type="jpeg", quality=70, full_page=False)
            b64 = base64.b64encode(data).decode("utf-8")
            vp = self._page.viewport_size
            if not vp:
                vp = self._page.evaluate(
                    "() => ({ width: window.innerWidth, height: window.innerHeight })"
                )
            payload: Dict[str, Any] = {
                "step": step_num,
                "status": status,
                "image": b64,
                "mime": "image/jpeg",
                "viewport": {"width": int(vp["width"]), "height": int(vp["height"])},
                "overlays": screenshot_overlays_from_observation(observation),
            }
            self._sse("browser_screenshot", payload)
        except Exception as exc:
            logger.debug("_sse_screenshot_sync failed: %s", exc)

    @staticmethod
    def _is_async_page(page) -> bool:
        return bool(inspect.iscoroutinefunction(getattr(page, "goto", None)))

    @property
    def page(self):
        return self._page

    @property
    def step_log(self) -> List[Dict[str, Any]]:
        return list(self._step_log)

    def _llm_evaluate_condition(
        self,
        ai_service,
        condition: str,
        extracted_text: str,
    ) -> bool:
        """Use LLM to evaluate a complex condition against extracted page text."""
        prompt = (
            "System: You evaluate conditions against web page data. "
            "Reply with ONLY valid JSON: {\"met\": true/false, \"reason\": \"one sentence\", \"extracted_value\": \"the relevant value you found\"}\n\n"
            f"User: Condition to check: {condition}\n\n"
            f"Page text (extracted):\n{extracted_text[:2500]}\n\n"
            "Is this condition met? Extract the relevant numeric/text value and compare."
        )
        try:
            raw = ai_service.call_genai(prompt, temperature=0, max_tokens=256)
            data = extract_json_object(raw)
            return bool(data.get("met", False))
        except Exception as exc:
            logger.warning("Condition evaluation failed: %s — defaulting to False", exc)
            return False

    def take_screenshot(self, label: str = "step") -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = f"{label}_{ts}.png"
        fpath = SCREENSHOT_DIR / fname
        try:
            self._page.screenshot(path=str(fpath), full_page=False)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return ""
        return str(fpath)

    async def take_screenshot_async(self, label: str = "step") -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fname = f"{label}_{ts}.png"
        fpath = SCREENSHOT_DIR / fname
        try:
            await self._page.screenshot(path=str(fpath), full_page=False)
        except Exception as exc:
            logger.warning("Screenshot failed: %s", exc)
            return ""
        return str(fpath)

    async def replay_recorded_bundles_async(
        self,
        prior_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Re-execute recorded ``dsl_bundle`` actions only (no LLM). Emits progress + viewport screenshots."""
        if not self._is_async_page(self._page):
            raise TypeError("replay_recorded_bundles_async requires an async Playwright page")

        page = self._page
        out: List[Dict[str, Any]] = []

        for r in prior_results:
            step_num = r.get("step_number", len(out) + 1)
            action = r.get("action", "replay")
            description = (r.get("description") or "Replay recorded step")[:2000]
            raw = r.get("dsl_bundle")

            log_entry: Dict[str, Any] = {
                "step_number": step_num,
                "action": action,
                "description": description,
                "status": "pending",
                "started_at": datetime.now().isoformat(),
            }

            if not isinstance(raw, dict) or not raw.get("actions"):
                log_entry.update(
                    status="error",
                    error="missing dsl_bundle.actions in recorded step",
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                await self._sse_screenshot_async(step_num, status="error", observation=None)
                break

            try:
                bundle = parse_dsl_bundle(raw)
            except Exception as exc:
                log_entry.update(
                    status="error",
                    error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                await self._sse_screenshot_async(step_num, status="error", observation=None)
                break

            n_act = len(bundle.actions)
            self._sse_progress(
                "replay",
                f"Step {step_num}: replaying {n_act} recorded action(s)…",
            )
            try:
                obs = await async_execute_dsl_actions(
                    page, bundle, screenshot_dir=SCREENSHOT_DIR, step_num=step_num
                )
            except Exception as exc:
                log_entry.update(
                    status="error",
                    error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                await self._sse_screenshot_async(step_num, status="error", observation=None)
                break

            if obs.get("partial_failure"):
                err = obs.get("failed_action_error", "partial bundle failure")
                log_entry.update(
                    status="error",
                    error=err,
                    dsl_bundle=bundle.model_dump(),
                    observation=obs,
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                await self._sse_screenshot_async(step_num, status="error", observation=obs)
                break

            exp = r.get("expected_outcome")
            if self._use_grounded_verifier and exp:
                snap = await async_capture_page_snapshot(page)
                vis = snap.get("visible_text") or ""
                title = snap.get("title") or ""
                ok, msg = grounded_verify_postcondition(str(exp), vis, title)
                if not ok:
                    log_entry.update(
                        status="error",
                        error=f"grounded verifier: {msg}",
                        dsl_bundle=bundle.model_dump(),
                        observation=obs,
                        finished_at=datetime.now().isoformat(),
                    )
                    out.append(log_entry)
                    self._step_log.append(log_entry)
                    await self._sse_screenshot_async(step_num, status="error", observation=obs)
                    break

            await page.wait_for_timeout(300)
            ss = await self.take_screenshot_async(f"step{step_num}")
            log_entry.update(
                status="success",
                dsl_bundle=bundle.model_dump(),
                observation=obs,
                screenshot=ss,
                attempts=1,
                vision_used=False,
                finished_at=datetime.now().isoformat(),
            )
            out.append(log_entry)
            self._step_log.append(log_entry)
            await self._sse_screenshot_async(step_num, status="success", observation=obs)
            self._sse_progress("replay", f"Step {step_num} replay completed.")

        return out

    def replay_recorded_bundles(self, prior_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sync page: re-execute recorded DSL bundles (no LLM)."""
        if self._is_async_page(self._page):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self.replay_recorded_bundles_async(prior_results))
            raise RuntimeError(
                "Async Playwright page: use `await executor.replay_recorded_bundles_async(...)`."
            )

        out: List[Dict[str, Any]] = []
        for r in prior_results:
            step_num = r.get("step_number", len(out) + 1)
            action = r.get("action", "replay")
            description = (r.get("description") or "Replay recorded step")[:2000]
            raw = r.get("dsl_bundle")

            log_entry: Dict[str, Any] = {
                "step_number": step_num,
                "action": action,
                "description": description,
                "status": "pending",
                "started_at": datetime.now().isoformat(),
            }

            if not isinstance(raw, dict) or not raw.get("actions"):
                log_entry.update(
                    status="error",
                    error="missing dsl_bundle.actions in recorded step",
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                self._sse_screenshot_sync(step_num, status="error", observation=None)
                break

            try:
                bundle = parse_dsl_bundle(raw)
            except Exception as exc:
                log_entry.update(
                    status="error",
                    error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                self._sse_screenshot_sync(step_num, status="error", observation=None)
                break

            self._sse_progress(
                "replay",
                f"Step {step_num}: replaying {len(bundle.actions)} recorded action(s)…",
            )
            try:
                obs = execute_dsl_actions(
                    self._page, bundle, screenshot_dir=SCREENSHOT_DIR, step_num=step_num
                )
            except Exception as exc:
                log_entry.update(
                    status="error",
                    error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                self._sse_screenshot_sync(step_num, status="error", observation=None)
                break

            if obs.get("partial_failure"):
                err = obs.get("failed_action_error", "partial bundle failure")
                log_entry.update(
                    status="error",
                    error=err,
                    dsl_bundle=bundle.model_dump(),
                    observation=obs,
                    finished_at=datetime.now().isoformat(),
                )
                out.append(log_entry)
                self._step_log.append(log_entry)
                self._sse_screenshot_sync(step_num, status="error", observation=obs)
                break

            exp = r.get("expected_outcome")
            if self._use_grounded_verifier and exp:
                snap = capture_page_snapshot(self._page)
                vis = snap.get("visible_text") or ""
                title = snap.get("title") or ""
                ok, msg = grounded_verify_postcondition(str(exp), vis, title)
                if not ok:
                    log_entry.update(
                        status="error",
                        error=f"grounded verifier: {msg}",
                        dsl_bundle=bundle.model_dump(),
                        observation=obs,
                        finished_at=datetime.now().isoformat(),
                    )
                    out.append(log_entry)
                    self._step_log.append(log_entry)
                    self._sse_screenshot_sync(step_num, status="error", observation=obs)
                    break

            self._page.wait_for_timeout(300)
            ss = self.take_screenshot(f"step{step_num}")
            log_entry.update(
                status="success",
                dsl_bundle=bundle.model_dump(),
                observation=obs,
                screenshot=ss,
                attempts=1,
                vision_used=False,
                finished_at=datetime.now().isoformat(),
            )
            out.append(log_entry)
            self._step_log.append(log_entry)
            self._sse_screenshot_sync(step_num, status="success", observation=obs)
            self._sse_progress("replay", f"Step {step_num} replay completed.")

        return out

    async def execute_step_async(
        self,
        ai_service,
        step: Dict[str, Any],
        retry: int = 2,
    ) -> Dict[str, Any]:
        page = self._page
        step_num = step.get("step_number", 0)
        action = step.get("action", "custom")
        description = step.get("description", "")

        log_entry: Dict[str, Any] = {
            "step_number": step_num,
            "action": action,
            "description": description,
            "status": "pending",
            "started_at": datetime.now().isoformat(),
        }

        target_url = step.get("target_url")
        if action == "navigate" and target_url:
            self._sse_progress(
                "step",
                f"Step {step_num}: navigate — loading {str(target_url)[:80]}{'…' if len(str(target_url)) > 80 else ''}",
            )
            try:
                bundle = parse_dsl_bundle(
                    {
                        "actions": [
                            {"type": "goto", "url": target_url},
                            {"type": "wait_ms", "ms": 3000},
                        ]
                    }
                )
                obs = await async_execute_dsl_actions(
                    page, bundle, screenshot_dir=SCREENSHOT_DIR, step_num=step_num
                )
                snap = await async_capture_page_snapshot(page)
                title = snap.get("title") or ""
                vis = snap.get("visible_text") or ""
                if self._use_grounded_verifier and step.get("expected_outcome"):
                    ok, msg = grounded_verify_postcondition(step["expected_outcome"], vis, title)
                    if not ok:
                        log_entry.update(
                            status="error",
                            error=f"grounded verifier: {msg}",
                            dsl_bundle=bundle.model_dump(),
                            observation=obs,
                            grounded_verify_failed=True,
                            finished_at=datetime.now().isoformat(),
                        )
                        self._step_log.append(log_entry)
                        return log_entry

                ss = await self.take_screenshot_async(f"step{step_num}")
                log_entry.update(
                    status="success",
                    screenshot=ss,
                    dsl_bundle=bundle.model_dump(),
                    observation=obs,
                    finished_at=datetime.now().isoformat(),
                )
                if obs.get("condition_met") is not None:
                    log_entry["condition_met"] = obs["condition_met"]
                self._step_log.append(log_entry)
                return log_entry
            except Exception as exc:
                log_entry.update(
                    status="error",
                    error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                self._step_log.append(log_entry)
                return log_entry

        attempts = 0
        last_error = ""
        _last_bundle: Optional[DSLBundle] = None
        _last_data_raw: Optional[dict] = None

        while attempts <= retry:
            attempts += 1
            if attempts == 1:
                self._sse_progress(
                    "dsl",
                    f"Step {step_num}: snapshot + accessibility tree → asking LLM for browser DSL…",
                )
            else:
                self._sse_progress(
                    "dsl",
                    f"Step {step_num}: retry {attempts}/{retry + 1} (previous: {last_error[:100]}{'…' if len(last_error) > 100 else ''})",
                )
            dom_ctx = await build_dom_context_async(page)
            user_msg = (
                f"Current URL: {page.url}\n\n"
                f"Step {step_num}: [{action}] {description}\n"
            )
            if step.get("search_query"):
                user_msg += f"Search query: {step['search_query']}\n"
            if step.get("element_hint"):
                user_msg += f"Element hint: {step['element_hint']}\n"
            if step.get("value"):
                user_msg += f"Value: {step['value']}\n"
            if step.get("condition"):
                user_msg += f"Condition to verify: {step['condition']}\n"
            if step.get("expected_outcome"):
                user_msg += f"Expected outcome after step: {step['expected_outcome']}\n"
            if action == "navigate" and target_url:
                user_msg += f"Navigate URL: {target_url}\n"
            user_msg += f"\n--- Page context ---\n{dom_ctx}\n"
            ds_ctx = self._data_store_context_for_llm()
            if ds_ctx:
                user_msg += ds_ctx
            user_msg += _dsl_linkedin_stored_text_hint(page.url, action, ds_ctx)

            if last_error:
                user_msg += (
                    f"\n⚠️ Previous attempt #{attempts - 1} FAILED: {last_error}\n"
                    "Analyze the error carefully. The DOM context above is FRESH (re-captured).\n"
                    "You MUST choose a DIFFERENT action type or selector strategy.\n"
                )
                # Add targeted recovery hints based on the error pattern
                err_lower = last_error.lower()
                if ("fill_placeholder" in err_lower or "fill_role" in err_lower
                        or "fill_label" in err_lower or "get_by_placeholder" in err_lower):
                    user_msg += (
                        "**The fill_placeholder / fill_role / fill_label action FAILED.** "
                        "This almost certainly means the target is a contenteditable rich text editor "
                        "(LinkedIn, ChatGPT, Gmail, etc.), NOT a native <input>/<textarea>. "
                        "Placeholder-like text (e.g. 'What do you want to talk about?') is NOT a real HTML placeholder. "
                        "**You MUST use `type_text` with a CSS `selector` targeting the contenteditable element** "
                        "(e.g. `[contenteditable=\"true\"]`, `[role=\"textbox\"]`, or a specific class).\n"
                    )
                elif "click_text" in err_lower and "option" in err_lower:
                    user_msg += (
                        "click_text failed on what appears to be a dropdown option. "
                        "Try select_option for native <select> or click_css with the visible trigger instead.\n"
                    )
                else:
                    user_msg += (
                        "Choose a DIFFERENT selector strategy — e.g. if click_text failed, try click_role or click_css; "
                        "if fill_* failed on a rich text editor, use type_text with a CSS selector.\n"
                    )
                user_msg += 'Output corrected JSON only: {"actions":[...]}\n'

            screenshot_png: Optional[bytes] = None
            try:
                screenshot_png = await page.screenshot(type="png", full_page=False)
                print(
                    f"[BrowserVision] Step {step_num} attempt {attempts}: "
                    f"screenshot captured ({len(screenshot_png):,} bytes)"
                )
            except Exception as exc:
                print(f"[BrowserVision] Step {step_num}: screenshot FAILED: {exc}")

            send_vision = screenshot_png if (self._use_vision or attempts > 1) else None
            if not send_vision and screenshot_png:
                print(
                    f"[BrowserVision] Step {step_num}: vision OFF (use_vision={self._use_vision}, "
                    f"attempt={attempts}) -- screenshot NOT sent to LLM"
                )
            elif send_vision:
                print(
                    f"[BrowserVision] Step {step_num}: will send screenshot to LLM "
                    f"({len(screenshot_png):,} bytes)"
                )
            else:
                print(f"[BrowserVision] Step {step_num}: no screenshot available -- text-only LLM call")

            system_block = DSL_GEN_SYSTEM + (DSL_VISION_ADDON if send_vision else "")
            full_prompt = f"System: {system_block}\n\nUser: {user_msg}"

            try:
                if send_vision:
                    self._sse_progress("dsl", f"Step {step_num}: LLM call with viewport screenshot (vision)...")
                raw = ai_service.call_genai(
                    full_prompt,
                    temperature=0.12 + (attempts - 1) * 0.08,
                    max_tokens=4096,
                    screenshot_png=send_vision,
                )
                print(
                    f"[BrowserVision] Step {step_num}: LLM responded ({len(raw)} chars) | "
                    f"preview: {raw[:150]}"
                )
                data = extract_json_object(raw)
                data_raw = dict(data)
                data = resolve_bundle_variables(data, self._data_store)
                bundle = parse_dsl_bundle(data)
                _last_bundle = bundle
                _last_data_raw = data_raw
                n_act = len(bundle.actions)
                par = " (parallel fills)" if getattr(bundle, "parallel", False) else ""
                self._sse_progress("execute", f"Step {step_num}: executing {n_act} DSL action(s){par} via Playwright…")
                obs = await async_execute_dsl_actions(
                    page, bundle, screenshot_dir=SCREENSHOT_DIR, step_num=step_num
                )
                self._update_data_store_from_observation(obs)

                # ── Two-phase dropdown recovery ────────────────────
                # opened but option click timed out), re-snapshot NOW while the
                # dropdown is still open and ask the LLM for the remaining action.
                if obs.get("partial_failure"):
                    completed = obs.get("actions_completed", 0)
                    total = obs.get("actions_total", 0)
                    fail_err = obs.get("failed_action_error", "")
                    logger.warning(
                        "Step %d: PARTIAL failure — %d/%d actions ran, failed at action %d: %s",
                        step_num, completed, total, obs.get("failed_action_idx", -1), fail_err,
                    )
                    # Check if a combobox/dropdown was likely opened
                    _opened_dropdown = any(
                        r.get("role") in ("combobox", "listbox", "menu")
                        or r.get("type") in ("click_role", "click_css", "hover")
                        for r in obs.get("executed", [])
                        if not r.get("error")
                    )
                    if _opened_dropdown and completed > 0:
                        logger.info(
                            "Step %d: dropdown likely open — attempting two-phase recovery (re-snapshot + LLM for remaining action)",
                            step_num,
                        )
                        self._sse_progress(
                            "dsl",
                            f"Step {step_num}: dropdown opened but option click failed — re-reading page with dropdown open…",
                        )
                        # Short wait for any animation
                        await page.wait_for_timeout(500)
                        # Re-snapshot while dropdown is still open
                        phase2_dom = await build_dom_context_async(page)
                        phase2_screenshot: Optional[bytes] = None
                        try:
                            phase2_screenshot = await page.screenshot(type="png", full_page=False)
                            logger.info(
                                "Step %d: phase-2 screenshot captured (%s bytes) with dropdown open",
                                step_num, f"{len(phase2_screenshot):,}",
                            )
                        except Exception:
                            pass
                        phase2_msg = (
                            f"Current URL: {page.url}\n\n"
                            f"Step {step_num}: [{action}] {description}\n\n"
                            f"IMPORTANT: A dropdown/combobox was just opened (previous actions partially succeeded). "
                            f"The DOM snapshot below shows the CURRENT page state WITH the dropdown/popover/listbox OPEN. "
                            f"Previous action failed: {fail_err}\n"
                            f"Generate ONLY the action(s) needed to select the correct option from the now-open dropdown. "
                            f"Look at the accessibility tree and key_elements for the actual roles and names of the visible options.\n\n"
                            f"--- Page context (dropdown OPEN) ---\n{phase2_dom}\n"
                        )
                        phase2_system = DSL_GEN_SYSTEM + DSL_VISION_ADDON
                        phase2_prompt = f"System: {phase2_system}\n\nUser: {phase2_msg}"
                        phase2_vision = phase2_screenshot if (self._use_vision or True) else None
                        try:
                            self._sse_progress("dsl", f"Step {step_num}: asking LLM to select from open dropdown…")
                            raw2 = ai_service.call_genai(
                                phase2_prompt,
                                temperature=0.1,
                                max_tokens=2048,
                                screenshot_png=phase2_vision,
                            )
                            logger.info(
                                "Step %d: phase-2 LLM response (%d chars) | preview: %.200s",
                                step_num, len(raw2), raw2[:200],
                            )
                            data2_raw = extract_json_object(raw2)
                            data2 = resolve_bundle_variables(data2_raw, self._data_store)
                            bundle2 = parse_dsl_bundle(data2)
                            self._sse_progress("execute", f"Step {step_num}: executing phase-2 action(s) on open dropdown…")
                            obs2 = await async_execute_dsl_actions(
                                page, bundle2, screenshot_dir=SCREENSHOT_DIR, step_num=step_num,
                            )
                            if not obs2.get("partial_failure"):
                                # Phase 2 succeeded — merge observations
                                obs["executed"].extend(obs2.get("executed", []))
                                obs["url_after"] = obs2.get("url_after", page.url)
                                obs.pop("partial_failure", None)
                                obs.pop("failed_action_idx", None)
                                obs.pop("failed_action_error", None)
                                # Export/replay must include both initial and phase-2 recovery actions.
                                merged_raw_actions: List[Dict[str, Any]] = []
                                if isinstance(data_raw.get("actions"), list):
                                    merged_raw_actions.extend(data_raw["actions"])
                                if isinstance(data2_raw.get("actions"), list):
                                    merged_raw_actions.extend(data2_raw["actions"])
                                if merged_raw_actions:
                                    data_raw["actions"] = merged_raw_actions

                                merged_actions = [*bundle.actions, *bundle2.actions]
                                bundle = parse_dsl_bundle(
                                    {"actions": [a.model_dump() for a in merged_actions]}
                                )
                                logger.info("Step %d: two-phase dropdown recovery SUCCEEDED", step_num)
                            else:
                                logger.warning("Step %d: two-phase recovery also failed: %s", step_num, obs2.get("failed_action_error"))
                                last_error = f"dropdown recovery failed: {obs2.get('failed_action_error', fail_err)}"
                                continue
                        except Exception as exc2:
                            logger.warning("Step %d: two-phase recovery LLM/exec error: %s", step_num, exc2)
                            last_error = f"dropdown recovery error: {exc2}"
                            continue
                    else:
                        last_error = fail_err
                        continue

                # If still a partial failure after recovery attempt, retry
                if obs.get("partial_failure"):
                    last_error = obs.get("failed_action_error", "partial bundle failure")
                    continue

                for exec_rec in obs.get("executed", []):
                    if exec_rec.get("needs_llm_eval"):
                        self._sse_progress(
                            "verify",
                            f"Step {step_num}: LLM evaluating condition '{exec_rec.get('condition', '')[:80]}...' ",
                        )
                        llm_result = self._llm_evaluate_condition(
                            ai_service,
                            exec_rec["condition"],
                            exec_rec.get("extracted_text", ""),
                        )
                        exec_rec["condition_result"] = llm_result
                        if obs.get("condition_met") is None:
                            obs["condition_met"] = llm_result

                snap = await async_capture_page_snapshot(page)
                title = snap.get("title") or ""
                vis = snap.get("visible_text") or ""
                snippet = vis[:2000] if vis else await _async_safe_page_text(page, 2000)

                if self._use_grounded_verifier and step.get("expected_outcome"):
                    ok, msg = grounded_verify_postcondition(step["expected_outcome"], vis, title)
                    if not ok:
                        last_error = f"grounded verifier: {msg}"
                        continue

                if self._use_step_critic and not _critic_ok(ai_service, step, obs, snippet):
                    last_error = "critic rejected outcome"
                    continue

                await page.wait_for_timeout(800)
                ss = await self.take_screenshot_async(f"step{step_num}")
                log_entry["dsl_bundle"] = bundle.model_dump()
                log_entry["dsl_bundle_raw"] = data_raw
                log_entry["observation"] = obs
                log_entry["status"] = "success"
                log_entry["screenshot"] = ss
                log_entry["vision_used"] = bool(send_vision)
                log_entry["attempts"] = attempts
                log_entry["finished_at"] = datetime.now().isoformat()
                if obs.get("condition_met") is not None:
                    log_entry["condition_met"] = obs["condition_met"]
                self._step_log.append(log_entry)
                return log_entry
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Step %d attempt %d/%d: %s", step_num, attempts, retry + 1, last_error)

        log_entry.update(
            status="error",
            error=last_error,
            finished_at=datetime.now().isoformat(),
        )
        if _last_bundle and "dsl_bundle" not in log_entry:
            log_entry["dsl_bundle"] = _last_bundle.model_dump()
            log_entry["dsl_bundle_raw"] = _last_data_raw
            log_entry["dsl_bundle_status"] = "failed"
        self._step_log.append(log_entry)
        return log_entry

    async def _replan_remaining_async(
        self,
        ai_service,
        failed_step: Dict[str, Any],
        remaining_steps: List[Dict[str, Any]],
        error: str,
    ) -> List[Dict[str, Any]]:
        dom_ctx = await build_dom_context_async(self._page)
        remaining_desc = "\n".join(
            f"  {s.get('step_number')}. [{s.get('action')}] {s.get('description')}"
            for s in remaining_steps
        )

        # Capture screenshot for vision-powered replanning
        replan_screenshot: Optional[bytes] = None
        if self._use_vision:
            try:
                replan_screenshot = await self._page.screenshot(type="png", full_page=False)
                print(f"[BrowserVision] Replan: screenshot captured ({len(replan_screenshot):,} bytes)")
            except Exception:
                pass

        prompt = (
            "System: You are a browser-automation re-planner. A step failed during execution. "
            "You can see the current page state (DOM + screenshot). "
            "Produce a corrected JSON array of goal steps that achieves the same goal. "
            "Adapt to the current page. Do NOT guess element selectors -- just describe "
            "the goals in plain English. A downstream refiner with page access will handle selectors. "
            "Return ONLY a JSON array. Each object MUST include: "
            "`step_number` (int), `action` (navigate|search|click|type|scroll|select|wait|verify|add_to_cart|custom), "
            "`description` (required). Optional: target_url, search_query, "
            "element_hint, value, condition, expected_outcome. No markdown fences.\n\n"
            f"User:\n"
            f"Current URL: {self._page.url}\n"
            f"Failed step: [{failed_step.get('action')}] {failed_step.get('description')}\n"
            f"Error: {error}\n\n"
            f"Remaining goals that still need to be done:\n{remaining_desc}\n\n"
            f"--- Current page context ---\n{dom_ctx[:8000]}\n\n"
            "Produce a corrected goal plan that works from the current page state."
        )
        try:
            self._sse_progress("replan", "Re-plan LLM: generating corrected goals from current page...")
            raw = ai_service.call_genai(
                prompt, temperature=0.2, max_tokens=4096,
                screenshot_png=replan_screenshot,
            )
            text = raw.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            parsed = json.loads(text) if text.startswith("[") else []
            if not isinstance(parsed, list):
                match = re.search(r"\[.*\]", text, re.DOTALL)
                parsed = json.loads(match.group()) if match else []
            base = failed_step.get("step_number", 0)
            for i, s in enumerate(parsed):
                s["step_number"] = base + i
            from .step_validator import validate_planner_steps

            validated = validate_planner_steps(parsed)
            print(f"[BrowserPlanner] Re-plan OK: {len(validated)} goal(s) queued")
            self._sse_progress("replan", f"Re-plan OK -- {len(validated)} goal(s) queued from current page.")
            return validated
        except Exception as exc:
            print(f"[BrowserPlanner] Re-plan failed: {exc}")
            self._sse_progress("replan", f"Re-plan failed ({exc}) -- keeping original remaining goals.")
            return remaining_steps

    async def run_all_async(
        self,
        ai_service,
        steps: List[Dict[str, Any]],
        original_query: str = "",
        max_replans: int = 2,
    ) -> List[Dict[str, Any]]:
        """Plan-act-observe loop: refine each goal with LIVE page context before executing."""
        if not self._is_async_page(self._page):
            raise TypeError("run_all_async requires an async Playwright Page (from BrowserPool.async_acquire_page)")

        results: List[Dict[str, Any]] = []
        remaining = list(steps)
        replans_used = 0
        observation_replans_used = 0
        steps_since_obs_check = 0
        query = original_query or ""

        while remaining:
            goal = remaining.pop(0)
            sn = goal.get("step_number", "?")
            sa = goal.get("action", "?")
            sd = (goal.get("description") or "")[:120]

            # ── REFINE: ground the goal against the LIVE page ──────
            self._sse_progress(
                "refine",
                f"Step {sn}: reading page to refine goal [{sa}]: {sd}...",
            )
            snap_before = await async_capture_page_snapshot(self._page)
            page_ctx = format_snapshot_for_llm(snap_before)

            # Capture screenshot for refiner vision
            refine_screenshot: Optional[bytes] = None
            if self._use_vision:
                try:
                    refine_screenshot = await self._page.screenshot(type="png", full_page=False)
                    print(
                        f"[BrowserVision] Step {sn}: refiner screenshot captured "
                        f"({len(refine_screenshot):,} bytes)"
                    )
                except Exception as exc:
                    print(f"[BrowserVision] Step {sn}: refiner screenshot failed: {exc}")

            step = refine_step_with_page_context(
                ai_service,
                goal,
                page_ctx,
                original_query=query,
                screenshot_png=refine_screenshot,
            )

            # Re-read step fields after refinement
            sn = step.get("step_number", sn)
            sa = step.get("action", sa)
            sd = (step.get("description") or "")[:120]
            hint = step.get("element_hint", "")
            self._sse_progress(
                "step",
                f"Step {sn} [{sa}]: {sd}"
                + (f" (hint: {hint[:60]})" if hint else ""),
            )

            # ── EXECUTE the refined step ───────────────────────────
            result = await self.execute_step_async(ai_service, step)
            results.append(result)
            snap_after = await async_capture_page_snapshot(self._page)
            summary = summarize_observation(snap_before, snap_after, result)
            st = result.get("status", "?")
            if st == "success":
                self._sse_progress("step", f"Step {sn} completed ({result.get('attempts', 1)} attempt(s)).")
            else:
                err = (result.get("error") or "unknown")[:150]
                self._sse_progress("step", f"Step {sn} failed: {err}")
            await self._sse_screenshot_async(sn, status=st, observation=result.get("observation"))

            # ── OBSERVE: handle failure + periodic replan ──────────
            if result["status"] == "error" and remaining and replans_used < max_replans:
                print(
                    f"[BrowserPlanner] Step {sn} failed -- re-planning "
                    f"({replans_used + 1}/{max_replans}), {len(remaining)} remaining"
                )
                self._sse_thinking(
                    "thinking",
                    f"Failure replan {replans_used + 1}/{max_replans} -- adapting "
                    f"{len(remaining)} remaining goal(s) to the current page.",
                )
                remaining = await self._replan_remaining_async(
                    ai_service, step, remaining, result.get("error", "unknown"),
                )
                replans_used += 1
                steps_since_obs_check = 0
                continue

            if result["status"] == "error":
                print(f"[BrowserPlanner] Step {sn} failed -- no re-plans left.")

            steps_since_obs_check += 1
            if (
                remaining
                and steps_since_obs_check >= REPLAN_AFTER_EVERY_N_STEPS
                and observation_replans_used < MAX_OBSERVATION_REPLANS
            ):
                self._sse_progress(
                    "observe",
                    f"Observation check: asking LLM if {len(remaining)} remaining "
                    f"goal(s) still fit the page...",
                )
                needs, new_rem = check_observation_replan(
                    ai_service, summary, remaining, query,
                )
                observation_replans_used += 1
                steps_since_obs_check = 0
                if needs:
                    from .step_validator import validate_planner_steps

                    try:
                        remaining = validate_planner_steps(new_rem)
                        self._sse_progress(
                            "observe",
                            f"Plan updated -- {len(remaining)} goal(s) after observation replan.",
                        )
                    except ValueError as exc:
                        logger.warning("Observation replan validation failed: %s", exc)
                        self._sse_progress("observe", f"Observation replan invalid ({exc}) -- keeping prior goals.")
                else:
                    self._sse_progress("observe", "Remaining goals still valid -- continuing.")

        return results

    def execute_step(
        self,
        ai_service,
        step: Dict[str, Any],
        retry: int = 2,
    ) -> Dict[str, Any]:
        step_num = step.get("step_number", 0)
        action = step.get("action", "custom")
        description = step.get("description", "")

        log_entry: Dict[str, Any] = {
            "step_number": step_num,
            "action": action,
            "description": description,
            "status": "pending",
            "started_at": datetime.now().isoformat(),
        }

        target_url = step.get("target_url")
        if action == "navigate" and target_url:
            self._sse_progress(
                "step",
                f"Step {step_num}: navigate — loading {str(target_url)[:80]}{'…' if len(str(target_url)) > 80 else ''}",
            )
            try:
                bundle = parse_dsl_bundle(
                    {
                        "actions": [
                            {"type": "goto", "url": target_url},
                            {"type": "wait_ms", "ms": 3000},
                        ]
                    }
                )
                obs = execute_dsl_actions(self._page, bundle, screenshot_dir=SCREENSHOT_DIR, step_num=step_num)
                snap = capture_page_snapshot(self._page)
                title = snap.get("title") or ""
                vis = snap.get("visible_text") or ""
                if self._use_grounded_verifier and step.get("expected_outcome"):
                    ok, msg = grounded_verify_postcondition(step["expected_outcome"], vis, title)
                    if not ok:
                        log_entry.update(
                            status="error",
                            error=f"grounded verifier: {msg}",
                            dsl_bundle=bundle.model_dump(),
                            observation=obs,
                            grounded_verify_failed=True,
                            finished_at=datetime.now().isoformat(),
                        )
                        self._step_log.append(log_entry)
                        return log_entry

                ss = self.take_screenshot(f"step{step_num}")
                log_entry.update(
                    status="success",
                    screenshot=ss,
                    dsl_bundle=bundle.model_dump(),
                    observation=obs,
                    finished_at=datetime.now().isoformat(),
                )
                if obs.get("condition_met") is not None:
                    log_entry["condition_met"] = obs["condition_met"]
                self._step_log.append(log_entry)
                return log_entry
            except Exception as exc:
                log_entry.update(
                    status="error",
                    error=str(exc),
                    finished_at=datetime.now().isoformat(),
                )
                self._step_log.append(log_entry)
                return log_entry

        attempts = 0
        last_error = ""
        _last_bundle: Optional[DSLBundle] = None
        _last_data_raw: Optional[dict] = None

        while attempts <= retry:
            attempts += 1
            if attempts == 1:
                self._sse_progress(
                    "dsl",
                    f"Step {step_num}: snapshot + accessibility tree → asking LLM for browser DSL…",
                )
            else:
                self._sse_progress(
                    "dsl",
                    f"Step {step_num}: retry {attempts}/{retry + 1} (previous: {last_error[:100]}{'…' if len(last_error) > 100 else ''})",
                )

            # --- Fresh DOM context + screenshot on EVERY attempt ---
            dom_ctx = build_dom_context(self._page)
            user_msg = (
                f"Current URL: {self._page.url}\n\n"
                f"Step {step_num}: [{action}] {description}\n"
            )
            if step.get("search_query"):
                user_msg += f"Search query: {step['search_query']}\n"
            if step.get("element_hint"):
                user_msg += f"Element hint: {step['element_hint']}\n"
            if step.get("value"):
                user_msg += f"Value: {step['value']}\n"
            if step.get("condition"):
                user_msg += f"Condition to verify: {step['condition']}\n"
            if step.get("expected_outcome"):
                user_msg += f"Expected outcome after step: {step['expected_outcome']}\n"
            if action == "navigate" and target_url:
                user_msg += f"Navigate URL: {target_url}\n"
            user_msg += f"\n--- Page context ---\n{dom_ctx}\n"
            ds_ctx = self._data_store_context_for_llm()
            if ds_ctx:
                user_msg += ds_ctx
            user_msg += _dsl_linkedin_stored_text_hint(self._page.url, action, ds_ctx)

            if last_error:
                user_msg += (
                    f"\n⚠️ Previous attempt #{attempts - 1} FAILED: {last_error}\n"
                    "Analyze the error carefully. The DOM context above is FRESH (re-captured).\n"
                    "You MUST choose a DIFFERENT action type or selector strategy.\n"
                )
                # Add targeted recovery hints based on the error pattern
                err_lower = last_error.lower()
                if ("fill_placeholder" in err_lower or "fill_role" in err_lower
                        or "fill_label" in err_lower or "get_by_placeholder" in err_lower):
                    user_msg += (
                        "**The fill_placeholder / fill_role / fill_label action FAILED.** "
                        "This almost certainly means the target is a contenteditable rich text editor "
                        "(LinkedIn, ChatGPT, Gmail, etc.), NOT a native <input>/<textarea>. "
                        "Placeholder-like text (e.g. 'What do you want to talk about?') is NOT a real HTML placeholder. "
                        "**You MUST use `type_text` with a CSS `selector` targeting the contenteditable element** "
                        "(e.g. `[contenteditable=\"true\"]`, `[role=\"textbox\"]`, or a specific class).\n"
                    )
                elif "click_text" in err_lower and "option" in err_lower:
                    user_msg += (
                        "click_text failed on what appears to be a dropdown option. "
                        "Try select_option for native <select> or click_css with the visible trigger instead.\n"
                    )
                else:
                    user_msg += (
                        "Choose a DIFFERENT selector strategy — e.g. if click_text failed, try click_role or click_css; "
                        "if fill_* failed on a rich text editor, use type_text with a CSS selector.\n"
                    )
                user_msg += 'Output corrected JSON only: {"actions":[...]}\n'

            screenshot_png: Optional[bytes] = None
            try:
                screenshot_png = self._page.screenshot(type="png", full_page=False)
                print(
                    f"[BrowserVision] Step {step_num} attempt {attempts}: "
                    f"screenshot captured ({len(screenshot_png):,} bytes)"
                )
            except Exception as exc:
                print(f"[BrowserVision] Step {step_num}: screenshot FAILED: {exc}")

            send_vision = screenshot_png if (self._use_vision or attempts > 1) else None
            if not send_vision and screenshot_png:
                print(
                    f"[BrowserVision] Step {step_num}: vision OFF (use_vision={self._use_vision}, "
                    f"attempt={attempts}) -- screenshot NOT sent to LLM"
                )
            elif send_vision:
                print(
                    f"[BrowserVision] Step {step_num}: will send screenshot to LLM "
                    f"({len(screenshot_png):,} bytes)"
                )
            else:
                print(f"[BrowserVision] Step {step_num}: no screenshot available -- text-only LLM call")

            system_block = DSL_GEN_SYSTEM + (DSL_VISION_ADDON if send_vision else "")
            full_prompt = f"System: {system_block}\n\nUser: {user_msg}"

            try:
                if send_vision:
                    self._sse_progress("dsl", f"Step {step_num}: LLM call with viewport screenshot (vision)...")
                raw = ai_service.call_genai(
                    full_prompt,
                    temperature=0.12 + (attempts - 1) * 0.08,
                    max_tokens=4096,
                    screenshot_png=send_vision,
                )
                print(
                    f"[BrowserVision] Step {step_num}: LLM responded ({len(raw)} chars) | "
                    f"preview: {raw[:150]}"
                )
                data = extract_json_object(raw)
                data_raw = dict(data)
                data = resolve_bundle_variables(data, self._data_store)
                bundle = parse_dsl_bundle(data)
                _last_bundle = bundle
                _last_data_raw = data_raw
                n_act = len(bundle.actions)
                par = " (parallel fills)" if getattr(bundle, "parallel", False) else ""
                self._sse_progress("execute", f"Step {step_num}: executing {n_act} DSL action(s){par} via Playwright…")
                obs = execute_dsl_actions(self._page, bundle, screenshot_dir=SCREENSHOT_DIR, step_num=step_num)
                self._update_data_store_from_observation(obs)

                # ── Two-phase dropdown recovery (sync) ─────────────
                if obs.get("partial_failure"):
                    completed = obs.get("actions_completed", 0)
                    total = obs.get("actions_total", 0)
                    fail_err = obs.get("failed_action_error", "")
                    logger.warning(
                        "Step %d: PARTIAL failure — %d/%d actions ran, failed at action %d: %s",
                        step_num, completed, total, obs.get("failed_action_idx", -1), fail_err,
                    )
                    _opened_dropdown = any(
                        r.get("role") in ("combobox", "listbox", "menu")
                        or r.get("type") in ("click_role", "click_css", "hover")
                        for r in obs.get("executed", [])
                        if not r.get("error")
                    )
                    if _opened_dropdown and completed > 0:
                        logger.info(
                            "Step %d: dropdown likely open — attempting two-phase recovery",
                            step_num,
                        )
                        self._sse_progress(
                            "dsl",
                            f"Step {step_num}: dropdown opened but option click failed — re-reading page…",
                        )
                        self._page.wait_for_timeout(500)
                        phase2_dom = build_dom_context(self._page)
                        phase2_screenshot: Optional[bytes] = None
                        try:
                            phase2_screenshot = self._page.screenshot(type="png", full_page=False)
                        except Exception:
                            pass
                        phase2_msg = (
                            f"Current URL: {self._page.url}\n\n"
                            f"Step {step_num}: [{action}] {description}\n\n"
                            f"IMPORTANT: A dropdown/combobox was just opened (previous actions partially succeeded). "
                            f"The DOM snapshot below shows the CURRENT page state WITH the dropdown/popover/listbox OPEN. "
                            f"Previous action failed: {fail_err}\n"
                            f"Generate ONLY the action(s) needed to select the correct option from the now-open dropdown. "
                            f"Look at the accessibility tree and key_elements for the actual roles and names of the visible options.\n\n"
                            f"--- Page context (dropdown OPEN) ---\n{phase2_dom}\n"
                        )
                        phase2_system = DSL_GEN_SYSTEM + DSL_VISION_ADDON
                        phase2_prompt = f"System: {phase2_system}\n\nUser: {phase2_msg}"
                        try:
                            self._sse_progress("dsl", f"Step {step_num}: asking LLM to select from open dropdown…")
                            raw2 = ai_service.call_genai(
                                phase2_prompt, temperature=0.1, max_tokens=2048,
                                screenshot_png=phase2_screenshot if self._use_vision else None,
                            )
                            data2_raw = extract_json_object(raw2)
                            data2 = resolve_bundle_variables(data2_raw, self._data_store)
                            bundle2 = parse_dsl_bundle(data2)
                            obs2 = execute_dsl_actions(self._page, bundle2, screenshot_dir=SCREENSHOT_DIR, step_num=step_num)
                            if not obs2.get("partial_failure"):
                                obs["executed"].extend(obs2.get("executed", []))
                                obs["url_after"] = obs2.get("url_after", self._page.url)
                                obs.pop("partial_failure", None)
                                obs.pop("failed_action_idx", None)
                                obs.pop("failed_action_error", None)
                                # Export/replay must include both initial and phase-2 recovery actions.
                                merged_raw_actions: List[Dict[str, Any]] = []
                                if isinstance(data_raw.get("actions"), list):
                                    merged_raw_actions.extend(data_raw["actions"])
                                if isinstance(data2_raw.get("actions"), list):
                                    merged_raw_actions.extend(data2_raw["actions"])
                                if merged_raw_actions:
                                    data_raw["actions"] = merged_raw_actions

                                merged_actions = [*bundle.actions, *bundle2.actions]
                                bundle = parse_dsl_bundle(
                                    {"actions": [a.model_dump() for a in merged_actions]}
                                )
                                logger.info("Step %d: two-phase dropdown recovery SUCCEEDED", step_num)
                            else:
                                last_error = f"dropdown recovery failed: {obs2.get('failed_action_error', fail_err)}"
                                continue
                        except Exception as exc2:
                            last_error = f"dropdown recovery error: {exc2}"
                            continue
                    else:
                        last_error = fail_err
                        continue

                if obs.get("partial_failure"):
                    last_error = obs.get("failed_action_error", "partial bundle failure")
                    continue

                # Post-process: LLM evaluation for evaluate_condition actions
                for exec_rec in obs.get("executed", []):
                    if exec_rec.get("needs_llm_eval"):
                        self._sse_progress(
                            "verify",
                            f"Step {step_num}: LLM evaluating condition '{exec_rec.get('condition', '')[:80]}...' ",
                        )
                        llm_result = self._llm_evaluate_condition(
                            ai_service,
                            exec_rec["condition"],
                            exec_rec.get("extracted_text", ""),
                        )
                        exec_rec["condition_result"] = llm_result
                        if obs.get("condition_met") is None:
                            obs["condition_met"] = llm_result

                snap = capture_page_snapshot(self._page)
                title = snap.get("title") or ""
                vis = snap.get("visible_text") or ""
                snippet = vis[:2000] if vis else _safe_page_text(self._page, 2000)

                if self._use_grounded_verifier and step.get("expected_outcome"):
                    ok, msg = grounded_verify_postcondition(step["expected_outcome"], vis, title)
                    if not ok:
                        last_error = f"grounded verifier: {msg}"
                        continue

                if self._use_step_critic and not _critic_ok(ai_service, step, obs, snippet):
                    last_error = "critic rejected outcome"
                    continue
                self._page.wait_for_timeout(800)
                ss = self.take_screenshot(f"step{step_num}")
                log_entry["dsl_bundle"] = bundle.model_dump()
                log_entry["dsl_bundle_raw"] = data_raw
                log_entry["observation"] = obs
                log_entry["status"] = "success"
                log_entry["screenshot"] = ss
                log_entry["vision_used"] = bool(send_vision)
                log_entry["attempts"] = attempts
                log_entry["finished_at"] = datetime.now().isoformat()
                if obs.get("condition_met") is not None:
                    log_entry["condition_met"] = obs["condition_met"]
                self._step_log.append(log_entry)
                return log_entry
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("Step %d attempt %d/%d: %s", step_num, attempts, retry + 1, last_error)

        log_entry.update(
            status="error",
            error=last_error,
            finished_at=datetime.now().isoformat(),
        )
        if _last_bundle and "dsl_bundle" not in log_entry:
            log_entry["dsl_bundle"] = _last_bundle.model_dump()
            log_entry["dsl_bundle_raw"] = _last_data_raw
            log_entry["dsl_bundle_status"] = "failed"
        self._step_log.append(log_entry)
        return log_entry

    def _replan_remaining(
        self,
        ai_service,
        failed_step: Dict[str, Any],
        remaining_steps: List[Dict[str, Any]],
        error: str,
    ) -> List[Dict[str, Any]]:
        """Ask LLM to re-plan remaining steps given a failure and current page state + vision."""
        dom_ctx = build_dom_context(self._page)
        remaining_desc = "\n".join(
            f"  {s.get('step_number')}. [{s.get('action')}] {s.get('description')}"
            for s in remaining_steps
        )

        replan_screenshot: Optional[bytes] = None
        if self._use_vision:
            try:
                replan_screenshot = self._page.screenshot(type="png", full_page=False)
                print(f"[BrowserVision] Replan: screenshot captured ({len(replan_screenshot):,} bytes)")
            except Exception:
                pass

        prompt = (
            "System: You are a browser-automation re-planner. A step failed during execution. "
            "You can see the current page state (DOM + screenshot). "
            "Produce a corrected JSON array of goal steps that achieves the same goal. "
            "Adapt to the current page. Do NOT guess element selectors -- just describe "
            "the goals in plain English. A downstream refiner with page access will handle selectors. "
            "Return ONLY a JSON array. Each object MUST include: "
            "`step_number` (int), `action` (navigate|search|click|type|scroll|select|wait|verify|add_to_cart|custom), "
            "`description` (required). Optional: target_url, search_query, "
            "element_hint, value, condition, expected_outcome. No markdown fences.\n\n"
            f"User:\n"
            f"Current URL: {self._page.url}\n"
            f"Failed step: [{failed_step.get('action')}] {failed_step.get('description')}\n"
            f"Error: {error}\n\n"
            f"Remaining goals that still need to be done:\n{remaining_desc}\n\n"
            f"--- Current page context ---\n{dom_ctx[:8000]}\n\n"
            "Produce a corrected goal plan that works from the current page state."
        )
        try:
            self._sse_progress("replan", "Re-plan LLM: generating corrected goals from current page...")
            raw = ai_service.call_genai(
                prompt, temperature=0.2, max_tokens=4096,
                screenshot_png=replan_screenshot,
            )
            text = raw.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            parsed = json.loads(text) if text.startswith("[") else []
            if not isinstance(parsed, list):
                match = re.search(r"\[.*\]", text, re.DOTALL)
                parsed = json.loads(match.group()) if match else []
            base = failed_step.get("step_number", 0)
            for i, s in enumerate(parsed):
                s["step_number"] = base + i
            from .step_validator import validate_planner_steps
            validated = validate_planner_steps(parsed)
            print(f"[BrowserPlanner] Re-plan OK: {len(validated)} goal(s) queued")
            self._sse_progress("replan", f"Re-plan OK -- {len(validated)} goal(s) queued from current page.")
            return validated
        except Exception as exc:
            print(f"[BrowserPlanner] Re-plan failed: {exc}")
            self._sse_progress("replan", f"Re-plan failed ({exc}) -- keeping original remaining goals.")
            return remaining_steps

    def run_all(
        self,
        ai_service,
        steps: List[Dict[str, Any]],
        max_replans: int = 2,
        original_query: str = "",
    ) -> List[Dict[str, Any]]:
        """Sync plan-act-observe loop: refine each goal with LIVE page context before executing."""
        if self._is_async_page(self._page):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(
                    self.run_all_async(
                        ai_service, steps, original_query=original_query, max_replans=max_replans
                    )
                )
            raise RuntimeError(
                "Async Playwright page: use `await executor.run_all_async(...)` from async code, "
                "not `run_all()`."
            )

        results: List[Dict[str, Any]] = []
        remaining = list(steps)
        replans_used = 0
        observation_replans_used = 0
        steps_since_obs_check = 0
        query = original_query or ""

        while remaining:
            goal = remaining.pop(0)
            sn = goal.get("step_number", "?")
            sa = goal.get("action", "?")
            sd = (goal.get("description") or "")[:120]

            # ── REFINE: ground the goal against the LIVE page ──────
            self._sse_progress(
                "refine",
                f"Step {sn}: reading page to refine goal [{sa}]: {sd}...",
            )
            snap_before = capture_page_snapshot(self._page)
            page_ctx = format_snapshot_for_llm(snap_before)

            refine_screenshot: Optional[bytes] = None
            if self._use_vision:
                try:
                    refine_screenshot = self._page.screenshot(type="png", full_page=False)
                    print(
                        f"[BrowserVision] Step {sn}: refiner screenshot captured "
                        f"({len(refine_screenshot):,} bytes)"
                    )
                except Exception as exc:
                    print(f"[BrowserVision] Step {sn}: refiner screenshot failed: {exc}")

            step = refine_step_with_page_context(
                ai_service,
                goal,
                page_ctx,
                original_query=query,
                screenshot_png=refine_screenshot,
            )

            sn = step.get("step_number", sn)
            sa = step.get("action", sa)
            sd = (step.get("description") or "")[:120]
            hint = step.get("element_hint", "")
            self._sse_progress(
                "step",
                f"Step {sn} [{sa}]: {sd}"
                + (f" (hint: {hint[:60]})" if hint else ""),
            )

            # ── EXECUTE the refined step ───────────────────────────
            result = self.execute_step(ai_service, step)
            results.append(result)
            snap_after = capture_page_snapshot(self._page)
            summary = summarize_observation(snap_before, snap_after, result)
            st = result.get("status", "?")
            if st == "success":
                self._sse_progress("step", f"Step {sn} completed ({result.get('attempts', 1)} attempt(s)).")
            else:
                err = (result.get("error") or "unknown")[:150]
                self._sse_progress("step", f"Step {sn} failed: {err}")

            # ── OBSERVE: handle failure + periodic replan ──────────
            if result["status"] == "error" and remaining and replans_used < max_replans:
                print(
                    f"[BrowserPlanner] Step {sn} failed -- re-planning "
                    f"({replans_used + 1}/{max_replans}), {len(remaining)} remaining"
                )
                self._sse_thinking(
                    "thinking",
                    f"Failure replan {replans_used + 1}/{max_replans} -- adapting "
                    f"{len(remaining)} remaining goal(s) to the current page.",
                )
                remaining = self._replan_remaining(
                    ai_service, step, remaining, result.get("error", "unknown"),
                )
                replans_used += 1
                steps_since_obs_check = 0
                continue

            if result["status"] == "error":
                print(f"[BrowserPlanner] Step {sn} failed -- no re-plans left.")

            steps_since_obs_check += 1
            if (
                remaining
                and steps_since_obs_check >= REPLAN_AFTER_EVERY_N_STEPS
                and observation_replans_used < MAX_OBSERVATION_REPLANS
            ):
                self._sse_progress(
                    "observe",
                    f"Observation check: asking LLM if {len(remaining)} remaining "
                    f"goal(s) still fit the page...",
                )
                needs, new_rem = check_observation_replan(ai_service, summary, remaining, query)
                observation_replans_used += 1
                steps_since_obs_check = 0
                if needs:
                    from .step_validator import validate_planner_steps

                    try:
                        remaining = validate_planner_steps(new_rem)
                        self._sse_progress(
                            "observe",
                            f"Plan updated -- {len(remaining)} goal(s) after observation replan.",
                        )
                    except ValueError as exc:
                        logger.warning("Observation replan validation failed: %s", exc)
                        self._sse_progress("observe", f"Observation replan invalid ({exc}) -- keeping prior goals.")
                else:
                    self._sse_progress("observe", "Remaining goals still valid -- continuing.")

        return results

    def build_standalone_script(self, steps_results: List[Dict[str, Any]], headless: bool = False) -> str:
        first_goto_url = "https://www.google.com"
        assert_texts: List[str] = []
        for sr in steps_results:
            raw = sr.get("dsl_bundle")
            if not raw or not raw.get("actions"):
                continue
            for a in raw["actions"]:
                if not isinstance(a, dict):
                    continue
                if a.get("type") == "goto" and a.get("url"):
                    first_goto_url = a["url"]
                if a.get("type") == "assert_text_contains" and a.get("text"):
                    assert_texts.append(str(a["text"]))

        return self._build_standalone_script_impl(
            steps_results, headless, first_goto_url, assert_texts
        )

    def _build_standalone_script_impl(
        self,
        steps_results: List[Dict[str, Any]],
        headless: bool,
        first_goto_url: str,
        assert_texts: List[str],
    ) -> str:
        from .action_dsl import GotoAction, ExtractTextAction as _ETA

        lines = [
            "#!/usr/bin/env python3",
            '"""Auto-generated Playwright script from executed DSL bundles.',
            "",
            "Run:  python script.py",
            "Pytest:  pytest script.py -m browser -s",
            "Env:  BROWSER_START_URL, BROWSER_SEARCH_QUERY (optional; patch fills to use SEARCH_QUERY).",
            '"""',
            "",
            "import os",
            "import time",
            "",
            "import pytest",
            "",
            "pytestmark = pytest.mark.browser",
            "",
            f"START_URL = os.environ.get(\"BROWSER_START_URL\", {json.dumps(first_goto_url)})",
            'SEARCH_QUERY = os.environ.get("BROWSER_SEARCH_QUERY", "")',
            "",
            "from playwright.sync_api import sync_playwright",
            "",
            "",
            "def main():",
            "    with sync_playwright() as p:",
            f"        browser = p.chromium.launch(headless={headless}, slow_mo=300)",
            '        context = browser.new_context(viewport={"width": 1366, "height": 768})',
            "        page = context.new_page()",
            "        page.set_default_timeout(30000)",
            "",
        ]
        first_goto_seen = False
        known_vars: set = set()

        for sr in steps_results:
            step_num = sr.get("step_number", "?")
            desc = sr.get("description", "")
            status = sr.get("status", "unknown")
            lines.append(f"        # --- Step {step_num}: {desc} ({status}) ---")
            raw = sr.get("dsl_bundle_raw") or sr.get("dsl_bundle")
            bundle_failed = sr.get("dsl_bundle_status") == "failed"
            if raw and raw.get("actions"):
                try:
                    bundle = parse_dsl_bundle(raw)
                    if bundle_failed:
                        lines.append(
                            f"        # ⚠️  Step {step_num} FAILED — attempted code below (fix selectors before re-running):"
                        )
                    for act in bundle.actions:
                        if not first_goto_seen and isinstance(act, GotoAction):
                            code_line = '        page.goto(START_URL, wait_until="domcontentloaded", timeout=30000)'
                            lines.append(f"        # {code_line.strip()}" if bundle_failed else code_line)
                            first_goto_seen = True
                            continue
                        if isinstance(act, _ETA) and not bundle_failed:
                            known_vars.add(act.store_as)
                        sub = parse_dsl_bundle({"actions": [act.model_dump()]})
                        for pl in bundle_to_playwright_lines(sub, known_vars=known_vars):
                            lines.append(f"        # {pl.strip()}" if bundle_failed else pl)
                except Exception:
                    lines.append(f'        print("Step {step_num}: could not export DSL")')
            lines.append(f'        print("Step {step_num} done")')
            lines.append("        time.sleep(0.5)")
            lines.append("")
        lines += [
            "        browser.close()",
            "",
            "",
            "# --- Assertions derived from verify / assert_text_contains DSL (uncomment to enforce) ---",
        ]
        for t in assert_texts:
            safe = json.dumps(t)
            lines.append(f"# assert {safe} in page.locator(\"body\").inner_text(timeout=10000)")
        lines += [
            "",
            "",
            "def test_recorded_browser_flow():",
            '    """Regression entrypoint — run with: pytest -m browser -s"""',
            "    main()",
            "",
            "",
            'if __name__ == "__main__":',
            "    main()",
            "",
        ]
        return "\n".join(lines)

    # ── HTML report with per-action screenshots ─────────────────────

    def build_html_report(
        self,
        query: str,
        steps_results: List[Dict[str, Any]],
        session_id: str = "",
    ) -> str:
        """Generate a self-contained HTML report with embedded base64 screenshots for every action."""
        import base64

        def _embed_img(path_str: str) -> str:
            """Read a screenshot file and return a base64 data-URI <img> tag."""
            if not path_str:
                return '<span class="no-screenshot">No screenshot</span>'
            p = Path(path_str)
            if not p.exists():
                return f'<span class="no-screenshot">File not found: {p.name}</span>'
            try:
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                return (
                    f'<img src="data:image/png;base64,{b64}" '
                    f'alt="{p.stem}" class="screenshot" loading="lazy" />'
                )
            except Exception as exc:
                return f'<span class="no-screenshot">Read error: {exc}</span>'

        now = datetime.now()
        succeeded = sum(1 for r in steps_results if r.get("status") == "success")
        failed = sum(1 for r in steps_results if r.get("status") == "error")
        total = len(steps_results)

        # Build step cards
        step_cards = []
        for r in steps_results:
            step_num = r.get("step_number", "?")
            status = r.get("status", "unknown")
            status_cls = "success" if status == "success" else "error" if status == "error" else "pending"
            status_icon = "\u2705" if status == "success" else "\u274c" if status == "error" else "\u23f3"
            desc = r.get("description", "")
            action = r.get("action", "")
            error = r.get("error", "")
            attempts = r.get("attempts", 1)
            vision = r.get("vision_used", False)

            # Collect per-action screenshots from the observation
            action_screenshots_html = ""
            obs = r.get("observation", {})
            executed_actions = obs.get("executed", []) if isinstance(obs, dict) else []

            if executed_actions:
                action_items = []
                for idx, ea in enumerate(executed_actions):
                    ea_type = ea.get("type", "?")
                    ea_screenshot = ea.get("screenshot", "")
                    detail_parts = []
                    for k, v in ea.items():
                        if k not in ("type", "screenshot"):
                            detail_parts.append(f'<span class="action-detail">{k}: {json.dumps(v, default=str)[:120]}</span>')
                    details_html = " ".join(detail_parts) if detail_parts else ""
                    img_html = _embed_img(ea_screenshot) if ea_screenshot else ""
                    action_items.append(f"""
                        <div class="action-card">
                            <div class="action-header">
                                <span class="action-idx">Action {idx + 1}</span>
                                <code class="action-type">{ea_type}</code>
                                {details_html}
                            </div>
                            {f'<div class="action-screenshot">{img_html}</div>' if img_html else ''}
                        </div>""")
                action_screenshots_html = "\n".join(action_items)

            # Step-level screenshot (taken after all actions in the step)
            step_screenshot = _embed_img(r.get("screenshot", ""))

            step_cards.append(f"""
            <div class="step-card {status_cls}">
                <div class="step-header">
                    <span class="step-icon">{status_icon}</span>
                    <h3>Step {step_num}: {desc}</h3>
                    <span class="step-badge {status_cls}">{status.upper()}</span>
                </div>
                <div class="step-meta">
                    <span>Action: <code>{action}</code></span>
                    <span>Attempts: {attempts}</span>
                    <span>Vision: {'Yes' if vision else 'No'}</span>
                    {f'<span class="step-error">Error: {error[:200]}</span>' if error else ''}
                </div>
                <div class="actions-timeline">
                    <h4>Actions Executed</h4>
                    {action_screenshots_html if action_screenshots_html else '<p class="no-actions">No action details recorded</p>'}
                </div>
                <div class="step-final-screenshot">
                    <h4>Final State</h4>
                    {step_screenshot}
                </div>
            </div>""")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Browser Agent Report — {now.strftime('%Y-%m-%d %H:%M')}</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #242837;
    --border: #2e3348;
    --text: #e1e4ed;
    --text-dim: #8b8fa3;
    --accent: #6c7bff;
    --success: #34d399;
    --error: #f87171;
    --warning: #fbbf24;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    padding: 2rem;
  }}
  .report-container {{ max-width: 1200px; margin: 0 auto; }}
  .report-header {{
    background: linear-gradient(135deg, #1e2235 0%, #2a1f3d 100%);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 2rem;
    margin-bottom: 2rem;
  }}
  .report-header h1 {{
    font-size: 1.75rem;
    margin-bottom: 0.5rem;
    background: linear-gradient(135deg, #6c7bff, #a78bfa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .report-header .query {{ color: var(--text-dim); font-size: 1.05rem; margin-bottom: 1rem; }}
  .stats-row {{
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
  }}
  .stat {{
    background: var(--surface2);
    border-radius: 10px;
    padding: 0.75rem 1.25rem;
    font-size: 0.9rem;
  }}
  .stat strong {{ color: var(--accent); }}
  .stat.success strong {{ color: var(--success); }}
  .stat.error strong {{ color: var(--error); }}

  .step-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 1.5rem;
    overflow: hidden;
    transition: border-color 0.2s;
  }}
  .step-card:hover {{ border-color: var(--accent); }}
  .step-card.success {{ border-left: 4px solid var(--success); }}
  .step-card.error {{ border-left: 4px solid var(--error); }}
  .step-header {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 1.25rem 1.5rem;
    background: var(--surface2);
    border-bottom: 1px solid var(--border);
  }}
  .step-header h3 {{ flex: 1; font-size: 1.05rem; font-weight: 600; }}
  .step-icon {{ font-size: 1.3rem; }}
  .step-badge {{
    padding: 0.2rem 0.7rem;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.05em;
  }}
  .step-badge.success {{ background: rgba(52,211,153,0.15); color: var(--success); }}
  .step-badge.error {{ background: rgba(248,113,113,0.15); color: var(--error); }}
  .step-meta {{
    display: flex;
    gap: 1.5rem;
    padding: 0.75rem 1.5rem;
    color: var(--text-dim);
    font-size: 0.85rem;
    flex-wrap: wrap;
  }}
  .step-meta code {{
    background: var(--surface2);
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    color: var(--accent);
  }}
  .step-error {{ color: var(--error); }}
  .actions-timeline {{
    padding: 1rem 1.5rem;
  }}
  .actions-timeline h4, .step-final-screenshot h4 {{
    font-size: 0.85rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 0.75rem;
  }}
  .action-card {{
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.75rem;
  }}
  .action-header {{
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
    margin-bottom: 0.5rem;
  }}
  .action-idx {{ color: var(--text-dim); font-size: 0.8rem; font-weight: 600; }}
  .action-type {{
    background: var(--accent);
    color: #fff;
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
  }}
  .action-detail {{
    font-size: 0.78rem;
    color: var(--text-dim);
    background: var(--bg);
    padding: 0.1rem 0.4rem;
    border-radius: 3px;
  }}
  .action-screenshot {{ margin-top: 0.5rem; }}
  .action-screenshot img, .step-final-screenshot img {{
    max-width: 100%;
    border-radius: 8px;
    border: 1px solid var(--border);
    cursor: pointer;
    transition: transform 0.2s;
  }}
  .action-screenshot img:hover, .step-final-screenshot img:hover {{
    transform: scale(1.02);
  }}
  .step-final-screenshot {{
    padding: 1rem 1.5rem;
    border-top: 1px solid var(--border);
  }}
  .no-screenshot {{ color: var(--text-dim); font-style: italic; font-size: 0.85rem; }}
  .no-actions {{ color: var(--text-dim); font-style: italic; }}

  .footer {{
    text-align: center;
    color: var(--text-dim);
    font-size: 0.8rem;
    padding: 2rem 0 1rem;
    border-top: 1px solid var(--border);
    margin-top: 2rem;
  }}

  /* Lightbox */
  .lightbox {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.9);
    z-index: 9999;
    justify-content: center;
    align-items: center;
    cursor: zoom-out;
  }}
  .lightbox.active {{ display: flex; }}
  .lightbox img {{
    max-width: 95vw;
    max-height: 95vh;
    border-radius: 8px;
  }}
</style>
</head>
<body>
<div class="report-container">
  <div class="report-header">
    <h1>Browser Automation Report</h1>
    <div class="query">{query}</div>
    <div class="stats-row">
      <div class="stat"><strong>{total}</strong> Total Steps</div>
      <div class="stat success"><strong>{succeeded}</strong> Succeeded</div>
      <div class="stat error"><strong>{failed}</strong> Failed</div>
      <div class="stat">Session: <strong>{session_id[:12]}…</strong></div>
      <div class="stat">{now.strftime('%Y-%m-%d %H:%M:%S')}</div>
    </div>
  </div>

  {''.join(step_cards)}

  <div class="footer">
    Generated by Browser Automation Agent &mdash; {now.strftime('%Y-%m-%d %H:%M:%S')}
  </div>
</div>

<div class="lightbox" id="lightbox" onclick="this.classList.remove('active')">
  <img id="lightbox-img" src="" alt="Full screenshot" />
</div>

<script>
document.querySelectorAll('.screenshot').forEach(img => {{
  img.style.cursor = 'zoom-in';
  img.addEventListener('click', () => {{
    document.getElementById('lightbox-img').src = img.src;
    document.getElementById('lightbox').classList.add('active');
  }});
}});
</script>
</body>
</html>"""

        # Save HTML report
        report_path = LOGS_DIR / f"report_{session_id}_{now.strftime('%Y%m%d_%H%M%S')}.html"
        report_path.write_text(html, encoding="utf-8")
        logger.info("HTML report saved: %s", report_path)
        return str(report_path)
