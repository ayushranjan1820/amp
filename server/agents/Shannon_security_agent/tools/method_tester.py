import httpx
import time
from typing import Dict, Any, List
from urllib.parse import urljoin

from .web_context import validate_url, _check_redirect


DANGEROUS_METHODS = ["PUT", "DELETE", "PATCH", "TRACE"]
INFO_METHODS = ["OPTIONS"]


def test_http_methods(
    base_url: str,
    endpoints: List[str] = None,
    time_budget: float = 20.0,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    result = {
        "findings": [],
        "endpoints_tested": [],
        "stats": {
            "endpoints_tested": 0,
            "methods_tested": 0,
            "time_elapsed": 0,
        },
        "errors": [],
    }

    if not validate_url(base_url):
        result["errors"].append(f"URL validation failed: {base_url}")
        return result

    default_paths = ["/", "/api/", "/api/v1/"]
    test_endpoints = list(set((endpoints or []) + default_paths))[:20]

    start_time = time.time()

    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            event_hooks={"response": [_check_redirect]},
            headers={"User-Agent": "Mozilla/5.0 (compatible; SecurityAssessment/1.0)"},
        ) as client:
            for path in test_endpoints:
                elapsed = time.time() - start_time
                if elapsed > time_budget:
                    result["errors"].append(f"Time budget exceeded ({time_budget}s)")
                    break

                full_url = urljoin(base_url, path)
                if not validate_url(full_url):
                    continue

                endpoint_result = {
                    "url": full_url,
                    "path": path,
                    "allowed_methods": [],
                    "dangerous_methods_allowed": [],
                    "trace_enabled": False,
                    "cors_preflight": None,
                }

                try:
                    resp = client.request("OPTIONS", full_url)
                    result["stats"]["methods_tested"] += 1

                    allow_header = resp.headers.get("allow", "")
                    if allow_header:
                        methods = [m.strip().upper() for m in allow_header.split(",")]
                        endpoint_result["allowed_methods"] = methods

                        for m in DANGEROUS_METHODS:
                            if m in methods:
                                endpoint_result["dangerous_methods_allowed"].append(m)

                    cors_methods = resp.headers.get("access-control-allow-methods", "")
                    if cors_methods:
                        endpoint_result["cors_preflight"] = cors_methods
                except Exception:
                    pass

                try:
                    resp = client.request("TRACE", full_url)
                    result["stats"]["methods_tested"] += 1
                    if resp.status_code == 200 and "TRACE" in resp.text.upper()[:500]:
                        endpoint_result["trace_enabled"] = True
                except Exception:
                    pass

                for method in ["PUT", "DELETE"]:
                    elapsed = time.time() - start_time
                    if elapsed > time_budget:
                        break
                    try:
                        resp = client.request(method, full_url)
                        result["stats"]["methods_tested"] += 1
                        if resp.status_code not in (405, 501, 404, 403, 401):
                            if method not in endpoint_result["dangerous_methods_allowed"]:
                                endpoint_result["dangerous_methods_allowed"].append(method)
                    except Exception:
                        continue

                result["endpoints_tested"].append(endpoint_result)
                result["stats"]["endpoints_tested"] += 1

                if endpoint_result["dangerous_methods_allowed"]:
                    result["findings"].append({
                        "title": f"Dangerous HTTP Methods Allowed on {path}",
                        "severity": "Medium",
                        "owasp_category": "A05:2021 — Security Misconfiguration",
                        "location": full_url,
                        "description": f"The endpoint '{path}' accepts HTTP methods that could allow data modification or deletion: {', '.join(endpoint_result['dangerous_methods_allowed'])}.",
                        "evidence": f"HTTP {', '.join(endpoint_result['dangerous_methods_allowed'])} requests to {full_url} returned non-error status codes. "
                                    f"Allow header: '{allow_header or 'not set'}'.",
                        "recommendation": "Restrict HTTP methods to only those required (typically GET and POST). Disable PUT, DELETE, TRACE, and PATCH unless explicitly needed.",
                    })

                if endpoint_result["trace_enabled"]:
                    result["findings"].append({
                        "title": f"HTTP TRACE Method Enabled on {path}",
                        "severity": "Medium",
                        "owasp_category": "A05:2021 — Security Misconfiguration",
                        "location": full_url,
                        "description": "The TRACE method is enabled, which can be used in Cross-Site Tracing (XST) attacks to steal credentials.",
                        "evidence": f"HTTP TRACE request to {full_url} returned 200 with the request echoed in the response body.",
                        "recommendation": "Disable the TRACE HTTP method on the web server.",
                    })

    except Exception as e:
        result["errors"].append(f"Method tester error: {str(e)[:200]}")

    result["stats"]["time_elapsed"] = round(time.time() - start_time, 2)
    return result
