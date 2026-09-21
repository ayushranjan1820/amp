"""Prototype workflow API routes."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import admin_auth
from prototype.workflow import prototype_workflow_execute, prototype_workflow_execute_stream, prototype_workflow_generate
from prototype import workflow_store

router = APIRouter(prefix="/api/admin/workflows", tags=["workflows"])


class WorkflowGenerateRequest(BaseModel):
    instruction: str


class WorkflowSaveRequest(BaseModel):
    id: Optional[str] = None
    name: str
    instruction: str
    definition: Dict[str, Any]
    mermaid_code: str
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None
    memory_enabled: Optional[bool] = None


class WorkflowExecuteRequest(BaseModel):
    definition: Dict[str, Any]
    workflow_id: Optional[str] = None
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None
    agent_extra_kwargs: Optional[Dict[str, Dict[str, Any]]] = None
    step_mode: str = "auto"


class WorkflowStepRerunRequest(BaseModel):
    step: Dict[str, Any]
    query: str
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None
    agent_extra_kwargs: Optional[Dict[str, Dict[str, Any]]] = None


def _optional_user(authorization: Optional[str]):
    token = (authorization or "").replace("Bearer ", "").strip()
    return admin_auth.verify_token(token) if token else None


def _require_user(authorization: Optional[str]):
    user = _optional_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def _is_admin(user: Dict) -> bool:
    return user.get("role") in ("admin", "super_admin")


@router.post("/generate")
async def generate_workflow(req: WorkflowGenerateRequest, authorization: str = Header(None)):
    return {"success": True, "workflow": prototype_workflow_generate(req.instruction)}


@router.post("/execute")
async def execute_workflow(req: WorkflowExecuteRequest, authorization: str = Header(None)):
    user = _optional_user(authorization)
    result = prototype_workflow_execute(req.definition)
    workflow_store.record_execution(req.workflow_id, result["execution_id"], user.get("id") if user else None, result.get("steps", []))
    return {"success": True, **result}


@router.post("/execute-stream")
async def execute_workflow_stream(req: WorkflowExecuteRequest, authorization: str = Header(None)):
    return await prototype_workflow_execute_stream(req.definition)


@router.post("/execute-step-stream")
async def execute_workflow_step_stream(req: WorkflowStepRerunRequest, authorization: str = Header(None)):
    synthetic = {"nodes": [{**req.step, "id": req.step.get("id", "step_1"), "query": req.query}]}
    return await prototype_workflow_execute_stream(synthetic)


@router.post("/execute-stream/{execution_id}/respond")
async def workflow_respond(execution_id: str, request: Request, authorization: str = Header(None)):
    return {"success": True}


@router.post("/save")
async def save_workflow_endpoint(req: WorkflowSaveRequest, authorization: str = Header(None)):
    user = _require_user(authorization)
    wid = workflow_store.save_workflow(req.id, req.name, req.instruction, req.definition, req.mermaid_code, user["id"], req.agent_user_configs, req.memory_enabled)
    return {"success": True, "id": wid}


@router.get("")
async def list_workflows_endpoint(authorization: str = Header(None)):
    user = _optional_user(authorization)
    if not user:
        return {"success": True, "workflows": []}
    workflows = workflow_store.list_workflows(user["id"], _is_admin(user))
    return {"success": True, "workflows": workflows}


@router.get("/executions/{execution_id}")
async def get_workflow_execution(execution_id: str, authorization: str = Header(None), full: bool = False):
    detail = workflow_store.get_execution(execution_id, full=full)
    if not detail:
        raise HTTPException(status_code=404, detail="Execution not found")
    return {"success": True, "execution": detail}


@router.delete("/executions/{execution_id}")
async def delete_workflow_execution(execution_id: str, authorization: str = Header(None)):
    _require_user(authorization)
    if not workflow_store.delete_execution(execution_id):
        raise HTTPException(status_code=404, detail="Execution not found")
    return {"success": True}


@router.get("/executions/{execution_id}/steps/{step_number}")
async def get_workflow_execution_step(execution_id: str, step_number: int, authorization: str = Header(None)):
    step = workflow_store.get_execution_step(execution_id, step_number)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return {"success": True, "step": step}


@router.get("/{workflow_id}/executions")
async def list_workflow_executions(workflow_id: str, authorization: str = Header(None)):
    _require_user(authorization)
    return {"success": True, "executions": workflow_store.list_executions(workflow_id)}


@router.get("/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str, authorization: str = Header(None)):
    wf = workflow_store.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    user = _optional_user(authorization)
    if user and (_is_admin(user) or wf.get("user_id") == user.get("id")):
        return {"success": True, "workflow": wf}
    public_wf = dict(wf)
    public_wf.pop("agent_user_configs", None)
    return {"success": True, "workflow": public_wf}


@router.delete("/{workflow_id}")
async def delete_workflow_endpoint(workflow_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    wf = workflow_store.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not _is_admin(user) and wf.get("user_id") != user.get("id"):
        raise HTTPException(status_code=403, detail="Not allowed")
    workflow_store.delete_workflow(workflow_id)
    return {"success": True}


@router.get("/{workflow_id}/memory-users")
async def list_workflow_memory_users_endpoint(workflow_id: str, authorization: str = Header(None)):
    user = _require_user(authorization)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return {"success": True, "users": [{"user_id": 1, "username": "admin"}]}
