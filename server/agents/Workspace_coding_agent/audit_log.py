"""Append-only JSONL audit log for Workspace context Agent.

One log file per workspace (keyed by a hash of the workspace path), stored
under a ``logs/`` directory beside this module.  Each entry captures:
  ts               — ISO-8601 UTC timestamp
  session_id       — caller-supplied session identifier
  workspace        — absolute path of the workspace root
  intent           — classified intent (modify / generate / analyze / …)
  query            — first 500 chars of the user request
  files_modified   — list of relative paths written
  response_preview — first 300 chars of the LLM response
  prompt_tokens    — estimated prompt token count
  completion_tokens— estimated completion token count
  diff_summary     — first 1 000 chars of the git diff
  error            — exception message if the operation failed, else null

The log is written in a thread-safe way (append + lock) and never blocks the
main request path — all I/O errors are silently swallowed.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOGS_DIR = Path(__file__).parent / "logs"
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_path(workspace_root: str) -> Path:
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(workspace_root.encode()).hexdigest()[:12]
    safe_name = Path(workspace_root).name[:40].replace(" ", "_")
    return _LOGS_DIR / f"{safe_name}_{h}.jsonl"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_audit_entry(
    workspace_root: str,
    session_id: str,
    query: str,
    intent: str,
    files_modified: List[str],
    response_preview: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    diff_summary: str = "",
    error: Optional[str] = None,
) -> None:
    """Append one entry to the workspace audit log (thread-safe, best-effort)."""
    entry: Dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "workspace": workspace_root,
        "intent": intent,
        "query": query[:500],
        "files_modified": files_modified,
        "response_preview": response_preview[:300],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "diff_summary": diff_summary[:1_000],
        "error": error,
    }
    log_path = _log_path(workspace_root)
    with _lock:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # never let audit failures break the main request


def read_audit_log(
    workspace_root: str,
    last_n: int = 50,
) -> List[Dict[str, Any]]:
    """Return the most recent ``last_n`` entries from the workspace audit log."""
    log_path = _log_path(workspace_root)
    entries: List[Dict[str, Any]] = []
    if not log_path.exists():
        return entries
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        for line in lines[-last_n:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except OSError:
        pass
    return entries


def get_audit_stats(workspace_root: str) -> Dict[str, Any]:
    """Return aggregate stats (total calls, tokens, files changed) for a workspace."""
    entries = read_audit_log(workspace_root, last_n=1_000)
    total_prompt = sum(e.get("prompt_tokens", 0) for e in entries)
    total_completion = sum(e.get("completion_tokens", 0) for e in entries)
    all_files: List[str] = []
    for e in entries:
        all_files.extend(e.get("files_modified", []))
    return {
        "total_calls": len(entries),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "unique_files_modified": len(set(all_files)),
        "errors": sum(1 for e in entries if e.get("error")),
    }
