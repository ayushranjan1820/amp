from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional


def _run(command: List[str], cwd: str) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return {"success": proc.returncode == 0, "output": output, "command": command}
    except Exception as exc:
        return {"success": False, "output": str(exc), "command": command}


def get_git_diff(workspace_root: str) -> str:
    result = _run(["git", "diff"], workspace_root)
    return result["output"] if result["success"] else ""


def get_changed_files(workspace_root: str) -> List[str]:
    result = _run(["git", "diff", "--name-only"], workspace_root)
    if not result["success"]:
        return []
    return [line.strip() for line in result["output"].splitlines() if line.strip()]


def current_branch(workspace_root: str) -> Optional[str]:
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], workspace_root)
    if result["success"]:
        return result["output"].splitlines()[0].strip()
    return None
