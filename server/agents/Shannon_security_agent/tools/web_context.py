import re
import httpx
import socket
import ssl
import ipaddress
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin


SSRF_BLOCKED = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "169.254.169.254", "metadata.google.internal"}


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if hostname.lower() in SSRF_BLOCKED:
            return False
        try:
            resolved = socket.gethostbyname(hostname)
            ip = ipaddress.ip_address(resolved)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except (socket.gaierror, ValueError):
            return False
        return True
    except Exception:
        return False


def _check_redirect(response):
    if response.is_redirect:
        location = response.headers.get("location", "")
        if location:
            redirect_url = urljoin(str(response.url), location)
            if not validate_url(redirect_url):
                raise httpx.TooManyRedirects(f"Redirect to blocked URL: {redirect_url}")


def _check_tls(url: str) -> Dict[str, Any]:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    tls_info = {
        "uses_https": parsed.scheme == "https",
        "http_to_https_redirect": False,
        "tls_version": None,
        "certificate_valid": None,
        "certificate_issuer": None,
        "certificate_expiry": None,
    }

    if parsed.scheme == "http":
        try:
            with httpx.Client(follow_redirects=False, timeout=10.0) as client:
                resp = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SecurityAssessment/1.0)"})
                if resp.status_code in (301, 302, 307, 308):
                    location = resp.headers.get("location", "")
                    if location.startswith("https://"):
                        tls_info["http_to_https_redirect"] = True
        except Exception:
            pass

    if parsed.scheme == "https" or tls_info["http_to_https_redirect"]:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    tls_info["tls_version"] = ssock.version()
                    cert = ssock.getpeercert()
                    if cert:
                        tls_info["certificate_valid"] = True
                        issuer = dict(x[0] for x in cert.get("issuer", []))
                        tls_info["certificate_issuer"] = issuer.get("organizationName", "Unknown")
                        tls_info["certificate_expiry"] = cert.get("notAfter", "Unknown")
        except ssl.SSLCertVerificationError as e:
            tls_info["certificate_valid"] = False
            tls_info["tls_version"] = "Error: " + str(e)
        except Exception:
            pass

    return tls_info


def gather_web_context(url: str) -> Dict[str, Any]:
    if not validate_url(url):
        return {"error": f"URL validation failed or blocked: {url}", "url": url}

    result = {
        "url": url,
        "status_code": None,
        "headers": {},
        "security_headers": {},
        "missing_security_headers": [],
        "forms": [],
        "input_fields": [],
        "links": [],
        "scripts": [],
        "meta_tags": [],
        "cookies": [],
        "technologies": [],
        "api_endpoints": [],
        "comments": [],
        "tls_info": {},
        "error": None,
        "recon_successful": False,
    }

    result["tls_info"] = _check_tls(url)

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            event_hooks={"response": [_check_redirect]},
        ) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SecurityAssessment/1.0)"},
            )

        final_hostname = resp.url.host or ""
        if final_hostname.lower() in SSRF_BLOCKED:
            return {"error": f"Final URL resolved to blocked host: {final_hostname}", "url": url}
        try:
            final_ip = socket.gethostbyname(final_hostname)
            ip_obj = ipaddress.ip_address(final_ip)
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local:
                return {"error": f"Final URL resolved to private IP: {final_ip}", "url": url}
        except (socket.gaierror, ValueError):
            pass

        result["status_code"] = resp.status_code
        result["headers"] = dict(resp.headers)
        result["recon_successful"] = True

        raw_headers_str = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
        result["raw_headers_snapshot"] = f"HTTP/{resp.http_version} {resp.status_code}\n{raw_headers_str}"

        important_headers = [
            "Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options",
            "Strict-Transport-Security", "X-XSS-Protection", "Referrer-Policy",
            "Permissions-Policy",
        ]

        security_headers = {}
        missing_headers = []
        for h in important_headers:
            val = resp.headers.get(h.lower())
            if val:
                security_headers[h] = val
            else:
                missing_headers.append(h)

        cors_val = resp.headers.get("access-control-allow-origin")
        if cors_val:
            security_headers["Access-Control-Allow-Origin"] = cors_val
        set_cookie_val = resp.headers.get("set-cookie")
        if set_cookie_val:
            security_headers["Set-Cookie"] = set_cookie_val

        result["security_headers"] = security_headers
        result["missing_security_headers"] = missing_headers

        for cookie in resp.cookies.jar:
            result["cookies"].append({
                "name": cookie.name,
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": cookie.secure,
                "httponly": "httponly" in str(cookie).lower(),
            })

        html = resp.text
        soup = BeautifulSoup(html, "html.parser")

        for form in soup.find_all("form"):
            form_data = {
                "action": form.get("action", ""),
                "method": form.get("method", "GET").upper(),
                "inputs": [],
                "has_csrf_token": False,
            }
            for inp in form.find_all(["input", "textarea", "select"]):
                inp_data = {
                    "name": inp.get("name", ""),
                    "type": inp.get("type", "text"),
                    "id": inp.get("id", ""),
                }
                form_data["inputs"].append(inp_data)
                name_lower = (inp.get("name") or "").lower()
                if any(tok in name_lower for tok in ["csrf", "token", "_token", "authenticity"]):
                    form_data["has_csrf_token"] = True
            result["forms"].append(form_data)

        for inp in soup.find_all(["input", "textarea"]):
            result["input_fields"].append({
                "name": inp.get("name", ""),
                "type": inp.get("type", "text"),
                "id": inp.get("id", ""),
                "placeholder": inp.get("placeholder", ""),
            })

        parsed_base = urlparse(url)
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = urljoin(url, href)
            parsed_link = urlparse(full)
            if parsed_link.netloc == parsed_base.netloc:
                result["links"].append(full)
        result["links"] = list(set(result["links"]))[:100]

        for script in soup.find_all("script"):
            src = script.get("src", "")
            if src:
                result["scripts"].append(urljoin(url, src))
            else:
                inline = script.string or ""
                api_patterns = re.findall(r'["\'](/api/[^"\']+)["\']', inline)
                result["api_endpoints"].extend(api_patterns)
                fetch_patterns = re.findall(r'fetch\s*\(\s*["\']([^"\']+)["\']', inline)
                result["api_endpoints"].extend(fetch_patterns)
                xhr_patterns = re.findall(r'\.open\s*\(\s*["\'][A-Z]+["\']\s*,\s*["\']([^"\']+)["\']', inline)
                result["api_endpoints"].extend(xhr_patterns)

        result["api_endpoints"] = list(set(result["api_endpoints"]))[:50]

        for meta in soup.find_all("meta"):
            result["meta_tags"].append({
                "name": meta.get("name", meta.get("property", "")),
                "content": meta.get("content", ""),
            })

        comments = re.findall(r'<!--(.*?)-->', html, re.DOTALL)
        result["comments"] = [c.strip()[:200] for c in comments[:20]]

        server = resp.headers.get("server", "")
        powered_by = resp.headers.get("x-powered-by", "")
        if server:
            result["technologies"].append(f"Server: {server}")
        if powered_by:
            result["technologies"].append(f"Powered-By: {powered_by}")

        framework_hints = {
            "react": "React",
            "angular": "Angular",
            "vue": "Vue.js",
            "next": "Next.js",
            "nuxt": "Nuxt.js",
            "express": "Express.js",
            "django": "Django",
            "flask": "Flask",
            "laravel": "Laravel",
            "wordpress": "WordPress",
            "jquery": "jQuery",
        }
        html_lower = html.lower()
        for hint, name in framework_hints.items():
            if hint in html_lower:
                result["technologies"].append(name)

    except Exception as e:
        result["error"] = str(e)

    return result


def summarize_web_context(ctx: Dict[str, Any]) -> str:
    if ctx.get("error") and not ctx.get("recon_successful"):
        return f"**RECON FAILURE**: Could not retrieve target. Error: {ctx['error']}\nNo further analysis can be performed on data that was not collected."

    lines = [
        f"## Target: {ctx['url']}",
        f"HTTP Status: {ctx.get('status_code', 'N/A')}",
        f"Recon Status: {'Successful' if ctx.get('recon_successful') else 'Failed'}",
    ]

    tls = ctx.get("tls_info", {})
    if tls:
        lines.append("\n### TLS/HTTPS Status")
        lines.append(f"- Uses HTTPS: {'Yes' if tls.get('uses_https') else 'No'}")
        if not tls.get("uses_https"):
            lines.append(f"- HTTP→HTTPS Redirect: {'Yes' if tls.get('http_to_https_redirect') else 'No'}")
        if tls.get("tls_version"):
            lines.append(f"- TLS Version: {tls['tls_version']}")
        if tls.get("certificate_valid") is not None:
            lines.append(f"- Certificate Valid: {'Yes' if tls['certificate_valid'] else 'NO — INVALID'}")
        if tls.get("certificate_issuer"):
            lines.append(f"- Issuer: {tls['certificate_issuer']}")

    lines.append("\n### Security Headers")
    present = ctx.get("security_headers", {})
    missing = ctx.get("missing_security_headers", [])

    for h in missing:
        lines.append(f"- {h}: ❌ MISSING")
    for h, v in present.items():
        if h not in ("Access-Control-Allow-Origin", "Set-Cookie"):
            lines.append(f"- {h}: ✅ {v}")

    cors_val = present.get("Access-Control-Allow-Origin")
    if cors_val:
        lines.append(f"- Access-Control-Allow-Origin: {'⚠️ WILDCARD (*)' if cors_val == '*' else '✅ ' + cors_val}")

    if ctx.get("cookies"):
        lines.append(f"\n### Cookies ({len(ctx['cookies'])} found)")
        for c in ctx["cookies"]:
            flags = []
            if c.get("secure"):
                flags.append("Secure")
            if c.get("httponly"):
                flags.append("HttpOnly")
            lines.append(f"- {c['name']}: {', '.join(flags) if flags else '⚠️ No security flags'}")
    else:
        lines.append("\n### Cookies: None detected")

    if ctx.get("forms"):
        lines.append(f"\n### Forms ({len(ctx['forms'])} found)")
        for i, f in enumerate(ctx["forms"][:10], 1):
            csrf = "has CSRF token" if f.get("has_csrf_token") else "⚠️ NO CSRF token"
            lines.append(f"- Form {i}: action={f['action']}, method={f['method']}, inputs={len(f['inputs'])}, {csrf}")
            for inp in f["inputs"][:5]:
                lines.append(f"  - {inp['type']}: name={inp['name']}")
    else:
        lines.append("\n### Forms: None detected")

    if ctx.get("input_fields"):
        lines.append(f"\n### Input Fields ({len(ctx['input_fields'])} found)")
    else:
        lines.append("\n### Input Fields: None detected")

    if ctx.get("api_endpoints"):
        lines.append(f"\n### Discovered API Endpoints ({len(ctx['api_endpoints'])})")
        for ep in ctx["api_endpoints"][:20]:
            lines.append(f"- {ep}")
    else:
        lines.append("\n### API Endpoints: None discovered")

    if ctx.get("links"):
        lines.append(f"\n### Internal Links ({len(ctx['links'])} found)")
        for link in ctx["links"][:20]:
            lines.append(f"- {link}")

    if ctx.get("technologies"):
        lines.append(f"\n### Detected Technologies")
        for t in ctx["technologies"]:
            lines.append(f"- {t}")

    if ctx.get("comments"):
        lines.append(f"\n### HTML Comments ({len(ctx['comments'])} found)")
        for c in ctx["comments"][:5]:
            lines.append(f"- {c[:100]}")

    if ctx.get("error"):
        lines.append(f"\n### Partial Errors During Recon")
        lines.append(f"- {ctx['error']}")

    return "\n".join(lines)
