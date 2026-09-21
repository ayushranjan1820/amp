import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from agents.llm_activity_stream import build_llm_call_step, build_llm_response_step

from .ai_service import (
    trace_debugger_ai_service,
    user_message_mentions_langfuse_session,
)
from .models import TraceDebuggerResponse
from .tools.langfuse_client import LangfuseClient
from .tools.normalizer import normalize_trace


def _chunk_text_for_stream(text: str, target_size: int = 100) -> List[str]:
    """Match api._chunk_text shape for SSE streaming of the final summary."""
    if not text:
        return []
    paragraphs = text.split("\n\n")
    chunks: List[str] = []
    for i, para in enumerate(paragraphs):
        suffix = "\n\n" if i < len(paragraphs) - 1 else ""
        if len(para) <= target_size:
            chunks.append(para + suffix)
        else:
            lines = para.split("\n")
            buf: List[str] = []
            buf_len = 0
            for line in lines:
                buf.append(line)
                buf_len += len(line) + 1
                if buf_len >= target_size:
                    chunks.append("\n".join(buf) + "\n")
                    buf = []
                    buf_len = 0
            if buf:
                chunks.append("\n".join(buf) + suffix)
    return chunks or [text]


class TraceDebuggerAgent:
    """Open-ended Langfuse agent: search, inspect, debug, explore sessions, get metrics, and more."""

    _VALID_OPS = frozenset({
        "inspect_trace", "debug_trace", "search_traces", "explore_session", "list_sessions",
        "get_scores", "get_observations", "compare_traces", "get_metrics", "browse_logs",
        "get_prompts", "get_datasets", "general_answer",
    })

    def __init__(self):
        self.langfuse = LangfuseClient()
        self.ai = trace_debugger_ai_service

    def _coerce_operations(self, payload_results: List[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for _, spec in payload_results:
            op = (spec.get("op") or "").strip().lower()
            if op in self._VALID_OPS:
                out.append(spec)
        if not out:
            return [{"op": "browse_logs", "search_params": {"limit": 15, "order_by": "timestamp.desc"}}]
        return out

    def _plan_and_build_operations(
        self, raw_input: str, thinking: List[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        prov, model = self.ai.llm_activity_meta()
        thinking.append(
            build_llm_call_step(
                provider=prov,
                model=model,
                prompt=self.ai.build_plan_prompt(raw_input),
                phase_note="Langfuse plan",
            )
        )
        _plan_raw, plan = self.ai.plan_langfuse_workflow(raw_input)
        thinking.append(build_llm_response_step(provider=prov, model=model, text=_plan_raw))
        steps = plan.get("steps") or []
        if not isinstance(steps, list):
            steps = []

        for i, step in enumerate(steps):
            thinking.append(
                build_llm_call_step(
                    provider=prov,
                    model=model,
                    prompt=self.ai.build_payload_prompt(raw_input, step, i),
                    phase_note=f"Langfuse payload[{i}]",
                )
            )

        max_workers = min(8, max(1, len(steps))) if steps else 1
        if not steps:
            return plan, [{"op": "browse_logs", "search_params": {"limit": 15, "order_by": "timestamp.desc"}}]

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            payload_results = list(
                ex.map(
                    lambda pair: self.ai.build_operation_payload(raw_input, pair[1], pair[0]),
                    enumerate(steps),
                )
            )

        for raw_txt, _ in payload_results:
            thinking.append(build_llm_response_step(provider=prov, model=model, text=raw_txt))

        return plan, self._coerce_operations(payload_results)

    def _finalize_summary(
        self,
        raw_input: str,
        plan: Dict[str, Any],
        all_results: List[Dict[str, Any]],
        thinking: List[Dict[str, Any]],
    ) -> str:
        prov, model = self.ai.llm_activity_meta()
        context = {
            "plan": plan,
            "explicit_session_in_query": user_message_mentions_langfuse_session(raw_input),
        }
        summ_prompt, response_text = self.ai.summarize_langfuse_results(
            user_query=raw_input,
            operation_results=all_results,
            context=context,
        )
        thinking.append(
            build_llm_call_step(
                provider=prov,
                model=model,
                prompt=summ_prompt,
                phase_note="Langfuse summary",
            )
        )
        thinking.append(build_llm_response_step(provider=prov, model=model, text=response_text))
        return response_text

    def debug_trace(self, trace_id: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        _ = session_id
        raw_input = (trace_id or "").strip()
        thinking: List[Dict[str, Any]] = [
            {"type": "thinking", "content": f"Processing request: `{raw_input}`"}
        ]

        try:
            if self.langfuse.is_likely_trace_id(raw_input):
                return self._handle_single_trace(raw_input, mode="auto", thinking=thinking)

            plan, operations = self._plan_and_build_operations(raw_input, thinking)

            all_results: List[Dict[str, Any]] = []
            collected_data: Dict[str, Any] = {}

            for op_spec in operations:
                op = (op_spec.get("op") or "").strip().lower()
                result = self._execute_operation(op, op_spec, None, thinking)
                all_results.append({"operation": op, **result})
                for k, v in result.items():
                    if k not in ("operation",):
                        collected_data[k] = v

            response_text = self._finalize_summary(raw_input, plan, all_results, thinking)

            primary_trace_id = ""
            primary_analysis: Dict[str, Any] = {}
            for r in all_results:
                if r.get("trace_id"):
                    primary_trace_id = str(r["trace_id"])
                if r.get("analysis"):
                    primary_analysis = r["analysis"]
                if primary_trace_id and primary_analysis:
                    break

            return TraceDebuggerResponse(
                success=True,
                trace_id=primary_trace_id,
                response=response_text,
                thinking_steps=thinking,
                analysis=primary_analysis,
                normalized_trace=collected_data,
                operation=", ".join(str(op.get("op", "")) for op in operations),
                data=collected_data,
            ).model_dump()

        except Exception as exc:
            thinking.append({"type": "tool_result", "content": f"Error: {exc}", "tool_name": "agent"})
            return TraceDebuggerResponse(
                success=False,
                trace_id=raw_input,
                response=f"Operation failed: {exc}",
                thinking_steps=thinking,
            ).model_dump()

    async def debug_trace_stream(self, user_query: str) -> AsyncIterator[Any]:
        """SSE pipeline: plan → parallel payloads → Langfuse → summary (streamed chunks)."""
        raw_input = (user_query or "").strip()
        prov, model = self.ai.llm_activity_meta()
        collected: List[Dict[str, Any]] = [{"type": "thinking", "content": f"Processing request: `{raw_input}`"}]
        yield {"event": "thinking", "data": collected[0]}

        try:
            if self.langfuse.is_likely_trace_id(raw_input):
                yield {"event": "progress", "data": {"stage": "trace", "message": "Inspecting trace…"}}
                thinking = [collected[0]]
                result = await asyncio.to_thread(self._handle_single_trace, raw_input, "auto", thinking)
                for step in thinking[1:]:
                    collected.append(step)
                    yield {"event": "thinking", "data": step}
                resp = result.get("response") or ""
                for chunk in _chunk_text_for_stream(resp):
                    yield {"event": "response_chunk", "data": {"chunk": chunk}}
                    await asyncio.sleep(0.02)
                out = dict(result)
                out["_skip_final_response_chunking"] = True
                out["thinking_steps"] = collected
                yield out
                return

            yield {"event": "progress", "data": {"stage": "plan", "message": "Planning Langfuse operations…"}}
            pc = build_llm_call_step(
                provider=prov,
                model=model,
                prompt=self.ai.build_plan_prompt(raw_input),
                phase_note="Langfuse plan",
            )
            collected.append(pc)
            yield {"event": "thinking", "data": pc}

            plan_raw, plan = await asyncio.to_thread(self.ai.plan_langfuse_workflow, raw_input)
            pr = build_llm_response_step(provider=prov, model=model, text=plan_raw)
            collected.append(pr)
            yield {"event": "thinking", "data": pr}

            steps = plan.get("steps") or []
            if not isinstance(steps, list):
                steps = []

            yield {
                "event": "progress",
                "data": {"stage": "payloads", "message": f"Building {len(steps)} Langfuse payload(s) in parallel…"},
            }

            for i, step in enumerate(steps):
                p_call = build_llm_call_step(
                    provider=prov,
                    model=model,
                    prompt=self.ai.build_payload_prompt(raw_input, step, i),
                    phase_note=f"Langfuse payload[{i}]",
                )
                collected.append(p_call)
                yield {"event": "thinking", "data": p_call}

            max_workers = min(8, max(1, len(steps))) if steps else 1
            payload_results: List[Tuple[str, Dict[str, Any]]] = []
            if not steps:
                operations = [{"op": "browse_logs", "search_params": {"limit": 15, "order_by": "timestamp.desc"}}]
            else:
                loop = asyncio.get_running_loop()

                def _build(pair: Tuple[int, Dict[str, Any]]) -> Tuple[str, Dict[str, Any]]:
                    idx, st = pair
                    return self.ai.build_operation_payload(raw_input, st, idx)

                def _run_pool() -> List[Tuple[str, Dict[str, Any]]]:
                    with ThreadPoolExecutor(max_workers=max_workers) as ex:
                        return list(ex.map(_build, enumerate(steps)))

                payload_results = await loop.run_in_executor(None, _run_pool)
                operations = self._coerce_operations(payload_results)

            for raw_txt, _ in payload_results:
                rs = build_llm_response_step(provider=prov, model=model, text=raw_txt)
                collected.append(rs)
                yield {"event": "thinking", "data": rs}

            yield {"event": "progress", "data": {"stage": "fetch", "message": "Querying Langfuse…"}}

            all_results: List[Dict[str, Any]] = []
            collected_data: Dict[str, Any] = {}
            for op_spec in operations:
                op = (op_spec.get("op") or "").strip().lower()
                exec_thinking: List[Dict[str, Any]] = []
                r = await asyncio.to_thread(self._execute_operation, op, op_spec, None, exec_thinking)
                for step in exec_thinking:
                    collected.append(step)
                    yield {"event": "thinking", "data": step}
                all_results.append({"operation": op, **r})
                for k, v in r.items():
                    if k != "operation":
                        collected_data[k] = v

            yield {"event": "progress", "data": {"stage": "summarize", "message": "Summarizing results…"}}
            context = {
                "plan": plan,
                "explicit_session_in_query": user_message_mentions_langfuse_session(raw_input),
            }
            summ_prompt, response_text = await asyncio.to_thread(
                self.ai.summarize_langfuse_results,
                raw_input,
                all_results,
                context,
            )
            sc = build_llm_call_step(
                provider=prov,
                model=model,
                prompt=summ_prompt,
                phase_note="Langfuse summary",
            )
            collected.append(sc)
            yield {"event": "thinking", "data": sc}
            sr = build_llm_response_step(provider=prov, model=model, text=response_text)
            collected.append(sr)
            yield {"event": "thinking", "data": sr}

            for chunk in _chunk_text_for_stream(response_text):
                yield {"event": "response_chunk", "data": {"chunk": chunk}}
                await asyncio.sleep(0.02)

            primary_trace_id = ""
            primary_analysis: Dict[str, Any] = {}
            for r in all_results:
                if r.get("trace_id"):
                    primary_trace_id = str(r["trace_id"])
                if r.get("analysis"):
                    primary_analysis = r["analysis"]
                if primary_trace_id and primary_analysis:
                    break

            yield {
                "success": True,
                "trace_id": primary_trace_id,
                "response": response_text,
                "thinking_steps": collected,
                "analysis": primary_analysis,
                "normalized_trace": collected_data,
                "operation": ", ".join(str(op.get("op", "")) for op in operations),
                "data": collected_data,
                "_skip_final_response_chunking": True,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as exc:
            collected.append({"type": "tool_result", "content": f"Error: {exc}", "tool_name": "agent"})
            yield {"event": "thinking", "data": collected[-1]}
            yield {
                "success": False,
                "trace_id": raw_input,
                "response": f"Operation failed: {exc}",
                "thinking_steps": collected,
                "_skip_final_response_chunking": True,
                "timestamp": datetime.now().isoformat(),
            }

    # ------------------------------------------------------------------
    # Operation dispatcher
    # ------------------------------------------------------------------

    def _execute_operation(
        self, op: str, spec: Dict[str, Any], session_id: Optional[str], thinking: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        handlers = {
            "inspect_trace": self._op_inspect_trace,
            "debug_trace": self._op_debug_trace,
            "search_traces": self._op_search_traces,
            "explore_session": self._op_explore_session,
            "list_sessions": self._op_list_sessions,
            "get_scores": self._op_get_scores,
            "get_observations": self._op_get_observations,
            "compare_traces": self._op_compare_traces,
            "get_metrics": self._op_get_metrics,
            "browse_logs": self._op_browse_logs,
            "get_prompts": self._op_get_prompts,
            "get_datasets": self._op_get_datasets,
            "general_answer": self._op_general_answer,
        }
        handler = handlers.get(op, self._op_browse_logs)
        return handler(spec, session_id, thinking)

    # ------------------------------------------------------------------
    # Individual operation handlers
    # ------------------------------------------------------------------

    def _op_inspect_trace(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        tid = (spec.get("trace_id") or "").strip()
        if not tid:
            return {"error": "No trace_id provided for inspect"}

        thinking.append({"type": "tool_call", "content": f"Fetching trace {tid}", "tool_name": "langfuse_get_trace"})
        trace_data = self.langfuse.get_trace_cached(tid)
        normalized = normalize_trace(trace_data)
        observations = self.langfuse.get_observations(trace_id=tid)
        scores = self.langfuse.get_trace_scores(tid)
        obs_metrics = self.langfuse.compute_observation_metrics(observations)

        thinking.append({"type": "tool_result", "content": f"Trace {tid}: {normalized['step_count']} steps, {normalized['error_count']} errors", "tool_name": "langfuse_get_trace"})

        analysis = self.ai.analyze_trace(normalized, mode="inspect")

        return {
            "trace_id": tid,
            "normalized_trace": normalized,
            "observations": observations,
            "scores": scores,
            "observation_metrics": obs_metrics,
            "analysis": analysis,
        }

    def _op_debug_trace(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        tid = (spec.get("trace_id") or "").strip()
        if not tid:
            return {"error": "No trace_id provided for debug"}

        thinking.append({"type": "tool_call", "content": f"Debugging trace {tid}", "tool_name": "langfuse_get_trace"})
        trace_data = self.langfuse.get_trace_cached(tid)
        normalized = normalize_trace(trace_data)

        thinking.append({"type": "tool_call", "content": "Analyzing for failures", "tool_name": "trace_debugger_llm"})
        analysis = self.ai.analyze_trace(normalized, mode="debug")
        thinking.append({"type": "tool_result", "content": f"Debug complete: {analysis.get('status', 'unknown')}", "tool_name": "trace_debugger_llm"})

        return {
            "trace_id": tid,
            "normalized_trace": normalized,
            "analysis": analysis,
        }

    def _op_search_traces(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        search_params = dict(spec.get("search_params") or {})
        if not search_params.get("order_by"):
            search_params["order_by"] = "timestamp.desc"
        if not search_params.get("limit"):
            search_params["limit"] = 20

        thinking.append({"type": "tool_call", "content": f"Searching traces: {json.dumps(search_params)}", "tool_name": "langfuse_list_traces"})
        traces = self.langfuse.list_traces(search_params)
        thinking.append({"type": "tool_result", "content": f"Found {len(traces)} traces", "tool_name": "langfuse_list_traces"})

        max_traces = min(int(spec.get("max_traces") or 0), 10)
        analyses = []
        if max_traces > 0 and traces:
            for t in traces[:max_traces]:
                try:
                    td = self.langfuse.get_trace_cached(t["id"])
                    norm = normalize_trace(td)
                    a = self.ai.analyze_trace(norm, mode="inspect")
                    analyses.append({"trace_id": t["id"], "analysis": a})
                except Exception:
                    pass

        metrics = self.langfuse.compute_trace_metrics(traces)

        return {
            "traces": traces,
            "trace_count": len(traces),
            "metrics": metrics,
            "analyses": analyses,
            "search_params": search_params,
        }

    def _op_explore_session(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        _ = sid
        session_id = (spec.get("session_id") or "").strip()
        if not session_id:
            return {
                "error": (
                    "No session_id in the operation payload. "
                    "Ask the user for a Langfuse session id, or use search_traces with name/tags instead."
                ),
            }

        thinking.append({"type": "tool_call", "content": f"Exploring session {session_id}", "tool_name": "langfuse_session"})
        traces = self.langfuse.get_session_traces(session_id, limit=50)
        thinking.append({"type": "tool_result", "content": f"Session {session_id}: {len(traces)} traces", "tool_name": "langfuse_session"})

        metrics = self.langfuse.compute_trace_metrics(traces)

        max_analyze = min(int(spec.get("max_traces") or 3), 5)
        analyses = []
        for t in traces[:max_analyze]:
            try:
                td = self.langfuse.get_trace_cached(t["id"])
                norm = normalize_trace(td)
                a = self.ai.analyze_trace(norm, mode="inspect")
                analyses.append({"trace_id": t["id"], "name": t.get("name", ""), "analysis": a})
            except Exception:
                pass

        return {
            "session_id": session_id,
            "traces": traces,
            "trace_count": len(traces),
            "metrics": metrics,
            "analyses": analyses,
        }

    def _op_list_sessions(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        thinking.append({"type": "tool_call", "content": "Listing sessions", "tool_name": "langfuse_sessions"})
        sessions = self.langfuse.list_sessions(spec.get("search_params"))
        thinking.append({"type": "tool_result", "content": f"Found {len(sessions)} sessions", "tool_name": "langfuse_sessions"})
        return {"sessions": sessions, "session_count": len(sessions)}

    def _op_get_scores(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        score_params = dict(spec.get("score_params") or spec.get("search_params") or {})
        if spec.get("trace_id"):
            score_params["trace_id"] = spec["trace_id"]

        thinking.append({"type": "tool_call", "content": "Fetching scores", "tool_name": "langfuse_scores"})
        scores = self.langfuse.list_scores(score_params)
        thinking.append({"type": "tool_result", "content": f"Found {len(scores)} scores", "tool_name": "langfuse_scores"})

        score_summary: Dict[str, List] = {}
        for s in scores:
            name = s.get("name", "unknown")
            if name not in score_summary:
                score_summary[name] = []
            if s.get("value") is not None:
                score_summary[name].append(s["value"])

        aggregates = {}
        for name, vals in score_summary.items():
            numeric = [v for v in vals if isinstance(v, (int, float))]
            if numeric:
                aggregates[name] = {
                    "count": len(numeric),
                    "avg": round(sum(numeric) / len(numeric), 4),
                    "min": min(numeric),
                    "max": max(numeric),
                }
            else:
                aggregates[name] = {"count": len(vals)}

        return {"scores": scores, "score_count": len(scores), "aggregates": aggregates}

    def _op_get_observations(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        tid = (spec.get("trace_id") or "").strip()
        thinking.append({"type": "tool_call", "content": f"Getting observations{' for ' + tid if tid else ''}", "tool_name": "langfuse_observations"})
        observations = self.langfuse.get_observations(trace_id=tid or None, params=spec.get("search_params"))
        metrics = self.langfuse.compute_observation_metrics(observations)
        thinking.append({"type": "tool_result", "content": f"Found {len(observations)} observations", "tool_name": "langfuse_observations"})
        return {
            "trace_id": tid,
            "observations": observations,
            "observation_count": len(observations),
            "observation_metrics": metrics,
        }

    def _op_compare_traces(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        search_params = dict(spec.get("search_params") or {})
        if not search_params.get("limit"):
            search_params["limit"] = 10
        if not search_params.get("order_by"):
            search_params["order_by"] = "timestamp.desc"

        thinking.append({"type": "tool_call", "content": "Fetching traces for comparison", "tool_name": "langfuse_list_traces"})
        traces = self.langfuse.list_traces(search_params)

        max_compare = min(int(spec.get("max_traces") or 5), 10)
        comparisons = []
        for t in traces[:max_compare]:
            try:
                td = self.langfuse.get_trace_cached(t["id"])
                norm = normalize_trace(td)
                a = self.ai.analyze_trace(norm, mode="inspect")
                comparisons.append({
                    "trace_id": t["id"],
                    "name": t.get("name", ""),
                    "timestamp": t.get("timestamp", ""),
                    "normalized": norm,
                    "analysis": a,
                })
            except Exception:
                pass

        thinking.append({"type": "tool_result", "content": f"Compared {len(comparisons)} traces", "tool_name": "trace_compare"})
        return {"comparisons": comparisons, "compared_count": len(comparisons)}

    def _op_get_metrics(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        search_params = dict(spec.get("search_params") or {})
        if not search_params.get("limit"):
            search_params["limit"] = 50
        if not search_params.get("order_by"):
            search_params["order_by"] = "timestamp.desc"

        thinking.append({"type": "tool_call", "content": "Computing metrics from traces", "tool_name": "langfuse_metrics"})
        traces = self.langfuse.list_traces(search_params)
        trace_metrics = self.langfuse.compute_trace_metrics(traces)

        all_obs: List[Dict[str, Any]] = []
        for t in traces[:10]:
            try:
                obs = self.langfuse.get_observations(trace_id=t["id"])
                all_obs.extend(obs)
            except Exception:
                pass

        obs_metrics = self.langfuse.compute_observation_metrics(all_obs)
        thinking.append({"type": "tool_result", "content": f"Metrics computed from {len(traces)} traces, {len(all_obs)} observations", "tool_name": "langfuse_metrics"})

        return {
            "trace_metrics": trace_metrics,
            "observation_metrics": obs_metrics,
            "traces_analyzed": len(traces),
            "observations_analyzed": len(all_obs),
        }

    def _op_browse_logs(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        search_params = dict(spec.get("search_params") or {})
        if not search_params.get("limit"):
            search_params["limit"] = 15
        if not search_params.get("order_by"):
            search_params["order_by"] = "timestamp.desc"

        thinking.append({"type": "tool_call", "content": "Browsing recent logs", "tool_name": "langfuse_list_traces"})
        traces = self.langfuse.list_traces(search_params)
        metrics = self.langfuse.compute_trace_metrics(traces)
        thinking.append({"type": "tool_result", "content": f"Retrieved {len(traces)} traces", "tool_name": "langfuse_list_traces"})

        return {
            "traces": traces,
            "trace_count": len(traces),
            "metrics": metrics,
        }

    def _op_get_prompts(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        prompt_name = (spec.get("prompt_name") or "").strip()
        thinking.append({"type": "tool_call", "content": f"Getting prompts{': ' + prompt_name if prompt_name else ''}", "tool_name": "langfuse_prompts"})

        if prompt_name:
            prompt = self.langfuse.get_prompt(prompt_name)
            thinking.append({"type": "tool_result", "content": f"Retrieved prompt: {prompt_name}", "tool_name": "langfuse_prompts"})
            return {"prompt": prompt, "prompt_name": prompt_name}

        prompts = self.langfuse.list_prompts()
        thinking.append({"type": "tool_result", "content": f"Found {len(prompts)} prompts", "tool_name": "langfuse_prompts"})
        return {"prompts": prompts, "prompt_count": len(prompts)}

    def _op_get_datasets(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        dataset_name = (spec.get("dataset_name") or "").strip()
        thinking.append({"type": "tool_call", "content": f"Getting datasets{': ' + dataset_name if dataset_name else ''}", "tool_name": "langfuse_datasets"})

        if dataset_name:
            dataset = self.langfuse.get_dataset(dataset_name)
            thinking.append({"type": "tool_result", "content": f"Retrieved dataset: {dataset_name}", "tool_name": "langfuse_datasets"})
            return {"dataset": dataset, "dataset_name": dataset_name}

        datasets = self.langfuse.list_datasets()
        thinking.append({"type": "tool_result", "content": f"Found {len(datasets)} datasets", "tool_name": "langfuse_datasets"})
        return {"datasets": datasets, "dataset_count": len(datasets)}

    def _op_general_answer(self, spec: Dict, sid: Optional[str], thinking: List) -> Dict[str, Any]:
        thinking.append({"type": "tool_call", "content": "Gathering data for general answer", "tool_name": "langfuse_list_traces"})
        traces = self.langfuse.list_traces({"limit": 15, "order_by": "timestamp.desc"})
        sessions = self.langfuse.list_sessions({"limit": 10})
        metrics = self.langfuse.compute_trace_metrics(traces)
        thinking.append({"type": "tool_result", "content": f"Context: {len(traces)} traces, {len(sessions)} sessions", "tool_name": "langfuse_data"})

        return {
            "traces": traces,
            "sessions": sessions,
            "metrics": metrics,
        }

    # ------------------------------------------------------------------
    # Fast path for direct trace IDs
    # ------------------------------------------------------------------

    def _handle_single_trace(self, trace_id: str, mode: str, thinking: List) -> Dict[str, Any]:
        thinking.append({"type": "tool_call", "content": f"Fetching trace {trace_id}", "tool_name": "langfuse_get_trace"})
        trace_data = self.langfuse.get_trace_cached(trace_id)
        normalized = normalize_trace(trace_data)
        observations = self.langfuse.get_observations(trace_id=trace_id)
        scores = self.langfuse.get_trace_scores(trace_id)
        obs_metrics = self.langfuse.compute_observation_metrics(observations)

        thinking.append({"type": "tool_result", "content": f"{normalized['step_count']} steps, {normalized['error_count']} errors", "tool_name": "langfuse_get_trace"})

        analysis_mode = "debug" if (mode == "debug" or normalized["has_errors"]) else "inspect"
        thinking.append({"type": "tool_call", "content": f"Analyzing trace ({analysis_mode} mode)", "tool_name": "trace_analyzer"})
        analysis = self.ai.analyze_trace(normalized, mode=analysis_mode)
        thinking.append({"type": "tool_result", "content": f"Analysis: {analysis.get('status', 'done')}", "tool_name": "trace_analyzer"})

        thinking.append({"type": "tool_call", "content": "Formatting response", "tool_name": "llm_response"})
        response_text = self.ai.format_response(
            user_query=f"Tell me about trace {trace_id}",
            operation_results=[{
                "operation": "inspect_trace",
                "trace_id": trace_id,
                "normalized_trace": normalized,
                "observations_count": len(observations),
                "scores": scores,
                "observation_metrics": obs_metrics,
                "analysis": analysis,
            }],
            context={"mode": analysis_mode},
        )

        return TraceDebuggerResponse(
            success=True,
            trace_id=trace_id,
            response=response_text,
            thinking_steps=thinking,
            analysis=analysis,
            normalized_trace={
                "normalized": normalized,
                "observations": observations,
                "scores": scores,
                "observation_metrics": obs_metrics,
            },
            operation="inspect_trace",
            data={
                "normalized": normalized,
                "observations": observations,
                "scores": scores,
                "observation_metrics": obs_metrics,
                "analysis": analysis,
            },
        ).model_dump()


trace_debugger_agent = TraceDebuggerAgent()
