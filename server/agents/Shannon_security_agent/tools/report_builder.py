from typing import Dict, Any, List
from datetime import datetime


def build_security_report(
    url: str,
    findings: List[Dict[str, Any]],
    web_summary: str,
    repo_summary: str = "",
    assessment_status: str = "COMPLETE",
    recon_error: str = "",
    scan_stats: Dict[str, Any] = None,
) -> str:
    now = datetime.now().strftime("%B %d, %Y at %H:%M UTC")

    severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Informational": 4}
    findings_sorted = sorted(findings, key=lambda f: severity_order.get(f.get("severity", "Low"), 3))

    critical = sum(1 for f in findings if f.get("severity") == "Critical")
    high = sum(1 for f in findings if f.get("severity") == "High")
    medium = sum(1 for f in findings if f.get("severity") == "Medium")
    low = sum(1 for f in findings if f.get("severity") == "Low")
    info = sum(1 for f in findings if f.get("severity") == "Informational")
    total = len(findings)

    if assessment_status == "INCONCLUSIVE":
        overall_risk = "INCONCLUSIVE"
        risk_icon = "⚠️"
    elif critical > 0:
        overall_risk = "CRITICAL"
        risk_icon = "🔴"
    elif high > 0:
        overall_risk = "HIGH"
        risk_icon = "🟠"
    elif medium > 0:
        overall_risk = "MEDIUM"
        risk_icon = "🟡"
    elif low > 0:
        overall_risk = "LOW"
        risk_icon = "🔵"
    else:
        overall_risk = "PASS"
        risk_icon = "🟢"

    analysis_type = "White-box (Source + Dynamic)" if repo_summary else "Black-box (Dynamic Only)"

    lines = [
        f"# 🛡️ Security Assessment Report",
        "",
        f"> {risk_icon} **Overall Risk: {overall_risk}** — {total} findings identified across {_count_categories(critical, high, medium, low, info)}",
        "",
        f"| | |",
        f"|---|---|",
        f"| **Target** | `{url}` |",
        f"| **Date** | {now} |",
        f"| **Status** | {assessment_status} |",
        f"| **Scan Type** | {analysis_type} |",
        "",
    ]

    if assessment_status == "INCONCLUSIVE":
        lines.extend(_build_inconclusive_section(url, recon_error))

    lines.extend(_build_risk_overview(critical, high, medium, low, info, total))

    if scan_stats:
        lines.extend(_build_scan_coverage(scan_stats))

    if findings_sorted:
        lines.extend(_build_findings_section(findings_sorted))
    else:
        lines.extend([
            "---",
            "",
            "## Detailed Findings",
            "",
            "> 🟢 **No vulnerabilities identified.** This does not guarantee the application is secure.",
            "> A manual penetration test is recommended for comprehensive coverage.",
            "",
        ])

    if web_summary:
        lines.extend([
            "---",
            "",
            "## 🔍 Reconnaissance Data",
            "",
            web_summary,
            "",
        ])

    if repo_summary:
        lines.extend([
            "---",
            "",
            "## 📂 Source Code Analysis",
            "",
            repo_summary,
            "",
        ])

    lines.extend(_build_methodology_section())

    lines.extend([
        "",
        "> **Evidence Policy:** All findings are backed by data collected during active scanning. "
        "No speculative or assumed vulnerabilities are included. This agent performs active probing "
        "with safe, non-destructive payloads — it does not execute live exploits or attempt data exfiltration.",
    ])

    return "\n".join(lines)


def _count_categories(critical, high, medium, low, info):
    parts = []
    if critical:
        parts.append(f"{critical} critical")
    if high:
        parts.append(f"{high} high")
    if medium:
        parts.append(f"{medium} medium")
    if low:
        parts.append(f"{low} low")
    if info:
        parts.append(f"{info} informational")
    return ", ".join(parts) if parts else "0 severity categories"


def _build_inconclusive_section(url, recon_error):
    lines = [
        "---",
        "",
        "## ⚠️ Assessment Limitations",
        "",
        f"> **Reconnaissance failed.** The target `{url}` could not be fully accessed.",
    ]
    if recon_error:
        lines.append(f"> **Error:** `{recon_error}`")
    lines.extend([
        "",
        "Only TLS/HTTPS checks could be performed. Next steps:",
        "- Verify the URL is correct and publicly accessible",
        "- Check if the server is running and responding",
        "- Try again later or consider a manual penetration test",
        "",
    ])
    return lines


def _build_risk_overview(critical, high, medium, low, info, total):
    lines = [
        "---",
        "",
        "## Risk Overview",
        "",
    ]

    if total == 0:
        lines.extend([
            "No findings to display.",
            "",
        ])
        return lines

    bar_total = 30
    counts = [
        ("🔴 Critical", critical, "█"),
        ("🟠 High", high, "█"),
        ("🟡 Medium", medium, "█"),
        ("🔵 Low", low, "█"),
        ("⚪ Info", info, "░"),
    ]

    lines.append("| Severity | Count | Distribution |")
    lines.append("|----------|------:|--------------|")

    for label, count, block_char in counts:
        if total > 0:
            bar_len = max(0, round((count / total) * bar_total))
        else:
            bar_len = 0
        bar = block_char * bar_len
        pct = round((count / total) * 100) if total > 0 else 0
        lines.append(f"| {label} | **{count}** | `{bar}` {pct}% |")

    lines.append("")
    return lines


def _build_scan_coverage(scan_stats):
    pages = scan_stats.get("pages_crawled", 0)
    paths = scan_stats.get("paths_checked", 0)
    forms = scan_stats.get("forms_tested", 0)
    payloads = scan_stats.get("payloads_sent", 0)
    methods = scan_stats.get("methods_probed", 0)

    lines = [
        "",
        f"**Scan Coverage:** "
        f"🌐 {pages} pages crawled · "
        f"📁 {paths} paths probed · "
        f"📝 {forms} forms tested · "
        f"💉 {payloads} payloads sent · "
        f"🔧 {methods} methods checked",
        "",
    ]
    return lines


def _build_findings_section(findings_sorted):
    lines = [
        "---",
        "",
        "## Detailed Findings",
        "",
    ]

    severity_style = {
        "Critical": ("🔴", "CRITICAL"),
        "High": ("🟠", "HIGH"),
        "Medium": ("🟡", "MEDIUM"),
        "Low": ("🔵", "LOW"),
        "Informational": ("⚪", "INFO"),
    }

    for i, finding in enumerate(findings_sorted, 1):
        severity = finding.get("severity", "Low")
        icon, badge = severity_style.get(severity, ("⚪", "INFO"))

        lines.extend([
            f"### {icon} #{i} — {finding.get('title', 'Untitled')}",
            "",
            f"**`{badge}`** · {finding.get('owasp_category', 'N/A')}",
            "",
            f"**Location:** `{finding.get('location', 'N/A')}`",
            "",
            finding.get("description", "No description provided."),
            "",
        ])

        evidence = finding.get("evidence", "")
        if evidence:
            lines.extend([
                f"**Evidence:** {evidence}",
                "",
            ])

        snapshot = finding.get("evidence_snapshot")
        if snapshot:
            lines.extend(_render_evidence_snapshot(snapshot))
            lines.append("")

        recommendation = finding.get("recommendation", "")
        if recommendation:
            lines.extend([
                f"> 💡 **Remediation:** {recommendation}",
                "",
            ])

        lines.extend([
            "---",
            "",
        ])

    return lines


def _render_evidence_snapshot(snapshot: Dict[str, Any]) -> List[str]:
    lines = []
    snap_type = snapshot.get("type", "")
    label = snapshot.get("label", "Evidence Snapshot")

    lines.append(f"**📸 Evidence Snapshot** — _{label}_")
    lines.append("")

    if snap_type == "http_response":
        request_info = snapshot.get("request", "")
        status = snapshot.get("response_status", "")
        snippet = snapshot.get("response_snippet", "")

        if request_info:
            lines.append("```")
            lines.append(f"→ REQUEST")
            lines.append(request_info)
            lines.append("```")
            lines.append("")

        if snippet:
            lines.append(f"```")
            lines.append(f"← RESPONSE [{status}]")
            lines.append(snippet)
            lines.append("```")

    elif snap_type == "exposed_path":
        request_info = snapshot.get("request", "")
        status = snapshot.get("response_status", "")
        headers = snapshot.get("response_headers", "")
        body = snapshot.get("response_body_preview", "")

        content = []
        if request_info:
            content.append(f"→ REQUEST")
            content.append(request_info)
            content.append("")
        if headers:
            content.append(f"← RESPONSE HEADERS [{status}]")
            content.append(headers)
            content.append("")
        if body:
            content.append(f"← RESPONSE BODY")
            content.append(body[:400])

        if content:
            lines.append("```")
            lines.extend(content)
            lines.append("```")

    elif snap_type == "http_headers":
        headers = snapshot.get("response_headers", "")
        if headers:
            header_lines = headers.split("\n")[:20]
            lines.append("```")
            lines.append("← RESPONSE HEADERS")
            lines.extend(header_lines)
            if headers.count("\n") > 20:
                lines.append("... (truncated)")
            lines.append("```")

    else:
        raw = snapshot.get("raw", snapshot.get("data", ""))
        if raw:
            lines.append("```")
            lines.append(str(raw)[:500])
            lines.append("```")

    return lines


def _build_methodology_section():
    lines = [
        "---",
        "",
        "## Methodology",
        "",
        "Powered by **Shannon Security Agent**, inspired by the "
        "[Shannon autonomous pentesting framework](https://github.com/KeygraphHQ/shannon).",
        "",
        "| Phase | Description |",
        "|-------|-------------|",
        "| 1. Pre-Recon | Target validation and scope definition |",
        "| 2. Initial Recon | Homepage fetch, headers, TLS/HTTPS verification |",
        "| 3. Crawling | BFS site crawl to discover pages and forms |",
        "| 4. Path Discovery | Probing for exposed files, admin panels, backups |",
        "| 5. Injection Testing | Safe XSS and SQL injection payloads on forms |",
        "| 6. Method Probing | Testing dangerous HTTP methods (PUT, DELETE, TRACE) |",
        "| 7. CVE Lookup | Matching technology versions to known vulnerabilities |",
        "| 8. AI Analysis | LLM review of evidence for additional findings |",
        "| 9. Reporting | Consolidated findings with severity and evidence |",
        "",
    ]
    return lines


def parse_llm_findings(llm_response: str) -> List[Dict[str, Any]]:
    findings = []
    current = None
    current_field = None

    for line in llm_response.split("\n"):
        stripped = line.strip()

        if stripped.startswith("### FINDING"):
            if current:
                findings.append(current)
            current = {
                "title": stripped.replace("### FINDING:", "").replace("### FINDING", "").strip().strip(":").strip(),
                "severity": "Medium",
                "owasp_category": "",
                "location": "",
                "description": "",
                "evidence": "",
                "recommendation": "",
            }
            current_field = None
        elif current:
            if stripped.startswith("**Severity:**") or stripped.startswith("Severity:"):
                current["severity"] = stripped.split(":", 1)[1].strip().strip("*").strip()
                current_field = None
            elif stripped.startswith("**OWASP:**") or stripped.startswith("OWASP:"):
                current["owasp_category"] = stripped.split(":", 1)[1].strip().strip("*").strip()
                current_field = None
            elif stripped.startswith("**Location:**") or stripped.startswith("Location:"):
                current["location"] = stripped.split(":", 1)[1].strip().strip("*").strip()
                current_field = None
            elif stripped.startswith("**Description:**") or stripped.startswith("Description:"):
                desc_val = stripped.split(":", 1)[1].strip().strip("*").strip()
                current["description"] = desc_val
                current_field = "description"
            elif stripped.startswith("**Evidence:**") or stripped.startswith("Evidence:"):
                ev_val = stripped.split(":", 1)[1].strip().strip("*").strip()
                current["evidence"] = ev_val
                current_field = "evidence"
            elif stripped.startswith("**Recommendation:**") or stripped.startswith("Recommendation:"):
                rec_val = stripped.split(":", 1)[1].strip().strip("*").strip()
                current["recommendation"] = rec_val
                current_field = "recommendation"
            elif current_field and stripped:
                current[current_field] += "\n" + stripped

    if current:
        findings.append(current)

    return findings
