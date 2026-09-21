"""Clone a remote git repository for the Workspace context Agent.

Accepts GitHub / GitLab / Bitbucket / generic HTTPS URLs. Clones into
``repos/<session>/<owner>_<repo>/`` (sibling to the project's existing repos
directory). If a clone already exists for the same URL it is fast-forwarded
rather than re-cloned, so the TF-IDF index cache stays valid more often.

Tokens, when supplied, are injected only into the URL passed to ``git`` and
never written to disk. Error output is sanitized so the token cannot leak
upstream.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CLONES_ROOT = _PROJECT_ROOT / "repos"

_GENERIC_URL_RE = re.compile(
    r"^https?://([\w.\-]+)/([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$"
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

def parse_repo_url(repo_url: str) -> Optional[Tuple[str, str, str]]:
    """Return ``(host, owner, repo)`` or None for an unrecognized URL."""
    m = _GENERIC_URL_RE.match((repo_url or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def _sanitize(text: str, token: str) -> str:
    if not text or not token:
        return text or ""
    return text.replace(token, "***").replace(
        urllib.parse.quote(token, safe=""), "***"
    )


def _auth_url(host: str, owner: str, repo: str, token: str) -> str:
    """Inject a token into a generic git HTTPS URL.

    GitHub uses the documented ``x-access-token`` user; for other hosts we
    pass the token as the password and leave the username empty, which works
    for GitLab/Bitbucket personal access tokens.
    """
    if host.endswith("github.com"):
        return f"https://x-access-token:{token}@{host}/{owner}/{repo}.git"
    return f"https://oauth2:{token}@{host}/{owner}/{repo}.git"


def _git_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = "echo"
    return env


def _run(args: list, cwd: Optional[str] = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
        env=_git_env(),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def clone_or_refresh(
    repo_url: str,
    session_id: str,
    token: str = "",
    branch: Optional[str] = None,
    clones_root: Optional[Path] = None,
    shallow: bool = True,
) -> Dict[str, Any]:
    """Clone ``repo_url`` (or refresh an existing clone) for ``session_id``.

    Returns a dict ``{success, path?, owner?, name?, default_branch?, head_sha?,
    reused?, error?}``.
    """
    parsed = parse_repo_url(repo_url)
    if not parsed:
        return {"success": False, "error": "Unrecognized repository URL."}
    host, owner, repo = parsed

    root = (clones_root or _DEFAULT_CLONES_ROOT) / f"session-{session_id}"
    target = root / f"{owner}_{repo}"
    root.mkdir(parents=True, exist_ok=True)

    auth_url = _auth_url(host, owner, repo, token) if token else f"https://{host}/{owner}/{repo}.git"

    if (target / ".git").is_dir():
        # Refresh existing clone
        _run(["reset", "--hard", "HEAD"], cwd=str(target))
        _run(["clean", "-fdx"], cwd=str(target))

        default = branch or _detect_default_branch(str(target))
        _run(["checkout", default], cwd=str(target))

        pull = subprocess.run(
            ["git", "pull", auth_url, default],
            capture_output=True, text=True,
            cwd=str(target), timeout=180, env=_git_env(),
        )
        if pull.returncode != 0:
            return {
                "success": False,
                "error": f"git pull failed: {_sanitize(pull.stderr, token)}",
            }
        head_sha = _head_sha(str(target))
        return {
            "success": True,
            "path": str(target),
            "host": host,
            "owner": owner,
            "name": repo,
            "default_branch": default,
            "head_sha": head_sha,
            "reused": True,
        }

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    clone_args = ["clone"]
    if shallow:
        clone_args += ["--depth", "1"]
    if branch:
        clone_args += ["--branch", branch]
    clone_args += [auth_url, str(target)]

    proc = subprocess.run(
        ["git"] + clone_args,
        capture_output=True, text=True, timeout=600, env=_git_env(),
    )
    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"git clone failed: {_sanitize(proc.stderr, token)}",
        }

    default = branch or _detect_current_branch(str(target)) or "main"
    head_sha = _head_sha(str(target))

    return {
        "success": True,
        "path": str(target),
        "host": host,
        "owner": owner,
        "name": repo,
        "default_branch": default,
        "head_sha": head_sha,
        "reused": False,
    }


def _detect_default_branch(repo_path: str) -> str:
    info = _run(["remote", "show", "origin"], cwd=repo_path, timeout=30)
    if info.returncode == 0:
        m = re.search(r"HEAD branch:\s*(\S+)", info.stdout)
        if m:
            return m.group(1)
    return _detect_current_branch(repo_path) or "main"


def _detect_current_branch(repo_path: str) -> Optional[str]:
    p = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def _head_sha(repo_path: str) -> Optional[str]:
    p = _run(["rev-parse", "HEAD"], cwd=repo_path)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None
