"""Cost event logging & summary aggregation — MongoDB-backed.

Migrated from PostgreSQL in 2026-05. Public function signatures preserved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING

from mongo_db import get_db, next_seq, utcnow


COST_EVENTS = "cost_events"


def get_connection():
    """Compatibility shim — returns the pymongo Database."""
    return get_db()


def init_cost_tracking_db() -> None:
    try:
        db = get_db()
        db[COST_EVENTS].create_index("event_type", name="idx_cost_events_type")
        db[COST_EVENTS].create_index("agent_name", name="idx_cost_events_agent")
        db[COST_EVENTS].create_index([("created_at", DESCENDING)], name="idx_cost_events_created")
        print("[CostTracker] Database collection initialized")
    except Exception as e:
        print(f"[CostTracker] DB init error: {e}")


COST_RATES: Dict[str, Any] = {
    "llm_call": {
        "": {"input_per_1m": 0.10, "output_per_1m": 0.40},
        "vertex_ai.gemini-1.5-flash": {"input_per_1m": 0.075, "output_per_1m": 0.30},
        "vertex_ai.gemini-1.5-pro": {"input_per_1m": 1.25, "output_per_1m": 5.00},
        "gpt-4o": {"input_per_1m": 2.50, "output_per_1m": 10.00},
        "gpt-4": {"input_per_1m": 30.00, "output_per_1m": 60.00},
        "gpt-3.5-turbo": {"input_per_1m": 0.50, "output_per_1m": 1.50},
    },
    "perplexity_search": 0.005,
    "email_send": 0.00,
    "web_search": 0.005,
}


def _estimate_llm_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    rates = COST_RATES["llm_call"].get(model, {"input_per_1m": 0.10, "output_per_1m": 0.40})
    input_cost = (prompt_tokens / 1_000_000) * rates["input_per_1m"]
    output_cost = (completion_tokens / 1_000_000) * rates["output_per_1m"]
    return round(input_cost + output_cost, 6)


def log_cost_event(
    event_type: str,
    agent_name: str,
    model: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    estimated_cost: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
):
    try:
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)
        if estimated_cost is None:
            if event_type == "llm_call" and model:
                estimated_cost = _estimate_llm_cost(model, prompt_tokens, completion_tokens)
            elif event_type in COST_RATES:
                estimated_cost = COST_RATES[event_type]
            else:
                estimated_cost = 0.0

        db = get_db()
        db[COST_EVENTS].insert_one({
            "_id": next_seq("cost_events"),
            "event_type": event_type,
            "agent_name": agent_name,
            "model": model,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "estimated_cost": float(estimated_cost or 0.0),
            "metadata": metadata or {},
            "created_at": utcnow(),
        })
    except Exception as e:
        print(f"[CostTracker] Failed to log event: {e}")


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _aggregate_totals(match: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db()
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": None,
            "total_events": {"$sum": 1},
            "total_cost": {"$sum": {"$ifNull": ["$estimated_cost", 0]}},
            "total_prompt_tokens": {"$sum": {"$ifNull": ["$prompt_tokens", 0]}},
            "total_completion_tokens": {"$sum": {"$ifNull": ["$completion_tokens", 0]}},
            "total_tokens": {"$sum": {"$ifNull": ["$total_tokens", 0]}},
        }},
    ]
    rows = list(db[COST_EVENTS].aggregate(pipeline))
    if not rows:
        return {
            "total_events": 0,
            "total_cost": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
        }
    out = rows[0]
    out.pop("_id", None)
    return out


def _aggregate_grouped(match: Dict[str, Any], field: str) -> List[Dict[str, Any]]:
    db = get_db()
    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": f"${field}",
            "count": {"$sum": 1},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost", 0]}},
            "tokens": {"$sum": {"$ifNull": ["$total_tokens", 0]}},
        }},
        {"$sort": {"cost": -1}},
    ]
    rows = []
    for r in db[COST_EVENTS].aggregate(pipeline):
        rows.append({
            field: r["_id"],
            "count": r["count"],
            "cost": r["cost"],
            "tokens": r["tokens"],
        })
    return rows


def get_cost_summary() -> Dict[str, Any]:
    db = get_db()
    today_start = _today_start()
    today_match = {"created_at": {"$gte": today_start}}

    totals = _aggregate_totals({})
    today = _aggregate_totals(today_match)

    by_type = _aggregate_grouped({}, "event_type")
    today_by_type = _aggregate_grouped(today_match, "event_type")
    by_agent = _aggregate_grouped({}, "agent_name")
    today_by_agent = _aggregate_grouped(today_match, "agent_name")

    seven_days_ago = today_start - timedelta(days=7)
    daily_pipeline = [
        {"$match": {"created_at": {"$gte": seven_days_ago}}},
        {"$group": {
            "_id": {"$dateTrunc": {"date": "$created_at", "unit": "day"}},
            "count": {"$sum": 1},
            "cost": {"$sum": {"$ifNull": ["$estimated_cost", 0]}},
            "tokens": {"$sum": {"$ifNull": ["$total_tokens", 0]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_trend = []
    for r in db[COST_EVENTS].aggregate(daily_pipeline):
        d = r["_id"]
        daily_trend.append({
            "date": d.date().isoformat() if hasattr(d, "date") else (d.isoformat() if d else None),
            "count": r["count"],
            "cost": r["cost"],
            "tokens": r["tokens"],
        })

    recent_cursor = db[COST_EVENTS].find({}).sort("created_at", DESCENDING).limit(50)
    recent: List[Dict[str, Any]] = []
    for r in recent_cursor:
        row = dict(r)
        row["id"] = row.get("id") or row.get("_id")
        row.pop("_id", None)
        if row.get("created_at") and hasattr(row["created_at"], "isoformat"):
            row["created_at"] = row["created_at"].isoformat()
        recent.append(row)

    return {
        "totals": totals,
        "today": today,
        "by_type": by_type,
        "today_by_type": today_by_type,
        "by_agent": by_agent,
        "today_by_agent": today_by_agent,
        "daily_trend": daily_trend,
        "recent_events": recent,
    }
