from typing import List, Dict, Any
import os
import httpx

PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"

try:
    from ddgs import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False


def _canonical_provider(raw: str) -> str:
    v = (raw or "").strip().lower()
    if v in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
        return "free_ollama"
    if v in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
        return "free_duckduckgo"
    return "perplexity"


def _selected_provider() -> str:
    # Agent-specific override first; then shared web-search provider as fallback.
    raw = (
        os.getenv("MARKET_RESEARCH_WEB_SEARCH_PROVIDER")
        or os.getenv("WEB_SEARCH_PROVIDER")
        or "perplexity"
    )
    return _canonical_provider(raw)


def get_search_provider_label() -> str:
    provider = _selected_provider()
    if provider == "free_ollama":
        return "Ollama free web search"
    if provider == "free_duckduckgo":
        return "DuckDuckGo web search"
    return "Perplexity web search"


def _format_results_from_items(items: List[Dict[str, Any]], max_results: int) -> List[Dict]:
    formatted_results = []
    for result in items[:max_results]:
        formatted_results.append({
            "title": result.get("title", ""),
            "url": result.get("url", ""),
            "snippet": result.get("snippet", ""),
            "published_date": result.get("published_date"),
        })
    return formatted_results


def _search_perplexity(query: str, max_results: int) -> List[Dict]:
    api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
    if not api_key:
        print("Market Research web search: PERPLEXITY_API_KEY is not configured")
        return []

    payload = {
        "model": os.getenv("MARKET_RESEARCH_PERPLEXITY_MODEL", "sonar"),
        "messages": [
            {
                "role": "system",
                "content": "You are a market research assistant. Return factual, source-backed results.",
            },
            {"role": "user", "content": query},
        ],
        "return_citations": True,
        "return_images": False,
        "return_related_questions": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(PERPLEXITY_API_URL, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        citations = data.get("citations", []) if isinstance(data, dict) else []
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for c in citations:
            if isinstance(c, str):
                url = c.strip()
                title = url
                snippet = ""
            elif isinstance(c, dict):
                url = str(c.get("url") or "").strip()
                title = str(c.get("title") or url).strip()
                snippet = str(c.get("snippet") or "").strip()
            else:
                continue

            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "published_date": None,
            })

        return _format_results_from_items(normalized, max_results=max_results)
    except Exception as e:
        print(f"Perplexity market web search error: {e}")
        return []


def _search_ollama_web(query: str, max_results: int) -> List[Dict]:
    api_key = (
        (os.getenv("OLLAMA_API_KEY") or "").strip()
        or (os.getenv("ON_PREM_CLOUD_ACCESS_TOKEN") or "").strip()
        or (os.getenv("OLLAMA_CLOUD_BEARER_TOKEN") or "").strip()
    )
    if not api_key:
        print("Market Research web search: OLLAMA_API_KEY is not configured")
        return []

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
        with httpx.Client(timeout=45.0) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = data.get("results") if isinstance(data, dict) else []
        if not isinstance(results, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            normalized.append({
                "title": str(item.get("title") or "Untitled").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(item.get("content") or item.get("snippet") or "").strip(),
                "published_date": None,
            })

        return _format_results_from_items(normalized, max_results=max_results)
    except Exception as e:
        print(f"Ollama market web search error: {e}")
        return []


def _search_duckduckgo(query: str, max_results: int) -> List[Dict]:
    if not DDGS_AVAILABLE:
        print("Market Research web search: ddgs package is not installed")
        return []

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        normalized: List[Dict[str, Any]] = []
        for result in results:
            normalized.append({
                "title": result.get("title", ""),
                "url": result.get("href", result.get("link", "")),
                "snippet": result.get("body", result.get("snippet", "")),
                "published_date": None,
            })
        return _format_results_from_items(normalized, max_results=max_results)
    except Exception as e:
        print(f"DuckDuckGo market web search error: {e}")
        return []

def search_web(query: str, max_results: int = 10) -> List[Dict]:
    """
    Search the web for information using the configured provider.
    Providers: Perplexity, Ollama free web, DuckDuckGo fallback.
    """
    try:
        try:
            from cost_tracker import log_cost_event
            log_cost_event(event_type="web_search", agent_name="Market Research Agent", metadata={"query": query})
        except Exception:
            pass
        provider = _selected_provider()
        if provider == "free_ollama":
            results = _search_ollama_web(query, max_results=max_results)
            if results:
                return results
            # Graceful fallback when Ollama key is missing/unreachable.
            return _search_duckduckgo(query, max_results=max_results)

        if provider == "free_duckduckgo":
            return _search_duckduckgo(query, max_results=max_results)

        # Default: Perplexity, with fallback to DuckDuckGo if unavailable.
        results = _search_perplexity(query, max_results=max_results)
        if results:
            return results
        return _search_duckduckgo(query, max_results=max_results)
    except Exception as e:
        print(f"Web search error: {e}")
        return []

def fetch_page_content(url: str, max_chars: int = 5000) -> str:
    """
    Fetch and extract text content from a webpage.
    Handles SSL certificate issues and 403 errors with enhanced strategies.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1"
    }
    
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, verify=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'lxml')
            
            for script in soup(["script", "style", "nav", "footer", "header"]):
                script.decompose()
            
            text = soup.get_text(separator=' ', strip=True)
            return text[:max_chars]
            
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            print(f"Access denied (403) for {url} - Site may require authentication or block scrapers")
        else:
            print(f"HTTP error {e.response.status_code} fetching {url}")
        return ""
        
    except Exception as e:
        error_msg = str(e)
        
        if "CERTIFICATE_VERIFY_FAILED" in error_msg or "SSL" in error_msg:
            print(f"SSL verification failed for {url}, retrying without verification...")
            try:
                with httpx.Client(timeout=10.0, follow_redirects=True, verify=False) as client:
                    response = client.get(url, headers=headers)
                    response.raise_for_status()
                    
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.text, 'lxml')
                    
                    for script in soup(["script", "style", "nav", "footer", "header"]):
                        script.decompose()
                    
                    text = soup.get_text(separator=' ', strip=True)
                    print(f"Successfully fetched {url} (SSL verification disabled)")
                    return text[:max_chars]
                    
            except Exception as retry_error:
                print(f"Error fetching {url} (retry failed): {retry_error}")
                return ""
        else:
            print(f"Error fetching {url}: {e}")
            return ""
