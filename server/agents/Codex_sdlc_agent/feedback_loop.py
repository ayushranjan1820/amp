from __future__ import annotations

from .models import ExecutionResult, PlanStep, ValidationResult


def build_retry_prompt(step: PlanStep, execution: ExecutionResult, validation: ValidationResult) -> str:
    findings = "\n".join(
        f"- {check.get('name')}: {check.get('status')} ({check.get('details', '')})"
        for check in validation.checks
    ) or "- Validation failed without structured findings."
    return (
        f"{step.prompt}\n\n"
        "Your previous attempt did not satisfy validation.\n\n"
        f"Previous result summary:\n{execution.response[:2500]}\n\n"
        f"Validator findings:\n{findings}\n\n"
        "Retry the step by making the smallest corrective change necessary. "
        "Do not restate the plan; focus on producing the fix."
    )

