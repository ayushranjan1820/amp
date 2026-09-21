"""Hardcoded admin analytics, users, and auxiliary API payloads."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

PROTOTYPE_ADMIN_USER = "admin"
PROTOTYPE_ADMIN_PASSWORD = "admin123"

_NOW = datetime.now(timezone.utc)
_TODAY = _NOW.replace(hour=0, minute=0, second=0, microsecond=0)


def prototype_admin_user() -> Dict[str, Any]:
    return {
        "id": 1,
        "username": PROTOTYPE_ADMIN_USER,
        "role": "super_admin",
        "menu_permissions": [
            "overview", "agents", "sessions", "costs", "usage",
            "agent-studio", "knowledge-base", "settings", "chat", "agent-architecture",
        ],
        "agent_permissions": None,
        "is_active": True,
    }


def prototype_users_list() -> List[Dict[str, Any]]:
    return [
        {
            "id": 1,
            "username": "admin",
            "role": "super_admin",
            "menu_permissions": prototype_admin_user()["menu_permissions"],
            "agent_permissions": None,
            "is_active": True,
            "created_at": (_NOW - timedelta(days=90)).isoformat(),
        },
        {
            "id": 2,
            "username": "analyst",
            "role": "user",
            "menu_permissions": ["overview", "agents", "chat"],
            "agent_permissions": ["jira_agent", "basic_agent", "company_research"],
            "is_active": True,
            "created_at": (_NOW - timedelta(days=30)).isoformat(),
        },
    ]


def _totals_block(count: int, cost: float, tokens: int) -> Dict[str, Any]:
    prompt = int(tokens * 0.65)
    completion = tokens - prompt
    return {
        "total_events": count,
        "total_cost": round(cost, 4),
        "total_prompt_tokens": prompt,
        "total_completion_tokens": completion,
        "total_tokens": tokens,
    }


def prototype_cost_summary() -> Dict[str, Any]:
    agents = [
        ("JIRA Agent", 412, 18.42, 892000),
        ("Company Research Agent", 287, 14.08, 710000),
        ("Global Chat", 534, 22.15, 1240000),
        ("PPT Generator Agent", 156, 31.60, 980000),
        ("Basic Agent", 623, 8.94, 520000),
        ("BPMN Generator Agent", 98, 4.22, 210000),
    ]
    by_agent = [
        {"agent_name": n, "count": c, "cost": co, "tokens": t}
        for n, c, co, t in agents
    ]
    total_events = sum(a["count"] for a in by_agent)
    total_cost = sum(a["cost"] for a in by_agent)
    total_tokens = sum(a["tokens"] for a in by_agent)
    daily = []
    for i in range(7):
        d = (_TODAY - timedelta(days=6 - i)).date().isoformat()
        daily.append({"date": d, "count": 180 + i * 12, "cost": 8.5 + i * 0.7, "tokens": 95000 + i * 8000})
    recent = []
    for i, (name, count, cost, tokens) in enumerate(agents[:5]):
        recent.append({
            "id": i + 1,
            "event_type": "llm_completion",
            "agent_name": name,
            "model": "vertex_ai.gemini-2.5-pro",
            "prompt_tokens": int(tokens * 0.65 // count),
            "completion_tokens": int(tokens * 0.35 // count),
            "total_tokens": tokens // count,
            "estimated_cost": round(cost / count, 6),
            "metadata": {"source": "prototype"},
            "created_at": (_NOW - timedelta(hours=i * 3)).isoformat(),
        })
    return {
        "totals": _totals_block(total_events, total_cost, total_tokens),
        "today": _totals_block(89, 3.84, 142000),
        "by_type": [
            {"event_type": "llm_completion", "count": total_events - 40, "cost": total_cost * 0.92, "tokens": int(total_tokens * 0.92)},
            {"event_type": "embedding", "count": 40, "cost": total_cost * 0.08, "tokens": int(total_tokens * 0.08)},
        ],
        "today_by_type": [
            {"event_type": "llm_completion", "count": 82, "cost": 3.52, "tokens": 130000},
            {"event_type": "embedding", "count": 7, "cost": 0.32, "tokens": 12000},
        ],
        "by_agent": by_agent,
        "today_by_agent": [{"agent_name": a["agent_name"], "count": max(1, a["count"] // 14), "cost": round(a["cost"] / 14, 3), "tokens": a["tokens"] // 14} for a in by_agent[:4]],
        "daily_trend": daily,
        "recent_events": recent,
    }


def prototype_usage_summary() -> Dict[str, Any]:
    by_agent = [
        {"agent_name": "Global Chat", "count": 534},
        {"agent_name": "Basic Agent", "count": 623},
        {"agent_name": "JIRA Agent", "count": 412},
        {"agent_name": "Company Research Agent", "count": 287},
        {"agent_name": "PPT Generator Agent", "count": 156},
    ]
    daily = []
    for i in range(14):
        d = (_TODAY - timedelta(days=13 - i)).date().isoformat()
        daily.append({"date": d, "count": 95 + i * 4})
    return {
        "total_requests": 2847,
        "today_requests": 89,
        "by_agent": by_agent,
        "by_ip": [
            {
                "ip_address": "203.0.113.42",
                "city": "Mumbai",
                "region": "Maharashtra",
                "country": "India",
                "latitude": 19.076,
                "longitude": 72.8777,
                "zipcode": "400001",
                "timezone": "Asia/Kolkata",
                "isp": "Example ISP",
                "org": "PwC India",
                "count": 312,
            },
            {
                "ip_address": "198.51.100.18",
                "city": "London",
                "region": "England",
                "country": "United Kingdom",
                "latitude": 51.5074,
                "longitude": -0.1278,
                "zipcode": "EC1A",
                "timezone": "Europe/London",
                "isp": "Example ISP",
                "org": "PwC UK",
                "count": 198,
            },
        ],
        "by_country": [
            {"country": "India", "count": 842},
            {"country": "United Kingdom", "count": 521},
            {"country": "United States", "count": 467},
        ],
        "daily_trend": daily,
    }


def prototype_usage_logs(limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    logs: List[Dict[str, Any]] = []
    agents = ["JIRA Agent", "Global Chat", "Company Research Agent", "Basic Agent"]
    for i in range(50):
        logs.append({
            "id": i + 1,
            "agent_name": agents[i % len(agents)],
            "agent_id": "jira_agent",
            "ip_address": "203.0.113.42",
            "city": "Mumbai",
            "region": "Maharashtra",
            "country": "India",
            "user_agent": "Mozilla/5.0",
            "query_preview": f"Sample query #{i + 1} for analytics dashboard",
            "session_id": f"proto-session-{i // 4}",
            "created_at": (_NOW - timedelta(minutes=i * 17)).isoformat(),
            "latitude": 19.076,
            "longitude": 72.8777,
            "zipcode": "400001",
            "timezone": "Asia/Kolkata",
            "isp": "Example ISP",
            "org": "PwC India",
        })
    page = logs[offset : offset + limit]
    return {"logs": page, "limit": limit, "offset": offset, "total": len(logs)}


def prototype_ollama_models() -> Dict[str, Any]:
    return {"models": ["llama3.2", "qwen2.5:14b", "mistral-nemo", "gemma2:9b"]}


def prototype_pwc_models() -> Dict[str, Any]:
    return {
        "models": [
            "vertex_ai.gemini-2.5-pro",
            "vertex_ai.gemini-2.5-flash",
            "vertex_ai.gpt-4o",
            "vertex_ai.anthropic.claude-sonnet-4-6",
        ]
    }


def prototype_claude_models() -> Dict[str, Any]:
    return {
        "models": [
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
        ]
    }


def prototype_tts_voices() -> List[Dict[str, str]]:
    return [
        {"voice_id": "pFZP5JQG7iQjIQuC4Bku", "name": "Lily"},
        {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Sarah"},
    ]


def prototype_kb_status() -> Dict[str, Any]:
    return {"connected": True, "provider": "mongodb_atlas", "message": "Knowledge base ready"}


def prototype_kb_databases() -> Dict[str, Any]:
    return {"databases": ["agents_kb"]}


def prototype_kb_collections(db_name: str) -> Dict[str, Any]:
    return {"collections": ["documents", "policies", "runbooks"]}


def prototype_published_agents() -> List[Dict[str, Any]]:
    return [
        {
            "id": "custom-expense-bot",
            "slug": "expense-bot",
            "name": "Expense Policy Assistant",
            "description": "Answers questions about corporate expense policies and reimbursement workflows.",
            "status": "published",
            "owner_id": 1,
            "category": "Finance",
            "tags": ["expense", "policy"],
            "icon": "receipt",
            "usage_count": 128,
            "published_at": (_NOW - timedelta(days=12)).isoformat(),
        },
        {
            "id": "custom-onboarding-guide",
            "slug": "onboarding-guide",
            "name": "New Hire Onboarding Guide",
            "description": "Interactive onboarding assistant for day-one tasks and IT setup.",
            "status": "published",
            "owner_id": 1,
            "category": "HR",
            "tags": ["onboarding", "hr"],
            "icon": "users",
            "usage_count": 74,
            "published_at": (_NOW - timedelta(days=28)).isoformat(),
        },
    ]
