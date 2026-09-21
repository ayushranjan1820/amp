"""AI ETL Agent — LLM-orchestrated data transformation pipeline.

End-to-end flow:
1. Input Layer        — Schema + sample extraction (never send full data to LLM)
2. Planner Agent      — Convert user request → structured transformation plan
3. Tool Decision      — Route to SQL / Pandas / Direct LLM
4. Code Generation    — Generate safe, optimized Pandas code
5. Execution Engine   — Sandboxed execution on full dataset
6. Critic / Validator — Self-healing retry loop on failure
7. Memory & State     — Track steps, intermediates, errors per session
8. Schema Enforcement — Validate output matches expected structure
9. Aggregator         — Format result as table + human-readable explanation
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from .ai_service import ai_service
from .models import ThinkingStep
from .tools.code_generator import (
    build_code_generation_prompt,
    extract_code_block,
    validate_generated_code,
)
from .tools.sandbox_executor import ExecutionResult, execute_in_sandbox
from .tools.db_introspection import (
    ENV_DEST_DB,
    ENV_SOURCE_DB,
    build_erd_text,
    connection_fingerprint,
    create_engine_from_uri,
    load_dataframe,
    max_extract_rows,
    read_dataframe,
    validate_read_only_select,
)
from .tools.schema_extractor import (
    extract_schema_and_sample,
    parse_inline_data,
    schema_to_text,
)
from .tools.validator import (
    ValidationResult,
    build_critic_prompt,
    looks_like_information_schema_tables_output,
    validate_execution_result,
    _MAX_RETRIES,
)

logger = logging.getLogger(__name__)

_MAX_PREVIEW_ROWS = 100
_LARGE_ROW_COUNT = 100
_LARGE_CELL_COUNT = 5000
_MAX_JSON_CHARS_FOR_LLM = 200_000


def _add_thinking(
    thinking: List[ThinkingStep],
    step: ThinkingStep,
    on_step: Optional[Callable[[ThinkingStep], None]],
) -> None:
    thinking.append(step)
    if on_step:
        on_step(step)


def _strip_hallucinated_expected_schema(plan: Dict[str, Any], input_columns: List[Any]) -> None:
    """Clear expected_output_schema when planner invented columns not present in extracted df."""
    exp = plan.get("expected_output_schema")
    if not exp or not isinstance(exp, dict):
        return
    ec = exp.get("columns")
    if not isinstance(ec, list) or not ec:
        return
    inp_lower = {str(c).lower() for c in input_columns}
    if not inp_lower:
        return
    if not any(str(c).lower() in inp_lower for c in ec):
        plan["expected_output_schema"] = None


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Extract JSON object from LLM output that may include markdown fences."""
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Model did not return a JSON object.")
    return json.loads(raw[start : end + 1])


def _config_errors() -> List[str]:
    errs: List[str] = []
    if not (os.getenv("PWC_GENAI_API_KEY") or "").strip():
        errs.append("PWC_GENAI_API_KEY is missing. Required for ETL planning and code generation.")
    if not (os.getenv("PWC_GENAI_BEARER_TOKEN") or "").strip():
        errs.append("PWC_GENAI_BEARER_TOKEN is missing. Required for PwC GenAI authentication.")
    if not (os.getenv(ENV_SOURCE_DB) or "").strip():
        errs.append(
            f"{ENV_SOURCE_DB} is missing. Configure the source database connection string "
            "(catalog / user settings) so the agent can introspect the schema and extract data."
        )
    return errs


def _format_result_markdown(df: pd.DataFrame, max_rows: int = _MAX_PREVIEW_ROWS) -> str:
    """Render DataFrame as markdown table."""
    if df.empty:
        return "_No rows in result._"
    cols = list(df.columns)
    head = "| " + " | ".join(str(c) for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [head, sep]
    for _, row in df.head(max_rows).iterrows():
        cells = [
            "" if pd.isna(v) else str(v).replace("|", "\\|")
            for v in row
        ]
        lines.append("| " + " | ".join(cells) + " |")
    if len(df) > max_rows:
        lines.append(f"\n_Showing {max_rows} of {len(df)} rows._")
    return "\n".join(lines)


def _result_is_large(df: pd.DataFrame) -> bool:
    if len(df) >= _LARGE_ROW_COUNT:
        return True
    if len(df.columns) * len(df) >= _LARGE_CELL_COUNT:
        return True
    return False


class ETLAgent:
    """AI ETL Agent — orchestrates the full transformation pipeline."""

    def __init__(self):
        # Layer 7: Memory & State per session
        self._session_state: Dict[str, Dict[str, Any]] = {}
        # In-memory DataFrame store (keyed by data_id)
        self._dataframes: Dict[str, pd.DataFrame] = {}
        self._df_counter = 0
        print("AI ETL Agent initialized")

    def _state(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self._session_state:
            self._session_state[session_id] = {
                "history": [],
                "steps_log": [],
                "current_df_id": None,
                "retry_count": 0,
            }
        return self._session_state[session_id]

    def _store_df(self, df: pd.DataFrame, session_id: str) -> str:
        """Store a DataFrame and return its ID."""
        self._df_counter += 1
        df_id = f"df_{session_id}_{self._df_counter}"
        self._dataframes[df_id] = df
        return df_id

    def _get_df(self, df_id: str) -> Optional[pd.DataFrame]:
        return self._dataframes.get(df_id)

    def _log_step(self, session_id: str, step: Dict[str, Any]):
        """Layer 7: Memory — log a pipeline step for traceability."""
        state = self._state(session_id)
        state["steps_log"].append({
            **step,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def _compose_data_context_for_llm(self, db_memory: str, schema_text: str) -> str:
        """Planner / codegen / critic context: ERD memory plus current working DataFrame digest."""
        return (
            f"{db_memory}\n\n---\n\n"
            f"CURRENT WORKING DATASET (pandas DataFrame `df`):\n{schema_text}"
        )

    def _ensure_erd_in_session(
        self,
        session_id: str,
        source_engine,
        dest_engine: Optional[Any],
        source_uri: str,
        dest_uri: str,
    ) -> Tuple[str, str]:
        """Cache or rebuild source/destination ERD text in session memory."""
        state = self._state(session_id)
        fp_src = connection_fingerprint(source_uri)
        fp_dst = connection_fingerprint(dest_uri) if dest_uri.strip() else ""
        cache = state.get("db_erd_cache") or {}
        if (
            cache.get("fp_src") == fp_src
            and cache.get("fp_dst") == fp_dst
            and cache.get("source_erd")
        ):
            return cache["source_erd"], cache.get("dest_erd") or ""

        self._log_step(session_id, {"step": "erd_introspection_start", "fp_src": fp_src})
        source_erd = build_erd_text(source_engine, "Source database")
        dest_erd = ""
        if dest_engine is not None:
            dest_erd = build_erd_text(dest_engine, "Destination database")
        state["db_erd_cache"] = {
            "fp_src": fp_src,
            "fp_dst": fp_dst,
            "source_erd": source_erd,
            "dest_erd": dest_erd,
        }
        self._log_step(session_id, {
            "step": "erd_introspection_done",
            "source_erd_chars": len(source_erd),
            "dest_erd_chars": len(dest_erd),
        })
        return source_erd, dest_erd

    def _build_db_memory_block(self, source_erd: str, dest_erd: str, has_destination: bool) -> str:
        lines = [
            "## Database catalog (agent memory — use for SQL extract & load targets)",
            f"**Source** (`{ENV_SOURCE_DB}` is configured.)",
            source_erd,
        ]
        if has_destination and dest_erd:
            lines.extend([
                "",
                f"**Destination** (`{ENV_DEST_DB}` is configured.)",
                dest_erd,
            ])
        else:
            lines.extend(["", "**Destination**: not configured — do not assume a load target exists."])
        return "\n".join(lines)

    def _llm_extract_sql(
        self,
        query: str,
        source_erd: str,
        history: str,
        max_rows: int,
    ) -> str:
        prompt = f"""You write ONE read-only SQL query against the SOURCE database described below.
Use only tables and columns that appear in the schema. Prefer explicit column lists when reasonable.

{source_erd}

USER REQUEST (what to pull into pandas `df` for further transformation):
{query}

CONVERSATION CONTEXT:
{history if history else "(none)"}

Rules:
- Output a single SELECT or WITH ... SELECT. No DDL/DML. No multiple statements.
- Do not use semicolons. Do not add comments.
- If the user asks for **rows from a named table**, SELECT columns **from that table** (e.g. `SELECT * FROM public.admin_users`). Do **NOT** use `information_schema.tables`, `information_schema.columns`, `pg_catalog`, `sqlite_master`, or other catalog/system views to answer table data requests — those return metadata (table_schema, table_name, table_type), not row data.
- If the schema lists a table as schema.table (e.g. auth.admin_users), use that full qualification in FROM/JOIN — do not assume public or dbo only.
- Cap rows: end with LIMIT {max_rows} unless you already use TOP, FETCH FIRST, or LIMIT with a numeric bound ≤ {max_rows}.
- Output ONLY the SQL text. No markdown fences, no explanation."""
        raw = ai_service.call_genai(prompt, temperature=0.05, max_tokens=4096)
        sql = extract_code_block(raw) if "```" in raw else raw.strip()
        sql = sql.strip()
        normalized, err = validate_read_only_select(sql)
        if err:
            fix_prompt = f"""The SQL you generated failed validation: {err}
Fix it. Same rules as before.

{source_erd}

USER REQUEST:
{query}

INVALID SQL:
{sql}

Return ONLY the corrected SQL text."""
            raw2 = ai_service.call_genai(fix_prompt, temperature=0.02, max_tokens=4096)
            sql2 = extract_code_block(raw2) if "```" in raw2 else raw2.strip()
            normalized, err = validate_read_only_select(sql2.strip())
            if err:
                raise ValueError(f"Could not produce valid read-only SQL: {err}")
            sql = normalized
        else:
            sql = normalized
        return sql

    def _llm_load_plan(
        self,
        query: str,
        dest_erd: str,
        result_columns: List[str],
    ) -> Dict[str, Any]:
        prompt = f"""The ETL pipeline produced a transformed pandas DataFrame. Decide if it should be loaded into the DESTINATION database.

DESTINATION SCHEMA:
{dest_erd}

USER REQUEST (original):
{query}

RESULT COLUMN NAMES:
{result_columns}

Return a single JSON object only (no markdown):
{{
  "perform_load": boolean,
  "table": string or null — destination table name (unquoted),
  "schema": string or null — optional database schema name, or null for default,
  "if_exists": "append" | "replace" | "fail",
  "reason": short string
}}

Rules:
- Set perform_load true only if the user explicitly wants data written/persisted/loaded/saved into the destination database.
- If perform_load is true, table must match an existing table in the destination schema when the user names one; otherwise choose a sensible new table name (letters, digits, underscores).
- if_exists: use "append" unless the user asked to overwrite/replace/truncate the target."""
        raw = ai_service.call_genai(prompt, temperature=0.05, max_tokens=1024)
        return _extract_json_object(raw)

    # ── Layer 2: Planner Agent ──────────────────────────────────────

    def _build_plan_prompt(self, query: str, schema_text: str, history: str) -> str:
        return f"""You are a Planner Agent for an AI ETL pipeline. Convert the user's data transformation request into a structured plan.

CONVERSATION CONTEXT:
{history if history else "(none)"}

DATASET SCHEMA:
{schema_text}

USER REQUEST:
{query}

Return a single JSON object with these keys:
- "plan_summary": string — brief summary of what needs to be done
- "steps": array of objects, each with:
    - "operation": string — one of: "filter", "group_by", "aggregate", "sort", "limit", "join", "pivot", "unpivot", "rename", "cast", "fill_null", "drop_column", "add_column", "merge", "deduplicate", "custom"
    - "description": string — what this step does
    - "columns": array of column names involved (can be empty for custom)
- "tool_decision": string — one of: "pandas" (complex transforms), "sql" (simple aggregation/filter), "llm_direct" (lightweight text logic, no code needed)
- "expected_output_schema": object or null — ONLY when the output columns are fully determined by the plan (aggregations with new names, explicit renames, joins with a fixed column list). For requests like "fetch/load all rows from table X" or "show everything from …", set this to **null** (output columns are exactly whatever the extract placed in `df`).
- "needs_clarification": boolean
- "clarification_message": string or null

Rules:
1. Always plan before code generation.
2. Prefer "pandas" for complex multi-step transforms.
3. Use "sql" only for simple SELECT/GROUP BY/WHERE that can be expressed in one statement.
4. Use "llm_direct" only for simple questions about the data that don't need code (e.g. "what columns are there?").
5. If the request is ambiguous, set needs_clarification=true with a helpful message.
6. The context may include source/destination database ERDs; data is already in DataFrame `df` after extract. Do not assume sandbox code can open DB connections. Loading to a destination is handled by the system after transform when the user asks.
7. Never invent expected_output_schema column names (e.g. id, username) that are **not** listed in the DATASET SCHEMA for `df` unless your steps explicitly create them.
8. Output ONLY valid JSON. No markdown fences.
"""

    def _llm_plan(self, query: str, schema_text: str, history: str) -> Dict[str, Any]:
        prompt = self._build_plan_prompt(query, schema_text, history)
        raw = ai_service.call_genai(prompt, temperature=0.05, max_tokens=4096)
        obj = _extract_json_object(raw)
        # Normalize
        obj.setdefault("steps", [])
        obj.setdefault("tool_decision", "pandas")
        obj.setdefault("needs_clarification", False)
        obj.setdefault("expected_output_schema", None)
        obj.setdefault("plan_summary", "")
        return obj

    # ── Layer 4: Code Generation ────────────────────────────────────

    def _generate_code(
        self,
        query: str,
        schema_text: str,
        plan: Dict[str, Any],
    ) -> str:
        tool_decision = plan.get("tool_decision", "pandas")
        prompt = build_code_generation_prompt(query, schema_text, plan, tool_decision)
        raw = ai_service.call_genai(prompt, temperature=0.1, max_tokens=4096)
        return extract_code_block(raw)

    # ── Layer 9: Aggregator / Formatter ─────────────────────────────

    def _format_response(
        self,
        query: str,
        plan: Dict[str, Any],
        result_df: pd.DataFrame,
        exec_stats: Dict[str, Any],
        code: Optional[str],
        large: bool,
    ) -> str:
        if large:
            # Large result — skip LLM formatting, return table directly
            parts = ["### ETL Results\n\n"]
            parts.append(f"_Transformation complete: {len(result_df)} rows, {len(result_df.columns)} columns._\n\n")
            parts.append(_format_result_markdown(result_df))
            if code:
                parts.append(f"\n\n### Generated Code\n```python\n{code}\n```")
            parts.append(f"\n\n_Execution time: {exec_stats.get('execution_time_ms', 0):.0f}ms_")
            return "".join(parts)

        # Small result — use LLM for natural explanation
        preview = result_df.head(50).to_dict(orient="records")
        preview_json = json.dumps(preview, default=str)
        if len(preview_json) > _MAX_JSON_CHARS_FOR_LLM:
            preview_json = json.dumps(
                {"row_count": len(result_df), "columns": list(result_df.columns)},
                default=str,
            )

        fmt_prompt = f"""User asked:
{query}

Plan summary:
{plan.get("plan_summary", "")}

Execution stats:
- Rows produced: {len(result_df)}
- Columns: {list(result_df.columns)}
- Execution time: {exec_stats.get("execution_time_ms", 0):.0f}ms

Result data (JSON):
{preview_json}

Write a short markdown answer:
- What transformation was applied
- Key insights from the result
- Row/column counts

Do not reproduce the full table — a table is added by the system after your text.
Keep it concise (3-5 sentences max)."""

        try:
            narrative = ai_service.call_genai(fmt_prompt, temperature=0.15, max_tokens=2048)
        except Exception as e:
            narrative = f"Transformation completed successfully ({len(result_df)} rows). Interpretation unavailable: {e}\n"

        narrative += "\n\n### Results\n\n"
        narrative += _format_result_markdown(result_df)
        if code:
            narrative += f"\n\n### Generated Code\n```python\n{code}\n```"
        narrative += f"\n\n_Execution time: {exec_stats.get('execution_time_ms', 0):.0f}ms_"
        return narrative

    # ── Layer 3: Tool Decision + Direct LLM Handler ─────────────────

    def _handle_llm_direct(
        self,
        query: str,
        schema_text: str,
        plan: Dict[str, Any],
    ) -> str:
        """Handle requests that don't need code execution (schema questions, etc.)."""
        prompt = f"""You are a data analyst assistant. Answer the user's question about their dataset.

DATASET SCHEMA:
{schema_text}

PLAN:
{plan.get("plan_summary", "")}

USER QUESTION:
{query}

Provide a clear, concise markdown answer based on the schema and sample data.
"""
        return ai_service.call_genai(prompt, temperature=0.2, max_tokens=2048)

    # ── Main Pipeline Orchestrator ──────────────────────────────────

    def process_chat(
        self,
        request_data: Dict[str, Any],
        on_thinking_step: Optional[Callable[[ThinkingStep], None]] = None,
    ) -> Dict[str, Any]:
        """End-to-end ETL pipeline: connect DBs → ERD memory → extract → plan → code → sandbox → optional load."""
        thinking: List[ThinkingStep] = []
        session_id = request_data.get("session_id") or f"etl-{os.urandom(4).hex()}"
        query = (request_data.get("query") or request_data.get("message") or "").strip()
        clear_history = bool(request_data.get("clear_history", False))
        data_source = request_data.get("data_source")
        data_format = request_data.get("data_format")
        now = datetime.utcnow().isoformat()

        if clear_history:
            self._session_state.pop(session_id, None)

        errs = _config_errors()
        if errs:
            return {
                "success": False,
                "response": "**Configuration incomplete**\n\n" + "\n".join(f"- {e}" for e in errs),
                "query": query,
                "thinking_steps": thinking,
                "timestamp": now,
            }

        state = self._state(session_id)
        hist = state["history"]
        hist_ctx = ""
        if hist:
            parts = []
            for turn in hist[-4:]:
                parts.append(f"{turn['role'].upper()}: {turn['content'][:1200]}")
            hist_ctx = "\n".join(parts)

        source_uri = (os.getenv(ENV_SOURCE_DB) or "").strip()
        dest_uri = (os.getenv(ENV_DEST_DB) or "").strip()

        source_engine = None
        dest_engine = None
        try:
            try:
                source_engine = create_engine_from_uri(source_uri)
            except Exception as e:
                return {
                    "success": False,
                    "response": (
                        f"**Source database connection failed**\n\n{e}\n\n"
                        f"Verify `{ENV_SOURCE_DB}` (driver in the URL, network, credentials)."
                    ),
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": now,
                }
            if dest_uri:
                try:
                    dest_engine = create_engine_from_uri(dest_uri)
                except Exception as e:
                    return {
                        "success": False,
                        "response": (
                            f"**Destination database connection failed**\n\n{e}\n\n"
                            f"Verify `{ENV_DEST_DB}` or remove it if you only need the source."
                        ),
                        "query": query,
                        "thinking_steps": thinking,
                        "timestamp": now,
                    }

            return self._run_etl_with_engines(
                query=query,
                data_source=data_source,
                data_format=data_format,
                thinking=thinking,
                session_id=session_id,
                state=state,
                hist=hist,
                hist_ctx=hist_ctx,
                now=now,
                source_engine=source_engine,
                dest_engine=dest_engine,
                source_uri=source_uri,
                dest_uri=dest_uri,
                on_thinking_step=on_thinking_step,
            )
        finally:
            if source_engine is not None:
                source_engine.dispose()
            if dest_engine is not None:
                dest_engine.dispose()

    def _run_etl_with_engines(
        self,
        *,
        query: str,
        data_source: Any,
        data_format: Any,
        thinking: List[ThinkingStep],
        session_id: str,
        state: Dict[str, Any],
        hist: List[Dict[str, str]],
        hist_ctx: str,
        now: str,
        source_engine: Any,
        dest_engine: Optional[Any],
        source_uri: str,
        dest_uri: str,
        on_thinking_step: Optional[Callable[[ThinkingStep], None]] = None,
    ) -> Dict[str, Any]:
        """Pipeline after successful DB engine creation (extract → plan → code → sandbox → optional load)."""
        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content="Discovering database schemas (tables, columns, relationships)...",
                tool_name="db_introspection",
            ),
            on_thinking_step,
        )
        source_erd, dest_erd = self._ensure_erd_in_session(
            session_id, source_engine, dest_engine, source_uri, dest_uri
        )
        has_destination = dest_engine is not None
        db_memory = self._build_db_memory_block(source_erd, dest_erd, has_destination)

        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content="Connected to source database; ERD is in session memory for this run.",
                tool_name="db_introspection",
            ),
            on_thinking_step,
        )
        if dest_engine is not None:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content="Connected to destination database; ERD is in session memory for this run.",
                    tool_name="db_introspection",
                ),
                on_thinking_step,
            )

        destination_load_info: Optional[Dict[str, Any]] = None

        # ── Layer 1: Input — Load / parse data ──
        df: Optional[pd.DataFrame] = None

        if state.get("current_df_id"):
            df = self._get_df(state["current_df_id"])

        if data_source:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool", content="Parsing input data...", tool_name="schema_extractor"
                ),
                on_thinking_step,
            )
            try:
                df = parse_inline_data(data_source, data_format)
                df_id = self._store_df(df, session_id)
                state["current_df_id"] = df_id
                self._log_step(session_id, {
                    "step": "data_load",
                    "rows": len(df),
                    "cols": len(df.columns),
                })
            except Exception as e:
                return {
                    "success": False,
                    "response": f"**Failed to parse input data**\n\n{e}\n\nSupported formats: CSV, JSON, TSV.",
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": now,
                }

        if not query:
            _add_thinking(
                thinking,
                ThinkingStep(type="tool", content="Empty user message.", tool_name="llm"),
                on_thinking_step,
            )
            if df is not None:
                schema = extract_schema_and_sample(df)
                schema_text = schema_to_text(schema)
                intro = (
                    f"Data loaded successfully!\n\n{db_memory}\n\n{schema_text}\n\n"
                    "What transformation would you like to perform?"
                )
                return {
                    "success": True,
                    "response": intro,
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": now,
                    "output_schema": {
                        "columns": [c["name"] for c in schema["columns"]],
                        "types": [c["dtype"] for c in schema["columns"]],
                    },
                }
            intro = (
                f"{db_memory}\n\n"
                "Describe what to **extract** from the source (tables, filters, joins) and how to **transform** it. "
                "You can also paste CSV/JSON as inline data for one-off runs. "
                "If a destination database is configured, say when you want results **loaded** into a table."
            )
            return {
                "success": True,
                "response": intro,
                "query": query,
                "thinking_steps": thinking,
                "timestamp": now,
            }

        if df is None:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content="Checking if query contains inline data...",
                    tool_name="schema_extractor",
                ),
                on_thinking_step,
            )
            try:
                df = self._try_extract_data_from_query(query)
                if df is not None:
                    df_id = self._store_df(df, session_id)
                    state["current_df_id"] = df_id
                    self._log_step(session_id, {
                        "step": "data_extract_from_query",
                        "rows": len(df),
                        "cols": len(df.columns),
                    })
            except Exception:
                pass

        if df is None:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content="Generating read-only SQL to extract from the source database...",
                    tool_name="db_introspection",
                ),
                on_thinking_step,
            )
            max_rows = max_extract_rows()
            try:
                sql = ""
                df = None
                for extract_attempt in range(2):
                    sql = self._llm_extract_sql(
                        query if extract_attempt == 0 else (
                            f"{query}\n\n"
                            "CRITICAL: The previous SELECT returned **catalog metadata** "
                            "(columns like table_schema, table_name, table_type from information_schema). "
                            "Regenerate SQL to read **row data** from the application table the user named, "
                            "using the qualified table name from the DATABASE SCHEMA above (e.g. "
                            "`SELECT * FROM schema.admin_users`), not information_schema or pg_catalog."
                        ),
                        source_erd,
                        hist_ctx,
                        max_rows,
                    )
                    _add_thinking(
                        thinking,
                        ThinkingStep(
                            type="tool",
                            content="SQL ready — executing read-only extract against the source database...",
                            tool_name="db_introspection",
                        ),
                        on_thinking_step,
                    )
                    df = read_dataframe(source_engine, sql, max_rows)
                    if not looks_like_information_schema_tables_output(df):
                        break
                    if extract_attempt == 0:
                        _add_thinking(
                            thinking,
                            ThinkingStep(
                                type="tool",
                                content="Extract looked like information_schema metadata — regenerating SQL to read the real table...",
                                tool_name="db_introspection",
                            ),
                            on_thinking_step,
                        )

                if looks_like_information_schema_tables_output(df):
                    return {
                        "success": False,
                        "response": (
                            "**Extract returned catalog metadata, not table rows**\n\n"
                            "The generated SQL queried system catalogs (e.g. `information_schema.tables`), "
                            "which only describe table names — not the columns inside `admin_users`.\n\n"
                            "Ask explicitly for row data, for example: "
                            "`SELECT * FROM public.admin_users LIMIT 1000` "
                            "(use the **schema.table** name shown in the agent’s database schema if it differs from `public`)."
                        ),
                        "query": query,
                        "thinking_steps": thinking,
                        "timestamp": now,
                        "generated_code": None,
                    }

                df_id = self._store_df(df, session_id)
                state["current_df_id"] = df_id
                self._log_step(session_id, {
                    "step": "sql_extract",
                    "rows": len(df),
                    "cols": len(df.columns),
                    "sql": sql[:2000],
                })
                _add_thinking(
                    thinking,
                    ThinkingStep(
                        type="tool",
                        content=f"Extracted {len(df)} rows from source via SQL.",
                        tool_name="db_introspection",
                    ),
                    on_thinking_step,
                )
            except Exception as e:
                traceback.print_exc()
                return {
                    "success": False,
                    "response": (
                        f"**Could not extract data from the source database**\n\n{e}\n\n"
                        "Name the table(s) and filters clearly, or paste CSV/JSON as inline data. "
                        "Example: `Select * from orders where order_date >= '2024-01-01' limit 1000`."
                    ),
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": now,
                }

        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content=f"Extracting schema from {len(df)} rows, {len(df.columns)} columns.",
                tool_name="schema_extractor",
            ),
            on_thinking_step,
        )
        schema = extract_schema_and_sample(df)
        schema_text = schema_to_text(schema)
        llm_context = self._compose_data_context_for_llm(db_memory, schema_text)

        # ── Layer 2: Planner Agent ──
        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content="LLM planner: analyzing request and building transformation plan.",
                tool_name="planner",
            ),
            on_thinking_step,
        )
        try:
            plan = self._llm_plan(query, llm_context, hist_ctx)
        except Exception as e:
            traceback.print_exc()
            return {
                "success": False,
                "response": f"**Planning failed** (could not parse model output): {e}",
                "query": query,
                "thinking_steps": thinking,
                "timestamp": now,
            }

        _strip_hallucinated_expected_schema(plan, list(df.columns))

        self._log_step(session_id, {
            "step": "planning",
            "plan": plan,
        })

        # Handle clarification
        if plan.get("needs_clarification"):
            msg = plan.get("clarification_message") or plan.get("plan_summary") or "Could you clarify your transformation request?"
            hist.append({"role": "user", "content": query})
            hist.append({"role": "assistant", "content": msg[:8000]})
            if len(hist) > 20:
                del hist[:-20]
            return {
                "success": True,
                "response": msg,
                "query": query,
                "thinking_steps": thinking,
                "timestamp": now,
            }

        _add_thinking(
            thinking,
            ThinkingStep(
                type="thinking",
                content=f"Plan: {plan.get('plan_summary', 'N/A')} | Tool: {plan.get('tool_decision', 'pandas')} | Steps: {len(plan.get('steps', []))}",
            ),
            on_thinking_step,
        )

        # ── Layer 3: Tool Decision ──
        tool_decision = plan.get("tool_decision", "pandas")

        if tool_decision == "llm_direct":
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content="Direct LLM response (no code execution needed).",
                    tool_name="llm_direct",
                ),
                on_thinking_step,
            )
            response = self._handle_llm_direct(query, llm_context, plan)
            hist.append({"role": "user", "content": query})
            hist.append({"role": "assistant", "content": response[:8000]})
            if len(hist) > 20:
                del hist[:-20]
            return {
                "success": True,
                "response": response,
                "query": query,
                "thinking_steps": thinking,
                "timestamp": now,
            }

        # ── Layer 4: Code Generation ──
        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content="Generating transformation code...",
                tool_name="code_generator",
            ),
            on_thinking_step,
        )

        code = self._generate_code(query, llm_context, plan)

        self._log_step(session_id, {
            "step": "code_generation",
            "code": code,
            "tool": tool_decision,
        })

        # Static validation of generated code
        static_errors = validate_generated_code(code)
        if static_errors:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content=f"Static validation failed: {'; '.join(static_errors)}. Requesting fix...",
                    tool_name="critic",
                ),
                on_thinking_step,
            )
            # Self-heal: ask LLM to fix
            code = self._self_heal_code(
                query,
                llm_context,
                code,
                "; ".join(static_errors),
                thinking,
                session_id,
                on_thinking_step=on_thinking_step,
            )
            if code is None:
                return {
                    "success": False,
                    "response": (
                        "**Code generation failed** after validation.\n\n"
                        f"Errors: {'; '.join(static_errors)}\n\n"
                        "Try rephrasing your request or simplifying the transformation."
                    ),
                    "query": query,
                    "thinking_steps": thinking,
                    "timestamp": now,
                }

        # ── Layer 5: Sandboxed Execution ──
        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content=f"Executing code in sandbox on {len(df)} rows...",
                tool_name="sandbox_executor",
            ),
            on_thinking_step,
        )

        exec_result = execute_in_sandbox(code, df)

        # ── Layer 6: Critic / Validation + Self-Healing Loop ──
        attempt = 0
        while not exec_result.success and attempt < _MAX_RETRIES:
            attempt += 1
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content=f"Execution failed (attempt {attempt}). Critic agent fixing...",
                    tool_name="critic",
                ),
                on_thinking_step,
            )
            self._log_step(session_id, {
                "step": "execution_error",
                "attempt": attempt,
                "error": exec_result.error,
            })

            fixed_code = self._self_heal_code(
                query,
                llm_context,
                code,
                exec_result.error or "Unknown error",
                thinking,
                session_id,
                attempt=attempt,
                on_thinking_step=on_thinking_step,
            )
            if fixed_code is None:
                break
            code = fixed_code
            exec_result = execute_in_sandbox(code, df)

        if not exec_result.success:
            self._log_step(session_id, {
                "step": "execution_failed_final",
                "error": exec_result.error,
            })
            return {
                "success": False,
                "response": (
                    f"**Transformation failed** after {attempt + 1} attempt(s).\n\n"
                    f"Error:\n```\n{exec_result.error}\n```\n\n"
                    f"### Generated Code\n```python\n{code}\n```\n\n"
                    "Try simplifying your request or providing cleaner data."
                ),
                "query": query,
                "thinking_steps": thinking,
                "timestamp": now,
                "generated_code": code,
                "execution_stats": exec_result.to_dict(),
            }

        result_df = exec_result.result_df

        # ── Layer 8: Output Schema Enforcement ──
        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content="Validating output schema and data quality...",
                tool_name="validator",
            ),
            on_thinking_step,
        )
        expected_schema = plan.get("expected_output_schema")
        validation = validate_execution_result(result_df, df, expected_schema)

        self._log_step(session_id, {
            "step": "validation",
            "valid": validation.valid,
            "errors": validation.errors,
            "warnings": validation.warnings,
        })

        if not validation.valid:
            # One more self-heal attempt for validation failures
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content=f"Validation failed: {'; '.join(validation.errors)}. Attempting fix...",
                    tool_name="critic",
                ),
                on_thinking_step,
            )
            error_msg = (
                f"Validation errors: {'; '.join(validation.errors)}. "
                f"The code ran but produced invalid output."
            )
            fixed_code = self._self_heal_code(
                query,
                llm_context,
                code,
                error_msg,
                thinking,
                session_id,
                on_thinking_step=on_thinking_step,
            )
            if fixed_code:
                code = fixed_code
                exec_result = execute_in_sandbox(code, df)
                if exec_result.success:
                    result_df = exec_result.result_df
                    validation = validate_execution_result(result_df, df, expected_schema)

        # Store the result DataFrame for follow-up queries
        result_df_id = self._store_df(result_df, session_id)
        state["current_df_id"] = result_df_id

        exec_stats = exec_result.to_dict()

        # ── Layer 9: Aggregator / Formatter ──
        _add_thinking(
            thinking,
            ThinkingStep(
                type="tool",
                content="Formatting results...",
                tool_name="aggregator",
            ),
            on_thinking_step,
        )

        large = _result_is_large(result_df)
        response = self._format_response(query, plan, result_df, exec_stats, code, large)

        # Add validation warnings to response
        if validation.warnings:
            response += "\n\n### Warnings\n"
            for w in validation.warnings:
                response += f"- {w}\n"

        if dest_engine is not None:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content="Checking whether to load transformed data into the destination database...",
                    tool_name="db_introspection",
                ),
                on_thinking_step,
            )
            try:
                load_plan = self._llm_load_plan(query, dest_erd, list(result_df.columns))
                perform = load_plan.get("perform_load")
                if isinstance(perform, str):
                    perform = perform.strip().lower() in ("true", "1", "yes")
                if perform:
                    table = (load_plan.get("table") or "").strip()
                    if_exists = load_plan.get("if_exists") or "append"
                    if if_exists not in ("append", "replace", "fail"):
                        if_exists = "append"
                    schema_name = load_plan.get("schema")
                    if isinstance(schema_name, str) and not schema_name.strip():
                        schema_name = None
                    if not table:
                        destination_load_info = {
                            "success": False,
                            "message": "Load was indicated but no destination table name was provided.",
                        }
                        response += "\n\n### Destination load\n\n_No table name — skipping write._"
                    else:
                        ok, msg = load_dataframe(
                            dest_engine,
                            table,
                            result_df,
                            if_exists=if_exists,
                            schema=schema_name,
                        )
                        destination_load_info = {
                            "success": ok,
                            "message": msg,
                            "table": table,
                            "if_exists": if_exists,
                        }
                        tag = "Destination load" if ok else "Destination load (failed)"
                        response += f"\n\n### {tag}\n\n{msg}"
                else:
                    destination_load_info = {
                        "success": True,
                        "skipped": True,
                        "message": load_plan.get("reason") or "No destination write requested.",
                    }
            except Exception as e:
                destination_load_info = {"success": False, "message": str(e)}
                response += f"\n\n### Destination load (failed)\n\n{e}"

        # Update session history
        hist.append({"role": "user", "content": query})
        hist.append({"role": "assistant", "content": response[:8000]})
        if len(hist) > 20:
            del hist[:-20]

        self._log_step(session_id, {
            "step": "completed",
            "rows_produced": len(result_df),
            "cols_produced": len(result_df.columns),
            "execution_time_ms": exec_stats.get("execution_time_ms", 0),
        })

        # Build output schema
        output_schema = {
            "columns": list(result_df.columns),
            "types": [str(result_df[c].dtype) for c in result_df.columns],
        }

        # Build result preview
        preview_rows = result_df.head(_MAX_PREVIEW_ROWS).values.tolist()
        clean_preview = []
        for row in preview_rows:
            clean_row = []
            for cell in row:
                if pd.isna(cell):
                    clean_row.append(None)
                elif hasattr(cell, "isoformat"):
                    clean_row.append(cell.isoformat())
                else:
                    clean_row.append(cell)
            clean_preview.append(clean_row)

        return {
            "success": True,
            "response": response,
            "query": query,
            "thinking_steps": thinking,
            "timestamp": now,
            "generated_code": code,
            "output_schema": output_schema,
            "execution_stats": exec_stats,
            "result_preview": {
                "columns": list(result_df.columns),
                "rows": clean_preview,
                "total_rows": len(result_df),
                "truncated": exec_result.truncated,
            },
            "validation": validation.to_dict(),
            "plan": plan,
            "destination_load": destination_load_info,
        }

    # ── Self-healing helper ─────────────────────────────────────────

    def _self_heal_code(
        self,
        query: str,
        schema_text: str,
        code: str,
        error: str,
        thinking: List[ThinkingStep],
        session_id: str,
        attempt: int = 1,
        on_thinking_step: Optional[Callable[[ThinkingStep], None]] = None,
    ) -> Optional[str]:
        """Layer 6: Use LLM critic to regenerate code after failure."""
        prompt = build_critic_prompt(query, code, error, schema_text, attempt)
        try:
            raw = ai_service.call_genai(prompt, temperature=0.1, max_tokens=4096)
            fixed = extract_code_block(raw)

            # Validate the fix
            static_errors = validate_generated_code(fixed)
            if static_errors:
                _add_thinking(
                    thinking,
                    ThinkingStep(
                        type="tool",
                        content=f"Critic fix also has static errors: {'; '.join(static_errors)}",
                        tool_name="critic",
                    ),
                    on_thinking_step,
                )
                return None

            self._log_step(session_id, {
                "step": "self_heal",
                "attempt": attempt,
                "fixed_code": fixed,
            })

            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content=f"Critic generated fixed code (attempt {attempt}).",
                    tool_name="critic",
                ),
                on_thinking_step,
            )
            return fixed
        except Exception as e:
            _add_thinking(
                thinking,
                ThinkingStep(
                    type="tool",
                    content=f"Critic failed: {e}",
                    tool_name="critic",
                ),
                on_thinking_step,
            )
            return None

    # ── Data extraction from natural language queries ────────────────

    def _try_extract_data_from_query(self, query: str) -> Optional[pd.DataFrame]:
        """Try to find inline CSV/JSON data embedded in the user's query."""
        import re

        # Look for code blocks
        code_block = re.search(r"```(?:csv|json|tsv)?\s*\n(.*?)```", query, re.DOTALL)
        if code_block:
            raw = code_block.group(1).strip()
            return parse_inline_data(raw)

        # Look for data that looks like CSV (has commas and newlines with header)
        lines = query.strip().split("\n")
        if len(lines) >= 3:
            # Check if it looks like tabular data
            first_line = lines[0].strip()
            if "," in first_line:
                col_count = first_line.count(",") + 1
                data_lines = [l for l in lines if l.count(",") + 1 == col_count]
                if len(data_lines) >= 3:
                    csv_text = "\n".join(data_lines)
                    return parse_inline_data(csv_text, "csv")

        return None


etl_agent = ETLAgent()
