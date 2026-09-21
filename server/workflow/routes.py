"""
Workflow API routes - FastAPI router for workflow orchestration endpoints.
Extracted from api.py to keep workflow-related code in a single package.
"""

import json
import asyncio
import uuid as _uuid
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import orchestrator as workflow_orchestrator

router = APIRouter(prefix="/api/admin/workflows", tags=["workflows"])


# ── Request models ──────────────────────────────────────────────

class WorkflowGenerateRequest(BaseModel):
    instruction: str

class WorkflowSaveRequest(BaseModel):
    id: Optional[str] = None
    name: str
    instruction: str
    definition: Dict[str, Any]
    mermaid_code: str
    # Omitted or null = keep existing stored configs on update; dict replaces stored credentials.
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None
    # Omitted or null = preserve existing flag (default False for new workflows).
    memory_enabled: Optional[bool] = None

class WorkflowExecuteRequest(BaseModel):
    definition: Dict[str, Any]
    workflow_id: Optional[str] = None
    # Client-provided config (e.g. browser localStorage), keyed by catalog agent id (e.g. jira_agent).
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None
    # Per-agent extra kwargs merged into the dispatch call (e.g. uploaded_files for company_solution_advisor).
    agent_extra_kwargs: Optional[Dict[str, Dict[str, Any]]] = None
    # Execution mode: "auto" (run all batches automatically) or "step" (pause after each batch for user approval).
    step_mode: str = "auto"


class WorkflowStepRerunRequest(BaseModel):
    """Re-run a single agent step with a pre-resolved input (e.g. the full_query
    captured from a previous run). Skips DAG dependency resolution and is not
    persisted as a workflow execution."""
    step: Dict[str, Any]
    # The exact input string to send to the agent (typically the previous run's resolved full_query).
    query: str
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None
    agent_extra_kwargs: Optional[Dict[str, Dict[str, Any]]] = None


# ── Helper: import auth utilities lazily from api module ────────

def _get_auth_helpers():
    """Lazy import to avoid circular dependency with api module."""
    import admin_auth as _admin_auth
    return _admin_auth


def _require_permission(authorization: Optional[str], permission: str) -> Dict:
    admin_auth = _get_auth_helpers()
    token = (authorization or "").replace("Bearer ", "")
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if user.get("role") in ("admin", "super_admin"):
        return user
    perms = user.get("menu_permissions", [])
    if permission not in perms:
        raise HTTPException(status_code=403, detail=f"No access to '{permission}'")
    return user


def _optional_user(authorization: Optional[str]) -> Optional[Dict]:
    """Return the JWT user dict if Authorization is valid; otherwise None."""
    admin_auth = _get_auth_helpers()
    token = (authorization or "").replace("Bearer ", "").strip()
    if not token:
        return None
    return admin_auth.verify_token(token)


def _require_authenticated(authorization: Optional[str]) -> Dict:
    """Valid JWT required (any logged-in admin user). No menu-permission check."""
    admin_auth = _get_auth_helpers()
    token = (authorization or "").replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def _is_admin(user: Dict) -> bool:
    return user.get("role") in ("admin", "super_admin")


def _assert_workflow_owned_or_admin(user: Dict, wf: Optional[Dict]) -> Dict:
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if _is_admin(user):
        return wf
    owner_id = wf.get("user_id")
    if owner_id is None:
        raise HTTPException(status_code=403, detail="Not allowed to access this workflow")
    if owner_id != user.get("id"):
        raise HTTPException(status_code=403, detail="Not allowed to access this workflow")
    return wf


# ── Endpoints ───────────────────────────────────────────────────

@router.post("/generate")
async def generate_workflow(req: WorkflowGenerateRequest, authorization: str = Header(None)):
    # Public: no auth required (optional token ignored for access control).
    try:
        result = await workflow_orchestrator.generate_workflow(req.instruction)
        return {"success": True, "workflow": result}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Failed to parse LLM response: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute")
async def execute_workflow(req: WorkflowExecuteRequest, authorization: str = Header(None)):
    user = _optional_user(authorization)
    try:
        result = await workflow_orchestrator.execute_workflow(
            req.definition, agent_user_configs=req.agent_user_configs,
            agent_extra_kwargs=req.agent_extra_kwargs,
            user_id=(user.get("id") if user else None),
        )
        return {"success": True, **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute-stream")
async def execute_workflow_stream(req: WorkflowExecuteRequest, authorization: str = Header(None)):
    # Public runs: user_id only set when a valid JWT is sent.
    user = _optional_user(authorization)

    workflow_orchestrator.init_workflow_db()

    execution_id = str(_uuid.uuid4())

    # Look up the workflow to honour its memory toggle. Falls back to False
    # for ad-hoc runs (no workflow_id) or unknown ids.
    memory_enabled = False
    if req.workflow_id:
        try:
            wf_doc = workflow_orchestrator.get_workflow(req.workflow_id)
            if wf_doc and wf_doc.get("memory_enabled"):
                memory_enabled = True
        except Exception:
            memory_enabled = False

    run_all, event_queue = await workflow_orchestrator.execute_workflow_streaming(
        req.definition,
        execution_id,
        workflow_id=req.workflow_id,
        agent_user_configs=req.agent_user_configs,
        agent_extra_kwargs=req.agent_extra_kwargs,
        user_id=(user.get("id") if user else None),
        memory_enabled=memory_enabled,
        step_mode=req.step_mode,
    )

    async def event_generator():
        yield ": " + " " * 2048 + "\n\n"
        yield f"data: {json.dumps({'event': 'execution_started', 'data': {'execution_id': execution_id}})}\n\n"
        await asyncio.sleep(0)

        runner_task = asyncio.create_task(run_all())

        try:
            while True:
                try:
                    item = await asyncio.wait_for(event_queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}})}\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
                await asyncio.sleep(0)

            await runner_task
        except (asyncio.CancelledError, GeneratorExit):
            runner_task.cancel()
            try:
                await runner_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@router.post("/execute-step-stream")
async def execute_workflow_step_stream(req: WorkflowStepRerunRequest, authorization: str = Header(None)):
    """Re-run a single agent step using the previous resolved input. Streams SSE
    events identical to ``/execute-stream`` but for one step, with no DAG
    resolution and no execution-history persistence.
    """
    user = _optional_user(authorization)

    workflow_orchestrator.init_workflow_db()
    execution_id = str(_uuid.uuid4())

    # Strip dependency/KB context: the caller is supplying the already-resolved
    # input verbatim, so we don't want execute_step to re-resolve placeholders
    # or re-run vector search.
    raw_step = dict(req.step or {})
    if "step_number" not in raw_step:
        raw_step["step_number"] = 1
    if "agent_id" not in raw_step:
        raise HTTPException(status_code=400, detail="step.agent_id is required")
    rerun_step = {
        **raw_step,
        "query": req.query,
        "depends_on": [],
        "input_mapping": {},
        "kb_index": None,
    }
    synthetic_def = {
        "name": f"Re-run step {rerun_step['step_number']} ({rerun_step['agent_id']})",
        "steps": [rerun_step],
    }

    run_all, event_queue = await workflow_orchestrator.execute_workflow_streaming(
        synthetic_def,
        execution_id,
        workflow_id=None,
        agent_user_configs=req.agent_user_configs,
        agent_extra_kwargs=req.agent_extra_kwargs,
        user_id=(user.get("id") if user else None),
    )

    async def event_generator():
        yield ": " + " " * 2048 + "\n\n"
        yield f"data: {json.dumps({'event': 'execution_started', 'data': {'execution_id': execution_id}})}\n\n"
        await asyncio.sleep(0)

        runner_task = asyncio.create_task(run_all())

        try:
            while True:
                try:
                    item = await asyncio.wait_for(event_queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'heartbeat', 'data': {}})}\n\n"
                    continue
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
                await asyncio.sleep(0)

            await runner_task
        except (asyncio.CancelledError, GeneratorExit):
            runner_task.cancel()
            try:
                await runner_task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@router.post("/execute-stream/{execution_id}/respond")
async def workflow_respond(execution_id: str, request: Request, authorization: str = Header(None)):
    owner_id = workflow_orchestrator.get_execution_owner_user_id(execution_id)
    if owner_id is not None:
        user = _require_authenticated(authorization)
        if not _is_admin(user) and owner_id != user.get("id"):
            raise HTTPException(status_code=403, detail="Not allowed to access this execution")
    # Anonymous executions (user_id NULL): respond without login.

    body = await request.json()
    step_num = body.get("step_number")
    user_input = body.get("input", "")
    if step_num is None or not user_input:
        raise HTTPException(status_code=400, detail="step_number and input are required")
    ok = workflow_orchestrator.submit_user_input(execution_id, int(step_num), user_input)
    if not ok:
        raise HTTPException(status_code=404, detail="No pending input for this step")
    return {"success": True}


@router.post("/save")
async def save_workflow_endpoint(req: WorkflowSaveRequest, authorization: str = Header(None)):
    admin_auth = _get_auth_helpers()
    token = (authorization or "").replace("Bearer ", "")
    user = admin_auth.verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        workflow_orchestrator.init_workflow_db()
        wid = workflow_orchestrator.save_workflow(
            req.id,
            req.name,
            req.instruction,
            req.definition,
            req.mermaid_code,
            user_id=user["id"],
            agent_user_configs=req.agent_user_configs,
            memory_enabled=req.memory_enabled,
        )
        return {"success": True, "id": wid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_workflows_endpoint(authorization: str = Header(None)):
    """My agents: empty list when not logged in; otherwise own workflows (or all if admin)."""
    user = _optional_user(authorization)
    if not user:
        return {"success": True, "workflows": []}
    try:
        workflow_orchestrator.init_workflow_db()
        is_admin = user.get("role") in ("admin", "super_admin")
        workflows = workflow_orchestrator.list_workflows(user_id=user["id"], is_admin=is_admin)
        return {"success": True, "workflows": workflows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _authorize_execution_access(execution_id: str, authorization: Optional[str]) -> Dict:
    """Resolve + authorize an execution, returning the owner row.

    Raises 404 if the execution is unknown, and 401/403 if the caller may not
    access it. For public/anonymous runs (user_id NULL) access is open.
    """
    owner_id = workflow_orchestrator.get_execution_owner_user_id(execution_id)
    # get_execution_owner_user_id returns None either when the execution does
    # not exist OR when it exists but has no owner. The distinction matters for
    # callers that need a 404; the caller can re-check the detail/summary.
    if owner_id is None:
        return {"owner_id": None}
    user = _optional_user(authorization)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not _is_admin(user) and owner_id != user.get("id"):
        raise HTTPException(status_code=403, detail="Not allowed to access this execution")
    return {"owner_id": owner_id, "user": user}


@router.get("/executions/{execution_id}")
async def get_workflow_execution(
    execution_id: str,
    authorization: str = Header(None),
    full: bool = False,
):
    """Fetch an execution.

    By default, returns lightweight per-step metadata (sizes + status) so the
    history panel can render quickly. Pass ``?full=true`` for the legacy
    response that inlines every step's query/response/bpmn_xml.
    """
    try:
        workflow_orchestrator.init_workflow_db()
        if full:
            detail = workflow_orchestrator.get_execution_detail(execution_id)
        else:
            detail = workflow_orchestrator.get_execution_summary(execution_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Execution not found")
        owner_id = detail.get("user_id")
        if owner_id is None:
            return {"success": True, "execution": detail}
        user = _optional_user(authorization)
        if not user:
            raise HTTPException(status_code=401, detail="Unauthorized")
        if not _is_admin(user) and owner_id != user.get("id"):
            raise HTTPException(status_code=403, detail="Not allowed to access this execution")
        return {"success": True, "execution": detail}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/executions/{execution_id}")
async def delete_workflow_execution(execution_id: str, authorization: str = Header(None)):
    """Remove a single run and its persisted steps (owner or admin)."""
    user = _require_authenticated(authorization)
    try:
        workflow_orchestrator.init_workflow_db()
        wf_id = workflow_orchestrator.get_execution_workflow_id(execution_id)
        if not wf_id:
            raise HTTPException(status_code=404, detail="Execution not found")
        wf = workflow_orchestrator.get_workflow(wf_id)
        _assert_workflow_owned_or_admin(user, wf)
        deleted = workflow_orchestrator.delete_execution(execution_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Execution not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/executions/{execution_id}/steps/{step_number}")
async def get_workflow_execution_step(
    execution_id: str,
    step_number: int,
    authorization: str = Header(None),
):
    """Fetch the full body for a single execution step (lazy-loaded on expand)."""
    try:
        workflow_orchestrator.init_workflow_db()
        _authorize_execution_access(execution_id, authorization)
        step = workflow_orchestrator.get_execution_step(execution_id, step_number)
        if not step:
            raise HTTPException(status_code=404, detail="Step not found")
        return {"success": True, "step": step}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/executions")
async def list_workflow_executions(workflow_id: str, authorization: str = Header(None)):
    user = _require_authenticated(authorization)
    try:
        workflow_orchestrator.init_workflow_db()
        wf = workflow_orchestrator.get_workflow(workflow_id)
        _assert_workflow_owned_or_admin(user, wf)
        executions = workflow_orchestrator.list_executions(workflow_id)
        return {"success": True, "executions": executions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}")
async def get_workflow_endpoint(workflow_id: str, authorization: str = Header(None)):
    try:
        workflow_orchestrator.init_workflow_db()
        wf = workflow_orchestrator.get_workflow(workflow_id)
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")

        user = _optional_user(authorization)
        owner_id = wf.get("user_id")
        can_view_private = bool(
            user and (_is_admin(user) or (owner_id is not None and owner_id == user.get("id")))
        )
        if can_view_private:
            return {"success": True, "workflow": wf}

        # Public/shared view: allow loading by id but never leak stored credentials.
        public_wf = dict(wf)
        public_wf.pop("agent_user_configs", None)
        return {"success": True, "workflow": public_wf}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}/memory-users")
async def list_workflow_memory_users_endpoint(
    workflow_id: str,
    authorization: str = Header(None),
):
    """Admin-only: list users who have run this workflow (with usernames).

    Each user keeps an isolated memory bucket per workflow, so the viewer needs
    this list to switch between users.
    """
    user = _require_authenticated(authorization)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")

    workflow_orchestrator.init_workflow_db()
    wf = workflow_orchestrator.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    user_ids = workflow_orchestrator.list_workflow_run_user_ids(workflow_id)
    owner_id = wf.get("user_id")
    if owner_id is not None and owner_id not in user_ids:
        user_ids = [owner_id, *user_ids]

    import admin_auth as _admin_auth
    users_out = []
    seen: set = set()
    for uid in user_ids:
        if uid in seen:
            continue
        seen.add(uid)
        try:
            u = _admin_auth.get_user(int(uid))
        except Exception:
            u = None
        users_out.append({
            "user_id": int(uid),
            "username": (u or {}).get("username") if u else None,
            "is_owner": owner_id is not None and int(uid) == int(owner_id),
        })

    return {"success": True, "owner_user_id": owner_id, "users": users_out}


@router.get("/{workflow_id}/memories")
async def list_workflow_memories_endpoint(
    workflow_id: str,
    authorization: str = Header(None),
    page: int = 1,
    page_size: int = 50,
    target_user_id: Optional[int] = None,
):
    """Admin-only: fetch stored mem0 memories for a workflow.

    Returns ``{success, available, results, mem_user_id, page, page_size}``.
    *available=False* signals mem0 is not configured (missing API key / SDK).

    By default scopes to the workflow owner's memories. ``target_user_id`` lets
    super-admins inspect another user's run history for the same workflow.
    """
    user = _require_authenticated(authorization)
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin access required")

    workflow_orchestrator.init_workflow_db()
    wf = workflow_orchestrator.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Default: workflow owner's bucket. Falls back to current admin if owner is unknown.
    owner_id = wf.get("user_id")
    user_for_lookup = (
        target_user_id
        if target_user_id is not None
        else (owner_id if owner_id is not None else user.get("id"))
    )

    from workflow.components.memory import list_workflow_memories
    try:
        data = await list_workflow_memories(
            workflow_id=workflow_id,
            user_id=str(user_for_lookup) if user_for_lookup is not None else None,
            page=page,
            page_size=page_size,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mem0 lookup failed: {e}")

    return {
        "success": True,
        "memory_enabled": bool(wf.get("memory_enabled")),
        **data,
    }


@router.delete("/{workflow_id}")
async def delete_workflow_endpoint(workflow_id: str, authorization: str = Header(None)):
    user = _require_authenticated(authorization)
    try:
        workflow_orchestrator.init_workflow_db()
        wf = workflow_orchestrator.get_workflow(workflow_id)
        _assert_workflow_owned_or_admin(user, wf)
        deleted = workflow_orchestrator.delete_workflow(workflow_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
