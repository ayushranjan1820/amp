"""mem0 memory integration for workflow agent runs.

When a workflow has ``memory_enabled=True``, each agent step is augmented with
relevant memories retrieved from mem0 (cloud), and the resulting query/response
pair is stored back into mem0 for future runs.

Memories are scoped per-workflow so a workflow's "memory" is isolated from
other workflows. Within a workflow, the user_id (or "anonymous") is used as
the mem0 user_id so different end-users do not pollute each other's history.

The mem0 API key is read from the ``MEMO_GRAPH_MEMEORY_API_KEY`` env var
(spelling preserved from .env). When the key is missing or the SDK is not
installed, all memory operations no-op gracefully so workflow runs are never
blocked by memory failures.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_API_KEY_ENV = "MEMO_GRAPH_MEMEORY_API_KEY"

_client_singleton: Any = None
_client_init_attempted: bool = False


def _get_client() -> Any:
    """Return a cached mem0 MemoryClient or None when unavailable."""
    global _client_singleton, _client_init_attempted
    if _client_init_attempted:
        return _client_singleton
    _client_init_attempted = True

    api_key = os.getenv(_API_KEY_ENV)
    if not api_key:
        logger.info("mem0: %s not set — memory features disabled", _API_KEY_ENV)
        return None
    try:
        from mem0 import MemoryClient  # type: ignore
    except ImportError:
        logger.warning("mem0: mem0ai package not installed — memory features disabled")
        return None
    try:
        _client_singleton = MemoryClient(api_key=api_key)
        logger.info("mem0: client initialised")
    except Exception as e:
        logger.warning("mem0: client init failed: %s", e)
        _client_singleton = None
    return _client_singleton


def _agent_user_id(workflow_id: Optional[str], user_id: Optional[str]) -> Optional[str]:
    """Build a per-user-per-workflow mem0 namespace.

    Returns ``None`` when *user_id* is missing — anonymous runs deliberately get
    no memory so unrelated users never share a bucket. Memories are strictly
    scoped to ``wf-<workflow_id>-user-<user_id>``.
    """
    if user_id is None or str(user_id).strip() == "":
        return None
    wf = workflow_id or "default"
    return f"wf-{wf}-user-{user_id}"


def _format_memories(memories: List[dict]) -> str:
    """Render mem0 search results as a short bullet list."""
    lines: List[str] = []
    for m in memories:
        if not isinstance(m, dict):
            continue
        text = m.get("memory") or m.get("text") or m.get("content")
        if not text:
            continue
        lines.append(f"- {str(text).strip()}")
    return "\n".join(lines)


async def retrieve_memories(
    *,
    workflow_id: Optional[str],
    user_id: Optional[str],
    agent_id: str,
    query: str,
    limit: int = 5,
) -> str:
    """Search mem0 for memories relevant to *query* for this workflow/agent.

    Returns a formatted block ready to prepend to the agent's prompt, or an
    empty string when memory is unavailable, errors out, or finds nothing.
    """
    client = _get_client()
    if client is None or not query:
        return ""

    mem_user = _agent_user_id(workflow_id, user_id)
    if mem_user is None:
        # Anonymous run — skip memory so users never read each other's data.
        return ""

    def _search() -> List[dict]:
        try:
            return client.search(
                query=query,
                user_id=mem_user,
                metadata={"agent_id": agent_id},
                limit=limit,
            ) or []
        except TypeError:
            # Older SDKs may not accept metadata kwarg in search.
            return client.search(query=query, user_id=mem_user, limit=limit) or []
        except Exception as e:
            logger.debug("mem0 search failed for %s: %s", mem_user, e)
            return []

    try:
        memories = await asyncio.to_thread(_search)
    except Exception as e:
        logger.debug("mem0 search threadpool failed: %s", e)
        return ""

    formatted = _format_memories(memories)
    if not formatted:
        return ""
    return (
        "Relevant memories from previous workflow runs (use only if helpful):\n"
        f"{formatted}\n"
    )


async def store_interaction(
    *,
    workflow_id: Optional[str],
    user_id: Optional[str],
    agent_id: str,
    agent_name: str,
    query: str,
    response: str,
) -> None:
    """Persist the (query, response) pair into mem0 for future retrieval."""
    client = _get_client()
    if client is None:
        return
    if not (query or response):
        return

    mem_user = _agent_user_id(workflow_id, user_id)
    if mem_user is None:
        # Anonymous run — do not persist; memory is strictly per-user.
        return

    # mem0 accepts a list of role-tagged messages; let it extract memories.
    messages = [
        {"role": "user", "content": query[:8000] if query else ""},
        {"role": "assistant", "content": response[:8000] if response else ""},
    ]
    metadata = {
        "workflow_id": workflow_id or "",
        "agent_id": agent_id,
        "agent_name": agent_name,
    }

    def _add() -> None:
        try:
            client.add(messages=messages, user_id=mem_user, metadata=metadata)
        except TypeError:
            client.add(messages, user_id=mem_user, metadata=metadata)
        except Exception as e:
            logger.debug("mem0 add failed for %s: %s", mem_user, e)

    try:
        await asyncio.to_thread(_add)
    except Exception as e:
        logger.debug("mem0 add threadpool failed: %s", e)


def is_available() -> bool:
    """True when mem0 is configured and ready (used for diagnostics)."""
    return _get_client() is not None


async def list_workflow_memories(
    *,
    workflow_id: Optional[str],
    user_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """Return all stored memories for *workflow_id* (admin viewer).

    When *user_id* is None, memories for every user that ran this workflow
    cannot be enumerated by mem0 (filters require a concrete user_id), so we
    fall back to the canonical "anonymous" bucket plus, when available, the
    caller-supplied id. Most workflow runs go through ``_agent_user_id`` which
    encodes both the workflow id and user id, so passing ``user_id`` here
    targets the specific run history.
    """
    client = _get_client()
    if client is None:
        return {"results": [], "available": False, "page": page, "page_size": page_size}

    mem_user = _agent_user_id(workflow_id, user_id)
    if mem_user is None:
        return {
            "results": [],
            "available": True,
            "error": "user_id is required — memory is per-user",
            "page": page,
            "page_size": page_size,
        }

    def _fetch() -> dict:
        try:
            res = client.get_all(
                filters={"user_id": mem_user},
                page=int(page),
                page_size=int(page_size),
            )
        except TypeError:
            res = client.get_all(user_id=mem_user, page=int(page), page_size=int(page_size))
        if isinstance(res, list):
            return {"results": res}
        if isinstance(res, dict):
            return res
        return {"results": []}

    try:
        data = await asyncio.to_thread(_fetch)
    except Exception as e:
        logger.warning("mem0 list failed for %s: %s", mem_user, e)
        return {
            "results": [],
            "available": True,
            "error": str(e),
            "page": page,
            "page_size": page_size,
        }

    results = data.get("results") if isinstance(data, dict) else []
    return {
        "results": results or [],
        "available": True,
        "page": page,
        "page_size": page_size,
        "mem_user_id": mem_user,
    }
