from __future__ import annotations

from typing import List, Optional

from .models import PlanStep


def _has_any(text: str, words: list[str]) -> bool:
    lower = text.lower()
    return any(w in lower for w in words)


def build_plan(
    query: str,
    target_coverage: Optional[int] = None,
    create_pr: bool = False,
    max_retries: int = 2,
) -> List[PlanStep]:
    lower = query.lower()
    steps: List[PlanStep] = [
        PlanStep(
            step_id="analyze_repo",
            kind="analyze",
            title="Analyze repository context",
            prompt=(
                "Analyze the repository structure, dominant architecture, likely testing setup, "
                "and the smallest safe path to accomplish the user goal."
            ),
            validator_profile="analysis",
            max_retries=1,
        )
    ]

    if _has_any(lower, ["coverage", "test", "unit test"]):
        coverage_target = target_coverage or 85
        steps.append(
            PlanStep(
                step_id="increase_test_coverage",
                kind="test_coverage",
                title="Increase test coverage",
                prompt=(
                    f"Act as a senior test engineer. Increase coverage toward {coverage_target}%. "
                    "Prefer targeted tests for critical paths. Do not change production logic unless required to unblock tests."
                ),
                validator_profile="quality_gate",
                metadata={"target_coverage": coverage_target},
                max_retries=max_retries,
            )
        )

    if _has_any(lower, ["bug", "fix", "failure", "error", "stack trace"]):
        steps.append(
            PlanStep(
                step_id="fix_bug",
                kind="bug_fix",
                title="Fix bug with minimal safe change",
                prompt=(
                    "Act as a senior engineer. Identify the root cause and implement the smallest safe code change. "
                    "Preserve style and add or update tests when appropriate."
                ),
                validator_profile="quality_gate",
                max_retries=max_retries,
            )
        )

    if _has_any(lower, ["security", "vulnerability", "owasp", "semgrep", "audit"]):
        steps.append(
            PlanStep(
                step_id="security_review",
                kind="security_check",
                title="Run security review and remediation",
                prompt=(
                    "Review the codebase for likely security weaknesses. "
                    "Fix high-confidence issues with minimal blast radius and document anything that remains."
                ),
                validator_profile="security_gate",
                max_retries=max_retries,
            )
        )

    if _has_any(lower, ["document", "documentation", "readme", "docstring", "comments"]):
        steps.append(
            PlanStep(
                step_id="write_docs",
                kind="documentation",
                title="Write requested documentation",
                prompt=(
                    "Produce user-requested documentation only. "
                    "Match the repository tone and avoid broad speculative docs."
                ),
                validator_profile="documentation",
                max_retries=max_retries,
            )
        )

    if _has_any(lower, ["create", "build", "write code", "implement", "feature"]) and not _has_any(lower, ["create pr", "pull request"]):
        steps.append(
            PlanStep(
                step_id="write_code",
                kind="code_generation",
                title="Implement requested code",
                prompt=(
                    "Implement the requested feature in production-ready form. "
                    "Follow existing conventions and add tests when the repo pattern supports it."
                ),
                validator_profile="quality_gate",
                max_retries=max_retries,
            )
        )

    if not any(step.kind != "analyze" for step in steps):
        steps.append(
            PlanStep(
                step_id="general_improvement",
                kind="code_generation",
                title="Execute the requested repository change",
                prompt=(
                    "Carry out the user request with minimal safe changes, keeping validation green."
                ),
                validator_profile="quality_gate",
                max_retries=max_retries,
            )
        )

    if create_pr or _has_any(lower, ["create pr", "pull request", "open pr"]):
        steps.append(
            PlanStep(
                step_id="prepare_pr",
                kind="pr",
                title="Prepare pull request payload",
                prompt="Summarize the final change set as a pull request.",
                validator_profile="pr",
                max_retries=1,
            )
        )

    return steps

