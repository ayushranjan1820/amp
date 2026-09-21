"""Admin authentication & user management — MongoDB-backed.

Migrated from PostgreSQL in 2026-05. JWT issuance, bcrypt password hashing
and permission resolution are unchanged; only the storage layer moved.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import bcrypt
import jwt

from mongo_db import get_db, next_seq, utcnow


JWT_SECRET = os.environ.get("SESSION_SECRET")
JWT_ALGORITHM = "HS256"


def _get_jwt_secret() -> str:
    """Return the JWT signing secret, reading the env var lazily so the module
    can be imported even before SESSION_SECRET is set (e.g. during Railway startup)."""
    secret = JWT_SECRET if JWT_SECRET is not None else os.environ.get("SESSION_SECRET")
    if not secret:
        raise RuntimeError("SESSION_SECRET environment variable is required for admin authentication")
    return secret
JWT_EXPIRY_HOURS = 24

AGENT_ARCHITECTURE_MENU_PERMISSION = "agent-architecture"

CORE_MENU_PERMISSIONS = [
    "overview", "agents", "sessions", "costs", "usage",
    "agent-studio", "knowledge-base", "settings", "chat",
]

ALL_MENU_PERMISSIONS = CORE_MENU_PERMISSIONS + [AGENT_ARCHITECTURE_MENU_PERMISSION]

_PERM_RENAMES = {"workflows": "agent-studio"}

SUPER_ADMIN_USERNAME = "admin"

ADMIN_USERS = "admin_users"


def _normalize_stored_menu_permissions(menu_permissions: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for p in menu_permissions or []:
        q = _PERM_RENAMES.get(p, p)
        if q not in ALL_MENU_PERMISSIONS:
            continue
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def get_all_agent_ids() -> List[str]:
    try:
        from agents_catalog_db import get_all_agent_ids as _catalog_ids

        return _catalog_ids()
    except Exception:
        return []


def effective_agent_ids(role: str, stored: Any) -> List[str]:
    """Resolve which catalog agent IDs a user may use (for JWT and enforcement)."""
    ids = get_all_agent_ids()
    if role == "super_admin":
        return ids
    if stored is None:
        return ids
    if not isinstance(stored, list):
        return ids
    allowed = set(ids)
    return [x for x in stored if isinstance(x, str) and x in allowed]


# ---------------------------------------------------------------------------
# Compatibility shim
# ---------------------------------------------------------------------------


def get_connection():
    """Compatibility shim — returns the pymongo Database. The previous psycopg2
    connection-with-DDL-bootstrap is now replaced by ``init_admin_db()`` on
    startup; the schema-less Mongo collection needs no per-call DDL.
    """
    return get_db()


# ---------------------------------------------------------------------------
# Bootstrap & seeding
# ---------------------------------------------------------------------------


def init_admin_db() -> None:
    """Create the unique index on ``username`` and bootstrap the super-admin role."""
    try:
        db = get_db()
        db[ADMIN_USERS].create_index("username", unique=True, name="uq_admin_username")
        # Bring legacy 'user'/'admin' rows up to super_admin if they own SUPER_ADMIN_USERNAME.
        db[ADMIN_USERS].update_one(
            {"username": SUPER_ADMIN_USERNAME, "role": {"$in": ["user", "admin"]}},
            {"$set": {
                "role": "super_admin",
                "menu_permissions": list(ALL_MENU_PERMISSIONS),
                "is_active": True,
            }},
        )
        print("Admin users collection initialized with super_admin support")
    except Exception as e:
        print(f"Admin DB init error: {e}")


def seed_default_admin() -> None:
    db = get_db()
    try:
        # Bootstrap based on the presence of the admin account, not on whether
        # the collection happens to contain any other users. A migrated or
        # partially seeded collection must still receive its super-admin.
        existing = db[ADMIN_USERS].find_one({"username": SUPER_ADMIN_USERNAME})

        # Explicit recovery path for a newly configured database or a lost
        # admin password. This is intentionally opt-in and should be removed
        # from the environment after the next successful publish/startup.
        reset_password = os.environ.get("ADMIN_RESET_PASSWORD")
        if reset_password:
            hashed = bcrypt.hashpw(reset_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            if existing:
                db[ADMIN_USERS].update_one(
                    {"_id": existing["_id"]},
                    {"$set": {
                        "password_hash": hashed,
                        "role": "super_admin",
                        "menu_permissions": list(ALL_MENU_PERMISSIONS),
                        "agent_permissions": None,
                        "is_active": True,
                    }},
                )
                print("Super admin password reset from ADMIN_RESET_PASSWORD; remove that variable after login")
            else:
                user_id = next_seq("admin_users")
                db[ADMIN_USERS].insert_one({
                    "_id": user_id,
                    "id": user_id,
                    "username": SUPER_ADMIN_USERNAME,
                    "password_hash": hashed,
                    "role": "super_admin",
                    "menu_permissions": list(ALL_MENU_PERMISSIONS),
                    "agent_permissions": None,
                    "is_active": True,
                    "created_at": utcnow(),
                })
                print("Super admin created from ADMIN_RESET_PASSWORD; remove that variable after login")
            return

        if not existing:
            default_password = os.environ.get("ADMIN_DEFAULT_PASSWORD", "admin123")
            hashed = bcrypt.hashpw(default_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            user_id = next_seq("admin_users")
            db[ADMIN_USERS].insert_one({
                "_id": user_id,
                "id": user_id,
                "username": SUPER_ADMIN_USERNAME,
                "password_hash": hashed,
                "role": "super_admin",
                "menu_permissions": list(ALL_MENU_PERMISSIONS),
                "agent_permissions": None,
                "is_active": True,
                "created_at": utcnow(),
            })
            print("Default super admin created (username: admin) - change password after first login")
    except Exception as e:
        print(f"Seed admin error: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enrich_user(user: Dict[str, Any]) -> Dict[str, Any]:
    raw_menu = user.get("menu_permissions", [])
    if isinstance(raw_menu, str):
        try:
            raw_menu = json.loads(raw_menu)
        except Exception:
            raw_menu = []
    normalized = _normalize_stored_menu_permissions([p for p in (raw_menu or []) if isinstance(p, str)])
    role = user.get("role", "user")
    if role == "super_admin":
        perms = list(ALL_MENU_PERMISSIONS)
    elif role == "admin":
        perms = list(CORE_MENU_PERMISSIONS)
        if AGENT_ARCHITECTURE_MENU_PERMISSION in normalized:
            perms.append(AGENT_ARCHITECTURE_MENU_PERMISSION)
    else:
        perms = normalized

    raw_agent = user.get("agent_permissions")
    if isinstance(raw_agent, str):
        try:
            raw_agent = json.loads(raw_agent)
        except Exception:
            raw_agent = None

    return {
        "id": user.get("id") or user.get("_id"),
        "username": user["username"],
        "role": role,
        "menu_permissions": perms,
        "agent_permissions": raw_agent,
        "is_active": user.get("is_active", True),
    }


def _doc_to_user(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight projection used by list/get/update accessors."""
    return {
        "id": doc.get("id") or doc.get("_id"),
        "username": doc.get("username"),
        "password_hash": doc.get("password_hash"),
        "role": doc.get("role", "user"),
        "menu_permissions": doc.get("menu_permissions", []),
        "agent_permissions": doc.get("agent_permissions"),
        "is_active": doc.get("is_active", True),
        "created_at": doc.get("created_at"),
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def authenticate_admin(username: str, password: str) -> Optional[Dict[str, Any]]:
    db = get_db()
    user = db[ADMIN_USERS].find_one({"username": username})
    if not user:
        return None
    if not user.get("is_active", True):
        return None
    pw_hash = user.get("password_hash") or ""
    if not bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("utf-8")):
        return None
    return _enrich_user(_doc_to_user(user))


def generate_token(user: Dict[str, Any]) -> str:
    secret = _get_jwt_secret()
    role = user.get("role", "user")
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "role": role,
        "menu_permissions": user.get("menu_permissions", []),
        "agent_permissions": effective_agent_ids(role, user.get("agent_permissions")),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        secret = _get_jwt_secret()
    except RuntimeError:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        role = payload.get("role", "user")
        jwt_menu = payload.get("menu_permissions", [])
        if not isinstance(jwt_menu, list):
            jwt_menu = []
        jwt_menu = [p for p in jwt_menu if isinstance(p, str)]
        normalized = _normalize_stored_menu_permissions(jwt_menu)
        if role == "super_admin":
            perms = list(ALL_MENU_PERMISSIONS)
        elif role == "admin":
            perms = list(CORE_MENU_PERMISSIONS)
            if AGENT_ARCHITECTURE_MENU_PERMISSION in normalized:
                perms.append(AGENT_ARCHITECTURE_MENU_PERMISSION)
        else:
            perms = normalized
        agent_perms = payload.get("agent_permissions")
        ids = get_all_agent_ids()
        if not isinstance(agent_perms, list):
            agent_perms = ids
        else:
            agent_perms = [x for x in agent_perms if isinstance(x, str) and x in set(ids)]
            if role == "super_admin":
                agent_perms = ids
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": role,
            "menu_permissions": perms,
            "agent_permissions": agent_perms,
        }
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


def change_password(username: str, old_password: str, new_password: str) -> bool:
    user = authenticate_admin(username, old_password)
    if not user:
        return False
    db = get_db()
    hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    res = db[ADMIN_USERS].update_one(
        {"username": username}, {"$set": {"password_hash": hashed}}
    )
    return res.matched_count > 0


def create_user(
    username: str,
    password: str,
    role: str = "user",
    menu_permissions: Optional[List[str]] = None,
    agent_permissions: Any = None,
) -> Dict[str, Any]:
    if menu_permissions is None:
        menu_permissions = []
    if role == "super_admin":
        raise ValueError("Cannot create a super_admin account")

    db = get_db()
    if db[ADMIN_USERS].find_one({"username": username}, {"_id": 1}):
        raise ValueError(f"Username '{username}' already exists")

    if role == "admin":
        stored_perms = _normalize_stored_menu_permissions(menu_permissions or [])
        if not stored_perms:
            stored_perms = list(CORE_MENU_PERMISSIONS)
    else:
        stored_perms = _normalize_stored_menu_permissions(menu_permissions or [])

    stored_agent = agent_permissions
    if stored_agent is not None and not isinstance(stored_agent, list):
        raise ValueError("agent_permissions must be a list or null")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user_id = next_seq("admin_users")
    doc = {
        "_id": user_id,
        "id": user_id,
        "username": username,
        "password_hash": hashed,
        "role": role,
        "menu_permissions": stored_perms,
        "agent_permissions": stored_agent,
        "is_active": True,
        "created_at": utcnow(),
    }
    db[ADMIN_USERS].insert_one(doc)
    enriched = _enrich_user(_doc_to_user(doc))
    enriched["created_at"] = doc["created_at"]
    return enriched


def list_users() -> List[Dict[str, Any]]:
    db = get_db()
    cursor = db[ADMIN_USERS].find({}).sort("created_at", 1)
    out: List[Dict[str, Any]] = []
    for r in cursor:
        u = _enrich_user(_doc_to_user(r))
        u["created_at"] = r.get("created_at")
        out.append(u)
    return out


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    db = get_db()
    r = db[ADMIN_USERS].find_one({"_id": user_id})
    if not r:
        # Fallback in case the document was created before _id was used as the int id
        r = db[ADMIN_USERS].find_one({"id": user_id})
    if not r:
        return None
    u = _enrich_user(_doc_to_user(r))
    u["created_at"] = r.get("created_at")
    return u


def update_user(user_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    db = get_db()
    existing = db[ADMIN_USERS].find_one({"_id": user_id}) or db[ADMIN_USERS].find_one({"id": user_id})
    if not existing:
        return None
    if existing.get("role") == "super_admin":
        allowed = {"password"}
        bad = set(updates.keys()) - allowed
        if bad:
            raise ValueError("Super admin role and permissions cannot be changed")

    new_role = updates.get("role", existing.get("role"))
    if new_role == "super_admin":
        raise ValueError("Cannot assign super_admin role")

    set_updates: Dict[str, Any] = {}
    if "role" in updates and existing.get("role") != "super_admin":
        set_updates["role"] = updates["role"]
        if updates["role"] == "admin" and "menu_permissions" not in updates:
            set_updates["menu_permissions"] = list(ALL_MENU_PERMISSIONS)
    if "menu_permissions" in updates and existing.get("role") != "super_admin":
        set_updates["menu_permissions"] = _normalize_stored_menu_permissions(updates["menu_permissions"])
    if "agent_permissions" in updates and existing.get("role") != "super_admin":
        ap = updates["agent_permissions"]
        if ap is not None and not isinstance(ap, list):
            raise ValueError("agent_permissions must be a list or null")
        set_updates["agent_permissions"] = ap
    if "is_active" in updates and existing.get("role") != "super_admin":
        set_updates["is_active"] = updates["is_active"]
    if "password" in updates:
        set_updates["password_hash"] = bcrypt.hashpw(
            updates["password"].encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    if not set_updates:
        return get_user(user_id)

    db[ADMIN_USERS].update_one({"_id": existing["_id"]}, {"$set": set_updates})
    return get_user(user_id)


def delete_user(user_id: int) -> bool:
    db = get_db()
    row = db[ADMIN_USERS].find_one({"_id": user_id}) or db[ADMIN_USERS].find_one({"id": user_id})
    if not row:
        return False
    if row.get("role") == "super_admin":
        raise ValueError("Cannot delete the super admin account")
    res = db[ADMIN_USERS].delete_one({"_id": row["_id"]})
    return res.deleted_count > 0
