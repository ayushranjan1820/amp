from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List


def _run(command: List[str], cwd: str, timeout: int = 180) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return {"success": proc.returncode == 0, "output": output[:4000], "command": command}
    except FileNotFoundError:
        return {"success": False, "output": "Command not found", "command": command}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": f"Timed out after {timeout}s", "command": command}


def run_security_checks(workspace_root: str) -> Dict[str, Any]:
    root = Path(workspace_root)
    checks: List[Dict[str, Any]] = []

    if (root / "package.json").exists():
        checks.append(_run(["npm", "audit", "--audit-level=high"], workspace_root, timeout=240))

    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        checks.append(_run(["python", "-m", "bandit", "-q", "-r", "."], workspace_root))
        checks.append(_run(["python", "-m", "pip_audit"], workspace_root))

    checks.append(_run(["semgrep", "--config", "auto", "."], workspace_root, timeout=240))

    usable = [c for c in checks if c["output"] != "Command not found"]
    if not usable:
        return {"status": "skipped", "details": "No security scanner available in this environment.", "checks": checks}

    failed = [c for c in usable if not c["success"]]
    if failed:
        return {"status": "failed", "details": failed[0]["output"], "checks": usable}
    return {"status": "passed", "details": "Available security checks passed.", "checks": usable}

