"""Agent Registry — CRUD operations for user-created agents (MongoDB).

Migrated from PostgreSQL (psycopg2 + ThreadedConnectionPool) to MongoDB
(pymongo) in 2026-05. All public function signatures and return shapes are
preserved so callers don't need updating.

Notable behaviour:
- Uses the shared pymongo client from ``mongo_db.py`` (one process-wide pool).
- Secret values in default_config are Fernet-encrypted at rest; reads return
  the encrypted blob unless explicitly decrypted via _decrypt_for_runtime().
- update_agent supports optimistic concurrency via the `expected_updated_at`
  parameter — raises VersionConflictError if the row has been touched since.
- Usage stats are recorded by the dynamic runtime via record_usage() and read
  via get_usage_stats() for per-agent telemetry.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import DuplicateKeyError

from mongo_db import get_db, next_seq, utcnow
from agent_secrets import (
    decrypt_default_config,
    encrypt_default_config,
    redact_default_config,
)

_log = logging.getLogger("agent_registry")


# ---------------------------------------------------------------------------
# Compatibility shims for prior pool API
# ---------------------------------------------------------------------------


def close_pool() -> None:
    """No-op shim. The shared pymongo client is closed via mongo_db.close_client()
    during app shutdown.
    """
    return None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VersionConflictError(Exception):
    """Raised when update_agent's expected_updated_at doesn't match the row."""

    pass


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

_tables_ensured = False


def _ensure_tables() -> None:
    global _tables_ensured
    if _tables_ensured:
        return
    try:
        from agent_builder_db import init_agent_builder_db

        init_agent_builder_db()
        _ensure_usage_table()
        _tables_ensured = True
    except Exception as e:
        _log.warning("agent_registry: collection init on-demand: %s", e)


def _ensure_usage_table() -> None:
    """Create indexes on agent_usage_events if missing. Cheap & idempotent."""
    db = get_db()
    db["agent_usage_events"].create_index(
        [("agent_id", ASCENDING), ("started_at", DESCENDING)],
        name="idx_agent_usage_agent_started",
    )
    db["agent_usage_events"].create_index(
        [("user_id", ASCENDING), ("started_at", DESCENDING)],
        name="idx_agent_usage_user",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or f"agent-{uuid.uuid4().hex[:8]}"


def _unique_slug(base_name: str, exclude_id: Optional[str] = None) -> str:
    base = _slug(base_name)
    db = get_db()
    for suffix in ["", "-2", "-3", "-4", "-5"] + [f"-{uuid.uuid4().hex[:6]}"]:
        candidate = base + suffix if suffix else base
        q: Dict[str, Any] = {"slug": candidate}
        if exclude_id:
            q["_id"] = {"$ne": exclude_id}
        if db["agent_definitions"].find_one(q, {"_id": 1}) is None:
            return candidate
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _row_to_dict(row: Optional[dict], *, redact_secrets: bool = True) -> Optional[Dict[str, Any]]:
    """Normalise a Mongo document into the legacy row shape.

    redact_secrets=True (default): default_config secret values are masked with
    REDACTED_SENTINEL — safe for API responses. The runtime path uses
    redact_secrets=False to get the encrypted blob, which it then decrypts.
    """
    if row is None:
        return None
    out = dict(row)
    out.pop("_id", None)
    # Ensure id is exposed (mirrors the prior TEXT PK behaviour)
    if "id" not in out and "_id" in row:
        out["id"] = row.get("_id")
    if redact_secrets:
        dc = out.get("default_config") or {}
        if isinstance(dc, dict):
            redacted, meta = redact_default_config(dc)
            out["default_config"] = redacted
            out["default_config_meta"] = meta
    return out


def _agent_for_runtime(row: Optional[dict]) -> Optional[Dict[str, Any]]:
    """Return a row with default_config decrypted to plaintext (runtime use only)."""
    if row is None:
        return None
    out = _row_to_dict(row, redact_secrets=False)
    if out is None:
        return None
    dc = out.get("default_config") or {}
    if isinstance(dc, dict):
        out["default_config"] = decrypt_default_config(dc)
    return out


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


def create_agent(data: Dict[str, Any], owner_id: Optional[int] = None) -> Dict[str, Any]:
    _ensure_tables()
    db = get_db()
    agent_id = data.get("id") or f"custom_{uuid.uuid4().hex[:12]}"
    slug = data.get("slug") or _unique_slug(data.get("name", "agent"))
    encrypted_dc = encrypt_default_config(data.get("default_config", {}))
    now = utcnow()

    doc: Dict[str, Any] = {
        "_id": agent_id,
        "id": agent_id,
        "slug": slug,
        "owner_id": owner_id,
        "name": data.get("name", "Untitled Agent"),
        "description": data.get("description", ""),
        "category_id": data.get("category_id", "general"),
        "logo_url": data.get("logo_url", ""),
        "version": data.get("version", "1.0.0"),
        "status": "draft",
        "visibility": data.get("visibility", "private"),
        "agent_type": "custom",
        "system_prompt": data.get("system_prompt", ""),
        "llm_provider": data.get("llm_provider", "pwc_genai"),
        "llm_model": data.get("llm_model", ""),
        "temperature": data.get("temperature", 0.7),
        "max_tokens": data.get("max_tokens", 4096),
        "tools_config": data.get("tools_config", []),
        "capabilities": data.get("capabilities", []),
        "example_prompts": data.get("example_prompts", []),
        "required_env_keys": data.get("required_env_keys", []),
        "default_config": encrypted_dc,
        "downloads": 0,
        "rating": 0,
        "featured": False,
        "created_at": now,
        "updated_at": now,
        "published_at": None,
    }

    try:
        db["agent_definitions"].insert_one(doc)
        return _row_to_dict(doc)
    except DuplicateKeyError:
        # Slug or id race — retry with a uuid suffix
        retry = dict(data)
        retry["slug"] = f"{_slug(data.get('name', 'agent'))}-{uuid.uuid4().hex[:6]}"
        retry["id"] = f"custom_{uuid.uuid4().hex[:12]}"
        return create_agent(retry, owner_id=owner_id)


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Public accessor — returns redacted default_config (safe for API)."""
    _ensure_tables()
    db = get_db()
    return _row_to_dict(db["agent_definitions"].find_one({"_id": agent_id}))


def get_agent_for_runtime(agent_id: str) -> Optional[Dict[str, Any]]:
    """Internal accessor — returns decrypted default_config for tool execution."""
    _ensure_tables()
    db = get_db()
    return _agent_for_runtime(db["agent_definitions"].find_one({"_id": agent_id}))


def get_agent_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    _ensure_tables()
    db = get_db()
    return _row_to_dict(db["agent_definitions"].find_one({"slug": slug}))


def get_agent_by_slug_for_runtime(slug: str) -> Optional[Dict[str, Any]]:
    _ensure_tables()
    db = get_db()
    return _agent_for_runtime(db["agent_definitions"].find_one({"slug": slug}))


def list_agents(
    owner_id: Optional[int] = None,
    status: Optional[str] = None,
    visibility: Optional[str] = None,
    category_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List agents with optional search and total count for pagination."""
    _ensure_tables()
    db = get_db()
    query: Dict[str, Any] = {}
    if owner_id is not None:
        query["owner_id"] = owner_id
    if status:
        query["status"] = status
    if visibility:
        query["visibility"] = visibility
    if category_id:
        query["category_id"] = category_id
    if search:
        rx = re.compile(re.escape(search), re.IGNORECASE)
        query["$or"] = [{"name": rx}, {"description": rx}]

    total = db["agent_definitions"].count_documents(query)
    cursor = (
        db["agent_definitions"]
        .find(query)
        .sort("updated_at", DESCENDING)
        .skip(int(offset))
        .limit(int(limit))
    )
    rows = [_row_to_dict(r) for r in cursor]
    return {"agents": rows, "total": total, "limit": limit, "offset": offset}


def _coerce_expected_updated_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value.rstrip("Z")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None
    return None


def update_agent(
    agent_id: str,
    data: Dict[str, Any],
    *,
    expected_updated_at: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Update an agent. If `expected_updated_at` is supplied, the update only
    succeeds when the row's current updated_at matches — otherwise raises
    VersionConflictError. Use ISO-8601 strings or datetime objects.
    """
    _ensure_tables()
    db = get_db()
    allowed = {
        "name", "description", "category_id", "logo_url", "version",
        "status", "visibility", "system_prompt", "llm_provider", "llm_model",
        "temperature", "max_tokens", "tools_config", "capabilities",
        "example_prompts", "required_env_keys", "default_config", "featured",
    }

    # Read existing default_config so we can preserve fields the user didn't change.
    existing_dc: Dict[str, Any] = {}
    if "default_config" in data:
        existing_doc = db["agent_definitions"].find_one(
            {"_id": agent_id}, {"default_config": 1}
        )
        if existing_doc and existing_doc.get("default_config"):
            raw = existing_doc["default_config"]
            if isinstance(raw, dict):
                existing_dc = raw

    set_updates: Dict[str, Any] = {}
    for k, v in data.items():
        if k not in allowed:
            continue
        if k == "default_config":
            v = encrypt_default_config(v, existing=existing_dc)
        set_updates[k] = v

    if not set_updates:
        return get_agent(agent_id)

    set_updates["updated_at"] = utcnow()

    query: Dict[str, Any] = {"_id": agent_id}
    expected_dt = _coerce_expected_updated_at(expected_updated_at)
    if expected_dt is not None:
        query["updated_at"] = expected_dt

    updated = db["agent_definitions"].find_one_and_update(
        query,
        {"$set": set_updates},
        return_document=ReturnDocument.AFTER,
    )

    if updated is None and expected_dt is not None:
        # Row exists but updated_at didn't match — concurrent edit
        if db["agent_definitions"].find_one({"_id": agent_id}, {"_id": 1}):
            raise VersionConflictError(
                "This agent was modified in another tab. Reload to see the latest version."
            )
        return None

    return _row_to_dict(updated) if updated else None


def delete_agent(agent_id: str) -> bool:
    _ensure_tables()
    db = get_db()
    res = db["agent_definitions"].delete_one({"_id": agent_id})
    if res.deleted_count:
        # Manual cascade — mirrors PG ON DELETE CASCADE
        db["agent_versions"].delete_many({"agent_id": agent_id})
        db["agent_tools"].delete_many({"agent_id": agent_id})
        db["agent_submissions"].delete_many({"agent_id": agent_id})
    return res.deleted_count > 0


def clone_agent(source_id: str, new_owner_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """Duplicate an agent (under a new id/slug) for the given owner."""
    src = get_agent(source_id)
    if src is None:
        return None

    db = get_db()
    raw_doc = db["agent_definitions"].find_one(
        {"_id": source_id}, {"default_config": 1, "owner_id": 1}
    ) or {}
    raw_dc = raw_doc.get("default_config") or {}
    if not isinstance(raw_dc, dict):
        raw_dc = {}

    same_owner = raw_doc.get("owner_id") == new_owner_id
    cloned_dc: Dict[str, Any] = {}
    if same_owner:
        cloned_dc = dict(raw_dc)
    else:
        from agent_secrets import is_encrypted, is_secret_key

        for k, v in raw_dc.items():
            if is_secret_key(k) or is_encrypted(v):
                continue
            cloned_dc[k] = v

    new_name = (src.get("name") or "Untitled") + " (Copy)"
    new_id = f"custom_{uuid.uuid4().hex[:12]}"
    new_slug = _unique_slug(new_name)
    now = utcnow()

    doc = {
        "_id": new_id,
        "id": new_id,
        "slug": new_slug,
        "owner_id": new_owner_id,
        "name": new_name,
        "description": src.get("description", ""),
        "category_id": src.get("category_id", "general"),
        "logo_url": src.get("logo_url", ""),
        "version": "1.0.0",
        "status": "draft",
        "visibility": "private",
        "agent_type": "custom",
        "system_prompt": src.get("system_prompt", ""),
        "llm_provider": src.get("llm_provider", "pwc_genai"),
        "llm_model": src.get("llm_model", ""),
        "temperature": src.get("temperature", 0.7),
        "max_tokens": src.get("max_tokens", 4096),
        "tools_config": src.get("tools_config", []),
        "capabilities": src.get("capabilities", []),
        "example_prompts": src.get("example_prompts", []),
        "required_env_keys": src.get("required_env_keys", []),
        "default_config": cloned_dc,
        "downloads": 0,
        "rating": 0,
        "featured": False,
        "created_at": now,
        "updated_at": now,
        "published_at": None,
    }
    db["agent_definitions"].insert_one(doc)
    return _row_to_dict(doc)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


def create_version(agent_id: str, changelog: str = "") -> Optional[Dict[str, Any]]:
    """Snapshot the current agent state into agent_versions and bump the version."""
    src = get_agent(agent_id)
    if src is None:
        return None
    db = get_db()
    version_id = f"ver_{uuid.uuid4().hex[:12]}"
    next_version = _bump_version(src.get("version", "1.0.0"), agent_id)
    now = utcnow()

    doc = {
        "_id": version_id,
        "id": version_id,
        "agent_id": agent_id,
        "version": next_version,
        "system_prompt": src.get("system_prompt", ""),
        "tools_config": src.get("tools_config", []),
        "llm_config": {
            "llm_provider": src.get("llm_provider"),
            "llm_model": src.get("llm_model"),
            "temperature": src.get("temperature"),
            "max_tokens": src.get("max_tokens"),
        },
        "changelog": changelog,
        "created_at": now,
    }
    db["agent_versions"].insert_one(doc)
    update_agent(agent_id, {"version": next_version})
    out = dict(doc)
    out.pop("_id", None)
    return out


def _bump_version(version: str, agent_id: str) -> str:
    """Bump the patch component; if it collides with an existing version, bump again."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", version or "")
    if m:
        major, minor, patch = (int(x) for x in m.groups())
        candidate = f"{major}.{minor}.{patch + 1}"
    else:
        candidate = "1.0.1"

    db = get_db()
    for _ in range(10):
        if db["agent_versions"].find_one(
            {"agent_id": agent_id, "version": candidate}, {"_id": 1}
        ) is None:
            return candidate
        m2 = re.match(r"^(\d+)\.(\d+)\.(\d+)$", candidate)
        if m2:
            a, b, p = (int(x) for x in m2.groups())
            candidate = f"{a}.{b}.{p + 1}"
        else:
            candidate = f"{candidate}.1"
    return candidate


def list_versions(agent_id: str) -> List[Dict[str, Any]]:
    db = get_db()
    cursor = db["agent_versions"].find({"agent_id": agent_id}).sort("created_at", DESCENDING)
    out = []
    for r in cursor:
        row = dict(r)
        row.pop("_id", None)
        out.append(row)
    return out


def get_version(agent_id: str, version: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    r = db["agent_versions"].find_one({"agent_id": agent_id, "version": version})
    if not r:
        return None
    row = dict(r)
    row.pop("_id", None)
    return row


def rollback_to_version(agent_id: str, version: str) -> Optional[Dict[str, Any]]:
    """Restore the system_prompt + tools_config + llm config to a prior version."""
    snap = get_version(agent_id, version)
    if not snap:
        raise ValueError(f"Version {version} not found for agent {agent_id}")

    llm = snap.get("llm_config") or {}
    update_data: Dict[str, Any] = {
        "system_prompt": snap.get("system_prompt", ""),
        "tools_config": snap.get("tools_config", []),
    }
    for fld in ("llm_provider", "llm_model", "temperature", "max_tokens"):
        if fld in llm:
            update_data[fld] = llm[fld]

    updated = update_agent(agent_id, update_data)
    create_version(agent_id, changelog=f"Rolled back to v{version}")
    return updated


# ---------------------------------------------------------------------------
# Deploy & Publish
# ---------------------------------------------------------------------------


def deploy_agent(agent_id: str) -> Dict[str, Any]:
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError("Agent not found")
    if not agent.get("system_prompt"):
        raise ValueError("Agent must have a system prompt before deployment")
    create_version(agent_id, changelog="Deployed")
    return update_agent(agent_id, {"status": "deployed"})


def submit_for_publishing(agent_id: str, submitted_by: int) -> Dict[str, Any]:
    _ensure_tables()
    agent = get_agent(agent_id)
    if not agent:
        raise ValueError("Agent not found")
    if agent.get("status") not in ("deployed", "published"):
        raise ValueError("Agent must be deployed before submitting for publishing")
    db = get_db()
    sub_id = f"sub_{uuid.uuid4().hex[:12]}"
    doc = {
        "_id": sub_id,
        "id": sub_id,
        "agent_id": agent_id,
        "submitted_by": submitted_by,
        "status": "pending",
        "reviewer_id": None,
        "review_notes": "",
        "submitted_at": utcnow(),
        "reviewed_at": None,
    }
    db["agent_submissions"].insert_one(doc)
    out = dict(doc)
    out.pop("_id", None)
    return out


def review_submission(submission_id: str, reviewer_id: int, approved: bool, notes: str = "") -> Dict[str, Any]:
    _ensure_tables()
    db = get_db()
    new_status = "approved" if approved else "rejected"
    updated = db["agent_submissions"].find_one_and_update(
        {"_id": submission_id},
        {"$set": {
            "status": new_status,
            "reviewer_id": reviewer_id,
            "review_notes": notes,
            "reviewed_at": utcnow(),
        }},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        raise ValueError("Submission not found")
    if approved:
        db["agent_definitions"].update_one(
            {"_id": updated["agent_id"]},
            {"$set": {
                "status": "published",
                "visibility": "public",
                "published_at": utcnow(),
                "updated_at": utcnow(),
            }},
        )
    out = dict(updated)
    out.pop("_id", None)
    return out


def list_submissions(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    _ensure_tables()
    db = get_db()
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    cursor = (
        db["agent_submissions"]
        .find(q)
        .sort("submitted_at", DESCENDING)
        .limit(int(limit))
    )

    # Application-level join with agent_definitions to mirror the prior SQL JOIN
    submissions = []
    agent_ids: List[str] = []
    for r in cursor:
        row = dict(r)
        row.pop("_id", None)
        submissions.append(row)
        agent_ids.append(row.get("agent_id"))

    if not submissions:
        return []

    agents_by_id: Dict[str, Dict[str, Any]] = {}
    for a in db["agent_definitions"].find(
        {"_id": {"$in": [aid for aid in agent_ids if aid]}},
        {"name": 1, "description": 1, "slug": 1},
    ):
        agents_by_id[a["_id"]] = a

    for row in submissions:
        a = agents_by_id.get(row.get("agent_id"))
        if a:
            row["agent_name"] = a.get("name")
            row["agent_description"] = a.get("description")
            row["agent_slug"] = a.get("slug")
        else:
            row["agent_name"] = None
            row["agent_description"] = None
            row["agent_slug"] = None
    return submissions


# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------


def list_tools(system_only: bool = False) -> List[Dict[str, Any]]:
    _ensure_tables()
    db = get_db()
    q: Dict[str, Any] = {}
    if system_only:
        q["is_system"] = True
    cursor = db["tool_definitions"].find(q).sort("name", ASCENDING)
    out = []
    for r in cursor:
        row = dict(r)
        row.pop("_id", None)
        out.append(row)
    return out


def upsert_tool(tool: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_tables()
    db = get_db()
    tool_id = tool["id"]
    now = utcnow()
    doc = {
        "_id": tool_id,
        "id": tool_id,
        "slug": tool.get("slug", tool_id),
        "name": tool["name"],
        "description": tool.get("description", ""),
        "tool_type": tool.get("tool_type", "builtin"),
        "schema_config": tool.get("schema_config", {}),
        "implementation": tool.get("implementation", {}),
        "owner_id": tool.get("owner_id"),
        "is_system": tool.get("is_system", True),
        "created_at": now,
    }
    # Mirror PG's "ON CONFLICT (id) DO UPDATE" — keep created_at via $setOnInsert.
    update_doc = {k: v for k, v in doc.items() if k not in ("_id", "created_at")}
    result = db["tool_definitions"].find_one_and_update(
        {"_id": tool_id},
        {"$set": update_doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    out = dict(result)
    out.pop("_id", None)
    return out


def get_published_agents(limit: int = 100) -> List[Dict[str, Any]]:
    _ensure_tables()
    db = get_db()
    pipeline = [
        {"$match": {
            "status": {"$in": ["published", "deployed"]},
            "visibility": "public",
        }},
        {"$addFields": {"_published_first": {"$cond": [{"$eq": ["$status", "published"]}, 0, 1]}}},
        {"$sort": {"_published_first": 1, "downloads": -1, "updated_at": -1}},
        {"$limit": int(limit)},
    ]
    return [_row_to_dict(r) for r in db["agent_definitions"].aggregate(pipeline)]


# ---------------------------------------------------------------------------
# Usage telemetry
# ---------------------------------------------------------------------------


def record_usage(
    agent_id: str,
    *,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    tool_calls: int = 0,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> None:
    """Log a single agent invocation. Best-effort — swallows DB errors."""
    try:
        _ensure_tables()
        db = get_db()
        db["agent_usage_events"].insert_one({
            "_id": next_seq("agent_usage_events"),
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "started_at": utcnow(),
            "duration_ms": duration_ms,
            "success": success,
            "error_message": error_message,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "tool_calls": int(tool_calls or 0),
            "llm_provider": llm_provider,
            "llm_model": llm_model,
        })
    except Exception as e:
        _log.warning("agent_registry: record_usage failed: %s", e)


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Linear-interpolation percentile (matches PG percentile_cont semantics)."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    k = (len(sorted_values) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return float(sorted_values[lo]) * (1 - frac) + float(sorted_values[hi]) * frac


def get_usage_stats(agent_id: str, days: int = 30) -> Dict[str, Any]:
    """Return aggregate usage stats and a per-day series for the given agent."""
    _ensure_tables()
    db = get_db()
    cutoff = utcnow() - timedelta(days=int(days))
    match = {"agent_id": agent_id, "started_at": {"$gt": cutoff}}

    # ---- Aggregate totals
    agg_pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "calls": {"$sum": 1},
            "input_tokens": {"$sum": {"$ifNull": ["$input_tokens", 0]}},
            "output_tokens": {"$sum": {"$ifNull": ["$output_tokens", 0]}},
            "tool_calls": {"$sum": {"$ifNull": ["$tool_calls", 0]}},
            "errors": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
            "avg_duration_ms": {"$avg": "$duration_ms"},
            "last_call": {"$max": "$started_at"},
        }},
    ]
    agg_rows = list(db["agent_usage_events"].aggregate(agg_pipeline))
    agg = agg_rows[0] if agg_rows else {}
    if agg:
        agg.pop("_id", None)
    agg.setdefault("calls", 0)
    agg.setdefault("input_tokens", 0)
    agg.setdefault("output_tokens", 0)
    agg.setdefault("tool_calls", 0)
    agg.setdefault("errors", 0)
    agg.setdefault("avg_duration_ms", 0)
    agg.setdefault("last_call", None)

    # ---- Percentiles via app-level sort (Atlas $percentile is 7.0+; emulate for portability).
    durations = [
        d["duration_ms"]
        for d in db["agent_usage_events"].find(
            {"agent_id": agent_id, "started_at": {"$gt": cutoff}, "duration_ms": {"$ne": None}},
            {"duration_ms": 1, "_id": 0},
        )
    ]
    durations.sort()
    agg["p50_duration_ms"] = _percentile(durations, 0.5)
    agg["p95_duration_ms"] = _percentile(durations, 0.95)

    # ---- Daily series (DATE_TRUNC('day', started_at))
    series_pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "$dateTrunc": {"date": "$started_at", "unit": "day"}
            },
            "calls": {"$sum": 1},
            "errors": {"$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}},
            "tokens": {"$sum": {"$add": [
                {"$ifNull": ["$input_tokens", 0]},
                {"$ifNull": ["$output_tokens", 0]},
            ]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    series = []
    for r in db["agent_usage_events"].aggregate(series_pipeline):
        series.append({
            "day": r["_id"],
            "calls": r["calls"],
            "errors": r["errors"],
            "tokens": r["tokens"],
        })

    return {
        "window_days": days,
        "totals": agg,
        "series": series,
    }
