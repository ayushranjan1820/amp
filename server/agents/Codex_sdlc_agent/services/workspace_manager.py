from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple


IGNORE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
}


def isolated_workspaces_enabled() -> bool:
    return os.environ.get("CODEX_SDLC_ISOLATED_WORKSPACE", "false").strip().lower() in {
        "1", "true", "yes", "on"
    }


def isolated_workspace_base() -> Path:
    raw = os.environ.get("CODEX_SDLC_WORKSPACE_BASE", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "repos" / "_codex_sdlc_runs").resolve()


def create_isolated_workspace(source_root: str, run_id: str) -> Tuple[str, str]:
    """Create an isolated working copy for a run.

    Prefer a local git clone when the source is a git repo; otherwise copy files.
    Returns `(workspace_path, mode)`.
    """
    src = Path(source_root).resolve()
    base = isolated_workspace_base()
    target = base / run_id / src.name
    target.parent.mkdir(parents=True, exist_ok=True)

    git_dir = src / ".git"
    if git_dir.exists():
        result = subprocess.run(
            ["git", "clone", "--local", str(src), str(target)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            return str(target), "git-clone"

    shutil.copytree(
        src,
        target,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*IGNORE_NAMES),
    )
    return str(target), "copytree"
