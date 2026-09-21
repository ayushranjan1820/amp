"""Database helpers — MongoDB persistence for workflows and executions.

Migrated from PostgreSQL in 2026-05. Public function signatures preserved.

Collections:
- workflows                (id PK)
- workflow_executions      (id PK, workflow_id ref)
- workflow_execution_steps (auto id, execution_id ref)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING

from mongo_db import get_db, next_seq, utcnow

logger = logging.getLogger(__name__)


WORKFLOWS = "workflows"
EXECUTIONS = "workflow_executions"
STEPS = "workflow_execution_steps"


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------


def init_workflow_db() -> None:
    """Create indexes on the workflow collections. Idempotent."""
    try:
        db = get_db()
        db[WORKFLOWS].create_index([("updated_at", DESCENDING)], name="idx_workflow_updated")
        db[WORKFLOWS].create_index("user_id", name="idx_workflow_user")

        db[EXECUTIONS].create_index("workflow_id", name="idx_execution_workflow")
        db[EXECUTIONS].create_index([("started_at", DESCENDING)], name="idx_execution_started")
        db[EXECUTIONS].create_index("user_id", name="idx_execution_user")

        db[STEPS].create_index(
            [("execution_id", ASCENDING), ("step_number", ASCENDING), ("created_at", ASCENDING)],
            name="idx_step_order",
        )
        logger.info("Workflow collections initialized")
    except Exception as e:
        logger.warning("Workflow DB init failed: %s", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip(doc: Optional[dict]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    out = dict(doc)
    out.pop("_id", None)
    return out


# ---------------------------------------------------------------------------
# Workflow CRUD
# ---------------------------------------------------------------------------


def save_workflow(
    workflow_id: Optional[str],
    name: str,
    instruction: str,
    definition: Dict,
    mermaid_code: str,
    user_id: Optional[int] = None,
    agent_user_configs: Optional[Dict[str, Any]] = None,
    memory_enabled: Optional[bool] = None,
) -> str:
    """Insert or update a workflow definition."""
    if not workflow_id:
        workflow_id = str(uuid.uuid4())

    db = get_db()
    existing = db[WORKFLOWS].find_one({"_id": workflow_id})

    # Determine agent_user_configs value (preserve existing if not passed)
    if agent_user_configs is not None:
        configs_value: Optional[Dict[str, Any]] = dict(agent_user_configs)
    elif existing:
        configs_value = existing.get("agent_user_configs")
    else:
        configs_value = None

    # memory_enabled: None = preserve existing (default False for new docs)
    if memory_enabled is not None:
        memory_value = bool(memory_enabled)
    elif existing:
        memory_value = bool(existing.get("memory_enabled", False))
    else:
        memory_value = False

    now = utcnow()

    if existing:
        db[WORKFLOWS].update_one(
            {"_id": workflow_id},
            {"$set": {
                "name": name,
                "instruction": instruction,
                "definition": definition,
                "mermaid_code": mermaid_code,
                "agent_user_configs": configs_value,
                "memory_enabled": memory_value,
                "updated_at": now,
            }},
        )
    else:
        db[WORKFLOWS].insert_one({
            "_id": workflow_id,
            "id": workflow_id,
            "name": name,
            "instruction": instruction,
            "definition": definition,
            "mermaid_code": mermaid_code,
            "user_id": user_id,
            "agent_user_configs": configs_value,
            "memory_enabled": memory_value,
            "created_at": now,
            "updated_at": now,
        })
    return workflow_id


def list_workflows(user_id: Optional[int] = None, is_admin: bool = False) -> List[Dict]:
    """Return all workflows (admin) or only those owned by *user_id*."""
    db = get_db()
    q: Dict[str, Any] = {}
    if not (is_admin or user_id is None):
        q["user_id"] = user_id
    cursor = db[WORKFLOWS].find(
        q,
        {"id": 1, "name": 1, "instruction": 1, "definition": 1, "user_id": 1,
         "memory_enabled": 1, "created_at": 1, "updated_at": 1},
    ).sort("updated_at", DESCENDING)
    return [_strip(r) for r in cursor]


def get_workflow(workflow_id: str) -> Optional[Dict]:
    """Fetch a single workflow by ID."""
    db = get_db()
    return _strip(db[WORKFLOWS].find_one({"_id": workflow_id}))


def delete_workflow(workflow_id: str) -> bool:
    """Delete a workflow by ID. Returns True if a row was removed."""
    db = get_db()
    res = db[WORKFLOWS].delete_one({"_id": workflow_id})
    if res.deleted_count:
        # Cascade — match prior PG ON DELETE CASCADE
        execution_ids = [
            e["_id"]
            for e in db[EXECUTIONS].find({"workflow_id": workflow_id}, {"_id": 1})
        ]
        if execution_ids:
            db[STEPS].delete_many({"execution_id": {"$in": execution_ids}})
            db[EXECUTIONS].delete_many({"_id": {"$in": execution_ids}})
    return res.deleted_count > 0


# ---------------------------------------------------------------------------
# Execution CRUD
# ---------------------------------------------------------------------------


def create_execution(execution_id: str, workflow_id: str, user_id: Optional[int] = None) -> str:
    """Create a new execution record tied to *workflow_id*."""
    db = get_db()
    try:
        db[EXECUTIONS].insert_one({
            "_id": execution_id,
            "id": execution_id,
            "workflow_id": workflow_id,
            "status": "running",
            "user_id": user_id,
            "started_at": utcnow(),
            "completed_at": None,
        })
    except Exception as e:
        logger.error("Failed to create execution record: %s", e)
    return execution_id


def save_execution_step(
    execution_id: str,
    step_number: int,
    agent_id: str,
    agent_name: str,
    status: str,
    query: str,
    response: str,
    bpmn_xml: Optional[str] = None,
    download_url: Optional[str] = None,
):
    """Persist the result of a single workflow step."""
    db = get_db()
    try:
        db[STEPS].insert_one({
            "_id": next_seq("workflow_execution_steps"),
            "execution_id": execution_id,
            "step_number": int(step_number),
            "agent_id": agent_id,
            "agent_name": agent_name,
            "status": status,
            "query": query,
            "response": response,
            "bpmn_xml": bpmn_xml,
            "download_url": download_url,
            "created_at": utcnow(),
        })
    except Exception as e:
        logger.error("Failed to save step %d: %s", step_number, e)


def complete_execution(execution_id: str, success: bool):
    """Mark an execution as completed or failed."""
    db = get_db()
    try:
        db[EXECUTIONS].update_one(
            {"_id": execution_id},
            {"$set": {
                "status": "completed" if success else "failed",
                "completed_at": utcnow(),
            }},
        )
    except Exception as e:
        logger.error("Failed to complete execution: %s", e)


def list_workflow_run_user_ids(workflow_id: str) -> List[int]:
    """Return distinct ``user_id`` values that have executed *workflow_id*.

    Anonymous executions (``user_id is None``) are dropped — anonymous runs do
    not produce memories under the per-user scoping rule.
    """
    db = get_db()
    try:
        ids = db[EXECUTIONS].distinct("user_id", {"workflow_id": workflow_id})
    except Exception as e:
        logger.warning("Failed to list workflow run users: %s", e)
        return []
    return [int(u) for u in ids if u is not None]


def list_executions(workflow_id: str) -> List[Dict]:
    """Return all executions for a workflow, newest first."""
    db = get_db()
    cursor = db[EXECUTIONS].find(
        {"workflow_id": workflow_id},
        {"id": 1, "workflow_id": 1, "status": 1, "started_at": 1, "completed_at": 1},
    ).sort("started_at", DESCENDING)
    return [_strip(r) for r in cursor]


def get_execution_detail(execution_id: str) -> Optional[Dict]:
    """Fetch an execution with all its step results (full payloads)."""
    db = get_db()
    execution = db[EXECUTIONS].find_one(
        {"_id": execution_id},
        {"id": 1, "workflow_id": 1, "status": 1, "started_at": 1,
         "completed_at": 1, "user_id": 1},
    )
    if not execution:
        return None
    execution = _strip(execution)
    steps_cursor = db[STEPS].find(
        {"execution_id": execution_id},
        {"step_number": 1, "agent_id": 1, "agent_name": 1, "status": 1,
         "query": 1, "response": 1, "bpmn_xml": 1, "download_url": 1, "created_at": 1},
    ).sort([("step_number", ASCENDING), ("created_at", ASCENDING)])
    execution["steps"] = [_strip(r) for r in steps_cursor]
    return execution


def get_execution_summary(execution_id: str) -> Optional[Dict]:
    """Fetch an execution with per-step metadata only (no query/response bodies)."""
    db = get_db()
    execution = db[EXECUTIONS].find_one(
        {"_id": execution_id},
        {"id": 1, "workflow_id": 1, "status": 1, "started_at": 1,
         "completed_at": 1, "user_id": 1},
    )
    if not execution:
        return None
    execution = _strip(execution)

    pipeline = [
        {"$match": {"execution_id": execution_id}},
        {"$sort": {"step_number": 1, "created_at": 1}},
        {"$project": {
            "_id": 0,
            "step_number": 1,
            "agent_id": 1,
            "agent_name": 1,
            "status": 1,
            "query_length": {"$ifNull": [{"$strLenCP": {"$ifNull": ["$query", ""]}}, 0]},
            "response_length": {"$ifNull": [{"$strLenCP": {"$ifNull": ["$response", ""]}}, 0]},
            "has_bpmn": {"$and": [
                {"$ne": ["$bpmn_xml", None]},
                {"$gt": [{"$strLenCP": {"$ifNull": ["$bpmn_xml", ""]}}, 0]},
            ]},
            "download_url": 1,
            "created_at": 1,
        }},
    ]
    execution["steps"] = list(db[STEPS].aggregate(pipeline))
    return execution


def get_execution_step(execution_id: str, step_number: int) -> Optional[Dict]:
    """Fetch the full body (query/response/bpmn) for a single execution step."""
    db = get_db()
    cursor = db[STEPS].find(
        {"execution_id": execution_id, "step_number": int(step_number)},
        {"step_number": 1, "agent_id": 1, "agent_name": 1, "status": 1,
         "query": 1, "response": 1, "bpmn_xml": 1, "download_url": 1, "created_at": 1},
    ).sort("created_at", ASCENDING).limit(1)
    rows = list(cursor)
    return _strip(rows[0]) if rows else None


def get_execution_owner_user_id(execution_id: str) -> Optional[int]:
    """Return ``workflow_executions.user_id`` for this run, or None if unknown."""
    db = get_db()
    row = db[EXECUTIONS].find_one({"_id": execution_id}, {"user_id": 1, "_id": 0})
    if not row:
        return None
    return row.get("user_id")


def get_execution_workflow_id(execution_id: str) -> Optional[str]:
    """Return the workflow id for this execution, or None if the run does not exist."""
    db = get_db()
    row = db[EXECUTIONS].find_one({"_id": execution_id}, {"workflow_id": 1})
    if not row:
        return None
    return row.get("workflow_id")


def delete_execution(execution_id: str) -> bool:
    """Delete an execution and its steps. Returns True if an execution row was removed."""
    db = get_db()
    db[STEPS].delete_many({"execution_id": execution_id})
    res = db[EXECUTIONS].delete_one({"_id": execution_id})
    return res.deleted_count > 0
