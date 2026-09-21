"""Ollama Web Search client for PPT Generator Agent.

Uses Ollama's free web-search endpoint and returns results in the same
shape consumed by the PPT pipeline (title/url/date/snippet/content).
"""

import os
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")


class PPTOllamaFreeSearch:
    def __init__(self):
        self.base_url = (os.getenv("OLLAMA_WEB_SEARCH_BASE_URL") or "https://ollama.com").rstrip("/")

    def is_configured(self, api_key: Optional[str] = None) -> bool:
        """True when an API key is available.

        If ``api_key`` is provided, that value is authoritative so callers can
        enforce an agent-config-only credential flow.
        """
        if api_key is not None:
            return bool(api_key.strip())
        return bool((os.getenv("OLLAMA_API_KEY") or "").strip())

    async def search(
        self,
        query: str,
        max_results: int = 10,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        token = (api_key.strip() if api_key is not None else (os.getenv("OLLAMA_API_KEY") or "").strip())
        if not token:
            return []

        capped = max(1, min(10, int(max_results or 5)))
        url = f"{self.base_url}/api/web_search"
        payload = {"query": query, "max_results": capped}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=40.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            print(f"Ollama web search error (PPT agent): {e}")
            return []

        out: List[Dict[str, Any]] = []
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "title": (item.get("title") or "").strip(),
                    "url": (item.get("url") or "").strip(),
                    "date": (item.get("date") or "").strip(),
                    "snippet": (item.get("content") or item.get("snippet") or "").strip(),
                    "content": (item.get("content") or "").strip(),
                }
            )
        return out

    async def research_topic(
        self,
        topic: str,
        api_key: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run parallel freshness-oriented searches for deck-wide grounding."""
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
        """Parallel searches tuned for one slide's evidence block."""
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


ppt_ollama_free_search = PPTOllamaFreeSearch()
