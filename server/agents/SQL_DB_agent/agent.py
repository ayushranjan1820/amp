"""SQL DB Agent — LLM-orchestrated planning, programmatic SQL validation, governed execution.

Scaling features:
  - Query timeouts (per-dialect statement_timeout)
  - EXPLAIN plan analysis with cost / seq-scan warnings
  - Table row-count & index awareness in schema digest
  - Two-pass schema selection for databases with 150+ tables
  - Parallel step execution for independent SQL steps
  - Short-TTL result caching (5 min) per session
  - Paginated result delivery
  - Increased connection pool (5 + 10 overflow)
  - History summarisation for long conversations
  - Memory-safe chunked fetching
  - Optimisation rules in the orchestration prompt
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import os
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from .ai_service import ai_service
from .models import ThinkingStep
from .tools.schema_service import (
    build_detailed_digest_for_tables,
    build_mermaid_erd,
    iter_build_lightweight_digest,
    iter_build_schema_digest,
)
from .tools.sql_executor import run_explain, run_sql
from .tools.sql_guard import dialect_from_url, guard_sql, user_table_names_from_sql

logger = logging.getLogger(__name__)

# ── Size thresholds for presentation ─────────────────────────────────
_LARGE_ROW_COUNT = 100
_LARGE_CELL_COUNT = 5_000
_MAX_JSON_CHARS_FOR_LLM = 200_000
_FETCH_MAX_ROWS = 25_000
_MAX_ORCH_STEPS = 10

# ── Performance / scaling ────────────────────────────────────────────
_QUERY_TIMEOUT_MS = 30_000          # 30 s per statement
_EXPLAIN_COST_THRESHOLD = 50_000    # warn above this EXPLAIN cost
_EXPLAIN_ROW_THRESHOLD = 500_000    # warn above this estimated-row count

# ── Caching ──────────────────────────────────────────────────────────
_CACHE_TTL_SECONDS = 300            # 5-min result cache per session

# ── Parallel execution pool ──────────────────────────────────────────
_STEP_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=6, thread_name_prefix="sql_step"
)

# ── Engine & schema caches ───────────────────────────────────────────
_engines_lock = threading.Lock()
_engines: Dict[str, Any] = {}
_schema_lock = threading.Lock()
_schema_cache: Dict[str, Dict[str, Any]] = {}


# =====================================================================
#  Helpers — engine, config, JSON extraction
# =====================================================================

def _engine_fingerprint(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def _get_engine(url: str):
    key = _engine_fingerprint(url)
    with _engines_lock:
        if key not in _engines:
            _engines[key] = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=5,          # raised from 2
                max_overflow=10,      # raised from 2
                future=True,
            )
        return _engines[key], key


def _invalidate_schema_cache(engine_key: str) -> None:
    with _schema_lock:
        _schema_cache.pop(engine_key, None)


def _config_errors() -> List[str]:
    """Validate DB + LLM provider credentials via the shared helpers.

    Delegates LLM credential checks to :func:`is_llm_provider_configured` so every
    provider (``pwc_genai``, ``ollama_cloud``, ``local_llm``) is handled uniformly
    and new providers added to ``local_llm`` are picked up automatically.
    """
    from agents.local_llm import (
        describe_missing_llm_credentials,
        is_llm_provider_configured,
    )

    errs: List[str] = []
    if not (os.getenv("DATABASE_CONNECTION_STRING") or "").strip():
        errs.append(
            "DATABASE_CONNECTION_STRING is missing. Provide a SQLAlchemy URL "
            "(e.g. postgresql+psycopg2://user:pass@host:5432/dbname or sqlite:///./file.db)."
        )
    if not is_llm_provider_configured():
        errs.append(describe_missing_llm_credentials())
    return errs


# =====================================================================
#  Provider-aware token / prompt budgets
# =====================================================================

def _provider_budget() -> Dict[str, int]:
    """Budget knobs tuned to the active LLM provider.

    Small on-prem / Ollama models have tight context windows and lower
    throughput, so we cap ``max_tokens`` aggressively and tighten the schema
    digest cap. PwC GenAI (Claude/Gemini via Vertex) gets the larger defaults.
    """
    from agents.local_llm import get_llm_provider

    prov = get_llm_provider()
    if prov == "ollama_cloud":
        return {
            "orch_max_tokens": 4096,
            "review_max_tokens": 2048,
            "format_max_tokens": 3072,
            "repair_max_tokens": 1536,
            "select_tables_max_tokens": 1024,
            "history_summary_max_tokens": 400,
            "schema_digest_char_cap": 40_000,
            "force_two_pass_table_count": 80,
        }
    if prov == "local_llm":
        return {
            "orch_max_tokens": 2048,
            "review_max_tokens": 1024,
            "format_max_tokens": 2048,
            "repair_max_tokens": 1024,
            "select_tables_max_tokens": 768,
            "history_summary_max_tokens": 300,
            "schema_digest_char_cap": 20_000,
            "force_two_pass_table_count": 40,
        }
    # pwc_genai / default — large-context models
    return {
        "orch_max_tokens": 8192,
        "review_max_tokens": 8192,
        "format_max_tokens": 4096,
        "repair_max_tokens": 4096,
        "select_tables_max_tokens": 2048,
        "history_summary_max_tokens": 500,
        "schema_digest_char_cap": 0,            # no cap
        "force_two_pass_table_count": 150,
    }


def _cap_digest_text(digest: Dict[str, Any], char_cap: int) -> Dict[str, Any]:
    """Return a copy of ``digest`` with ``text`` truncated to ``char_cap`` chars.

    Zero or negative ``char_cap`` disables truncation.
    """
    if char_cap <= 0:
        return digest
    raw = digest.get("text") or ""
    if len(raw) <= char_cap:
        return digest
    truncated = raw[:char_cap] + (
        f"\n\n-- [schema digest truncated at {char_cap} chars due to LLM "
        "context limit; the agent will two-pass select relevant tables] --"
    )
    out = dict(digest)
    out["text"] = truncated
    return out


# =====================================================================
#  SQL error classification for the repair loop
# =====================================================================

_REPAIR_ATTEMPTS_MAX = int(os.getenv("SQL_DB_AGENT_REPAIR_ATTEMPTS", "2"))

# Guard errors that the LLM *can* fix by regenerating the SQL.
_REPAIRABLE_GUARD_PATTERNS = (
    "unknown table or view",
    "not defined on",
    "not in introspected schema",
    "sql parse error",
    "multiple sql statements",
    "update and delete require a where clause",
)

# Execution errors we should NOT retry on (cost amplification / won't help).
_NON_REPAIRABLE_SUBSTRINGS = (
    "statement timeout",
    "canceling statement due to",
    "lock wait timeout",
    "permission denied",
    "access denied",
    "role",
    "destructive or ddl statements are blocked",
    "does not allow",
)


def _is_repairable_error(err: str) -> bool:
    low = (err or "").lower()
    if any(s in low for s in _NON_REPAIRABLE_SUBSTRINGS):
        return False
    if any(s in low for s in _REPAIRABLE_GUARD_PATTERNS):
        return True
    # SQLAlchemy / DBAPI error class names commonly surfaced as "ClassName: detail"
    repairable_sqlerr_tokens = (
        "programmingerror",     # syntax, missing column, undefined table
        "operationalerror",     # some dialects surface bad SQL here
        "dataerror",            # value out of range, bad literal
        "undefinedcolumn",
        "undefinedtable",
        "syntax error",
        "no such column",
        "no such table",
        "ambiguous column",
        "column .* does not exist",
    )
    return any(tok in low for tok in repairable_sqlerr_tokens)


def _extract_json_object(text_str: str) -> Dict[str, Any]:
    """Parse the first top-level JSON object from model text.

    Using json.loads(slice from first '{' to last '}') breaks when the model emits
    two objects (e.g. ``{...}{...}``) or valid JSON followed by prose — that raises
    json.JSONDecodeError: Extra data. raw_decode consumes exactly one value.
    """
    raw = text_str.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        raw = "\n".join(lines)
    start = raw.find("{")
    if start < 0:
        raise ValueError("Model did not return a JSON object.")
    try:
        obj, _end = json.JSONDecoder().raw_decode(raw, start)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in model output: {e}") from e
    if not isinstance(obj, dict):
        raise ValueError("Model returned JSON that is not an object.")
    return obj


def _relationship_lines(digest: Dict[str, Any]) -> str:
    edges = digest.get("fk_edges") or []
    if not edges:
        return ""
    lines = []
    for src, dst, c, _ in edges[:120]:
        lines.append(f"{src} -> {dst} (columns: {c})")
    return "\n".join(lines)


def _all_table_labels(digest: Dict[str, Any]) -> str:
    items = digest.get("tables") or []
    labels: List[str] = []
    for t in items:
        nm = t.get("name") or ""
        sc = t.get("schema")
        kind = t.get("kind", "table")
        rc = t.get("row_count")
        rc_str = f" ~{rc} rows" if rc is not None else ""
        if sc:
            labels.append(f"{sc}.{nm} ({kind}{rc_str})")
        else:
            labels.append(f"{nm} ({kind}{rc_str})")
    return "\n".join(f"- {x}" for x in labels) if labels else "(none)"


def _normalize_orchestration(obj: Dict[str, Any]) -> Dict[str, Any]:
    ot = (obj.get("outcome_type") or "").strip().lower()
    if ot not in ("erd", "execute_sql", "need_clarification"):
        steps_raw = obj.get("steps")
        has_sql = isinstance(steps_raw, list) and any(
            isinstance(s, dict) and (s.get("sql") or "").strip() for s in steps_raw
        )
        ot = "execute_sql" if has_sql else "need_clarification"
    steps: List[Dict[str, Any]] = []
    raw_steps = obj.get("steps") if isinstance(obj.get("steps"), list) else []
    for s in raw_steps[:_MAX_ORCH_STEPS]:
        if not isinstance(s, dict):
            continue
        sql = (s.get("sql") or "").strip()
        if not sql:
            continue
        steps.append({
            "sql": sql,
            "purpose": (s.get("purpose") or "").strip(),
            "parallel": bool(s.get("parallel", False)),
        })
    clar = obj.get("clarification")
    clar_s = clar.strip() if isinstance(clar, str) else ""
    return {
        "refresh_schema": bool(obj.get("refresh_schema")),
        "outcome_type": ot,
        "clarification": clar_s or None,
        "plan_summary": (
            (obj.get("plan_summary") or "").strip()
            if isinstance(obj.get("plan_summary"), str) else ""
        ),
        "fk_and_constraint_notes": (
            (obj.get("fk_and_constraint_notes") or "").strip()
            if isinstance(obj.get("fk_and_constraint_notes"), str) else ""
        ),
        "steps": steps,
    }


# =====================================================================
#  Result formatting
# =====================================================================

def _format_result_markdown(columns: List[str], rows: List[List[Any]]) -> str:
    if not columns:
        return "_No rows returned._"
    head = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [head, sep]
    for r in rows:
        cells = ["" if x is None else str(x).replace("|", "\\|") for x in r]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _step_result_is_large(res: Dict[str, Any]) -> bool:
    rows = res.get("rows") or []
    cols = res.get("columns") or []
    if res.get("truncated"):
        return True
    if len(rows) >= _LARGE_ROW_COUNT:
        return True
    if len(cols) * len(rows) >= _LARGE_CELL_COUNT:
        return True
    return False


def _combined_results_large(combined: List[Dict[str, Any]]) -> bool:
    return any(_step_result_is_large(b.get("result") or {}) for b in combined)


def _compact_for_llm(combined: List[Dict[str, Any]]) -> str:
    """Full row payload for non-large results so the model doesn't assume sampling."""
    out: List[Dict[str, Any]] = []
    for block in combined:
        r = block.get("result") or {}
        cols = r.get("columns") or []
        rows = r.get("rows") or []
        out.append({
            "purpose": block.get("purpose"),
            "columns": cols,
            "row_count": len(rows),
            "fetch_hit_row_limit": bool(r.get("truncated")),
            "rows": rows,
        })
    s = json.dumps(out, default=str)
    if len(s) > _MAX_JSON_CHARS_FOR_LLM:
        slim: List[Dict[str, Any]] = []
        for block in combined:
            r = block.get("result") or {}
            slim.append({
                "purpose": block.get("purpose"),
                "columns": r.get("columns"),
                "row_count": len(r.get("rows") or []),
                "fetch_hit_row_limit": bool(r.get("truncated")),
            })
        s = json.dumps(slim, default=str)
    return s


def _paginate_rows(
    rows: List[List[Any]], page: int, page_size: int,
) -> Tuple[List[List[Any]], Dict[str, Any]]:
    """Return a slice of rows and a page_info dict."""
    total = len(rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    info = {
        "page": page,
        "page_size": page_size,
        "total_rows": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }
    return rows[start:end], info


def _append_full_results_section(
    combined_results: List[Dict[str, Any]],
    page: int = 1,
    page_size: int = 500,
) -> str:
    parts: List[str] = ["\n\n### Results\n"]
    for i, block in enumerate(combined_results):
        res = block.get("result") or {}
        purpose = block.get("purpose") or ""
        cols = res.get("columns") or []
        rows = res.get("rows") or []
        if purpose:
            parts.append(f"#### Step {i + 1}: {purpose}\n\n")
        else:
            parts.append(f"#### Step {i + 1}\n\n")
        page_rows, info = _paginate_rows(rows, page, page_size)
        parts.append(_format_result_markdown(cols, page_rows))
        if info["total_pages"] > 1:
            parts.append(
                f"\n\n_Page {info['page']} of {info['total_pages']} "
                f"({info['total_rows']} total rows)._"
            )
        parts.append("\n\n")
    return "".join(parts).rstrip()


def _build_tabular_only_response(
    combined_results: List[Dict[str, Any]],
    sql_block: Optional[str],
    show_sql: bool,
    page: int = 1,
    page_size: int = 500,
) -> str:
    parts: List[str] = ["### Results\n\n"]
    parts.append("_Large result set -- showing paginated results below._\n\n")
    for i, block in enumerate(combined_results):
        res = block.get("result") or {}
        purpose = block.get("purpose") or ""
        cols = res.get("columns") or []
        rows = res.get("rows") or []
        if purpose:
            parts.append(f"#### Step {i + 1}: {purpose}\n\n")
        else:
            parts.append(f"#### Step {i + 1}\n\n")
        page_rows, info = _paginate_rows(rows, page, page_size)
        parts.append(_format_result_markdown(cols, page_rows))
        if info["total_pages"] > 1:
            parts.append(
                f"\n\n_Page {info['page']} of {info['total_pages']} "
                f"({info['total_rows']} total rows)._"
            )
        if res.get("truncated"):
            parts.append(
                f"\n\n_Note: This step retrieved the maximum of {_FETCH_MAX_ROWS} rows; "
                "the result may continue in the database._\n"
            )
        parts.append("\n\n")
    if show_sql and sql_block:
        parts.append("### Generated SQL\n```sql\n" + sql_block + "\n```\n")
    return "".join(parts)


# =====================================================================
#  Short-TTL result cache (per session)
# =====================================================================

class _ResultCache:
    """Caches identical SQL results for _CACHE_TTL_SECONDS within a session."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _sql_hash(self, sqls: List[str]) -> str:
        return hashlib.sha256("|".join(sqls).encode()).hexdigest()[:32]

    def get(self, session_id: str, sqls: List[str]) -> Optional[Dict[str, Any]]:
        key = self._sql_hash(sqls)
        with self._lock:
            session_cache = self._store.get(session_id, {})
            entry = session_cache.get(key)
            if entry and (time.time() - entry["ts"]) < _CACHE_TTL_SECONDS:
                return entry["result"]
            if entry:
                session_cache.pop(key, None)
            return None

    def put(self, session_id: str, sqls: List[str], result: Dict[str, Any]) -> None:
        key = self._sql_hash(sqls)
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = {}
            self._store[session_id][key] = {"result": result, "ts": time.time()}
            # Evict stale entries
            cutoff = time.time() - _CACHE_TTL_SECONDS
            self._store[session_id] = {
                k: v for k, v in self._store[session_id].items() if v["ts"] > cutoff
            }

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)


_result_cache = _ResultCache()


# =====================================================================
#  Main Agent
# =====================================================================

class SqlDbAgent:
    def __init__(self) -> None:
        self._session_state: Dict[str, Dict[str, Any]] = {}
        print("SQL DB Agent initialized")

    def _state(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self._session_state:
            self._session_state[session_id] = {"history": []}
        return self._session_state[session_id]

    # ── Schema loading ───────────────────────────────────────────

    def _load_digest(
        self, engine, engine_key: str, force_refresh: bool,
    ) -> Dict[str, Any]:
        """Load schema digest (no SSE). Cache miss builds outside the lock."""
        with _schema_lock:
            if not force_refresh and engine_key in _schema_cache:
                return _schema_cache[engine_key]
        digest: Optional[Dict[str, Any]] = None
        for item in iter_build_schema_digest(engine, with_progress=False):
            if item.get("kind") == "digest":
                digest = item["digest"]
                break
        if digest is None:
            raise RuntimeError("Schema introspection produced no digest")
        with _schema_lock:
            _schema_cache[engine_key] = digest
        return digest

    def _stream_schema_digest_load(
        self, engine, engine_key: str, force_refresh: bool,
    ):
        """Yield ``{"event","data"}`` progress for SSE, then ``{"__digest__": digest}``."""
        with _schema_lock:
            cached = _schema_cache.get(engine_key) if not force_refresh else None
        if cached is not None:
            yield {
                "event": "progress",
                "data": {
                    "stage": "schema_load",
                    "message": "Using cached schema snapshot (no re-introspection).",
                },
            }
            yield {"__digest__": cached}
            return

        digest: Optional[Dict[str, Any]] = None
        for item in iter_build_schema_digest(engine, with_progress=True):
            if item.get("kind") == "progress":
                yield {
                    "event": "progress",
                    "data": {"stage": item["stage"], "message": item["message"]},
                }
            elif item.get("kind") == "digest":
                digest = item["digest"]
        if digest is None:
            raise RuntimeError("Schema introspection produced no digest")
        with _schema_lock:
            _schema_cache[engine_key] = digest
        yield {"__digest__": digest}

    def _stream_lightweight_digest(self, engine):
        """Yield progress SSE chunks, then ``{"__digest__": lightweight_dict}``."""
        digest: Optional[Dict[str, Any]] = None
        for item in iter_build_lightweight_digest(engine, with_progress=True):
            if item.get("kind") == "progress":
                yield {
                    "event": "progress",
                    "data": {"stage": item["stage"], "message": item["message"]},
                }
            elif item.get("kind") == "digest":
                digest = item["digest"]
        if digest is None:
            raise RuntimeError("Lightweight schema pass produced no digest")
        yield {"__digest__": digest}

    # ── Two-pass schema (large databases) ────────────────────────

    def _select_relevant_tables(
        self, query: str, lightweight_text: str,
    ) -> Set[str]:
        """Ask LLM to pick relevant tables from a lightweight digest."""
        prompt = (
            "You are a database expert. Given a user question and a database "
            "table summary, identify which tables/views are needed to answer "
            "the question.\n\n"
            f"User question:\n{query}\n\n"
            f"Available tables (name, kind, row count, sample columns):\n"
            f"{lightweight_text}\n\n"
            'Return ONLY a JSON object: {"tables": ["table1", "table2", ...]}\n'
            "Include table names exactly as shown. Include tables needed for "
            "JOINs (FK targets). Select at most 30 tables."
        )
        budget = _provider_budget()
        try:
            raw = ai_service.call_genai(
                prompt,
                temperature=0.0,
                max_tokens=budget["select_tables_max_tokens"],
            )
            obj = _extract_json_object(raw)
            tables = obj.get("tables") or []
            return {t.lower() for t in tables if isinstance(t, str)}
        except Exception:
            return set()

    # ── Conversation history with summarisation ──────────────────

    def _build_history_context(self, hist: List[Dict[str, str]]) -> str:
        if not hist:
            return ""
        # Short history: raw last-4 turns
        if len(hist) <= 8:
            parts = [
                f"{t['role'].upper()}: {t['content'][:1200]}" for t in hist[-4:]
            ]
            return "\n".join(parts)

        # Long history: summarise older turns + keep last-4 raw
        older = hist[:-8]
        older_text = "\n".join(
            f"{t['role'].upper()}: {t['content'][:300]}" for t in older[-10:]
        )
        budget = _provider_budget()
        try:
            summary = ai_service.call_genai(
                "Summarize this database conversation history in 3-4 bullet "
                "points. Focus on: what data was queried, key filters used, "
                f"decisions made.\n\n{older_text}",
                temperature=0.0,
                max_tokens=budget["history_summary_max_tokens"],
            )
        except Exception:
            summary = "(earlier conversation context unavailable)"

        recent = [
            f"{t['role'].upper()}: {t['content'][:1200]}" for t in hist[-4:]
        ]
        return f"Earlier context summary:\n{summary}\n\nRecent turns:\n" + "\n".join(recent)

    # ── Orchestration prompt (with optimisation rules) ───────────

    def _orchestration_prompt(
        self,
        dialect_name: str,
        digest: Dict[str, Any],
        query: str,
        history_snippet: str,
    ) -> str:
        fk_block = _relationship_lines(digest)
        fk_section = (
            f"\nKnown foreign-key relationships (from introspection):\n{fk_block}\n"
            if fk_block else ""
        )
        return f"""You orchestrate a secure SQL database assistant. Output ONLY valid JSON (no markdown).

Technical context:
- sqlglot dialect label: {dialect_name}

Conversation context:
{history_snippet if history_snippet else "(none)"}

Authoritative schema (tables, columns, types, approximate row counts, and index hints — you must NOT invent identifiers outside this text):
{digest.get("text", "")}
{fk_section}

User message:
{query}

Return a single JSON object with exactly these keys:
- "refresh_schema": boolean — true only if the user explicitly wants schema/catalog re-introspection refreshed from the database before planning.
- "outcome_type": one of "erd", "execute_sql", "need_clarification"
- "clarification": string or null — required, non-empty string when outcome_type is "need_clarification"
- "plan_summary": short string — your decomposition of the user goal and how steps relate
- "fk_and_constraint_notes": string — how joins/FKs/constraints apply to this request (empty if N/A)
- "steps": array of up to {_MAX_ORCH_STEPS} objects {{ "sql": "exactly one SQL statement", "purpose": "why", "parallel": true/false }}
  Set "parallel": true on steps that are independent from each other and can run concurrently.

Rules:
1. Schema awareness: every table/column in "steps" MUST appear in the authoritative schema (or standard read-only system catalogs such as information_schema / pg_catalog when needed for metadata). Never guess names.
2. Multi-entity / multi-table: If the user asks for **several kinds of records** (e.g. **project** + **BRD** + **test cases**, or parent + child entities stored in **different** tables), you MUST cover **every** part. Prefer **one** SELECT with **JOIN**s on the FK paths above; otherwise use **multiple steps** (e.g. one SELECT per table) each filtered by the same project (id or name). **Never** return only one entity type when the user asked for multiple.
3. Multi-step: split complex work into ordered steps; each "sql" is independent — repeat the project/scope filter in each step when using separate queries.
4. Accuracy: prefer explicit JOINs using FK hints; document join logic in fk_and_constraint_notes.
5. outcome_type "erd" for schema/diagram requests — use "steps": [].
6. outcome_type "need_clarification" when ambiguous — set "steps": [] and a helpful "clarification".
7. outcome_type "execute_sql" for data/DML; provide 1–{_MAX_ORCH_STEPS} steps. UPDATE/DELETE must include WHERE.
8. JSON must be valid; escape quotes inside strings.

Performance & optimisation rules (CRITICAL for large tables — check row-count hints in schema):
9. **Never SELECT * on tables with row counts >10K rows**; list only the columns the user needs.
10. **Push WHERE filters as early as possible** — filter before joining, not after. Use subqueries or CTEs to pre-filter large tables.
11. Use **EXISTS** instead of **IN** for correlated subqueries on large tables.
12. For **top-N** or exploratory queries always include **LIMIT** (or TOP for MSSQL).
13. Prefer filtering on **indexed columns** (shown in schema as index hints) in WHERE and JOIN conditions.
14. For **aggregations on large tables** filter rows first (WHERE) then aggregate (GROUP BY) — never aggregate unfiltered large tables.
15. When joining tables with very different sizes put the **smaller table first** in the FROM clause or use it as the driving table.
16. For complex analytical queries use **CTEs** (WITH clauses) to break logic into readable, reusable stages.
"""

    def _llm_orchestrate(
        self,
        dialect_name: str,
        digest: Dict[str, Any],
        query: str,
        history_snippet: str,
    ) -> Dict[str, Any]:
        budget = _provider_budget()
        prompt_digest = _cap_digest_text(digest, budget["schema_digest_char_cap"])
        prompt = self._orchestration_prompt(
            dialect_name, prompt_digest, query, history_snippet,
        )
        raw = ai_service.call_genai(
            prompt, temperature=0.05, max_tokens=budget["orch_max_tokens"],
        )
        obj = _extract_json_object(raw)
        return _normalize_orchestration(obj)

    # ── Plan completeness review ─────────────────────────────────

    def _llm_review_plan_completeness(
        self,
        query: str,
        orch: Dict[str, Any],
        digest: Dict[str, Any],
        dialect_name: str,
    ) -> Dict[str, Any]:
        """Second LLM pass: ensure the plan covers all entities the user asked for."""
        steps = orch.get("steps") or []
        if not steps:
            return orch

        plan_lines: List[str] = []
        tables_union: set = set()
        for i, s in enumerate(steps):
            plan_lines.append(f"{i + 1}. [{s.get('purpose', '')}] {s['sql']}")
            tables_union |= user_table_names_from_sql(s["sql"], dialect_name)

        fk_block = _relationship_lines(digest) or "(none listed)"
        tables_catalog = _all_table_labels(digest)

        prompt = f"""You validate whether a SQL execution plan fully answers a natural language database question.

User question:
{query}

Current plan_summary:
{orch.get("plan_summary", "")}

Current fk_and_constraint_notes:
{orch.get("fk_and_constraint_notes", "")}

Planned SQL ({len(steps)} step(s)):
{chr(10).join(plan_lines)}

Application tables referenced in that SQL: {sorted(tables_union)}

All application tables/views (use only these names/columns from the schema text the user sees):
{tables_catalog}

Foreign keys (use for JOINs):
{fk_block}

Checklist:
- If the user asked for **multiple** data domains (e.g. BRDs **and** test cases **for** a specific project), the plan must return **both** BRD-related rows **and** test-case rows, scoped to that project (JOINs or separate steps).
- If the plan only queries tables for one domain while the question clearly requires another domain's table as well, the plan is **incomplete**.

Output ONLY one JSON object:
- If sufficient: {{"complete": true}}
- If incomplete: {{"complete": false, "plan_summary": "string", "fk_and_constraint_notes": "string", "steps": [{{"sql":"single statement","purpose":"why"}}]}}
Replacement: 1–{_MAX_ORCH_STEPS} single SQL statements; valid identifiers only; prefer JOINs on FKs when possible."""

        budget = _provider_budget()
        raw = ai_service.call_genai(
            prompt, temperature=0.0, max_tokens=budget["review_max_tokens"],
        )
        try:
            rev = _extract_json_object(raw)
        except Exception:
            return orch
        if rev.get("complete") is True:
            return orch
        if rev.get("complete") is not False:
            return orch
        raw_st = rev.get("steps")
        if not isinstance(raw_st, list):
            return orch
        new_steps: List[Dict[str, Any]] = []
        for s in raw_st[:_MAX_ORCH_STEPS]:
            if not isinstance(s, dict):
                continue
            sql = (s.get("sql") or "").strip()
            if not sql:
                continue
            new_steps.append({
                "sql": sql,
                "purpose": (s.get("purpose") or "").strip(),
                "parallel": bool(s.get("parallel", False)),
            })
        if not new_steps:
            return orch
        return {
            **orch,
            "steps": new_steps,
            "plan_summary": (
                rev.get("plan_summary") or orch.get("plan_summary") or ""
            ).strip(),
            "fk_and_constraint_notes": (
                rev.get("fk_and_constraint_notes")
                or orch.get("fk_and_constraint_notes")
                or ""
            ).strip(),
        }

    # ── EXPLAIN plan check ───────────────────────────────────────

    def _check_explain(
        self, engine, sql: str, dialect: str, step_num: int,
    ) -> Optional[Dict[str, Any]]:
        """Run EXPLAIN and return a warning dict if the plan looks expensive."""
        plan = run_explain(engine, sql, dialect)
        if not plan.get("supported"):
            return None

        warnings = plan.get("warnings") or []
        est_rows = plan.get("estimated_rows")
        est_cost = plan.get("estimated_cost")

        should_warn = bool(plan.get("seq_scans"))
        if est_cost and est_cost > _EXPLAIN_COST_THRESHOLD:
            should_warn = True
        if est_rows and est_rows > _EXPLAIN_ROW_THRESHOLD:
            should_warn = True

        if should_warn:
            parts: List[str] = []
            if est_cost and est_cost > _EXPLAIN_COST_THRESHOLD:
                parts.append(f"High estimated cost: {est_cost:,.0f}")
            if est_rows and est_rows > _EXPLAIN_ROW_THRESHOLD:
                parts.append(f"Large estimated row scan: {est_rows:,}")
            parts.extend(warnings)
            return {
                "step": step_num,
                "estimated_rows": est_rows,
                "estimated_cost": est_cost,
                "seq_scans": plan.get("seq_scans") or [],
                "warning": "; ".join(parts),
            }
        return None

    # ── Single-step execution ────────────────────────────────────

    def _execute_single_step(
        self,
        engine,
        step: Dict[str, Any],
        step_index: int,
        dialect: str,
        allowed: Set[str],
        colmap: Dict[str, Set[str]],
        session_id: str,
    ) -> Dict[str, Any]:
        """Guard -> EXPLAIN -> Execute for one SQL step."""
        sql = step["sql"]
        purpose = step.get("purpose") or ""

        # Guard
        clean, gerr = guard_sql(sql, dialect, allowed, colmap, session_id)
        if gerr:
            return {
                "success": False, "step": step_index,
                "purpose": purpose, "error": gerr, "sql": sql,
            }

        # EXPLAIN check (best-effort, never blocks execution)
        explain_warning = self._check_explain(engine, clean, dialect, step_index + 1)

        # Execute
        try:
            out = run_sql(
                engine, clean,
                max_rows=_FETCH_MAX_ROWS,
                timeout_ms=_QUERY_TIMEOUT_MS,
                dialect=dialect,
            )
        except SQLAlchemyError as e:
            return {
                "success": False, "step": step_index,
                "purpose": purpose,
                "error": f"{type(e).__name__}: {e}",
                "sql": clean,
            }

        return {
            "success": True, "step": step_index,
            "purpose": purpose, "result": out,
            "sql": clean, "explain_warning": explain_warning,
        }

    # ── LLM SQL repair ───────────────────────────────────────────

    def _llm_repair_sql(
        self,
        bad_sql: str,
        error_msg: str,
        purpose: str,
        digest: Dict[str, Any],
        dialect_name: str,
        query: str,
        previous_attempts: List[str],
    ) -> Optional[str]:
        """Ask the LLM to fix a failing SQL statement.

        Returns the corrected single SQL string, or ``None`` if repair is not
        possible. The corrected SQL is still subject to the guard + EXPLAIN +
        execute pipeline — this method does not bypass any safety layer.
        """
        budget = _provider_budget()
        prompt_digest = _cap_digest_text(digest, budget["schema_digest_char_cap"])
        prior_attempts_block = ""
        if previous_attempts:
            prior_attempts_block = (
                "\nPrevious failed attempts (DO NOT repeat these):\n"
                + "\n".join(
                    f"-- attempt {i + 1}\n{a}" for i, a in enumerate(previous_attempts)
                )
                + "\n"
            )
        prompt = f"""You repair a failing SQL statement. Output ONLY a JSON object: {{"sql": "single corrected SQL statement"}}.

Dialect: {dialect_name}

Original user question:
{query}

Step purpose:
{purpose}

Authoritative schema (use ONLY these tables/columns — never invent identifiers):
{prompt_digest.get("text", "")}

Failing SQL:
{bad_sql}

Database / guard error:
{error_msg}
{prior_attempts_block}
Rules:
- Return ONE single SQL statement (no trailing semicolon, no multiple statements).
- Keep the same intent as the step purpose.
- Use only identifiers from the authoritative schema or standard read-only system catalogs (information_schema / pg_catalog).
- If the error says a column/table does not exist, pick the correct one from the schema.
- If the error says UPDATE/DELETE needs WHERE, add a narrow WHERE clause — never remove filters to make the query "work".
- Do not produce destructive DDL. Do not wrap in markdown.
"""
        try:
            raw = ai_service.call_genai(
                prompt,
                temperature=0.0,
                max_tokens=budget["repair_max_tokens"],
            )
            obj = _extract_json_object(raw)
        except Exception as e:
            logger.warning("SQL repair LLM call failed: %s", e)
            return None
        fixed = (obj.get("sql") or "").strip()
        if not fixed:
            return None
        if fixed.strip() == bad_sql.strip():
            return None
        return fixed

    # ── Multi-step execution (parallel when possible) ────────────

    def _execute_steps(
        self,
        engine,
        steps: List[Dict[str, Any]],
        dialect: str,
        allowed: Set[str],
        colmap: Dict[str, Set[str]],
        session_id: str,
        digest: Dict[str, Any],
        query: str,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Execute steps, parallelising adjacent independent ones.

        Each step that fails with a *repairable* error is retried up to
        ``_REPAIR_ATTEMPTS_MAX`` times: the LLM is asked to fix the SQL given
        the error + schema, and the repaired statement runs through the full
        guard + EXPLAIN + execute pipeline again.

        Returns (step_results, explain_warnings, repair_events).
        ``repair_events`` is a list of ``{"step", "attempt", "error",
        "old_sql", "new_sql", "success"}`` dicts for SSE thinking visibility.
        """
        explain_warnings: List[Dict[str, Any]] = []
        repair_events: List[Dict[str, Any]] = []
        results: List[Optional[Dict[str, Any]]] = [None] * len(steps)

        def _attempt_with_repair(
            step_idx: int,
            step_copy: Dict[str, Any],
            initial_out: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Run one step with up to ``_REPAIR_ATTEMPTS_MAX`` LLM repairs.

            Pass ``initial_out`` when the first execution was already performed
            (e.g. by a parallel batch) so we don't pointlessly re-run it.
            """
            attempted_sql: List[str] = []
            if initial_out is not None:
                out = initial_out
            else:
                out = self._execute_single_step(
                    engine, step_copy, step_idx, dialect, allowed, colmap, session_id,
                )
            for attempt in range(_REPAIR_ATTEMPTS_MAX):
                if out["success"]:
                    return out
                err = out.get("error") or ""
                if not _is_repairable_error(err):
                    return out
                attempted_sql.append(step_copy["sql"])
                fixed_sql = self._llm_repair_sql(
                    bad_sql=step_copy["sql"],
                    error_msg=err,
                    purpose=step_copy.get("purpose", ""),
                    digest=digest,
                    dialect_name=dialect,
                    query=query,
                    previous_attempts=attempted_sql,
                )
                if not fixed_sql:
                    return out
                repair_events.append({
                    "step": step_idx + 1,
                    "attempt": attempt + 1,
                    "error": err,
                    "old_sql": step_copy["sql"],
                    "new_sql": fixed_sql,
                    "success": None,
                })
                step_copy = {**step_copy, "sql": fixed_sql}
                out = self._execute_single_step(
                    engine, step_copy, step_idx, dialect, allowed, colmap, session_id,
                )
                repair_events[-1]["success"] = bool(out["success"])
            return out

        # Group steps into sequential batches; consecutive parallel steps
        # are batched together for concurrent execution.
        batches: List[List[int]] = []
        current_batch: List[int] = []

        for i, step in enumerate(steps):
            if step.get("parallel") and current_batch:
                current_batch.append(i)
            else:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [i]
        if current_batch:
            batches.append(current_batch)

        for batch in batches:
            if len(batch) == 1:
                idx = batch[0]
                out = _attempt_with_repair(idx, dict(steps[idx]))
                results[idx] = out
                if out.get("explain_warning"):
                    explain_warnings.append(out["explain_warning"])
                if not out["success"]:
                    break
            else:
                # Parallel batch — initial attempts run concurrently; any repair
                # passes run sequentially per failed step (keeps LLM fan-out bounded).
                futures: Dict[concurrent.futures.Future, int] = {}
                for idx in batch:
                    fut = _STEP_EXECUTOR.submit(
                        self._execute_single_step,
                        engine, dict(steps[idx]), idx, dialect, allowed, colmap, session_id,
                    )
                    futures[fut] = idx

                pending_repairs: List[Tuple[int, Dict[str, Any]]] = []
                for fut in concurrent.futures.as_completed(futures):
                    idx = futures[fut]
                    try:
                        out = fut.result(timeout=_QUERY_TIMEOUT_MS / 1000 + 10)
                    except Exception as e:
                        out = {
                            "success": False, "step": idx,
                            "purpose": steps[idx].get("purpose", ""),
                            "error": str(e), "sql": steps[idx]["sql"],
                        }
                    if (
                        not out["success"]
                        and _is_repairable_error(out.get("error") or "")
                    ):
                        pending_repairs.append((idx, out))
                    else:
                        results[idx] = out
                        if out.get("explain_warning"):
                            explain_warnings.append(out["explain_warning"])

                failed = False
                for idx, first_out in pending_repairs:
                    # Seed repair loop from the already-executed failed attempt
                    step_copy = {**steps[idx], "sql": first_out["sql"]}
                    repaired = _attempt_with_repair(
                        idx, step_copy, initial_out=first_out,
                    )
                    results[idx] = repaired
                    if repaired.get("explain_warning"):
                        explain_warnings.append(repaired["explain_warning"])
                    if not repaired["success"]:
                        failed = True

                if failed:
                    break
                if any(r is not None and not r["success"] for r in results):
                    break

        return (
            [r for r in results if r is not None],
            explain_warnings,
            repair_events,
        )

    # ── Main request handler ─────────────────────────────────────

    def process_chat_stream(self, request_data: Dict[str, Any]):
        """Generator that yields SSE-compatible dicts at every major step.

        Yields dicts with ``event`` key (progress/thinking events) and finally
        a result dict **without** ``event`` key that becomes the ``done`` payload.
        """
        thinking: List[ThinkingStep] = []
        session_id = request_data.get("session_id") or f"sql-{os.urandom(4).hex()}"
        query = (request_data.get("query") or request_data.get("message") or "").strip()
        show_sql = bool(request_data.get("show_sql", True))
        clear_history = bool(request_data.get("clear_history", False))
        page = max(1, int(request_data.get("page", 1)))
        page_size = max(1, min(int(request_data.get("page_size", 500)), _FETCH_MAX_ROWS))
        now = datetime.utcnow().isoformat()

        def _progress(message: str, stage: str = "processing"):
            return {"event": "progress", "data": {"stage": stage, "message": message}}

        def _thinking(content: str, tool_name: str = "sql_agent"):
            step = ThinkingStep(type="tool", content=content, tool_name=tool_name)
            thinking.append(step)
            return {"event": "thinking", "data": {"type": "tool", "content": content, "tool_name": tool_name}}

        if clear_history:
            self._session_state.pop(session_id, None)
            _result_cache.clear_session(session_id)

        # ── Config check ─────────────────────────────────────────
        yield _progress("Validating configuration...", "config")
        errs = _config_errors()
        if errs:
            yield {
                "success": False,
                "response": "**Configuration incomplete**\n\n" + "\n".join(f"- {e}" for e in errs),
                "query": query, "thinking_steps": thinking, "timestamp": now,
            }
            return

        conn_url = os.getenv("DATABASE_CONNECTION_STRING", "").strip()
        try:
            url_obj = make_url(conn_url)
            dialect_name = dialect_from_url(url_obj.drivername)
        except Exception as e:
            yield {
                "success": False,
                "response": f"Invalid DATABASE_CONNECTION_STRING (could not parse URL): {e}",
                "query": query, "thinking_steps": thinking, "timestamp": now,
            }
            return

        # ── DB connection test ───────────────────────────────────
        yield _progress("Connecting to database...", "connect")
        yield _thinking(f"Testing connection to {dialect_name} database...", "db_connect")
        try:
            engine, eng_key = _get_engine(conn_url)
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception as e:
            logger.exception("DB connection failed")
            yield {
                "success": False,
                "response": (
                    f"**Database connection failed**\n\n{type(e).__name__}: {e}\n\n"
                    "Check the connection string, network access, and credentials."
                ),
                "query": query, "thinking_steps": thinking, "timestamp": now,
            }
            return

        yield _thinking("Database connection successful.", "db_connect")

        # ── History ──────────────────────────────────────────────
        hist = self._state(session_id)["history"]
        hist_ctx = self._build_history_context(hist)

        if not query:
            yield _thinking("Empty user message.", "llm")
            try:
                empty_reply = ai_service.call_genai(
                    "The user sent an empty message in a SQL database assistant. "
                    "Reply in one or two short sentences inviting a natural-language "
                    "database question. Do not list configuration keys.",
                    temperature=0.3, max_tokens=160,
                )
            except Exception as e:
                empty_reply = f"I did not receive a question. ({e})"
            yield {
                "success": True, "response": empty_reply,
                "query": query, "thinking_steps": thinking, "timestamp": now,
            }
            return

        # ── Schema (with two-pass for large DBs) ────────────────
        yield _progress("Loading database schema...", "schema")
        yield _thinking("Introspecting tables, columns, indexes, and foreign keys…", "schema_load")
        digest = None
        for pkt in self._stream_schema_digest_load(engine, eng_key, False):
            if "__digest__" in pkt:
                digest = pkt["__digest__"]
            else:
                yield pkt
        if digest is None:
            raise RuntimeError("Schema load produced no digest")
        table_count = len(digest.get("tables", []))
        table_names = [t.get("name", "") for t in (digest.get("tables") or [])[:30]]
        yield _thinking(f"Schema loaded: {table_count} tables/views discovered.", "schema_load")
        if table_names:
            preview = ", ".join(table_names[:15])
            if len(table_names) > 15:
                preview += f", … (+{len(table_names) - 15} more)"
            yield _thinking(f"Tables: {preview}", "schema_load")

        budget = _provider_budget()
        force_two_pass = (
            budget["force_two_pass_table_count"] > 0
            and table_count >= budget["force_two_pass_table_count"]
        )
        if digest.get("is_large_db") or force_two_pass:
            reason = (
                f"Large database ({table_count} tables)"
                if digest.get("is_large_db")
                else f"Small-context LLM ({table_count} tables exceeds provider budget of {budget['force_two_pass_table_count']})"
            )
            yield _progress(f"{reason} — selecting relevant tables...", "schema")
            yield _thinking(
                f"{reason}. Running two-pass schema selection.",
                "schema_selection",
            )
            lightweight = None
            for pkt in self._stream_lightweight_digest(engine):
                if "__digest__" in pkt:
                    lightweight = pkt["__digest__"]
                else:
                    yield pkt
            if lightweight is None:
                raise RuntimeError("Lightweight schema summary failed")
            relevant = self._select_relevant_tables(query, lightweight["text"])
            if relevant:
                digest = build_detailed_digest_for_tables(engine, relevant, digest)
                yield _thinking(f"Focused on {len(relevant)} relevant tables.", "schema_selection")

        # ── Orchestration ────────────────────────────────────────
        yield _progress("Generating SQL plan...", "orchestrate")
        yield _thinking("LLM orchestration — analyzing intent, planning SQL, grounding against schema...", "llm_orchestrate")
        try:
            orch = self._llm_orchestrate(dialect_name, digest, query, hist_ctx)
        except Exception as e:
            traceback.print_exc()
            yield {
                "success": False,
                "response": f"Orchestration failed (could not parse model output): {e}",
                "query": query, "thinking_steps": thinking, "timestamp": now,
            }
            return

        outcome = orch["outcome_type"]
        plan_steps = orch.get("steps") or []
        step_count = len(plan_steps)
        yield _thinking(
            f"Plan ready: outcome={outcome}, {step_count} SQL step(s). "
            f"Summary: {orch.get('plan_summary', 'N/A')[:200]}",
            "llm_orchestrate",
        )
        if plan_steps and outcome == "execute_sql":
            for idx, ps in enumerate(plan_steps):
                sql_preview = (ps.get("sql") or "")[:200]
                purpose = ps.get("purpose") or ""
                parallel_tag = " [parallel]" if ps.get("parallel") else ""
                yield _thinking(
                    f"  Step {idx + 1}{parallel_tag}: {purpose}\n    SQL: {sql_preview}",
                    "llm_orchestrate",
                )

        # ── Optional schema refresh ──────────────────────────────
        if orch["refresh_schema"]:
            yield _progress("Refreshing schema from database...", "schema_refresh")
            yield _thinking("Schema cache invalidated; re-introspecting...", "schema_refresh")
            _invalidate_schema_cache(eng_key)
            digest = None
            for pkt in self._stream_schema_digest_load(engine, eng_key, True):
                if "__digest__" in pkt:
                    digest = pkt["__digest__"]
                else:
                    yield pkt
            if digest is None:
                raise RuntimeError("Schema refresh produced no digest")
            if orch["outcome_type"] == "execute_sql":
                yield _thinking("Re-orchestrating with fresh schema...", "llm_orchestrate")
                try:
                    orch = self._llm_orchestrate(dialect_name, digest, query, hist_ctx)
                except Exception as e:
                    traceback.print_exc()
                    yield {
                        "success": False,
                        "response": f"Re-orchestration after schema refresh failed: {e}",
                        "query": query, "thinking_steps": thinking, "timestamp": now,
                    }
                    return

        # ── Plan completeness review ─────────────────────────────
        if outcome == "execute_sql" and orch.get("steps"):
            yield _progress("Reviewing plan completeness...", "review")
            yield _thinking("Reviewing plan for multi-table / multi-entity coverage...", "plan_completeness_review")
            try:
                orch = self._llm_review_plan_completeness(query, orch, digest, dialect_name)
                yield _thinking("Plan review complete.", "plan_completeness_review")
            except Exception as e:
                logger.warning("Plan completeness review failed: %s", e)
                yield _thinking(f"Plan review skipped: {e}", "plan_completeness_review")

        # ── Route: need_clarification ────────────────────────────
        if outcome == "need_clarification":
            msg = (
                orch["clarification"]
                or orch["plan_summary"]
                or "Could you clarify what you need from the database?"
            )
            hist.append({"role": "user", "content": query})
            hist.append({"role": "assistant", "content": msg[:8000]})
            if len(hist) > 40:
                del hist[:-40]
            yield {
                "success": True, "response": msg,
                "query": query, "thinking_steps": thinking,
                "timestamp": now, "orchestration": orch,
            }
            return

        # ── Route: ERD ───────────────────────────────────────────
        if outcome == "erd":
            yield _progress("Building entity-relationship diagram...", "erd")
            yield _thinking("Building Mermaid ERD...", "schema_erd")
            mermaid = build_mermaid_erd(digest)
            yield _progress("Generating schema explanation...", "erd_narrative")
            yield _thinking("LLM narrative for ERD...", "llm")
            erd_budget = _provider_budget()
            try:
                explain = ai_service.call_genai(
                    f"User request:\n{query}\n\n"
                    f"Planner notes:\n{orch.get('plan_summary', '')}\n\n"
                    f"Relationship notes:\n{orch.get('fk_and_constraint_notes', '')}\n\n"
                    f"Mermaid erDiagram:\n```mermaid\n{mermaid}\n```\n\n"
                    "Explain the schema structure and relationships clearly in markdown. "
                    "Do not invent tables beyond the diagram.",
                    temperature=0.2, max_tokens=erd_budget["format_max_tokens"],
                )
            except Exception as e:
                explain = f"(Narrative unavailable: {e})"
            resp = explain + "\n\n### Mermaid ERD\n```mermaid\n" + mermaid + "\n```"
            hist.append({"role": "user", "content": query})
            hist.append({"role": "assistant", "content": resp[:8000]})
            if len(hist) > 40:
                del hist[:-40]
            yield {
                "success": True, "response": resp,
                "query": query, "thinking_steps": thinking,
                "timestamp": now, "mermaid_erd": mermaid, "orchestration": orch,
            }
            return

        # ── Route: execute_sql ───────────────────────────────────
        steps = orch["steps"]
        if not steps:
            yield {
                "success": False,
                "response": (
                    "The planner did not produce executable SQL steps for this "
                    "request. Try rephrasing or ask for clarification."
                ),
                "query": query, "thinking_steps": thinking,
                "timestamp": now, "orchestration": orch,
            }
            return

        # ── Cache check ──────────────────────────────────────────
        sql_list = [s["sql"] for s in steps]
        cached = _result_cache.get(session_id, sql_list)
        if cached and page == 1:
            yield _thinking("Returning cached result (identical query within TTL).", "cache_hit")
            yield {**cached, "cached": True, "timestamp": now}
            return

        # ── Execute ──────────────────────────────────────────────
        allowed = digest.get("allowed_tables") or set()
        colmap = digest.get("columns_by_table") or {}

        yield _progress(f"Executing {len(steps)} SQL step(s)...", "execute")
        for i, step in enumerate(steps):
            purpose = step.get("purpose", "")
            yield _thinking(
                f"Step {i + 1}/{len(steps)}: validating & executing — {purpose}",
                "sql_execute",
            )

        yield _thinking(f"Running {len(steps)} SQL step(s) with guard + EXPLAIN checks...", "sql_execute")

        step_results, explain_warnings, repair_events = self._execute_steps(
            engine, steps, dialect_name, allowed, colmap, session_id,
            digest=digest, query=query,
        )

        for ev in repair_events:
            status = "succeeded" if ev.get("success") else "failed"
            yield _thinking(
                f"Step {ev['step']} repair attempt {ev['attempt']} {status}: "
                f"{ev['error'][:200]}\n"
                f"  old SQL: {ev['old_sql'][:160]}\n"
                f"  new SQL: {ev['new_sql'][:160]}",
                "sql_repair",
            )

        for i, sr in enumerate(step_results):
            if sr["success"]:
                row_count = (sr.get("result") or {}).get("rowcount", 0)
                yield _thinking(
                    f"Step {i + 1} completed: {row_count} rows returned.",
                    "sql_execute",
                )
            else:
                yield _thinking(
                    f"Step {i + 1} failed: {sr.get('error', 'unknown error')}",
                    "sql_execute",
                )

        for ew in explain_warnings:
            yield _thinking(
                f"EXPLAIN warning (step {ew['step']}): {ew['warning']}",
                "explain_analysis",
            )

        # Check for failures
        for sr in step_results:
            if not sr["success"]:
                i = sr["step"]
                repair_note = ""
                attempts_on_step = [e for e in repair_events if e["step"] == i + 1]
                if attempts_on_step:
                    repair_note = (
                        f"\n\n_Repair attempted {len(attempts_on_step)} time(s) without success._"
                    )
                yield {
                    "success": False,
                    "response": (
                        f"**Query blocked or failed (step {i + 1})**\n\n"
                        f"{sr['error']}\n\n"
                        f"SQL:\n```sql\n{sr['sql']}\n```"
                        f"{repair_note}"
                    ),
                    "query": query, "thinking_steps": thinking,
                    "timestamp": now,
                    "generated_sql": sr["sql"] if show_sql else None,
                    "orchestration": orch,
                    "explain_warnings": explain_warnings,
                    "repair_events": repair_events,
                }
                return

        # ── Build combined results ───────────────────────────────
        executed_sql_parts = [sr["sql"] for sr in step_results]
        combined_results = [
            {"purpose": sr["purpose"], "result": sr["result"]}
            for sr in step_results
        ]
        sql_block = "\n\n".join(
            f"-- Step {j + 1}\n{s}" for j, s in enumerate(executed_sql_parts)
        )
        large = _combined_results_large(combined_results)

        # ── Pagination info ──────────────────────────────────────
        total_rows = sum(
            len((b.get("result") or {}).get("rows") or [])
            for b in combined_results
        )
        page_info: Optional[Dict[str, Any]] = None
        if total_rows > page_size:
            total_pages = (total_rows + page_size - 1) // page_size
            page_info = {
                "page": page, "page_size": page_size,
                "total_rows": total_rows, "total_pages": total_pages,
                "has_next": page < total_pages, "has_prev": page > 1,
            }

        # ── Format response ──────────────────────────────────────
        if large:
            yield _progress(f"Formatting large result set ({total_rows} rows)...", "format")
            yield _thinking(
                f"Large result ({total_rows} rows) — paginated tabular view (page {page}).",
                "render_table",
            )
            narrative = _build_tabular_only_response(
                combined_results, sql_block, show_sql, page, page_size,
            )
        else:
            yield _progress("Interpreting results with AI...", "format")
            yield _thinking("LLM interpretation of result set...", "llm_format")
            compact = _compact_for_llm(combined_results)
            llm_narrative = ""
            try:
                fmt_prompt = f"""User asked:
{query}

Planner summary:
{orch.get("plan_summary", "")}

FK / constraint notes:
{orch.get("fk_and_constraint_notes", "")}

Structured execution result (JSON). The "rows" arrays contain the complete result for each step. If "fetch_hit_row_limit" is true the database returned at least that many rows and the server stopped fetching further.
{compact}

Write a short markdown answer (no result table — a full table is added by the system after your text):
- What was executed and why
- Row counts or affected rows
- Brief insights grounded ONLY in the JSON

Do not say the data is "partial", "sampled", or "preview" unless fetch_hit_row_limit is true for that step; in that case mention only that the row cap was reached, not that the user is seeing a sample."""
                fmt_budget = _provider_budget()
                llm_narrative = ai_service.call_genai(
                    fmt_prompt,
                    temperature=0.15,
                    max_tokens=fmt_budget["format_max_tokens"],
                )
            except Exception as e:
                llm_narrative = f"Execution succeeded; interpretation failed ({e}).\n\n"

            # Stream the LLM narrative progressively as response_chunk events
            _CHUNK_SIZE = 80
            for ci in range(0, len(llm_narrative), _CHUNK_SIZE):
                yield {
                    "event": "response_chunk",
                    "data": {"chunk": llm_narrative[ci : ci + _CHUNK_SIZE]},
                }

            # Build the remaining sections (table, SQL, notes)
            extra_sections = _append_full_results_section(combined_results, page, page_size)
            if show_sql:
                extra_sections += "\n\n### Generated SQL\n```sql\n" + sql_block + "\n```"
            if any((b.get("result") or {}).get("truncated") for b in combined_results):
                extra_sections += (
                    f"\n\n_Note: At least one step hit the {_FETCH_MAX_ROWS}-row "
                    "fetch limit; additional rows may exist in the database._"
                )

            # Stream the extra sections too
            for ci in range(0, len(extra_sections), _CHUNK_SIZE):
                yield {
                    "event": "response_chunk",
                    "data": {"chunk": extra_sections[ci : ci + _CHUNK_SIZE]},
                }

            narrative = llm_narrative + extra_sections

        # ── EXPLAIN warnings section ─────────────────────────────
        if explain_warnings:
            narrative += "\n\n### Performance Warnings\n"
            for ew in explain_warnings:
                narrative += f"- **Step {ew['step']}**: {ew['warning']}\n"
                if ew.get("seq_scans"):
                    narrative += f"  - Sequential scans on: {', '.join(ew['seq_scans'])}\n"

        # ── Update session history ───────────────────────────────
        hist.append({"role": "user", "content": query})
        hist.append({"role": "assistant", "content": narrative[:8000]})
        if len(hist) > 40:
            del hist[:-40]

        response = {
            "success": True,
            "response": narrative,
            "query": query,
            "thinking_steps": thinking,
            "timestamp": now,
            "generated_sql": sql_block if show_sql else None,
            "result_preview": combined_results,
            "large_result": large,
            "orchestration": orch,
            "page_info": page_info,
            "explain_warnings": explain_warnings,
            "repair_events": repair_events,
            "cached": False,
            "_emit_reset_before_response_chunks": True,
        }

        # Cache for re-use within TTL
        _result_cache.put(session_id, sql_list, response)

        yield response

    def process_chat(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """Non-streaming wrapper for backward compatibility."""
        result: Dict[str, Any] = {}
        for item in self.process_chat_stream(request_data):
            if isinstance(item, dict) and "event" not in item:
                result = item
        return result or {"success": False, "response": "No result produced.", "query": request_data.get("query", ""), "thinking_steps": [], "timestamp": datetime.utcnow().isoformat()}


sql_db_agent = SqlDbAgent()
