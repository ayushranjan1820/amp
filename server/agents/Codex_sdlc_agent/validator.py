from __future__ import annotations

from .models import ExecutionResult, PlanStep, RunState, ValidationResult
from .services.coverage_service import run_coverage
from .services.security_service import run_security_checks
from .services.test_service import run_lint, run_tests


def validate_step(step: PlanStep, state: RunState, execution: ExecutionResult) -> ValidationResult:
    checks = []
    metrics = {}

    if step.validator_profile == "analysis":
        return ValidationResult(
            success=True,
            summary="Analysis step does not require execution gates.",
            checks=[{"name": "analysis", "status": "passed", "details": "Analysis completed."}],
        )

    if step.validator_profile == "documentation":
        status = "passed" if execution.success else "failed"
        return ValidationResult(
            success=execution.success,
            summary="Documentation step completed." if execution.success else "Documentation step failed.",
            checks=[{"name": "documentation", "status": status, "details": execution.response[:1000]}],
        )

    tests = run_tests(state.workspace_root)
    checks.append({"name": "tests", "status": tests["status"], "details": tests.get("details", "")})
    metrics["tests"] = tests

    lint = run_lint(state.workspace_root)
    checks.append({"name": "lint", "status": lint["status"], "details": lint.get("details", "")})
    metrics["lint"] = lint

    coverage = run_coverage(state.workspace_root)
    checks.append({"name": "coverage", "status": coverage["status"], "details": coverage.get("details", "")})
    metrics["coverage"] = coverage

    if step.validator_profile == "security_gate" or step.kind == "security_check":
        security = run_security_checks(state.workspace_root)
        checks.append({"name": "security", "status": security["status"], "details": security.get("details", "")})
        metrics["security"] = security

    failed = [c for c in checks if c["status"] == "failed"]
    skipped = [c for c in checks if c["status"] == "skipped"]
    summary = f"{len(checks) - len(failed) - len(skipped)} passed, {len(failed)} failed, {len(skipped)} skipped."
    return ValidationResult(
        success=len(failed) == 0,
        summary=summary,
        checks=checks,
        metrics=metrics,
    )

