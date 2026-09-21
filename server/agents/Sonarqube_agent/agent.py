"""Sonarqube Agent - Real SonarQube/SonarCloud integration with heuristic fallback.

Modes (auto-detected from user_config or environment):
  1. SonarCloud   – SONARCLOUD_TOKEN + optionally SONARCLOUD_ORGANIZATION
  2. Self-hosted  – SONARQUBE_HOST_URL + SONARQUBE_TOKEN
  3. Heuristic    – no credentials; local regex-based analysis (fallback)

For modes 1 & 2 the agent:
  a. Clones the repository.
  b. Writes sonar-project.properties and runs sonar-scanner (if available).
  c. Polls the background-task queue until analysis is ready.
  d. Fetches quality gate, measures, and issues via the REST API.
  e. Renders a report that mirrors the real SonarQube UI layout.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.GitHub_repo_agent.utils.git_utils import extract_repo_url

REPOS_DIR = Path(__file__).parent.parent.parent.parent / "repos"
REPOS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Heuristic constants (fallback mode)
# ---------------------------------------------------------------------------
_SECRET_PATTERNS = [
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9_\-]{12,}['\"]"),
    re.compile(r"(?i)secret\s*[:=]\s*['\"][A-Za-z0-9_\-]{8,}['\"]"),
    re.compile(r"(?i)password\s*[:=]\s*['\"][^'\"]{6,}['\"]"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
]

SOURCE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".rb",
    ".php", ".cs", ".cpp", ".c", ".h", ".hpp", ".swift", ".kt", ".scala",
    ".vue", ".svelte",
}

IGNORE_DIRS = {
    ".git", "node_modules", "dist", "build", "target", "bin", "obj",
    "coverage", "__pycache__", ".venv", "venv",
}

MAX_ISSUES = 160
MAX_FILES = 220
MAX_DUPLICATE_FINDINGS = 12

_PLACEHOLDER_SECRET_HINTS = {
    "example", "sample", "demo", "test", "changeme", "your_", "your-",
    "placeholder", "dummy", "mock", "xxx", "localhost", "127.0.0.1",
}

_LITERAL_VALUE_RE = re.compile(r"['\"]([^'\"]{4,})['\"]")

# SonarQube rating map (1.0=A … 5.0=E)
_RATING_MAP = {"1.0": "A", "2.0": "B", "3.0": "C", "4.0": "D", "5.0": "E"}


class SonarqubeAgent:
    def __init__(self):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        print("Sonarqube Agent initialized")

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "repo_url": None,
                "repo_path": None,
                "repo_name": None,
                "owner": None,
                "cloned": False,
            }
        return self.sessions[session_id]

    def clear_session(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # SonarQube / SonarCloud configuration resolution
    # ------------------------------------------------------------------

    def _get_sonar_config(self, user_config: Optional[Dict[str, str]]) -> Dict[str, Any]:
        """Return a config dict describing which integration mode to use."""
        cfg = user_config or {}

        sonarcloud_token = (cfg.get("SONARCLOUD_TOKEN") or os.getenv("SONARCLOUD_TOKEN", "")).strip()
        sonarcloud_org = (cfg.get("SONARCLOUD_ORGANIZATION") or os.getenv("SONARCLOUD_ORGANIZATION", "")).strip()

        sonarqube_url = (cfg.get("SONARQUBE_HOST_URL") or os.getenv("SONARQUBE_HOST_URL", "")).strip().rstrip("/")
        sonarqube_token = (cfg.get("SONARQUBE_TOKEN") or os.getenv("SONARQUBE_TOKEN", "")).strip()

        project_key_override = (cfg.get("SONARQUBE_PROJECT_KEY") or os.getenv("SONARQUBE_PROJECT_KEY", "")).strip()

        if sonarcloud_token:
            return {
                "mode": "sonarcloud",
                "base_url": "https://sonarcloud.io",
                "token": sonarcloud_token,
                "organization": sonarcloud_org or None,
                "project_key_override": project_key_override or None,
            }
        if sonarqube_url and sonarqube_token:
            return {
                "mode": "sonarqube",
                "base_url": sonarqube_url,
                "token": sonarqube_token,
                "organization": None,
                "project_key_override": project_key_override or None,
            }
        return {"mode": "heuristic"}

    def _make_project_key(self, owner: str, repo_name: str, sonar_config: Dict[str, Any]) -> str:
        override = sonar_config.get("project_key_override")
        if override:
            return override
        if sonar_config.get("mode") == "sonarcloud" and sonar_config.get("organization"):
            return f"{sonar_config['organization']}_{repo_name}"
        return f"{owner}_{repo_name}"

    # ------------------------------------------------------------------
    # SonarQube REST API helpers
    # ------------------------------------------------------------------

    def _sonar_api_get(self, base_url: str, token: str, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
        """Authenticated GET against SonarQube/SonarCloud REST API."""
        url = f"{base_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        credentials = base64.b64encode(f"{token}:".encode()).decode()
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            return {"_error": f"HTTP {exc.code}: {body[:300]}"}
        except Exception as exc:
            return {"_error": str(exc)}

    def _project_exists(self, base_url: str, token: str, project_key: str) -> bool:
        data = self._sonar_api_get(base_url, token, "/api/components/show", {"component": project_key})
        return "_error" not in data

    # ------------------------------------------------------------------
    # sonar-scanner execution
    # ------------------------------------------------------------------

    def _run_sonar_scanner(self, repo_path: str, project_key: str, sonar_config: Dict[str, Any]) -> Dict[str, Any]:
        """Write sonar-project.properties and run sonar-scanner CLI."""
        scanner_cmd: Optional[List[str]] = None
        for candidate in ["sonar-scanner", "sonar-scanner.bat"]:
            if shutil.which(candidate):
                scanner_cmd = [candidate]
                break
        if not scanner_cmd and shutil.which("npx"):
            scanner_cmd = ["npx", "sonarqube-scanner"]
        if not scanner_cmd:
            return {"success": False, "error": "sonar-scanner not found in PATH (install sonar-scanner or npx sonarqube-scanner)"}

        props_path = Path(repo_path) / "sonar-project.properties"
        lines = [
            f"sonar.projectKey={project_key}",
            "sonar.sources=.",
            f"sonar.host.url={sonar_config['base_url']}",
            f"sonar.token={sonar_config['token']}",
        ]
        if sonar_config.get("organization"):
            lines.append(f"sonar.organization={sonar_config['organization']}")
        props_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        try:
            result = subprocess.run(
                scanner_cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "sonar-scanner timed out after 600 s"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

        if result.returncode == 0:
            return {"success": True}
        err = (result.stderr or result.stdout or "scanner failed").strip()
        return {"success": False, "error": err[:1000]}

    def _wait_for_analysis(self, base_url: str, token: str, project_key: str, max_wait: int = 180) -> bool:
        """Poll /api/ce/component until the background analysis task finishes."""
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            data = self._sonar_api_get(base_url, token, "/api/ce/component", {"component": project_key})
            if "_error" in data:
                return False
            queue = data.get("queue", [])
            current = data.get("current", {})
            status = current.get("status", "")
            if not queue and status in ("SUCCESS", "FAILED", "CANCELLED", ""):
                return status in ("SUCCESS", "")
            time.sleep(5)
        return False

    # ------------------------------------------------------------------
    # Fetch full report from SonarQube/SonarCloud API
    # ------------------------------------------------------------------

    def _fetch_sonar_report(self, sonar_config: Dict[str, Any], project_key: str) -> Dict[str, Any]:
        base_url = sonar_config["base_url"]
        token = sonar_config["token"]

        qg_data = self._sonar_api_get(
            base_url, token, "/api/qualitygates/project_status", {"projectKey": project_key}
        )
        metric_keys = (
            "bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,"
            "ncloc,files,complexity,reliability_rating,security_rating,sqale_rating,"
            "security_hotspots,alert_status,sqale_index,"
            "reliability_remediation_effort,security_remediation_effort,"
            "new_bugs,new_vulnerabilities,new_code_smells,"
            "new_coverage,new_duplicated_lines_density"
        )
        measures_data = self._sonar_api_get(
            base_url, token, "/api/measures/component",
            {"component": project_key, "metricKeys": metric_keys},
        )
        issues_data = self._sonar_api_get(
            base_url, token, "/api/issues/search",
            {
                "componentKeys": project_key,
                "resolved": "false",
                "ps": "100",
                "p": "1",
                "s": "SEVERITY",
                "asc": "false",
            },
        )
        # Hotspots are a separate endpoint in newer SonarQube versions
        hotspots_data = self._sonar_api_get(
            base_url, token, "/api/hotspots/search",
            {"projectKey": project_key, "ps": "50"},
        )
        return {
            "quality_gate": qg_data,
            "measures": measures_data,
            "issues": issues_data,
            "hotspots": hotspots_data,
        }

    # ------------------------------------------------------------------
    # Build real SonarQube-style report from API data
    # ------------------------------------------------------------------

    def _build_real_report(
        self,
        repo_name: str,
        repo_url: str,
        project_key: str,
        sonar_data: Dict[str, Any],
        mode: str,
    ) -> str:
        # --- quality gate ---
        qg_root = sonar_data.get("quality_gate", {})
        project_status = qg_root.get("projectStatus", {})
        qg_status = project_status.get("status", "UNKNOWN")
        qg_conditions = project_status.get("conditions", [])

        # --- measures ---
        measures_raw = sonar_data.get("measures", {}).get("component", {}).get("measures", [])
        measures: Dict[str, str] = {m["metric"]: m.get("value", "") for m in measures_raw}

        # --- issues ---
        issues_payload = sonar_data.get("issues", {})
        issues: List[Dict[str, Any]] = issues_payload.get("issues", [])
        total_issues: int = issues_payload.get("total", len(issues))

        # --- hotspots ---
        hotspots: List[Dict[str, Any]] = sonar_data.get("hotspots", {}).get("hotspots", [])

        # helpers
        def rating(key: str) -> str:
            return _RATING_MAP.get(measures.get(key, ""), measures.get(key, "") or "—")

        def pct(key: str) -> str:
            v = measures.get(key, "")
            try:
                return f"{float(v):.1f}%"
            except (ValueError, TypeError):
                return v or "—"

        def num(key: str) -> str:
            v = measures.get(key, "")
            try:
                return f"{int(float(v)):,}"
            except (ValueError, TypeError):
                return v or "—"

        def minutes_to_human(v: str) -> str:
            try:
                m = int(float(v))
                if m < 60:
                    return f"{m} min"
                h = m // 60
                return f"{h}h {m % 60}min" if m % 60 else f"{h}h"
            except (ValueError, TypeError):
                return v or "—"

        # quality gate display
        qg_icon = "✅" if qg_status == "OK" else ("❌" if qg_status in ("ERROR", "WARN") else "⚠️")
        qg_label = "PASSED" if qg_status == "OK" else ("FAILED" if qg_status == "ERROR" else qg_status)

        # conditions table
        cond_rows: List[str] = []
        _METRIC_LABELS = {
            "new_reliability_rating": "Reliability Rating (new code)",
            "new_security_rating": "Security Rating (new code)",
            "new_maintainability_rating": "Maintainability Rating (new code)",
            "new_coverage": "Coverage (new code)",
            "new_duplicated_lines_density": "Duplications (new code)",
            "new_security_hotspots_reviewed": "Security Hotspots Reviewed (new code)",
            "reliability_rating": "Reliability Rating",
            "security_rating": "Security Rating",
            "sqale_rating": "Maintainability Rating",
            "coverage": "Coverage",
            "duplicated_lines_density": "Duplications",
            "bugs": "Bugs",
            "vulnerabilities": "Vulnerabilities",
            "code_smells": "Code Smells",
        }
        _COMPARATOR_LABELS = {"LT": "<", "GT": ">", "NE": "≠", "EQ": "="}
        for cond in qg_conditions:
            cst = cond.get("status", "")
            cst_icon = "✅" if cst == "OK" else "❌"
            metric = cond.get("metricKey", "")
            metric_label = _METRIC_LABELS.get(metric, metric)
            actual = cond.get("actualValue", "N/A")
            comparator = _COMPARATOR_LABELS.get(cond.get("comparator", ""), cond.get("comparator", ""))
            threshold = cond.get("errorThreshold", "N/A")
            cond_rows.append(f"| {metric_label} | {actual} | {comparator} {threshold} | {cst_icon} {cst} |")

        if cond_rows:
            conditions_section = (
                "| Condition | Actual | Threshold | Status |\n"
                "|-----------|--------|-----------|--------|\n"
                + "\n".join(cond_rows)
            )
        else:
            conditions_section = "_No quality gate conditions configured for this project._"

        # issue severity & type counts
        sev_counts = {"BLOCKER": 0, "CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "INFO": 0}
        type_counts = {"BUG": 0, "VULNERABILITY": 0, "CODE_SMELL": 0}
        for iss in issues:
            s = iss.get("severity", "INFO")
            t = iss.get("type", "CODE_SMELL")
            sev_counts[s] = sev_counts.get(s, 0) + 1
            type_counts[t] = type_counts.get(t, 0) + 1

        # top 25 issues
        top_issues = issues[:25]
        issue_lines: List[str] = []
        for iss in top_issues:
            comp = iss.get("component", "").split(":")[-1]
            line_no = iss.get("line", "")
            rule = iss.get("rule", "")
            msg = iss.get("message", "")
            sev = iss.get("severity", "")
            typ = iss.get("type", "")
            effort = iss.get("effort", "") or iss.get("debt", "")
            loc = f"{comp}:{line_no}" if line_no else comp
            effort_str = f" _(effort: {effort})_" if effort else ""
            issue_lines.append(f"- **[{sev}]** `{rule}` ({typ}) — `{loc}`{effort_str}\n  {msg}")

        if not issue_lines:
            issue_lines = ["_No unresolved issues found. Great job! 🎉_"]

        # security hotspots
        hotspot_lines: List[str] = []
        for hs in hotspots[:10]:
            comp = hs.get("component", "").split(":")[-1]
            line_no = hs.get("line", "")
            rule = hs.get("ruleKey", "")
            msg = hs.get("message", "")
            status = hs.get("status", "")
            loc = f"{comp}:{line_no}" if line_no else comp
            hotspot_lines.append(f"- **[{status}]** `{rule}` — `{loc}`\n  {msg}")

        hs_section = (
            "### Security Hotspots (top 10)\n\n" + "\n".join(hotspot_lines) + "\n\n"
            if hotspot_lines else ""
        )

        # technical debt
        debt_str = minutes_to_human(measures.get("sqale_index", ""))
        rel_effort_str = minutes_to_human(measures.get("reliability_remediation_effort", ""))
        sec_effort_str = minutes_to_human(measures.get("security_remediation_effort", ""))

        platform_label = "SonarCloud" if mode == "sonarcloud" else "SonarQube"
        dashboard_url = ""
        if mode == "sonarcloud":
            dashboard_url = f"\n- **Dashboard:** https://sonarcloud.io/project/overview?id={project_key}"

        return (
            f"## {platform_label} Analysis Report: {repo_name}\n\n"
            f"- **Repository:** {repo_url}\n"
            f"- **Project Key:** `{project_key}`"
            f"{dashboard_url}\n"
            f"- **Quality Gate:** {qg_icon} **{qg_label}**\n"
            f"- **Files scanned:** {num('files')}\n"
            f"- **Lines scanned:** {num('ncloc')}\n"
            f"- **Total issues:** {total_issues:,}\n\n"
            "---\n\n"
            "### Quality Gate Conditions\n\n"
            f"{conditions_section}\n\n"
            "---\n\n"
            "### Code Quality Metrics\n\n"
            "| Metric | Value | Rating |\n"
            "|--------|-------|--------|\n"
            f"| 🐛 Bugs | **{num('bugs')}** | **{rating('reliability_rating')}** |\n"
            f"| 🔒 Vulnerabilities | **{num('vulnerabilities')}** | **{rating('security_rating')}** |\n"
            f"| 🔥 Security Hotspots | **{num('security_hotspots')}** | — |\n"
            f"| 🔧 Code Smells | **{num('code_smells')}** | **{rating('sqale_rating')}** |\n"
            f"| 📊 Coverage | **{pct('coverage')}** | — |\n"
            f"| 🔁 Duplications | **{pct('duplicated_lines_density')}** | — |\n"
            f"| 📝 Lines of Code | **{num('ncloc')}** | — |\n"
            f"| 🔀 Cyclomatic Complexity | **{num('complexity')}** | — |\n\n"
            "### Technical Debt\n\n"
            f"| Debt Type | Effort |\n"
            f"|-----------|--------|\n"
            f"| Total Technical Debt | {debt_str} |\n"
            f"| Reliability Remediation | {rel_effort_str} |\n"
            f"| Security Remediation | {sec_effort_str} |\n\n"
            "---\n\n"
            "### Severity Breakdown\n\n"
            + "\n".join(f"- **{k}:** {sev_counts[k]}" for k in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"))
            + "\n\n### Issue Type Breakdown\n\n"
            + "\n".join(f"- **{k}:** {type_counts[k]}" for k in ("BUG", "VULNERABILITY", "CODE_SMELL"))
            + "\n\n### Issue Summary\n\n"
            "**By Severity:**\n\n"
            f"| Severity | Count |\n"
            f"|----------|-------|\n"
            f"| 🔴 BLOCKER | **{sev_counts['BLOCKER']}** |\n"
            f"| 🟠 CRITICAL | **{sev_counts['CRITICAL']}** |\n"
            f"| 🟡 MAJOR | **{sev_counts['MAJOR']}** |\n"
            f"| 🔵 MINOR | **{sev_counts['MINOR']}** |\n"
            f"| ⚪ INFO | **{sev_counts['INFO']}** |\n\n"
            "**By Type:**\n\n"
            f"| Type | Count |\n"
            f"|------|-------|\n"
            f"| 🐛 Bug | **{type_counts['BUG']}** |\n"
            f"| 🔒 Vulnerability | **{type_counts['VULNERABILITY']}** |\n"
            f"| 🔧 Code Smell | **{type_counts['CODE_SMELL']}** |\n\n"
            "---\n\n"
            f"### Top Findings\n\n_Showing top {len(top_issues)} of {total_issues:,}._\n\n"
            + "\n".join(issue_lines)
            + "\n\n"
            + hs_section
            + "---\n\n"
            f"_Report generated via {platform_label} REST API_\n"
        )

    # ------------------------------------------------------------------
    # Git clone (shared by all modes)
    # ------------------------------------------------------------------

    def _clone_repo(self, repo_url: str, session_id: str, github_token: Optional[str] = None) -> Dict[str, Any]:
        parts = repo_url.rstrip("/").split("/")
        if len(parts) < 2:
            return {"success": False, "error": "Invalid GitHub repository URL."}

        owner = parts[-2]
        repo_name = parts[-1].replace(".git", "")
        repo_dir = REPOS_DIR / session_id / f"{owner}_{repo_name}"
        if repo_dir.exists():
            shutil.rmtree(repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)

        token = (github_token or "").strip()
        candidates: List[str] = []

        if token and repo_url.startswith("https://"):
            candidates.append(repo_url.replace("https://", f"https://{token}@", 1))
            candidates.append(repo_url.replace("https://", f"https://x-access-token:{token}@", 1))

        candidates.append(repo_url + ".git" if not repo_url.endswith(".git") else repo_url)
        candidates.append(repo_url)

        last_err = ""
        for clone_url in candidates:
            try:
                result = subprocess.run(
                    ["git", "clone", "--depth", "50", clone_url, str(repo_dir)],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Clone timed out (>180s)."}
            except Exception as exc:
                last_err = str(exc)
                continue

            if result.returncode == 0:
                return {"success": True, "path": str(repo_dir), "name": repo_name, "owner": owner}

            err = (result.stderr or result.stdout or "Clone failed").strip()
            if token:
                err = err.replace(token, "***")
            last_err = err

        return {"success": False, "error": last_err or "Failed to clone repository."}

    # ------------------------------------------------------------------
    # Heuristic analysis (fallback when no SonarQube credentials)
    # ------------------------------------------------------------------

    def _iter_source_files(self, repo_path: Path):
        count = 0
        for fp in repo_path.rglob("*"):
            if any(part in IGNORE_DIRS for part in fp.parts):
                continue
            if not fp.is_file() or fp.suffix not in SOURCE_EXTS:
                continue
            count += 1
            if count > MAX_FILES:
                break
            yield fp

    def _severity_rank(self, sev: str) -> int:
        return {"BLOCKER": 0, "CRITICAL": 1, "MAJOR": 2, "MINOR": 3, "INFO": 4}.get(sev, 5)

    def _is_test_like_path(self, rel_path: str) -> bool:
        p = rel_path.lower()
        return any(
            token in p
            for token in (
                "/test", "/tests", "__tests__", ".spec.", ".test.",
                "playwright", "cypress", "automation_tests", "fixtures",
            )
        )

    def _looks_placeholder_secret_line(self, line: str) -> bool:
        lower = line.lower()
        if any(hint in lower for hint in _PLACEHOLDER_SECRET_HINTS):
            return True
        for raw in _LITERAL_VALUE_RE.findall(line):
            value = raw.strip().lower()
            if len(set(value)) <= 2:
                return True
            if any(h in value for h in _PLACEHOLDER_SECRET_HINTS):
                return True
        return False

    def _is_eligible_duplicate_line(self, stripped_line: str) -> bool:
        if len(stripped_line) < 70:
            return False
        if stripped_line.startswith(("#", "//", "/*", "*", "import ", "from ", "export ")):
            return False
        if stripped_line.startswith(("const ", "let ", "var ", "class ", "function ", "router.", "app.")):
            return False
        if re.fullmatch(r"[{}()\[\],.;:+\-*/=<>!&|\s]+", stripped_line):
            return False
        if stripped_line.count("<") >= 2 and stripped_line.count(">") >= 2:
            return False
        return True

    def _analyze_repo(self, repo_path: str) -> Dict[str, Any]:
        """Heuristic static analysis fallback."""
        root = Path(repo_path)
        issues: List[Dict[str, Any]] = []
        duplicate_index: Dict[str, List[tuple]] = {}
        total_files = 0
        total_lines = 0

        for fp in self._iter_source_files(root):
            rel = str(fp.relative_to(root)).replace("\\", "/")
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            total_files += 1
            lines = text.splitlines()
            total_lines += len(lines)

            for idx, line in enumerate(lines, start=1):
                stripped = line.strip()
                low = stripped.lower()

                if len(issues) >= MAX_ISSUES:
                    break

                if "eval(" in stripped or "exec(" in stripped:
                    issues.append({"severity": "CRITICAL", "type": "VULNERABILITY", "rule": "squid:S1523",
                                   "message": "Dynamic execution (eval/exec) can lead to code injection.", "file": rel, "line": idx})

                if "except:" in stripped and fp.suffix == ".py":
                    issues.append({"severity": "MAJOR", "type": "CODE_SMELL", "rule": "python:S5714",
                                   "message": "Catch specific exceptions instead of a bare except.", "file": rel, "line": idx})

                if "console.log(" in stripped and fp.suffix in {".js", ".ts", ".jsx", ".tsx"}:
                    issues.append({"severity": "MINOR", "type": "CODE_SMELL", "rule": "javascript:S2228",
                                   "message": "Remove debug console.log from production code.", "file": rel, "line": idx})

                if "todo" in low or "fixme" in low:
                    issues.append({"severity": "INFO", "type": "CODE_SMELL", "rule": "common-java:InsufficientCommentDensity",
                                   "message": "Pending TODO/FIXME comment should be tracked.", "file": rel, "line": idx})

                if len(line) > 140:
                    issues.append({"severity": "MINOR", "type": "CODE_SMELL", "rule": "common-py:LineLength",
                                   "message": "Line exceeds 140 characters.", "file": rel, "line": idx})

                for secret_re in _SECRET_PATTERNS:
                    if secret_re.search(line):
                        if self._looks_placeholder_secret_line(line):
                            break
                        is_test = self._is_test_like_path(rel)
                        issues.append({
                            "severity": "MAJOR" if is_test else "BLOCKER",
                            "type": "CODE_SMELL" if is_test else "VULNERABILITY",
                            "rule": "secrets:S6290",
                            "message": (
                                "Potential hardcoded secret in test code — prefer fixtures or env vars."
                                if is_test else
                                "Hardcoded secret/credential detected. Move to environment variable."
                            ),
                            "file": rel,
                            "line": idx,
                        })
                        break

                if self._is_eligible_duplicate_line(stripped):
                    sig = " ".join(stripped.split())
                    duplicate_index.setdefault(sig, []).append((rel, idx))

            if len(issues) >= MAX_ISSUES:
                break

        dup_found = 0
        for _line_text, locations in sorted(duplicate_index.items(), key=lambda i: len(i[1]), reverse=True):
            if len(issues) >= MAX_ISSUES or dup_found >= MAX_DUPLICATE_FINDINGS:
                break
            n = len(locations)
            fc = len({f for f, _ in locations})
            if n >= 6 and fc >= 2:
                f0, l0 = locations[0]
                issues.append({"severity": "MAJOR", "type": "CODE_SMELL", "rule": "common:DuplicatedBlocks",
                               "message": f"Logic block repeated {n}× across {fc} files.", "file": f0, "line": l0})
                dup_found += 1

        counts = {"BLOCKER": 0, "CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "INFO": 0}
        by_type = {"BUG": 0, "VULNERABILITY": 0, "CODE_SMELL": 0}
        for iss in issues:
            counts[iss["severity"]] = counts.get(iss["severity"], 0) + 1
            by_type[iss["type"]] = by_type.get(iss["type"], 0) + 1

        strict = (os.getenv("SONARQUBE_STRICT_FAIL_ON_MAJOR", "true").lower() in {"1", "true", "yes", "y", "on"})
        if counts["BLOCKER"] > 0 or counts["CRITICAL"] > 3 or (strict and counts["MAJOR"] > 0):
            quality_gate = "FAILED"
        elif counts["MAJOR"] > 12:
            quality_gate = "WARN"
        else:
            quality_gate = "PASSED"

        issues_sorted = sorted(
            issues,
            key=lambda x: (self._severity_rank(x.get("severity", "INFO")), x.get("file", ""), int(x.get("line", 0))),
        )
        return {
            "total_files": total_files, "total_lines": total_lines,
            "issues": issues_sorted, "severity_counts": counts,
            "type_counts": by_type, "quality_gate": quality_gate,
        }

    def _build_heuristic_report(self, repo_name: str, repo_url: str, analysis: Dict[str, Any], note: Optional[str] = None) -> str:
        """Render heuristic analysis in SonarQube report layout."""
        sev = analysis["severity_counts"]
        typ = analysis["type_counts"]
        issues = analysis["issues"]
        qg = analysis["quality_gate"]
        qg_icon = "✅" if qg == "PASSED" else ("⚠️" if qg == "WARN" else "❌")

        top_lines: List[str] = []
        for iss in issues[:25]:
            rule = iss.get("rule", "")
            msg = iss.get("message", "")
            effort = iss.get("effort", "")
            effort_str = f" _(effort: {effort})_" if effort else ""
            top_lines.append(
                f"- **[{iss['severity']}]** `{rule}` ({iss['type']}) — `{iss['file']}:{iss['line']}`{effort_str}\n  {msg}"
            )
        if not top_lines:
            top_lines = ["_No issues detected._"]

        severity_bullets = "\n".join(f"- **{k}:** {sev[k]}" for k in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"))
        type_bullets = "\n".join(f"- **{k}:** {typ[k]}" for k in ("BUG", "VULNERABILITY", "CODE_SMELL"))

        return (
            f"## SonarQube Analysis Report: {repo_name}\n\n"
            f"- **Repository:** {repo_url}\n"
            f"- **Quality Gate:** {qg_icon} **{qg}**\n"
            f"- **Files scanned:** {analysis['total_files']}\n"
            f"- **Lines scanned:** {analysis['total_lines']:,}\n"
            f"- **Total issues:** {len(issues)}\n\n"
            "---\n\n"
            + (
                f"> ℹ️ **Note:** {note}\n\n"
                if note else
                "> ⚠️ **Note:** Running in **heuristic mode** (no SonarQube/SonarCloud credentials). "
                "For exact SonarQube results, provide `SONARCLOUD_TOKEN` or `SONARQUBE_HOST_URL` + `SONARQUBE_TOKEN` in your configuration.\n\n"
            )
            + "---\n\n"
            "### Severity Breakdown\n\n"
            f"{severity_bullets}\n\n"
            "### Issue Type Breakdown\n\n"
            f"{type_bullets}\n\n"
            "### Code Quality Metrics\n\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            f"| 🐛 Bugs | **{typ['BUG']}** |\n"
            f"| 🔒 Vulnerabilities | **{typ['VULNERABILITY']}** |\n"
            f"| 🔧 Code Smells | **{typ['CODE_SMELL']}** |\n"
            f"| 📝 Files Scanned | **{analysis['total_files']}** |\n\n"
            "### Issue Summary\n\n"
            "**By Severity:**\n\n"
            "| Severity | Count |\n"
            "|----------|-------|\n"
            f"| 🔴 BLOCKER | **{sev['BLOCKER']}** |\n"
            f"| 🟠 CRITICAL | **{sev['CRITICAL']}** |\n"
            f"| 🟡 MAJOR | **{sev['MAJOR']}** |\n"
            f"| 🔵 MINOR | **{sev['MINOR']}** |\n"
            f"| ⚪ INFO | **{sev['INFO']}** |\n\n"
            "---\n\n"
            f"### Top Findings\n\n_Showing top {min(25, len(issues))} of {len(issues)}._\n\n"
            + "\n".join(top_lines)
            + "\n\n---\n\n"
            "### Recommended Actions\n\n"
            "1. Fix BLOCKER/CRITICAL findings first (secrets and dynamic execution).\n"
            "2. Connect to SonarCloud or self-hosted SonarQube for full, accurate analysis.\n"
            "3. Enforce Quality Gate on every pull request via CI.\n"
            "4. Resolve MAJOR code smells and enable team linting rules.\n"
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def process_query(
        self,
        query: str,
        session_id: str = "default",
        github_token: Optional[str] = None,
        user_config: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        session = self._get_session(session_id)
        thinking_steps: List[Dict[str, Any]] = []
        sonar_config = self._get_sonar_config(user_config)

        # --- clone if a new URL is detected ---
        repo_url = extract_repo_url(query)
        if repo_url and (not session.get("cloned") or repo_url != session.get("repo_url")):
            thinking_steps.append({"type": "tool_call", "content": f"Cloning repository: {repo_url}", "tool_name": "clone_repo"})
            clone_result = self._clone_repo(repo_url, session_id, github_token=github_token)
            if not clone_result.get("success"):
                err = clone_result.get("error", "Failed to clone repository")
                auth_related = any(k in err.lower() for k in ["authentication", "403", "401", "permission denied"])
                if not github_token and auth_related:
                    return {
                        "success": True,
                        "response": (
                            "I could not access that repository anonymously. "
                            "Please provide a GitHub token (repo scope) and try again."
                        ),
                        "thinking_steps": thinking_steps,
                        "requires_token": True,
                        "repo_url": repo_url,
                    }
                return {"success": False, "response": f"Failed to clone repository: {err}",
                        "thinking_steps": thinking_steps, "repo_url": repo_url}

            session["repo_url"] = repo_url
            session["repo_path"] = clone_result["path"]
            session["repo_name"] = clone_result["name"]
            session["owner"] = clone_result["owner"]
            session["cloned"] = True
            thinking_steps.append({"type": "tool_result", "content": "Repository cloned successfully", "tool_name": "clone_repo"})

        if not session.get("cloned"):
            return {
                "success": False,
                "response": (
                    "Please provide a GitHub repository URL. Example:\n\n"
                    "`Analyze https://github.com/owner/repo with SonarQube`"
                ),
                "thinking_steps": thinking_steps,
            }

        mode = sonar_config.get("mode", "heuristic")
        owner = session.get("owner", "unknown")
        repo_name = session.get("repo_name", "repository")
        repo_path = session.get("repo_path", "")

        # ---------------------------------------------------------------
        # Mode A: Real SonarQube / SonarCloud integration
        # ---------------------------------------------------------------
        if mode in ("sonarcloud", "sonarqube"):
            project_key = self._make_project_key(owner, repo_name, sonar_config)
            base_url = sonar_config["base_url"]
            token = sonar_config["token"]
            platform = "SonarCloud" if mode == "sonarcloud" else "SonarQube"

            thinking_steps.append({
                "type": "tool_call",
                "content": f"Connecting to {platform} — project key: {project_key}",
                "tool_name": "sonar_api",
            })

            # Try to run sonar-scanner (best-effort; skip if unavailable)
            scanner_result = self._run_sonar_scanner(repo_path, project_key, sonar_config)
            scanner_ran = scanner_result.get("success", False)
            if scanner_ran:
                thinking_steps.append({"type": "tool_result",
                                        "content": "sonar-scanner completed. Waiting for analysis...",
                                        "tool_name": "sonar_scanner"})
                self._wait_for_analysis(base_url, token, project_key)
            else:
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"sonar-scanner skipped ({scanner_result.get('error', 'unavailable')}). Fetching existing analysis.",
                    "tool_name": "sonar_scanner",
                })

            # Check project exists; if not (and scanner didn't just run), fall back to heuristic
            if not self._project_exists(base_url, token, project_key):
                fallback_reason = (
                    f"`sonar-scanner` is not installed on this server, so the project could not be submitted to {platform}. "
                    "The repository has been cloned and analyzed locally using static heuristic checks. "
                    f"To get official {platform} results, install `sonar-scanner` CLI and ensure the project `{project_key}` is registered."
                )
                thinking_steps.append({
                    "type": "tool_result",
                    "content": (
                        f"Project `{project_key}` not found on {platform} — "
                        "sonar-scanner not available. Running local heuristic analysis on cloned repository."
                    ),
                    "tool_name": "sonar_api",
                })
                # ---- heuristic fallback ----
                analysis = self._analyze_repo(repo_path)
                report = self._build_heuristic_report(
                    repo_name=repo_name,
                    repo_url=session.get("repo_url", ""),
                    analysis=analysis,
                    note=fallback_reason,
                )
                return {"success": True, "response": report, "thinking_steps": thinking_steps,
                        "repo_url": session.get("repo_url"), "requires_token": False}

            # Fetch full report data
            thinking_steps.append({"type": "tool_call", "content": "Fetching quality gate, measures and issues from API",
                                    "tool_name": "sonar_api"})
            sonar_data = self._fetch_sonar_report(sonar_config, project_key)

            qg_root = sonar_data.get("quality_gate", {})
            if "_error" in qg_root:
                return {
                    "success": False,
                    "response": f"Failed to fetch {platform} data: {qg_root['_error']}",
                    "thinking_steps": thinking_steps,
                    "repo_url": repo_url,
                }

            n_issues = sonar_data.get("issues", {}).get("total", 0)
            thinking_steps.append({
                "type": "tool_result",
                "content": f"Fetched {platform} data: {n_issues} issues found.",
                "tool_name": "sonar_api",
            })

            report = self._build_real_report(
                repo_name=repo_name,
                repo_url=session.get("repo_url", ""),
                project_key=project_key,
                sonar_data=sonar_data,
                mode=mode,
            )
            return {"success": True, "response": report, "thinking_steps": thinking_steps,
                    "repo_url": session.get("repo_url"), "requires_token": False}

        # ---------------------------------------------------------------
        # Mode B: Heuristic fallback
        # ---------------------------------------------------------------
        thinking_steps.append({"type": "tool_call", "content": "Running heuristic static analysis...",
                                "tool_name": "static_analysis"})
        analysis = self._analyze_repo(repo_path)
        thinking_steps.append({
            "type": "tool_result",
            "content": (
                f"Analysis complete: {len(analysis['issues'])} issues across "
                f"{analysis['total_files']} files. Quality Gate: {analysis['quality_gate']}"
            ),
            "tool_name": "static_analysis",
        })
        report = self._build_heuristic_report(
            repo_name=repo_name,
            repo_url=session.get("repo_url", ""),
            analysis=analysis,
        )
        return {"success": True, "response": report, "thinking_steps": thinking_steps,
                "repo_url": session.get("repo_url"), "requires_token": False}


sonarqube_agent = SonarqubeAgent()
