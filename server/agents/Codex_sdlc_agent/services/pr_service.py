from __future__ import annotations

from typing import Any, Dict, List


def build_pr_payload(query: str, files_changed: List[str], validation_summary: Dict[str, Any]) -> Dict[str, Any]:
    quality = validation_summary.get("quality_gate", {})
    security = validation_summary.get("security_gate", {})
    coverage = validation_summary.get("coverage", {})
    tests = validation_summary.get("tests", {})
    summary_bits = []
    if files_changed:
        summary_bits.append(f"Updated {len(files_changed)} file(s)")
    if tests.get("status"):
        summary_bits.append(f"Tests: {tests['status']}")
    if coverage.get("coverage_pct") is not None:
        summary_bits.append(f"Coverage: {coverage['coverage_pct']}%")
    if security.get("status"):
        summary_bits.append(f"Security: {security['status']}")

    title = query.strip().splitlines()[0][:72] or "Repository improvements via Codex SDLC Agent"
    return {
        "title": title,
        "summary": "; ".join(summary_bits) or "Repository changes prepared.",
        "changes": files_changed,
        "risk": "Medium" if security.get("status") == "failed" else "Low to Medium",
        "test_evidence": tests.get("details", ""),
        "security_fixes": security.get("details", ""),
        "body": (
            f"## Summary\n{query.strip()}\n\n"
            f"## Files Changed\n" + ("\n".join(f"- `{p}`" for p in files_changed) if files_changed else "- No file list captured") + "\n\n"
            f"## Validation\n- Tests: {tests.get('status', 'skipped')}\n"
            f"- Coverage: {coverage.get('coverage_pct', 'n/a')}\n"
            f"- Security: {security.get('status', 'skipped')}\n"
        ),
    }

