"""Schema introspection, table statistics, index awareness, and ERD generation."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# ── Limits  ──────────────────────────────
_MAX_TABLES_FULL = 200          # Full column detail in schema text
_MAX_COLS_PER_TABLE = 80        # Columns shown per table
_MAX_FK_EDGES = 120             # FK relationships in digest
_MAX_TABLES_ERD = 60            # Entities in Mermaid ERD
_MAX_COLS_ERD = 16              # Columns per entity in ERD
_LARGE_DB_TABLE_THRESHOLD = 150 # Two-pass schema kicks in above this
# Emit SSE progress every N tables/views during introspection (0 = only phase boundaries)
_SCHEMA_SSE_EVERY_N = 4


def _safe_ident(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _format_row_count(count: int) -> str:
    """Human-readable approximate row count."""
    if count < 1_000:
        return str(count)
    if count < 1_000_000:
        return f"~{count // 1_000}K"
    if count < 1_000_000_000:
        return f"~{count // 1_000_000}M"
    return f"~{count // 1_000_000_000}B"


# ── Table row counts from database statistics ────────────────────────

def get_table_row_counts(engine: Engine) -> Dict[str, int]:
    """Approximate row counts from database statistics (no full table scans).

    Returns mapping of lowercase table name -> estimated row count.
    Both fully-qualified (schema.table) and short (table) keys are stored.
    """
    counts: Dict[str, int] = {}
    dialect = engine.dialect.name.lower()
    try:
        with engine.connect() as conn:
            if "postgres" in dialect or "redshift" in dialect:
                rows = conn.execute(text(
                    "SELECT n.nspname || '.' || c.relname, c.reltuples::bigint "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE c.relkind = 'r' "
                    "AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
                )).fetchall()
                for tbl, cnt in rows:
                    c = max(0, int(cnt))
                    counts[tbl.lower()] = c
                    counts[tbl.split(".")[-1].lower()] = c

            elif "mysql" in dialect or "mariadb" in dialect:
                rows = conn.execute(text(
                    "SELECT CONCAT(table_schema, '.', table_name), table_rows "
                    "FROM information_schema.tables "
                    "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
                )).fetchall()
                for tbl, cnt in rows:
                    c = int(cnt or 0)
                    counts[tbl.lower()] = c
                    counts[tbl.split(".")[-1].lower()] = c

            elif "sqlite" in dialect:
                tables = conn.execute(text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )).fetchall()
                for (name,) in tables:
                    try:
                        cnt = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
                        counts[name.lower()] = int(cnt or 0)
                    except Exception:
                        pass

            elif "mssql" in dialect:
                rows = conn.execute(text(
                    "SELECT s.name + '.' + t.name, SUM(p.rows) "
                    "FROM sys.tables t "
                    "JOIN sys.schemas s ON t.schema_id = s.schema_id "
                    "JOIN sys.partitions p ON t.object_id = p.object_id "
                    "  AND p.index_id IN (0, 1) "
                    "GROUP BY s.name, t.name"
                )).fetchall()
                for tbl, cnt in rows:
                    c = int(cnt or 0)
                    counts[tbl.lower()] = c
                    counts[tbl.split(".")[-1].lower()] = c

    except Exception as e:
        logger.warning("Could not fetch row counts: %s", e)
    return counts


# ── Index metadata ───────────────────────────────────────────────────

def get_indexes_for_table(
    insp, table: str, schema: Optional[str],
) -> List[Dict[str, Any]]:
    """Return index metadata for a table."""
    try:
        indexes = insp.get_indexes(table, schema=schema) or []
        return [
            {
                "name": idx.get("name", "?"),
                "columns": idx.get("column_names") or [],
                "unique": bool(idx.get("unique")),
            }
            for idx in indexes
        ]
    except Exception:
        return []


def _format_indexes(indexes: List[Dict[str, Any]]) -> str:
    """Compact one-line index summary for the schema text."""
    if not indexes:
        return ""
    parts = []
    for idx in indexes[:8]:
        prefix = "UNIQUE " if idx["unique"] else ""
        cols = ",".join(idx["columns"])
        parts.append(f"{prefix}{idx['name']}({cols})")
    suffix = f" +{len(indexes) - 8} more" if len(indexes) > 8 else ""
    return " | indexes: " + "; ".join(parts) + suffix


# ── Full schema digest ───────────────────────────────────────────────

def _p(
    with_progress: bool, stage: str, message: str,
) -> Optional[Dict[str, Any]]:
    if not with_progress:
        return None
    return {
        "kind": "progress",
        "stage": stage,
        "message": message,
    }


def iter_build_schema_digest(
    engine: Engine,
    *,
    with_progress: bool = True,
    progress_every: int = _SCHEMA_SSE_EVERY_N,
) -> Iterator[Dict[str, Any]]:
    """Yield optional progress dicts, then a final ``{"kind": "digest", "digest": ...}``.

    Progress items: ``{"kind": "progress", "stage": str, "message": str}`` for SSE mapping.
    """
    if progress_every < 1:
        progress_every = 1

    msg = _p(with_progress, "schema_load", "Connecting to database metadata…")
    if msg:
        yield msg

    insp = inspect(engine)
    schemas: List[Optional[str]] = []
    try:
        schemas = list(insp.get_schema_names())
    except Exception:
        schemas = []

    if not schemas or "information_schema" in schemas:
        try_default: List[Optional[str]] = [None]
    else:
        try_default = [None] + [
            s for s in schemas
            if s not in ("information_schema", "pg_catalog", "pg_toast")
        ]

    msg = _p(
        with_progress,
        "schema_load",
        f"Resolved {len(try_default)} schema(s) to scan; fetching row-count estimates…",
    )
    if msg:
        yield msg

    row_counts = get_table_row_counts(engine)

    msg = _p(with_progress, "schema_load", "Row-count estimates loaded; introspecting tables and columns…")
    if msg:
        yield msg

    tables_payload: List[Dict[str, Any]] = []
    table_names_lower: Set[str] = set()
    columns_by_table: Dict[str, Set[str]] = {}
    table_idx_global = 0

    for schema in try_default:
        schema_label = schema if schema else "(default)"
        try:
            tnames = insp.get_table_names(schema=schema) or []
        except Exception:
            tnames = []

        msg = _p(
            with_progress,
            "schema_load",
            f"Schema {schema_label}: {len(tnames)} table(s) — loading columns, PKs, indexes…",
        )
        if msg:
            yield msg

        for ti, t in enumerate(tnames):
            fq = f"{schema}.{t}" if schema else t
            try:
                cols = insp.get_columns(t, schema=schema) or []
            except Exception:
                cols = []
            try:
                pk = set(
                    insp.get_pk_constraint(t, schema=schema)
                    .get("constrained_columns") or []
                )
            except Exception:
                pk = set()

            indexes = get_indexes_for_table(insp, t, schema)
            col_info: List[Dict[str, Any]] = []
            col_set: Set[str] = set()
            for c in cols:
                nm = c.get("name") or ""
                col_set.add(nm.lower())
                col_info.append({
                    "name": nm,
                    "type": str(c.get("type", "")),
                    "nullable": bool(c.get("nullable", True)),
                    "pk": nm in pk,
                })
            columns_by_table[fq.lower()] = col_set
            table_names_lower.add(t.lower())
            rc = row_counts.get(fq.lower()) or row_counts.get(t.lower())
            tables_payload.append({
                "schema": schema, "name": t, "columns": col_info,
                "indexes": indexes, "row_count": rc,
            })
            table_idx_global += 1
            if with_progress and progress_every and table_idx_global % progress_every == 0:
                yield {
                    "kind": "progress",
                    "stage": "schema_load",
                    "message": (
                        f"Schema {schema_label}: table {ti + 1}/{len(tnames)} "
                        f"(`{t}`) — {table_idx_global} objects so far…"
                    ),
                }

        try:
            vnames = insp.get_view_names(schema=schema) or []
        except Exception:
            vnames = []

        if vnames:
            msg = _p(
                with_progress,
                "schema_load",
                f"Schema {schema_label}: {len(vnames)} view(s) — loading column lists…",
            )
            if msg:
                yield msg

        for vi, v in enumerate(vnames):
            fq = f"{schema}.{v}" if schema else v
            try:
                cols = insp.get_columns(v, schema=schema) or []
            except Exception:
                cols = []
            col_info = []
            col_set: Set[str] = set()
            for c in cols:
                nm = c.get("name") or ""
                col_set.add(nm.lower())
                col_info.append({
                    "name": nm,
                    "type": str(c.get("type", "")),
                    "nullable": bool(c.get("nullable", True)),
                    "pk": False,
                })
            columns_by_table[fq.lower()] = col_set
            table_names_lower.add(v.lower())
            tables_payload.append({
                "schema": schema, "name": v, "columns": col_info,
                "kind": "view", "indexes": [], "row_count": None,
            })
            table_idx_global += 1
            if with_progress and progress_every and table_idx_global % progress_every == 0:
                yield {
                    "kind": "progress",
                    "stage": "schema_load",
                    "message": (
                        f"Schema {schema_label}: view {vi + 1}/{len(vnames)} "
                        f"(`{v}`) — {table_idx_global} objects so far…"
                    ),
                }

    allowed_tables: Set[str] = set()
    for ent in tables_payload:
        sc, nm = ent.get("schema"), ent["name"]
        if sc:
            allowed_tables.add(f"{sc}.{nm}".lower())
        allowed_tables.add(nm.lower())

    base_tables = [e for e in tables_payload if e.get("kind") != "view"]
    n_fk = len(base_tables)
    msg = _p(
        with_progress,
        "schema_load",
        f"Loaded {len(tables_payload)} tables/views; resolving foreign keys ({n_fk} base tables)…",
    )
    if msg:
        yield msg

    fk_edges: List[Tuple[str, str, str, str]] = []
    for fi, ent in enumerate(base_tables):
        t, schema = ent["name"], ent.get("schema")
        try:
            fks = insp.get_foreign_keys(t, schema=schema) or []
        except Exception:
            fks = []
        for fk in fks:
            rt = fk.get("referred_table")
            rs = fk.get("referred_schema")
            if not rt:
                continue
            src = f"{schema}.{t}" if schema else t
            dst = f"{rs}.{rt}" if rs else rt
            fk_edges.append((
                src, dst,
                ",".join(fk.get("constrained_columns") or []),
                ",".join(fk.get("referred_columns") or []),
            ))
        if with_progress and n_fk and progress_every and (fi + 1) % max(progress_every * 3, 8) == 0:
            yield {
                "kind": "progress",
                "stage": "schema_load",
                "message": f"Foreign keys: {fi + 1}/{n_fk} tables processed…",
            }

    msg = _p(with_progress, "schema_load", "Building schema summary text for the model…")
    if msg:
        yield msg

    lines: List[str] = []
    for ent in tables_payload[:_MAX_TABLES_FULL]:
        sc, nm = ent.get("schema"), ent["name"]
        label = f"{sc}.{nm}" if sc else nm
        kind = ent.get("kind", "table")
        cols = ent.get("columns") or []
        rc = ent.get("row_count")
        rc_str = f" (~{_format_row_count(rc)} rows)" if rc is not None else ""
        idx_str = _format_indexes(ent.get("indexes") or [])
        col_str = ", ".join(
            f"{c['name']} ({c['type']})"
            f"{' PK' if c.get('pk') else ''}"
            f"{' NULL' if c.get('nullable') else ' NOT NULL'}"
            for c in cols[:_MAX_COLS_PER_TABLE]
        )
        if len(cols) > _MAX_COLS_PER_TABLE:
            col_str += f", ... +{len(cols) - _MAX_COLS_PER_TABLE} more"
        lines.append(f"- [{kind}] {label}{rc_str}: {col_str}{idx_str}")

    schema_text = "Database schema (use ONLY these identifiers):\n" + "\n".join(lines)
    if len(tables_payload) > _MAX_TABLES_FULL:
        schema_text += (
            f"\n\n... {len(tables_payload) - _MAX_TABLES_FULL} additional "
            "tables/views omitted for brevity."
        )

    yield {
        "kind": "digest",
        "digest": {
            "text": schema_text,
            "tables": tables_payload,
            "table_names_lower": table_names_lower,
            "columns_by_table": columns_by_table,
            "fk_edges": fk_edges[:_MAX_FK_EDGES],
            "allowed_tables": allowed_tables,
            "row_counts": row_counts,
            "is_large_db": len(tables_payload) > _LARGE_DB_TABLE_THRESHOLD,
        },
    }


def build_schema_digest(engine: Engine) -> Dict[str, Any]:
    """Tables, columns, PKs, FKs, indexes, and row counts for LLM grounding."""
    digest: Optional[Dict[str, Any]] = None
    for item in iter_build_schema_digest(engine, with_progress=False):
        if item.get("kind") == "digest":
            digest = item["digest"]
    if digest is None:
        raise RuntimeError("iter_build_schema_digest produced no digest")
    return digest


# ── Lightweight digest (pass 1 for large databases) ──────────────────

def iter_build_lightweight_digest(
    engine: Engine,
    *,
    with_progress: bool = True,
    progress_every: int = _SCHEMA_SSE_EVERY_N,
) -> Iterator[Dict[str, Any]]:
    """Yield progress, then ``{"kind": "digest", "digest": ...}`` (table summary pass)."""
    if progress_every < 1:
        progress_every = 1

    msg = _p(with_progress, "schema_selection", "Large DB: building lightweight table summary…")
    if msg:
        yield msg

    insp = inspect(engine)
    schemas: List[Optional[str]] = []
    try:
        schemas = list(insp.get_schema_names())
    except Exception:
        schemas = []

    if not schemas or "information_schema" in schemas:
        try_default: List[Optional[str]] = [None]
    else:
        try_default = [None] + [
            s for s in schemas
            if s not in ("information_schema", "pg_catalog", "pg_toast")
        ]

    msg = _p(with_progress, "schema_selection", "Fetching row-count estimates for lightweight pass…")
    if msg:
        yield msg

    row_counts = get_table_row_counts(engine)
    table_summaries: List[Dict[str, Any]] = []
    all_names: Set[str] = set()
    obj_idx = 0

    for schema in try_default:
        schema_label = schema if schema else "(default)"
        try:
            tnames = insp.get_table_names(schema=schema) or []
        except Exception:
            tnames = []

        msg = _p(
            with_progress,
            "schema_selection",
            f"Schema {schema_label}: summarizing {len(tnames)} table(s)…",
        )
        if msg:
            yield msg

        for ti, t in enumerate(tnames):
            fq = f"{schema}.{t}" if schema else t
            try:
                cols = insp.get_columns(t, schema=schema) or []
            except Exception:
                cols = []
            rc = row_counts.get(fq.lower()) or row_counts.get(t.lower())
            col_names = [c.get("name", "") for c in cols[:10]]
            table_summaries.append({
                "schema": schema, "name": t, "kind": "table",
                "col_count": len(cols), "row_count": rc,
                "sample_columns": col_names,
            })
            all_names.add(t.lower())
            obj_idx += 1
            if with_progress and progress_every and obj_idx % progress_every == 0:
                yield {
                    "kind": "progress",
                    "stage": "schema_selection",
                    "message": (
                        f"Lightweight pass: table {ti + 1}/{len(tnames)} in {schema_label} "
                        f"(`{t}`) — {obj_idx} objects…"
                    ),
                }

        try:
            vnames = insp.get_view_names(schema=schema) or []
        except Exception:
            vnames = []

        if vnames:
            msg = _p(
                with_progress,
                "schema_selection",
                f"Schema {schema_label}: summarizing {len(vnames)} view(s)…",
            )
            if msg:
                yield msg

        for vi, v in enumerate(vnames):
            fq = f"{schema}.{v}" if schema else v
            try:
                cols = insp.get_columns(v, schema=schema) or []
            except Exception:
                cols = []
            col_names = [c.get("name", "") for c in cols[:10]]
            table_summaries.append({
                "schema": schema, "name": v, "kind": "view",
                "col_count": len(cols), "row_count": None,
                "sample_columns": col_names,
            })
            all_names.add(v.lower())
            obj_idx += 1
            if with_progress and progress_every and obj_idx % progress_every == 0:
                yield {
                    "kind": "progress",
                    "stage": "schema_selection",
                    "message": (
                        f"Lightweight pass: view {vi + 1}/{len(vnames)} in {schema_label} "
                        f"(`{v}`) — {obj_idx} objects…"
                    ),
                }

    msg = _p(with_progress, "schema_selection", "Building lightweight summary text…")
    if msg:
        yield msg

    lines: List[str] = []
    for t in table_summaries:
        sc, nm = t.get("schema"), t["name"]
        label = f"{sc}.{nm}" if sc else nm
        kind = t["kind"]
        rc = t.get("row_count")
        rc_str = f", ~{_format_row_count(rc)} rows" if rc is not None else ""
        sample = ", ".join(t.get("sample_columns") or [])
        lines.append(f"- [{kind}] {label} ({t['col_count']} cols{rc_str}): {sample} ...")

    summary_text = (
        f"Database has {len(table_summaries)} tables/views. "
        "Summary (sample columns shown):\n" + "\n".join(lines)
    )

    yield {
        "kind": "digest",
        "digest": {
            "text": summary_text,
            "table_summaries": table_summaries,
            "all_names": all_names,
            "row_counts": row_counts,
        },
    }


def build_lightweight_digest(engine: Engine) -> Dict[str, Any]:
    """Table names + row counts + sample columns — no full column detail.

    Used when the database has > _LARGE_DB_TABLE_THRESHOLD tables so the LLM
    can select relevant tables before we introspect their full schemas.
    """
    digest: Optional[Dict[str, Any]] = None
    for item in iter_build_lightweight_digest(engine, with_progress=False):
        if item.get("kind") == "digest":
            digest = item["digest"]
    if digest is None:
        raise RuntimeError("iter_build_lightweight_digest produced no digest")
    return digest


# ── Focused digest (pass 2 for large databases) ─────────────────────

def build_detailed_digest_for_tables(
    engine: Engine,
    target_tables: Set[str],
    full_digest: Dict[str, Any],
) -> Dict[str, Any]:
    """Rebuild schema text focusing on *target_tables* with full column detail.

    Tables not in the target set are listed with abbreviated info so the LLM
    is still aware they exist but doesn't waste context on them.
    """
    if not target_tables:
        return full_digest

    target_lower = {t.lower() for t in target_tables}
    focused: List[Dict[str, Any]] = []
    other_count = 0

    for ent in full_digest.get("tables") or []:
        nm = ent.get("name", "").lower()
        sc = ent.get("schema")
        fq = f"{sc}.{nm}".lower() if sc else nm
        if nm in target_lower or fq in target_lower:
            focused.append(ent)

    lines: List[str] = []
    # Full detail for focused tables
    for ent in focused:
        sc, nm = ent.get("schema"), ent["name"]
        label = f"{sc}.{nm}" if sc else nm
        kind = ent.get("kind", "table")
        cols = ent.get("columns") or []
        rc = ent.get("row_count")
        rc_str = f" (~{_format_row_count(rc)} rows)" if rc is not None else ""
        idx_str = _format_indexes(ent.get("indexes") or [])
        col_str = ", ".join(
            f"{c['name']} ({c['type']})"
            f"{' PK' if c.get('pk') else ''}"
            f"{' NULL' if c.get('nullable') else ' NOT NULL'}"
            for c in cols[:_MAX_COLS_PER_TABLE]
        )
        if len(cols) > _MAX_COLS_PER_TABLE:
            col_str += f", ... +{len(cols) - _MAX_COLS_PER_TABLE} more"
        lines.append(f"- [{kind}] {label}{rc_str} [RELEVANT]: {col_str}{idx_str}")

    # Abbreviated listing for remaining tables
    for ent in full_digest.get("tables") or []:
        nm = ent.get("name", "").lower()
        sc = ent.get("schema")
        fq = f"{sc}.{nm}".lower() if sc else nm
        if nm in target_lower or fq in target_lower:
            continue
        other_count += 1
        if other_count <= 30:
            label = f"{sc}.{ent['name']}" if sc else ent["name"]
            kind = ent.get("kind", "table")
            rc = ent.get("row_count")
            rc_str = f" (~{_format_row_count(rc)} rows)" if rc is not None else ""
            lines.append(f"- [{kind}] {label}{rc_str}: (columns available on request)")

    if other_count > 30:
        lines.append(f"- ... +{other_count - 30} more tables/views")

    schema_text = (
        "Database schema — tables marked [RELEVANT] have full column detail:\n"
        + "\n".join(lines)
    )

    return {
        **full_digest,
        "text": schema_text,
        "focused_tables": focused,
    }


# ── Mermaid ERD ──────────────────────────────────────────────────────

def build_mermaid_erd(digest: Dict[str, Any]) -> str:
    """Entity-relationship diagram (Mermaid) from FK edges."""
    edges = digest.get("fk_edges") or []
    if not edges:
        tables = digest.get("tables") or []
        if not tables:
            return "erDiagram\n  %% No tables discovered"
        lines = ["erDiagram"]
        for ent in tables[:_MAX_TABLES_ERD]:
            sc, nm = ent.get("schema"), ent["name"]
            eid = _safe_ident(f"{sc}_{nm}" if sc else nm)
            lines.append(f"  {eid} {{")
            for c in (ent.get("columns") or [])[:_MAX_COLS_ERD]:
                lines.append(
                    f"    {str(c.get('type', 'unknown'))[:24]} "
                    f"{_safe_ident(c.get('name', 'col'))}"
                )
            lines.append("  }")
        return "\n".join(lines)

    lines = ["erDiagram"]
    seen_ent: Set[str] = set()
    for src, dst, scols, _ in edges:
        sid = _safe_ident(src.replace(".", "_"))
        did = _safe_ident(dst.replace(".", "_"))
        if sid not in seen_ent:
            lines.append(f"  {sid} {{}}")
            seen_ent.add(sid)
        if did not in seen_ent:
            lines.append(f"  {did} {{}}")
            seen_ent.add(did)
        rel = (scols or "fk").replace(" ", "")[:40]
        lines.append(f'  {sid} ||--o{{ {did} : "{rel}"')

    return "\n".join(lines)
