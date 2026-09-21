"""Execute validated SQL with timeouts, EXPLAIN analysis, and safe chunked fetching."""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ── Timeout defaults ─────────────────────────────────────────────────
_DEFAULT_TIMEOUT_MS = 30_000   # 30 seconds
_MAX_TIMEOUT_MS = 300_000      # 5 minutes
_FETCH_CHUNK_SIZE = 5_000      # rows per fetch-many batch (limits peak memory)


def _serialize_cell(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, (bytes, memoryview)):
        return f"<binary {len(v)} bytes>"
    return v


# ── Statement timeout (per dialect) ─────────────────────────────────

def _set_statement_timeout(conn, dialect: str, timeout_ms: int) -> None:
    """Set a statement-level query timeout so runaway queries are killed."""
    try:
        if "postgres" in dialect or "redshift" in dialect:
            conn.execute(text(f"SET statement_timeout = {timeout_ms}"))
        elif "mysql" in dialect or "mariadb" in dialect:
            conn.execute(text(f"SET max_execution_time = {timeout_ms}"))
        elif "mssql" in dialect or "tsql" in dialect:
            conn.execute(text(f"SET LOCK_TIMEOUT {timeout_ms}"))
        # SQLite has no native statement timeout
    except Exception as e:
        logger.warning("Could not set statement timeout (%s): %s", dialect, e)


# ── EXPLAIN plan analysis ────────────────────────────────────────────

def _find_pg_seq_scans(plan: dict, seq_scans: list, warnings: list) -> None:
    """Recursively find Seq Scan nodes in a PostgreSQL EXPLAIN JSON plan."""
    node_type = plan.get("Node Type", "")
    if "Seq Scan" in node_type:
        table = plan.get("Relation Name", "unknown")
        rows = plan.get("Plan Rows", 0)
        seq_scans.append(table)
        if rows > 10_000:
            warnings.append(
                f"Sequential scan on '{table}' (est. {rows:,} rows) "
                "-- consider adding a WHERE filter or check for missing indexes"
            )
    for child in plan.get("Plans", []):
        _find_pg_seq_scans(child, seq_scans, warnings)


def run_explain(engine: Engine, sql: str, dialect: str) -> Dict[str, Any]:
    """Run EXPLAIN on a SELECT/WITH query and return parsed plan analysis.

    Returns dict with keys: supported, estimated_rows, estimated_cost,
    seq_scans (list of table names), warnings (list of strings), raw.
    """
    result: Dict[str, Any] = {
        "supported": False,
        "estimated_rows": None,
        "estimated_cost": None,
        "seq_scans": [],
        "warnings": [],
        "raw": "",
    }

    # Only EXPLAIN read queries
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith(("SELECT", "WITH")):
        return result

    try:
        with engine.connect() as conn:
            # ── PostgreSQL / Redshift ──────────────────────────────
            if "postgres" in dialect or "redshift" in dialect:
                plan_rows = conn.execute(
                    text(f"EXPLAIN (FORMAT JSON) {sql}")
                ).fetchall()
                result["supported"] = True
                if plan_rows:
                    plan_json = plan_rows[0][0]
                    if isinstance(plan_json, str):
                        plan_json = json.loads(plan_json)
                    if isinstance(plan_json, list) and plan_json:
                        plan = plan_json[0].get("Plan", {})
                        result["estimated_rows"] = int(plan.get("Plan Rows", 0))
                        result["estimated_cost"] = float(plan.get("Total Cost", 0))
                        result["raw"] = json.dumps(plan_json, indent=2)[:2000]
                        _find_pg_seq_scans(
                            plan, result["seq_scans"], result["warnings"]
                        )

            # ── MySQL / MariaDB ────────────────────────────────────
            elif "mysql" in dialect or "mariadb" in dialect:
                plan_rows = conn.execute(text(f"EXPLAIN {sql}")).fetchall()
                result["supported"] = True
                total_rows = 0
                for row in plan_rows:
                    row_dict = (
                        dict(row._mapping)
                        if hasattr(row, "_mapping")
                        else {}
                    )
                    est = row_dict.get("rows") or 0
                    total_rows += int(est)
                    scan_type = str(row_dict.get("type", "")).upper()
                    table = row_dict.get("table", "")
                    if scan_type == "ALL" and table:
                        result["seq_scans"].append(table)
                        result["warnings"].append(
                            f"Full table scan on '{table}' (est. {est} rows)"
                        )
                result["estimated_rows"] = total_rows
                result["raw"] = str(plan_rows)[:2000]

            # ── SQLite ─────────────────────────────────────────────
            elif "sqlite" in dialect:
                plan_rows = conn.execute(
                    text(f"EXPLAIN QUERY PLAN {sql}")
                ).fetchall()
                result["supported"] = True
                raw_lines: List[str] = []
                for row in plan_rows:
                    line = str(row)
                    raw_lines.append(line)
                    line_upper = line.upper()
                    if "SCAN" in line_upper and "INDEX" not in line_upper:
                        parts = line_upper.split("SCAN TABLE")
                        if len(parts) > 1:
                            tbl = parts[1].strip().split()[0] if parts[1].strip() else ""
                            if tbl:
                                result["seq_scans"].append(tbl.lower())
                                result["warnings"].append(
                                    f"Full table scan on '{tbl}'"
                                )
                result["raw"] = "\n".join(raw_lines)[:2000]

            # MSSQL EXPLAIN (SET SHOWPLAN_XML) is complex; skip for now.

    except Exception as e:
        result["supported"] = True
        result["warnings"].append(f"EXPLAIN failed: {e}")
        logger.warning("EXPLAIN failed for dialect=%s: %s", dialect, e)

    return result


# ── SQL execution ────────────────────────────────────────────────────

def run_sql(
    engine: Engine,
    sql: str,
    max_rows: int = 500,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    dialect: str = "postgres",
) -> Dict[str, Any]:
    """Execute SQL with a per-statement timeout and chunked result fetching.

    Chunked fetching limits peak memory — instead of pulling *max_rows* rows
    in one shot we iterate in batches of _FETCH_CHUNK_SIZE.
    """
    timeout_ms = min(timeout_ms, _MAX_TIMEOUT_MS)

    with engine.connect() as conn:
        with conn.begin():
            _set_statement_timeout(conn, dialect, timeout_ms)
            result = conn.execute(text(sql))

            if result.returns_rows:
                cols: List[str] = list(result.keys())
                rows: List[List[Any]] = []
                truncated = False
                remaining = max_rows + 1

                while remaining > 0:
                    batch_size = min(remaining, _FETCH_CHUNK_SIZE)
                    batch = result.fetchmany(batch_size)
                    if not batch:
                        break
                    for row in batch:
                        rows.append([_serialize_cell(x) for x in row])
                    remaining -= len(batch)

                if len(rows) > max_rows:
                    truncated = True
                    rows = rows[:max_rows]

                return {
                    "columns": cols,
                    "rows": rows,
                    "truncated": truncated,
                    "rowcount": len(rows),
                }

            rc = result.rowcount
            return {
                "columns": [],
                "rows": [],
                "truncated": False,
                "rowcount": rc if rc is not None else 0,
            }
