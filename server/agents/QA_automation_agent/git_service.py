"""Git operations for the QA Automation Agent.

Unlike the Claude Code Agent (which works on the default branch and opens a
new PR), this agent operates *on* an existing Pull Request: it clones the PR
head repo, checks out the PR head branch, and pushes generated automation
scripts back to the same branch so they appear as additional commits on the
PR.

The clone path is intentionally over-engineered for resilience:

1. **Reuse path** — refresh-in-place (works for re-runs on the same PR).
2. **Fresh-clone path** — used when reuse fails or no clone exists yet.
   Clones with the full default refspec (no ``--single-branch``) so any
   subsequent re-run can switch branches without rewriting refspecs.
3. **Claude-Code-CLI fallback** — if both of the above fail, we hand the
   workspace to the Claude Code CLI with a tightly-scoped prompt and let
   its agentic Bash + Read loop figure out the right git incantation.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _auth_url(owner: str, repo: str, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def _sanitize(text: str, token: str) -> str:
    if not text:
        return text or ""
    if not token:
        return text
    return text.replace(token, "***").replace(
        urllib.parse.quote(token, safe=""), "***"
    )


def _run_git(
    args: List[str], cwd: str, timeout: int = 120
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    return subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env=env,
    )


def _git_step(args: List[str], cwd: str, token: str, timeout: int = 120) -> Dict[str, Any]:
    proc = _run_git(args, cwd, timeout=timeout)
    return {
        "ok": proc.returncode == 0,
        "stdout": _sanitize(proc.stdout, token),
        "stderr": _sanitize(proc.stderr, token),
        "args": args,
    }


# ---------------------------------------------------------------------------
# Reuse / fresh-clone primitives
# ---------------------------------------------------------------------------

def _refresh_existing_clone(
    target: Path, branch: str, clone_url: str, token: str
) -> Dict[str, Any]:
    """Reset, fetch, and check out ``branch`` in an existing clone.

    Robust against single-branch clones whose refspec doesn't cover the
    requested branch: we widen the refspec, fetch all branches, and check
    out via ``FETCH_HEAD`` so we don't depend on ``origin/<branch>``
    actually existing as a remote-tracking ref.
    """
    cwd = str(target)
    log: List[Dict[str, Any]] = []

    log.append(_git_step(["reset", "--hard", "HEAD"], cwd, token))
    log.append(_git_step(["clean", "-fdx"], cwd, token))
    log.append(_git_step(["remote", "set-url", "origin", clone_url], cwd, token))
    # Widen the fetch refspec so future branch switches work even if the
    # original clone was --single-branch.
    log.append(_git_step(
        ["config", "remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*"],
        cwd, token,
    ))

    fetch = _git_step(["fetch", "--prune", "origin", branch], cwd, token, timeout=180)
    log.append(fetch)
    if not fetch["ok"]:
        return {"ok": False, "error": f"git fetch failed: {fetch['stderr']}", "log": log}

    # Try the standard ref first, then fall back to FETCH_HEAD which is
    # always populated by the fetch above.
    chk = _git_step(["checkout", "-B", branch, f"origin/{branch}"], cwd, token)
    if not chk["ok"]:
        log.append(chk)
        chk = _git_step(["checkout", "-B", branch, "FETCH_HEAD"], cwd, token)
    log.append(chk)
    if not chk["ok"]:
        return {"ok": False, "error": f"git checkout failed: {chk['stderr']}", "log": log}

    return {"ok": True, "log": log}


def _fresh_clone(
    target: Path, branch: str, clone_url: str, token: str
) -> Dict[str, Any]:
    """Wipe ``target`` and do a normal clone, then check out ``branch``.

    A normal clone (no ``--single-branch``) keeps the default refspec
    so subsequent runs can switch branches cheaply.
    """
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.run(
        ["git", "clone", clone_url, str(target)],
        capture_output=True, text=True, timeout=300,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "echo"},
    )
    log: List[Dict[str, Any]] = [{
        "ok": proc.returncode == 0,
        "stdout": _sanitize(proc.stdout, token),
        "stderr": _sanitize(proc.stderr, token),
        "args": ["clone", clone_url, str(target)],
    }]
    if proc.returncode != 0:
        return {"ok": False, "error": f"git clone failed: {_sanitize(proc.stderr, token)}", "log": log}

    cwd = str(target)
    fetch = _git_step(["fetch", "--prune", "origin", branch], cwd, token, timeout=180)
    log.append(fetch)
    if not fetch["ok"]:
        return {"ok": False, "error": f"git fetch failed: {fetch['stderr']}", "log": log}

    chk = _git_step(["checkout", "-B", branch, f"origin/{branch}"], cwd, token)
    if not chk["ok"]:
        log.append(chk)
        chk = _git_step(["checkout", "-B", branch, "FETCH_HEAD"], cwd, token)
    log.append(chk)
    if not chk["ok"]:
        return {"ok": False, "error": f"git checkout failed: {chk['stderr']}", "log": log}

    return {"ok": True, "log": log}


# ---------------------------------------------------------------------------
# Claude-Code-CLI self-healing fallback
# ---------------------------------------------------------------------------

async def _claude_code_recover_clone(
    target: Path,
    owner: str,
    repo: str,
    branch: str,
    token: str,
    api_key: str,
    earlier_errors: List[str],
    emit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Last-resort: hand the broken workspace to the Claude Code CLI.

    Claude Code can run arbitrary ``git`` / shell commands via Bash, so it
    can diagnose whatever weird state we're in (bad refspec, dirty tree,
    detached HEAD, missing remote, lock files, etc.) and put the working
    tree on ``branch`` of ``owner/repo``.
    """
    # Lazy import so the regular path doesn't pay the import cost.
    from agents.Claude_code_agent.claude_service import run_claude_code

    # Make sure there's *some* directory for Claude Code to chdir into.
    workspace = target if target.exists() else target.parent
    workspace.mkdir(parents=True, exist_ok=True)

    auth_url = _auth_url(owner, repo, token)
    safe_url = f"https://github.com/{owner}/{repo}.git"
    errors_block = "\n".join(f"- {e}" for e in earlier_errors[-5:]) or "(none captured)"

    prompt = f"""You are recovering a broken local clone of a GitHub
repository so a downstream test-generation step can run inside it.

## Goal
Make the directory at the current working directory be a clean working
copy of the repository **{owner}/{repo}** with the branch
**{branch}** checked out. The branch already exists on the remote.

## Authenticated remote (use this exact URL when fetching/setting origin)
`{auth_url}`

(Equivalent unauthenticated URL — for log messages only — is
`{safe_url}`.)

## What you can do
- Run shell commands via Bash: `git`, `ls`, `cat`, `rm`, `mv`, etc.
- Read files (e.g. `.git/config`, `.git/HEAD`).
- Edit files **only** if a git config file or hook is the actual problem.

## What we already tried and what failed
{errors_block}

## Your tactics (try in order, stop as soon as one works)

1. If the current directory is a git repo, try to repair it:
   - `git reset --hard HEAD` (ignore errors)
   - `git clean -fdx`
   - `git remote set-url origin "{auth_url}"`
   - `git config remote.origin.fetch "+refs/heads/*:refs/remotes/origin/*"`
   - `git fetch --prune origin "{branch}"`
   - `git checkout -B "{branch}" "origin/{branch}"`
     (if that fails, try `git checkout -B "{branch}" FETCH_HEAD`)
2. If repair fails, nuke the directory contents and re-clone:
   - On Windows: `cmd /c rd /s /q .` from the parent, or
     remove every file/dir individually if a `.git` lock prevents that.
   - On POSIX: `rm -rf <dir>` from the parent.
   - Then `git clone "{auth_url}" <dir>` and check out `{branch}`.
3. Verify success with:
   - `git rev-parse --abbrev-ref HEAD` → must print exactly `{branch}`
   - `git status` → must show a clean working tree

## Constraints
- Do NOT modify any source files.
- Do NOT push, force-push, or create new branches.
- Do NOT print or echo the access token. Use the `{auth_url}`
  URL value directly in commands; never copy the token elsewhere.
- Stop as soon as `git rev-parse --abbrev-ref HEAD` returns
  `{branch}` and the working tree is clean.

When done, output a one-line summary of what you ran and the final
state.
"""

    cli = await run_claude_code(
        prompt=prompt,
        repo_path=str(workspace),
        anthropic_api_key=api_key,
        emit=emit,
        # No Edit/Write needed for normal recovery, but allowed for the rare
        # case where a hook/.git config is the actual blocker.
        allowed_tools="Bash,Read,Edit,Glob,Grep",
    )

    if not cli.get("success"):
        return {
            "ok": False,
            "error": f"Claude-Code recovery failed: {cli.get('error') or 'unknown error'}",
            "summary": cli.get("summary", ""),
        }

    # Verify ourselves — never trust the agent's word for it.
    if not (target / ".git").is_dir():
        return {
            "ok": False,
            "error": (
                "Claude-Code recovery returned success but no .git directory "
                f"exists at {target}."
            ),
            "summary": cli.get("summary", ""),
        }
    head = _git_step(["rev-parse", "--abbrev-ref", "HEAD"], str(target), token)
    if not head["ok"] or head["stdout"].strip() != branch:
        return {
            "ok": False,
            "error": (
                f"Claude-Code recovery did not leave HEAD on `{branch}` "
                f"(got `{head['stdout'].strip()}`)."
            ),
            "summary": cli.get("summary", ""),
        }
    return {"ok": True, "summary": cli.get("summary", ""), "via": "claude_code_cli"}


# ---------------------------------------------------------------------------
# Public clone API
# ---------------------------------------------------------------------------

async def clone_pr_branch(
    owner: str,
    repo: str,
    branch: str,
    dest_dir: Path,
    token: str,
    *,
    anthropic_api_key: Optional[str] = None,
    emit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Clone (or refresh) ``owner/repo`` and check out ``branch``.

    Tries — in order — refresh-in-place, fresh re-clone, and finally a
    Claude-Code-CLI driven recovery (if ``anthropic_api_key`` is supplied).

    Returns ``{"success", "path", "branch", "reused", "recovered_via"}``.
    """
    if not token:
        return {"success": False, "error": "GitHub token is required to clone."}

    target = Path(dest_dir) / f"{owner}_{repo}"
    target.parent.mkdir(parents=True, exist_ok=True)
    clone_url = _auth_url(owner, repo, token)

    errors: List[str] = []

    # 1. Reuse
    if (target / ".git").is_dir():
        refresh = _refresh_existing_clone(target, branch, clone_url, token)
        if refresh.get("ok"):
            return {
                "success": True,
                "path": str(target),
                "branch": branch,
                "reused": True,
            }
        errors.append(f"refresh: {refresh.get('error')}")
        if emit:
            try:
                emit({
                    "type": "thinking",
                    "content": (
                        f"Refresh of existing clone failed ({refresh.get('error')}). "
                        "Falling back to a fresh clone."
                    ),
                })
            except Exception:
                pass

    # 2. Fresh re-clone
    fresh = _fresh_clone(target, branch, clone_url, token)
    if fresh.get("ok"):
        return {
            "success": True,
            "path": str(target),
            "branch": branch,
            "reused": False,
        }
    errors.append(f"fresh-clone: {fresh.get('error')}")

    # 3. Claude-Code-CLI fallback
    if not anthropic_api_key:
        return {
            "success": False,
            "error": (
                "Clone/checkout failed and no ANTHROPIC_API_KEY available "
                "for Claude-Code recovery. Errors: " + " | ".join(errors)
            ),
        }
    if emit:
        try:
            emit({
                "type": "thinking",
                "content": (
                    "Standard git operations failed. Invoking Claude Code CLI "
                    "to self-heal the clone."
                ),
            })
        except Exception:
            pass
    recover = await _claude_code_recover_clone(
        target, owner, repo, branch, token, anthropic_api_key, errors, emit=emit,
    )
    if recover.get("ok"):
        return {
            "success": True,
            "path": str(target),
            "branch": branch,
            "reused": False,
            "recovered_via": "claude_code_cli",
        }
    return {
        "success": False,
        "error": (
            "All recovery attempts failed. " + recover.get("error", "")
            + " | Earlier errors: " + " | ".join(errors)
        ),
    }


# ---------------------------------------------------------------------------
# Push API (with the same self-healing fallback)
# ---------------------------------------------------------------------------

async def push_to_pr_branch(
    repo_path: str,
    owner: str,
    repo: str,
    branch: str,
    token: str,
    commit_message: str,
    *,
    anthropic_api_key: Optional[str] = None,
    emit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Stage, commit, and push changes onto ``branch``.

    Falls back to a Claude-Code-CLI recovery run if standard git fails.
    """
    _run_git(["config", "user.email", "qa-automation-agent@users.noreply.github.com"], repo_path)
    _run_git(["config", "user.name", "QA Automation Agent"], repo_path)

    _run_git(["add", "-A"], repo_path)

    status = _run_git(["status", "--porcelain"], repo_path)
    if not status.stdout.strip():
        return {
            "success": True,
            "skipped": True,
            "files_pushed": [],
            "message": "No changes to push — Claude Code did not modify any files.",
        }

    changed_files = [
        ln.strip().split(maxsplit=1)[-1]
        for ln in status.stdout.strip().splitlines()
        if ln.strip()
    ]

    commit = _run_git(["commit", "-m", commit_message], repo_path)
    if commit.returncode != 0:
        return {
            "success": False,
            "error": f"git commit failed: {_sanitize(commit.stderr, token)}",
        }

    push_url = _auth_url(owner, repo, token)
    push = _run_git(["push", push_url, f"HEAD:{branch}"], repo_path, timeout=180)
    if push.returncode == 0:
        return {
            "success": True,
            "branch": branch,
            "files_pushed": changed_files,
        }

    push_err = _sanitize(push.stderr, token)

    # Try Claude-Code-CLI recovery before giving up.
    if not anthropic_api_key:
        return {
            "success": False,
            "error": f"git push failed: {push_err}",
        }

    if emit:
        try:
            emit({
                "type": "thinking",
                "content": (
                    f"git push failed ({push_err[:200]}). Invoking Claude Code "
                    "CLI to self-heal and retry."
                ),
            })
        except Exception:
            pass

    from agents.Claude_code_agent.claude_service import run_claude_code

    auth_url = push_url
    prompt = f"""You are recovering a failed `git push` so the latest
local commit on this working copy lands on the remote branch
**{branch}** of repository **{owner}/{repo}**.

## What you can do
- Run shell commands via Bash: `git`, `ls`, `cat`, etc.

## Authenticated push URL (use this exact value)
`{auth_url}`

## What we already tried
- `git push <auth-url> HEAD:{branch}` failed with:
  `{push_err[:400]}`

## Tactics (try in order)
1. Check `git status`. If there's an unfinished merge/rebase, abort it
   (`git merge --abort` / `git rebase --abort`) and re-stage the
   intended changes.
2. Pull with rebase to resolve non-fast-forward:
   `git fetch "{auth_url}" {branch}` then
   `git rebase FETCH_HEAD` and retry the push.
3. If the failure is due to LFS, hooks, or large files, identify and
   skip the offending file(s) and re-commit (do NOT skip hooks with
   --no-verify).
4. Retry: `git push "{auth_url}" HEAD:{branch}`.

## Constraints
- Never force-push.
- Never modify source files.
- Never echo or print the access token.
- Stop as soon as `git push "{auth_url}" HEAD:{branch}` succeeds.

Output a one-line summary at the end.
"""
    cli = await run_claude_code(
        prompt=prompt,
        repo_path=repo_path,
        anthropic_api_key=anthropic_api_key,
        emit=emit,
        allowed_tools="Bash,Read,Edit,Glob,Grep",
    )

    if not cli.get("success"):
        return {
            "success": False,
            "error": (
                f"git push failed: {push_err}. Claude-Code recovery also "
                f"failed: {cli.get('error') or 'unknown error'}"
            ),
        }

    # Verify the push actually landed.
    verify = _run_git(["ls-remote", auth_url, f"refs/heads/{branch}"], repo_path, timeout=60)
    local_head = _run_git(["rev-parse", "HEAD"], repo_path)
    remote_sha = (verify.stdout.split()[0] if verify.stdout.strip() else "").strip()
    local_sha = local_head.stdout.strip()
    if not remote_sha or remote_sha != local_sha:
        return {
            "success": False,
            "error": (
                "Claude-Code push recovery returned success but the remote "
                f"`{branch}` SHA does not match local HEAD."
            ),
        }
    return {
        "success": True,
        "branch": branch,
        "files_pushed": changed_files,
        "recovered_via": "claude_code_cli",
    }
