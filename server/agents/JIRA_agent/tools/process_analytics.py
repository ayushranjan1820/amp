"""Analytics processing for JIRA agent — computes chart data from live JIRA issues."""
from typing import Dict, Any, Optional
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from ..core.logging import log_info, log_error
from ..helpers.conversation_manager import ConversationContext, ConversationState


async def compute_analytics(jira_service) -> Dict[str, Any]:
    """Fetch all project issues from JIRA and compute analytics data for charts.

    Returns a dict with:
        status_distribution  – list[{name, value}]
        priority_distribution – list[{name, value}]
        type_distribution    – list[{name, value}]
        assignee_distribution – list[{name, value}]  (top 10)
        creation_trend       – list[{date, count}]   (last 30 days)
        summary              – {total, open, in_progress, done, unassigned}
    """
    settings = jira_service.settings
    project_key = getattr(settings, "jira_project_key", None) or "KAN"
    jql = f"project = {project_key} ORDER BY created DESC"

    issues = await jira_service.search_with_jql(jql, max_results=500)
    log_info(f"Analytics: fetched {len(issues)} issues from {project_key}", "analytics")

    status_counts: Dict[str, int] = defaultdict(int)
    priority_counts: Dict[str, int] = defaultdict(int)
    type_counts: Dict[str, int] = defaultdict(int)
    assignee_counts: Dict[str, int] = defaultdict(int)
    day_counts: Dict[str, int] = defaultdict(int)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30)

    open_statuses = {"to do", "open", "backlog", "todo", "new", "reopened"}
    in_progress_statuses = {"in progress", "in review", "review", "testing", "in development"}
    done_statuses = {"done", "closed", "resolved", "complete", "completed"}

    open_count = 0
    in_progress_count = 0
    done_count = 0
    unassigned_count = 0

    for issue in issues:
        status = issue.get("status") or "Unknown"
        priority = issue.get("priority") or "Medium"
        issue_type = issue.get("issueType") or "Story"
        assignee = issue.get("assignee") or None
        created_str = issue.get("created") or ""

        status_counts[status] += 1
        priority_counts[priority] += 1
        type_counts[issue_type] += 1

        status_lower = status.lower()
        if status_lower in open_statuses:
            open_count += 1
        elif status_lower in in_progress_statuses:
            in_progress_count += 1
        elif status_lower in done_statuses:
            done_count += 1
        else:
            open_count += 1

        if assignee:
            assignee_counts[assignee] += 1
        else:
            unassigned_count += 1

        if created_str:
            try:
                dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                if dt >= cutoff:
                    day_key = dt.strftime("%Y-%m-%d")
                    day_counts[day_key] += 1
            except Exception:
                pass

    # Build last-30-day date range, filling gaps with 0
    trend = []
    for i in range(30):
        day = (cutoff + timedelta(days=i + 1)).strftime("%Y-%m-%d")
        trend.append({"date": day, "count": day_counts.get(day, 0)})

    # ── Burndown chart data ────────────────────────────────────────────────────
    # For each day in last 30 days compute:
    #   remaining = issues created on/before that day - issues resolved on/before that day
    # ideal = linear decrease from day-0 remaining to 0
    def _parse_dt(s: str | None):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    # Pre-parse dates for all issues
    parsed_issues = []
    for issue in issues:
        created_dt = _parse_dt(issue.get("created"))
        resolved_dt = _parse_dt(issue.get("resolutiondate"))
        parsed_issues.append((created_dt, resolved_dt))

    burndown_period_days = 30
    burndown = []
    for i in range(burndown_period_days + 1):
        day_dt = (cutoff + timedelta(days=i)).replace(hour=23, minute=59, second=59)
        existing = sum(1 for cd, _ in parsed_issues if cd and cd <= day_dt)
        resolved = sum(1 for cd, rd in parsed_issues if cd and cd <= day_dt and rd and rd <= day_dt)
        burndown.append({
            "date": day_dt.strftime("%Y-%m-%d"),
            "remaining": existing - resolved,
        })

    # Attach ideal line — linear from the PEAK remaining in the period down to 0.
    # Using peak (not day-0) handles Kanban boards that ramp up before burning down.
    peak_remaining = max((p["remaining"] for p in burndown), default=0)
    total_days = max(len(burndown) - 1, 1)
    for i, point in enumerate(burndown):
        point["ideal"] = round(peak_remaining * (1 - i / total_days))

    # Top 10 assignees
    sorted_assignees = sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    if unassigned_count:
        sorted_assignees.append(("Unassigned", unassigned_count))

    # Priority sort order
    priority_order = ["Highest", "High", "Medium", "Low", "Lowest"]
    priority_dist = sorted(
        [{"name": k, "value": v} for k, v in priority_counts.items()],
        key=lambda x: priority_order.index(x["name"]) if x["name"] in priority_order else 99
    )

    return {
        "status_distribution": [{"name": k, "value": v} for k, v in sorted(status_counts.items(), key=lambda x: -x[1])],
        "priority_distribution": priority_dist,
        "type_distribution": [{"name": k, "value": v} for k, v in sorted(type_counts.items(), key=lambda x: -x[1])],
        "assignee_distribution": [{"name": k, "value": v} for k, v in sorted_assignees],
        "creation_trend": trend,
        "burndown_data": burndown,
        "summary": {
            "total": len(issues),
            "open": open_count,
            "in_progress": in_progress_count,
            "done": done_count,
            "unassigned": unassigned_count,
        },
    }


async def process_analytics(
    user_prompt: str,
    conversation_ctx: ConversationContext,
    jira_service,
    ai_service,
    context,
) -> Dict[str, Any]:
    """Handle ANALYTICS intent — compute chart data and return an enriched response."""
    conversation_ctx.state = ConversationState.COMPLETED

    try:
        chart_data = await compute_analytics(jira_service)
        summary = chart_data["summary"]
        total = summary["total"]
        done = summary["done"]
        in_prog = summary["in_progress"]
        open_ = summary["open"]
        unassigned = summary["unassigned"]

        top_status = chart_data["status_distribution"][0]["name"] if chart_data["status_distribution"] else "N/A"
        top_priority = chart_data["priority_distribution"][0]["name"] if chart_data["priority_distribution"] else "N/A"

        response = (
            f"## Project Analytics Dashboard\n\n"
            f"Here's a live snapshot of your JIRA project:\n\n"
            f"**Overview**\n"
            f"- **Total Issues:** {total}\n"
            f"- **Open / To Do:** {open_}\n"
            f"- **In Progress:** {in_prog}\n"
            f"- **Done / Resolved:** {done}\n"
            f"- **Unassigned:** {unassigned}\n\n"
            f"**Top Status:** {top_status} &nbsp;|&nbsp; **Top Priority:** {top_priority}\n\n"
            f"The charts below show the full breakdown across status, priority, issue type, assignees, and creation trends over the last 30 days."
        )

        return {
            "success": True,
            "state": conversation_ctx.state.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "analytics",
            "response": response,
            "tickets": [],
            "collected_data": conversation_ctx.collected_data,
            "chart_data": chart_data,
        }

    except Exception as e:
        log_error("Analytics computation failed", "analytics", e)
        return {
            "success": False,
            "state": ConversationState.INITIAL.value,
            "session_id": conversation_ctx.session_id,
            "prompt": user_prompt,
            "intent": "analytics",
            "response": f"Could not load analytics data: {str(e)}. Please check that JIRA is configured correctly.",
            "tickets": [],
        }
