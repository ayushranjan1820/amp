from __future__ import annotations

import json
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
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return {"success": proc.returncode == 0, "command": command, "output": output.strip()}
    except FileNotFoundError:
        return {"success": False, "command": command, "output": "Command not found"}
    except subprocess.TimeoutExpired:
        return {"success": False, "command": command, "output": f"Timed out after {timeout}s"}


def detect_test_commands(workspace_root: str) -> List[List[str]]:
    root = Path(workspace_root)
    commands: List[List[str]] = []
    package_json = root / "package.json"
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"

    if package_json.exists():
        try:
            pkg = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            if "test" in scripts:
                commands.append(["npm", "test", "--", "--runInBand"])
            elif "vitest" in json.dumps(pkg.get("devDependencies", {})).lower():
                commands.append(["npx", "vitest", "run"])
        except Exception:
            commands.append(["npm", "test", "--", "--runInBand"])

    if pyproject.exists() or requirements.exists() or (root / "pytest.ini").exists():
        commands.append(["python", "-m", "pytest", "-q"])

    return commands


def run_tests(workspace_root: str) -> Dict[str, Any]:
    commands = detect_test_commands(workspace_root)
    if not commands:
        return {"status": "skipped", "details": "No test command detected."}

    results = []
    for cmd in commands:
        result = _run(cmd, workspace_root)
        results.append(result)
        if not result["success"]:
            return {
                "status": "failed",
                "details": result["output"][:4000],
                "command": cmd,
                "results": results,
            }
    return {"status": "passed", "details": "All detected test commands passed.", "results": results}


def run_lint(workspace_root: str) -> Dict[str, Any]:
    root = Path(workspace_root)
    candidates: List[List[str]] = []
    if (root / "package.json").exists():
        candidates.append(["npm", "run", "lint"])
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        candidates.append(["python", "-m", "ruff", "check", "."])

    for cmd in candidates:
        result = _run(cmd, workspace_root, timeout=120)
        if result["success"]:
            return {"status": "passed", "details": "Lint passed.", "command": cmd}
        if "Command not found" not in result["output"]:
            return {"status": "failed", "details": result["output"][:4000], "command": cmd}
    return {"status": "skipped", "details": "No lint command available."}

