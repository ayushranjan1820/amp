"""Agent dispatch — low-level invocation helpers and agent routing."""

import asyncio
import inspect
import json
import functools
import logging
import os
from typing import Any, Dict, Optional, Tuple

from .catalog import _AGENT_DISPATCH

logger = logging.getLogger(__name__)


# unit_test_agent runs the actual generation in a background daemon thread and
# returns immediately with a task_id. The workflow needs to poll for the real
# result so the step doesn't "complete" on the start banner.
_UNIT_TEST_POLL_INTERVAL = float(os.getenv("UNIT_TEST_POLL_INTERVAL", "2.0"))
_UNIT_TEST_POLL_TIMEOUT = float(os.getenv("UNIT_TEST_POLL_TIMEOUT", "1800"))


# ---------------------------------------------------------------------------
# Low-level invocation
# ---------------------------------------------------------------------------


async def _invoke_async(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Call *method_name* on *obj* and ``await`` if it returns a coroutine."""
    method = getattr(obj, method_name)
    result = method(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


async def _invoke_threaded(obj: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
    """Like ``_invoke_async`` but runs synchronous methods in a thread."""
    method = getattr(obj, method_name)
    if inspect.iscoroutinefunction(method):
        return await method(*args, **kwargs)
    func = functools.partial(method, *args, **kwargs)
    return await asyncio.to_thread(func)


def _build_call_args(call_style: str, query: str, sid: str) -> Tuple[tuple, dict]:
    """Build ``(args, kwargs)`` for an agent call based on its *call_style*."""
    if call_style == "q":
        return (query,), {}
    if call_style == "qs":
        return (query, sid), {}
    if call_style == "qsk":
        return (query,), {"session_id": sid}
    if call_style == "chat":
        return ({"message": query, "session_id": sid},), {}
    if call_style == "doc":
        # Document formatter (and similar) use process(query, ..., session_id=..., output_format=...).
        # A single dict positional was incorrectly bound to *query*, breaking Pydantic responses.
        return (query,), {"session_id": sid, "output_format": "markdown"}
    return (query,), {}


def _strip_code_fences(text: str) -> str:
    """Remove markdown code-fence wrappers (``````...``````) from *text*."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]  # drop closing fence
        text = "\n".join(lines)
    return text.strip()


# ---------------------------------------------------------------------------
# Agent dispatch
# ---------------------------------------------------------------------------


def _coerce_company_solution_uploads(extra: Dict[str, Any]) -> Dict[str, Any]:
    """For company_solution_advisor: convert dict-shaped uploaded_files into
    UploadedSolutionFile pydantic instances so the agent's typed signature works."""
    raw = extra.get("uploaded_files")
    if not raw:
        return extra
    try:
        from agents.Company_solution_agent.models import UploadedSolutionFile
    except Exception:
        return extra
    coerced = []
    for item in raw:
        if isinstance(item, UploadedSolutionFile):
            coerced.append(item)
            continue
        if isinstance(item, dict):
            fc = item.get("file_content")
            ft = item.get("file_type")
            if not fc or not ft:
                continue
            coerced.append(UploadedSolutionFile(
                file_content=fc,
                file_type=ft,
                file_name=item.get("file_name"),
            ))
    out = dict(extra)
    out["uploaded_files"] = coerced
    return out


async def _dispatch_agent(
    agent_id: str,
    query: str,
    sid: str,
    *,
    threaded: bool = False,
    agent_user_configs: Optional[Dict[str, Dict[str, str]]] = None,
    agent_extra_kwargs: Optional[Dict[str, Any]] = None,
    ticket_tools_context: Any = None,
    user_id: Optional[str] = None,
    on_thinking_step: Optional[Any] = None,
) -> Any:
    """Dispatch to an internal agent (via table) or an external agent (via API).

    When *threaded* is ``True`` (streaming path), synchronous agent methods are
    run in a worker thread so they don't block the event loop.

    *agent_user_configs* maps catalog ``agent_id`` (e.g. ``jira_agent``) to key/value
    config from the client (e.g. browser localStorage). When the agent has catalog env
    keys, execution runs inside ``apply_user_config`` with ``isolate_catalog_environment``.
    LLM-related keys never fall back to ``server/.env``; other catalog keys may still use
    ``.env`` when the client did not supply a value.
    """
    from api import _get_agent
    from agents.llm_continuation import set_current_agent, set_current_session, set_current_user
    from user_config import (
        apply_user_config,
        get_agent_display_name_by_id,
        get_catalog_env_keys_for_agent,
        merge_configs_for_agent_id,
    )
    import api as api_module

    display = get_agent_display_name_by_id(agent_id)

    set_current_agent(display or agent_id)
    set_current_session(sid)
    set_current_user(user_id)

    async def _run_dispatch() -> Any:
        dispatch_info = _AGENT_DISPATCH.get(agent_id)
        if dispatch_info:
            agent_key, method_name, call_style, is_async_native = dispatch_info
            agent_obj = _get_agent(agent_key)
            args, kwargs = _build_call_args(call_style, query, sid)
            if agent_id == "jira_agent" and ticket_tools_context is not None:
                kwargs = dict(kwargs)
                kwargs["ticket_tools_context"] = ticket_tools_context
            if agent_extra_kwargs:
                extra = dict(agent_extra_kwargs)
                if call_style == "chat" and args and isinstance(args[0], dict):
                    payload = dict(args[0])
                    base_text = (payload.get("query") or payload.get("message") or query or "").strip()
                    payload["query"] = base_text
                    payload["message"] = base_text
                    for key in ("file_content", "file_type", "file_name", "raw_text"):
                        if key in extra:
                            payload[key] = extra[key]
                            extra.pop(key, None)
                    args = (payload,)
                    # Remaining keys (unlikely for workflow) still go to kwargs
                    if extra:
                        kwargs = dict(kwargs)
                        kwargs.update(extra)
                else:
                    if agent_id == "company_solution_advisor":
                        extra = _coerce_company_solution_uploads(extra)
                    kwargs = dict(kwargs)
                    kwargs.update(extra)
            if on_thinking_step is not None:
                try:
                    method_ref = getattr(agent_obj, method_name)
                    if "on_thinking_step" in inspect.signature(method_ref).parameters:
                        kwargs["on_thinking_step"] = on_thinking_step
                except (TypeError, ValueError):
                    pass
            if threaded and not is_async_native:
                result = await _invoke_threaded(agent_obj, method_name, *args, **kwargs)
            else:
                result = await _invoke_async(agent_obj, method_name, *args, **kwargs)

            if (
                agent_id == "unit_test_agent"
                and isinstance(result, dict)
                and result.get("task_id")
                and hasattr(agent_obj, "get_task_status")
            ):
                result = await _await_unit_test_task(
                    agent_obj,
                    result["task_id"],
                    initial=result,
                    on_thinking_step=on_thinking_step,
                )
            return result
        return await _call_external_agent(agent_id, query, sid, threaded=threaded)

    if not display or not get_catalog_env_keys_for_agent(display):
        return await _run_dispatch()

    merged = merge_configs_for_agent_id(agent_id, (agent_user_configs or {}).get(agent_id))
    # When the client omits agent_user_configs (e.g. Telegram bot, scripts), do not isolate
    # catalog env keys — otherwise apply_user_config strips JIRA_* etc. from the process and
    # server/.env credentials are invisible. Browser/UI calls always send a dict (possibly empty).
    isolate = agent_user_configs is not None
    ctx = apply_user_config(
        merged,
        agent_cache=api_module._agent_cache,
        agent_display_name=display,
        isolate_catalog_environment=isolate,
    )
    ctx.__enter__()
    try:
        return await _run_dispatch()
    finally:
        ctx.__exit__(None, None, None)


async def _emit_thinking_step(on_thinking_step: Optional[Any], step: Dict[str, Any]) -> None:
    if on_thinking_step is None:
        return
    try:
        res = on_thinking_step(step)
        if inspect.isawaitable(res):
            await res
    except Exception:
        logger.exception("on_thinking_step callback failed")


async def _await_unit_test_task(
    agent_obj: Any,
    task_id: str,
    *,
    initial: Dict[str, Any],
    on_thinking_step: Optional[Any],
    poll_interval: float = _UNIT_TEST_POLL_INTERVAL,
    timeout: float = _UNIT_TEST_POLL_TIMEOUT,
) -> Dict[str, Any]:
    """Poll the unit-test agent's background task until it finishes.

    Streams newly-emitted thinking steps and progress messages through
    *on_thinking_step* so the workflow SSE shows live status. Returns the merged
    final result (response/success/thinking_steps) from the completed task.
    """
    seen_steps = len(initial.get("thinking_steps") or [])
    last_progress: Optional[str] = None
    deadline = asyncio.get_event_loop().time() + timeout

    while True:
        status = await asyncio.to_thread(agent_obj.get_task_status, task_id)
        if not status:
            await asyncio.sleep(poll_interval)
            if asyncio.get_event_loop().time() > deadline:
                return {
                    **initial,
                    "success": False,
                    "response": (initial.get("response") or "")
                    + "\n\nUnit test task vanished before completion.",
                }
            continue

        thinking = status.get("thinking_steps") or []
        for step in thinking[seen_steps:]:
            await _emit_thinking_step(on_thinking_step, step)
        seen_steps = len(thinking)

        progress = status.get("progress") or ""
        if progress and progress != last_progress:
            await _emit_thinking_step(
                on_thinking_step,
                {"type": "thinking", "content": progress},
            )
            last_progress = progress

        task_status = status.get("status")
        if task_status and task_status != "running":
            return {
                **initial,
                "success": status.get("success", initial.get("success", True)),
                "response": status.get("response") or initial.get("response", ""),
                "thinking_steps": thinking,
                "task_id": task_id,
                "progress": status.get("progress", ""),
            }

        if asyncio.get_event_loop().time() > deadline:
            return {
                **initial,
                "success": False,
                "response": (initial.get("response") or "")
                + "\n\nUnit test generation timed out before completion.",
                "thinking_steps": thinking,
            }

        await asyncio.sleep(poll_interval)


async def _call_external_agent(agent_id: str, query: str, sid: str, *, threaded: bool = False) -> dict:
    """Call an externally-registered agent via its HTTP API, or fall back to basic_agent."""
    import httpx
    from api import (
        _get_agent, _get_external_agent_config, _build_external_payload,
        _external_request_kwargs,
        _extract_external_response, _llm_call_async,
        _build_payload_adaptation_prompt, _build_response_formatting_prompt,
    )

    ext_config = _get_external_agent_config(agent_id)
    if not ext_config:
        agent = _get_agent("basic_agent")
        if threaded:
            return await _invoke_threaded(agent, "process_query", query)
        return await _invoke_async(agent, "process_query", query)

    ext_url = ext_config["external_api_url"]
    ext_tpl = ext_config.get("external_payload_template", "")
    ext_hdrs = ext_config.get("external_headers", {})
    ext_method = ext_config.get("external_method", "POST").upper()
    ext_format = ext_config.get("external_payload_format", "json")
    ext_name = ext_config.get("name", agent_id)
    ext_desc = ext_config.get("description", "External agent")

    # Build payload
    if ext_tpl and ext_tpl.strip() and "{{query}}" in ext_tpl:
        payload = _build_external_payload(ext_tpl, query, sid)
    else:
        try:
            adapt_prompt = _build_payload_adaptation_prompt(
                query, ext_name, ext_desc, ext_tpl, ext_url, sid,
            )
            llm_text = await _llm_call_async(adapt_prompt, max_tokens=1024, temperature=0.1)
            llm_text = _strip_code_fences(llm_text)
            payload = json.loads(llm_text)
        except Exception:
            payload = {"query": query, "session_id": sid}

    # Send the request
    headers = {"Content-Type": "application/json"}
    if ext_hdrs and isinstance(ext_hdrs, dict):
        headers.update(ext_hdrs)
    headers, request_kwargs = _external_request_kwargs(payload, ext_format, headers)

    async with httpx.AsyncClient(timeout=120.0, verify=False) as client:
        resp = await client.request(ext_method, ext_url, headers=headers, **request_kwargs)
        resp.raise_for_status()

    raw_resp = _extract_external_response(resp)

    # Optionally format the response via an LLM pass
    is_json_like = raw_resp.strip().startswith("{") or raw_resp.strip().startswith("[")
    if is_json_like or len(raw_resp) > 2000:
        try:
            fmt_prompt = _build_response_formatting_prompt(raw_resp, ext_name, query)
            formatted = await _llm_call_async(fmt_prompt, max_tokens=4096, temperature=0.3)
        except Exception:
            formatted = raw_resp
    else:
        formatted = raw_resp

    return {"response": formatted, "success": True}
