"""Index bootstrap for the Agent Builder collections (MongoDB).

Migrated from PostgreSQL DDL to MongoDB index creation in 2026-05. Document
shapes mirror the previous tables — see ``agent_registry`` for the actual CRUD.

Collections:
- tool_definitions   (id PK, slug unique)
- agent_definitions  (id PK, slug unique)
- agent_versions     (id PK, unique on agent_id+version)
- agent_tools        (composite PK agent_id+tool_id)
- agent_submissions  (id PK)
"""

from pymongo import ASCENDING, DESCENDING

from mongo_db import get_db


def init_agent_builder_db() -> None:
    try:
        db = get_db()

        db["tool_definitions"].create_index("slug", unique=True, name="uq_tool_slug")

        db["agent_definitions"].create_index("slug", unique=True, name="uq_agent_slug")
        db["agent_definitions"].create_index("owner_id", name="idx_agent_owner")
        db["agent_definitions"].create_index("status", name="idx_agent_status")
        db["agent_definitions"].create_index([("updated_at", DESCENDING)], name="idx_agent_updated")

        db["agent_versions"].create_index(
            [("agent_id", ASCENDING), ("version", ASCENDING)],
            unique=True,
            name="uq_agent_version",
        )
        db["agent_versions"].create_index([("created_at", DESCENDING)], name="idx_agent_version_created")

        db["agent_tools"].create_index(
            [("agent_id", ASCENDING), ("tool_id", ASCENDING)],
            unique=True,
            name="uq_agent_tool",
        )

        db["agent_submissions"].create_index("status", name="idx_submission_status")
        db["agent_submissions"].create_index("agent_id", name="idx_submission_agent")
        db["agent_submissions"].create_index([("submitted_at", DESCENDING)], name="idx_submission_submitted")

        print("Agent Builder collections initialized")
    except Exception as e:
        print(f"Agent Builder DB init: {e}")
