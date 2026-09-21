"""Usage analytics & geolocation logging — MongoDB-backed.

Migrated from PostgreSQL in 2026-05. Public function signatures preserved.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pymongo import ASCENDING, DESCENDING

from mongo_db import get_db, next_seq, utcnow


USAGE_LOGS = "usage_logs"


def get_connection():
    """Compatibility shim — returns the pymongo Database."""
    return get_db()


def init_usage_tracking_db() -> None:
    try:
        db = get_db()
        db[USAGE_LOGS].create_index("agent_name", name="idx_usage_logs_agent")
        db[USAGE_LOGS].create_index("ip_address", name="idx_usage_logs_ip")
        db[USAGE_LOGS].create_index([("created_at", DESCENDING)], name="idx_usage_logs_created")
        print("[UsageTracker] Database collection initialized")
    except Exception as e:
        print(f"[UsageTracker] DB init error: {e}")


def log_usage(
    agent_name: str,
    ip_address: Optional[str] = None,
    agent_id: Optional[str] = None,
    city: Optional[str] = None,
    region: Optional[str] = None,
    country: Optional[str] = None,
    location_raw: Optional[str] = None,
    user_agent: Optional[str] = None,
    query_preview: Optional[str] = None,
    session_id: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    zipcode: Optional[str] = None,
    timezone: Optional[str] = None,
    isp: Optional[str] = None,
    org: Optional[str] = None,
):
    try:
        db = get_db()
        db[USAGE_LOGS].insert_one({
            "_id": next_seq("usage_logs"),
            "agent_name": agent_name,
            "agent_id": agent_id,
            "ip_address": ip_address,
            "city": city,
            "region": region,
            "country": country,
            "location_raw": location_raw,
            "user_agent": user_agent,
            "query_preview": (query_preview[:200] if query_preview else None),
            "session_id": session_id,
            "latitude": latitude,
            "longitude": longitude,
            "zipcode": zipcode,
            "timezone": timezone,
            "isp": isp,
            "org": org,
            "created_at": utcnow(),
        })
    except Exception as e:
        print(f"[UsageTracker] Log error: {e}")


def resolve_ip_location(ip_address: Optional[str]) -> Dict[str, Any]:
    if not ip_address or ip_address in ("127.0.0.1", "::1", "unknown"):
        return {"city": "Local", "region": "", "country": "Local", "lat": None, "lon": None,
                "zip": "", "timezone": "", "isp": "", "org": ""}
    try:
        import httpx

        resp = httpx.get(
            f"http://ip-api.com/json/{ip_address}?fields=status,city,regionName,country,lat,lon,zip,timezone,isp,org,district",
            timeout=3.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                district = data.get("district", "")
                city = data.get("city", "")
                if district and district != city:
                    city = f"{district}, {city}"
                return {
                    "city": city,
                    "region": data.get("regionName", ""),
                    "country": data.get("country", ""),
                    "lat": data.get("lat"),
                    "lon": data.get("lon"),
                    "zip": data.get("zip", ""),
                    "timezone": data.get("timezone", ""),
                    "isp": data.get("isp", ""),
                    "org": data.get("org", ""),
                }
    except Exception:
        pass
    return {"city": "", "region": "", "country": "", "lat": None, "lon": None,
            "zip": "", "timezone": "", "isp": "", "org": ""}


def count_usage_logs(agent_filter: Optional[str] = None) -> int:
    db = get_db()
    q: Dict[str, Any] = {}
    if agent_filter:
        q["agent_name"] = agent_filter
    return int(db[USAGE_LOGS].count_documents(q))


def get_usage_logs(limit: int = 100, offset: int = 0, agent_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    db = get_db()
    q: Dict[str, Any] = {}
    if agent_filter:
        q["agent_name"] = agent_filter
    cursor = db[USAGE_LOGS].find(q).sort("created_at", DESCENDING).skip(int(offset)).limit(int(limit))
    out: List[Dict[str, Any]] = []
    for r in cursor:
        row = dict(r)
        row["id"] = row.get("id") or row.get("_id")
        row.pop("_id", None)
        out.append(row)
    return out


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_usage_summary() -> Dict[str, Any]:
    db = get_db()
    total = int(db[USAGE_LOGS].count_documents({}))
    today_start = _today_start()
    today = int(db[USAGE_LOGS].count_documents({"created_at": {"$gte": today_start}}))

    by_agent_pipeline = [
        {"$group": {"_id": "$agent_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_agent = [
        {"agent_name": r["_id"], "count": r["count"]}
        for r in db[USAGE_LOGS].aggregate(by_agent_pipeline)
    ]

    by_ip_pipeline = [
        {"$match": {"ip_address": {"$ne": None}}},
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": {
                "ip_address": "$ip_address",
                "city": "$city",
                "region": "$region",
                "country": "$country",
            },
            "latitude": {"$first": "$latitude"},
            "longitude": {"$first": "$longitude"},
            "zipcode": {"$first": "$zipcode"},
            "timezone": {"$first": "$timezone"},
            "isp": {"$first": "$isp"},
            "org": {"$first": "$org"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    by_ip = []
    for r in db[USAGE_LOGS].aggregate(by_ip_pipeline):
        key = r.pop("_id")
        row = {**key, **{k: r[k] for k in ("latitude", "longitude", "zipcode", "timezone", "isp", "org", "count")}}
        by_ip.append(row)

    by_country_pipeline = [
        {"$match": {"country": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$country", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 15},
    ]
    by_country = [
        {"country": r["_id"], "count": r["count"]}
        for r in db[USAGE_LOGS].aggregate(by_country_pipeline)
    ]

    daily_pipeline = [
        {"$group": {
            "_id": {"$dateTrunc": {"date": "$created_at", "unit": "day"}},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": -1}},
        {"$limit": 30},
    ]
    daily = []
    for r in db[USAGE_LOGS].aggregate(daily_pipeline):
        d = r["_id"]
        daily.append({
            "date": d.date().isoformat() if hasattr(d, "date") else (d.isoformat() if d else None),
            "count": r["count"],
        })

    return {
        "total_requests": total,
        "today_requests": today,
        "by_agent": by_agent,
        "by_ip": by_ip,
        "by_country": by_country,
        "daily_trend": daily,
    }
