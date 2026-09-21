"""Claude Code CLI runner.

Wraps ``npx @anthropic-ai/claude-code -p`` in non-interactive print mode and
captures the stream-json output so we can:

* surface live activity (which file is being read/edited, which command is
  running) back to the caller as ``thinking_steps``;
* detect exactly which files Claude Code created or modified by snapshotting
  ``mtime``s before/after the run;
* enforce a wall-clock timeout that kills the whole process tree on
  Windows (``taskkill /T /F``) and POSIX (``killpg`` after ``setsid``);
* sanitize the API key out of any error message we surface.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_IS_WINDOWS = platform.system() == "Windows"

FALLBACK_MODEL = "claude-sonnet-4-5"


def _current_default_model() -> str:
    return (os.getenv("CLAUDE_CODE_MODEL") or "").strip() or FALLBACK_MODEL


def _current_allowed_tools() -> str:
    return (os.getenv("CLAUDE_CODE_ALLOWED_TOOLS") or "").strip() or "Read,Write,Edit,Bash,Glob,Grep"


def _current_max_budget_usd() -> float:
    raw = os.getenv("CLAUDE_CODE_MAX_BUDGET_USD")
    try:
        return float(raw) if raw is not None and raw.strip() else 10.0
    except ValueError:
        return 10.0


def _current_timeout_seconds() -> int:
    raw = os.getenv("CLAUDE_CODE_TIMEOUT_SECONDS")
    try:
        return int(raw) if raw is not None and raw.strip() else 1800
    except ValueError:
        return 1800

SNAPSHOT_SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".cache", "target", ".claude_code_agent",
})


# ---------------------------------------------------------------------------
# File-change detection
# ---------------------------------------------------------------------------

def snapshot_mtimes(repo_path: str) -> Dict[str, float]:
    snap: Dict[str, float] = {}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SNAPSHOT_SKIP_DIRS]
        for f in files:
            full = os.path.join(root, f)
            try:
                snap[full] = os.path.getmtime(full)
            except OSError:
                pass
    return snap


def detect_changes(repo_path: str, before: Dict[str, float]) -> List[Dict[str, Any]]:
    after = snapshot_mtimes(repo_path)
    changes: List[Dict[str, Any]] = []
    for full, mtime in after.items():
        rel = os.path.relpath(full, repo_path)
        if full not in before:
            changes.append({"file_path": rel, "action": "create"})
        elif mtime > before[full]:
            changes.append({"file_path": rel, "action": "modify"})
    return changes


# ---------------------------------------------------------------------------
# Process-tree kill (cross-platform)
# ---------------------------------------------------------------------------

def _build_popen_kwargs() -> Dict[str, Any]:
    if _IS_WINDOWS:
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}
    return {"start_new_session": True}


def _kill_process_tree(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        if _IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=10, check=False,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _sanitize(text: Optional[str], api_key: str) -> Optional[str]:
    if not text:
        return text
    if api_key and api_key in text:
        text = text.replace(api_key, "***")
    return text[:2000]


# ---------------------------------------------------------------------------
# Stream parsing
# ---------------------------------------------------------------------------

@dataclass
class _RunState:
    total_cost: float = 0.0
    duration_ms: int = 0
    error_msg: Optional[str] = None
    summary_chunks: List[str] = field(default_factory=list)
    final_result_text: str = ""
    last_tool_name: str = ""


def _parse_event(line: str) -> Optional[Dict[str, Any]]:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _handle_event(
    event: Dict[str, Any],
    repo_path: str,
    state: _RunState,
    emit: Callable[[Dict[str, Any]], None],
) -> None:
    evt_type = event.get("type", "")

    if evt_type == "system":
        emit({"type": "thinking", "content": "Claude Code session connected."})
        return

    if evt_type == "assistant":
        for block in event.get("message", {}).get("content", []) or []:
            btype = block.get("type", "")
            if btype == "tool_use":
                _handle_tool_use(block, repo_path, state, emit)
            elif btype in ("thinking", "text"):
                key = "thinking" if btype == "thinking" else "text"
                txt = (block.get(key) or "").strip()
                if txt:
                    state.summary_chunks.append(txt[:16000])
                    emit({"type": "thinking", "content": txt[:2000]})
                    if len(state.summary_chunks) > 100:
                        del state.summary_chunks[:50]
        return

    if evt_type == "user":
        for block in event.get("message", {}).get("content", []) or []:
            if block.get("type") != "tool_result":
                continue
            content = block.get("content", "")
            if isinstance(content, list):
                content = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
            if isinstance(content, str) and content.strip():
                emit({
                    "type": "tool_result",
                    "content": content.strip()[:1200],
                    "tool_name": state.last_tool_name,
                })
        return

    if evt_type == "result":
        state.total_cost = float(event.get("total_cost_usd", 0.0) or 0.0)
        state.duration_ms = int(event.get("duration_ms", 0) or 0)
        result_text = event.get("result")
        if isinstance(result_text, str) and result_text.strip():
            state.final_result_text = result_text
        if event.get("is_error") or str(event.get("subtype", "")).startswith("error"):
            state.error_msg = result_text or "Claude Code finished with error"
        return

    raw = json.dumps(event, ensure_ascii=False, default=str)
    if len(raw) > 1600:
        raw = raw[:1597] + "..."
    emit({"type": "thinking", "content": f"[{evt_type or 'stream-json'}] {raw}"})


def _handle_tool_use(
    block: Dict[str, Any],
    repo_path: str,
    state: _RunState,
    emit: Callable[[Dict[str, Any]], None],
) -> None:
    name = block.get("name", "")
    inp = block.get("input", {}) or {}
    state.last_tool_name = name

    if name in ("Write", "Edit"):
        fp = inp.get("file_path", "") or ""
        rel = os.path.relpath(fp, repo_path) if fp and os.path.isabs(fp) else fp
        action = "Creating" if name == "Write" else "Editing"
        emit({
            "type": "tool_call",
            "tool_name": name,
            "content": f"{action} `{rel}`",
        })
    elif name == "Read":
        fp = inp.get("file_path", "") or ""
        rel = os.path.relpath(fp, repo_path) if fp and os.path.isabs(fp) else fp
        emit({"type": "tool_call", "tool_name": "Read", "content": f"Reading `{rel}`"})
    elif name == "Bash":
        cmd = (inp.get("command") or "")[:200]
        emit({"type": "tool_call", "tool_name": "Bash", "content": f"Running: `{cmd}`"})
    elif name in ("Glob", "Grep"):
        pat = str(inp.get("pattern") or inp.get("glob") or "")[:120]
        emit({"type": "tool_call", "tool_name": name, "content": f"Searching `{pat}`"})
    else:
        emit({"type": "tool_call", "tool_name": name, "content": f"Using tool {name}"})


# ---------------------------------------------------------------------------
# Public runner
# ---------------------------------------------------------------------------

async def run_claude_code(
    prompt: str,
    repo_path: str,
    anthropic_api_key: str,
    emit: Optional[Callable[[Dict[str, Any]], None]] = None,
    model: Optional[str] = None,
    max_budget_usd: Optional[float] = None,
    allowed_tools: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    """Run the Claude Code CLI inside ``repo_path`` with ``prompt``.

    Returns ``{"success", "summary", "changed_files", "cost_usd",
    "duration_seconds", "error", "thinking_steps"}``.
    """
    if not anthropic_api_key:
        return _err("ANTHROPIC_API_KEY is required.")
    if not os.path.isdir(repo_path):
        return _err(f"Repository path does not exist: {repo_path}")

    resolved_model = (model or "").strip() or _current_default_model()
    budget = float(max_budget_usd if max_budget_usd is not None else _current_max_budget_usd())
    tools = allowed_tools or _current_allowed_tools()
    deadline = max(60, int(timeout_seconds or _current_timeout_seconds()))

    thinking_steps: List[Dict[str, Any]] = []

    def _emit(step: Dict[str, Any]) -> None:
        thinking_steps.append(step)
        if emit:
            try:
                emit(step)
            except Exception:
                pass

    npx_cmd = "npx.cmd" if _IS_WINDOWS else "npx"
    cmd = [
        npx_cmd, "--yes", "@anthropic-ai/claude-code",
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--allowed-tools", tools,
        "--model", resolved_model,
        "--max-budget-usd", str(budget),
    ]

    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = anthropic_api_key
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["CI"] = "1"

    before = snapshot_mtimes(repo_path)
    state = _RunState()

    # Run the blocking subprocess in a worker thread so we don't block the
    # asyncio loop the agent runs on.
    def _runner() -> Dict[str, Any]:
        prompt_path = _write_prompt_file(prompt)
        if not prompt_path:
            return {"error": "Failed to write prompt file"}

        proc: Optional[subprocess.Popen] = None
        prompt_fh = None
        stderr_lines: List[str] = []
        watchdog_stop = threading.Event()
        timed_out = False
        deadline_at = time.monotonic() + deadline

        try:
            prompt_fh = open(prompt_path, "r", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                stdin=prompt_fh,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=repo_path,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_build_popen_kwargs(),
            )
            try:
                prompt_fh.close()
            except Exception:
                pass
            prompt_fh = None

            def _drain_stderr() -> None:
                try:
                    for line in proc.stderr:  # type: ignore[union-attr]
                        s = line.strip()
                        if s:
                            stderr_lines.append(s)
                except Exception:
                    pass

            def _watchdog() -> None:
                while not watchdog_stop.wait(timeout=5):
                    if time.monotonic() >= deadline_at:
                        _kill_process_tree(proc)
                        return

            threading.Thread(target=_drain_stderr, daemon=True).start()
            threading.Thread(target=_watchdog, daemon=True).start()

            for line in proc.stdout:  # type: ignore[union-attr]
                event = _parse_event(line)
                if event:
                    _handle_event(event, repo_path, state, _emit)

            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                _kill_process_tree(proc)

            if time.monotonic() >= deadline_at:
                timed_out = True

        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
        finally:
            watchdog_stop.set()
            if prompt_fh is not None:
                try:
                    prompt_fh.close()
                except Exception:
                    pass
            if proc is not None and proc.poll() is None:
                _kill_process_tree(proc)
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

        result: Dict[str, Any] = {}
        if timed_out:
            result["error"] = f"Claude Code timed out after {deadline}s"
        elif state.error_msg:
            result["error"] = state.error_msg
        elif proc is not None and proc.returncode not in (0, None):
            tail = " | ".join(stderr_lines[-3:])[:500]
            result["error"] = f"Claude Code exited with code {proc.returncode}: {tail}"
        return result

    result = await asyncio.to_thread(_runner)

    changed = detect_changes(repo_path, before)
    if state.final_result_text:
        summary = state.final_result_text[:64000]
    else:
        summary = " ".join(state.summary_chunks)[:64000]
    error = _sanitize(result.get("error"), anthropic_api_key)

    return {
        "success": error is None,
        "summary": summary,
        "changed_files": changed,
        "cost_usd": state.total_cost,
        "duration_seconds": round(state.duration_ms / 1000, 1),
        "error": error,
        "thinking_steps": thinking_steps,
    }


def _write_prompt_file(prompt: str) -> Optional[str]:
    fd = -1
    path: Optional[str] = None
    try:
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="claude_code_agent_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)
        fd = -1
        if not _IS_WINDOWS:
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        return path
    except Exception:
        if fd != -1:
            try:
                os.close(fd)
            except Exception:
                pass
        return None


def _err(msg: str) -> Dict[str, Any]:
    return {
        "success": False,
        "summary": "",
        "changed_files": [],
        "cost_usd": 0.0,
        "duration_seconds": 0.0,
        "error": msg,
        "thinking_steps": [],
    }


def is_claude_code_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    import shutil as _shutil
    return _shutil.which("npx") is not None
