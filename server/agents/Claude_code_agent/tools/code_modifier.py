"""Repository code modification using Claude Code CLI.

The CLI gets full tool access (Read, Edit, Write, Bash) to the cloned repo
so it can read existing code, make targeted edits, create new files, and
even run tests or linting commands.
"""

import os
import subprocess
from typing import Dict, Any, List
from ..claude_service import run_claude_cli, MODIFY_SYSTEM_PROMPT


async def modify_repository_code(
    repo_path: str,
    repo_name: str,
    query: str,
    cli_session_id: str = None,
) -> Dict[str, Any]:
    """Modify code in a cloned repository using Claude Code CLI."""

    snapshot_before = _get_tracked_files(repo_path)

    prompt = (
        f"In this repository '{repo_name}', make the following changes:\n\n"
        f"{query}\n\n"
        f"Read the relevant source files first to understand the codebase, "
        f"then use Edit/Write tools to apply changes directly. "
        f"After making changes, briefly summarize what was modified."
    )

    result = await run_claude_cli(
        prompt=prompt,
        cwd=repo_path,
        system_prompt=MODIFY_SYSTEM_PROMPT,
        allowed_tools="Read Edit Write",
        max_budget_usd=1.5,
        session_id=cli_session_id,
    )

    modified_files = _detect_changes(repo_path, snapshot_before)

    response = result["result"]
    if modified_files:
        file_list = "\n".join(f"  - `{f}`" for f in modified_files)
        response += f"\n\n**Modified files:**\n{file_list}"

    return {
        "success": result["success"],
        "response": response,
        "modified_files": modified_files,
        "cost": result.get("cost", 0),
        "cli_session_id": result.get("session_id"),
    }


def _get_tracked_files(repo_path: str) -> Dict[str, float]:
    """Snapshot modification times of all tracked files."""
    snapshot = {}
    skip = {'.git', '__pycache__', 'node_modules', '.claude'}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, repo_path)
            try:
                snapshot[rel] = os.path.getmtime(full)
            except OSError:
                pass
    return snapshot


def _detect_changes(repo_path: str, before: Dict[str, float]) -> List[str]:
    """Compare file modification times to detect what changed."""
    changed = []
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=repo_path, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            changed = [f.strip() for f in r.stdout.strip().split('\n') if f.strip()]

        r2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=repo_path, timeout=10,
        )
        if r2.returncode == 0 and r2.stdout.strip():
            changed.extend([f.strip() for f in r2.stdout.strip().split('\n') if f.strip()])

        r3 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=repo_path, timeout=10,
        )
        if r3.returncode == 0 and r3.stdout.strip():
            changed.extend([f.strip() for f in r3.stdout.strip().split('\n') if f.strip()])

        if changed:
            return list(dict.fromkeys(changed))
    except Exception:
        pass

    after = {}
    skip = {'.git', '__pycache__', 'node_modules', '.claude'}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, repo_path)
            try:
                after[rel] = os.path.getmtime(full)
            except OSError:
                pass

    for rel, mtime in after.items():
        if rel not in before or before[rel] != mtime:
            changed.append(rel)

    return list(dict.fromkeys(changed))
