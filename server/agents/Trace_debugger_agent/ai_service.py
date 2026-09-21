"""AI service for Trace Debugger Agent — delegates to shared BaseAIService."""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from agents.base_ai_service import BaseAIService
from agents.local_llm import get_llm_provider, uses_pwc_genai_credentials


def user_message_mentions_langfuse_session(user_query: str) -> bool:
    """True only when the user typed a Langfuse-style session id (not trace UUIDs, not the app chat id)."""
    q = (user_query or "").strip()
    if not q:
        return False
    return bool(re.search(r"\bsession-[A-Za-z0-9_.-]{4,}\b", q))


PLAN_SYSTEM_PROMPT = """You are the planning stage for a Langfuse observability agent.

Return JSON ONLY with exactly these keys:
- reasoning: short string — why these steps answer the user
- steps: array of 1–4 objects, each with:
  - op: one of the operation names below (required)
  - intent: short string — what this step should fetch from Langfuse

Operation names (same as the executor):
inspect_trace, debug_trace, search_traces, explore_session, list_sessions, get_scores,
get_observations, compare_traces, get_metrics, browse_logs, get_prompts, get_datasets, general_answer

CRITICAL RULES:
- NEVER assume a Langfuse session id. Do NOT schedule explore_session unless the USER QUERY explicitly contains a session-like id (e.g. session-...) or clearly names one exact session to inspect.
- Requests such as "traces for <agent name>" or "runs from SQL DB Agent" MUST use search_traces (name / tags / time filters), NOT explore_session, unless the user also gave a session id in the same message.
- If the user pasted a trace id (UUID or trc_), use inspect_trace or debug_trace.
- Prefer minimal plans (often one search_traces is enough).

Always return strict JSON."""


PAYLOAD_SYSTEM_PROMPT = """You are the payload builder for a Langfuse API client.

Given the USER QUERY and one PLANNED STEP, output JSON ONLY — a single operation object the server will run.

Allowed top-level keys (omit keys that do not apply):
- op: required string, must match the planned step's op
- trace_id, session_id, search_params, prompt_name, dataset_name, score_params, max_traces

search_params optional keys: page, limit, user_id, name, session_id, from_timestamp, to_timestamp, order_by, tags

RULES:
- NEVER invent session_id or user_id. Set session_id ONLY if the USER QUERY explicitly contains that exact session string (or clearly copies it).
- For agent/tool names, set search_params.name to plausible Langfuse trace names (variations, e.g. "SQL DB Agent", "SQL DB agent", "SqlDb") and keep limit reasonable (15–30) unless the user asks otherwise.
- Default order_by for listings: "timestamp.desc".
- Output one JSON object, no markdown.

PLANNED_STEP_JSON:
{step_json}

STEP_INDEX: {step_index}

USER_QUERY:
{user_query}
"""


ORCHESTRATOR_SYSTEM_PROMPT = """You are the orchestrator for a Langfuse operations agent.

The user can ask ANYTHING about their Langfuse project. Your job is to determine what operation(s) to perform.

Available operations:
- "inspect_trace": Look at a specific trace in detail (need trace_id)
- "debug_trace": Debug/analyze a trace for failures (need trace_id)
- "search_traces": Search traces by name, user, session, tags, time range, etc.
- "explore_session": Get all traces belonging to a session and analyze them
- "list_sessions": List recent sessions
- "get_scores": Get scores/evaluations for traces
- "get_observations": Get observations (spans, generations) for a trace
- "compare_traces": Compare multiple traces side by side
- "get_metrics": Compute stats like token usage, latency, cost, error rates
- "browse_logs": General browsing - show latest traces, recent activity
- "get_prompts": List or retrieve prompts from Langfuse prompt management
- "get_datasets": List or retrieve datasets
- "general_answer": Answer a general question using fetched data

Return JSON ONLY with these keys:
- operations: array of operation objects, each with:
  - op: one of the operation names above
  - trace_id: string (if applicable)
  - session_id: string (if applicable)
  - search_params: object with optional keys (page, limit, user_id, name, session_id, from_timestamp, to_timestamp, order_by, tags)
  - prompt_name: string (if fetching a specific prompt)
  - dataset_name: string (if fetching a specific dataset)
  - score_params: object with optional keys (trace_id, name, source, limit)
  - max_traces: integer 1-10 (how many traces to fetch/analyze)
- user_intent: short phrase of what user really wants
- reasoning: short explanation of your plan

Rules:
- You can chain multiple operations if the user request needs it (e.g. search + analyze top results).
- Never set session_id or explore_session unless the user explicitly provided a session identifier in their message.
- If user input looks like a trace id (UUID or starts with trc_), use inspect_trace or debug_trace.
- If user says "debug" or "what went wrong", use debug_trace.
- If user says "show me", "list", "get logs", "recent", use browse_logs or search_traces.
- If the user explicitly names a Langfuse session id, use explore_session or list_sessions; otherwise prefer search_traces by name/tags.
- If user asks about "scores", "evaluations", "quality", use get_scores.
- If user asks about "tokens", "cost", "usage", "latency", "stats", use get_metrics.
- If user asks about "prompts", use get_prompts.
- If user asks about "datasets", use get_datasets.
- If user asks to "compare", use compare_traces.
- For search, default to order_by "timestamp.desc" and limit 15-25.
- Always return strict JSON."""


TRACE_ANALYZER_SYSTEM_PROMPT = """You are an expert AI trace analyzer.

Analyze the given LLM trace data and provide insights based on what you see.
Be accurate. Report what is actually in the data. Do not invent findings.

If there are errors, identify:
1. Where the failure occurred
2. Why it failed
3. Issue classification (prompt issue, tool misuse, missing context, model limitation, timeout, rate limit, etc.)
4. Concrete fixes

If the trace is healthy, report:
- What the trace does (workflow summary)
- Performance observations (latency, token usage)
- Any potential improvements

Return a JSON object with these keys:
- status: "error" | "warning" | "healthy"
- summary: string (1-3 sentence overview)
- failure_point: string (empty if healthy)
- root_cause: string (empty if healthy)
- issue_type: string (empty if healthy)
- fixes: array of strings (empty if healthy)
- performance: object with latency_assessment, token_efficiency, any observations
- improved_prompt: string (only if there's a prompt issue, else empty)
- workflow_steps: array of strings describing the trace flow"""


RESPONSE_SYSTEM_PROMPT = """You are the Langfuse agent's response layer.

Produce the final answer for the user based on the data gathered.

Rules:
- Be accurate and grounded in the actual data provided.
- Do NOT invent data, trace IDs, or metrics.
- Do NOT mention a chat or Langfuse session id unless the user explicitly wrote it in their request or it appears in the operation results as a filter you actually used. Never imply the user "provided" an id they did not type.
- Match your response style to the user's intent:
  * If they asked a question, answer it directly.
  * If they asked for logs, present them clearly.
  * If they asked for debugging, focus on root cause and fixes.
  * If they asked for stats, present numbers and patterns.
  * If they asked to compare, show differences.
  * If they browsed, give a summary with highlights.
- Use the natural format that best fits the content. Do not force a fixed structure.
- Include trace IDs, timestamps, and concrete values when relevant.
- If something wasn't found or data is empty, say so clearly and suggest next steps."""


class TraceDebuggerAIService(BaseAIService):
    def __init__(self):
        model = os.getenv("TRACE_DEBUGGER_MODEL", "").strip()
        super().__init__(
            default_model=model,
            default_temperature=0.2,
            default_max_tokens=4096,
            timeout=180,
            transport="httpx_sync",
            agent_name="Trace Debugger Agent",
        )

        provider = get_llm_provider()
        if provider == "local_llm":
            print("Langfuse agent - Using Local LLM service")
        elif provider == "ollama_cloud":
            print("Langfuse agent - Using Ollama Cloud")
        elif self._api_key() and self._endpoint_url():
            print("Langfuse agent - Using PwC GenAI service")
        else:
            print("Langfuse agent - PwC GenAI credentials not configured")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ValueError("LLM did not return a JSON object.")
        parsed = json.loads(match.group())
        if not isinstance(parsed, dict):
            raise ValueError("LLM JSON response must be an object.")
        return parsed

    def _call_llm_json(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.2) -> Dict[str, Any]:
        content = self.call_genai(prompt, temperature=temperature, max_tokens=max_tokens)
        return self._extract_json(content)

    def _call_llm_text(self, prompt: str, max_tokens: int = 4096, temperature: float = 0.2) -> str:
        return self.call_genai(prompt, temperature=temperature, max_tokens=max_tokens)

    def llm_activity_meta(self) -> Tuple[str, str]:
        """Provider id and model id for SSE thinking steps (llm_call / llm_response)."""
        return get_llm_provider(), self.default_model

    # ------------------------------------------------------------------
    # Stage 1–2: plan, then per-step Langfuse API payloads (parallel on caller)
    # ------------------------------------------------------------------

    def build_plan_prompt(self, user_query: str) -> str:
        """Full planner prompt (for SSE visibility)."""
        return f"{PLAN_SYSTEM_PROMPT}\n\nUSER_QUERY:\n{(user_query or '').strip()}\n"

    def plan_langfuse_workflow(self, user_query: str) -> Tuple[str, Dict[str, Any]]:
        """LLM stage 1: high-level steps (op + intent only). Returns (raw_text, parsed)."""
        prompt = self.build_plan_prompt(user_query)
        raw = self.call_genai(prompt, temperature=0.1, max_tokens=1536)
        try:
            parsed = self._extract_json(raw)
        except Exception:
            parsed = {
                "reasoning": "Planner JSON parse failed; using safe default.",
                "steps": [{"op": "browse_logs", "intent": "Recent Langfuse traces"}],
            }
        steps = parsed.get("steps")
        if not isinstance(steps, list) or not steps:
            parsed["steps"] = [{"op": "browse_logs", "intent": "Recent Langfuse traces"}]
        return raw, parsed

    def build_payload_prompt(self, user_query: str, planned_step: Dict[str, Any], step_index: int) -> str:
        step_json = json.dumps(planned_step, ensure_ascii=True, indent=2)
        return PAYLOAD_SYSTEM_PROMPT.format(
            step_json=step_json,
            step_index=int(step_index),
            user_query=(user_query or "").strip(),
        )

    def build_operation_payload(
        self, user_query: str, planned_step: Dict[str, Any], step_index: int
    ) -> Tuple[str, Dict[str, Any]]:
        """LLM stage 2: full operation spec for one planned step. Returns (raw_text, spec)."""
        prompt = self.build_payload_prompt(user_query, planned_step, step_index)
        raw = self.call_genai(prompt, temperature=0.1, max_tokens=2048)
        planned_op = (planned_step.get("op") or "").strip().lower() or "browse_logs"
        try:
            spec = self._extract_json(raw)
        except Exception:
            spec = {
                "op": planned_op,
                "search_params": {"limit": 20, "order_by": "timestamp.desc"},
            }
        if not isinstance(spec, dict):
            spec = {"op": planned_op, "search_params": {"limit": 20, "order_by": "timestamp.desc"}}
        spec["op"] = (spec.get("op") or planned_op).strip().lower()
        # Strip invented session_id unless user actually mentioned it
        if not user_message_mentions_langfuse_session(user_query):
            spec.pop("session_id", None)
            sp = spec.get("search_params")
            if isinstance(sp, dict) and "session_id" in sp:
                sp.pop("session_id", None)
        return raw, spec

    # ------------------------------------------------------------------
    # Orchestrator: decides what operations to run
    # ------------------------------------------------------------------

    def orchestrate(self, user_query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        # App chat session_id is intentionally NOT passed to Langfuse planning.
        _ = session_id
        prompt = (
            f"{ORCHESTRATOR_SYSTEM_PROMPT}\n\n"
            f"USER_QUERY: {user_query}\n"
        )
        result = self._call_llm_json(prompt=prompt, max_tokens=2048, temperature=0.1)
        operations = result.get("operations") or []
        if not isinstance(operations, list):
            operations = [operations] if isinstance(operations, dict) else []
        return {
            "operations": operations,
            "user_intent": str(result.get("user_intent") or ""),
            "reasoning": str(result.get("reasoning") or ""),
        }

    # ------------------------------------------------------------------
    # Trace analysis (debug or inspect)
    # ------------------------------------------------------------------

    def analyze_trace(self, normalized_trace: Dict[str, Any], mode: str = "debug") -> Dict[str, Any]:
        if mode == "debug":
            instruction = (
                "Focus on finding problems, errors, and failures. "
                "Provide root cause analysis and concrete fixes."
            )
        else:
            instruction = (
                "Provide a comprehensive overview of this trace: what it does, "
                "how it performed, and any observations."
            )

        prompt = (
            f"{TRACE_ANALYZER_SYSTEM_PROMPT}\n\n"
            f"MODE: {mode}\n"
            f"INSTRUCTION: {instruction}\n\n"
            "Return ONLY a valid JSON object.\n\n"
            f"TRACE DATA:\n{json.dumps(normalized_trace, ensure_ascii=True, indent=2)}"
        )
        result = self._call_llm_json(prompt=prompt, max_tokens=4096, temperature=0.2)
        return result

    # ------------------------------------------------------------------
    # Final response formatting
    # ------------------------------------------------------------------

    def build_format_response_prompt(
        self,
        user_query: str,
        operation_results: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> str:
        return (
            f"{RESPONSE_SYSTEM_PROMPT}\n\n"
            f"USER REQUEST:\n{user_query}\n\n"
            f"OPERATION RESULTS:\n{json.dumps(operation_results, ensure_ascii=True, indent=2)}\n\n"
            f"CONTEXT:\n{json.dumps(context, ensure_ascii=True, indent=2)}\n\n"
            "Now produce the final response for the user."
        )

    def summarize_langfuse_results(
        self,
        user_query: str,
        operation_results: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> Tuple[str, str]:
        """Returns (prompt, answer) for SSE visibility without double LLM calls."""
        prompt = self.build_format_response_prompt(user_query, operation_results, context)
        text = self._call_llm_text(prompt=prompt, max_tokens=6144, temperature=0.2)
        return prompt, text

    def format_response(
        self,
        user_query: str,
        operation_results: List[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> str:
        _, text = self.summarize_langfuse_results(user_query, operation_results, context)
        return text

    # ------------------------------------------------------------------
    # Backward compat aliases
    # ------------------------------------------------------------------

    def orchestrate_user_request(self, user_query: str, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Legacy compat: maps old orchestrate call to new format, returns old-style plan."""
        result = self.orchestrate(user_query, session_id)
        ops = result.get("operations") or []
        first_op = ops[0] if ops else {}
        return {
            "mode": first_op.get("op", "search_and_analyze"),
            "trace_id": first_op.get("trace_id", ""),
            "search_params": first_op.get("search_params", {}),
            "user_need": result.get("user_intent", ""),
            "reasoning": result.get("reasoning", ""),
            "should_analyze_multiple": len(ops) > 1 or first_op.get("max_traces", 1) > 1,
            "max_traces_to_analyze": first_op.get("max_traces", 1),
        }

    def summarize_for_user(self, user_query: str, selected_traces: list, analyses: list, normalized_context: dict) -> str:
        """Legacy compat."""
        return self.format_response(
            user_query=user_query,
            operation_results=[{"traces": selected_traces, "analyses": analyses}],
            context=normalized_context,
        )


trace_debugger_ai_service = TraceDebuggerAIService()
