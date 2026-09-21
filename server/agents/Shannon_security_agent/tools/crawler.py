import httpx
import time
from typing import Dict, Any, List, Set, Optional
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup
from collections import deque

from .web_context import validate_url, SSRF_BLOCKED, _check_redirect


DEFAULT_MAX_PAGES = 30
DEFAULT_MAX_DEPTH = 3
DEFAULT_TIME_BUDGET = 30
DEFAULT_TIMEOUT = 10


def _normalize_url(url: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _is_same_origin(base_url: str, target_url: str) -> bool:
    base = urlparse(base_url)
    target = urlparse(target_url)
    return base.netloc == target.netloc


def _is_crawlable(url: str) -> bool:
    parsed = urlparse(url)
    skip_ext = {
        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp', '.bmp',
        '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
        '.pdf', '.zip', '.gz', '.tar', '.rar', '.7z',
        '.mp3', '.mp4', '.avi', '.mov', '.wmv', '.flv',
        '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    }
    path_lower = parsed.path.lower()
    return not any(path_lower.endswith(ext) for ext in skip_ext)


def crawl_site(
    start_url: str,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    time_budget: float = DEFAULT_TIME_BUDGET,
    timeout: float = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    result = {
        "pages_crawled": [],
        "all_urls": [],
        "forms_found": [],
        "api_endpoints": [],
        "technologies": set(),
        "cookies_collected": [],
        "errors": [],
        "stats": {
            "pages_crawled": 0,
            "total_urls_found": 0,
            "time_elapsed": 0,
            "max_depth_reached": 0,
        },
    }

    if not validate_url(start_url):
        result["errors"].append(f"URL validation failed: {start_url}")
        return result

    visited: Set[str] = set()
    queue: deque = deque()
    queue.append((start_url, 0))
    visited.add(_normalize_url(start_url))
    start_time = time.time()

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            event_hooks={"response": [_check_redirect]},
            headers={"User-Agent": "Mozilla/5.0 (compatible; SecurityAssessment/1.0)"},
        ) as client:
            while queue and len(result["pages_crawled"]) < max_pages:
                elapsed = time.time() - start_time
                if elapsed > time_budget:
                    result["errors"].append(f"Time budget exceeded ({time_budget}s)")
                    break

                url, depth = queue.popleft()

                if depth > max_depth:
                    continue

                try:
                    resp = client.get(url)
                except Exception as e:
                    result["errors"].append(f"Failed to fetch {url}: {str(e)[:100]}")
                    continue

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    continue

                page_data = {
                    "url": str(resp.url),
                    "status_code": resp.status_code,
                    "depth": depth,
                    "headers": dict(resp.headers),
                    "security_headers_present": [],
                    "security_headers_missing": [],
                }

                important_headers = [
                    "content-security-policy", "x-content-type-options",
                    "x-frame-options", "strict-transport-security",
                    "referrer-policy", "permissions-policy",
                ]
                for h in important_headers:
                    if resp.headers.get(h):
                        page_data["security_headers_present"].append(h)
                    else:
                        page_data["security_headers_missing"].append(h)

                result["pages_crawled"].append(page_data)
                result["stats"]["max_depth_reached"] = max(result["stats"]["max_depth_reached"], depth)

                for cookie in resp.cookies.jar:
                    cookie_data = {
                        "name": cookie.name,
                        "domain": cookie.domain,
                        "path": cookie.path,
                        "secure": cookie.secure,
                        "httponly": "httponly" in str(cookie).lower(),
                        "found_on": str(resp.url),
                    }
                    if not any(c["name"] == cookie.name and c["domain"] == cookie.domain for c in result["cookies_collected"]):
                        result["cookies_collected"].append(cookie_data)

                html = resp.text
                soup = BeautifulSoup(html, "html.parser")

                for form in soup.find_all("form"):
                    form_data = {
                        "page_url": str(resp.url),
                        "action": form.get("action", ""),
                        "method": form.get("method", "GET").upper(),
                        "inputs": [],
                        "has_csrf_token": False,
                    }
                    action_url = urljoin(str(resp.url), form_data["action"]) if form_data["action"] else str(resp.url)
                    form_data["action_url"] = action_url

                    for inp in form.find_all(["input", "textarea", "select"]):
                        inp_data = {
                            "name": inp.get("name", ""),
                            "type": inp.get("type", "text"),
                            "id": inp.get("id", ""),
                            "value": inp.get("value", ""),
                        }
                        form_data["inputs"].append(inp_data)
                        name_lower = (inp.get("name") or "").lower()
                        if any(tok in name_lower for tok in ["csrf", "token", "_token", "authenticity"]):
                            form_data["has_csrf_token"] = True

                    result["forms_found"].append(form_data)

                import re
                for script in soup.find_all("script"):
                    src = script.get("src", "")
                    if not src:
                        inline = script.string or ""
                        api_patterns = re.findall(r'["\'](/api/[^"\']+)["\']', inline)
                        result["api_endpoints"].extend(api_patterns)
                        fetch_patterns = re.findall(r'fetch\s*\(\s*["\']([^"\']+)["\']', inline)
                        result["api_endpoints"].extend(fetch_patterns)

                server = resp.headers.get("server", "")
                powered = resp.headers.get("x-powered-by", "")
                if server:
                    result["technologies"].add(f"Server: {server}")
                if powered:
                    result["technologies"].add(f"Powered-By: {powered}")

                if depth < max_depth:
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        full_url = urljoin(str(resp.url), href)
                        normalized = _normalize_url(full_url)

                        if (
                            normalized not in visited
                            and _is_same_origin(start_url, full_url)
                            and _is_crawlable(full_url)
                            and validate_url(full_url)
                        ):
                            visited.add(normalized)
                            queue.append((full_url, depth + 1))

    except Exception as e:
        result["errors"].append(f"Crawler error: {str(e)[:200]}")

    result["all_urls"] = list(visited)
    result["api_endpoints"] = list(set(result["api_endpoints"]))
    result["technologies"] = list(result["technologies"])
    result["stats"]["pages_crawled"] = len(result["pages_crawled"])
    result["stats"]["total_urls_found"] = len(visited)
    result["stats"]["time_elapsed"] = round(time.time() - start_time, 2)

    return result
