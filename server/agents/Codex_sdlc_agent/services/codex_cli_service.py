from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional


def codex_cli_binary() -> Optional[str]:
    explicit = os.environ.get("CODEX_CLI_PATH", "").strip()
    if explicit:
        return explicit
    return shutil.which("codex")


def codex_cli_available() -> bool:
    return codex_cli_binary() is not None


def codex_runtime_config() -> Dict[str, Any]:
    return {
        "cli_path": os.environ.get("CODEX_CLI_PATH", "").strip() or None,
        "model": os.environ.get("CODEX_MODEL", "").strip() or None,
        "profile": os.environ.get("CODEX_PROFILE", "").strip() or None,
        "sandbox": os.environ.get("CODEX_SANDBOX", "").strip() or None,
    }


async def run_codex_cli(
    prompt: str,
    cwd: str,
    sandbox: str = "workspace-write",
    model: Optional[str] = None,
    profile: Optional[str] = None,
    output_schema: Optional[str] = None,
    ephemeral: bool = True,
) -> Dict[str, Any]:
    """Run Codex CLI non-interactively and return the final message.

    Uses `--output-last-message` for the stable final text and captures stderr for diagnostics.
    """
    cli_binary = codex_cli_binary()
    if not cli_binary:
        return {
            "success": False,
            "result": "Codex CLI is not installed on this host.",
            "backend": "codex_cli",
        }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as tmp:
        output_file = tmp.name

    cmd = [cli_binary, "exec"] + [
        "--skip-git-repo-check",
        "--sandbox",
        sandbox,
        "--json",
        "--color",
        "never",
        "--cd",
        cwd,
        "--output-last-message",
        output_file,
    ]
    if ephemeral:
        cmd.append("--ephemeral")
    if model:
        cmd.extend(["--model", model])
    if profile:
        cmd.extend(["--profile", profile])
    if output_schema:
        cmd.extend(["--output-schema", output_schema])

    env = os.environ.copy()
    prompt_bytes = prompt.encode("utf-8") if prompt else None

    if sys.platform == "win32":
        cmd_str = subprocess.list2cmdline(cmd)
        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(input=prompt_bytes), timeout=600)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        try:
            Path(output_file).unlink(missing_ok=True)
        except Exception:
            pass
        return {
            "success": False,
            "result": "Codex CLI timed out after 10 minutes.",
            "stdout": "",
            "stderr": "",
            "backend": "codex_cli",
        }

    stdout_text = stdout.decode("utf-8", errors="replace").strip()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    try:
        result_text = Path(output_file).read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        result_text = ""
    finally:
        try:
            Path(output_file).unlink(missing_ok=True)
        except Exception:
            pass

    success = proc.returncode == 0 and bool(result_text)
    if not result_text:
        result_text = stderr_text or stdout_text or f"Codex CLI failed with exit code {proc.returncode}."

    return {
        "success": success,
        "result": result_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "backend": "codex_cli",
        "runtime_config": {
            "cli_path": cli_binary,
            "model": model,
            "profile": profile,
            "sandbox": sandbox,
        },
    }
