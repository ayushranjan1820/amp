import os
import re
import asyncio
import httpx
from typing import List, Dict, Any, Optional
from pathlib import Path
from urllib.parse import urlparse

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent.parent / ".env")

try:
    from agents.source_citation_mandate import WEB_SEARCH_CITATION_APPEND
except ImportError:  # pragma: no cover
    WEB_SEARCH_CITATION_APPEND = (
        " MANDATORY: Cite every external fact with [label](https://...)."
    )

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

SEARCH_FOCUS_MODELS = {
    "general": "sonar",
    "news": "sonar",
    "academic": "sonar",
    "writing": "sonar",
    "math": "sonar",
    "deep_research": "sonar-deep-research",
}

FOCUS_SYSTEM_PROMPTS = {
    "general": "You are a helpful search assistant. Provide comprehensive, well-structured answers with relevant details. Always cite your sources.",
    "news": "You are a news research assistant. Focus on the latest news, breaking stories, and recent developments. Prioritize recency and provide dates for all information. Always cite your sources.",
    "academic": "You are an academic research assistant. Provide scholarly, evidence-based answers with emphasis on peer-reviewed sources, research papers, and authoritative publications. Include methodology details when relevant. Always cite your sources.",
    "writing": "You are a writing assistant powered by web search. Help the user with writing tasks by finding relevant information, examples, and references. Provide well-structured content that can be used as reference material. Always cite your sources.",
    "math": "You are a math and science assistant. Provide precise, step-by-step explanations with formulas and calculations. Reference authoritative mathematical and scientific sources. Always cite your sources.",
    "deep_research": "You are a deep research assistant. Conduct thorough, multi-faceted research on the topic. Provide comprehensive analysis with multiple perspectives, detailed evidence, and extensive source citations.",
}


class PerplexityClient:

    def __init__(self):
        self.api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
        self.ollama_api_key = (
            (os.getenv("OLLAMA_API_KEY") or "").strip()
            or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
            or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
        )
        prov = self.current_provider()
        if self.is_configured():
            if prov == "free_ollama":
                print("🔍 Web Search Agent - Ollama free web search configured")
            elif prov == "free_duckduckgo":
                print("🔍 Web Search Agent - DuckDuckGo free web search configured")
            else:
                print("🔍 Web Search Agent - Perplexity API configured")
        else:
            print("⚠️ Web Search Agent - search provider credentials not set")

    @staticmethod
    def _provider() -> str:
        raw = (os.getenv("WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "free_ollama"
        if raw in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "free_duckduckgo"
        return "perplexity"

    def current_provider(self) -> str:
        return self._provider()

    def is_configured(self) -> bool:
        prov = self._provider()
        if prov == "free_ollama":
            return bool(
                (os.getenv("OLLAMA_API_KEY") or "").strip()
                or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
                or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
            )
        if prov == "free_duckduckgo":
            return DDGS_AVAILABLE
        return bool((os.getenv("PERPLEXITY_API_KEY") or "").strip())

    async def _search_duckduckgo(
        self,
        query: str,
        max_results: int = 8,
    ) -> Dict[str, Any]:
        if not DDGS_AVAILABLE:
            return {
                "answer": "DuckDuckGo search backend is not available. Please install the ddgs package.",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

        def _run() -> List[Dict[str, Any]]:
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max(1, min(10, int(max_results or 8)))))

        try:
            results = await asyncio.to_thread(_run)
            citations: List[Dict[str, Any]] = []
            answer_lines: List[str] = []

            for i, item in enumerate(results[:10], 1):
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "Untitled").strip()
                url = (item.get("href") or item.get("url") or "").strip()
                content = (item.get("body") or item.get("snippet") or "").strip()
                citations.append({"title": title, "url": url, "snippet": content[:240]})
                answer_lines.append(f"{i}. {title}\n{content[:600]}\nSource: {url}")

            answer = (
                "\n\n".join(answer_lines)
                if answer_lines
                else "No web search results were returned for this query."
            )

            return {
                "answer": answer,
                "citations": citations,
                "images": [],
                "related_questions": [],
                "model": "duckduckgo-web-search",
                "usage": {},
            }
        except Exception as e:
            print(f"DuckDuckGo web search error: {e}")
            return {
                "answer": f"Search failed: {str(e)}",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

    async def _search_ollama(
        self,
        query: str,
        max_results: int = 8,
    ) -> Dict[str, Any]:
        api_key = (
            (os.getenv("OLLAMA_API_KEY") or "").strip()
            or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
            or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
        )
        if not api_key:
            return {
                "answer": "Ollama API key is not configured. Please set OLLAMA_API_KEY.",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

        base_url = (os.getenv("OLLAMA_WEB_SEARCH_BASE_URL") or "https://ollama.com").rstrip("/")
        endpoint = f"{base_url}/api/web_search"
        payload = {
            "query": query,
            "max_results": max(1, min(10, int(max_results or 8))),
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()

            results = data.get("results") or []
            citations: List[Dict[str, Any]] = []
            answer_lines: List[str] = []

            for i, item in enumerate(results[:10], 1):
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "Untitled").strip()
                url = (item.get("url") or "").strip()
                content = (item.get("content") or item.get("snippet") or "").strip()
                citations.append({"title": title, "url": url, "snippet": content[:240]})
                answer_lines.append(f"{i}. {title}\n{content[:600]}\nSource: {url}")

            answer = (
                "\n\n".join(answer_lines)
                if answer_lines
                else "No web search results were returned for this query."
            )

            return {
                "answer": answer,
                "citations": citations,
                "images": [],
                "related_questions": [],
                "model": "ollama-web-search",
                "usage": {},
            }
        except httpx.HTTPStatusError as e:
            print(f"Ollama web search HTTP error: {e.response.status_code} - {e.response.text}")
            return {
                "answer": f"Search failed with HTTP error {e.response.status_code}. Please try again.",
                "citations": [],
                "images": [],
                "related_questions": [],
            }
        except Exception as e:
            print(f"Ollama web search error: {e}")
            return {
                "answer": f"Search failed: {str(e)}",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

    async def search(
        self,
        query: str,
        search_focus: str = "general",
        search_recency_filter: Optional[str] = None,
        return_images: bool = True,
        return_related_questions: bool = True,
    ) -> Dict[str, Any]:
        provider = self._provider()
        if provider == "free_ollama":
            return await self._search_ollama(query=query, max_results=8)
        if provider == "free_duckduckgo":
            return await self._search_duckduckgo(query=query, max_results=8)

        self.api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
        if not self.api_key:
            return {
                "answer": "Perplexity API key is not configured. Please set the PERPLEXITY_API_KEY environment variable.",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

        model = SEARCH_FOCUS_MODELS.get(search_focus, "sonar")
        system_prompt = FOCUS_SYSTEM_PROMPTS.get(search_focus, FOCUS_SYSTEM_PROMPTS["general"]) + WEB_SEARCH_CITATION_APPEND

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query},
            ],
            "return_citations": True,
            "return_images": return_images,
            "return_related_questions": return_related_questions,
        }

        if search_recency_filter and search_focus == "news":
            payload["search_recency_filter"] = search_recency_filter

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    PERPLEXITY_API_URL,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            answer = ""
            if data.get("choices"):
                answer = data["choices"][0].get("message", {}).get("content", "")

            citations = data.get("citations", [])
            images = data.get("images", [])
            related = data.get("related_questions", [])
            usage = data.get("usage", {})

            try:
                from langfuse_tracer import trace_llm_call
                trace_llm_call(
                    model=model,
                    prompt=query,
                    completion=answer,
                    prompt_tokens=usage.get("prompt_tokens") or 0,
                    completion_tokens=usage.get("completion_tokens") or 0,
                    latency_ms=0,
                    agent_name="Web Search Agent",
                    extra_metadata={"path": "perplexity/search", "focus": search_focus},
                )
            except Exception:
                pass

            return {
                "answer": answer,
                "citations": citations if isinstance(citations, list) else [],
                "images": images if isinstance(images, list) else [],
                "related_questions": related if isinstance(related, list) else [],
                "model": model,
                "usage": usage,
            }

        except httpx.HTTPStatusError as e:
            print(f"Perplexity API HTTP error: {e.response.status_code} - {e.response.text}")
            return {
                "answer": f"Search failed with HTTP error {e.response.status_code}. Please try again.",
                "citations": [],
                "images": [],
                "related_questions": [],
            }
        except Exception as e:
            print(f"Perplexity search error: {e}")
            return {
                "answer": f"Search failed: {str(e)}",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

    async def search_with_context(
        self,
        query: str,
        conversation_history: List[Dict[str, str]],
        search_focus: str = "general",
    ) -> Dict[str, Any]:
        provider = self._provider()
        if provider == "free_ollama":
            # Ollama web search is stateless; ignore conversation history.
            return await self._search_ollama(query=query, max_results=8)
        if provider == "free_duckduckgo":
            # DuckDuckGo web search is stateless; ignore conversation history.
            return await self._search_duckduckgo(query=query, max_results=8)

        self.api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
        if not self.api_key:
            return {
                "answer": "Perplexity API key is not configured.",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

        model = SEARCH_FOCUS_MODELS.get(search_focus, "sonar")
        system_prompt = FOCUS_SYSTEM_PROMPTS.get(search_focus, FOCUS_SYSTEM_PROMPTS["general"]) + WEB_SEARCH_CITATION_APPEND

        messages = [{"role": "system", "content": system_prompt}]
        for msg in conversation_history[-6:]:
            messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
        messages.append({"role": "user", "content": query})

        payload = {
            "model": model,
            "messages": messages,
            "return_citations": True,
            "return_images": True,
            "return_related_questions": True,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    PERPLEXITY_API_URL,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            answer = ""
            if data.get("choices"):
                answer = data["choices"][0].get("message", {}).get("content", "")

            usage = data.get("usage", {})

            try:
                from langfuse_tracer import trace_llm_call
                trace_llm_call(
                    model=model,
                    prompt=query,
                    completion=answer,
                    prompt_tokens=usage.get("prompt_tokens") or 0,
                    completion_tokens=usage.get("completion_tokens") or 0,
                    latency_ms=0,
                    agent_name="Web Search Agent",
                    extra_metadata={"path": "perplexity/search_with_context", "focus": search_focus},
                )
            except Exception:
                pass

            return {
                "answer": answer,
                "citations": data.get("citations", []),
                "images": data.get("images", []),
                "related_questions": data.get("related_questions", []),
                "model": model,
                "usage": usage,
            }

        except Exception as e:
            print(f"Perplexity contextual search error: {e}")
            return {
                "answer": f"Search failed: {str(e)}",
                "citations": [],
                "images": [],
                "related_questions": [],
            }

    _OG_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml",
    }

    @staticmethod
    def _is_safe_url(url: str) -> bool:
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            hostname = parsed.hostname or ""
            if not hostname:
                return False
            import ipaddress
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    return False
            except ValueError:
                blocked = ("localhost", "127.0.0.1", "0.0.0.0", "metadata.google", "169.254.")
                if any(hostname.startswith(b) or hostname == b for b in blocked):
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    async def fetch_og_image(url: str) -> Optional[str]:
        if not url or not PerplexityClient._is_safe_url(url):
            return None
        try:
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, max_redirects=3) as client:
                resp = await client.get(url, headers=PerplexityClient._OG_HEADERS)
                if resp.status_code != 200:
                    return None
                html = resp.text[:60000]
                for pattern in [
                    r'<meta\s+property=["\']og:image["\']\s+content=["\'](https?://[^"\']+)["\']',
                    r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+property=["\']og:image["\']',
                    r'<meta\s+name=["\']twitter:image["\']\s+content=["\'](https?://[^"\']+)["\']',
                    r'<meta\s+content=["\'](https?://[^"\']+)["\']\s+name=["\']twitter:image["\']',
                ]:
                    m = re.search(pattern, html, re.IGNORECASE)
                    if m:
                        return m.group(1)
        except Exception:
            pass
        return None

    @staticmethod
    def extract_domain(url: str) -> str:
        try:
            parsed = urlparse(url)
            return parsed.netloc.replace("www.", "")
        except Exception:
            return url


perplexity_client = PerplexityClient()
