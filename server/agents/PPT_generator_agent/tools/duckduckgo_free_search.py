"""DuckDuckGo Web Search client for PPT Generator Agent.

Uses the ddgs package and returns results in the same shape consumed by the
PPT pipeline (title/url/date/snippet/content).
"""

import asyncio
from typing import Any, Dict, List, Optional

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


class PPTDuckDuckGoFreeSearch:
    def is_configured(self, api_key: Optional[str] = None) -> bool:
        # API key is unused for DuckDuckGo free search, but the optional argument
        # keeps call compatibility with other PPT search clients.
        return DDGS_AVAILABLE

    @staticmethod
    def _search_sync(
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        if not DDGS_AVAILABLE:
            return []

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max(1, min(10, int(max_results or 10)))))
        except Exception as e:
            print(f"DuckDuckGo web search error (PPT agent): {e}")
            return []

        out: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "title": (item.get("title") or "").strip(),
                    "url": (item.get("href") or item.get("url") or "").strip(),
                    "date": (item.get("date") or "").strip(),
                    "snippet": (item.get("body") or item.get("snippet") or "").strip(),
                    "content": (item.get("body") or item.get("content") or "").strip(),
                }
            )
        return out

    async def search(
        self,
        query: str,
        max_results: int = 10,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    async def research_topic(
        self,
        topic: str,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        from datetime import datetime

        year = datetime.now().year
        breaking_task = self.search(
            f"{topic} breaking news latest announcement update today {year}",
            max_results=6,
            api_key=api_key,
        )
        week_task = self.search(
            f"{topic} this week trends earnings regulatory announcement {year}",
            max_results=6,
            api_key=api_key,
        )
        month_task = self.search(
            f"{topic} latest developments analysis report {year}",
            max_results=6,
            api_key=api_key,
        )
        overview_task = self.search(
            f"{topic} overview key facts statistics market size TAM CAGR",
            max_results=6,
            api_key=api_key,
        )

        breaking, week, month, overview = await asyncio.gather(
            breaking_task, week_task, month_task, overview_task
        )

        for r in breaking:
            r["_tier"] = "breaking"
        for r in week:
            r["_tier"] = "week"
        for r in month:
            r["_tier"] = "month"
        for r in overview:
            r["_tier"] = "evergreen"

        merged: List[Dict[str, Any]] = []
        seen = set()
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
        from datetime import datetime

        year = datetime.now().year
        fq = (focus_query or "").strip() or f"latest facts statistics {year}"

        hour_task = self.search(
            f"{fq} latest breaking today",
            max_results=5,
            api_key=api_key,
        )
        day_task = self.search(
            f"{fq} news announcement update {year}",
            max_results=6,
            api_key=api_key,
        )
        week_task = self.search(
            f"{fq} analysis figures market share revenue CAGR",
            max_results=5,
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


ppt_duckduckgo_free_search = PPTDuckDuckGoFreeSearch()
