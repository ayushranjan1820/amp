"""Server-side database introspection (ERD), read-only extract, and load for the ETL agent.

Connections use SQLAlchemy; credentials come from environment (user_config / catalog keys).
Sandboxed transform code never receives connection strings.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

ENV_SOURCE_DB = "SOURCE_DATABASE_CONNECTION_STRING"
ENV_DEST_DB = "DESTINATION_DATABASE_CONNECTION_STRING"

_DEFAULT_MAX_EXTRACT = 50_000


def connection_fingerprint(uri: str) -> str:
    return hashlib.sha256(uri.strip().encode("utf-8")).hexdigest()[:20]


def create_engine_from_uri(uri: str) -> Engine:
    """Create a SQLAlchemy engine with sane defaults for short-lived agent requests."""
    return create_engine(uri.strip(), pool_pre_ping=True, pool_recycle=300)


def _is_system_schema(dialect: str, schema: str) -> bool:
    s = (schema or "").lower()
    if dialect == "postgresql":
        if s in ("information_schema", "pg_catalog", "pg_toast"):
            return True
        if s.startswith("pg_temp_") or s.startswith("pg_toast_temp"):
            return True
    if dialect in ("mysql", "mariadb"):
        if s in ("information_schema", "mysql", "performance_schema", "sys"):
            return True
    if dialect == "mssql":
        if s.lower() in ("information_schema",):
            return True
    return False


def _list_schema_qualified_tables(insp, engine: Engine) -> List[Tuple[Optional[str], str]]:
    """Return (schema, table) pairs so non-default schemas (e.g. auth.admin_users) appear in the ERD."""
    dialect = (engine.dialect.name or "").lower()
    out: List[Tuple[Optional[str], str]] = []

    if dialect == "postgresql":
        try:
            for schema in sorted(insp.get_schema_names()):
                if _is_system_schema(dialect, schema):
                    continue
                for t in sorted(insp.get_table_names(schema=schema)):
                    out.append((schema, t))
        except Exception as e:
            logger.warning("Multi-schema PostgreSQL introspection failed, falling back: %s", e)
            return []
        return out

    if dialect == "mssql":
        try:
            for schema in sorted(insp.get_schema_names()):
                if _is_system_schema(dialect, schema):
                    continue
                for t in sorted(insp.get_table_names(schema=schema)):
                    out.append((schema, t))
        except Exception as e:
            logger.warning("Multi-schema SQL Server introspection failed, falling back: %s", e)
            return []
        return out

    return []


def _erd_table_label(schema: Optional[str], tname: str) -> str:
    if schema:
        return f"{schema}.{tname}"
    return tname


def build_erd_text(engine: Engine, label: str) -> str:
    """Build a text ERD-style summary: tables, columns, PKs, FKs."""
    lines: list[str] = [f"### {label}", ""]
    try:
        insp = inspect(engine)
        pairs = _list_schema_qualified_tables(insp, engine)
        if not pairs:
            table_names = sorted(insp.get_table_names())
            pairs = [(None, t) for t in table_names]
    except Exception as e:
        lines.append(f"(Introspection failed: {e})")
        return "\n".join(lines)

    if not pairs:
        lines.append("(No tables visible to this user / empty schema.)")
        return "\n".join(lines)

    for schema, tname in pairs:
        label_name = _erd_table_label(schema, tname)
        try:
            if schema is not None:
                cols = insp.get_columns(tname, schema=schema)
                pk = insp.get_pk_constraint(tname, schema=schema) or {}
                fks = insp.get_foreign_keys(tname, schema=schema) or []
            else:
                cols = insp.get_columns(tname)
                pk = insp.get_pk_constraint(tname) or {}
                fks = insp.get_foreign_keys(tname) or []
            pk_cols = pk.get("constrained_columns") or []
        except Exception as e:
            lines.append(f"TABLE `{label_name}` (columns unavailable: {e})")
            lines.append("")
            continue

        lines.append(f"TABLE `{label_name}`")
        for c in cols:
            ctype = c.get("type")
            ctype_s = str(ctype) if ctype is not None else "unknown"
            null = c.get("nullable", True)
            lines.append(f"  - {c['name']}: {ctype_s} nullable={null}")
        if pk_cols:
            lines.append(f"  PRIMARY KEY: {', '.join(pk_cols)}")
        for fk in fks:
            ref_t = fk.get("referred_table", "?")
            ref_c = fk.get("referred_columns", [])
            loc_c = fk.get("constrained_columns", [])
            lines.append(f"  FK: {list(loc_c)} -> {ref_t}.{list(ref_c)}")
        lines.append("")

    return "\n".join(lines).rstrip()


def validate_read_only_select(sql: str) -> Tuple[Optional[str], Optional[str]]:
    """Ensure a single read-only SELECT (or WITH ... SELECT). Returns (normalized_sql, error)."""
    s = (sql or "").strip()
    if s.startswith("```"):
        lines = s.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    s = s.rstrip().rstrip(";").strip()
    if not s:
        return None, "Empty SQL."
    if ";" in s:
        return None, "Multiple statements are not allowed."

    su = s.upper()
    if not (su.startswith("SELECT") or su.startswith("WITH")):
        return None, "SQL must be a single SELECT or WITH ... SELECT statement."

    padded = f" {su} "
    forbidden_tokens = (
        " INSERT ", " UPDATE ", " DELETE ", " DROP ", " ALTER ", " CREATE ",
        " TRUNCATE ", " GRANT ", " REVOKE ", " MERGE ", " CALL ", " INTO ",
    )
    for tok in forbidden_tokens:
        if tok in padded:
            return None, f"Forbidden SQL construct detected ({tok.strip()})."

    return s, None


def read_dataframe(engine: Engine, sql: str, max_rows: Optional[int] = None) -> pd.DataFrame:
    """Execute validated read-only SQL and return a DataFrame (row-capped for safety)."""
    cap = max_rows if max_rows is not None else max_extract_rows()
    chunks: list[pd.DataFrame] = []
    n = 0
    with engine.connect() as conn:
        for chunk in pd.read_sql(text(sql), conn, chunksize=min(50_000, cap)):
            chunks.append(chunk)
            n += len(chunk)
            if n >= cap:
                break
    if not chunks:
        return pd.DataFrame()
    df = pd.concat(chunks, ignore_index=True)
    if len(df) > cap:
        df = df.iloc[:cap].copy()
    return df


def load_dataframe(
    engine: Engine,
    table_name: str,
    df: pd.DataFrame,
    *,
    if_exists: str = "append",
    schema: Optional[str] = None,
) -> Tuple[bool, str]:
    """Write DataFrame to destination. Returns (success, message)."""
    if if_exists not in ("fail", "replace", "append"):
        return False, f"Invalid if_exists: {if_exists}"
    try:
        chunksize = min(1000, max(100, len(df) // 10 or 100))
        kwargs: Dict[str, Any] = {
            "name": table_name,
            "con": engine,
            "if_exists": if_exists,
            "index": False,
            "chunksize": chunksize,
        }
        if schema:
            kwargs["schema"] = schema
        df.to_sql(**kwargs)
        return True, f"Loaded {len(df)} rows into `{table_name}` (if_exists={if_exists})."
    except Exception as e:
        logger.exception("ETL load to destination failed")
        return False, f"Load failed: {e}"


def max_extract_rows() -> int:
    raw = (os.getenv("ETL_MAX_EXTRACT_ROWS") or "").strip()
    if raw.isdigit():
        return min(int(raw), 500_000)
    return _DEFAULT_MAX_EXTRACT
