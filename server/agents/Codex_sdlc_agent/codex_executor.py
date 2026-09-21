from __future__ import annotations

from typing import List

from .models import ExecutionResult, PlanStep, RunState
from .services.codex_cli_service import codex_cli_available, codex_runtime_config, run_codex_cli
from .services.git_service import get_changed_files, get_git_diff


class CodexExecutor:
    """Codex CLI-only execution backend for SDLC workflows."""

    primary_backend = "codex_cli"

    async def execute(self, step: PlanStep, state: RunState) -> ExecutionResult:
        goal = (
            f"{step.prompt}\n\n"
            f"Primary goal:\n{state.query}\n\n"
            f"Repository memory:\n{state.memory}\n\n"
            f"{state.context_block}"
        ).strip()
        return await self._execute_with_codex(step, state, goal)

    async def _execute_with_codex(
        self,
        step: PlanStep,
        state: RunState,
        goal: str,
    ) -> ExecutionResult:
        if not codex_cli_available():
            return ExecutionResult(
                success=False,
                response="Codex CLI is not installed or not available in PATH on this host.",
                backend=self.primary_backend,
            )

        runtime = codex_runtime_config()
        sandbox = runtime["sandbox"] or ("read-only" if step.kind in {"analyze", "pr"} or state.dry_run else "workspace-write")
        model = state.memory.get("codex_model") or runtime["model"] or None
        profile = runtime["profile"] or None
        prompt = self._build_codex_prompt(step, state, goal)
        before_files = set(get_changed_files(state.workspace_root))
        cli = await run_codex_cli(
            prompt=prompt,
            cwd=state.workspace_root,
            sandbox=sandbox,
            model=model,
            profile=profile,
            ephemeral=not state.create_pr,
        )
        if not cli["success"]:
            return ExecutionResult(
                success=False,
                response=cli["result"],
                artifacts={
                    "stdout": cli.get("stdout", ""),
                    "stderr": cli.get("stderr", ""),
                    "runtime_config": cli.get("runtime_config", {}),
                },
                backend=self.primary_backend,
            )

        after_files = set(get_changed_files(state.workspace_root))
        changed_files = sorted(after_files - before_files) if not state.dry_run else []
        if not changed_files and not state.dry_run:
            changed_files = sorted(after_files)
        diff = "" if state.dry_run else get_git_diff(state.workspace_root)
        return ExecutionResult(
            success=True,
            response=cli["result"],
            files_changed=changed_files,
            diff=diff,
            artifacts={
                "stdout": cli.get("stdout", ""),
                "stderr": cli.get("stderr", ""),
                "runtime_config": cli.get("runtime_config", {}),
            },
            backend=self.primary_backend,
        )

    def _build_codex_prompt(self, step: PlanStep, state: RunState, goal: str) -> str:
        mode = "analyze only; do not modify files" if step.kind in {"analyze", "pr"} or state.dry_run else "modify files as needed"
        return (
            f"You are executing an SDLC workflow step in repository `{state.repo_name}`.\n\n"
            f"Step: {step.title}\n"
            f"Mode: {mode}\n\n"
            f"Instructions:\n{goal}\n\n"
            "Requirements:\n"
            "- Follow existing repository conventions.\n"
            "- Keep changes minimal and production-oriented.\n"
            "- If modifying code, prefer adding or updating tests when appropriate.\n"
            "- End with a concise summary of what you changed or analyzed.\n"
        )
