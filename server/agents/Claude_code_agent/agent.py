"""Claude Code Agent — end-to-end repo modification + PR.

Workflow on every prompt:

1. Clone the configured GitHub repo (or reuse an existing clone for the same
   repo URL, hard-resetting it to the remote default branch).
2. Build/refresh adaptive memory for that repo and inject it into ``CLAUDE.md``
   so Claude Code reads it automatically as persistent context.
3. Run the Claude Code CLI inside the repo with the user's prompt.
4. Append a run-note to the memory record (so the next run sees what
   changed).
5. Restore the original ``CLAUDE.md`` and remove the snapshot dir so the
   managed memory block is never committed to the user's remote.
6. Create a new branch, commit the changes, push to GitHub.
7. Open a PR head_branch -> base_branch via the GitHub REST API.

Required configuration (passed per-call or via env):

* ``anthropic_api_key`` — used to call Claude Code (``ANTHROPIC_API_KEY``).
* ``github_token`` — GitHub PAT with ``repo`` scope, used to clone, push,
  and create PRs (``GITHUB_PERSONAL_ACCESS_TOKEN``).
* ``repo_url`` — the GitHub repo this agent operates on (``GITHUB_REPO_URL``).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import git_service, memory_service
from .claude_service import run_claude_code
from .review_service import format_review_report, run_review

REPOS_DIR = Path(__file__).parent.parent.parent.parent / "repos" / "claude_code_agent"
REPOS_DIR.mkdir(parents=True, exist_ok=True)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _push_thinking_step(
    thinking_steps: List[Dict[str, Any]],
    step: Dict[str, Any],
    on_thinking_step: Optional[Callable[[Dict[str, Any]], None]],
) -> None:
    thinking_steps.append(step)
    if on_thinking_step:
        try:
            on_thinking_step(step)
        except Exception:
            pass


SYSTEM_PROMPT_PREFIX = (
    "You are an elite software engineer making targeted changes to an existing "
    "repository. Read CLAUDE.md first for project memory, then read the "
    "specific files you intend to change before editing. Preserve the "
    "codebase's existing style and conventions. Use the Edit/Write tools to "
    "apply changes directly. After your changes, output a short summary of "
    "what was modified and why.\n\n"
    "GIT MANDATE (STRICT — DO NOT VIOLATE):\n"
    "- A dedicated feature branch has already been checked out for you. ALL "
    "your edits must stay on this branch. NEVER switch branches.\n"
    "- DO NOT run any of: `git commit`, `git push`, `git branch`, "
    "`git checkout`, `git switch`, `git merge`, `git rebase`, `git reset`, "
    "`git tag`, `gh pr ...`, or any equivalent. The orchestrator handles ALL "
    "git operations (staging, committing, pushing the feature branch, opening "
    "the pull request).\n"
    "- NEVER push to `main`, `master`, or any base/default branch under any "
    "circumstance. There is no scenario in this run where you should touch "
    "the remote.\n"
    "- You may use Bash for non-git tasks (running tests, linters, build "
    "tools, file inspection). Anything git-related is forbidden.\n\n"
    "VALIDATION LOOP (REQUIRED — USE BASH):\n"
    "After applying your edits, you MUST validate the implementation by "
    "actually executing it with the Bash tool. Do not assume code works "
    "because it compiles in your head — run it. Workflow:\n"
    "1. Detect the project type from files present (package.json -> npm/yarn/"
    "pnpm; requirements.txt / pyproject.toml -> python; go.mod -> go; "
    "Cargo.toml -> rust; pom.xml / build.gradle -> jvm; Makefile -> make). "
    "Prefer the project's own scripts (`npm test`, `pytest`, `go test ./...`, "
    "`cargo test`, `make test`, etc.).\n"
    "2. Run, in this order, whichever apply: install/sync deps if missing → "
    "type-check / lint → unit tests → a smoke run of the affected entrypoint "
    "(import the module, hit the endpoint, invoke the CLI). For pure "
    "additions with no test harness, write a minimal inline check via Bash "
    "(e.g. `python -c 'import mymod; mymod.thing()'`) to prove the code at "
    "least loads and the happy path returns.\n"
    "3. If ANY command fails, read the error output, fix the root cause in "
    "the code (do not suppress, skip, or `|| true` past failures), and "
    "re-run the same validation command. Repeat until it passes or you have "
    "attempted at least 5 fix cycles for that command. If after 5 cycles a "
    "command still fails, stop iterating on it, leave the code in the best "
    "working state you can, and clearly record the remaining failure in the "
    "validation report below.\n"
    "4. Never edit tests just to make them green unless the test itself is "
    "demonstrably wrong (explain why in the report).\n"
    "5. Keep commands non-interactive and bounded — pass `--yes` / `--no-"
    "input` flags, avoid watch modes, and don't start long-running servers "
    "without a timeout.\n\n"
    "VALIDATION REPORT (REQUIRED):\n"
    "After the summary — and in addition to the migration-json block — you "
    "MUST emit exactly one fenced code block tagged `validation-json` "
    "describing what you executed and the outcome. Emit this on every run, "
    "even if you only ran one command. Shape (strict JSON):\n"
    "```validation-json\n"
    "{\n"
    "  \"overall_status\": \"passed\" | \"failed\" | \"partial\",\n"
    "  \"iterations\": 3,\n"
    "  \"steps\": [\n"
    "    {\n"
    "      \"command\": \"pytest -q\",\n"
    "      \"purpose\": \"unit tests\",\n"
    "      \"attempts\": 2,\n"
    "      \"final_status\": \"passed\" | \"failed\" | \"skipped\",\n"
    "      \"final_output_tail\": \"last ~20 lines of stdout/stderr\",\n"
    "      \"fixes_applied\": [\"short bullet of what you changed and why\"]\n"
    "    }\n"
    "  ],\n"
    "  \"remaining_issues\": [\"any failure you could not fix in 5 cycles\"]\n"
    "}\n"
    "```\n"
    "Set `overall_status` to `passed` only if every step's `final_status` is "
    "`passed`. Use `partial` if some passed and some are listed under "
    "`remaining_issues`. Use `failed` if nothing passes. Do not wrap the "
    "block in additional formatting and do not emit more than one "
    "`validation-json` block.\n\n"
    "MANUAL TEST CASES CSV (REQUIRED):\n"
    "After applying your code changes — and before emitting the final "
    "summary — you MUST create a folder named `manual_test_cases/` at the "
    "repository root (if it does not already exist) and write a single new "
    "CSV file inside it covering manual QA test cases for THIS run only. "
    "Name the file `test_cases_<UTC-timestamp>.csv` using the format "
    "`YYYYMMDD-HHMMSS` for the timestamp (e.g. "
    "`manual_test_cases/test_cases_20260427-155000.csv`). Do not overwrite "
    "or modify CSV files from previous runs.\n\n"
    "Use these exact CSV headers, in this order:\n"
    "`Test Case ID,Scenario Type,Title,Preconditions,Steps,Test Data,"
    "Expected Result,Priority`\n\n"
    "Rules for the file content:\n"
    "- Cover every category in `Scenario Type`: `Happy Path`, `E2E`, "
    "`Edge Case`, `Positive`, `Negative`. Include at least one row per "
    "category that is genuinely applicable to the change; if a category "
    "truly does not apply, include one row that says so in `Title` and "
    "`Expected Result` rather than omitting it.\n"
    "- `Test Case ID` must be sequential (`TC-001`, `TC-002`, ...).\n"
    "- `Steps` must be numbered (`1. ... | 2. ... | 3. ...`) using `|` as "
    "the separator so it stays on a single CSV cell.\n"
    "- `Priority` must be one of `High`, `Medium`, `Low`.\n"
    "- Quote any field that contains a comma, newline, or double-quote, "
    "and escape inner double-quotes by doubling them (RFC 4180).\n"
    "- Tailor every row to the actual files you changed and the user "
    "request — do NOT emit generic boilerplate.\n"
    "- Write only the CSV file under `manual_test_cases/`; do not modify "
    "anything else in that folder.\n\n"
    "DATABASE MIGRATION REPORT (REQUIRED):\n"
    "After the summary, you MUST emit a fenced code block tagged exactly "
    "`migration-json` describing any database schema impact of your changes. "
    "This is non-negotiable — emit the block on every run, even when no DB "
    "changes were made.\n\n"
    "Detect DB impact from any of: new/edited `*.sql` files, files under a "
    "`migrations/` or `db/` directory, ORM model changes (SQLAlchemy, "
    "Sequelize, Mongoose, Prisma schema, Django/Rails models, TypeORM, "
    "etc.), or code that creates/alters tables, columns, indexes, "
    "constraints, enums, or stored procedures.\n\n"
    "When DB impact exists, set `migration_needed: true` and list one entry "
    "per logical change in `scripts`. Each `sql` value MUST be raw, runnable "
    "SQL (CREATE TABLE / ALTER TABLE / CREATE INDEX / etc.) — never ORM "
    "syntax — and `reason` MUST be a short human-readable explanation. If "
    "the repo is using a non-SQL store (e.g. Mongo) include the equivalent "
    "shell commands as `sql` and note the dialect in `reason`. If there is "
    "no DB impact, set `migration_needed: false` and `scripts: []`.\n\n"
    "Output exactly this shape (strict JSON — double-quoted keys/strings):\n"
    "```migration-json\n"
    "{\n"
    "  \"migration_needed\": true,\n"
    "  \"scripts\": [\n"
    "    { \"reason\": \"...\", \"sql\": \"...\" }\n"
    "  ]\n"
    "}\n"
    "```\n"
    "Do not wrap the block in any other formatting and do not emit more than "
    "one `migration-json` block."
)

_MIGRATION_BLOCK_RE = re.compile(
    r"```migration-json\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)
_VALIDATION_BLOCK_RE = re.compile(
    r"```validation-json\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)

_DEFAULT_VALIDATION: Dict[str, Any] = {
    "overall_status": "skipped",
    "iterations": 0,
    "steps": [],
    "remaining_issues": ["No validation block emitted by Claude Code."],
}


def _extract_validation_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the validation-json fenced block out of Claude's summary."""
    if not text:
        return None
    match = _VALIDATION_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    status = str(parsed.get("overall_status", "")).strip().lower() or "unknown"
    if status not in {"passed", "failed", "partial", "skipped", "unknown"}:
        status = "unknown"
    raw_steps = parsed.get("steps") or []
    steps: List[Dict[str, Any]] = []
    if isinstance(raw_steps, list):
        for s in raw_steps:
            if not isinstance(s, dict):
                continue
            fixes = s.get("fixes_applied") or []
            if not isinstance(fixes, list):
                fixes = []
            steps.append({
                "command": str(s.get("command", "")).strip(),
                "purpose": str(s.get("purpose", "")).strip(),
                "attempts": int(s.get("attempts", 1) or 1),
                "final_status": str(s.get("final_status", "")).strip().lower() or "unknown",
                "final_output_tail": str(s.get("final_output_tail", "")).strip()[:2000],
                "fixes_applied": [str(f).strip() for f in fixes if str(f).strip()],
            })
    remaining = parsed.get("remaining_issues") or []
    if not isinstance(remaining, list):
        remaining = []
    return {
        "overall_status": status,
        "iterations": int(parsed.get("iterations", len(steps)) or len(steps)),
        "steps": steps,
        "remaining_issues": [str(r).strip() for r in remaining if str(r).strip()],
    }


def _format_validation_report(validation: Dict[str, Any]) -> str:
    status = str(validation.get("overall_status", "unknown")).lower()
    iters = validation.get("iterations", 0)
    steps = validation.get("steps", []) or []
    remaining = validation.get("remaining_issues", []) or []
    lines = [
        f"- **Overall status:** `{status}`",
        f"- **Iterations:** {iters}",
        f"- **Steps executed:** {len(steps)}",
    ]
    if steps:
        lines.append("")
        lines.append("| Step | Command | Attempts | Final |")
        lines.append("|------|---------|----------|-------|")
        for s in steps[:20]:
            cmd = (s.get("command") or "").replace("|", "\\|")[:80]
            purpose = (s.get("purpose") or "").replace("|", "\\|")[:40]
            lines.append(
                f"| {purpose or '—'} | `{cmd}` | {s.get('attempts', 1)} | "
                f"`{s.get('final_status', 'unknown')}` |"
            )
        failing = [s for s in steps if s.get("final_status") not in {"passed", "skipped"}]
        if failing:
            lines.append("")
            lines.append("### Failure output (last lines)")
            for s in failing[:5]:
                tail = s.get("final_output_tail") or ""
                if not tail:
                    continue
                lines.append("")
                lines.append(f"**`{s.get('command', '')}`**")
                lines.append("```")
                lines.append(tail[:1500])
                lines.append("```")
        fixes = [(s.get("command"), f) for s in steps for f in (s.get("fixes_applied") or [])]
        if fixes:
            lines.append("")
            lines.append("### Fixes applied during validation")
            for cmd, fix in fixes[:30]:
                lines.append(f"- (`{cmd}`) {fix}")
    if remaining:
        lines.append("")
        lines.append("### Remaining issues")
        for r in remaining[:20]:
            lines.append(f"- {r}")
    return "\n".join(lines)
def _resolve_review_settings() -> Dict[str, Any]:
    """Read review-loop settings fresh on every call.

    Read at call time (not import time) so per-request agent config applied via
    ``apply_user_config_concurrent`` (UI-saved values forwarded as env vars for
    the duration of the request) takes effect.
    """
    return {
        "enabled": _env_bool("CLAUDE_CODE_REVIEW_ENABLED", True),
        "target_score": max(0.0, min(100.0, _env_float("CLAUDE_CODE_REVIEW_TARGET_SCORE", 90.0))),
        "max_loops": max(1, _env_int("CLAUDE_CODE_REVIEW_MAX_LOOPS", 3)),
    }


def _extract_migration_json(text: str) -> Optional[Dict[str, Any]]:
    """Pull the migration-json fenced block out of Claude's summary.

    Returns ``None`` if the block is missing or malformed so callers can
    decide whether to fall back to a default shape.
    """
    if not text:
        return None
    match = _MIGRATION_BLOCK_RE.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    scripts = parsed.get("scripts") or []
    if not isinstance(scripts, list):
        scripts = []
    cleaned_scripts: List[Dict[str, str]] = []
    for s in scripts:
        if not isinstance(s, dict):
            continue
        cleaned_scripts.append({
            "reason": str(s.get("reason", "")).strip(),
            "sql": str(s.get("sql", "")).strip(),
        })
    return {
        "migration_needed": bool(parsed.get("migration_needed", False)) and bool(cleaned_scripts),
        "scripts": cleaned_scripts,
    }


def _review_passes_threshold(review: Dict[str, Any], target_score: float) -> bool:
    score = float(review.get("alignment_score", 0.0) or 0.0)
    mismatches = review.get("mismatches", []) or []
    return score >= target_score and len(mismatches) == 0


def _merge_changed_files(changed_map: Dict[str, str], changed: List[Dict[str, Any]]) -> None:
    for item in changed:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("file_path", "")).strip()
        if not file_path:
            continue
        action = str(item.get("action", "modify")).strip().lower()
        if action not in {"create", "modify"}:
            action = "modify"
        prev = changed_map.get(file_path)
        if prev == "create":
            continue
        if action == "create" or prev is None:
            changed_map[file_path] = action
        else:
            changed_map[file_path] = "modify"


def _changed_files_from_map(changed_map: Dict[str, str]) -> List[Dict[str, str]]:
    return [
        {"file_path": file_path, "action": action}
        for file_path, action in sorted(changed_map.items())
    ]


def _build_fix_prompt(
    query: str,
    review: Dict[str, Any],
    target_score: float,
) -> str:
    mismatches = review.get("mismatches", []) or []
    fixes = review.get("fix_instructions", []) or []
    mismatches_text = "\n".join(f"- {m}" for m in mismatches[:50]) or "- No mismatch details provided"
    fixes_text = "\n".join(f"- {f}" for f in fixes[:50]) or "- Derive fixes directly from mismatches"

    return (
        "You are an elite software engineer applying targeted remediation to an "
        "existing repository.\n"
        "Apply the smallest set of edits needed to resolve the review findings and "
        "fully align to the user request. Preserve existing architecture and style.\n\n"
        "Original user request:\n"
        f"{query.strip()}\n\n"
        "Review mismatches to fix:\n"
        f"{mismatches_text}\n\n"
        "Suggested fix instructions:\n"
        f"{fixes_text}\n\n"
        f"Goal: reach at least {target_score:.0f}% alignment with zero mismatches in next review.\n\n"
        "After applying fixes, output a short summary and one migration-json block in this exact shape:\n"
        "```migration-json\n"
        "{\n"
        "  \"migration_needed\": false,\n"
        "  \"scripts\": []\n"
        "}\n"
        "```"
    )


class ClaudeCodeAgent:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}
        print("[Claude Code Agent] initialized")

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------

    def _resolve_config(
        self,
        anthropic_api_key: Optional[str],
        github_token: Optional[str],
        repo_url: Optional[str],
    ) -> Dict[str, Any]:
        api_key = (anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        token = (github_token or os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN") or "").strip()
        repo = (repo_url or os.environ.get("GITHUB_REPO_URL") or "").strip()

        missing: List[str] = []
        if not api_key:
            missing.append("anthropic_api_key")
        if not token:
            missing.append("github_token")
        if not repo:
            missing.append("repo_url")
        if not missing and not git_service.parse_github_url(repo):
            return {"ok": False, "error": f"Invalid GitHub repo URL: {repo}"}
        if missing:
            return {
                "ok": False,
                "error": "Missing required configuration: " + ", ".join(missing),
            }
        return {"ok": True, "anthropic_api_key": api_key, "github_token": token, "repo_url": repo}

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def process_query(
        self,
        query: str,
        session_id: str = "default",
        anthropic_api_key: Optional[str] = None,
        github_token: Optional[str] = None,
        repo_url: Optional[str] = None,
        base_branch: Optional[str] = None,
        review_enabled: Optional[bool] = None,
        model: Optional[str] = None,
        # Backwards-compat (older callers may still pass these — ignored):
        workspace_root: Optional[str] = None,
        context_files: Optional[list] = None,
        on_thinking_step: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        review_settings = _resolve_review_settings()
        review_on = review_settings["enabled"] if review_enabled is None else bool(review_enabled)
        review_target = review_settings["target_score"]
        review_max_loops = review_settings["max_loops"]
        thinking_steps: List[Dict[str, Any]] = []

        if not (query or "").strip():
            return _final(False, "Please provide a non-empty prompt.", thinking_steps)

        cfg = self._resolve_config(anthropic_api_key, github_token, repo_url)
        if not cfg["ok"]:
            return _final(
                False,
                cfg["error"]
                + "\n\nProvide them in the request body (`anthropic_api_key`, "
                "`github_token`, `repo_url`) or set "
                "`ANTHROPIC_API_KEY`, `GITHUB_PERSONAL_ACCESS_TOKEN`, "
                "`GITHUB_REPO_URL` in the environment.",
                thinking_steps,
                requires_token=not cfg.get("github_token"),
            )

        try:
            # --- 1. Clone / refresh -------------------------------------
            _push_thinking_step(thinking_steps, {
                "type": "tool_call", "tool_name": "git_clone",
                "content": f"Cloning {cfg['repo_url']}",
            }, on_thinking_step)
            clone = git_service.clone_repo(cfg["repo_url"], REPOS_DIR, cfg["github_token"])
            if not clone.get("success"):
                return _final(False, f"Clone failed: {clone.get('error')}", thinking_steps)
            repo_path = clone["path"]
            repo_name = clone["name"]
            owner = clone["owner"]
            default_branch = base_branch or clone.get("default_branch") or "main"
            _push_thinking_step(thinking_steps, {
                "type": "tool_result",
                "content": (
                    f"{'Refreshed' if clone.get('reused') else 'Cloned'} "
                    f"{owner}/{repo_name} (base: {default_branch})"
                ),
            }, on_thinking_step)

            # --- 1b. Create feature branch BEFORE the CLI runs ----------
            # This guarantees any commit Claude Code makes lands on the
            # feature branch, never on the base branch.
            _push_thinking_step(thinking_steps, {
                "type": "tool_call", "tool_name": "git_branch",
                "content": "Creating feature branch off base branch...",
            }, on_thinking_step)
            branch_create = git_service.create_feature_branch(
                repo_path=repo_path,
                prompt=query,
                token=cfg["github_token"],
            )
            if not branch_create.get("success"):
                return _final(
                    False,
                    f"Branch creation failed: {branch_create.get('error')}",
                    thinking_steps,
                    repo_url=cfg["repo_url"],
                )
            feature_branch = branch_create["branch"]
            _push_thinking_step(thinking_steps, {
                "type": "tool_result",
                "content": f"Feature branch ready: `{feature_branch}` (base: `{default_branch}`)",
            }, on_thinking_step)

            # --- 2. Adaptive memory + CLAUDE.md injection ---------------
            _push_thinking_step(thinking_steps, {
                "type": "thinking",
                "content": "Building adaptive memory and injecting CLAUDE.md...",
            }, on_thinking_step)
            memory = memory_service.build_or_refresh_memory(
                cfg["repo_url"], repo_path, repo_name
            )
            memory_service.write_claude_md(repo_path, memory)

            # --- 3. Run Claude Code CLI ---------------------------------
            _push_thinking_step(thinking_steps, {
                "type": "tool_call", "tool_name": "claude_code_cli",
                "content": "Running Claude Code CLI on the repository...",
            }, on_thinking_step)
            selected_model = (model or "").strip() or None
            if selected_model:
                _push_thinking_step(thinking_steps, {
                    "type": "thinking",
                    "content": f"Using Claude model: `{selected_model}`",
                }, on_thinking_step)
            full_prompt = f"{SYSTEM_PROMPT_PREFIX}\n\nUser request:\n{query}"
            cli = await run_claude_code(
                prompt=full_prompt,
                repo_path=repo_path,
                anthropic_api_key=cfg["anthropic_api_key"],
                emit=on_thinking_step,
                model=selected_model,
            )
            thinking_steps.extend(cli.get("thinking_steps", []))

            if not cli["success"]:
                # Restore CLAUDE.md even when the CLI fails so we don't leave
                # the managed block lying around in a reused clone.
                memory_service.restore_original_claude_md(repo_path)
                memory_service.cleanup_snapshot_dir(repo_path)
                return _final(
                    False,
                    f"Claude Code run failed: {cli.get('error')}",
                    thinking_steps,
                    repo_url=cfg["repo_url"],
                )

            changed_map: Dict[str, str] = {}
            _merge_changed_files(changed_map, cli.get("changed_files", []) or [])
            latest_summary = cli.get("summary", "")
            migration = _extract_migration_json(latest_summary) or {
                "migration_needed": False,
                "scripts": [],
            }
            validation = _extract_validation_json(latest_summary) or dict(_DEFAULT_VALIDATION)
            _push_thinking_step(thinking_steps, {
                "type": "tool_result",
                "content": (
                    f"Validation loop: status=`{validation.get('overall_status')}`, "
                    f"iterations={validation.get('iterations', 0)}, "
                    f"steps={len(validation.get('steps') or [])}, "
                    f"remaining_issues={len(validation.get('remaining_issues') or [])}"
                ),
            }, on_thinking_step)
            total_cost_usd = float(cli.get("cost_usd", 0.0) or 0.0)
            total_duration_seconds = float(cli.get("duration_seconds", 0.0) or 0.0)
            _push_thinking_step(thinking_steps, {
                "type": "tool_result",
                "content": (
                    f"Claude Code generation finished — {len(changed_map)} file(s) changed, "
                    f"cost ${total_cost_usd:.4f}, {total_duration_seconds:.1f}s"
                ),
            }, on_thinking_step)

            latest_review: Dict[str, Any] = {
                "alignment_score": 0.0,
                "is_aligned": False,
                "mismatches": [],
                "fix_instructions": [],
                "summary": "",
            }
            review_reports: List[Dict[str, Any]] = []
            latest_inspected: List[Dict[str, str]] = []
            if not review_on:
                _push_thinking_step(thinking_steps, {
                    "type": "thinking",
                    "content": "Review/validation loop is disabled (CLAUDE_CODE_REVIEW_ENABLED=false). Skipping prompt-alignment review.",
                }, on_thinking_step)
            for review_pass in range(1, review_max_loops + 1) if review_on else []:
                _push_thinking_step(thinking_steps, {
                    "type": "tool_call",
                    "tool_name": "review_agent",
                    "content": f"Review pass {review_pass}: validating prompt alignment...",
                }, on_thinking_step)

                def _emit_review_step(step: Dict[str, Any]) -> None:
                    _push_thinking_step(thinking_steps, step, on_thinking_step)

                review_result = await run_review(
                    user_request=query,
                    repo_path=repo_path,
                    base_branch=default_branch,
                    changed_files=_changed_files_from_map(changed_map),
                    target_score=review_target,
                    anthropic_api_key=cfg["anthropic_api_key"],
                    emit=_emit_review_step,
                )
                total_cost_usd += float(review_result.get("cost_usd", 0.0) or 0.0)
                total_duration_seconds += float(review_result.get("duration_seconds", 0.0) or 0.0)

                if not review_result["success"]:
                    memory_service.restore_original_claude_md(repo_path)
                    memory_service.cleanup_snapshot_dir(repo_path)
                    return _final(
                        False,
                        f"Review pass failed: {review_result.get('error')}",
                        thinking_steps,
                        repo_url=cfg["repo_url"],
                    )

                latest_review = review_result["review"]
                latest_inspected = review_result.get("inspected", []) or []
                review_reports.append(latest_review)
                review_score = float(latest_review.get("alignment_score", 0.0) or 0.0)
                mismatch_count = len(latest_review.get("mismatches", []) or [])
                _push_thinking_step(thinking_steps, {
                    "type": "tool_result",
                    "content": (
                        f"Review pass {review_pass} result — alignment {review_score:.1f}% "
                        f"(target {review_target:.0f}%), mismatches: {mismatch_count}, "
                        f"files inspected: {len(latest_inspected)}"
                    ),
                }, on_thinking_step)

                if _review_passes_threshold(latest_review, review_target):
                    break

                if review_pass >= review_max_loops:
                    break

                _push_thinking_step(thinking_steps, {
                    "type": "tool_call",
                    "tool_name": "claude_code_cli",
                    "content": "Review found mismatches. Applying automated fixes...",
                }, on_thinking_step)
                fix_prompt = _build_fix_prompt(query, latest_review, review_target)
                fix_cli = await run_claude_code(
                    prompt=fix_prompt,
                    repo_path=repo_path,
                    anthropic_api_key=cfg["anthropic_api_key"],
                    emit=on_thinking_step,
                    model=selected_model,
                )
                thinking_steps.extend(fix_cli.get("thinking_steps", []))
                total_cost_usd += float(fix_cli.get("cost_usd", 0.0) or 0.0)
                total_duration_seconds += float(fix_cli.get("duration_seconds", 0.0) or 0.0)

                if not fix_cli["success"]:
                    memory_service.restore_original_claude_md(repo_path)
                    memory_service.cleanup_snapshot_dir(repo_path)
                    return _final(
                        False,
                        f"Claude Code fix pass failed: {fix_cli.get('error')}",
                        thinking_steps,
                        repo_url=cfg["repo_url"],
                    )

                _merge_changed_files(changed_map, fix_cli.get("changed_files", []) or [])
                latest_summary = fix_cli.get("summary", "") or latest_summary
                maybe_migration = _extract_migration_json(latest_summary)
                if maybe_migration is not None:
                    migration = maybe_migration
                maybe_validation = _extract_validation_json(latest_summary)
                if maybe_validation is not None:
                    validation = maybe_validation
                _push_thinking_step(thinking_steps, {
                    "type": "tool_result",
                    "content": (
                        f"Fix pass complete — {len(fix_cli.get('changed_files', []) or [])} "
                        "file(s) updated before re-review."
                    ),
                }, on_thinking_step)

            changed = _changed_files_from_map(changed_map)
            final_review_score = float(latest_review.get("alignment_score", 0.0) or 0.0)
            review_pass_count = len(review_reports)
            coverage_met = (
                True
                if not review_on
                else _review_passes_threshold(latest_review, review_target)
            )
            if review_on:
                _push_thinking_step(thinking_steps, {
                    "type": "tool_result",
                    "content": (
                        f"Generation + review cycle complete — alignment {final_review_score:.1f}% "
                        f"after {review_pass_count} review pass(es)."
                    ),
                }, on_thinking_step)

            if review_on and not coverage_met:
                _push_thinking_step(thinking_steps, {
                    "type": "tool_result",
                    "content": (
                        f"Review threshold not met (alignment {final_review_score:.1f}% < "
                        f"target {review_target:.0f}% after {review_pass_count} pass(es)). "
                        "Falling back to push + PR with a warning so changes aren't lost."
                    ),
                }, on_thinking_step)

            # --- 4. Persist run note ------------------------------------
            run_note_summary = (
                f"{latest_summary}\n\n"
                f"Review alignment: {final_review_score:.1f}% "
                f"(target {review_target:.0f}%)."
            ).strip() if review_on else (latest_summary or "").strip()
            memory_service.append_run_note(
                cfg["repo_url"],
                summary=run_note_summary,
                changed_files=[c["file_path"] for c in changed],
                cost_usd=total_cost_usd,
                duration_seconds=round(total_duration_seconds, 1),
            )

            if not changed:
                # No changes → still restore CLAUDE.md and skip push/PR.
                memory_service.restore_original_claude_md(repo_path)
                memory_service.cleanup_snapshot_dir(repo_path)
                no_change_msg = (
                    "Claude Code completed without modifying any files.\n\n"
                    f"**Summary:** {latest_summary or '(no summary)'}"
                )
                if review_on:
                    no_change_msg += (
                        f"\n**Review alignment:** {final_review_score:.1f}% "
                        f"(target: {review_target:.0f}%)"
                    )
                return _final(
                    True,
                    no_change_msg,
                    thinking_steps,
                    repo_url=cfg["repo_url"],
                )

            # --- 5. Branch + commit + push ------------------------------
            commit_msg = _commit_message_from(query, latest_summary)
            _push_thinking_step(thinking_steps, {
                "type": "tool_call", "tool_name": "git_push",
                "content": f"Pushing to a new branch on {owner}/{repo_name}...",
            }, on_thinking_step)
            push = git_service.push_changes(
                repo_path=repo_path,
                repo_url=cfg["repo_url"],
                token=cfg["github_token"],
                commit_message=commit_msg,
                base_branch=default_branch,
                branch_name=feature_branch,
            )
            if not push.get("success"):
                return _final(
                    False,
                    f"Push failed: {push.get('error')}",
                    thinking_steps,
                    repo_url=cfg["repo_url"],
                )
            branch = push["branch"]

            # --- 6. Create PR -------------------------------------------
            _push_thinking_step(thinking_steps, {
                "type": "tool_call", "tool_name": "github_pr",
                "content": f"Opening PR `{branch}` -> `{default_branch}`...",
            }, on_thinking_step)
            metrics = {
                "cost_usd": total_cost_usd,
                "duration_seconds": round(total_duration_seconds, 1),
            }
            pr_body = _build_pr_body(
                query, latest_summary, changed, metrics, migration,
                latest_review if review_on else None,
                target_score=review_target,
                review_passes=review_pass_count if review_on else 0,
                coverage_met=coverage_met if review_on else True,
                inspected=latest_inspected if review_on else None,
                validation=validation,
            )
            pr = git_service.create_pull_request(
                owner=owner,
                repo=repo_name,
                token=cfg["github_token"],
                head_branch=branch,
                base_branch=default_branch,
                title=commit_msg,
                body=pr_body,
            )

            self.sessions[session_id] = {
                "repo_url": cfg["repo_url"],
                "repo_path": repo_path,
                "branch": branch,
                "last_changed_files": [c["file_path"] for c in changed],
            }

            files_md = "\n".join(f"  - `{c['file_path']}` ({c['action']})" for c in changed[:20])
            if pr.get("success"):
                pr_line = f"[**Open Pull Request →**]({pr['pr_url']})"
                if pr.get("already_exists"):
                    pr_line += " *(existing PR for this branch)*"
            else:
                pr_line = (
                    f"PR could not be opened automatically: {pr.get('error')}\n"
                    f"You can open one manually here: {push.get('compare_url')}"
                )

            migration_block = (
                "\n\n```json\n"
                + json.dumps(migration, indent=2)
                + "\n```"
            )
            validation_status = str(validation.get("overall_status", "unknown")).lower()
            status_emoji = {
                "passed": "PASS",
                "partial": "PARTIAL",
                "failed": "FAIL",
                "skipped": "SKIPPED",
            }.get(validation_status, "UNKNOWN")
            validation_line = (
                f"**Validation:** {status_emoji} "
                f"(iterations: {validation.get('iterations', 0)}, "
                f"steps: {len(validation.get('steps') or [])}, "
                f"remaining: {len(validation.get('remaining_issues') or [])})\n"
            )
            validation_report_block = (
                "\n\n## Validation Report\n\n"
                + _format_validation_report(validation)
                + "\n"
            )
            if review_on:
                status_label = "passed" if coverage_met else "below target — fallback push"
                review_line = (
                    f"**Review alignment:** {final_review_score:.1f}% "
                    f"(target: {review_target:.0f}%) after {review_pass_count} pass(es) — {status_label}\n"
                )
                review_report_block = (
                    "\n\n## Review Report\n\n"
                    + format_review_report(latest_review, review_target, latest_inspected)
                    + "\n"
                )
            else:
                review_line = "**Review alignment:** disabled\n"
                review_report_block = ""
            warning_block = ""
            if review_on and not coverage_met:
                warning_block = (
                    "\n> **Warning:** review threshold was not met after all passes. "
                    "Changes were pushed as a fallback so work isn't lost. See the "
                    "Review Report below for outstanding mismatches.\n"
                )
            response = (
                f"Done — pushed changes to **{owner}/{repo_name}**.\n\n"
                f"**Branch:** `{branch}` (base: `{default_branch}`)\n"
                f"**Commit:** {commit_msg}\n"
                f"**Files changed ({len(changed)}):**\n{files_md}\n\n"
                f"{review_line}"
                f"{validation_line}"
                f"**Cost:** ${total_cost_usd:.4f} · **Duration:** {round(total_duration_seconds, 1)}s\n\n"
                f"{pr_line}"
                f"{warning_block}"
                f"{review_report_block}"
                f"{validation_report_block}"
                f"{migration_block}"
            )

            return _final(
                True, response, thinking_steps,
                repo_url=cfg["repo_url"],
                generated_files=[c["file_path"] for c in changed],
                pr_url=pr.get("pr_url"),
                branch=branch,
                migration=migration,
                validation=validation,
            )

        except Exception as e:
            return _final(False, f"Unhandled error: {type(e).__name__}: {e}", thinking_steps)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _commit_message_from(query: str, summary: str) -> str:
    base = (summary or query or "Update via Claude Code Agent").strip().splitlines()[0]
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) > 72:
        base = base[:69] + "..."
    return base or "Update via Claude Code Agent"


def _build_pr_body(
    query: str,
    summary: str,
    changed: List[Dict[str, Any]],
    cli: Dict[str, Any],
    migration: Optional[Dict[str, Any]] = None,
    review: Optional[Dict[str, Any]] = None,
    target_score: Optional[float] = None,
    review_passes: int = 0,
    coverage_met: bool = True,
    inspected: Optional[List[Dict[str, str]]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> str:
    if target_score is None:
        target_score = _resolve_review_settings()["target_score"]
    files = "\n".join(f"- `{c['file_path']}` ({c['action']})" for c in changed[:50])
    cleaned_summary = (summary or "").strip()
    cleaned_summary = _MIGRATION_BLOCK_RE.sub("", cleaned_summary).strip()
    cleaned_summary = _VALIDATION_BLOCK_RE.sub("", cleaned_summary).strip()
    validation = validation or dict(_DEFAULT_VALIDATION)
    migration = migration or {"migration_needed": False, "scripts": []}
    review = review or {}
    review_score = float(review.get("alignment_score", 0.0) or 0.0)
    review_summary = (review.get("summary") or "").strip()
    review_mismatches = review.get("mismatches", []) or []
    review_fixes = review.get("fix_instructions", []) or []
    review_status = "PASSED" if coverage_met else "BELOW TARGET (fallback push)"
    inspected = inspected or []
    body = [
        "## Request",
        "",
        query.strip()[:1500],
        "",
        "## Summary",
        "",
        (cleaned_summary or "_(no summary returned)_")[:1500],
        "",
        "## Review Validation",
        "",
        f"- Status: **{review_status}**",
        f"- Alignment score: {review_score:.1f}%",
        f"- Target score: {target_score:.0f}%",
        f"- Review passes: {review_passes}",
        f"- Remaining mismatches: {len(review_mismatches)}",
        f"- Files inspected by validator: {len(inspected)}",
        "",
    ]
    if review_summary:
        body.extend(["### Validator summary", "", review_summary, ""])
    if inspected:
        body.append("### What the validator reviewed")
        body.append("")
        for item in inspected[:50]:
            tool = item.get("tool", "")
            target = item.get("target", "")
            label = {"read_file": "read", "glob_files": "glob", "grep_files": "grep"}.get(tool, tool)
            body.append(f"- {label}: `{target}`")
        if len(inspected) > 50:
            body.append(f"- … {len(inspected) - 50} more")
        body.append("")
    if review_mismatches:
        body.append("### Mismatches")
        body.append("")
        body.extend(f"- {m}" for m in review_mismatches[:20])
        body.append("")
    if review_fixes:
        body.append("### Suggested fixes")
        body.append("")
        body.extend(f"- {f}" for f in review_fixes[:20])
        body.append("")
    if not coverage_met:
        body.extend([
            "> **Warning:** the review agent did not reach the target alignment "
            "after all configured passes. These changes are pushed as a fallback "
            "so work isn't lost — please review the outstanding mismatches above "
            "before merging.",
            "",
        ])
    body += [
        "## Files Changed",
        "",
        files or "_(none)_",
        "",
        "## Validation Report",
        "",
        _format_validation_report(validation),
        "",
        "## Database Migration",
        "",
        "```json",
        json.dumps(migration, indent=2),
        "```",
        "",
        "---",
        f"_Generated by Claude Code Agent at {datetime.utcnow().isoformat()}Z · "
        f"cost ${cli.get('cost_usd', 0):.4f} · {cli.get('duration_seconds', 0)}s_",
    ]
    return "\n".join(body)


def _final(
    success: bool,
    response: str,
    thinking_steps: List[Dict[str, Any]],
    *,
    requires_token: bool = False,
    repo_url: Optional[str] = None,
    generated_files: Optional[List[str]] = None,
    pr_url: Optional[str] = None,
    branch: Optional[str] = None,
    migration: Optional[Dict[str, Any]] = None,
    validation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "success": success,
        "response": response,
        "thinking_steps": thinking_steps,
        "requires_token": requires_token,
        "repo_url": repo_url,
        "generated_files": generated_files or [],
        "pr_url": pr_url,
        "branch": branch,
        "migration": migration or {"migration_needed": False, "scripts": []},
        "validation": validation or dict(_DEFAULT_VALIDATION),
    }


claude_code_agent = ClaudeCodeAgent()
