"""Structured page snapshot extractor for LLM consumption.

Combines accessibility tree, visible text, interactive elements,
form state, and page metadata into a token-efficient representation.
Replaces the ad-hoc `build_dom_context` with a richer, reusable snapshot.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── sync capture ────────────────────────────────────────────────────

def capture_page_snapshot(page, max_elements: int = 80) -> Dict[str, Any]:
    """Capture a structured snapshot of the current page state (sync API).

    Returns a dict with keys: url, title, accessibility_tree, visible_text,
    interactive_counts, key_elements, form_state.
    """
    snapshot: Dict[str, Any] = {
        "url": page.url,
        "title": "",
        "accessibility_tree": None,
        "visible_text": "",
        "interactive_counts": {},
        "key_elements": [],
        "form_state": [],
    }

    try:
        snapshot["title"] = page.title()
    except Exception:
        pass

    try:
        snapshot["accessibility_tree"] = page.accessibility.snapshot()
    except Exception as exc:
        logger.debug("Accessibility snapshot failed: %s", exc)

    try:
        snapshot["visible_text"] = page.inner_text("body")[:8000]
    except Exception:
        snapshot["visible_text"] = "(unable to read page text)"

    try:
        snapshot["interactive_counts"] = page.evaluate(
            """() => ({
                buttons: document.querySelectorAll('button,[role="button"],input[type="submit"]').length,
                links: document.querySelectorAll('a[href]').length,
                inputs: document.querySelectorAll('input:not([type="hidden"])').length,
                selects: document.querySelectorAll('select').length,
                textareas: document.querySelectorAll('textarea').length,
                checkboxes: document.querySelectorAll('input[type="checkbox"]').length,
                radios: document.querySelectorAll('input[type="radio"]').length,
            })"""
        )
    except Exception:
        pass

    try:
        snapshot["key_elements"] = page.evaluate(
            """(maxEls) => {
                const els = [];
                const selectors = [
                    'select', 'input:not([type="hidden"])', 'button', '[role="button"]',
                    'input[type="submit"]', '[role="searchbox"]', '[role="combobox"]',
                    'textarea', '[role="tab"]', '[role="menuitem"]',
                    '[role="listbox"]', '[role="option"]', '[role="menu"]',
                    '[role="switch"]', '[role="slider"]',
                    '[data-state]', '[data-value]',
                    '[aria-haspopup]', '[aria-expanded]',
                    '[contenteditable="true"]', '[contenteditable=""]',
                    '[role="textbox"]'
                ];
                const seen = new Set();
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) continue;
                        const id = el.id ? '#' + el.id : '';
                        const cls = el.className && typeof el.className === 'string'
                            ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.')
                            : '';
                        const info = {
                            tag: el.tagName.toLowerCase(),
                            selector: id || cls || el.tagName.toLowerCase(),
                            role: el.getAttribute('role') || '',
                            name: (el.getAttribute('aria-label') || el.placeholder || el.textContent || '').slice(0, 80).trim(),
                            type: el.type || '',
                            visible: rect.width > 0 && rect.height > 0,
                            bbox: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }
                        };
                        const expanded = el.getAttribute('aria-expanded');
                        if (expanded !== null) info.aria_expanded = expanded;
                        const hasPopup = el.getAttribute('aria-haspopup');
                        if (hasPopup) info.aria_haspopup = hasPopup;
                        const dataState = el.getAttribute('data-state');
                        if (dataState) info.data_state = dataState;
                        const dataValue = el.getAttribute('data-value');
                        if (dataValue) info.data_value = dataValue.slice(0, 80);
                        const ce = el.getAttribute('contenteditable');
                        if (ce !== null) info.contenteditable = ce || 'true';
                        els.push(info);
                        if (els.length >= maxEls) break;
                    }
                    if (els.length >= maxEls) break;
                }
                return els;
            }""",
            max_elements,
        )
    except Exception:
        pass

    try:
        snapshot["form_state"] = page.evaluate(
            """() => {
                const state = [];
                // Text inputs and textareas with values
                document.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), textarea').forEach(el => {
                    if (el.value) {
                        const id = el.id ? '#' + el.id : '';
                        const name = el.name || el.getAttribute('aria-label') || el.placeholder || '';
                        state.push({
                            type: 'input',
                            selector: id || el.tagName.toLowerCase(),
                            name: name.slice(0, 80),
                            value: el.value.slice(0, 200),
                        });
                    }
                });
                // Select elements — current selection
                document.querySelectorAll('select').forEach(el => {
                    const selected = el.options[el.selectedIndex];
                    if (selected) {
                        const id = el.id ? '#' + el.id : '';
                        state.push({
                            type: 'select',
                            selector: id || el.tagName.toLowerCase(),
                            name: (el.getAttribute('aria-label') || el.name || '').slice(0, 80),
                            value: selected.value,
                            label: selected.text.slice(0, 100),
                        });
                    }
                });
                // Checked checkboxes and radios
                document.querySelectorAll('input[type="checkbox"]:checked, input[type="radio"]:checked').forEach(el => {
                    const id = el.id ? '#' + el.id : '';
                    state.push({
                        type: el.type,
                        selector: id || el.tagName.toLowerCase(),
                        name: (el.getAttribute('aria-label') || el.name || '').slice(0, 80),
                        checked: true,
                    });
                });
                return state.slice(0, 30);
            }"""
        )
    except Exception:
        pass

    return snapshot


# ── async capture ───────────────────────────────────────────────────

async def async_capture_page_snapshot(page, max_elements: int = 80) -> Dict[str, Any]:
    """Capture a structured snapshot (async Playwright API)."""
    snapshot: Dict[str, Any] = {
        "url": page.url,
        "title": "",
        "accessibility_tree": None,
        "visible_text": "",
        "interactive_counts": {},
        "key_elements": [],
        "form_state": [],
    }

    try:
        snapshot["title"] = await page.title()
    except Exception:
        pass

    try:
        snapshot["accessibility_tree"] = await page.accessibility.snapshot()
    except Exception as exc:
        logger.debug("Accessibility snapshot failed: %s", exc)

    try:
        snapshot["visible_text"] = (await page.inner_text("body"))[:8000]
    except Exception:
        snapshot["visible_text"] = "(unable to read page text)"

    try:
        snapshot["interactive_counts"] = await page.evaluate(
            """() => ({
                buttons: document.querySelectorAll('button,[role="button"],input[type="submit"]').length,
                links: document.querySelectorAll('a[href]').length,
                inputs: document.querySelectorAll('input:not([type="hidden"])').length,
                selects: document.querySelectorAll('select').length,
                textareas: document.querySelectorAll('textarea').length,
                checkboxes: document.querySelectorAll('input[type="checkbox"]').length,
                radios: document.querySelectorAll('input[type="radio"]').length,
            })"""
        )
    except Exception:
        pass

    try:
        snapshot["key_elements"] = await page.evaluate(
            """(maxEls) => {
                const els = [];
                const selectors = [
                    'select', 'input:not([type="hidden"])', 'button', '[role="button"]',
                    'input[type="submit"]', '[role="searchbox"]', '[role="combobox"]',
                    'textarea', '[role="tab"]', '[role="menuitem"]',
                    '[role="listbox"]', '[role="option"]', '[role="menu"]',
                    '[role="switch"]', '[role="slider"]',
                    '[data-state]', '[data-value]',
                    '[aria-haspopup]', '[aria-expanded]',
                    '[contenteditable="true"]', '[contenteditable=""]',
                    '[role="textbox"]'
                ];
                const seen = new Set();
                for (const sel of selectors) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (seen.has(el)) continue;
                        seen.add(el);
                        const rect = el.getBoundingClientRect();
                        if (rect.width === 0 && rect.height === 0) continue;
                        const id = el.id ? '#' + el.id : '';
                        const cls = el.className && typeof el.className === 'string'
                            ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.')
                            : '';
                        const info = {
                            tag: el.tagName.toLowerCase(),
                            selector: id || cls || el.tagName.toLowerCase(),
                            role: el.getAttribute('role') || '',
                            name: (el.getAttribute('aria-label') || el.placeholder || el.textContent || '').slice(0, 80).trim(),
                            type: el.type || '',
                            visible: rect.width > 0 && rect.height > 0,
                            bbox: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) }
                        };
                        const expanded = el.getAttribute('aria-expanded');
                        if (expanded !== null) info.aria_expanded = expanded;
                        const hasPopup = el.getAttribute('aria-haspopup');
                        if (hasPopup) info.aria_haspopup = hasPopup;
                        const dataState = el.getAttribute('data-state');
                        if (dataState) info.data_state = dataState;
                        const dataValue = el.getAttribute('data-value');
                        if (dataValue) info.data_value = dataValue.slice(0, 80);
                        const ce = el.getAttribute('contenteditable');
                        if (ce !== null) info.contenteditable = ce || 'true';
                        els.push(info);
                        if (els.length >= maxEls) break;
                    }
                    if (els.length >= maxEls) break;
                }
                return els;
            }""",
            max_elements,
        )
    except Exception:
        pass

    try:
        snapshot["form_state"] = await page.evaluate(
            """() => {
                const state = [];
                document.querySelectorAll('input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]), textarea').forEach(el => {
                    if (el.value) {
                        const id = el.id ? '#' + el.id : '';
                        const name = el.name || el.getAttribute('aria-label') || el.placeholder || '';
                        state.push({ type: 'input', selector: id || el.tagName.toLowerCase(), name: name.slice(0, 80), value: el.value.slice(0, 200) });
                    }
                });
                document.querySelectorAll('select').forEach(el => {
                    const selected = el.options[el.selectedIndex];
                    if (selected) {
                        const id = el.id ? '#' + el.id : '';
                        state.push({ type: 'select', selector: id || el.tagName.toLowerCase(), name: (el.getAttribute('aria-label') || el.name || '').slice(0, 80), value: selected.value, label: selected.text.slice(0, 100) });
                    }
                });
                document.querySelectorAll('input[type="checkbox"]:checked, input[type="radio"]:checked').forEach(el => {
                    const id = el.id ? '#' + el.id : '';
                    state.push({ type: el.type, selector: id || el.tagName.toLowerCase(), name: (el.getAttribute('aria-label') || el.name || '').slice(0, 80), checked: true });
                });
                return state.slice(0, 30);
            }"""
        )
    except Exception:
        pass

    return snapshot


# ── formatting ──────────────────────────────────────────────────────

def format_snapshot_for_llm(snapshot: Dict[str, Any], max_chars: int = 28_000) -> str:
    """Format a page snapshot into a string suitable for LLM prompts."""
    parts: List[str] = []

    parts.append(f"## Page: {snapshot.get('title', '(untitled)')}")
    parts.append(f"URL: {snapshot.get('url', '(unknown)')}\n")

    tree = snapshot.get("accessibility_tree")
    if tree:
        dumped = json.dumps(tree, default=str)
        parts.append("## Accessibility tree (truncated)\n")
        parts.append(dumped[:12_000])
    else:
        parts.append("## Accessibility tree\n(unavailable)")

    parts.append("\n## Visible text (truncated)\n")
    parts.append(snapshot.get("visible_text", "")[:5000])

    counts = snapshot.get("interactive_counts", {})
    if counts:
        parts.append("\n## Interactive counts\n")
        parts.append(json.dumps(counts))

    elements = snapshot.get("key_elements", [])
    if elements:
        parts.append("\n## Key interactive elements (tag, selector, role, name, bbox)\n")
        parts.append(json.dumps(elements, default=str)[:4000])

    form_state = snapshot.get("form_state", [])
    if form_state:
        parts.append("\n## Current form state (filled fields, selections)\n")
        parts.append(json.dumps(form_state, default=str)[:2000])

    result = "\n".join(parts)
    return result[:max_chars]


def summarize_observation(
    snapshot_before: Optional[Dict[str, Any]],
    snapshot_after: Dict[str, Any],
    step_result: Dict[str, Any],
) -> str:
    """Concise observation summary for the closed-loop controller.

    Compares before/after state so the replanning LLM can decide whether
    the remaining steps are still valid.
    """
    parts: List[str] = []

    url_before = (snapshot_before or {}).get("url", "")
    url_after = snapshot_after.get("url", "")
    title_after = snapshot_after.get("title", "")

    parts.append(f"URL: {url_after}")
    if url_before and url_before != url_after:
        parts.append(f"  (changed from: {url_before})")
    parts.append(f"Page title: {title_after}")

    status = step_result.get("status", "unknown")
    parts.append(f"Step status: {status}")
    if step_result.get("error"):
        parts.append(f"Error: {step_result['error']}")
    if step_result.get("condition_met") is not None:
        parts.append(f"Condition met: {step_result['condition_met']}")

    text_after = snapshot_after.get("visible_text", "")[:500]
    parts.append(f"\nVisible text (snippet): {text_after}")

    form_after = snapshot_after.get("form_state", [])
    if form_after:
        parts.append(f"\nForm state: {json.dumps(form_after[:10], default=str)[:500]}")

    return "\n".join(parts)
