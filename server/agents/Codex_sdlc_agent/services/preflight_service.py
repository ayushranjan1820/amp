from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


def _which(command: str) -> Optional[str]:
    return shutil.which(command)


def _check_command(command: str, required: bool = True) -> Dict[str, Any]:
    path = _which(command)
    if path:
        return {
            "status": "passed",
            "required": required,
            "message": f"{command} found",
            "path": path,
        }
    return {
        "status": "failed" if required else "warning",
        "required": required,
        "message": f"{command} not found in PATH",
        "path": None,
    }


def _check_python_module(module_name: str, required: bool = False) -> Dict[str, Any]:
    found = importlib.util.find_spec(module_name) is not None
    if found:
        return {
            "status": "passed",
            "required": required,
            "message": f"Python module '{module_name}' is available",
        }
    return {
        "status": "failed" if required else "warning",
        "required": required,
        "message": f"Python module '{module_name}' is missing",
    }


def _check_workspace_base_writable() -> Dict[str, Any]:
    raw = os.environ.get("CODEX_SDLC_WORKSPACE_BASE", "").strip()
    if raw:
        base = Path(raw).expanduser().resolve()
    else:
        base = (Path(__file__).resolve().parents[3] / "repos" / "_codex_sdlc_runs").resolve()

    try:
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="preflight_", dir=str(base), delete=True):
            pass
        return {
            "status": "passed",
            "message": "Isolated workspace base is writable",
            "path": str(base),
            "from_env": bool(raw),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"Isolated workspace base is not writable: {exc}",
            "path": str(base),
            "from_env": bool(raw),
        }


def _run_codex_smoke(cwd: str, timeout_sec: int = 60) -> Dict[str, Any]:
    codex = _which("codex")
    if not codex:
        return {
            "status": "failed",
            "message": "codex not found; smoke test skipped",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }

    cmd = [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--json",
        "--cd",
        cwd,
        "Reply with OK only",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "failed",
            "message": f"codex smoke test timed out after {timeout_sec}s",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "message": f"codex smoke test failed to execute: {exc}",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
        }

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    merged = "\n".join([x for x in [out, err] if x]).lower()

    if proc.returncode == 0:
        return {
            "status": "passed",
            "message": "codex smoke test succeeded",
            "exit_code": 0,
            "stdout": out[:3000],
            "stderr": err[:3000],
        }

    if "usage limit" in merged or "upgrade to plus" in merged:
        return {
            "status": "failed",
            "message": "codex is installed but quota/auth is not currently usable on this host",
            "exit_code": proc.returncode,
            "stdout": out[:3000],
            "stderr": err[:3000],
        }

    return {
        "status": "failed",
        "message": "codex smoke test failed",
        "exit_code": proc.returncode,
        "stdout": out[:3000],
        "stderr": err[:3000],
    }


def _status_score(status: str) -> int:
    if status == "passed":
        return 0
    if status == "warning":
        return 1
    return 2


def _overall_status(checks: List[Dict[str, Any]]) -> str:
    worst = max((_status_score(c.get("status", "failed")) for c in checks), default=2)
    if worst == 0:
        return "ready"
    if worst == 1:
        return "degraded"
    return "blocked"


def run_codex_sdlc_preflight(include_smoke: bool = False, cwd: Optional[str] = None) -> Dict[str, Any]:
    run_cwd = str(Path(cwd or Path(__file__).resolve().parents[3]).resolve())

    checks: List[Dict[str, Any]] = []
    checks.append({"name": "codex_cli", **_check_command("codex", required=True)})
    checks.append({"name": "git", **_check_command("git", required=True)})
    checks.append({"name": "python", **_check_command("python", required=True)})

    checks.append({"name": "npm", **_check_command("npm", required=False)})
    checks.append({"name": "npx", **_check_command("npx", required=False)})
    checks.append({"name": "pytest", **_check_python_module("pytest", required=False)})
    checks.append({"name": "ruff", **_check_python_module("ruff", required=False)})
    checks.append({"name": "bandit", **_check_python_module("bandit", required=False)})
    checks.append({"name": "pip_audit", **_check_python_module("pip_audit", required=False)})
    checks.append({"name": "semgrep", **_check_command("semgrep", required=False)})

    isolated_enabled = os.environ.get("CODEX_SDLC_ISOLATED_WORKSPACE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if isolated_enabled:
        checks.append({"name": "workspace_base", **_check_workspace_base_writable()})
    else:
        checks.append(
            {
                "name": "workspace_isolation",
                "status": "warning",
                "required": False,
                "message": "CODEX_SDLC_ISOLATED_WORKSPACE is disabled",
            }
        )

    runtime = {
        "CODEX_CLI_PATH": os.environ.get("CODEX_CLI_PATH", "").strip() or None,
        "CODEX_MODEL": os.environ.get("CODEX_MODEL", "").strip() or None,
        "CODEX_PROFILE": os.environ.get("CODEX_PROFILE", "").strip() or None,
        "CODEX_SANDBOX": os.environ.get("CODEX_SANDBOX", "").strip() or None,
        "CODEX_SDLC_ISOLATED_WORKSPACE": isolated_enabled,
        "CODEX_SDLC_WORKSPACE_BASE": os.environ.get("CODEX_SDLC_WORKSPACE_BASE", "").strip() or None,
    }

    smoke = None
    if include_smoke:
        smoke = _run_codex_smoke(cwd=run_cwd)
        checks.append({"name": "codex_smoke", **smoke})

    status = _overall_status(checks)
    required_failures = [c for c in checks if c.get("required") and c.get("status") == "failed"]

    summary = "Codex SDLC preflight is ready"
    if status == "blocked":
        summary = "Codex SDLC preflight found blocking issues"
    elif status == "degraded":
        summary = "Codex SDLC preflight passed with warnings"

    return {
        "status": status,
        "summary": summary,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "cwd": run_cwd,
        "required_failures": [c["name"] for c in required_failures],
        "checks": checks,
        "runtime": runtime,
        "smoke": smoke,
    }


def preflight_as_json(include_smoke: bool = False, cwd: Optional[str] = None) -> str:
    payload = run_codex_sdlc_preflight(include_smoke=include_smoke, cwd=cwd)
    return json.dumps(payload, indent=2)
