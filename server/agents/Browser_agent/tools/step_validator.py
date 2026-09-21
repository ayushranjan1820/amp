"""Validate planner step JSON before execution (schema + safety)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


ALLOWED_ACTIONS = frozenset({
    "navigate", "search", "click", "type", "scroll", "select", "wait",
    "verify", "extract", "add_to_cart", "custom",
})

# Re-planning models often emit synonyms; map into ALLOWED_ACTIONS.
_ACTION_ALIASES = {
    "goto": "navigate",
    "go_to": "navigate",
    "open": "click",
    "tap": "click",
    "press": "click",
    "submit": "click",
    "enter": "type",
    "input": "type",
    "fill": "type",
    "choose": "select",
    "pick": "select",
    "dropdown": "select",
    "select_option": "select",
    "option": "select",
    "check": "verify",
    "assert": "verify",
    "cart": "add_to_cart",
    "add": "add_to_cart",
    "pause": "wait",
    "sleep": "wait",
    "load": "wait",
    "remember": "extract",
    "copy": "extract",
    "read": "extract",
    "save": "extract",
    "store": "extract",
    "get_text": "extract",
    "capture": "extract",
}


def coerce_planner_step_dict(step: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize LLM quirks (e.g. ``step`` instead of ``action``, missing ``description``)."""
    out: Dict[str, Any] = dict(step)

    if "action" not in out or not str(out.get("action", "")).strip():
        if "step" in out and str(out["step"]).strip():
            out["action"] = str(out["step"]).strip().lower()
        elif "type" in out and str(out["type"]).strip():
            out["action"] = str(out["type"]).strip().lower()

    act = str(out.get("action", "")).strip().lower()
    if act in _ACTION_ALIASES:
        out["action"] = _ACTION_ALIASES[act]
    elif act and act not in ALLOWED_ACTIONS:
        out["action"] = "custom"

    desc = out.get("description")
    if desc is None or not str(desc).strip():
        for key in (
            "description", "detail", "details", "instruction", "instructions",
            "summary", "goal", "task", "name", "label", "text", "notes",
        ):
            val = out.get(key)
            if val is not None and isinstance(val, str) and val.strip():
                out["description"] = val.strip()
                break
        else:
            parts: List[str] = []
            if out.get("action"):
                parts.append(str(out["action"]))
            if out.get("target_url"):
                parts.append(f"url {out['target_url']}")
            if out.get("search_query"):
                parts.append(f"search {out['search_query']}")
            if out.get("element_hint"):
                parts.append(str(out["element_hint"]))
            if out.get("selector"):
                out.setdefault("element_hint", str(out["selector"]))
                parts.append(f"selector {out['selector']}")
            if out.get("value"):
                parts.append(f"value {out['value']}")
            out["description"] = "; ".join(parts) if parts else "Automation step"

    if "element_hint" not in out or not str(out.get("element_hint", "")).strip():
        sel = out.get("selector")
        if sel and isinstance(sel, str) and sel.strip():
            out["element_hint"] = sel.strip()

    return out


class PlannerStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    step_number: int = Field(..., ge=1, le=500)
    action: str = Field(..., min_length=1, max_length=64)
    target_url: Optional[str] = None
    description: str = Field(..., min_length=1, max_length=2000)
    search_query: Optional[str] = Field(None, max_length=2000)
    element_hint: Optional[str] = Field(None, max_length=500)
    value: Optional[str] = Field(None, max_length=10_000)
    condition: Optional[str] = Field(None, max_length=500)
    expected_outcome: Optional[str] = Field(
        None,
        max_length=1000,
        description="Post-condition for grounded verification after the step.",
    )

    @field_validator("action")
    @classmethod
    def action_allowed(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ALLOWED_ACTIONS:
            raise ValueError(f"action must be one of {sorted(ALLOWED_ACTIONS)}")
        return v

    @field_validator("target_url")
    @classmethod
    def url_safe(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        v = v.strip()
        if not re.match(r"^https?://", v, re.I):
            raise ValueError("target_url must be http(s)")
        if len(v) > 2048:
            raise ValueError("target_url too long")
        return v


def validate_planner_steps(raw_steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return list of dicts validated through PlannerStep; raises ValueError on bad data."""
    out: List[Dict[str, Any]] = []
    for i, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            raise ValueError(f"steps[{i}] must be an object")
        model = PlannerStep.model_validate(coerce_planner_step_dict(step))
        out.append(model.model_dump())
    return out
