import os
import asyncio
import re as _re
from typing import List, Dict, Any, Optional, Literal
import httpx

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

# Perplexity search_recency_filter — narrows/prioritizes the crawl window (SDK literal).
RecencyFilter = Literal["hour", "day", "week", "month", "year"]

try:
    from perplexity import Perplexity
    PERPLEXITY_AVAILABLE = True
except ImportError:
    PERPLEXITY_AVAILABLE = False

import httpx
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")


class CompanyPerplexitySearch:

    def __init__(self):
        # Client is built lazily: PERPLEXITY_API_KEY is injected per-request from merged
        # agent config (see api.apply_user_config), not necessarily present at import time.
        self.client = None
        self._client_api_key: Optional[str] = None

    @staticmethod
    def _provider() -> str:
        raw = (os.getenv("COMPANY_RESEARCH_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
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

    def _search_ollama_sync(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        api_key = self._ollama_api_key()
        if not api_key:
            return []

        base_url = (os.getenv("OLLAMA_WEB_SEARCH_BASE_URL") or "https://ollama.com").rstrip("/")
        endpoint = f"{base_url}/api/web_search"
        payload = {"query": query, "max_results": max(1, min(10, int(max_results or 10)))}
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
            print(f"Ollama web search error: {e}")
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

    def _search_duckduckgo_sync(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        if not DDGS_AVAILABLE:
            return []

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max(1, min(10, int(max_results or 10)))))
        except Exception as e:
            print(f"DuckDuckGo web search error: {e}")
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

    _FIELDS_LOGGED = False

    @staticmethod
    def _extract_field(result: Any, *names: str) -> Optional[str]:
        """SDK versions differ: date vs published_date, snippet vs description vs text, content vs text."""
        for n in names:
            v = getattr(result, n, None)
            if v:
                return v
        return None

    def _search_sync(
        self,
        query: str,
        max_results: int = 10,
        search_recency_filter: Optional[RecencyFilter] = None,
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
                log_cost_event(event_type="perplexity_search", agent_name="Company Research Agent", metadata={"query": query[:100]})
            except Exception:
                pass

            results = []
            for result in search.results:
                if not CompanyPerplexitySearch._FIELDS_LOGGED:
                    CompanyPerplexitySearch._FIELDS_LOGGED = True
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
            print(f"Perplexity search error: {e}")
            return []

    async def _search(
        self,
        query: str,
        max_results: int = 10,
        search_recency_filter: Optional[RecencyFilter] = None,
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._search_sync, query, max_results, search_recency_filter
        )

    async def search_company_overview(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} company profile business overview products services headquarters"
        print(f"  🔍 Searching: Company overview for {company_name}")
        return await self._search(query, max_results=5, search_recency_filter="month")

    async def search_financials(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} latest quarterly results revenue net profit EBITDA margin EPS"
        print(f"  📊 Searching: Quarterly financials for {company_name}")
        results = await self._search(query, max_results=8, search_recency_filter=None)
        query2 = f"{company_name} annual report FY revenue net profit total assets market cap"
        print(f"  📊 Searching: Annual financials for {company_name}")
        results2 = await self._search(query2, max_results=8, search_recency_filter=None)
        return results + results2

    async def search_balance_sheet(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} balance sheet total assets liabilities equity debt cash latest quarter"
        print(f"  📋 Searching: Balance sheet for {company_name}")
        return await self._search(query, max_results=5, search_recency_filter=None)

    async def search_focus_areas(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} strategy growth priorities CEO announcements"
        print(f"  🎯 Searching: Focus areas and leadership for {company_name}")
        return await self._search(query, max_results=8, search_recency_filter="month")

    async def search_relevant_news(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} partnerships acquisitions regulatory news"
        print(f"  📰 Searching: Relevant news for {company_name}")
        return await self._search(query, max_results=6, search_recency_filter="week")

    async def search_latest_news(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} latest news announcements"
        print(f"  📢 Searching: Latest news for {company_name}")
        return await self._search(query, max_results=8, search_recency_filter="week")

    _OG_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    @staticmethod
    async def _fetch_og_image(url: str) -> Optional[str]:
        if not url:
            return None
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(url, headers=CompanyPerplexitySearch._OG_HEADERS)
                if resp.status_code != 200:
                    return None
                html = resp.text[:80000]
                for pattern in [
                    r'<meta\s+property=["\']og:image["\']\s+content=["\'](https?://[^"\']+)["\']',
                    r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+property=["\']og:image["\']',
                    r'<meta\s+name=["\']twitter:image["\']\s+content=["\'](https?://[^"\']+)["\']',
                    r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+name=["\']twitter:image["\']',
                    r'<meta\s+name=["\']twitter:image:src["\']\s+content=["\'](https?://[^"\']+)["\']',
                    r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+name=["\']twitter:image:src["\']',
                    r'<link\s+rel=["\']image_src["\']\s+href=["\'](https?://[^"\']+)["\']',
                ]:
                    m = _re.search(pattern, html, _re.IGNORECASE)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return None

    async def search_financial_snapshot(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} market cap revenue net profit debt equity ratio"
        print(f"  💰 Searching: Financial snapshot KPIs for {company_name}")
        return await self._search(query, max_results=8, search_recency_filter="week")

    async def search_news_cards(self, company_name: str) -> List[Dict[str, Any]]:
        query = f"{company_name} latest news"
        print(f"  🗞️ Searching: News cards for {company_name}")
        results = await self._search(query, max_results=6, search_recency_filter="week")

        urls = [r.get('url', '') for r in results]
        og_images = await asyncio.gather(*[self._fetch_og_image(u) for u in urls], return_exceptions=True)

        cards = []
        for i, r in enumerate(results):
            url = r.get('url', '')
            domain = ''
            if url:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(url)
                    domain = parsed.netloc.replace('www.', '')
                except Exception:
                    domain = url.split('/')[2] if len(url.split('/')) > 2 else ''

            og_img = og_images[i] if i < len(og_images) and isinstance(og_images[i], str) else None

            cards.append({
                'title': r.get('title', ''),
                'url': url,
                'date': r.get('date', None),
                'snippet': r.get('snippet', '') or r.get('content', '')[:200] if r.get('content') else '',
                'source': domain,
                'image_url': og_img,
            })
            print(f"    📷 Card {i+1}: {'OG image found' if og_img else 'No image'} - {r.get('title', '')[:50]}")
        return cards


company_perplexity_search = CompanyPerplexitySearch()
