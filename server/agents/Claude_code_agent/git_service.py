"""Git operations for the Claude Code Agent — clone, branch, push, PR.

Handles authenticated GitHub operations using a personal access token. The
token is injected into the remote URL only at clone/push time and sanitized
out of any error messages we surface to the caller.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .memory_service import cleanup_snapshot_dir, restore_original_claude_md

GITHUB_URL_RE = re.compile(
    r"^https?://github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$"
)


# ---------------------------------------------------------------------------
# URL parsing + sanitization
# ---------------------------------------------------------------------------

def parse_github_url(repo_url: str) -> Optional[Tuple[str, str]]:
    match = GITHUB_URL_RE.match((repo_url or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _sanitize(text: str, token: str) -> str:
    if not text:
        return text or ""
    if not token:
        return text
    return text.replace(token, "***").replace(
        urllib.parse.quote(token, safe=""), "***"
    )


def _auth_url(owner: str, repo: str, token: str) -> str:
    return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"


def _run_git(args: List[str], cwd: str, token: str = "", timeout: int = 60) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    return subprocess.run(
        ["git"] + args,
        capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env,
    )


# ---------------------------------------------------------------------------
# Clone
# ---------------------------------------------------------------------------

def clone_repo(repo_url: str, dest_dir: Path, token: str = "") -> Dict[str, Any]:
    """Clone ``repo_url`` into ``dest_dir/<owner>_<repo>``.

    If a clone already exists at the target path, it's reset and updated rather
    than re-cloned, so cached memory + the local working copy stay aligned.
    """
    parsed = parse_github_url(repo_url)
    if not parsed:
        return {"success": False, "error": "Invalid GitHub URL"}

    owner, repo = parsed
    target = Path(dest_dir) / f"{owner}_{repo}"
    target.parent.mkdir(parents=True, exist_ok=True)

    clone_url = _auth_url(owner, repo, token) if token else f"https://github.com/{owner}/{repo}.git"

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"

    if (target / ".git").is_dir():
        # Reuse existing clone: hard-reset + pull to a clean state
        _run_git(["reset", "--hard", "HEAD"], str(target), token)
        _run_git(["clean", "-fdx"], str(target), token)
        # Switch to default branch
        head = _run_git(["remote", "show", "origin"], str(target), token, timeout=30)
        default = "main"
        if head.returncode == 0:
            m = re.search(r"HEAD branch:\s*(\S+)", head.stdout)
            if m:
                default = m.group(1)
        _run_git(["checkout", default], str(target), token)
        pull = subprocess.run(
            ["git", "pull", clone_url, default],
            capture_output=True, text=True, cwd=str(target), timeout=120, env=env,
        )
        if pull.returncode != 0:
            return {
                "success": False,
                "error": f"git pull failed: {_sanitize(pull.stderr, token)}",
            }
        return {
            "success": True, "path": str(target),
            "owner": owner, "name": repo, "default_branch": default, "reused": True,
        }

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    proc = subprocess.run(
        ["git", "clone", clone_url, str(target)],
        capture_output=True, text=True, timeout=300, env=env,
    )
    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"git clone failed: {_sanitize(proc.stderr, token)}",
        }

    head = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], str(target), token)
    default_branch = head.stdout.strip() if head.returncode == 0 else "main"

    return {
        "success": True, "path": str(target),
        "owner": owner, "name": repo, "default_branch": default_branch, "reused": False,
    }


# ---------------------------------------------------------------------------
# Branch + commit + push
# ---------------------------------------------------------------------------

def _branch_name_from_prompt(prompt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (prompt or "").lower())[:40].strip("-") or "update"
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return f"claude-code-agent/{slug}-{ts}"


def create_feature_branch(repo_path: str, prompt: str, token: str = "") -> Dict[str, Any]:
    """Create + check out a fresh feature branch BEFORE the CLI runs.

    Doing this up-front guarantees that any commit Claude Code makes during
    its run lands on the feature branch, never on the base branch.
    """
    branch = _branch_name_from_prompt(prompt)
    chk = _run_git(["checkout", "-b", branch], repo_path, token)
    if chk.returncode != 0:
        # Branch already exists locally — switch to it and reset to base HEAD
        sw = _run_git(["checkout", branch], repo_path, token)
        if sw.returncode != 0:
            return {
                "success": False,
                "error": f"Failed to create or switch to feature branch: {_sanitize(chk.stderr or sw.stderr, token)}",
            }
    return {"success": True, "branch": branch}


def push_changes(
    repo_path: str,
    repo_url: str,
    token: str,
    commit_message: str,
    base_branch: str,
    branch_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Stage, commit, and push changes to a new branch on GitHub."""
    parsed = parse_github_url(repo_url)
    if not parsed:
        return {"success": False, "error": "Invalid GitHub URL"}
    owner, repo = parsed

    # Strip internal artefacts so the managed memory block + snapshot dir
    # never land on the user's remote.
    acted, action = restore_original_claude_md(repo_path)
    if acted:
        print(f"[git] CLAUDE.md {action} pre-push")
    cleanup_snapshot_dir(repo_path)

    branch = branch_name or _branch_name_from_prompt(commit_message)

    _run_git(["config", "user.email", "claude-code-agent@users.noreply.github.com"], repo_path, token)
    _run_git(["config", "user.name", "Claude Code Agent"], repo_path, token)

    # The orchestrator creates the feature branch up-front (see
    # create_feature_branch). Switch to it if we're not already there; create
    # it as a last-resort fallback if it doesn't exist for some reason.
    sw = _run_git(["checkout", branch], repo_path, token)
    if sw.returncode != 0:
        _run_git(["checkout", "-b", branch], repo_path, token)

    # Hard-guard: never push to the base branch from this function.
    cur = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path, token)
    current_branch = (cur.stdout or "").strip()
    if current_branch == base_branch:
        return {
            "success": False,
            "error": (
                f"Refusing to push: HEAD is on base branch '{base_branch}'. "
                "A feature branch must be created before any push."
            ),
        }

    _run_git(["add", "-A"], repo_path, token)

    status = _run_git(["status", "--porcelain"], repo_path, token)
    if not status.stdout.strip():
        return {
            "success": True,
            "skipped": True,
            "message": "No changes to push — Claude Code did not modify any files.",
            "branch": branch,
        }

    commit = _run_git(["commit", "-m", commit_message], repo_path, token)
    if commit.returncode != 0:
        return {
            "success": False,
            "error": f"git commit failed: {_sanitize(commit.stderr, token)}",
        }

    push_url = _auth_url(owner, repo, token)
    push = _run_git(["push", push_url, branch], repo_path, token, timeout=180)
    if push.returncode != 0:
        # Retry with --force when the remote branch already exists from a prior run
        if "already exists" in (push.stderr or "").lower():
            push = _run_git(["push", "--force", push_url, branch], repo_path, token, timeout=180)
        if push.returncode != 0:
            return {
                "success": False,
                "error": f"git push failed: {_sanitize(push.stderr, token)}",
            }

    changed_files = [
        ln.strip().split(maxsplit=1)[-1]
        for ln in status.stdout.strip().splitlines()
        if ln.strip()
    ]

    compare_url = f"https://github.com/{owner}/{repo}/compare/{base_branch}...{branch}?expand=1"
    return {
        "success": True,
        "branch": branch,
        "files_pushed": changed_files,
        "compare_url": compare_url,
        "owner": owner,
        "repo": repo,
    }


# ---------------------------------------------------------------------------
# Pull request creation via GitHub REST API
# ---------------------------------------------------------------------------

def create_pull_request(
    owner: str,
    repo: str,
    token: str,
    head_branch: str,
    base_branch: str,
    title: str,
    body: str = "",
) -> Dict[str, Any]:
    """Open a PR head_branch -> base_branch via GitHub REST API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = json.dumps({
        "title": title[:250] or f"Claude Code Agent changes on {head_branch}",
        "head": head_branch,
        "base": base_branch,
        "body": body or "Automated changes by Claude Code Agent.",
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "claude-code-agent",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "success": True,
                "pr_url": data.get("html_url"),
                "pr_number": data.get("number"),
            }
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body)
            msg = err_json.get("message", err_body)
            errors = err_json.get("errors") or []
            # GitHub returns 422 when a PR for the same head/base already exists
            if e.code == 422 and any("already exists" in str(x).lower() for x in errors):
                return {
                    "success": True,
                    "pr_url": f"https://github.com/{owner}/{repo}/pulls?q=head%3A{head_branch}",
                    "already_exists": True,
                }
        except Exception:
            msg = str(e)
        return {"success": False, "error": _sanitize(f"GitHub API {e.code}: {msg}", token)}
    except Exception as e:
        return {"success": False, "error": _sanitize(str(e), token)}
