import httpx
import re
import time
from typing import Dict, Any, List
from urllib.parse import urljoin

from .web_context import validate_url, _check_redirect


SENSITIVE_PATHS = [
    ("/.env", "Environment configuration file — may contain API keys, database credentials, and secrets"),
    ("/.git/HEAD", "Git repository metadata — may expose source code history and sensitive commits"),
    ("/.git/config", "Git configuration — may expose repository URLs and credentials"),
    ("/.svn/entries", "SVN repository metadata — may expose source code"),
    ("/.htaccess", "Apache configuration — may reveal URL rewriting rules and access controls"),
    ("/.htpasswd", "Apache password file — may contain hashed credentials"),
    ("/wp-admin/", "WordPress admin panel"),
    ("/wp-login.php", "WordPress login page"),
    ("/admin", "Admin panel"),
    ("/admin/", "Admin panel"),
    ("/administrator/", "Admin panel"),
    ("/login", "Login page"),
    ("/signin", "Sign-in page"),
    ("/api/", "API root — may expose API documentation or endpoints"),
    ("/api/docs", "API documentation (Swagger/OpenAPI)"),
    ("/api/swagger", "Swagger UI"),
    ("/api/v1/", "API version 1 root"),
    ("/api/v2/", "API version 2 root"),
    ("/swagger-ui.html", "Swagger UI"),
    ("/swagger.json", "Swagger/OpenAPI specification"),
    ("/openapi.json", "OpenAPI specification"),
    ("/graphql", "GraphQL endpoint — may allow introspection queries"),
    ("/graphiql", "GraphQL interactive IDE"),
    ("/debug", "Debug page — may expose application internals"),
    ("/debug/", "Debug page"),
    ("/trace", "Trace endpoint"),
    ("/server-status", "Apache server status page"),
    ("/server-info", "Apache server info page"),
    ("/phpinfo.php", "PHP info page — exposes full server configuration"),
    ("/info.php", "PHP info page"),
    ("/test", "Test page"),
    ("/test.php", "Test page"),
    ("/backup/", "Backup directory"),
    ("/backup.sql", "Database backup file"),
    ("/database.sql", "Database dump file"),
    ("/dump.sql", "Database dump file"),
    ("/db.sql", "Database dump file"),
    ("/config.php", "Configuration file"),
    ("/config.yml", "Configuration file"),
    ("/config.json", "Configuration file"),
    ("/settings.py", "Python settings file"),
    ("/credentials.json", "Credentials file"),
    ("/.docker/", "Docker configuration"),
    ("/docker-compose.yml", "Docker compose file"),
    ("/Dockerfile", "Dockerfile — may expose build process"),
    ("/robots.txt", "Robots.txt — may reveal hidden paths"),
    ("/sitemap.xml", "Sitemap — reveals site structure"),
    ("/crossdomain.xml", "Flash cross-domain policy"),
    ("/security.txt", "Security contact information"),
    ("/.well-known/security.txt", "Security contact information"),
    ("/actuator", "Spring Boot Actuator — may expose health, env, beans"),
    ("/actuator/env", "Spring Boot environment variables"),
    ("/actuator/health", "Spring Boot health endpoint"),
    ("/elmah.axd", "ELMAH error log (ASP.NET)"),
    ("/trace.axd", "ASP.NET trace"),
    ("/console", "Application console"),
    ("/.DS_Store", "macOS directory metadata — may expose file listing"),
    ("/web.config", "IIS configuration file"),
    ("/WEB-INF/web.xml", "Java web application configuration"),
]


def enumerate_directories(
    base_url: str,
    time_budget: float = 30.0,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    result = {
        "accessible_paths": [],
        "interesting_responses": [],
        "robots_txt_entries": [],
        "stats": {
            "paths_checked": 0,
            "accessible_found": 0,
            "time_elapsed": 0,
        },
        "errors": [],
    }

    if not validate_url(base_url):
        result["errors"].append(f"URL validation failed: {base_url}")
        return result

    start_time = time.time()

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            event_hooks={"response": [_check_redirect]},
            headers={"User-Agent": "Mozilla/5.0 (compatible; SecurityAssessment/1.0)"},
        ) as client:
            try:
                robots_resp = client.get(urljoin(base_url, "/robots.txt"))
                if robots_resp.status_code == 200 and "text" in robots_resp.headers.get("content-type", ""):
                    for line in robots_resp.text.split("\n"):
                        line = line.strip()
                        if line.lower().startswith("disallow:"):
                            path = line.split(":", 1)[1].strip()
                            if path and path != "/":
                                result["robots_txt_entries"].append(path)
                        elif line.lower().startswith("allow:"):
                            path = line.split(":", 1)[1].strip()
                            if path:
                                result["robots_txt_entries"].append(path)
            except Exception:
                pass

            extra_paths = [(p, "Found in robots.txt — may be intentionally hidden") for p in result["robots_txt_entries"][:20]]
            all_paths = SENSITIVE_PATHS + extra_paths

            for path, description in all_paths:
                elapsed = time.time() - start_time
                if elapsed > time_budget:
                    result["errors"].append(f"Time budget exceeded ({time_budget}s)")
                    break

                full_url = urljoin(base_url, path)
                if not validate_url(full_url):
                    continue

                try:
                    resp = client.get(full_url)
                    result["stats"]["paths_checked"] += 1

                    if resp.status_code == 200:
                        content_length = len(resp.content)
                        content_type = resp.headers.get("content-type", "")

                        is_default_page = False
                        if content_length < 50:
                            is_default_page = True
                        if resp.url != httpx.URL(full_url) and str(resp.url).rstrip("/") == base_url.rstrip("/"):
                            is_default_page = True

                        if not is_default_page:
                            body_preview = resp.text[:500].strip()
                            if len(resp.text) > 500:
                                body_preview += "..."
                            body_preview = re.sub(r'\s+', ' ', body_preview)

                            resp_headers_str = "\n".join(
                                f"{k}: {v}" for k, v in resp.headers.items()
                                if k.lower() in ("content-type", "server", "x-powered-by", "set-cookie", "x-frame-options", "content-length")
                            )

                            entry = {
                                "path": path,
                                "url": str(resp.url),
                                "status_code": 200,
                                "content_type": content_type,
                                "content_length": content_length,
                                "description": description,
                                "evidence_snapshot": {
                                    "type": "exposed_path",
                                    "label": f"Exposed path: {path}",
                                    "request": f"GET {str(resp.url)}",
                                    "response_status": 200,
                                    "response_headers": resp_headers_str,
                                    "response_body_preview": body_preview,
                                },
                            }
                            result["accessible_paths"].append(entry)
                            result["stats"]["accessible_found"] += 1

                    elif resp.status_code in (401, 403):
                        result["interesting_responses"].append({
                            "path": path,
                            "status_code": resp.status_code,
                            "description": f"{description} (access restricted — {resp.status_code})",
                        })

                except Exception:
                    continue

    except Exception as e:
        result["errors"].append(f"Directory enumeration error: {str(e)[:200]}")

    result["stats"]["time_elapsed"] = round(time.time() - start_time, 2)
    return result
