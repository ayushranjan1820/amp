import httpx
import re
import html
import time
from typing import Dict, Any, List
from urllib.parse import urljoin, urlparse

from .web_context import validate_url, _check_redirect


XSS_PAYLOADS = [
    {
        "name": "script_tag",
        "payload": "<script>alert('XSS-TEST-7291')</script>",
        "detect": r"<script>alert\('XSS-TEST-7291'\)</script>",
        "description": "Basic script injection — tests if HTML tags are rendered unescaped",
    },
    {
        "name": "img_onerror",
        "payload": '<img src=x onerror="alert(1)">',
        "detect": r'<img\s+src=x\s+onerror="alert\(1\)"',
        "description": "Event handler injection — tests if HTML attributes are rendered unescaped",
    },
    {
        "name": "svg_onload",
        "payload": '<svg onload="alert(1)">',
        "detect": r'<svg\s+onload="alert\(1\)"',
        "description": "SVG event handler injection",
    },
    {
        "name": "angle_brackets",
        "payload": '"><test-xss-tag>',
        "detect": r"<test-xss-tag>",
        "description": "Attribute breakout — tests if angle brackets are sanitized",
    },
    {
        "name": "javascript_uri",
        "payload": "javascript:alert('XSS')",
        "detect": r"javascript:alert\('XSS'\)",
        "description": "JavaScript URI injection",
    },
]

SQLI_PAYLOADS = [
    {
        "name": "single_quote",
        "payload": "'",
        "error_patterns": [
            r"SQL syntax",
            r"mysql_fetch",
            r"Warning.*mysql",
            r"MySQLSyntaxErrorException",
            r"valid MySQL result",
            r"check the manual that corresponds to your (MySQL|MariaDB)",
        ],
        "description": "Single quote — tests for unescaped SQL string termination",
    },
    {
        "name": "double_quote",
        "payload": '"',
        "error_patterns": [
            r"SQL syntax",
            r"Unclosed quotation mark",
        ],
        "description": "Double quote — tests for SQL string handling",
    },
    {
        "name": "or_tautology",
        "payload": "' OR '1'='1",
        "error_patterns": [
            r"SQL syntax",
            r"ORA-\d{5}",
            r"PostgreSQL.*ERROR",
            r"pg_query",
            r"pg_exec",
            r"unterminated quoted string",
        ],
        "description": "OR tautology — tests for SQL injection in WHERE clauses",
    },
    {
        "name": "union_select",
        "payload": "' UNION SELECT NULL--",
        "error_patterns": [
            r"SQL syntax",
            r"UNION",
            r"column.*different",
            r"SELECTs.*different number",
        ],
        "description": "UNION SELECT — tests for UNION-based SQL injection",
    },
    {
        "name": "comment_injection",
        "payload": "1; --",
        "error_patterns": [
            r"SQL syntax",
            r"sqlite3\.OperationalError",
            r"SQLite.*error",
            r"SQLSTATE",
            r"PDOException",
        ],
        "description": "Comment injection — tests for statement termination",
    },
]


def test_form_injections(
    forms: List[Dict[str, Any]],
    base_url: str,
    time_budget: float = 30.0,
    timeout: float = 8.0,
) -> Dict[str, Any]:
    result = {
        "xss_findings": [],
        "sqli_findings": [],
        "forms_tested": 0,
        "payloads_sent": 0,
        "stats": {
            "time_elapsed": 0,
        },
        "errors": [],
    }

    if not forms:
        return result

    start_time = time.time()

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            event_hooks={"response": [_check_redirect]},
            headers={"User-Agent": "Mozilla/5.0 (compatible; SecurityAssessment/1.0)"},
        ) as client:
            for form in forms:
                elapsed = time.time() - start_time
                if elapsed > time_budget:
                    result["errors"].append(f"Time budget exceeded ({time_budget}s)")
                    break

                action_url = form.get("action_url", "")
                if not action_url:
                    action = form.get("action", "")
                    action_url = urljoin(base_url, action) if action else base_url

                if not validate_url(action_url):
                    continue

                method = form.get("method", "GET").upper()
                inputs = form.get("inputs", [])
                testable_inputs = [
                    inp for inp in inputs
                    if inp.get("name") and inp.get("type", "text") not in ("hidden", "submit", "button", "file", "image")
                ]

                if not testable_inputs:
                    continue

                result["forms_tested"] += 1

                for inp in testable_inputs:
                    elapsed = time.time() - start_time
                    if elapsed > time_budget:
                        break

                    for xss in XSS_PAYLOADS:
                        elapsed = time.time() - start_time
                        if elapsed > time_budget:
                            break

                        form_data = _build_form_data(inputs, inp["name"], xss["payload"])
                        try:
                            if method == "POST":
                                resp = client.post(action_url, data=form_data)
                            else:
                                resp = client.get(action_url, params=form_data)

                            result["payloads_sent"] += 1

                            if re.search(xss["detect"], resp.text, re.IGNORECASE):
                                snippet = _extract_response_snippet(resp.text, xss["detect"], context_chars=150)
                                result["xss_findings"].append({
                                    "type": "Reflected XSS",
                                    "form_url": form.get("page_url", action_url),
                                    "action_url": action_url,
                                    "method": method,
                                    "parameter": inp["name"],
                                    "payload": xss["payload"],
                                    "payload_name": xss["name"],
                                    "description": xss["description"],
                                    "evidence": f"Payload was reflected unescaped in the HTTP response. "
                                                f"The pattern '{xss['detect']}' matched in the response body.",
                                    "evidence_snapshot": {
                                        "type": "http_response",
                                        "label": f"XSS payload reflected in response from {action_url}",
                                        "request": f"{method} {action_url}\nParameter: {inp['name']}={xss['payload']}",
                                        "response_status": resp.status_code,
                                        "response_snippet": snippet,
                                    },
                                })
                        except Exception:
                            continue

                    for sqli in SQLI_PAYLOADS:
                        elapsed = time.time() - start_time
                        if elapsed > time_budget:
                            break

                        form_data = _build_form_data(inputs, inp["name"], sqli["payload"])
                        try:
                            if method == "POST":
                                resp = client.post(action_url, data=form_data)
                            else:
                                resp = client.get(action_url, params=form_data)

                            result["payloads_sent"] += 1

                            for pattern in sqli["error_patterns"]:
                                if re.search(pattern, resp.text, re.IGNORECASE):
                                    snippet = _extract_response_snippet(resp.text, pattern, context_chars=150)
                                    result["sqli_findings"].append({
                                        "type": "SQL Injection Indicator",
                                        "form_url": form.get("page_url", action_url),
                                        "action_url": action_url,
                                        "method": method,
                                        "parameter": inp["name"],
                                        "payload": sqli["payload"],
                                        "payload_name": sqli["name"],
                                        "description": sqli["description"],
                                        "evidence": f"Database error pattern detected in response: '{pattern}' matched. "
                                                    f"This suggests the input is being passed to a SQL query without proper sanitization.",
                                        "matched_pattern": pattern,
                                        "evidence_snapshot": {
                                            "type": "http_response",
                                            "label": f"SQL error in response from {action_url}",
                                            "request": f"{method} {action_url}\nParameter: {inp['name']}={sqli['payload']}",
                                            "response_status": resp.status_code,
                                            "response_snippet": snippet,
                                        },
                                    })
                                    break
                        except Exception:
                            continue

    except Exception as e:
        result["errors"].append(f"Injection tester error: {str(e)[:200]}")

    result["stats"]["time_elapsed"] = round(time.time() - start_time, 2)
    return result


def _extract_response_snippet(response_text: str, pattern: str, context_chars: int = 150) -> str:
    match = re.search(pattern, response_text, re.IGNORECASE)
    if not match:
        return response_text[:300] + ("..." if len(response_text) > 300 else "")

    start = max(0, match.start() - context_chars)
    end = min(len(response_text), match.end() + context_chars)

    snippet = response_text[start:end]
    snippet = re.sub(r'\s+', ' ', snippet).strip()

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(response_text) else ""
    return f"{prefix}{snippet}{suffix}"


def _build_form_data(inputs: List[Dict], target_name: str, payload: str) -> Dict[str, str]:
    data = {}
    for inp in inputs:
        name = inp.get("name", "")
        if not name:
            continue
        if name == target_name:
            data[name] = payload
        else:
            inp_type = inp.get("type", "text").lower()
            default_val = inp.get("value", "")
            if default_val:
                data[name] = default_val
            elif inp_type == "email":
                data[name] = "test@example.com"
            elif inp_type == "password":
                data[name] = "TestPassword123"
            elif inp_type in ("number", "tel"):
                data[name] = "12345"
            elif inp_type == "url":
                data[name] = "https://example.com"
            else:
                data[name] = "test"
    return data
