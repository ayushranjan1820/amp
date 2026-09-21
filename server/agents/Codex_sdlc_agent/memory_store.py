from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


BASE_DIR = Path(__file__).resolve().parent
STATE_BASE_DIR = BASE_DIR.parent / "Workspace_coding_agent"
MEMORY_DIR = STATE_BASE_DIR / "sessions" / "codex_sdlc_memory"
RUNS_DIR = STATE_BASE_DIR / "logs" / "codex_sdlc_runs"


def _ensure_dirs() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _repo_key(workspace_root: str) -> str:
    return hashlib.sha1(workspace_root.encode("utf-8")).hexdigest()[:16]


def load_repo_memory(workspace_root: str) -> Dict[str, Any]:
    _ensure_dirs()
    path = MEMORY_DIR / f"{_repo_key(workspace_root)}.json"
    if not path.exists():
        return {
            "repo_patterns": [],
            "test_style": "",
            "common_failures": [],
            "previous_fixes": [],
            "updated_at": None,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "repo_patterns": [],
            "test_style": "",
            "common_failures": [],
            "previous_fixes": [],
            "updated_at": None,
        }


def save_repo_memory(workspace_root: str, memory: Dict[str, Any]) -> None:
    _ensure_dirs()
    path = MEMORY_DIR / f"{_repo_key(workspace_root)}.json"
    payload = dict(memory)
    payload["updated_at"] = datetime.utcnow().isoformat() + "Z"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_run_log(session_id: str, payload: Dict[str, Any]) -> None:
    _ensure_dirs()
    path = RUNS_DIR / f"{session_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
