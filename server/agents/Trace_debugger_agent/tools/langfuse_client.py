import os
import re
import time
from functools import lru_cache
from typing import Any, Dict, List, Optional

from langfuse import Langfuse


def _to_dict(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_to_dict(item) for item in value]
    if isinstance(value, tuple):
        return [_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {k: _to_dict(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return _to_dict(value.model_dump())
    if hasattr(value, "dict"):
        return _to_dict(value.dict())
    if hasattr(value, "__dict__"):
        raw = {k: v for k, v in value.__dict__.items() if not k.startswith("_")}
        return _to_dict(raw)
    return str(value)


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


class LangfuseClient:
    """Full-capability Langfuse client for traces, sessions, observations, scores, prompts, datasets.

    Compatible with Langfuse SDK v4+ (``langfuse.api.*`` namespace).
    """

    def __init__(self):
        self.public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
        self.secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        self.host = (
            os.getenv("LANGFUSE_BASE_URL", "").strip()
            or os.getenv("LANGFUSE_HOST", "").strip()
            or "https://cloud.langfuse.com"
        )
        self.client: Optional[Langfuse] = (
            Langfuse(
                public_key=self.public_key,
                secret_key=self.secret_key,
                host=self.host,
            )
            if self.public_key and self.secret_key
            else None
        )

    def _require_client(self):
        if not self.client:
            raise ValueError("LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are required.")

    # ------------------------------------------------------------------
    # Trace operations
    # ------------------------------------------------------------------

    @staticmethod
    def is_likely_trace_id(value: str) -> bool:
        text = (value or "").strip()
        if not text:
            return False
        if " " in text:
            return False
        if text.startswith("trc_"):
            return True
        return bool(re.fullmatch(r"[0-9a-fA-F-]{16,64}", text))

    def _is_not_found_error(self, exc: Exception) -> bool:
        msg = str(exc)
        return "LangfuseNotFoundError" in msg or "status_code: 404" in msg or "not found" in msg.lower()

    def get_trace(self, trace_id: str, retries: int = 3, retry_delay: float = 0.6) -> Dict[str, Any]:
        if not trace_id.strip():
            raise ValueError("trace_id cannot be empty")
        self._require_client()
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                raw = self.client.api.trace.get(trace_id.strip())
                data = _to_dict(raw)
                if not isinstance(data, dict):
                    raise RuntimeError("Langfuse trace payload is not a dictionary")
                return data
            except Exception as exc:
                if self._is_not_found_error(exc):
                    raise RuntimeError(f"Trace {trace_id} not found: {exc}") from exc
                last_error = exc
                if attempt == retries - 1:
                    break
                time.sleep(retry_delay * (attempt + 1))
        raise RuntimeError(f"Failed to fetch trace {trace_id}: {last_error}") from last_error

    @lru_cache(maxsize=256)
    def get_trace_cached(self, trace_id: str) -> Dict[str, Any]:
        return self.get_trace(trace_id=trace_id)

    def list_traces(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self._require_client()
        params = dict(params or {})
        allowed = {
            "page", "limit", "user_id", "name", "session_id",
            "from_timestamp", "to_timestamp", "order_by", "tags",
        }
        clean = {k: v for k, v in params.items() if k in allowed and v not in (None, "", [], {})}

        try:
            data = self.client.api.trace.list(**clean)
        except Exception as exc:
            raise RuntimeError(f"Failed to list traces: {exc}") from exc

        return self._extract_trace_list(data)

    def _extract_trace_list(self, data: Any) -> List[Dict[str, Any]]:
        raw = _to_dict(data)
        if isinstance(raw, dict):
            values = raw.get("data") or raw.get("traces") or []
        elif isinstance(raw, list):
            values = raw
        else:
            values = []

        out: List[Dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            entry = {
                "id": _safe_str(item.get("id")),
                "name": _safe_str(item.get("name")),
                "session_id": _safe_str(item.get("sessionId") or item.get("session_id")),
                "user_id": _safe_str(item.get("userId") or item.get("user_id")),
                "timestamp": _safe_str(item.get("timestamp") or item.get("createdAt")),
                "tags": item.get("tags") or [],
                "input": _safe_str(item.get("input")),
                "output": _safe_str(item.get("output")),
                "metadata": item.get("metadata") or {},
                "release": _safe_str(item.get("release")),
                "version": _safe_str(item.get("version")),
            }
            if item.get("latency") is not None:
                entry["latency"] = item["latency"]
            if item.get("totalCost") is not None or item.get("total_cost") is not None:
                entry["total_cost"] = item.get("totalCost") or item.get("total_cost")
            if item.get("usage"):
                entry["usage"] = _to_dict(item["usage"])
            if item.get("scores"):
                entry["scores"] = _to_dict(item["scores"])
            if item.get("level") or item.get("status"):
                entry["level"] = _safe_str(item.get("level") or item.get("status"))
            out.append(entry)
        return [t for t in out if t.get("id")]

    def find_trace_candidates(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        self._require_client()
        query = (query or "").strip()
        if not query:
            return []

        seen: set = set()
        candidates: List[Dict[str, Any]] = []

        def _collect(items: Any):
            for item in self._extract_trace_list(items):
                tid = item.get("id", "")
                if tid and tid not in seen:
                    seen.add(tid)
                    candidates.append(item)

        for kwargs in (
            {"name": query, "limit": limit},
            {"session_id": query, "limit": limit},
            {"user_id": query, "limit": limit},
            {"tags": [query], "limit": limit},
        ):
            try:
                _collect(self.client.api.trace.list(**kwargs))
            except Exception:
                continue
            if len(candidates) >= limit:
                break

        return candidates[:limit]

    # ------------------------------------------------------------------
    # Observation operations
    # ------------------------------------------------------------------

    def get_observations(self, trace_id: Optional[str] = None, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Get observations, optionally filtered by trace_id or other params."""
        self._require_client()

        if trace_id:
            trace = self.get_trace_cached(trace_id)
            observations = trace.get("observations") or []
            if observations:
                return [self._normalize_observation(obs) for obs in observations if isinstance(obs, dict)]

            # Fallback to API if trace object doesn't embed observations
            try:
                data = self.client.api.observations.get_many(trace_id=trace_id, limit=100)
                return self._extract_observation_list(data)
            except Exception:
                return []

        params = dict(params or {})
        allowed = {"limit", "name", "type", "trace_id", "parent_observation_id", "user_id"}
        clean = {k: v for k, v in params.items() if k in allowed and v not in (None, "", [], {})}

        try:
            data = self.client.api.observations.get_many(**clean)
        except Exception:
            return []

        return self._extract_observation_list(data)

    def _extract_observation_list(self, data: Any) -> List[Dict[str, Any]]:
        raw = _to_dict(data)
        if isinstance(raw, dict):
            values = raw.get("data") or raw.get("observations") or []
        elif isinstance(raw, list):
            values = raw
        else:
            values = []
        return [self._normalize_observation(obs) for obs in values if isinstance(obs, dict)]

    def _normalize_observation(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": _safe_str(obs.get("id")),
            "trace_id": _safe_str(obs.get("traceId") or obs.get("trace_id")),
            "type": _safe_str(obs.get("type")),
            "name": _safe_str(obs.get("name")),
            "start_time": _safe_str(obs.get("startTime") or obs.get("start_time")),
            "end_time": _safe_str(obs.get("endTime") or obs.get("end_time")),
            "input": obs.get("input"),
            "output": obs.get("output"),
            "model": _safe_str(obs.get("model")),
            "model_parameters": obs.get("modelParameters") or obs.get("model_parameters") or {},
            "usage": _to_dict(obs.get("usage")) or {},
            "level": _safe_str(obs.get("level")),
            "status_message": _safe_str(obs.get("statusMessage") or obs.get("status_message")),
            "parent_observation_id": _safe_str(obs.get("parentObservationId") or obs.get("parent_observation_id")),
            "metadata": obs.get("metadata") or {},
            "completion_start_time": _safe_str(obs.get("completionStartTime") or obs.get("completion_start_time")),
        }

    # ------------------------------------------------------------------
    # Session operations
    # ------------------------------------------------------------------

    def list_sessions(self, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self._require_client()
        params = dict(params or {})
        allowed = {"page", "limit", "from_timestamp", "to_timestamp"}
        clean = {k: v for k, v in params.items() if k in allowed and v not in (None, "", [], {})}
        if "limit" not in clean:
            clean["limit"] = 20

        try:
            data = self.client.api.sessions.list(**clean)
        except Exception:
            return self._sessions_via_traces(clean.get("limit", 20))

        raw = _to_dict(data)
        if isinstance(raw, dict):
            values = raw.get("data") or raw.get("sessions") or []
        elif isinstance(raw, list):
            values = raw
        else:
            values = []

        return [self._normalize_session(s) for s in values if isinstance(s, dict)]

    def _sessions_via_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fallback: derive sessions from recent traces."""
        traces = self.list_traces({"limit": min(limit * 3, 100), "order_by": "timestamp.desc"})
        session_map: Dict[str, Dict[str, Any]] = {}
        for t in traces:
            sid = t.get("session_id", "")
            if not sid:
                continue
            if sid not in session_map:
                session_map[sid] = {
                    "id": sid,
                    "created_at": t.get("timestamp", ""),
                    "trace_count": 0,
                    "trace_ids": [],
                }
            session_map[sid]["trace_count"] += 1
            session_map[sid]["trace_ids"].append(t.get("id", ""))
        return list(session_map.values())[:limit]

    def _normalize_session(self, session: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": _safe_str(session.get("id")),
            "created_at": _safe_str(session.get("createdAt") or session.get("created_at")),
            "project_id": _safe_str(session.get("projectId") or session.get("project_id")),
            "trace_count": session.get("traces") if isinstance(session.get("traces"), int) else len(session.get("traces") or []),
        }

    def get_session_traces(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self.list_traces({"session_id": session_id, "limit": limit, "order_by": "timestamp.desc"})

    # ------------------------------------------------------------------
    # Score operations
    # ------------------------------------------------------------------

    def list_scores(self, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self._require_client()
        params = dict(params or {})
        allowed = {"page", "limit", "user_id", "name", "trace_id", "source", "data_type", "config_id"}
        clean = {k: v for k, v in params.items() if k in allowed and v not in (None, "", [], {})}
        if "limit" not in clean:
            clean["limit"] = 25

        try:
            data = self.client.api.scores.get_many(**clean)
        except Exception:
            return []

        raw = _to_dict(data)
        if isinstance(raw, dict):
            values = raw.get("data") or raw.get("scores") or []
        elif isinstance(raw, list):
            values = raw
        else:
            values = []

        return [self._normalize_score(s) for s in values if isinstance(s, dict)]

    def get_trace_scores(self, trace_id: str) -> List[Dict[str, Any]]:
        return self.list_scores({"trace_id": trace_id})

    def _normalize_score(self, score: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": _safe_str(score.get("id")),
            "trace_id": _safe_str(score.get("traceId") or score.get("trace_id")),
            "observation_id": _safe_str(score.get("observationId") or score.get("observation_id")),
            "name": _safe_str(score.get("name")),
            "value": score.get("value"),
            "string_value": _safe_str(score.get("stringValue") or score.get("string_value")),
            "source": _safe_str(score.get("source")),
            "comment": _safe_str(score.get("comment")),
            "timestamp": _safe_str(score.get("timestamp") or score.get("createdAt")),
            "data_type": _safe_str(score.get("dataType") or score.get("data_type")),
        }

    # ------------------------------------------------------------------
    # Prompt operations
    # ------------------------------------------------------------------

    def list_prompts(self, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self._require_client()
        try:
            data = self.client.api.prompts.list(**(params or {}))
        except Exception:
            return []

        raw = _to_dict(data)
        if isinstance(raw, dict):
            values = raw.get("data") or raw.get("prompts") or []
        elif isinstance(raw, list):
            values = raw
        else:
            values = []

        return [_to_dict(p) for p in values if isinstance(p, (dict,))]

    def get_prompt(self, name: str, version: Optional[int] = None) -> Dict[str, Any]:
        self._require_client()
        try:
            data = self.client.get_prompt(name=name, version=version)
            return _to_dict(data)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Dataset operations
    # ------------------------------------------------------------------

    def list_datasets(self, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        self._require_client()
        try:
            data = self.client.api.datasets.list(**(params or {}))
        except Exception:
            return []

        raw = _to_dict(data)
        if isinstance(raw, dict):
            values = raw.get("data") or raw.get("datasets") or []
        elif isinstance(raw, list):
            values = raw
        else:
            values = []

        return [_to_dict(d) for d in values if isinstance(d, (dict,))]

    def get_dataset(self, name: str) -> Dict[str, Any]:
        self._require_client()
        try:
            data = self.client.get_dataset(name=name)
            return _to_dict(data)
        except Exception as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------
    # Metrics / aggregation helpers
    # ------------------------------------------------------------------

    def compute_trace_metrics(self, traces: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute aggregate metrics from a list of trace dicts."""
        total = len(traces)
        if total == 0:
            return {"total_traces": 0}

        latencies = []
        costs = []
        error_count = 0
        names: Dict[str, int] = {}
        sessions: set = set()

        for t in traces:
            name = t.get("name", "unknown")
            names[name] = names.get(name, 0) + 1
            sid = t.get("session_id", "")
            if sid:
                sessions.add(sid)
            if t.get("latency") is not None:
                try:
                    latencies.append(float(t["latency"]))
                except (TypeError, ValueError):
                    pass
            cost = t.get("total_cost")
            if cost is not None:
                try:
                    costs.append(float(cost))
                except (TypeError, ValueError):
                    pass
            level = (t.get("level") or "").upper()
            if level in ("ERROR", "FAILED"):
                error_count += 1

        metrics: Dict[str, Any] = {
            "total_traces": total,
            "unique_sessions": len(sessions),
            "error_count": error_count,
            "error_rate": round(error_count / total, 4) if total else 0,
            "trace_name_distribution": names,
        }
        if latencies:
            latencies.sort()
            metrics["latency_ms"] = {
                "min": round(min(latencies), 2),
                "max": round(max(latencies), 2),
                "avg": round(sum(latencies) / len(latencies), 2),
                "p50": round(latencies[len(latencies) // 2], 2),
                "p95": round(latencies[int(len(latencies) * 0.95)], 2) if len(latencies) > 1 else round(latencies[0], 2),
            }
        if costs:
            metrics["cost"] = {
                "total": round(sum(costs), 6),
                "avg": round(sum(costs) / len(costs), 6),
                "min": round(min(costs), 6),
                "max": round(max(costs), 6),
            }
        return metrics

    def compute_observation_metrics(self, observations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compute metrics from observations (token usage, model breakdown, etc.)."""
        total = len(observations)
        if total == 0:
            return {"total_observations": 0}

        models: Dict[str, int] = {}
        types: Dict[str, int] = {}
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0
        error_count = 0

        for obs in observations:
            model = obs.get("model", "") or "unknown"
            obs_type = obs.get("type", "") or "unknown"
            models[model] = models.get(model, 0) + 1
            types[obs_type] = types.get(obs_type, 0) + 1

            usage = obs.get("usage") or {}
            if isinstance(usage, dict):
                total_input_tokens += int(usage.get("input") or usage.get("promptTokens") or usage.get("prompt_tokens") or 0)
                total_output_tokens += int(usage.get("output") or usage.get("completionTokens") or usage.get("completion_tokens") or 0)
                total_tokens += int(usage.get("total") or usage.get("totalTokens") or usage.get("total_tokens") or 0)

            level = (obs.get("level") or "").upper()
            if level == "ERROR":
                error_count += 1

        if total_tokens == 0:
            total_tokens = total_input_tokens + total_output_tokens

        return {
            "total_observations": total,
            "observation_type_distribution": types,
            "model_distribution": models,
            "token_usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_tokens,
            },
            "error_count": error_count,
        }


# Backward compat alias
LangfuseTraceClient = LangfuseClient
