"""In-memory workflow persistence for the prototype platform."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_workflows: Dict[str, Dict[str, Any]] = {}
_executions: Dict[str, Dict[str, Any]] = {}


def save_workflow(
    workflow_id: Optional[str],
    name: str,
    instruction: str,
    definition: Dict[str, Any],
    mermaid_code: str,
    user_id: int,
    agent_user_configs: Optional[Dict] = None,
    memory_enabled: Optional[bool] = None,
) -> str:
    wid = workflow_id or str(uuid.uuid4())
    existing = _workflows.get(wid, {})
    _workflows[wid] = {
        "id": wid,
        "name": name,
        "instruction": instruction,
        "definition": definition,
        "mermaid_code": mermaid_code,
        "user_id": user_id,
        "agent_user_configs": agent_user_configs if agent_user_configs is not None else existing.get("agent_user_configs"),
        "memory_enabled": memory_enabled if memory_enabled is not None else existing.get("memory_enabled", False),
        "created_at": existing.get("created_at", _now_iso()),
        "updated_at": _now_iso(),
    }
    return wid


def list_workflows(user_id: int, is_admin: bool) -> List[Dict[str, Any]]:
    rows = list(_workflows.values())
    if not is_admin:
        rows = [w for w in rows if w.get("user_id") == user_id]
    return sorted(rows, key=lambda w: w.get("updated_at", ""), reverse=True)


def get_workflow(workflow_id: str) -> Optional[Dict[str, Any]]:
    row = _workflows.get(workflow_id)
    return copy.deepcopy(row) if row else None


def delete_workflow(workflow_id: str) -> bool:
    return _workflows.pop(workflow_id, None) is not None


def record_execution(workflow_id: Optional[str], execution_id: str, user_id: Optional[int], steps: List[Dict]) -> None:
    _executions[execution_id] = {
        "id": execution_id,
        "workflow_id": workflow_id,
        "user_id": user_id,
        "status": "completed",
        "steps": steps,
        "created_at": _now_iso(),
    }


def list_executions(workflow_id: str) -> List[Dict[str, Any]]:
    return [e for e in _executions.values() if e.get("workflow_id") == workflow_id]


def get_execution(execution_id: str, full: bool = False) -> Optional[Dict[str, Any]]:
    row = _executions.get(execution_id)
    if not row:
        return None
    out = copy.deepcopy(row)
    if not full:
        out["steps"] = [
            {"step_number": i + 1, "agent_id": s.get("agent_id"), "status": "completed", "response_size": len(str(s.get("output", "")))}
            for i, s in enumerate(out.get("steps", []))
        ]
    return out


def get_execution_step(execution_id: str, step_number: int) -> Optional[Dict[str, Any]]:
    row = _executions.get(execution_id)
    if not row:
        return None
    steps = row.get("steps", [])
    if step_number < 1 or step_number > len(steps):
        return None
    return copy.deepcopy(steps[step_number - 1])


def delete_execution(execution_id: str) -> bool:
    return _executions.pop(execution_id, None) is not None
