"""Whitelisted browser action DSL — parsed from LLM JSON and executed via Playwright.

No arbitrary code execution: only these action types are mapped to deterministic
Playwright calls.  Supports both sync and async execution, with optional
parallel action groups for form-heavy workflows.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time as _time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

MAX_ACTIONS_PER_STEP = 25
MAX_WAIT_MS = 30_000
MAX_TOTAL_WAIT_MS_PER_STEP = 90_000


# ═══════════════════════════════════════════════════════════════════
#  Action type definitions (unchanged schema, all Pydantic-validated)
# ═══════════════════════════════════════════════════════════════════

class GotoAction(BaseModel):
    type: Literal["goto"] = "goto"
    url: str

    @field_validator("url")
    @classmethod
    def http_only(cls, v: str) -> str:
        v = (v or "").strip()
        if not re.match(r"^https?://", v, re.I):
            raise ValueError("goto.url must start with http:// or https://")
        if len(v) > 2048:
            raise ValueError("url too long")
        return v


class WaitMsAction(BaseModel):
    type: Literal["wait_ms"] = "wait_ms"
    ms: int = Field(..., ge=0, le=MAX_WAIT_MS)


class WaitLoadAction(BaseModel):
    type: Literal["wait_load"] = "wait_load"
    state: Literal["domcontentloaded", "load", "networkidle"] = "domcontentloaded"


class ClickRoleAction(BaseModel):
    type: Literal["click_role"] = "click_role"
    role: Literal[
        "button", "link", "textbox", "searchbox", "combobox",
        "checkbox", "radio", "tab", "menuitem",
        "option", "listbox", "menu", "switch",
    ]
    name: str = Field(..., min_length=1, max_length=500)
    exact: bool = False
    force: bool = Field(default=False)
    nth: Optional[int] = Field(
        default=None,
        ge=0,
        le=99,
        description="0-based index when multiple elements match role+name (e.g. duplicate menu labels).",
    )


class ClickTextAction(BaseModel):
    type: Literal["click_text"] = "click_text"
    text: str = Field(..., min_length=1, max_length=500)
    exact: bool = False
    force: bool = Field(default=False)
    nth: Optional[int] = Field(
        default=None,
        ge=0,
        le=99,
        description="0-based index when the same text appears multiple times (e.g. dropdown trigger + selected row).",
    )


class FillPlaceholderAction(BaseModel):
    type: Literal["fill_placeholder"] = "fill_placeholder"
    placeholder: str = Field(..., min_length=1, max_length=300)
    value: str = Field(..., max_length=10_000)


class FillRoleAction(BaseModel):
    type: Literal["fill_role"] = "fill_role"
    role: Literal["textbox", "searchbox", "combobox"] = "textbox"
    name: Optional[str] = None
    value: str = Field(..., max_length=10_000)


class FillLabelAction(BaseModel):
    type: Literal["fill_label"] = "fill_label"
    label: str = Field(..., min_length=1, max_length=400)
    value: str = Field(..., max_length=10_000)
    exact: bool = False


class PressAction(BaseModel):
    type: Literal["press"] = "press"
    key: str = Field(..., min_length=1, max_length=50)


class ScrollAction(BaseModel):
    type: Literal["scroll"] = "scroll"
    delta_y: int = Field(..., ge=-5000, le=5000)


class AssertTextContainsAction(BaseModel):
    type: Literal["assert_text_contains"] = "assert_text_contains"
    text: str = Field(..., min_length=1, max_length=500)


class SelectOptionAction(BaseModel):
    type: Literal["select_option"] = "select_option"
    selector: str = Field(..., min_length=1, max_length=500)
    value: Optional[str] = Field(None)
    label: Optional[str] = Field(None)
    index: Optional[int] = Field(None, ge=0, le=500)


class ClickCssAction(BaseModel):
    type: Literal["click_css"] = "click_css"
    selector: str = Field(..., min_length=1, max_length=500)
    force: bool = Field(default=False)


class HoverAction(BaseModel):
    type: Literal["hover"] = "hover"
    selector: Optional[str] = Field(None, max_length=500)
    role: Optional[str] = Field(None, max_length=64)
    name: Optional[str] = Field(None, max_length=500)
    text: Optional[str] = Field(None, max_length=500)


class EvaluateConditionAction(BaseModel):
    type: Literal["evaluate_condition"] = "evaluate_condition"
    condition: str = Field(..., min_length=1, max_length=1000)
    extract_selector: Optional[str] = Field(None, max_length=500)


class ExtractTextAction(BaseModel):
    """Extract text from an element and store it in a named variable for later steps."""
    type: Literal["extract_text"] = "extract_text"
    selector: str = Field(..., min_length=1, max_length=500)
    store_as: str = Field(
        ..., min_length=1, max_length=100,
        pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$",
        description="Variable name to store the extracted text under (use {{name}} to reference later).",
    )
    max_length: int = Field(default=50_000, ge=1, le=200_000)


class TypeTextAction(BaseModel):
    """Type text character-by-character (works on contenteditable / rich editors unlike fill)."""
    type: Literal["type_text"] = "type_text"
    text: str = Field(..., min_length=1, max_length=200_000)
    selector: Optional[str] = Field(
        None, max_length=500,
        description="CSS selector to click/focus before typing. If omitted, types into the currently focused element.",
    )
    delay_ms: int = Field(
        default=0, ge=0, le=200,
        description="Per-character delay in ms. 0 = instant insert (fast paste), >0 = simulated typing.",
    )


class WaitForSelectorAction(BaseModel):
    """Wait until an element matching the selector reaches the desired state."""
    type: Literal["wait_for_selector"] = "wait_for_selector"
    selector: str = Field(..., min_length=1, max_length=500)
    state: Literal["attached", "detached", "visible", "hidden"] = "visible"
    timeout_ms: int = Field(default=30_000, ge=1000, le=120_000)


class WaitForTextStableAction(BaseModel):
    """Wait until the text content of an element stops changing (e.g. streaming LLM responses)."""
    type: Literal["wait_for_text_stable"] = "wait_for_text_stable"
    selector: str = Field(..., min_length=1, max_length=500)
    timeout_ms: int = Field(default=90_000, ge=5000, le=300_000)
    stable_ms: int = Field(
        default=5000, ge=1000, le=30_000,
        description="How long the text must remain unchanged to be considered stable.",
    )


DSLAction = (
    GotoAction
    | WaitMsAction
    | WaitLoadAction
    | ClickRoleAction
    | ClickTextAction
    | FillPlaceholderAction
    | FillRoleAction
    | FillLabelAction
    | PressAction
    | ScrollAction
    | AssertTextContainsAction
    | SelectOptionAction
    | ClickCssAction
    | HoverAction
    | EvaluateConditionAction
    | ExtractTextAction
    | TypeTextAction
    | WaitForSelectorAction
    | WaitForTextStableAction
)

# Set of action types safe to run in parallel (independent, no ordering dependency)
_PARALLELIZABLE_TYPES = frozenset({
    "fill_placeholder", "fill_role", "fill_label",
})


class DSLBundle(BaseModel):
    """LLM output: ordered list of actions for one planner step."""

    actions: List[DSLAction]
    notes: Optional[str] = None
    parallel: bool = Field(
        default=False,
        description="If true, independent fill actions run concurrently (form optimization).",
    )

    @field_validator("actions")
    @classmethod
    def _cap_actions(cls, v: List[Any]) -> List[Any]:
        if len(v) > MAX_ACTIONS_PER_STEP:
            raise ValueError(f"at most {MAX_ACTIONS_PER_STEP} actions per step")
        return v


# ═══════════════════════════════════════════════════════════════════
#  Parsing
# ═══════════════════════════════════════════════════════════════════

_ACTION_PARSERS = {
    "goto": GotoAction,
    "wait_ms": WaitMsAction,
    "wait_load": WaitLoadAction,
    "click_role": ClickRoleAction,
    "click_text": ClickTextAction,
    "fill_placeholder": FillPlaceholderAction,
    "fill_role": FillRoleAction,
    "fill_label": FillLabelAction,
    "press": PressAction,
    "scroll": ScrollAction,
    "assert_text_contains": AssertTextContainsAction,
    "select_option": SelectOptionAction,
    "click_css": ClickCssAction,
    "hover": HoverAction,
    "evaluate_condition": EvaluateConditionAction,
    "extract_text": ExtractTextAction,
    "type_text": TypeTextAction,
    "wait_for_selector": WaitForSelectorAction,
    "wait_for_text_stable": WaitForTextStableAction,
}


def parse_dsl_bundle(raw_json: str | dict) -> DSLBundle:
    """Parse and validate LLM JSON into a DSLBundle."""
    if isinstance(raw_json, str):
        data = json.loads(raw_json)
    else:
        data = dict(raw_json)
    actions_raw = data.get("actions")
    if not isinstance(actions_raw, list):
        raise ValueError("bundle must contain 'actions' array")
    parsed: List[DSLAction] = []
    for i, item in enumerate(actions_raw):
        if not isinstance(item, dict):
            raise ValueError(f"actions[{i}] must be an object")
        t = item.get("type")
        parser = _ACTION_PARSERS.get(t)
        if parser is None:
            raise ValueError(f"unknown action type: {t!r}")
        parsed.append(parser.model_validate(item))
    total_wait = sum(a.ms for a in parsed if isinstance(a, WaitMsAction))
    if total_wait > MAX_TOTAL_WAIT_MS_PER_STEP:
        raise ValueError(f"sum of wait_ms exceeds {MAX_TOTAL_WAIT_MS_PER_STEP}ms")
    return DSLBundle(
        actions=parsed,
        notes=data.get("notes"),
        parallel=bool(data.get("parallel", False)),
    )


def resolve_bundle_variables(raw_data: dict, data_store: Dict[str, str]) -> dict:
    """Replace ``{{var_name}}`` placeholders in action string values with stored data.

    Called on the raw JSON dict *before* ``parse_dsl_bundle`` so Pydantic
    validates the resolved values.
    """
    if not data_store:
        return raw_data

    def _resolve(s: str) -> str:
        for key, value in data_store.items():
            s = s.replace("{{" + key + "}}", value)
        return s

    resolved_actions = []
    for action in raw_data.get("actions", []):
        if isinstance(action, dict):
            new_action = {}
            for k, v in action.items():
                new_action[k] = _resolve(v) if isinstance(v, str) else v
            resolved_actions.append(new_action)
        else:
            resolved_actions.append(action)

    result = dict(raw_data)
    result["actions"] = resolved_actions
    return result


# ═══════════════════════════════════════════════════════════════════
#  Sync helpers
# ═══════════════════════════════════════════════════════════════════

def _try_bbox_sync(el) -> Optional[Dict[str, float]]:
    """Viewport CSS pixels — matches Playwright viewport screenshots."""
    try:
        b = el.bounding_box()
        if b:
            return {
                "x": float(b["x"]),
                "y": float(b["y"]),
                "width": float(b["width"]),
                "height": float(b["height"]),
            }
    except Exception:
        pass
    return None


def _attach_target_overlay(
    rec: Dict[str, Any],
    kind: str,
    label: str,
    box: Optional[Dict[str, float]],
) -> None:
    if not box:
        return
    rec["target_rect"] = box
    rec["target_kind"] = kind
    if label:
        rec["target_label"] = label[:200]


def _locator_click(
    page,
    loc,
    timeout: int = 30_000,
    force: bool = False,
    nth: Optional[int] = None,
) -> Optional[Dict[str, float]]:
    el = loc.nth(nth) if nth is not None else loc.first
    el.wait_for(state="visible", timeout=timeout)
    el.scroll_into_view_if_needed(timeout=timeout)
    box = _try_bbox_sync(el)
    el.click(timeout=timeout, force=force)
    return box


def _fill_locator(loc, value: str, timeout: int = 30_000) -> Optional[Dict[str, float]]:
    el = loc.first
    el.wait_for(state="visible", timeout=timeout)
    el.scroll_into_view_if_needed(timeout=timeout)
    box = _try_bbox_sync(el)
    el.fill(value, timeout=timeout)
    return box


def _take_action_screenshot(page, screenshot_dir: Optional[Path], step_num: int, action_idx: int, action_type: str) -> str:
    if screenshot_dir is None:
        return ""
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y%m%d_%H%M%S_%f")
    fname = f"step{step_num}_action{action_idx}_{action_type}_{ts}.png"
    fpath = screenshot_dir / fname
    try:
        page.screenshot(path=str(fpath), full_page=False)
    except Exception as exc:
        logger.warning("Action screenshot failed: %s", exc)
        return ""
    return str(fpath)


def _execute_single_action_sync(page, act: DSLAction, screenshot_dir, step_num, action_idx) -> Dict[str, Any]:
    """Execute a single DSL action (sync) and return its record dict."""
    rec: Dict[str, Any] = {"type": act.type}
    condition_met = None

    if isinstance(act, GotoAction):
        page.goto(act.url, wait_until="domcontentloaded", timeout=30_000)
        rec["url"] = act.url
    elif isinstance(act, WaitMsAction):
        page.wait_for_timeout(act.ms)
        rec["ms"] = act.ms
    elif isinstance(act, WaitLoadAction):
        page.wait_for_load_state(act.state, timeout=30_000)
        rec["state"] = act.state
    elif isinstance(act, ClickRoleAction):
        loc = page.get_by_role(act.role, name=act.name, exact=act.exact)
        box = _locator_click(page, loc, force=act.force, nth=act.nth)
        _attach_target_overlay(rec, "click", f"{act.role}: {act.name}", box)
        rec["role"] = act.role
        rec["name"] = act.name
        if act.nth is not None:
            rec["nth"] = act.nth
    elif isinstance(act, ClickTextAction):
        loc = page.get_by_text(act.text, exact=act.exact)
        box = _locator_click(page, loc, force=act.force, nth=act.nth)
        _attach_target_overlay(rec, "click", f'"{act.text[:80]}{"..." if len(act.text) > 80 else ""}"', box)
        rec["text"] = act.text
        if act.nth is not None:
            rec["nth"] = act.nth
    elif isinstance(act, FillPlaceholderAction):
        loc = page.get_by_placeholder(act.placeholder)
        box = _fill_locator(loc, act.value)
        _attach_target_overlay(rec, "fill", f"placeholder: {act.placeholder}", box)
        rec["placeholder"] = act.placeholder
    elif isinstance(act, FillRoleAction):
        if act.name:
            loc = page.get_by_role(act.role, name=act.name)
        else:
            loc = page.get_by_role(act.role)
        box = _fill_locator(loc, act.value)
        _attach_target_overlay(
            rec,
            "fill",
            f"{act.role}: {act.name}" if act.name else act.role,
            box,
        )
        rec["role"] = act.role
    elif isinstance(act, FillLabelAction):
        loc = page.get_by_label(act.label, exact=act.exact)
        box = _fill_locator(loc, act.value)
        _attach_target_overlay(rec, "fill", f"label: {act.label[:120]}", box)
        rec["label"] = act.label
    elif isinstance(act, PressAction):
        page.keyboard.press(act.key)
        rec["key"] = act.key
    elif isinstance(act, ScrollAction):
        page.mouse.wheel(0, act.delta_y)
        rec["delta_y"] = act.delta_y
    elif isinstance(act, AssertTextContainsAction):
        body = page.locator("body")
        text = body.inner_text(timeout=10_000)
        condition_met = act.text in text
        rec["text"] = act.text
        rec["result"] = condition_met
    elif isinstance(act, SelectOptionAction):
        loc = page.locator(act.selector)
        kwargs: Dict[str, Any] = {}
        if act.value is not None:
            kwargs["value"] = act.value
        elif act.label is not None:
            kwargs["label"] = act.label
        elif act.index is not None:
            kwargs["index"] = act.index
        sel_el = loc.first
        sel_el.wait_for(state="visible", timeout=30_000)
        box = _try_bbox_sync(sel_el)
        _attach_target_overlay(rec, "select", act.selector[:120], box)
        loc.select_option(**kwargs, timeout=30_000)
        rec["selector"] = act.selector
        rec["selected"] = kwargs
    elif isinstance(act, ClickCssAction):
        loc = page.locator(act.selector).first
        loc.wait_for(state="visible", timeout=30_000)
        loc.scroll_into_view_if_needed(timeout=30_000)
        box = _try_bbox_sync(loc)
        loc.click(timeout=30_000, force=act.force)
        _attach_target_overlay(rec, "click", act.selector[:120], box)
        rec["selector"] = act.selector
    elif isinstance(act, HoverAction):
        if act.selector:
            loc = page.locator(act.selector).first
        elif act.role and act.name:
            loc = page.get_by_role(act.role, name=act.name).first
        elif act.text:
            loc = page.get_by_text(act.text).first
        else:
            raise ValueError("hover requires selector, role+name, or text")
        loc.wait_for(state="visible", timeout=15_000)
        box = _try_bbox_sync(loc)
        loc.hover(timeout=15_000)
        _attach_target_overlay(
            rec,
            "hover",
            act.selector[:80] if act.selector else (f"{act.role}: {act.name}" if act.role and act.name else (act.text or "hover")),
            box,
        )
        rec["hovered"] = True
    elif isinstance(act, EvaluateConditionAction):
        if act.extract_selector:
            el_text = page.locator(act.extract_selector).first.inner_text(timeout=10_000)
        else:
            el_text = page.locator("body").inner_text(timeout=10_000)[:3000]
        rec["condition"] = act.condition
        rec["extracted_text"] = el_text[:2000]
        rec["needs_llm_eval"] = True
    elif isinstance(act, ExtractTextAction):
        el = page.locator(act.selector).first
        el.wait_for(state="visible", timeout=30_000)
        extracted = el.inner_text(timeout=30_000)
        extracted = extracted[:act.max_length]
        rec["selector"] = act.selector
        rec["store_as"] = act.store_as
        rec["extracted_text"] = extracted
        rec["text_length"] = len(extracted)
    elif isinstance(act, TypeTextAction):
        if act.selector:
            loc = page.locator(act.selector).first
            loc.wait_for(state="visible", timeout=30_000)
            loc.click(timeout=30_000)
            # Wait for editor initialization (rich text editors need time after focus)
            page.wait_for_timeout(500)
        if act.delay_ms > 0:
            page.keyboard.type(act.text, delay=act.delay_ms)
            rec["method"] = "type"
        else:
            # Detect contenteditable — insert_text (CDP Input.insertText) doesn't
            # fire proper beforeinput events that rich text editors (LinkedIn,
            # ChatGPT, Notion, etc.) require.  Use execCommand('insertText') which
            # fires browser-native events, then fall back to keyboard.type.
            is_ce = page.evaluate(
                "() => document.activeElement?.isContentEditable === true"
            )
            if is_ce:
                ok = page.evaluate(
                    "(text) => document.execCommand('insertText', false, text)",
                    act.text,
                )
                if ok:
                    rec["method"] = "execCommand_insertText"
                else:
                    # execCommand failed — fall back to keyboard.type (slow but universal)
                    page.keyboard.type(act.text, delay=0)
                    rec["method"] = "type_fallback"
            else:
                page.keyboard.insert_text(act.text)
                rec["method"] = "insert_text"
        rec["typed_length"] = len(act.text)
    elif isinstance(act, WaitForSelectorAction):
        page.wait_for_selector(act.selector, state=act.state, timeout=act.timeout_ms)
        rec["selector"] = act.selector
        rec["state"] = act.state
    elif isinstance(act, WaitForTextStableAction):
        sel = act.selector
        timeout_sec = act.timeout_ms / 1000
        stable_sec = act.stable_ms / 1000
        start = _time.time()
        last_text = ""
        last_change = start
        while True:
            try:
                current = page.locator(sel).first.inner_text(timeout=5000)
            except Exception:
                current = ""
            if current != last_text:
                last_text = current
                last_change = _time.time()
            if (_time.time() - last_change) >= stable_sec and last_text:
                break
            if (_time.time() - start) > timeout_sec:
                break
            page.wait_for_timeout(500)
        rec["selector"] = sel
        rec["stable"] = (_time.time() - last_change) >= stable_sec
        rec["text_length"] = len(last_text)

    if screenshot_dir is not None and act.type not in ("wait_ms",):
        ss_path = _take_action_screenshot(page, screenshot_dir, step_num, action_idx, act.type)
        if ss_path:
            rec["screenshot"] = ss_path

    if condition_met is not None:
        rec["_condition_met"] = condition_met

    return rec


def execute_dsl_actions(
    page,
    bundle: DSLBundle,
    screenshot_dir: Optional[Path] = None,
    step_num: int = 0,
) -> Dict[str, Any]:
    """Run validated DSL actions in order (sync). Returns observation dict.

    Individual action failures are caught and recorded — the function stops at
    the first error but does NOT raise, so callers can inspect partial results.
    """
    condition_met: Optional[bool] = None
    url_before = page.url
    executed: List[Dict[str, Any]] = []
    failed_action_idx: Optional[int] = None
    failed_action_error: Optional[str] = None

    for action_idx, act in enumerate(bundle.actions):
        try:
            rec = _execute_single_action_sync(page, act, screenshot_dir, step_num, action_idx)
            if "_condition_met" in rec:
                condition_met = rec.pop("_condition_met")
            executed.append(rec)
        except Exception as exc:
            logger.warning(
                "Step %d action %d (%s) failed: %s",
                step_num, action_idx, act.type, exc,
            )
            executed.append({
                "type": act.type,
                "error": f"{type(exc).__name__}: {exc}",
                "action_idx": action_idx,
            })
            failed_action_idx = action_idx
            failed_action_error = f"{type(exc).__name__}: {exc}"
            break  # stop at first failure

    result: Dict[str, Any] = {
        "executed": executed,
        "url_before": url_before,
        "url_after": page.url,
        "condition_met": condition_met,
    }
    if failed_action_idx is not None:
        result["partial_failure"] = True
        result["failed_action_idx"] = failed_action_idx
        result["failed_action_error"] = failed_action_error
        result["actions_completed"] = failed_action_idx
        result["actions_total"] = len(bundle.actions)
    return result


# ═══════════════════════════════════════════════════════════════════
#  Async helpers
# ═══════════════════════════════════════════════════════════════════

async def _try_bbox_async(el) -> Optional[Dict[str, float]]:
    try:
        b = await el.bounding_box()
        if b:
            return {
                "x": float(b["x"]),
                "y": float(b["y"]),
                "width": float(b["width"]),
                "height": float(b["height"]),
            }
    except Exception:
        pass
    return None


async def _async_locator_click(
    loc,
    timeout: int = 30_000,
    force: bool = False,
    nth: Optional[int] = None,
) -> Optional[Dict[str, float]]:
    el = loc.nth(nth) if nth is not None else loc.first
    await el.wait_for(state="visible", timeout=timeout)
    await el.scroll_into_view_if_needed(timeout=timeout)
    box = await _try_bbox_async(el)
    await el.click(timeout=timeout, force=force)
    return box


async def _async_fill_locator(loc, value: str, timeout: int = 30_000) -> Optional[Dict[str, float]]:
    el = loc.first
    await el.wait_for(state="visible", timeout=timeout)
    await el.scroll_into_view_if_needed(timeout=timeout)
    box = await _try_bbox_async(el)
    await el.fill(value, timeout=timeout)
    return box


async def _async_take_screenshot(page, screenshot_dir: Optional[Path], step_num: int, action_idx: int, action_type: str) -> str:
    if screenshot_dir is None:
        return ""
    from datetime import datetime as _dt
    ts = _dt.now().strftime("%Y%m%d_%H%M%S_%f")
    fname = f"step{step_num}_action{action_idx}_{action_type}_{ts}.png"
    fpath = screenshot_dir / fname
    try:
        await page.screenshot(path=str(fpath), full_page=False)
    except Exception as exc:
        logger.warning("Action screenshot failed: %s", exc)
        return ""
    return str(fpath)


async def _async_execute_single_action(page, act: DSLAction, screenshot_dir, step_num, action_idx) -> Dict[str, Any]:
    """Execute a single DSL action (async) and return its record dict."""
    rec: Dict[str, Any] = {"type": act.type}
    condition_met = None

    if isinstance(act, GotoAction):
        await page.goto(act.url, wait_until="domcontentloaded", timeout=30_000)
        rec["url"] = act.url
    elif isinstance(act, WaitMsAction):
        await page.wait_for_timeout(act.ms)
        rec["ms"] = act.ms
    elif isinstance(act, WaitLoadAction):
        await page.wait_for_load_state(act.state, timeout=30_000)
        rec["state"] = act.state
    elif isinstance(act, ClickRoleAction):
        loc = page.get_by_role(act.role, name=act.name, exact=act.exact)
        box = await _async_locator_click(loc, force=act.force, nth=act.nth)
        _attach_target_overlay(rec, "click", f"{act.role}: {act.name}", box)
        rec["role"] = act.role
        rec["name"] = act.name
        if act.nth is not None:
            rec["nth"] = act.nth
    elif isinstance(act, ClickTextAction):
        loc = page.get_by_text(act.text, exact=act.exact)
        box = await _async_locator_click(loc, force=act.force, nth=act.nth)
        _attach_target_overlay(rec, "click", f'"{act.text[:80]}{"..." if len(act.text) > 80 else ""}"', box)
        rec["text"] = act.text
        if act.nth is not None:
            rec["nth"] = act.nth
    elif isinstance(act, FillPlaceholderAction):
        loc = page.get_by_placeholder(act.placeholder)
        box = await _async_fill_locator(loc, act.value)
        _attach_target_overlay(rec, "fill", f"placeholder: {act.placeholder}", box)
        rec["placeholder"] = act.placeholder
    elif isinstance(act, FillRoleAction):
        if act.name:
            loc = page.get_by_role(act.role, name=act.name)
        else:
            loc = page.get_by_role(act.role)
        box = await _async_fill_locator(loc, act.value)
        _attach_target_overlay(
            rec,
            "fill",
            f"{act.role}: {act.name}" if act.name else act.role,
            box,
        )
        rec["role"] = act.role
    elif isinstance(act, FillLabelAction):
        loc = page.get_by_label(act.label, exact=act.exact)
        box = await _async_fill_locator(loc, act.value)
        _attach_target_overlay(rec, "fill", f"label: {act.label[:120]}", box)
        rec["label"] = act.label
    elif isinstance(act, PressAction):
        await page.keyboard.press(act.key)
        rec["key"] = act.key
    elif isinstance(act, ScrollAction):
        await page.mouse.wheel(0, act.delta_y)
        rec["delta_y"] = act.delta_y
    elif isinstance(act, AssertTextContainsAction):
        body = page.locator("body")
        text = await body.inner_text(timeout=10_000)
        condition_met = act.text in text
        rec["text"] = act.text
        rec["result"] = condition_met
    elif isinstance(act, SelectOptionAction):
        loc = page.locator(act.selector)
        kwargs: Dict[str, Any] = {}
        if act.value is not None:
            kwargs["value"] = act.value
        elif act.label is not None:
            kwargs["label"] = act.label
        elif act.index is not None:
            kwargs["index"] = act.index
        sel_el = loc.first
        await sel_el.wait_for(state="visible", timeout=30_000)
        box = await _try_bbox_async(sel_el)
        _attach_target_overlay(rec, "select", act.selector[:120], box)
        await loc.select_option(**kwargs, timeout=30_000)
        rec["selector"] = act.selector
        rec["selected"] = kwargs
    elif isinstance(act, ClickCssAction):
        loc = page.locator(act.selector).first
        await loc.wait_for(state="visible", timeout=30_000)
        await loc.scroll_into_view_if_needed(timeout=30_000)
        box = await _try_bbox_async(loc)
        await loc.click(timeout=30_000, force=act.force)
        _attach_target_overlay(rec, "click", act.selector[:120], box)
        rec["selector"] = act.selector
    elif isinstance(act, HoverAction):
        if act.selector:
            loc = page.locator(act.selector).first
        elif act.role and act.name:
            loc = page.get_by_role(act.role, name=act.name).first
        elif act.text:
            loc = page.get_by_text(act.text).first
        else:
            raise ValueError("hover requires selector, role+name, or text")
        await loc.wait_for(state="visible", timeout=15_000)
        box = await _try_bbox_async(loc)
        await loc.hover(timeout=15_000)
        hl = (
            act.selector[:80]
            if act.selector
            else (f"{act.role}: {act.name}" if act.role and act.name else (act.text or "hover"))
        )
        _attach_target_overlay(rec, "hover", hl, box)
        rec["hovered"] = True
    elif isinstance(act, EvaluateConditionAction):
        if act.extract_selector:
            el_text = await page.locator(act.extract_selector).first.inner_text(timeout=10_000)
        else:
            el_text = (await page.locator("body").inner_text(timeout=10_000))[:3000]
        rec["condition"] = act.condition
        rec["extracted_text"] = el_text[:2000]
        rec["needs_llm_eval"] = True
    elif isinstance(act, ExtractTextAction):
        el = page.locator(act.selector).first
        await el.wait_for(state="visible", timeout=30_000)
        extracted = await el.inner_text(timeout=30_000)
        extracted = extracted[:act.max_length]
        rec["selector"] = act.selector
        rec["store_as"] = act.store_as
        rec["extracted_text"] = extracted
        rec["text_length"] = len(extracted)
    elif isinstance(act, TypeTextAction):
        if act.selector:
            loc = page.locator(act.selector).first
            await loc.wait_for(state="visible", timeout=30_000)
            await loc.click(timeout=30_000)
            # Wait for editor initialization (rich text editors need time after focus)
            await page.wait_for_timeout(500)
        if act.delay_ms > 0:
            await page.keyboard.type(act.text, delay=act.delay_ms)
            rec["method"] = "type"
        else:
            # Detect contenteditable — insert_text (CDP Input.insertText) doesn't
            # fire proper beforeinput events that rich text editors (LinkedIn,
            # ChatGPT, Notion, etc.) require.  Use execCommand('insertText') which
            # fires browser-native events, then fall back to keyboard.type.
            is_ce = await page.evaluate(
                "() => document.activeElement?.isContentEditable === true"
            )
            if is_ce:
                ok = await page.evaluate(
                    "(text) => document.execCommand('insertText', false, text)",
                    act.text,
                )
                if ok:
                    rec["method"] = "execCommand_insertText"
                else:
                    # execCommand failed — fall back to keyboard.type (slow but universal)
                    await page.keyboard.type(act.text, delay=0)
                    rec["method"] = "type_fallback"
            else:
                await page.keyboard.insert_text(act.text)
                rec["method"] = "insert_text"
        rec["typed_length"] = len(act.text)
    elif isinstance(act, WaitForSelectorAction):
        await page.wait_for_selector(act.selector, state=act.state, timeout=act.timeout_ms)
        rec["selector"] = act.selector
        rec["state"] = act.state
    elif isinstance(act, WaitForTextStableAction):
        sel = act.selector
        timeout_sec = act.timeout_ms / 1000
        stable_sec = act.stable_ms / 1000
        start = _time.time()
        last_text = ""
        last_change = start
        while True:
            try:
                current = await page.locator(sel).first.inner_text(timeout=5000)
            except Exception:
                current = ""
            if current != last_text:
                last_text = current
                last_change = _time.time()
            if (_time.time() - last_change) >= stable_sec and last_text:
                break
            if (_time.time() - start) > timeout_sec:
                break
            await page.wait_for_timeout(500)
        rec["selector"] = sel
        rec["stable"] = (_time.time() - last_change) >= stable_sec
        rec["text_length"] = len(last_text)

    if screenshot_dir is not None and act.type not in ("wait_ms",):
        ss_path = await _async_take_screenshot(page, screenshot_dir, step_num, action_idx, act.type)
        if ss_path:
            rec["screenshot"] = ss_path

    if condition_met is not None:
        rec["_condition_met"] = condition_met

    return rec


async def async_execute_dsl_actions(
    page,
    bundle: DSLBundle,
    screenshot_dir: Optional[Path] = None,
    step_num: int = 0,
) -> Dict[str, Any]:
    """Run validated DSL actions (async). Supports parallel fill actions.

    Individual action failures are caught — stops at first error and returns
    partial results so callers can inspect what succeeded (e.g. dropdown opened
    but option click failed).
    """
    condition_met: Optional[bool] = None
    url_before = page.url
    executed: List[Dict[str, Any]] = []
    failed_action_idx: Optional[int] = None
    failed_action_error: Optional[str] = None

    if bundle.parallel:
        # Split into parallelizable groups and sequential actions
        parallel_batch: List[tuple[int, DSLAction]] = []
        sequential: List[tuple[int, DSLAction]] = []

        for idx, act in enumerate(bundle.actions):
            if act.type in _PARALLELIZABLE_TYPES:
                parallel_batch.append((idx, act))
            else:
                sequential.append((idx, act))

        # Run parallel fills concurrently
        if parallel_batch:
            coros = [
                _async_execute_single_action(page, act, screenshot_dir, step_num, idx)
                for idx, act in parallel_batch
            ]
            parallel_results = await asyncio.gather(*coros, return_exceptions=True)
            for (idx, _), result in zip(parallel_batch, parallel_results):
                if isinstance(result, Exception):
                    executed.append({"type": "error", "error": str(result), "action_idx": idx})
                else:
                    if "_condition_met" in result:
                        condition_met = result.pop("_condition_met")
                    executed.append(result)

        # Run sequential actions in order
        for idx, act in sequential:
            try:
                rec = await _async_execute_single_action(page, act, screenshot_dir, step_num, idx)
                if "_condition_met" in rec:
                    condition_met = rec.pop("_condition_met")
                executed.append(rec)
            except Exception as exc:
                logger.warning(
                    "Step %d action %d (%s) failed: %s",
                    step_num, idx, act.type, exc,
                )
                executed.append({
                    "type": act.type,
                    "error": f"{type(exc).__name__}: {exc}",
                    "action_idx": idx,
                })
                failed_action_idx = idx
                failed_action_error = f"{type(exc).__name__}: {exc}"
                break
    else:
        # Standard sequential execution
        for action_idx, act in enumerate(bundle.actions):
            try:
                rec = await _async_execute_single_action(page, act, screenshot_dir, step_num, action_idx)
                if "_condition_met" in rec:
                    condition_met = rec.pop("_condition_met")
                executed.append(rec)
            except Exception as exc:
                logger.warning(
                    "Step %d action %d (%s) failed: %s",
                    step_num, action_idx, act.type, exc,
                )
                executed.append({
                    "type": act.type,
                    "error": f"{type(exc).__name__}: {exc}",
                    "action_idx": action_idx,
                })
                failed_action_idx = action_idx
                failed_action_error = f"{type(exc).__name__}: {exc}"
                break

    result: Dict[str, Any] = {
        "executed": executed,
        "url_before": url_before,
        "url_after": page.url,
        "condition_met": condition_met,
    }
    if failed_action_idx is not None:
        result["partial_failure"] = True
        result["failed_action_idx"] = failed_action_idx
        result["failed_action_error"] = failed_action_error
        result["actions_completed"] = failed_action_idx
        result["actions_total"] = len(bundle.actions)
    return result
