"""Perplexity web-search client for the PPT Generator Agent.

Mirrors the pattern used by Company_research_agent and Meeting_prep_agent:
client is built lazily (PERPLEXITY_API_KEY is injected per-request from the
merged agent config via ``apply_user_config``), so a missing key at import
time is not an error — callers must guard with ``is_configured()``.
"""

import os
import asyncio
from typing import List, Dict, Any, Optional, Literal

RecencyFilter = Literal["hour", "day", "week", "month", "year"]

try:
    from perplexity import Perplexity
    PERPLEXITY_AVAILABLE = True
except ImportError:
    PERPLEXITY_AVAILABLE = False

from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")


class PPTPerplexitySearch:

    def __init__(self):
        self.client = None
        self._client_api_key: Optional[str] = None

    def is_configured(self, api_key: Optional[str] = None) -> bool:
        """True when Perplexity SDK is installed AND an API key is available.

        When ``api_key`` is passed explicitly (the PPT agent does this —
        the key must come from agent config, not server/.env), that value
        is authoritative and no env lookup happens.
        """
        if not PERPLEXITY_AVAILABLE:
            return False
        if api_key is not None:
            return bool(api_key.strip())
        return bool((os.getenv("PERPLEXITY_API_KEY") or "").strip())

    def _ensure_client(self, api_key_override: Optional[str] = None) -> bool:
        """Build (or reuse) the Perplexity client.

        ``api_key_override`` wins over env. When passed as a non-None value,
        env is never consulted — this is how the PPT agent enforces the
        agent-config-only contract.
        """
        if not PERPLEXITY_AVAILABLE:
            return False
        if api_key_override is not None:
            api_key = api_key_override.strip()
        else:
            api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
        if not api_key:
            self.client = None
            self._client_api_key = None
            return False
        if self.client is not None and self._client_api_key == api_key:
            return True
        self.client = Perplexity(api_key=api_key)
        self._client_api_key = api_key
        return True

    @staticmethod
    def _extract_field(result: Any, *names: str) -> Optional[str]:
        for n in names:
            v = getattr(result, n, None)
            if v:
                return v
        return None

    def _search_sync(
        self,
        query: str,
        max_results: int = 10,
        search_recency_filter: Optional[RecencyFilter] = "month",
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self._ensure_client(api_key_override=api_key):
            return []

        try:
            create_kwargs: Dict[str, Any] = {
                "query": query,
                "max_results": max_results,
            }
            if search_recency_filter is not None:
                create_kwargs["search_recency_filter"] = search_recency_filter

            search = self.client.search.create(**create_kwargs)

            try:
                from cost_tracker import log_cost_event
                log_cost_event(
                    event_type="perplexity_search",
                    agent_name="PPT Generator Agent",
                    metadata={"query": query[:120]},
                )
            except Exception:
                pass

            results: List[Dict[str, Any]] = []
            for r in search.results:
                results.append({
                    "title": self._extract_field(r, "title") or "",
                    "url": self._extract_field(r, "url") or "",
                    "date": self._extract_field(r, "date", "published_date", "publishedDate"),
                    "snippet": self._extract_field(r, "snippet", "description") or "",
                    "content": self._extract_field(r, "content", "text") or "",
                })
            return results

        except Exception as e:
            print(f"Perplexity search error (PPT agent): {e}")
            return []

    async def search(
        self,
        query: str,
        max_results: int = 10,
        search_recency_filter: Optional[RecencyFilter] = "month",
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._search_sync, query, max_results, search_recency_filter, api_key
        )

    async def research_topic(
        self,
        topic: str,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run four parallel searches covering different freshness tiers so
        the deck is grounded in up-to-the-day information, not stale facts.

        Tiers:
          • Breaking (≤24h) — breaking news / latest announcements
          • This week   — trends, recent earnings, regulatory moves
          • This month  — deeper recent context, reports, analysis
          • Evergreen   — foundational sizing, definitions, historical data

        Results are merged with recent tiers prioritised, then deduped by URL.
        """
        from datetime import datetime
        year = datetime.now().year
        breaking_task = self.search(
            f"{topic} breaking news latest announcement update today {year}",
            max_results=6,
            search_recency_filter="day",
            api_key=api_key,
        )
        week_task = self.search(
            f"{topic} this week trends earnings regulatory announcement {year}",
            max_results=6,
            search_recency_filter="week",
            api_key=api_key,
        )
        month_task = self.search(
            f"{topic} latest developments analysis report {year}",
            max_results=6,
            search_recency_filter="month",
            api_key=api_key,
        )
        overview_task = self.search(
            f"{topic} overview key facts statistics market size TAM CAGR",
            max_results=6,
            search_recency_filter=None,
            api_key=api_key,
        )
        breaking, week, month, overview = await asyncio.gather(
            breaking_task, week_task, month_task, overview_task
        )

        # Tag each result with its freshness tier so the prompt formatter can
        # surface latest-first and the LLM can prioritise recent data.
        for r in breaking: r["_tier"] = "breaking"
        for r in week:     r["_tier"] = "week"
        for r in month:    r["_tier"] = "month"
        for r in overview: r["_tier"] = "evergreen"

        merged: List[Dict[str, Any]] = []
        seen = set()
        # Freshness order: breaking → week → month → evergreen
        for r in (breaking + week + month + overview):
            url = r.get("url") or ""
            key = url or (r.get("title", "") + r.get("snippet", ""))[:120]
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)
        return merged[:18]

    async def research_slide_focus(
        self,
        focus_query: str,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Parallel searches tuned for a single slide — prioritises very recent web data.

        Used when many slides each need their own research batch; lighter than
        ``research_topic`` (3 tiers instead of 4 + overview) but still merges
        with freshness ordering.
        """
        from datetime import datetime
        year = datetime.now().year
        fq = (focus_query or "").strip() or f"latest facts statistics {year}"

        hour_task = self.search(
            f"{fq} latest breaking today",
            max_results=5,
            search_recency_filter="hour",
            api_key=api_key,
        )
        day_task = self.search(
            f"{fq} news announcement update {year}",
            max_results=6,
            search_recency_filter="day",
            api_key=api_key,
        )
        week_task = self.search(
            f"{fq} analysis figures market share revenue CAGR",
            max_results=5,
            search_recency_filter="week",
            api_key=api_key,
        )
        hour_r, day_r, week_r = await asyncio.gather(hour_task, day_task, week_task)

        for r in hour_r:
            r["_tier"] = "breaking"
        for r in day_r:
            r["_tier"] = "breaking"
        for r in week_r:
            r["_tier"] = "week"

        merged: List[Dict[str, Any]] = []
        seen = set()
        for r in hour_r + day_r + week_r:
            url = r.get("url") or ""
            key = url or (r.get("title", "") + (r.get("snippet") or ""))[:120]
            if key in seen:
                continue
            seen.add(key)
            merged.append(r)
        return merged[:14]


_TIER_LABELS = {
    "breaking": "LAST 24 HOURS — BREAKING",
    "week":     "THIS WEEK",
    "month":    "THIS MONTH",
    "evergreen": "FOUNDATIONAL / EVERGREEN",
}


def format_research_for_prompt(results: List[Dict[str, Any]], char_budget: int = 6500) -> str:
    """Render search results as a compact reference block the LLM can read.

    Groups results by freshness tier (breaking → week → month → evergreen)
    and labels each group prominently so the LLM prioritises the most
    recent data when drafting slides. Truncates each snippet to ~500 chars
    and stops when the char_budget is exhausted.
    """
    if not results:
        return ""

    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    header = (
        f"RESEARCH FINDINGS — today is {today}. Data is grouped by freshness; "
        "entries labelled LAST 24 HOURS / THIS WEEK are the most current and MUST be cited over older sources when they conflict.\n"
    )
    lines: List[str] = [header]
    used = len(header)

    # Group by tier in the canonical order
    tier_order = ["breaking", "week", "month", "evergreen"]
    grouped: Dict[str, List[Dict[str, Any]]] = {t: [] for t in tier_order}
    for r in results:
        tier = r.get("_tier") or "evergreen"
        grouped.setdefault(tier, []).append(r)

    idx = 0
    for tier in tier_order:
        bucket = grouped.get(tier) or []
        if not bucket:
            continue
        section_header = f"\n━━ {_TIER_LABELS[tier]} ━━\n"
        if used + len(section_header) > char_budget:
            break
        lines.append(section_header)
        used += len(section_header)

        for r in bucket:
            idx += 1
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            date = (r.get("date") or "").strip()
            body = (r.get("content") or r.get("snippet") or "").strip()
            if len(body) > 500:
                body = body[:500].rsplit(" ", 1)[0] + "…"

            block = f"[{idx}] {title}"
            if date:
                block += f" ({date})"
            if url:
                block += f"\n    URL: {url}"
            if body:
                block += f"\n    {body}"
            block += "\n"

            if used + len(block) > char_budget:
                return "\n".join(lines)
            lines.append(block)
            used += len(block)

    return "\n".join(lines)


ppt_perplexity_search = PPTPerplexitySearch()
