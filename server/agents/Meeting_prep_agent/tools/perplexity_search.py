import os
import asyncio
import httpx
from urllib.parse import urlparse
from typing import List, Dict, Any, Literal, Optional

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

# Perplexity search_recency_filter: restrict/prioritize results to this window.
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


class MeetingPerplexitySearch:
    """All meeting-prep web facts go through Perplexity **Search** API (`client.search.create`) only."""

    _FIELDS_LOGGED = False

    def __init__(self):
        # Client is built lazily: PERPLEXITY_API_KEY is injected per-request from merged
        # agent config, not necessarily present at import time.
        self.client = None
        self._client_api_key: Optional[str] = None

    @staticmethod
    def _provider() -> str:
        raw = (os.getenv("MEETING_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "free_ollama"
        if raw in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "free_duckduckgo"
        return "perplexity"

    @staticmethod
    def _ollama_api_key() -> str:
        return (
            (os.getenv("OLLAMA_API_KEY") or "").strip()
            or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
            or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
        )

    def is_configured(self) -> bool:
        provider = self._provider()
        if provider == "free_ollama":
            return bool(self._ollama_api_key())
        if provider == "free_duckduckgo":
            return DDGS_AVAILABLE
        if not PERPLEXITY_AVAILABLE:
            return False
        return bool((os.getenv("PERPLEXITY_API_KEY") or "").strip())

    def _ensure_client(self) -> bool:
        if not PERPLEXITY_AVAILABLE:
            return False
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

    def _search_ollama_sync(self, query: str, max_results: int = 8) -> List[Dict[str, Any]]:
        api_key = self._ollama_api_key()
        if not api_key:
            return []

        base_url = (os.getenv("OLLAMA_WEB_SEARCH_BASE_URL") or "https://ollama.com").rstrip("/")
        endpoint = f"{base_url}/api/web_search"
        payload = {"query": query, "max_results": max(1, min(10, int(max_results or 8)))}
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=40.0) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            print(f"  ⚠️ Ollama web search error: {e}")
            return []

        out: List[Dict[str, Any]] = []
        for result in data.get("results") or []:
            if not isinstance(result, dict):
                continue
            out.append({
                "title": (result.get("title") or "").strip(),
                "url": (result.get("url") or "").strip(),
                "date": (result.get("date") or "").strip(),
                "snippet": (result.get("content") or result.get("snippet") or "").strip(),
                "content": (result.get("content") or "").strip(),
            })
        return out

    def _search_duckduckgo_sync(self, query: str, max_results: int = 8) -> List[Dict[str, Any]]:
        if not DDGS_AVAILABLE:
            return []

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max(1, min(10, int(max_results or 8)))))
        except Exception as e:
            print(f"  ⚠️ DuckDuckGo web search error: {e}")
            return []

        out: List[Dict[str, Any]] = []
        for result in results:
            if not isinstance(result, dict):
                continue
            out.append({
                "title": (result.get("title") or "").strip(),
                "url": (result.get("href") or result.get("url") or "").strip(),
                "date": (result.get("date") or "").strip(),
                "snippet": (result.get("body") or result.get("snippet") or "").strip(),
                "content": (result.get("body") or result.get("content") or "").strip(),
            })
        return out

    @staticmethod
    def _extract_field(result: Any, *names: str) -> Optional[str]:
        """SDK versions differ: date vs published_date, snippet vs description, content vs text."""
        for n in names:
            v = getattr(result, n, None)
            if v:
                return v
        return None

    def _search_sync(
        self,
        query: str,
        max_results: int = 8,
        search_recency_filter: Optional[RecencyFilter] = "month",
    ) -> List[Dict[str, Any]]:
        provider = self._provider()
        if provider == "free_ollama":
            return self._search_ollama_sync(query=query, max_results=max_results)
        if provider == "free_duckduckgo":
            return self._search_duckduckgo_sync(query=query, max_results=max_results)

        if not self._ensure_client():
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
                log_cost_event(event_type="perplexity_search", agent_name="Meeting Prep Agent", metadata={"query": query[:100]})
            except Exception:
                pass

            results = []
            for result in search.results:
                if not MeetingPerplexitySearch._FIELDS_LOGGED:
                    MeetingPerplexitySearch._FIELDS_LOGGED = True
                    available = [a for a in dir(result) if not a.startswith('_')]
                    print(f"🔎 Perplexity SearchResult fields: {available}")
                results.append({
                    'title': self._extract_field(result, 'title'),
                    'url': self._extract_field(result, 'url'),
                    'date': self._extract_field(result, 'date', 'published_date', 'publishedDate'),
                    'snippet': self._extract_field(result, 'snippet', 'description'),
                    'content': self._extract_field(result, 'content', 'text'),
                })

            return results

        except Exception as e:
            print(f"  ⚠️ Perplexity search error: {e}")
            return []

    async def _search(
        self,
        query: str,
        max_results: int = 8,
        search_recency_filter: Optional[RecencyFilter] = "month",
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._search_sync, query, max_results, search_recency_filter
        )

    async def search_person(self, person_name: str, role: str, company: str) -> List[Dict[str, Any]]:
        query = f"{person_name} {role} {company} background career profile"
        print(f"  🔍 Searching: Person profile — {person_name}")
        return await self._search(query, max_results=8, search_recency_filter="week")

    async def search_company(self, company: str) -> List[Dict[str, Any]]:
        query = f"{company} company overview recent news earnings strategy"
        print(f"  🏢 Searching: Company profile — {company}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_topic(self, topic: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"{topic} {industry} market trends opportunities".strip()
        print(f"  📖 Searching: Topic research — {topic}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_company_topic(self, company: str, topic: str) -> List[Dict[str, Any]]:
        query = f"{company} {topic} initiatives strategy press releases"
        print(f"  🔗 Searching: {company} + {topic}")
        return await self._search(query, max_results=8, search_recency_filter="week")

    async def search_forecast(self, company: str, topic: str) -> List[Dict[str, Any]]:
        query = f"{company} {topic} guidance growth plans outlook"
        print(f"  📈 Searching: Forecast & growth — {company}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_client_challenges(self, company: str, topic: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"{company} {topic} {industry} challenges risks regulatory".strip()
        print(f"  ⚠️ Searching: Client challenges — {company} + {topic}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_current_status(self, company: str, topic: str) -> List[Dict[str, Any]]:
        query = f"{company} {topic} current progress performance latest"
        print(f"  📍 Searching: Current status — {company} + {topic}")
        return await self._search(query, max_results=8, search_recency_filter="week")

    async def search_current_technology(self, company: str, topic: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"{company} technology stack platforms {topic} {industry}".strip()
        print(f"  💻 Searching: Current technology — {company}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_best_technology(self, topic: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"best technology solutions for {topic} {industry} leading vendors".strip()
        print(f"  🚀 Searching: Best available technology — {topic}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_references(self, topic: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"{topic} {industry} case studies success stories examples".strip()
        print(f"  🌍 Searching: Indian & global references — {topic}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_peer_list(self, company: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"{company} competitors peers {industry}".strip()
        print(f"  🏆 Searching: Peer companies — {company}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_peer_financials(self, company: str, peers_hint: str, industry: str = "") -> List[Dict[str, Any]]:
        query = f"{company} {peers_hint} {industry} revenue profit market cap comparison".strip()
        print(f"  📊 Searching: Peer financial benchmarking — {company}")
        return await self._search(query, max_results=8, search_recency_filter=None)

    async def search_news_cards(self, company_name: str) -> List[Dict[str, Any]]:
        """Latest-news style cards from Perplexity Search API only (no Chat API, no third-party HTML fetches)."""
        query = (
            f"{company_name} latest news articles reports announcements today yesterday this week"
        )
        print(f"  🗞️ Searching: News cards (Search API) — {company_name}")
        results = await self._search(query, max_results=6, search_recency_filter="week")
        cards: List[Dict[str, Any]] = []
        for r in results:
            url = (r.get("url") or "").strip()
            domain = ""
            if url:
                try:
                    domain = urlparse(url).netloc.replace("www.", "")
                except Exception:
                    domain = url.split("/")[2] if len(url.split("/")) > 2 else ""
            snippet = r.get("snippet") or ""
            if not snippet and r.get("content"):
                snippet = (r.get("content") or "")[:200]
            cards.append({
                "title": r.get("title", ""),
                "url": url,
                "date": r.get("date"),
                "snippet": snippet,
                "source": domain,
                "image_url": None,
            })
        return cards


meeting_perplexity_search = MeetingPerplexitySearch()
