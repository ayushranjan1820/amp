from typing import Any, Dict, List, Optional


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _safe_latency_ms(item: Dict[str, Any]) -> float:
    latency = item.get("latency") or item.get("latency_ms") or item.get("duration")
    if latency is None:
        start_time = item.get("startTime") or item.get("start_time")
        end_time = item.get("endTime") or item.get("end_time")
        if isinstance(start_time, (int, float)) and isinstance(end_time, (int, float)):
            latency = max(0.0, float(end_time) - float(start_time))
    try:
        return float(latency) if latency is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _extract_usage(item: Dict[str, Any]) -> Dict[str, Any]:
    usage = item.get("usage") or {}
    if not isinstance(usage, dict):
        return {}
    return {
        "input_tokens": int(usage.get("input") or usage.get("promptTokens") or usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("output") or usage.get("completionTokens") or usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total") or usage.get("totalTokens") or usage.get("total_tokens") or 0),
    }


def _extract_cost(item: Dict[str, Any]) -> Optional[float]:
    for key in ("totalCost", "total_cost", "cost", "calculatedTotalCost"):
        val = item.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    return None


def normalize_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a full Langfuse trace into a rich, consistent schema."""
    spans: List[Dict[str, Any]] = list(trace.get("spans") or [])
    generations: List[Dict[str, Any]] = list(trace.get("generations") or [])
    tool_calls: List[Dict[str, Any]] = list(trace.get("tool_calls") or trace.get("toolCalls") or [])
    observations: List[Dict[str, Any]] = list(trace.get("observations") or [])
    scores_raw: List[Dict[str, Any]] = list(trace.get("scores") or [])

    if observations:
        for obs in observations:
            obs_type = (obs.get("type") or "").lower()
            if obs_type == "generation":
                generations.append(obs)
            elif obs_type == "span":
                spans.append(obs)

    steps: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    models_used: set = set()

    for span in spans:
        span_name = _stringify(span.get("name") or "span")
        if span_name.lower().startswith("tool") or span.get("tool_name") or span.get("toolName"):
            step_type = "tool"
        else:
            step_type = "llm"
        usage = _extract_usage(span)
        step = {
            "type": step_type,
            "name": span_name,
            "input": _stringify(span.get("input") or span.get("prompt")),
            "output": _stringify(span.get("output")),
            "latency_ms": _safe_latency_ms(span),
            "level": _stringify(span.get("level")),
            "model": _stringify(span.get("model")),
            "usage": usage,
            "metadata": span.get("metadata") or {},
        }
        steps.append(step)
        if usage.get("total_tokens"):
            total_input_tokens += usage["input_tokens"]
            total_output_tokens += usage["output_tokens"]
            total_tokens += usage["total_tokens"]
        if step["model"]:
            models_used.add(step["model"])
        if span.get("level") == "ERROR" or span.get("status") == "ERROR" or span.get("error"):
            errors.append({
                "step": span_name,
                "type": step_type,
                "message": _stringify(span.get("error") or span.get("statusMessage") or "Span error"),
                "level": _stringify(span.get("level")),
            })

    for generation in generations:
        gen_name = _stringify(generation.get("name") or generation.get("model") or "generation")
        model = _stringify(generation.get("model"))
        usage = _extract_usage(generation)
        step = {
            "type": "llm",
            "name": gen_name,
            "input": _stringify(generation.get("input") or generation.get("prompt")),
            "output": _stringify(generation.get("output") or generation.get("completion")),
            "latency_ms": _safe_latency_ms(generation),
            "level": _stringify(generation.get("level")),
            "model": model,
            "usage": usage,
            "model_parameters": generation.get("modelParameters") or generation.get("model_parameters") or {},
            "metadata": generation.get("metadata") or {},
        }
        steps.append(step)
        if usage.get("total_tokens"):
            total_input_tokens += usage["input_tokens"]
            total_output_tokens += usage["output_tokens"]
            total_tokens += usage["total_tokens"]
        if model:
            models_used.add(model)
        if generation.get("error"):
            errors.append({"step": gen_name, "type": "llm", "message": _stringify(generation.get("error"))})

    for tool_call in tool_calls:
        tool_name = _stringify(tool_call.get("name") or tool_call.get("toolName") or "tool_call")
        step = {
            "type": "tool",
            "name": tool_name,
            "input": _stringify(tool_call.get("input") or tool_call.get("args")),
            "output": _stringify(tool_call.get("output") or tool_call.get("result")),
            "latency_ms": _safe_latency_ms(tool_call),
            "level": _stringify(tool_call.get("level")),
            "metadata": tool_call.get("metadata") or {},
        }
        steps.append(step)
        if tool_call.get("error"):
            errors.append({"step": tool_name, "type": "tool", "message": _stringify(tool_call.get("error"))})

    scores = []
    for s in scores_raw:
        if isinstance(s, dict):
            scores.append({
                "name": _stringify(s.get("name")),
                "value": s.get("value"),
                "source": _stringify(s.get("source")),
                "comment": _stringify(s.get("comment")),
            })

    total_cost = _extract_cost(trace)
    if total_tokens == 0:
        total_tokens = total_input_tokens + total_output_tokens

    normalized = {
        "trace_id": _stringify(trace.get("id")),
        "name": _stringify(trace.get("name")),
        "session_id": _stringify(trace.get("sessionId") or trace.get("session_id")),
        "user_id": _stringify(trace.get("userId") or trace.get("user_id")),
        "timestamp": _stringify(trace.get("timestamp") or trace.get("createdAt")),
        "input": _stringify(trace.get("input")),
        "output": _stringify(trace.get("output")),
        "tags": trace.get("tags") or [],
        "release": _stringify(trace.get("release")),
        "version": _stringify(trace.get("version")),
        "steps": steps,
        "errors": errors,
        "scores": scores,
        "metadata": trace.get("metadata") or {},
        "token_usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_tokens,
        },
        "total_cost": total_cost,
        "models_used": sorted(models_used),
        "step_count": len(steps),
        "error_count": len(errors),
        "has_errors": len(errors) > 0,
    }
    return normalized
