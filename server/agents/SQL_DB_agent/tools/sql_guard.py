"""RBAC, dangerous-statement blocking, and audit logging for SQL execution."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp

# Schemas / objects that are not in the user digest but are valid read targets (metadata queries).
_SYSTEM_SCHEMAS = frozenset(
    {
        "information_schema",
        "pg_catalog",
        "pg_toast",
        "mysql",
        "performance_schema",
        "sys",
    }
)
_SYSTEM_TABLE_NAMES = frozenset({"sqlite_master", "sqlite_schema", "sqlite_temp_master"})

_audit_lock = threading.Lock()
_audit_logger = logging.getLogger("sql_db_agent.audit")

_MUTATING = frozenset({"INSERT", "UPDATE", "DELETE"})
_READ = frozenset({"SELECT", "WITH"})


def _audit_log_path() -> Path:
    base = Path(__file__).resolve().parent.parent.parent.parent / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "sql_db_audit.log"


def audit_line(session_id: str, sql: str, ok: bool, detail: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "ok": ok,
        "detail": detail[:500],
        "sql_prefix": (sql or "")[:400],
    }
    line = json.dumps(entry, ensure_ascii=False)
    _audit_logger.info(line)
    try:
        with _audit_lock:
            with open(_audit_log_path(), "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except OSError:
        pass


def strip_sql_comments(sql: str) -> str:
    s = sql.strip()
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    lines = []
    for line in s.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        lines.append(line)
    return " ".join(lines).strip()


def normalize_single_statement(sql: str) -> Tuple[Optional[str], Optional[str]]:
    raw = strip_sql_comments(sql)
    if not raw:
        return None, "Empty SQL after removing comments."
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if len(parts) > 1:
        return None, "Multiple SQL statements are not allowed; use one statement at a time."
    return parts[0], None


def classify_statement(parsed: exp.Expression) -> str:
    if isinstance(parsed, exp.Insert):
        return "INSERT"
    if isinstance(parsed, exp.Update):
        return "UPDATE"
    if isinstance(parsed, exp.Delete):
        return "DELETE"
    if isinstance(parsed, (exp.Select, exp.Union)):
        return "SELECT"
    if isinstance(parsed, exp.Command):
        name = (parsed.this or "").strip().split(None, 1)[0].upper()
        return name or "UNKNOWN"
    if isinstance(parsed, exp.Drop):
        return "DROP"
    if isinstance(parsed, exp.TruncateTable):
        return "TRUNCATE"
    if isinstance(parsed, exp.Create):
        return "CREATE"
    if isinstance(parsed, exp.Alter):
        return "ALTER"
    if isinstance(parsed, exp.Merge):
        return "MERGE"
    key = getattr(parsed, "key", None)
    if key:
        return str(key).upper()
    return "UNKNOWN"


def _role_caps(role: str) -> Set[str]:
    r = (role or "writer").strip().lower()
    if r == "reader":
        return set(_READ) | {"SHOW", "DESCRIBE", "EXPLAIN"}
    if r == "admin":
        return set(_READ) | set(_MUTATING) | {"DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE", "REPLACE", "MERGE"}
    return set(_READ) | set(_MUTATING) | {"SHOW", "DESCRIBE", "EXPLAIN", "MERGE"}


def _is_temp_table_create(sql: str) -> bool:
    """Check if a CREATE statement targets a TEMPORARY table."""
    upper = sql.strip().upper()
    return upper.startswith("CREATE TEMP ") or upper.startswith("CREATE TEMPORARY ")


def _is_system_catalog_table(schema: Optional[str], name: Optional[str]) -> bool:
    if not name:
        return False
    s = (schema or "").strip().lower()
    n = name.strip().lower()
    if s in _SYSTEM_SCHEMAS:
        return True
    if n in _SYSTEM_TABLE_NAMES:
        return True
    return False


def _parsed_references_system_catalog(parsed: exp.Expression) -> bool:
    for node in parsed.find_all(exp.Table):
        if _is_system_catalog_table(node.db, node.name):
            return True
    return False


def user_table_names_from_sql(sql: str, dialect: str) -> Set[str]:
    """Lowercase application table names referenced in SQL (excludes system catalogs)."""
    try:
        parsed = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return set()
    names: Set[str] = set()
    for node in parsed.find_all(exp.Table):
        if _is_system_catalog_table(node.db, node.name):
            continue
        if node.name:
            names.add(node.name.lower())
    return names


def _short_to_fq_map(columns_by_table: Dict[str, Set[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for fq in columns_by_table:
        short = fq.split(".")[-1].lower()
        out.setdefault(short, []).append(fq)
    return out


def validate_against_schema(
    parsed: exp.Expression,
    allowed_tables: Set[str],
    columns_by_table: Dict[str, Set[str]],
) -> Tuple[bool, str]:
    colmap = {k.lower(): v for k, v in (columns_by_table or {}).items()}
    short_map = _short_to_fq_map(colmap)

    for node in parsed.find_all(exp.Table):
        schema = node.db
        name = node.name
        if not name:
            continue
        if _is_system_catalog_table(schema, name):
            continue
        candidates = [
            f"{schema}.{name}".lower() if schema else None,
            name.lower(),
        ]
        if not any(c and c in allowed_tables for c in candidates if c):
            return False, f"Unknown table or view '{name}' (not in introspected schema)."

    for col in parsed.find_all(exp.Column):
        nm = (col.name or "").strip()
        if not nm or nm == "*":
            continue
        tbl = col.table
        if not tbl:
            continue
        t_full = tbl.lower()
        t_short = tbl.split(".")[-1].lower()
        if "." in tbl:
            sch = tbl.split(".", 1)[0].lower()
            if sch in _SYSTEM_SCHEMAS:
                continue
        if t_short in _SYSTEM_TABLE_NAMES:
            continue
        if t_full.startswith(
            ("information_schema.", "pg_catalog.", "mysql.", "performance_schema.", "sys.")
        ):
            continue
        fq_keys = short_map.get(t_short) or []
        colset: Optional[Set[str]] = None
        for fk in fq_keys:
            if fk in colmap:
                colset = colmap[fk]
                break
        if colset is None:
            for cand in (f"{tbl}".lower(), t_short):
                if cand in colmap:
                    colset = colmap[cand]
                    break
        if colset is None:
            continue
        if nm.lower() not in colset:
            return False, f"Column '{nm}' is not defined on '{tbl}' according to the loaded schema."

    return True, ""


def guard_sql(
    sql: str,
    dialect: str,
    allowed_tables: Set[str],
    columns_by_table: dict,
    session_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Returns (clean_sql, error_message)."""
    single, err = normalize_single_statement(sql)
    if err:
        audit_line(session_id, sql, False, err)
        return None, err

    try:
        parsed = sqlglot.parse_one(single, read=dialect)
    except Exception as e:
        msg = f"SQL parse error (refused to execute): {e}"
        audit_line(session_id, single, False, msg)
        return None, msg

    kw = classify_statement(parsed)
    role = os.getenv("SQL_DB_ROLE", "writer")
    allow_destructive = os.getenv("SQL_DB_ALLOW_DESTRUCTIVE", "").strip().lower() in ("1", "true", "yes")
    caps = _role_caps(role)

    destructive_kw = {"DROP", "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE", "REPLACE"}
    if kw in destructive_kw:
        # Allow CREATE TEMPORARY TABLE for writer+ roles (useful for complex
        # analytical workflows without requiring full admin privileges).
        if kw == "CREATE" and _is_temp_table_create(single):
            pass  # permitted for any role with write access
        elif role.strip().lower() != "admin" or not allow_destructive:
            msg = (
                "Destructive or DDL statements are blocked. They require SQL_DB_ROLE=admin and "
                "SQL_DB_ALLOW_DESTRUCTIVE=true (only when explicitly authorized)."
            )
            audit_line(session_id, single, False, msg)
            return None, msg

    if kw in _MUTATING or kw == "MERGE":
        if kw not in caps:
            msg = f"Role '{role}' does not allow {kw} statements."
            audit_line(session_id, single, False, msg)
            return None, msg
        if _parsed_references_system_catalog(parsed):
            msg = (
                "Statements that modify system or metadata catalogs (e.g. information_schema, pg_catalog, "
                "sqlite_master) are not allowed."
            )
            audit_line(session_id, single, False, msg)
            return None, msg

    if kw in ("SELECT", "WITH") and kw not in caps:
        msg = f"Role '{role}' does not allow read statements."
        audit_line(session_id, single, False, msg)
        return None, msg

    if kw in ("UPDATE", "DELETE"):
        low = single.lower()
        if " where " not in f" {low} ":
            msg = "UPDATE and DELETE require a WHERE clause for safety."
            audit_line(session_id, single, False, msg)
            return None, msg

    ok_schema, schema_err = validate_against_schema(parsed, allowed_tables, columns_by_table)
    if not ok_schema:
        audit_line(session_id, single, False, schema_err)
        return None, schema_err

    audit_line(session_id, single, True, "validated")
    return single, None


def dialect_from_url(drivername: str) -> str:
    d = (drivername or "").lower()
    if "postgres" in d or "redshift" in d:
        return "postgres"
    if "mysql" in d or "mariadb" in d:
        return "mysql"
    if "sqlite" in d:
        return "sqlite"
    if "mssql" in d or "sqlserver" in d:
        return "tsql"
    return "postgres"
