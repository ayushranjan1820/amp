import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from .ai_service import ai_service
from .tools.web_context import gather_web_context, summarize_web_context, validate_url
from .tools.owasp_mapper import get_owasp_checklist, map_finding_to_owasp, OWASP_TOP_10
from .tools.report_builder import build_security_report, parse_llm_findings
from .tools.crawler import crawl_site
from .tools.dir_enum import enumerate_directories
from .tools.injection_tester import test_form_injections
from .tools.method_tester import test_http_methods
from .tools.cve_lookup import lookup_cves

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    env_path = Path(__file__).parent.parent.parent / '.env'
    load_dotenv_then_scrub_pwc(dotenv_path=env_path)


class ShannonSecurityAgent:
    def __init__(self):
        self.ai_service = ai_service
        self.sessions: Dict[str, Dict[str, Any]] = {}
        print("🛡️ Shannon Security Agent initialized")

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "url": None,
                "web_context": None,
                "web_summary": None,
                "repo_summary": None,
                "findings": None,
                "report": None,
                "phase": "idle",
                "history": [],
            }
        return self.sessions[session_id]

    def _extract_url(self, text: str) -> Optional[str]:
        patterns = [
            r'https?://[^\s<>"\'`,;)}\]]+',
            r'www\.[^\s<>"\'`,;)}\]]+',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                url = match.group(0).rstrip('.')
                if url.startswith('www.'):
                    url = 'https://' + url
                return url
        return None

    def _is_security_query(self, query: str) -> bool:
        keywords = [
            'security', 'pentest', 'penetration', 'vulnerability', 'vulnerabilities',
            'owasp', 'xss', 'injection', 'sqli', 'ssrf', 'exploit',
            'scan', 'assess', 'audit', 'attack', 'breach', 'hack',
            'secure', 'insecure', 'risk', 'threat', 'weakness',
        ]
        q_lower = query.lower()
        return any(kw in q_lower for kw in keywords)

    def process_query(self, query: str, session_id: str = "default") -> Dict[str, Any]:
        session = self._get_session(session_id)
        session["history"].append({"role": "user", "content": query})

        url = self._extract_url(query)
        q_lower = query.lower()

        if url and not session["url"]:
            session["url"] = url

        if not session["url"] and not session["report"]:
            if self._is_security_query(query):
                response = (
                    "I'm the Shannon Security Agent — I perform **deep AI-driven security assessments** "
                    "on web applications, inspired by the [Shannon pentesting framework](https://github.com/KeygraphHQ/shannon).\n\n"
                    "To get started, please provide:\n"
                    "- **A target URL** to assess (e.g., `https://your-app.com`)\n\n"
                    "My deep scan includes:\n"
                    "- **Full site crawling** — discovers all pages, not just the homepage\n"
                    "- **Sensitive path discovery** — checks for exposed files like `.env`, `.git`, `/admin`, API docs\n"
                    "- **Active injection testing** — sends safe XSS and SQL injection payloads to forms\n"
                    "- **HTTP method probing** — tests for dangerous methods (PUT, DELETE, TRACE)\n"
                    "- **TLS/HTTPS verification** — checks certificate validity and protocol version\n"
                    "- **Technology CVE lookup** — matches detected server versions against known vulnerabilities\n"
                    "- **OWASP Top 10 analysis** — comprehensive mapping of all findings\n\n"
                    "Just paste a URL and I'll begin the deep assessment."
                )
                session["history"].append({"role": "assistant", "content": response})
                return {"success": True, "response": response}
            else:
                response = self._ask_llm_general(query)
                session["history"].append({"role": "assistant", "content": response})
                return {"success": True, "response": response}

        if session["url"] and not session["web_context"]:
            return self._run_deep_assessment(session)

        if session["report"]:
            if any(kw in q_lower for kw in ['finding', 'detail', 'explain', 'more about', 'elaborate']):
                response = self._ask_about_findings(query, session)
                session["history"].append({"role": "assistant", "content": response})
                return {"success": True, "response": response}
            elif any(kw in q_lower for kw in ['rescan', 'scan again', 'reassess', 'new scan']):
                session["web_context"] = None
                session["web_summary"] = None
                session["findings"] = None
                session["report"] = None
                session["phase"] = "idle"
                return self._run_deep_assessment(session)
            elif url and url != session["url"]:
                session["url"] = url
                session["web_context"] = None
                session["web_summary"] = None
                session["findings"] = None
                session["report"] = None
                session["phase"] = "idle"
                return self._run_deep_assessment(session)
            else:
                response = self._ask_about_findings(query, session)
                session["history"].append({"role": "assistant", "content": response})
                return {"success": True, "response": response}

        return self._run_deep_assessment(session)

    def _run_deep_assessment(self, session: Dict[str, Any]) -> Dict[str, Any]:
        url = session["url"]
        thinking_steps = []
        all_findings = []

        thinking_steps.append({
            "type": "thinking",
            "content": f"Phase 1: Pre-Reconnaissance — Validating target URL: {url}"
        })

        if not validate_url(url):
            response = (
                f"I couldn't validate the URL `{url}`. Please make sure:\n"
                "- It starts with `http://` or `https://`\n"
                "- It's a publicly accessible domain\n"
                "- It's not a local/private IP address"
            )
            session["history"].append({"role": "assistant", "content": response})
            session["url"] = None
            return {"success": False, "response": response}

        # === PHASE 2: Initial Reconnaissance ===
        session["phase"] = "reconnaissance"
        thinking_steps.append({
            "type": "tool_call",
            "content": "Phase 2: Initial Reconnaissance — Fetching homepage, headers, TLS, cookies...",
            "tool_name": "web_context"
        })

        try:
            web_ctx = gather_web_context(url)
            session["web_context"] = web_ctx
        except Exception as e:
            response = f"Error during reconnaissance of `{url}`: {str(e)}"
            session["history"].append({"role": "assistant", "content": response})
            return {"success": False, "response": response, "thinking_steps": thinking_steps}

        recon_ok = web_ctx.get("recon_successful", False)
        recon_error = web_ctx.get("error")

        if not recon_ok and recon_error:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"Reconnaissance FAILED: {recon_error}",
                "tool_name": "web_context"
            })

            tls_info = web_ctx.get("tls_info", {})
            tls_findings = self._analyze_tls(url, tls_info)

            web_summary = summarize_web_context(web_ctx)
            session["web_summary"] = web_summary
            session["findings"] = tls_findings

            report = build_security_report(
                url=url,
                findings=tls_findings,
                web_summary=web_summary,
                assessment_status="INCONCLUSIVE",
                recon_error=recon_error,
            )
            session["report"] = report
            session["phase"] = "complete"

            thinking_steps.append({
                "type": "thinking",
                "content": f"Assessment marked INCONCLUSIVE — reconnaissance failed. Only TLS checks performed. {len(tls_findings)} findings."
            })

            session["history"].append({"role": "assistant", "content": report})
            return {"success": True, "response": report, "thinking_steps": thinking_steps}

        web_summary = summarize_web_context(web_ctx)
        session["web_summary"] = web_summary

        thinking_steps.append({
            "type": "tool_result",
            "content": (
                f"Homepage recon complete (HTTP {web_ctx.get('status_code', '?')}). "
                f"{len(web_ctx.get('forms', []))} forms, {len(web_ctx.get('cookies', []))} cookies, "
                f"{len(web_ctx.get('missing_security_headers', []))} missing headers, "
                f"{len(web_ctx.get('technologies', []))} technologies"
            ),
            "tool_name": "web_context"
        })

        all_findings.extend(self._analyze_tls(url, web_ctx.get("tls_info", {})))
        all_findings.extend(self._analyze_missing_headers(web_ctx))
        all_findings.extend(self._analyze_cookies(web_ctx))
        all_findings.extend(self._analyze_cors(web_ctx))

        # === PHASE 3: Site Crawling ===
        session["phase"] = "crawling"
        thinking_steps.append({
            "type": "tool_call",
            "content": "Phase 3: Site Crawling — Discovering all pages (max 30 pages, depth 3)...",
            "tool_name": "crawler"
        })

        try:
            crawl_result = crawl_site(url, max_pages=30, max_depth=3, time_budget=30)
            crawl_stats = crawl_result["stats"]

            thinking_steps.append({
                "type": "tool_result",
                "content": (
                    f"Crawled {crawl_stats['pages_crawled']} pages, found {crawl_stats['total_urls_found']} URLs "
                    f"(depth {crawl_stats['max_depth_reached']}) in {crawl_stats['time_elapsed']}s. "
                    f"Discovered {len(crawl_result['forms_found'])} forms, {len(crawl_result['api_endpoints'])} API endpoints"
                ),
                "tool_name": "crawler"
            })

            for page in crawl_result["pages_crawled"]:
                if page["security_headers_missing"] and page["url"] != url:
                    page_missing = page["security_headers_missing"]
                    header_diff = set(page_missing) - set(web_ctx.get("missing_security_headers", []))
                    for h in header_diff:
                        all_findings.append({
                            "title": f"Inconsistent Security Headers on {page['url']}",
                            "severity": "Medium",
                            "owasp_category": "A05:2021 — Security Misconfiguration",
                            "location": page["url"],
                            "description": f"The page at {page['url']} is missing the '{h}' header, while other pages may have it. Inconsistent security header deployment can leave some pages vulnerable.",
                            "evidence": f"Crawled page at depth {page['depth']} is missing header '{h}' in its response.",
                            "recommendation": "Ensure security headers are applied consistently across all pages via server-level configuration.",
                        })

            for cookie in crawl_result["cookies_collected"]:
                if not any(c["name"] == cookie["name"] for c in web_ctx.get("cookies", [])):
                    if not cookie.get("secure"):
                        all_findings.append({
                            "title": f"Cookie '{cookie['name']}' Missing Secure Flag (discovered on {cookie.get('found_on', 'crawled page')})",
                            "severity": "Medium",
                            "owasp_category": "A02:2021 — Cryptographic Failures",
                            "location": f"Cookie: {cookie['name']} on {cookie.get('found_on', '')}",
                            "description": f"Cookie '{cookie['name']}' discovered during crawling does not have the Secure flag.",
                            "evidence": f"Set-Cookie for '{cookie['name']}' observed on {cookie.get('found_on', 'a crawled page')} without Secure attribute.",
                            "recommendation": "Set the Secure flag on all cookies.",
                        })

            all_forms = web_ctx.get("forms", []) + crawl_result.get("forms_found", [])
            all_api_endpoints = web_ctx.get("api_endpoints", []) + crawl_result.get("api_endpoints", [])

        except Exception as e:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"Crawling failed: {str(e)[:100]}",
                "tool_name": "crawler"
            })
            all_forms = web_ctx.get("forms", [])
            all_api_endpoints = web_ctx.get("api_endpoints", [])

        # === PHASE 4: Directory Enumeration ===
        session["phase"] = "dir_enum"
        thinking_steps.append({
            "type": "tool_call",
            "content": "Phase 4: Sensitive Path Discovery — Checking for exposed files, admin panels, backups...",
            "tool_name": "dir_enum"
        })

        try:
            dir_result = enumerate_directories(url, time_budget=25)

            accessible = dir_result["accessible_paths"]
            restricted = dir_result["interesting_responses"]
            robots = dir_result["robots_txt_entries"]

            thinking_steps.append({
                "type": "tool_result",
                "content": (
                    f"Checked {dir_result['stats']['paths_checked']} paths in {dir_result['stats']['time_elapsed']}s. "
                    f"Found {len(accessible)} accessible, {len(restricted)} restricted, "
                    f"{len(robots)} robots.txt entries"
                ),
                "tool_name": "dir_enum"
            })

            sensitive_patterns = [".env", ".git", ".svn", ".htpasswd", "backup", ".sql", "credentials", "config", ".DS_Store"]
            for path_info in accessible:
                path = path_info["path"]
                is_sensitive = any(p in path.lower() for p in sensitive_patterns)
                severity = "Critical" if is_sensitive else "Medium"
                owasp = "A01:2021 — Broken Access Control" if is_sensitive else "A05:2021 — Security Misconfiguration"

                finding = {
                    "title": f"Exposed Path: {path}",
                    "severity": severity,
                    "owasp_category": owasp,
                    "location": path_info["url"],
                    "description": f"{path_info['description']}. This path is publicly accessible and returned HTTP 200.",
                    "evidence": (
                        f"HTTP GET {path_info['url']} returned status 200 with content-type '{path_info.get('content_type', 'N/A')}' "
                        f"and {path_info.get('content_length', 0)} bytes."
                    ),
                    "recommendation": "Restrict access to this path. Use authentication, remove the file from the web root, or block access via server configuration.",
                }
                if path_info.get("evidence_snapshot"):
                    finding["evidence_snapshot"] = path_info["evidence_snapshot"]
                all_findings.append(finding)

        except Exception as e:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"Directory enumeration failed: {str(e)[:100]}",
                "tool_name": "dir_enum"
            })

        # === PHASE 5: Injection Testing ===
        session["phase"] = "injection_testing"
        if all_forms:
            thinking_steps.append({
                "type": "tool_call",
                "content": f"Phase 5: Active Injection Testing — Testing {len(all_forms)} forms with XSS and SQLi payloads...",
                "tool_name": "injection_tester"
            })

            try:
                injection_result = test_form_injections(all_forms, url, time_budget=30)

                xss_count = len(injection_result["xss_findings"])
                sqli_count = len(injection_result["sqli_findings"])

                thinking_steps.append({
                    "type": "tool_result",
                    "content": (
                        f"Tested {injection_result['forms_tested']} forms with {injection_result['payloads_sent']} payloads "
                        f"in {injection_result['stats']['time_elapsed']}s. "
                        f"Found {xss_count} XSS and {sqli_count} SQLi indicators"
                    ),
                    "tool_name": "injection_tester"
                })

                for xss in injection_result["xss_findings"]:
                    finding = {
                        "title": f"Reflected XSS in '{xss['parameter']}' parameter",
                        "severity": "High",
                        "owasp_category": "A03:2021 — Injection",
                        "location": f"Form: {xss['form_url']} → {xss['action_url']} ({xss['method']})",
                        "description": f"{xss['description']}. The parameter '{xss['parameter']}' reflects user input without proper encoding, allowing script injection.",
                        "evidence": xss["evidence"],
                        "recommendation": "Encode all user input before rendering in HTML. Use context-appropriate encoding (HTML entity, JavaScript, URL). Implement a Content-Security-Policy header.",
                    }
                    if xss.get("evidence_snapshot"):
                        finding["evidence_snapshot"] = xss["evidence_snapshot"]
                    all_findings.append(finding)

                for sqli in injection_result["sqli_findings"]:
                    finding = {
                        "title": f"SQL Injection Indicator in '{sqli['parameter']}' parameter",
                        "severity": "Critical",
                        "owasp_category": "A03:2021 — Injection",
                        "location": f"Form: {sqli['form_url']} → {sqli['action_url']} ({sqli['method']})",
                        "description": f"{sqli['description']}. Database error messages in the response suggest user input is being passed to SQL queries without proper parameterization.",
                        "evidence": sqli["evidence"],
                        "recommendation": "Use parameterized queries or prepared statements. Never concatenate user input into SQL queries. Implement an ORM or query builder.",
                    }
                    if sqli.get("evidence_snapshot"):
                        finding["evidence_snapshot"] = sqli["evidence_snapshot"]
                    all_findings.append(finding)

            except Exception as e:
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"Injection testing failed: {str(e)[:100]}",
                    "tool_name": "injection_tester"
                })
        else:
            thinking_steps.append({
                "type": "thinking",
                "content": "Phase 5: Injection Testing — Skipped (no forms discovered to test)"
            })

        all_findings.extend(self._analyze_forms_from_list(all_forms))

        # === PHASE 6: HTTP Method Testing ===
        session["phase"] = "method_testing"
        test_paths = list(set(all_api_endpoints[:10] + ["/", "/api/"]))

        thinking_steps.append({
            "type": "tool_call",
            "content": f"Phase 6: HTTP Method Testing — Probing {len(test_paths)} endpoints for dangerous methods...",
            "tool_name": "method_tester"
        })

        try:
            method_result = test_http_methods(url, endpoints=test_paths, time_budget=15)

            thinking_steps.append({
                "type": "tool_result",
                "content": (
                    f"Tested {method_result['stats']['endpoints_tested']} endpoints with "
                    f"{method_result['stats']['methods_tested']} method probes in "
                    f"{method_result['stats']['time_elapsed']}s. "
                    f"Found {len(method_result['findings'])} issues"
                ),
                "tool_name": "method_tester"
            })

            all_findings.extend(method_result["findings"])

        except Exception as e:
            thinking_steps.append({
                "type": "tool_result",
                "content": f"Method testing failed: {str(e)[:100]}",
                "tool_name": "method_tester"
            })

        # === PHASE 7: CVE Lookup ===
        session["phase"] = "cve_lookup"
        all_tech = list(set(web_ctx.get("technologies", []) + crawl_result.get("technologies", []))) if 'crawl_result' in dir() else web_ctx.get("technologies", [])
        server_header = ""
        for t in all_tech:
            if t.startswith("Server: "):
                server_header = t.replace("Server: ", "")

        if all_tech or server_header:
            thinking_steps.append({
                "type": "tool_call",
                "content": f"Phase 7: CVE Lookup — Checking {len(all_tech)} detected technologies against known vulnerabilities...",
                "tool_name": "cve_lookup"
            })

            try:
                cve_result = lookup_cves(all_tech, server_header)

                thinking_steps.append({
                    "type": "tool_result",
                    "content": (
                        f"Analyzed {cve_result['stats']['technologies_analyzed']} technologies. "
                        f"Found {cve_result['stats']['cves_found']} known vulnerabilities"
                    ),
                    "tool_name": "cve_lookup"
                })

                all_findings.extend(cve_result["findings"])

                if server_header:
                    all_findings.append({
                        "title": "Server Version Disclosure",
                        "severity": "Low",
                        "owasp_category": "A05:2021 — Security Misconfiguration",
                        "location": "Server HTTP Header",
                        "description": f"The server discloses its identity/version: '{server_header}'. This helps attackers target known vulnerabilities.",
                        "evidence": f"HTTP 'Server' header contains: '{server_header}'.",
                        "recommendation": "Remove or obfuscate the Server header.",
                    })

            except Exception as e:
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"CVE lookup failed: {str(e)[:100]}",
                    "tool_name": "cve_lookup"
                })
        else:
            thinking_steps.append({
                "type": "thinking",
                "content": "Phase 7: CVE Lookup — Skipped (no technology versions detected)"
            })

        # === PHASE 8: LLM Deep Analysis ===
        session["phase"] = "llm_analysis"
        if all_forms or web_ctx.get("cookies") or all_api_endpoints:
            thinking_steps.append({
                "type": "tool_call",
                "content": "Phase 8: AI Deep Analysis — LLM reviewing all collected evidence for additional vulnerabilities...",
                "tool_name": "llm_analyzer"
            })

            try:
                llm_findings = self._llm_analyze(url, web_ctx, web_summary, all_forms, all_api_endpoints)
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"AI analysis found {len(llm_findings)} additional findings",
                    "tool_name": "llm_analyzer"
                })
                all_findings.extend(llm_findings)
            except Exception as e:
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"AI analysis failed (non-fatal): {str(e)[:100]}",
                    "tool_name": "llm_analyzer"
                })
        else:
            thinking_steps.append({
                "type": "thinking",
                "content": "Phase 8: AI Analysis — Skipped (no forms, cookies, or APIs to analyze beyond what's already checked)"
            })

        # === PHASE 9: Report Generation ===
        session["phase"] = "report"

        seen_titles = set()
        unique_findings = []
        for f in all_findings:
            key = f.get("title", "").lower().strip()
            if key not in seen_titles:
                seen_titles.add(key)
                unique_findings.append(f)

        session["findings"] = unique_findings

        scan_stats = {
            "pages_crawled": crawl_result["stats"]["pages_crawled"] if 'crawl_result' in dir() else 0,
            "paths_checked": dir_result["stats"]["paths_checked"] if 'dir_result' in dir() else 0,
            "forms_tested": injection_result["forms_tested"] if 'injection_result' in dir() else 0,
            "payloads_sent": injection_result["payloads_sent"] if 'injection_result' in dir() else 0,
            "methods_probed": method_result["stats"]["methods_tested"] if 'method_result' in dir() else 0,
        }

        thinking_steps.append({
            "type": "tool_call",
            "content": f"Phase 9: Report Generation — Compiling {len(unique_findings)} unique findings from all phases...",
            "tool_name": "report_builder"
        })

        report = build_security_report(
            url=url,
            findings=unique_findings,
            web_summary=web_summary,
            repo_summary=session.get("repo_summary", ""),
            scan_stats=scan_stats,
        )
        session["report"] = report
        session["phase"] = "complete"

        thinking_steps.append({
            "type": "tool_result",
            "content": f"Deep assessment complete — {len(unique_findings)} evidence-backed findings across 8 scan phases",
            "tool_name": "report_builder"
        })

        session["history"].append({"role": "assistant", "content": report})
        return {
            "success": True,
            "response": report,
            "thinking_steps": thinking_steps,
        }

    def _analyze_tls(self, url: str, tls_info: Dict) -> List[Dict]:
        findings = []
        if not tls_info:
            return findings

        if not tls_info.get("uses_https"):
            if not tls_info.get("http_to_https_redirect"):
                findings.append({
                    "title": "No HTTPS — Cleartext HTTP Communication",
                    "severity": "High",
                    "owasp_category": "A02:2021 — Cryptographic Failures",
                    "location": url,
                    "description": "The target is served over HTTP without redirecting to HTTPS. All data is transmitted in cleartext.",
                    "evidence": f"URL scheme is HTTP. No HTTP→HTTPS redirect detected.",
                    "recommendation": "Enable HTTPS with a valid TLS certificate and redirect all HTTP traffic to HTTPS.",
                })
            else:
                findings.append({
                    "title": "HTTP→HTTPS Redirect Present",
                    "severity": "Informational",
                    "owasp_category": "A02:2021 — Cryptographic Failures",
                    "location": url,
                    "description": "The site redirects HTTP to HTTPS, which is good practice.",
                    "evidence": "HTTP request returned a redirect to HTTPS.",
                    "recommendation": "Ensure HSTS header is also set to prevent downgrade attacks.",
                })

        if tls_info.get("certificate_valid") is False:
            findings.append({
                "title": "Invalid TLS Certificate",
                "severity": "Critical",
                "owasp_category": "A02:2021 — Cryptographic Failures",
                "location": url,
                "description": "The TLS certificate failed validation.",
                "evidence": f"TLS certificate validation failed. Version: {tls_info.get('tls_version', 'Unknown')}",
                "recommendation": "Install a valid TLS certificate from a trusted Certificate Authority.",
            })

        tls_ver = tls_info.get("tls_version", "")
        if tls_ver and ("TLSv1.0" in tls_ver or "TLSv1.1" in tls_ver or "SSLv" in tls_ver):
            findings.append({
                "title": f"Outdated TLS Version: {tls_ver}",
                "severity": "High",
                "owasp_category": "A02:2021 — Cryptographic Failures",
                "location": url,
                "description": f"The server uses {tls_ver}, which is deprecated and vulnerable.",
                "evidence": f"TLS negotiation returned version: {tls_ver}",
                "recommendation": "Upgrade to TLS 1.2 or TLS 1.3.",
            })

        return findings

    def _analyze_missing_headers(self, web_ctx: Dict) -> List[Dict]:
        findings = []
        missing = web_ctx.get("missing_security_headers", [])
        header_info = {
            "Content-Security-Policy": ("High", "A05:2021 — Security Misconfiguration", "No CSP header — browser has no restrictions on loading external resources, making XSS easier.", "Implement a strict CSP. Start with 'default-src self'."),
            "Strict-Transport-Security": ("High", "A02:2021 — Cryptographic Failures", "No HSTS — browsers may connect over HTTP, enabling SSL-stripping.", "Add 'Strict-Transport-Security: max-age=31536000; includeSubDomains'."),
            "X-Content-Type-Options": ("Medium", "A05:2021 — Security Misconfiguration", "No X-Content-Type-Options — browsers may MIME-sniff responses.", "Add 'X-Content-Type-Options: nosniff'."),
            "X-Frame-Options": ("Medium", "A05:2021 — Security Misconfiguration", "No X-Frame-Options — page can be embedded in iframes (clickjacking).", "Add 'X-Frame-Options: DENY' or 'SAMEORIGIN'."),
            "Referrer-Policy": ("Low", "A05:2021 — Security Misconfiguration", "No Referrer-Policy — may leak URL parameters to external sites.", "Add 'Referrer-Policy: strict-origin-when-cross-origin'."),
            "Permissions-Policy": ("Low", "A05:2021 — Security Misconfiguration", "No Permissions-Policy — browser features not explicitly restricted.", "Add Permissions-Policy to restrict features."),
            "X-XSS-Protection": ("Informational", "A05:2021 — Security Misconfiguration", "Legacy XSS protection not set.", "Add 'X-XSS-Protection: 1; mode=block' for older browsers."),
        }
        raw_snapshot = web_ctx.get("raw_headers_snapshot", "")
        first_header = True
        for h in missing:
            info = header_info.get(h)
            if info:
                finding = {
                    "title": f"Missing {h} Header",
                    "severity": info[0],
                    "owasp_category": info[1],
                    "location": "HTTP Response Headers",
                    "description": info[2],
                    "evidence": f"The '{h}' header was not present in the HTTP response.",
                    "recommendation": info[3],
                }
                if raw_snapshot and first_header:
                    finding["evidence_snapshot"] = {
                        "type": "http_headers",
                        "label": f"HTTP response headers — '{h}' is absent",
                        "response_headers": raw_snapshot,
                    }
                    first_header = False
                findings.append(finding)
        return findings

    def _analyze_cookies(self, web_ctx: Dict) -> List[Dict]:
        findings = []
        for cookie in web_ctx.get("cookies", []):
            if not cookie.get("secure"):
                findings.append({
                    "title": f"Cookie '{cookie['name']}' Missing Secure Flag",
                    "severity": "Medium",
                    "owasp_category": "A02:2021 — Cryptographic Failures",
                    "location": f"Cookie: {cookie['name']}",
                    "description": f"Cookie '{cookie['name']}' can be sent over unencrypted HTTP.",
                    "evidence": f"Set-Cookie for '{cookie['name']}' without Secure attribute.",
                    "recommendation": "Set the Secure flag on all cookies.",
                })
            if not cookie.get("httponly"):
                findings.append({
                    "title": f"Cookie '{cookie['name']}' Missing HttpOnly Flag",
                    "severity": "Medium",
                    "owasp_category": "A07:2021 — Identification and Authentication Failures",
                    "location": f"Cookie: {cookie['name']}",
                    "description": f"Cookie '{cookie['name']}' is accessible via JavaScript.",
                    "evidence": f"Set-Cookie for '{cookie['name']}' without HttpOnly attribute.",
                    "recommendation": "Set HttpOnly flag on session cookies.",
                })
        return findings

    def _analyze_cors(self, web_ctx: Dict) -> List[Dict]:
        findings = []
        cors = web_ctx.get("security_headers", {}).get("Access-Control-Allow-Origin")
        if cors == "*":
            finding = {
                "title": "Overly Permissive CORS Policy (Wildcard)",
                "severity": "High",
                "owasp_category": "A01:2021 — Broken Access Control",
                "location": "CORS Configuration",
                "description": "Server sends 'Access-Control-Allow-Origin: *', allowing any website to make cross-origin requests.",
                "evidence": "HTTP response contains 'Access-Control-Allow-Origin: *'.",
                "recommendation": "Restrict CORS to specific trusted origins.",
            }
            raw_snapshot = web_ctx.get("raw_headers_snapshot", "")
            if raw_snapshot:
                finding["evidence_snapshot"] = {
                    "type": "http_headers",
                    "label": "HTTP response shows wildcard CORS header",
                    "response_headers": raw_snapshot,
                }
            findings.append(finding)
        return findings

    def _analyze_forms_from_list(self, forms: List[Dict]) -> List[Dict]:
        findings = []
        for i, form in enumerate(forms, 1):
            if form.get("method") == "POST" and not form.get("has_csrf_token"):
                action = form.get("action", form.get("action_url", "(no action)"))
                page = form.get("page_url", "")
                findings.append({
                    "title": f"Form Missing CSRF Protection",
                    "severity": "Medium",
                    "owasp_category": "A01:2021 — Broken Access Control",
                    "location": f"POST form on {page or action}",
                    "description": f"A POST form (action='{action}') has no visible CSRF token, potentially vulnerable to CSRF attacks.",
                    "evidence": f"Form uses POST with {len(form.get('inputs', []))} inputs but no csrf/token input detected.",
                    "recommendation": "Add CSRF token protection to all state-changing forms.",
                })
        return findings

    def _llm_analyze(self, url: str, web_ctx: Dict, web_summary: str, all_forms: List, all_api_endpoints: List) -> List[Dict]:
        if not all_forms and not web_ctx.get("cookies") and not all_api_endpoints:
            return []

        owasp_checklist = get_owasp_checklist()

        prompt = f"""You are Shannon, an expert security analyst reviewing ACTUAL reconnaissance data.

## CRITICAL RULES
1. ONLY report vulnerabilities DIRECTLY evidenced by the data below.
2. If a data category is empty, do NOT report findings about it.
3. Every finding MUST cite specific evidence from the recon data.
4. Do NOT report: missing headers, TLS issues, CORS, server version — those are already handled.
5. Focus on: application-level logic issues, authentication concerns, information disclosure in comments/meta, insecure form patterns.

## Target: {url}

## Forms ({len(all_forms)} found)
{json.dumps(all_forms[:10], indent=2)}

## Cookies
{json.dumps(web_ctx.get('cookies', []), indent=2)}

## API Endpoints ({len(all_api_endpoints)} found)
{json.dumps(all_api_endpoints[:20], indent=2)}

## Technologies
{json.dumps(web_ctx.get('technologies', []), indent=2)}

## HTML Comments
{json.dumps(web_ctx.get('comments', []), indent=2)}

For each finding use EXACTLY this format:

### FINDING: [Title]
**Severity:** [Critical/High/Medium/Low/Informational]
**OWASP:** [e.g., A03:2021 - Injection]
**Location:** [Specific location]
**Description:** [Issue description]
**Evidence:** [EXACT data that proves this]
**Recommendation:** [Fix]

If no additional findings, respond: NO ADDITIONAL FINDINGS"""

        llm_response = self.ai_service.call_genai(prompt, temperature=0.2, max_tokens=4096)

        if "NO ADDITIONAL FINDINGS" in llm_response.upper():
            return []

        findings = parse_llm_findings(llm_response)
        for f in findings:
            if not f.get("owasp_category") or f["owasp_category"] == "N/A":
                owasp_key = map_finding_to_owasp(f.get("title", "") + " " + f.get("description", ""))
                cat = OWASP_TOP_10.get(owasp_key, {})
                f["owasp_category"] = f"{cat.get('id', '')} — {cat.get('name', '')}"
        return findings

    def _ask_about_findings(self, query: str, session: Dict) -> str:
        findings_text = ""
        if session.get("findings"):
            for i, f in enumerate(session["findings"], 1):
                findings_text += f"\n{i}. {f.get('title', '')} ({f.get('severity', '')}): {f.get('description', '')}\n   Evidence: {f.get('evidence', 'N/A')}\n"

        prompt = f"""You are Shannon, an expert AI security analyst. The user completed a deep security assessment and asks a follow-up.

Target URL: {session.get('url', 'N/A')}

Findings:
{findings_text}

User Question: {query}

Answer based only on the findings above. Do not introduce new speculative vulnerabilities."""

        try:
            return self.ai_service.call_genai(prompt, temperature=0.5, max_tokens=4096)
        except Exception as e:
            return f"Error processing question: {str(e)}"

    def _ask_llm_general(self, query: str) -> str:
        prompt = f"""You are Shannon, an AI security assessment agent inspired by the Shannon pentesting framework.

Your capabilities include deep scanning:
- Full site crawling (discovers all pages)
- Sensitive path discovery (.env, .git, /admin, API docs)
- Active injection testing (XSS, SQL injection payloads on forms)
- HTTP method probing (PUT, DELETE, TRACE)
- TLS/HTTPS verification
- Technology CVE lookup
- OWASP Top 10 analysis

User message: {query}

Respond helpfully. If no URL provided, ask for one."""

        try:
            return self.ai_service.call_genai(prompt, temperature=0.7, max_tokens=2048)
        except Exception as e:
            return f"Error: {str(e)}"

    def clear_session(self, session_id: str) -> Dict[str, Any]:
        if session_id in self.sessions:
            del self.sessions[session_id]
        return {"success": True, "message": "Session cleared"}


shannon_security_agent = ShannonSecurityAgent()
