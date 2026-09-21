"""Hardcoded agent builder API."""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi.responses import StreamingResponse

from .fixtures import prototype_published_agents


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_agent(**overrides) -> Dict[str, Any]:
    row = {
        "id": str(uuid.uuid4()),
        "slug": "demo-assistant",
        "owner_id": 1,
        "name": "Demo Assistant",
        "description": "A sample custom agent for demonstration.",
        "category_id": "general",
        "logo_url": "",
        "version": "1.0.0",
        "status": "draft",
        "visibility": "private",
        "agent_type": "chat",
        "system_prompt": "You are a helpful assistant.",
        "llm_provider": "pwc_genai",
        "llm_model": "vertex_ai.gemini-2.5-pro",
        "temperature": 0.7,
        "max_tokens": 4096,
        "tools_config": [],
        "capabilities": [],
        "example_prompts": [],
        "required_env_keys": [],
        "default_config": {},
        "default_config_meta": {},
        "downloads": 0,
        "rating": 0,
        "featured": False,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "published_at": None,
    }
    row.update(overrides)
    return row


_store: Dict[str, Dict[str, Any]] = {
    "builder-demo-001": _base_agent(
        id="builder-demo-001",
        slug="demo-assistant",
        name="Demo Assistant",
        owner_id=1,
    )
}


def list_agents(owner_id: Optional[int] = None, **_) -> Dict[str, Any]:
    agents = list(_store.values())
    if owner_id is not None:
        agents = [a for a in agents if a.get("owner_id") == owner_id]
    return {"agents": agents, "total": len(agents)}


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    row = _store.get(agent_id)
    return copy.deepcopy(row) if row else None


def create_agent(payload: Dict[str, Any], owner_id: int) -> Dict[str, Any]:
    agent_id = str(uuid.uuid4())
    row = _base_agent(
        id=agent_id,
        owner_id=owner_id,
        slug=payload.get("slug") or f"agent-{agent_id[:8]}",
        name=payload.get("name", "Untitled Agent"),
        description=payload.get("description", ""),
        system_prompt=payload.get("system_prompt", ""),
        llm_model=payload.get("llm_model", "vertex_ai.gemini-2.5-pro"),
        llm_provider=payload.get("llm_provider", "pwc_genai"),
        category_id=payload.get("category_id", "general"),
        logo_url=payload.get("logo_url", ""),
        visibility=payload.get("visibility", "private"),
        temperature=payload.get("temperature", 0.7),
        max_tokens=payload.get("max_tokens", 4096),
        tools_config=payload.get("tools_config", []),
        capabilities=payload.get("capabilities", []),
        example_prompts=payload.get("example_prompts", []),
        required_env_keys=payload.get("required_env_keys", []),
        default_config=payload.get("default_config", {}),
    )
    _store[agent_id] = row
    return copy.deepcopy(row)


def update_agent(agent_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    row = _store.get(agent_id)
    if not row:
        return None
    for k, v in payload.items():
        if v is not None and k not in ("id", "owner_id"):
            row[k] = v
    row["updated_at"] = _now_iso()
    return copy.deepcopy(row)


def delete_agent(agent_id: str) -> bool:
    return _store.pop(agent_id, None) is not None


def clone_agent(agent_id: str, owner_id: int) -> Optional[Dict[str, Any]]:
    src = _store.get(agent_id)
    if not src:
        return None
    new_id = str(uuid.uuid4())
    row = copy.deepcopy(src)
    row.update({"id": new_id, "slug": f"{src.get('slug', 'agent')}-copy", "name": f"{src.get('name')} (Copy)", "status": "draft", "owner_id": owner_id, "updated_at": _now_iso(), "created_at": _now_iso()})
    _store[new_id] = row
    return copy.deepcopy(row)


def list_tools() -> List[Dict[str, Any]]:
    return [
        {"id": "web_search", "slug": "web_search", "name": "Web Search", "description": "Search the web", "tool_type": "builtin", "schema_config": {}, "implementation": {}, "is_system": True, "created_at": _now_iso()},
        {"id": "send_email", "slug": "send_email", "name": "Send Email", "description": "Send emails", "tool_type": "builtin", "schema_config": {}, "implementation": {}, "is_system": True, "created_at": _now_iso()},
    ]


def list_versions(agent_id: str) -> List[Dict[str, Any]]:
    row = _store.get(agent_id)
    if not row:
        return []
    return [{"id": "v1", "agent_id": agent_id, "version": row.get("version", "1.0.0"), "system_prompt": row.get("system_prompt", ""), "tools_config": row.get("tools_config", []), "llm_config": {}, "changelog": "Initial version", "created_at": row.get("updated_at")}]


def get_published() -> List[Dict[str, Any]]:
    published = prototype_published_agents()
    out = []
    for p in published:
        row = _base_agent(**{k: v for k, v in p.items() if k not in ("status", "visibility")})
        row["status"] = "published"
        row["visibility"] = "public"
        out.append(row)
    return out


def agent_stats(agent_id: str, days: int = 30) -> Dict[str, Any]:
    return {
        "window_days": days,
        "totals": {"calls": 42, "input_tokens": 12000, "output_tokens": 8000, "tool_calls": 6, "errors": 0, "avg_duration_ms": 1200, "p50_duration_ms": 980, "p95_duration_ms": 2400, "last_call": _now_iso()},
        "series": [{"day": "2025-06-28", "calls": 8, "errors": 0, "tokens": 3200}],
    }


async def test_agent_stream(agent_id: str, query: str, session_id: Optional[str] = None):
    """Run the saved custom-agent configuration in the test playground.

    Reads from the real, persistent agent store (agent_registry) rather than
    this module's in-memory dict — agents created via the builder UI are
    stored there, and default_config needs decrypting for the LLM call.
    """
    from datetime import datetime, timezone
    from agents.llm_continuation import set_current_agent, set_current_session
    from api import _llm_call_async
    from user_config import apply_user_config
    import agent_registry

    agent = agent_registry.get_agent_for_runtime(agent_id)
    if not agent:
        async def missing_stream():
            yield f"data: {json.dumps({'event': 'error', 'data': {'message': 'Agent not found'}})}\n\n"

        return StreamingResponse(missing_stream(), media_type="text/event-stream")

    name = agent.get("name") or "Custom Agent"
    sid = session_id or f"test-{agent_id}"
    system_prompt = (agent.get("system_prompt") or "").strip()
    if not system_prompt:
        system_prompt = "You are a helpful assistant. Answer the user's request clearly and accurately."

    model = (agent.get("llm_model") or "").strip()
    temperature = float(agent.get("temperature", 0.7) or 0.7)
    max_tokens = int(agent.get("max_tokens", 4096) or 4096)
    prompt = f"{system_prompt}\n\nUser request:\n{query}\n\nAssistant response:"

    async def event_stream():
        started = datetime.now(timezone.utc).isoformat()
        yield f"data: {json.dumps({'event': 'start', 'data': {'agent': name, 'timestamp': started}})}\n\n"
        yield f"data: {json.dumps({'event': 'thinking', 'data': {'type': 'thinking', 'content': 'Applied the configured system prompt to generate the response above.'}})}\n\n"

        try:
            set_current_agent(name)
            set_current_session(sid)
            with apply_user_config(agent.get("default_config") or {}):
                response = await _llm_call_async(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=model or None,
                )

            response = str(response or "").strip()
            if not response:
                raise ValueError("The configured model returned an empty response.")

            for start in range(0, len(response), 100):
                chunk = response[start:start + 100]
                yield f"data: {json.dumps({'event': 'response_chunk', 'data': {'chunk': chunk}})}\n\n"
                await asyncio.sleep(0.02)

            yield f"data: {json.dumps({'event': 'done', 'data': {'response': response, 'agent': name, 'turn': 1}})}\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield f"data: {json.dumps({'event': 'error', 'data': {'message': f'Custom agent failed: {exc}'}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
