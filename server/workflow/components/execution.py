"""Workflow execution — sync and streaming (SSE) execution paths."""

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from .catalog import AGENT_REGISTRY, AGENT_PROGRESS_PHASES, DEFAULT_PROGRESS_PHASES
from .dispatch import _dispatch_agent
from .load_gate import heavy_agent_slot
from .prompt_harness import build_dep_response_overrides
from .step_helpers import (
    _resolve_query_dependencies,
    _retrieve_kb_context,
    _normalize_result,
    merge_attachments_into_agent_dispatch,
    normalize_depends_on,
)
from .followup import needs_followup, extract_followup_question
from .user_input import wait_for_user_input
from .db import create_execution, save_execution_step, complete_execution
from .memory import retrieve_memories, store_interaction

logger = logging.getLogger(__name__)


def _agent_result_response_text(result: dict) -> str:
    """Pick a user-facing string from an agent payload; avoid ``json.dumps`` on raw Pydantic models."""
    r = result.get("response")
    if isinstance(r, str) and r.strip():
        return r
    if r is not None and not isinstance(r, str):
        return str(r)
    m = result.get("message")
    if isinstance(m, str) and m.strip():
        return m
    if m is not None and not isinstance(m, str):
        return str(m)
    return json.dumps(result)


def _parse_batch_approval_response(raw: str, allowed_steps: List[int]) -> Tuple[bool, Dict[int, str]]:
    """Parse POST body text for batch pause (step mode).

    Returns (should_stop, query_overrides) where ``query_overrides`` maps step_number
    to the full raw prompt to send to the agent for the next batch (optional).

    Legacy: ``\"continue\"`` / ``\"stop\"`` / empty string behavior preserved.
    """
    if not raw:
        return True, {}
    t = raw.strip()
    low = t.lower()
    if low == "stop":
        return True, {}
    allowed = set(allowed_steps)
    if low == "continue":
        return False, {}
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        return False, {}
    if obj is None:
        return True, {}
    if not isinstance(obj, dict):
        return False, {}
    cmd = str(obj.get("cmd") or obj.get("action") or "").strip().lower()
    if cmd == "stop" or obj.get("stop") is True:
        return True, {}
    overrides = obj.get("overrides") or obj.get("step_queries")
    out: Dict[int, str] = {}
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            try:
                sn = int(k)
            except (TypeError, ValueError):
                continue
            if sn in allowed and isinstance(v, str):
                out[sn] = v
    if cmd == "continue":
        return False, out
    if out:
        return False, out
    return False, {}


# ---------------------------------------------------------------------------
# Non-streaming execution
# ---------------------------------------------------------------------------


async def execute_workflow(
    workflow_def: Dict[str, Any],
    on_step_update=None,
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None,
    agent_extra_kwargs: Optional[Dict[str, Dict[str, Any]]] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute a workflow definition with DAG-based parallelism.

    Returns a dict with ``success``, ``results``, and ``statuses``.
    """
    steps = workflow_def.get("steps", [])
    results: Dict[int, Dict] = {}
    step_statuses: Dict[int, str] = {s["step_number"]: "pending" for s in steps}
    workflow_session_id = f"wf-{uuid.uuid4()}"
    from agents.JIRA_agent.tools.ticket_tools import TicketToolsContext

    jira_ticket_ctx = (
        TicketToolsContext()
        if any(s.get("agent_id") == "jira_agent" for s in steps)
        else None
    )

    async def execute_step(step: Dict[str, Any]) -> Dict[str, Any]:
        step_num = step["step_number"]
        agent_id = step["agent_id"]

        step_statuses[step_num] = "running"
        if on_step_update:
            await on_step_update(step_num, "running", None)

        try:
            dep_overrides = await build_dep_response_overrides(step, results, agent_user_configs)
            kb_out = await _retrieve_kb_context(step, results, step_num, dep_overrides=dep_overrides)
            if kb_out:
                query, _n_chunks = kb_out
            else:
                query = _resolve_query_dependencies(step["query"], step, results, dep_overrides=dep_overrides)

            merged_extra = dict((agent_extra_kwargs or {}).get(agent_id) or {})
            query = merge_attachments_into_agent_dispatch(agent_id, query, step, merged_extra)

            sid = workflow_session_id
            _user_str = str(user_id) if user_id is not None else None
            async with heavy_agent_slot(agent_id):
                result = await _dispatch_agent(
                    agent_id,
                    query,
                    sid,
                    threaded=False,
                    agent_user_configs=agent_user_configs,
                    agent_extra_kwargs=merged_extra,
                    ticket_tools_context=jira_ticket_ctx,
                    user_id=_user_str,
                )
            result = _normalize_result(result)

            bpmn_xml = result.get("bpmn_xml")
            download_url = result.get("download_url")
            response_text = _agent_result_response_text(result)

            results[step_num] = {"success": True, "response": response_text, "agent_id": agent_id}
            if bpmn_xml:
                results[step_num]["bpmn_xml"] = bpmn_xml
            if download_url:
                results[step_num]["download_url"] = download_url

            step_statuses[step_num] = "completed"
            if on_step_update:
                await on_step_update(step_num, "completed", dict(results[step_num]))

            return results[step_num]

        except Exception as e:
            error_msg = str(e)
            results[step_num] = {"success": False, "response": f"Error: {error_msg}", "agent_id": agent_id}
            step_statuses[step_num] = "failed"
            if on_step_update:
                await on_step_update(step_num, "failed", error_msg)
            return results[step_num]

    # --- Topological DAG execution ---
    dep_graph = {s["step_number"]: normalize_depends_on(s.get("depends_on")) for s in steps}
    step_map = {s["step_number"]: s for s in steps}
    completed: set = set()

    while len(completed) < len(steps):
        ready = [
            sn for sn, deps in dep_graph.items()
            if sn not in completed and all(d in completed for d in deps)
        ]
        if not ready:
            break

        await asyncio.gather(*(execute_step(step_map[sn]) for sn in ready))
        completed.update(ready)

    all_success = all(r.get("success", False) for r in results.values())
    return {
        "success": all_success,
        "results": {str(k): v for k, v in results.items()},
        "statuses": {str(k): v for k, v in step_statuses.items()},
    }


# ---------------------------------------------------------------------------
# Streaming execution (SSE)
# ---------------------------------------------------------------------------


async def execute_workflow_streaming(
    workflow_def: Dict[str, Any],
    execution_id: str,
    workflow_id: Optional[str] = None,
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None,
    agent_extra_kwargs: Optional[Dict[str, Dict[str, Any]]] = None,
    user_id: Optional[int] = None,
    memory_enabled: bool = False,
    step_mode: str = "auto",
):
    """Execute a workflow and push progress events to an ``asyncio.Queue``.

    Returns ``(run_all_coro, event_queue)``.
    """
    steps = workflow_def.get("steps", [])
    results: Dict[int, Dict] = {}
    step_statuses: Dict[int, str] = {s["step_number"]: "pending" for s in steps}
    # Step-mode batch approval: user-edited full prompts (step_num -> text); shared by run_all + execute_step.
    batch_query_overrides: Dict[int, str] = {}
    event_queue: asyncio.Queue = asyncio.Queue()
    workflow_session_id = f"wf-{execution_id}"
    from agents.JIRA_agent.tools.ticket_tools import TicketToolsContext

    jira_ticket_ctx = (
        TicketToolsContext()
        if any(s.get("agent_id") == "jira_agent" for s in steps)
        else None
    )

    async def emit(event_type: str, data: dict):
        await event_queue.put({"event": event_type, "data": data})

    async def _build_dispatch_query(
        step: Dict[str, Any],
        step_num: int,
        agent_id: str,
        agent_name: str,
        *,
        quiet: bool,
        dispatch_extra: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Resolve KB/deps, memories, and attachments into the text passed to the agent."""
        query = step["query"]
        dep_overrides = await build_dep_response_overrides(step, results, agent_user_configs)
        kb_index = step.get("kb_index")
        kb_out = await _retrieve_kb_context(step, results, step_num, dep_overrides=dep_overrides)
        if kb_out:
            query, n_chunks = kb_out
            if not quiet:
                if n_chunks > 0:
                    await emit("step_progress", {
                        "step_number": step_num, "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": f"Retrieved {n_chunks} relevant chunks from knowledge base (strict context)",
                        "elapsed": 0,
                    })
                elif kb_index and kb_index.get("enabled"):
                    await emit("step_progress", {
                        "step_number": step_num, "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": "KB index enabled: no chunks retrieved — proceeding with strict task context only",
                        "elapsed": 0,
                    })
        else:
            query = _resolve_query_dependencies(query, step, results, dep_overrides=dep_overrides)

        if memory_enabled:
            try:
                mem_block = await retrieve_memories(
                    workflow_id=workflow_id,
                    user_id=str(user_id) if user_id is not None else None,
                    agent_id=agent_id,
                    query=query,
                )
            except Exception as mem_err:
                logger.debug("memory retrieve failed: %s", mem_err)
                mem_block = ""
            if mem_block:
                query = f"{mem_block}\n{query}"
                if not quiet:
                    await emit("step_progress", {
                        "step_number": step_num,
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": "Loaded relevant memories from previous runs",
                        "elapsed": 0,
                    })

        if dispatch_extra is None:
            dispatch_extra = dict((agent_extra_kwargs or {}).get(agent_id) or {})
        query = merge_attachments_into_agent_dispatch(agent_id, query, step, dispatch_extra)
        return query

    # ----- per-step executor -----

    async def execute_step(step: Dict[str, Any]) -> Dict[str, Any]:
        step_num = step["step_number"]
        agent_id = step["agent_id"]
        agent_name = step.get("agent", AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id))
        query = step["query"]

        step_statuses[step_num] = "running"
        await emit("step_start", {
            "step_number": step_num,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "query": query[:200],
        })

        try:
            merged_dispatch_extra = dict((agent_extra_kwargs or {}).get(agent_id) or {})
            query = await _build_dispatch_query(
                step, step_num, agent_id, agent_name, quiet=False,
                dispatch_extra=merged_dispatch_extra,
            )
            override_q = batch_query_overrides.pop(step_num, None)
            if override_q is not None:
                query = override_q

            await emit("step_input", {
                "step_number": step_num,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "full_query": query,
            })

            sid = workflow_session_id

            # Bridge live agent thinking (e.g. Claude Code CLI stream-json) to SSE.
            loop = asyncio.get_running_loop()

            def forward_agent_thinking(step: Union[Dict[str, Any], Any]) -> None:
                if isinstance(step, dict):
                    thinking_payload: Dict[str, Any] = step
                elif hasattr(step, "model_dump"):
                    thinking_payload = step.model_dump()
                elif hasattr(step, "dict"):
                    thinking_payload = step.dict()  # type: ignore[assignment]
                else:
                    thinking_payload = {"type": "thinking", "content": str(step)}

                async def _emit_thinking():
                    await emit("step_thinking", {
                        "step_number": step_num,
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "thinking": thinking_payload,
                    })

                try:
                    asyncio.run_coroutine_threadsafe(_emit_thinking(), loop)
                except RuntimeError:
                    pass

            # --- Progress ticker ---
            phases = AGENT_PROGRESS_PHASES.get(agent_id, DEFAULT_PROGRESS_PHASES)
            done_flag = asyncio.Event()

            async def progress_ticker():
                phase_idx = 0
                elapsed = 0
                phase_interval = max(8, 45 // max(len(phases), 1))
                while not done_flag.is_set():
                    await asyncio.sleep(phase_interval)
                    if done_flag.is_set():
                        break
                    elapsed += phase_interval
                    msg = phases[phase_idx] if phase_idx < len(phases) else f"Still working... ({elapsed}s elapsed)"
                    phase_idx += 1
                    await emit("step_progress", {
                        "step_number": step_num,
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "message": msg,
                        "elapsed": elapsed,
                    })

            ticker_task = asyncio.create_task(progress_ticker())

            _user_str = str(user_id) if user_id is not None else None
            try:
                async with heavy_agent_slot(agent_id):
                    result = await _dispatch_agent(
                        agent_id,
                        query,
                        sid,
                        threaded=True,
                        agent_user_configs=agent_user_configs,
                        agent_extra_kwargs=merged_dispatch_extra if merged_dispatch_extra else None,
                        ticket_tools_context=jira_ticket_ctx,
                        user_id=_user_str,
                        on_thinking_step=forward_agent_thinking,
                    )
            finally:
                done_flag.set()
                ticker_task.cancel()
                try:
                    await ticker_task
                except asyncio.CancelledError:
                    pass

            result = _normalize_result(result)
            response_text = _agent_result_response_text(result)

            # --- Follow-up handling ---
            if needs_followup(response_text):
                extracted_question = await extract_followup_question(response_text, agent_name)
                await emit("needs_input", {
                    "step_number": step_num,
                    "agent_id": agent_id,
                    "agent_name": agent_name,
                    "question": extracted_question,
                })
                user_response = await wait_for_user_input(execution_id, step_num)
                if user_response:
                    await emit("step_resumed", {
                        "step_number": step_num,
                        "agent_name": agent_name,
                        "user_input": user_response[:100],
                    })
                    followup_query = f"{query}\n\nUser's response: {user_response}"
                    followup_agent = agent_id if agent_id in ("basic_agent", "email_agent", "jira_agent") else "basic_agent"
                    async with heavy_agent_slot(followup_agent):
                        result2 = await _dispatch_agent(
                            followup_agent,
                            followup_query,
                            sid,
                            threaded=True,
                            agent_user_configs=agent_user_configs,
                            agent_extra_kwargs=(agent_extra_kwargs or {}).get(followup_agent),
                            ticket_tools_context=jira_ticket_ctx,
                            user_id=_user_str,
                            on_thinking_step=forward_agent_thinking,
                        )
                    result2 = _normalize_result(result2)
                    response_text = _agent_result_response_text(result2)

            # --- Collect special fields ---
            bpmn_xml = result.get("bpmn_xml")
            download_url = result.get("download_url")
            if not download_url and hasattr(result, "download_url"):
                download_url = getattr(result, "download_url", None)

            results[step_num] = {"success": True, "response": response_text, "agent_id": agent_id}
            if bpmn_xml:
                results[step_num]["bpmn_xml"] = bpmn_xml
            if download_url:
                results[step_num]["download_url"] = download_url
            step_statuses[step_num] = "completed"

            # Stream response in chunks.
            # For very large outputs, avoid long artificial delays before step_complete.
            chunk_size = 80 if len(response_text) <= 12_000 else 1_600
            total_chunks = (len(response_text) + chunk_size - 1) // chunk_size
            sleep_per_chunk = 0.0 if total_chunks > 200 else 0.02
            if len(response_text) > chunk_size:
                for i in range(0, len(response_text), chunk_size):
                    chunk = response_text[i:i + chunk_size]
                    await emit("step_output", {
                        "step_number": step_num,
                        "agent_id": agent_id,
                        "agent_name": agent_name,
                        "chunk": chunk,
                        "done": (i + chunk_size) >= len(response_text),
                    })
                    if sleep_per_chunk > 0:
                        await asyncio.sleep(sleep_per_chunk)

            step_complete_data = {
                "step_number": step_num,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "success": True,
                "response": response_text,
            }
            if bpmn_xml:
                step_complete_data["bpmn_xml"] = bpmn_xml
            if download_url:
                step_complete_data["download_url"] = download_url
            await emit("step_complete", step_complete_data)

            if workflow_id:
                try:
                    save_execution_step(
                        execution_id, step_num, agent_id, agent_name,
                        "completed", query, response_text, bpmn_xml, download_url,
                    )
                except Exception as db_err:
                    logger.error("Failed to save step %d result: %s", step_num, db_err)

            if memory_enabled:
                try:
                    await store_interaction(
                        workflow_id=workflow_id,
                        user_id=str(user_id) if user_id is not None else None,
                        agent_id=agent_id,
                        agent_name=agent_name,
                        query=query,
                        response=response_text,
                    )
                except Exception as mem_err:
                    logger.debug("memory store failed: %s", mem_err)

            return results[step_num]

        except Exception as e:
            error_msg = str(e)
            results[step_num] = {"success": False, "response": f"Error: {error_msg}", "agent_id": agent_id}
            step_statuses[step_num] = "failed"
            await emit("step_failed", {
                "step_number": step_num,
                "agent_id": agent_id,
                "agent_name": agent_name,
                "error": error_msg,
            })

            if workflow_id:
                try:
                    save_execution_step(
                        execution_id, step_num, agent_id, agent_name,
                        "failed", query, f"Error: {error_msg}",
                    )
                except Exception as db_err:
                    logger.error("Failed to save step %d failure: %s", step_num, db_err)

            return results[step_num]

    # ----- batch orchestrator -----

    async def run_all():
        if workflow_id:
            try:
                create_execution(execution_id, workflow_id, user_id=user_id)
            except Exception as e:
                logger.error("Could not create execution record: %s", e)

        dep_graph = {s["step_number"]: normalize_depends_on(s.get("depends_on")) for s in steps}
        step_map = {s["step_number"]: s for s in steps}
        completed: set = set()
        batch_num = 0
        stop_requested = False

        while len(completed) < len(steps):
            ready = [
                sn for sn, deps in dep_graph.items()
                if sn not in completed and all(d in completed for d in deps)
            ]
            if not ready:
                break

            batch_num += 1
            ready_names = [
                step_map[sn].get("agent", step_map[sn].get("agent_id", f"Step {sn}"))
                for sn in ready
            ]
            msg = (
                f"Running {len(ready)} agents in parallel: {', '.join(ready_names)}"
                if len(ready) > 1
                else f"Running {ready_names[0]}..."
            )
            await emit("batch_start", {
                "batch": batch_num,
                "step_numbers": ready,
                "agents": ready_names,
                "message": msg,
            })

            await asyncio.gather(*(execute_step(step_map[sn]) for sn in ready))
            completed.update(ready)

            await emit("batch_complete", {
                "batch": batch_num,
                "completed_count": len(completed),
                "total_count": len(steps),
                "message": f"Batch {batch_num} done \u2014 {len(completed)}/{len(steps)} steps completed",
            })

            # In step mode, pause after each batch and wait for user to continue.
            if step_mode == "step":
                remaining_sns = set(dep_graph.keys()) - completed
                if remaining_sns:
                    next_ready = [
                        sn for sn, deps in dep_graph.items()
                        if sn not in completed and all(d in completed for d in deps)
                    ]
                    next_names = [
                        step_map[sn].get("agent", step_map[sn].get("agent_id", f"Step {sn}"))
                        for sn in next_ready
                    ]
                    next_step_inputs: Dict[str, str] = {}
                    for sn in next_ready:
                        st = step_map[sn]
                        aid = st["agent_id"]
                        an = st.get("agent", AGENT_REGISTRY.get(aid, {}).get("name", aid))
                        next_step_inputs[str(sn)] = await _build_dispatch_query(
                            st, sn, aid, an, quiet=True,
                        )
                    await emit("batch_approval_required", {
                        "batch": batch_num,
                        "next_batch": batch_num + 1,
                        "next_step_numbers": next_ready,
                        "next_agents": next_names,
                        "next_step_inputs": next_step_inputs,
                        "message": f"Batch {batch_num} complete. Next up: {', '.join(next_names)}",
                    })
                    # Wait for user to approve (stop / continue / optional edited prompts)
                    user_response = await wait_for_user_input(execution_id, -batch_num)
                    should_stop, overrides = _parse_batch_approval_response(
                        user_response, next_ready
                    )
                    if should_stop:
                        stop_requested = True
                        break
                    batch_query_overrides.update(overrides)

        # Handle unresolved steps (cycles or upstream failures, or user stop)
        unresolved = set(dep_graph.keys()) - completed
        stop_label = "Stopped by user" if stop_requested else "Skipped \u2014 unresolvable dependencies"
        stop_error = "Stopped by user" if stop_requested else "Skipped due to unresolvable dependencies or upstream failure"
        for sn in unresolved:
            step_statuses[sn] = "skipped"
            results[sn] = {
                "success": False,
                "response": stop_label,
                "agent_id": step_map[sn].get("agent_id", ""),
            }
            if not stop_requested:
                await emit("step_failed", {
                    "step_number": sn,
                    "agent_id": step_map[sn].get("agent_id", ""),
                    "agent_name": step_map[sn].get("agent", "Unknown"),
                    "error": stop_error,
                })

        all_success = len(unresolved) == 0 and all(
            r.get("success", False) for r in results.values()
        )

        if workflow_id:
            try:
                complete_execution(execution_id, all_success)
            except Exception as db_err:
                logger.error("Failed to finalize execution: %s", db_err)

        if stop_requested:
            await emit("workflow_stopped", {
                "success": False,
                "message": f"Workflow stopped by user after batch {batch_num}. {len(completed)}/{len(steps)} steps completed.",
                "completed_count": len(completed),
                "total_count": len(steps),
                "results": {str(k): v for k, v in results.items()},
                "statuses": {str(k): v for k, v in step_statuses.items()},
            })
        else:
            await emit("workflow_complete", {
                "success": all_success,
                "results": {str(k): v for k, v in results.items()},
                "statuses": {str(k): v for k, v in step_statuses.items()},
            })
        await event_queue.put(None)

    return run_all, event_queue
