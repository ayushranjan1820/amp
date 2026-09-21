"""One-shot migration: copy all data from PostgreSQL (DATABASE_URL) into MongoDB
(CORE_SYSTEM_MONGO_DB).

Run once after the schema migration to MongoDB:

    cd server
    python migrate_postgres_to_mongo.py

Re-run only tables that failed (e.g. after a pooler disconnect):

    python migrate_postgres_to_mongo.py --only cost_events,usage_logs,agent_usage_events

After it succeeds you can remove DATABASE_URL / EXTERNAL_DATABASE_URL from .env
— the runtime no longer reads them.

What it does:
- Reads every legacy table that may exist in the PG database (each step is
  guarded so missing tables don't abort the run).
- Inserts the rows into the corresponding MongoDB collection.
- Re-encrypts ``agent_definitions.default_config`` secrets so they remain
  decryptable after the encryption key derivation drops DATABASE_URL.
- Advances the ``_counters`` collection past the largest imported integer id
  so subsequent ``next_seq()`` calls don't collide with imported rows.
- Idempotent — uses upserts; re-running is safe.

Requires the ``psycopg2-binary`` package to be available *only for this
script*. The runtime imports have already been migrated off psycopg2.
"""

from __future__ import annotations

import base64
import hashlib
import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

# Load .env so DATABASE_URL / CORE_SYSTEM_MONGO_DB / JWT_SECRET are present.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("pg2mongo")

# ---------------------------------------------------------------------------
# Source: PostgreSQL
# ---------------------------------------------------------------------------

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    log.error(
        "psycopg2 is required for the migration script. Install it just for the "
        "migration: pip install psycopg2-binary"
    )
    sys.exit(2)


def _pg_url() -> str:
    url = os.environ.get("EXTERNAL_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        log.error("DATABASE_URL is not set — nothing to migrate from.")
        sys.exit(2)
    return url


def _pg_connect():
    # keepalives*: Neon/serverless poolers often drop idle backends; these help only
    # while a query is in flight. We still close PG after each SELECT so Mongo upserts
    # never hold an idle server connection open.
    return psycopg2.connect(
        _pg_url(),
        connect_timeout=30,
        keepalives=1,
        keepalives_idle=30,
        keepalives_interval=10,
        keepalives_count=5,
    )


def _table_exists(conn, table_name: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM information_schema.tables
                WHERE table_schema = current_schema() AND table_name = %s""",
            (table_name,),
        )
        return cur.fetchone() is not None


def _fetch_all(table_name: str) -> List[Dict[str, Any]]:
    """SELECT * with RealDictCursor; returns [] when the table is missing.

    Opens and closes its own connection so the PG socket is not left idle while we
    bulk-write to MongoDB (Neon pooler timeouts caused failures on later tables).
    """
    conn = _pg_connect()
    try:
        if not _table_exists(conn, table_name):
            log.info("  (skip) table %s does not exist in source DB", table_name)
            return []
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {table_name}")
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Destination: MongoDB
# ---------------------------------------------------------------------------

# Resolve sys.path so we can import mongo_db / agent_secrets from this script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mongo_db import get_db, utcnow  # noqa: E402

# Initialise indexes (mirrors what api.py does on boot, keeps the migration
# self-contained — no need to start the FastAPI app first).
import chat_db  # noqa: E402
import cost_tracker  # noqa: E402
import usage_tracker  # noqa: E402
import admin_auth  # noqa: E402
from agent_builder_db import init_agent_builder_db  # noqa: E402
from workflow.components import db as wdb  # noqa: E402

# ---------------------------------------------------------------------------
# Re-key helper: decrypt with the OLD (DATABASE_URL-seeded) Fernet, re-encrypt
# with the new (CORE_SYSTEM_MONGO_DB-seeded) one used by the runtime.
# ---------------------------------------------------------------------------

import agent_secrets  # noqa: E402
from cryptography.fernet import Fernet, InvalidToken  # noqa: E402

OLD_ENC_PREFIX = agent_secrets.ENC_PREFIX


def _build_old_fernet() -> Optional[Fernet]:
    """Re-create the Fernet instance the *PostgreSQL-era* code would have used.

    Mirrors the prior derivation in agent_secrets._derive_key():
    explicit AGENT_BUILDER_SECRET_KEY → JWT_SECRET + DATABASE_URL + salt.
    """
    explicit = os.environ.get("AGENT_BUILDER_SECRET_KEY", "").strip()
    if explicit:
        digest = hashlib.sha256(explicit.encode("utf-8")).digest()
    else:
        seed_parts = [
            os.environ.get("JWT_SECRET", ""),
            os.environ.get("EXTERNAL_DATABASE_URL", "") or os.environ.get("DATABASE_URL", ""),
            "agent-builder-secrets-v1",
        ]
        seed = "::".join(p for p in seed_parts if p)
        if not seed.strip("::"):
            return None
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


_OLD_FERNET: Optional[Fernet] = _build_old_fernet()


def _rekey_default_config(dc: Any) -> Any:
    """Decrypt enc::v1::* values with the old key and re-encrypt with the new one.

    Non-encrypted entries pass through. Bad blobs are dropped with a warning so
    the migration doesn't silently mask broken state.
    """
    if not isinstance(dc, dict) or not dc:
        return dc
    if _OLD_FERNET is None:
        # No old key (no JWT_SECRET / DATABASE_URL): leave blobs alone — they
        # were probably stored under the new key already.
        return dc
    out: Dict[str, Any] = {}
    for k, v in dc.items():
        if isinstance(v, str) and v.startswith(OLD_ENC_PREFIX):
            token = v[len(OLD_ENC_PREFIX):]
            try:
                plain = _OLD_FERNET.decrypt(token.encode("utf-8")).decode("utf-8")
            except InvalidToken:
                # Already encrypted with the new key, OR the old key changed mid-flight.
                # Try to verify against the *new* key by attempting a decrypt round-trip.
                try:
                    agent_secrets.decrypt_value(v)
                    out[k] = v  # already valid under new key
                    continue
                except Exception:
                    log.warning("rekey: dropping unrecoverable secret '%s'", k)
                    continue
            except Exception as e:
                log.warning("rekey: dropping '%s' (decrypt error: %s)", k, e)
                continue
            out[k] = agent_secrets.encrypt_value(plain)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Per-table copy routines
# ---------------------------------------------------------------------------


def _bulk_upsert(coll_name: str, docs: List[Dict[str, Any]], id_key: str = "_id") -> int:
    """Replace-on-id upsert for each doc, returning the number of writes."""
    if not docs:
        return 0
    coll = get_db()[coll_name]
    written = 0
    for d in docs:
        if id_key not in d:
            continue
        coll.replace_one({id_key: d[id_key]}, d, upsert=True)
        written += 1
    return written


def _max_int(values: List[Any]) -> int:
    out = 0
    for v in values:
        try:
            iv = int(v)
            if iv > out:
                out = iv
        except (TypeError, ValueError):
            continue
    return out


def _set_counter(name: str, max_seen: int) -> None:
    """Bump _counters[name] so it's at least ``max_seen``. Idempotent."""
    if max_seen <= 0:
        return
    coll = get_db()["_counters"]
    coll.update_one(
        {"_id": name},
        {"$max": {"seq": int(max_seen)}},
        upsert=True,
    )


def migrate_chat_sessions() -> Tuple[int, int]:
    rows = _fetch_all("chat_sessions")
    docs = []
    for r in rows:
        sid = r.get("id")
        if not sid:
            continue
        docs.append({
            "_id": sid,
            "id": sid,
            "title": r.get("title", "New Chat"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "message_count": int(r.get("message_count") or 0),
        })
    return len(rows), _bulk_upsert("chat_sessions", docs)


def migrate_chat_messages() -> Tuple[int, int]:
    rows = _fetch_all("chat_messages")
    docs = []
    for r in rows:
        mid = r.get("id")
        if mid is None:
            continue
        docs.append({
            "_id": int(mid),
            "id": int(mid),
            "session_id": r.get("session_id"),
            "role": r.get("role"),
            "content": r.get("content"),
            "thinking_steps": r.get("thinking_steps"),
            "routed_to": r.get("routed_to"),
            "bpmn_xml": r.get("bpmn_xml"),
            "metadata": r.get("metadata"),
            "created_at": r.get("created_at"),
        })
    written = _bulk_upsert("chat_messages", docs)
    _set_counter("chat_messages", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_pipeline_steps() -> Tuple[int, int]:
    rows = _fetch_all("pipeline_steps")
    docs = []
    for r in rows:
        sid = r.get("id")
        if sid is None:
            continue
        docs.append({
            "_id": int(sid),
            "id": int(sid),
            "session_id": r.get("session_id"),
            "agent_name": r.get("agent_name"),
            "input_hash": r.get("input_hash"),
            "status": r.get("status"),
            "result": r.get("result"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        })
    written = _bulk_upsert("pipeline_steps", docs)
    _set_counter("pipeline_steps", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_tool_definitions() -> Tuple[int, int]:
    rows = _fetch_all("tool_definitions")
    docs = []
    for r in rows:
        tid = r.get("id")
        if not tid:
            continue
        docs.append({
            "_id": tid,
            "id": tid,
            "slug": r.get("slug"),
            "name": r.get("name"),
            "description": r.get("description", ""),
            "tool_type": r.get("tool_type", "builtin"),
            "schema_config": r.get("schema_config", {}),
            "implementation": r.get("implementation", {}),
            "owner_id": r.get("owner_id"),
            "is_system": bool(r.get("is_system", True)),
            "created_at": r.get("created_at"),
        })
    return len(rows), _bulk_upsert("tool_definitions", docs)


def migrate_agent_definitions() -> Tuple[int, int]:
    rows = _fetch_all("agent_definitions")
    docs = []
    for r in rows:
        aid = r.get("id")
        if not aid:
            continue
        dc = r.get("default_config")
        if isinstance(dc, str):
            # Some deployments stored JSONB as text.
            import json as _json

            try:
                dc = _json.loads(dc)
            except Exception:
                dc = {}
        rekeyed = _rekey_default_config(dc or {})

        docs.append({
            "_id": aid,
            "id": aid,
            "slug": r.get("slug"),
            "owner_id": r.get("owner_id"),
            "name": r.get("name", "Untitled Agent"),
            "description": r.get("description", ""),
            "category_id": r.get("category_id", "general"),
            "logo_url": r.get("logo_url", ""),
            "version": r.get("version", "1.0.0"),
            "status": r.get("status", "draft"),
            "visibility": r.get("visibility", "private"),
            "agent_type": r.get("agent_type", "custom"),
            "system_prompt": r.get("system_prompt", ""),
            "llm_provider": r.get("llm_provider", "pwc_genai"),
            "llm_model": r.get("llm_model", ""),
            "temperature": r.get("temperature", 0.7),
            "max_tokens": r.get("max_tokens", 4096),
            "tools_config": r.get("tools_config", []),
            "capabilities": r.get("capabilities", []),
            "example_prompts": r.get("example_prompts", []),
            "required_env_keys": r.get("required_env_keys", []),
            "default_config": rekeyed,
            "downloads": int(r.get("downloads") or 0),
            "rating": float(r.get("rating") or 0),
            "featured": bool(r.get("featured") or False),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "published_at": r.get("published_at"),
        })
    return len(rows), _bulk_upsert("agent_definitions", docs)


def migrate_agent_versions() -> Tuple[int, int]:
    rows = _fetch_all("agent_versions")
    docs = []
    for r in rows:
        vid = r.get("id")
        if not vid:
            continue
        docs.append({
            "_id": vid,
            "id": vid,
            "agent_id": r.get("agent_id"),
            "version": r.get("version"),
            "system_prompt": r.get("system_prompt", ""),
            "tools_config": r.get("tools_config"),
            "llm_config": r.get("llm_config"),
            "changelog": r.get("changelog", ""),
            "created_at": r.get("created_at"),
        })
    return len(rows), _bulk_upsert("agent_versions", docs)


def migrate_agent_tools() -> Tuple[int, int]:
    rows = _fetch_all("agent_tools")
    coll = get_db()["agent_tools"]
    written = 0
    for r in rows:
        agent_id = r.get("agent_id")
        tool_id = r.get("tool_id")
        if not agent_id or not tool_id:
            continue
        coll.update_one(
            {"agent_id": agent_id, "tool_id": tool_id},
            {"$set": {
                "agent_id": agent_id,
                "tool_id": tool_id,
                "config_override": r.get("config_override", {}),
            }},
            upsert=True,
        )
        written += 1
    return len(rows), written


def migrate_agent_submissions() -> Tuple[int, int]:
    rows = _fetch_all("agent_submissions")
    docs = []
    for r in rows:
        sid = r.get("id")
        if not sid:
            continue
        docs.append({
            "_id": sid,
            "id": sid,
            "agent_id": r.get("agent_id"),
            "submitted_by": r.get("submitted_by"),
            "status": r.get("status", "pending"),
            "reviewer_id": r.get("reviewer_id"),
            "review_notes": r.get("review_notes", ""),
            "submitted_at": r.get("submitted_at"),
            "reviewed_at": r.get("reviewed_at"),
        })
    return len(rows), _bulk_upsert("agent_submissions", docs)


def migrate_workflows() -> Tuple[int, int]:
    rows = _fetch_all("workflows")
    docs = []
    for r in rows:
        wid = r.get("id")
        if not wid:
            continue
        docs.append({
            "_id": wid,
            "id": wid,
            "name": r.get("name"),
            "instruction": r.get("instruction"),
            "definition": r.get("definition", {}),
            "mermaid_code": r.get("mermaid_code"),
            "user_id": r.get("user_id"),
            "agent_user_configs": r.get("agent_user_configs"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
        })
    return len(rows), _bulk_upsert("workflows", docs)


def migrate_workflow_executions() -> Tuple[int, int]:
    rows = _fetch_all("workflow_executions")
    docs = []
    for r in rows:
        eid = r.get("id")
        if not eid:
            continue
        docs.append({
            "_id": eid,
            "id": eid,
            "workflow_id": r.get("workflow_id"),
            "status": r.get("status", "running"),
            "user_id": r.get("user_id"),
            "started_at": r.get("started_at"),
            "completed_at": r.get("completed_at"),
        })
    return len(rows), _bulk_upsert("workflow_executions", docs)


def migrate_workflow_execution_steps() -> Tuple[int, int]:
    rows = _fetch_all("workflow_execution_steps")
    docs = []
    for r in rows:
        sid = r.get("id")
        if sid is None:
            continue
        docs.append({
            "_id": int(sid),
            "execution_id": r.get("execution_id"),
            "step_number": int(r.get("step_number") or 0),
            "agent_id": r.get("agent_id"),
            "agent_name": r.get("agent_name"),
            "status": r.get("status", "pending"),
            "query": r.get("query"),
            "response": r.get("response"),
            "bpmn_xml": r.get("bpmn_xml"),
            "download_url": r.get("download_url"),
            "created_at": r.get("created_at"),
        })
    written = _bulk_upsert("workflow_execution_steps", docs)
    _set_counter("workflow_execution_steps", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_admin_users() -> Tuple[int, int]:
    rows = _fetch_all("admin_users")
    docs = []
    for r in rows:
        uid = r.get("id")
        if uid is None:
            continue
        docs.append({
            "_id": int(uid),
            "id": int(uid),
            "username": r.get("username"),
            "password_hash": r.get("password_hash"),
            "role": r.get("role", "user"),
            "menu_permissions": r.get("menu_permissions", []),
            "agent_permissions": r.get("agent_permissions"),
            "is_active": bool(r.get("is_active", True)),
            "created_at": r.get("created_at"),
        })
    written = _bulk_upsert("admin_users", docs)
    _set_counter("admin_users", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_cost_events() -> Tuple[int, int]:
    rows = _fetch_all("cost_events")
    docs = []
    for r in rows:
        eid = r.get("id")
        if eid is None:
            continue
        docs.append({
            "_id": int(eid),
            "event_type": r.get("event_type"),
            "agent_name": r.get("agent_name"),
            "model": r.get("model"),
            "prompt_tokens": int(r.get("prompt_tokens") or 0),
            "completion_tokens": int(r.get("completion_tokens") or 0),
            "total_tokens": int(r.get("total_tokens") or 0),
            "estimated_cost": float(r.get("estimated_cost") or 0.0),
            "metadata": r.get("metadata", {}),
            "created_at": r.get("created_at"),
        })
    written = _bulk_upsert("cost_events", docs)
    _set_counter("cost_events", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_usage_logs() -> Tuple[int, int]:
    rows = _fetch_all("usage_logs")
    docs = []
    for r in rows:
        uid = r.get("id")
        if uid is None:
            continue
        docs.append({
            "_id": int(uid),
            "agent_name": r.get("agent_name"),
            "agent_id": r.get("agent_id"),
            "ip_address": r.get("ip_address"),
            "city": r.get("city"),
            "region": r.get("region"),
            "country": r.get("country"),
            "location_raw": r.get("location_raw"),
            "user_agent": r.get("user_agent"),
            "query_preview": r.get("query_preview"),
            "session_id": r.get("session_id"),
            "latitude": r.get("latitude"),
            "longitude": r.get("longitude"),
            "zipcode": r.get("zipcode"),
            "timezone": r.get("timezone"),
            "isp": r.get("isp"),
            "org": r.get("org"),
            "created_at": r.get("created_at"),
        })
    written = _bulk_upsert("usage_logs", docs)
    _set_counter("usage_logs", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_agent_usage_events() -> Tuple[int, int]:
    rows = _fetch_all("agent_usage_events")
    docs = []
    for r in rows:
        eid = r.get("id")
        if eid is None:
            continue
        docs.append({
            "_id": int(eid),
            "agent_id": r.get("agent_id"),
            "user_id": r.get("user_id"),
            "session_id": r.get("session_id"),
            "started_at": r.get("started_at"),
            "duration_ms": r.get("duration_ms"),
            "success": bool(r.get("success", True)),
            "error_message": r.get("error_message"),
            "input_tokens": int(r.get("input_tokens") or 0),
            "output_tokens": int(r.get("output_tokens") or 0),
            "tool_calls": int(r.get("tool_calls") or 0),
            "llm_provider": r.get("llm_provider"),
            "llm_model": r.get("llm_model"),
        })
    written = _bulk_upsert("agent_usage_events", docs)
    _set_counter("agent_usage_events", _max_int([d["_id"] for d in docs]))
    return len(rows), written


def migrate_telegram_bot_sessions() -> Tuple[int, int]:
    rows = _fetch_all("telegram_bot_sessions")
    docs = []
    for r in rows:
        key = r.get("key")
        if not key:
            continue
        docs.append({
            "_id": key,
            "data": r.get("data") or {},
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "expires_at": r.get("expires_at"),
        })
    return len(rows), _bulk_upsert("telegram_bot_sessions", docs)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

MIGRATIONS: List[Tuple[str, Callable[[], Tuple[int, int]]]] = [
    ("chat_sessions", migrate_chat_sessions),
    ("chat_messages", migrate_chat_messages),
    ("pipeline_steps", migrate_pipeline_steps),
    ("tool_definitions", migrate_tool_definitions),
    ("agent_definitions", migrate_agent_definitions),
    ("agent_versions", migrate_agent_versions),
    ("agent_tools", migrate_agent_tools),
    ("agent_submissions", migrate_agent_submissions),
    ("workflows", migrate_workflows),
    ("workflow_executions", migrate_workflow_executions),
    ("workflow_execution_steps", migrate_workflow_execution_steps),
    ("admin_users", migrate_admin_users),
    ("cost_events", migrate_cost_events),
    ("usage_logs", migrate_usage_logs),
    ("agent_usage_events", migrate_agent_usage_events),
    ("telegram_bot_sessions", migrate_telegram_bot_sessions),
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-shot PostgreSQL → MongoDB migration (upserts; safe to re-run).",
    )
    parser.add_argument(
        "--only",
        metavar="NAMES",
        help="Comma-separated table names to migrate (e.g. cost_events,usage_logs). "
        "Use after a partial failure to backfill missing collections.",
    )
    args = parser.parse_args(argv)

    only: Optional[Set[str]] = None
    if args.only:
        only = {x.strip() for x in args.only.split(",") if x.strip()}
        known = {name for name, _ in MIGRATIONS}
        unknown = only - known
        if unknown:
            log.error("Unknown table(s) in --only: %s", ", ".join(sorted(unknown)))
            return 2

    log.info("Step 1/3: ensuring MongoDB indexes are in place")
    chat_db.init_db()
    init_agent_builder_db()
    cost_tracker.init_cost_tracking_db()
    usage_tracker.init_usage_tracking_db()
    admin_auth.init_admin_db()
    wdb.init_workflow_db()

    log.info("Step 2/3: copying data from PostgreSQL → MongoDB")
    summary: List[Tuple[str, int, int]] = []
    for name, fn in MIGRATIONS:
        if only is not None and name not in only:
            continue
        try:
            read, written = fn()
            log.info("  %-28s read=%-6d written=%-6d", name, read, written)
            summary.append((name, read, written))
        except Exception as e:
            log.exception("  %-28s FAILED: %s", name, e)
            summary.append((name, -1, -1))

    log.info("Step 3/3: report")
    log.info("  table                         rows_read   rows_written")
    log.info("  ---------------------------- ----------- --------------")
    total_read = total_written = 0
    failed: List[str] = []
    for name, read, written in summary:
        flag = "OK" if read >= 0 else "FAIL"
        log.info("  %-28s %10d %14d  [%s]", name, max(read, 0), max(written, 0), flag)
        if read >= 0:
            total_read += read
            total_written += written
        else:
            failed.append(name)
    log.info("  TOTAL                         read=%d written=%d", total_read, total_written)
    if failed:
        log.warning("Tables that failed (see traceback above): %s", ", ".join(failed))
        return 1
    log.info("Migration complete. You can now remove DATABASE_URL / EXTERNAL_DATABASE_URL from .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
