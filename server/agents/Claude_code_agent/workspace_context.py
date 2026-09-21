"""Shared workspace binding and file-context loading for coding agents (local MCP workflows)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MAX_CONTEXT_FILES = 40
MAX_CONTEXT_BYTES_PER_FILE = 200_000
MAX_CONTEXT_TOTAL_BYTES = 900_000


def path_under_root(file_path: Path, root: Path) -> bool:
    try:
        file_path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def bind_workspace(session: Dict[str, Any], workspace_root: str) -> Tuple[bool, Optional[str]]:
    try:
        root = Path(workspace_root).expanduser().resolve()
    except OSError:
        return False, f"Invalid workspace_root: {workspace_root!r}"
    if not root.is_dir():
        return False, f"workspace_root is not a directory: {root}"
    prev = session.get("repo_path")
    if prev and str(Path(prev).resolve()) != str(root):
        session["modified_files"] = []
        session["cli_session_id"] = None
    session["repo_path"] = str(root)
    session["repo_name"] = root.name or "workspace"
    session["cloned"] = True
    session["local_workspace"] = True
    session.setdefault("repo_url", None)
    return True, None


def build_context_files_block(root: Path, paths: List[str]) -> Tuple[str, List[str]]:
    notes: List[str] = []
    parts: List[str] = []
    root_r = root.resolve()
    total = 0
    for raw in paths[:MAX_CONTEXT_FILES]:
        raw = (raw or "").strip()
        if not raw:
            continue
        cand = Path(raw).expanduser()
        if not cand.is_absolute():
            cand = (root_r / raw).resolve()
        else:
            try:
                cand = cand.resolve()
            except OSError:
                notes.append(f"skipped (invalid path): {raw}")
                continue
        if not path_under_root(cand, root_r):
            notes.append(f"skipped (outside workspace): {raw}")
            continue
        if not cand.is_file():
            notes.append(f"skipped (not a file): {raw}")
            continue
        try:
            sz = cand.stat().st_size
        except OSError:
            notes.append(f"skipped (unreadable): {raw}")
            continue
        if sz > MAX_CONTEXT_BYTES_PER_FILE:
            notes.append(f"skipped (file too large): {raw}")
            continue
        try:
            data = cand.read_bytes()[:MAX_CONTEXT_BYTES_PER_FILE]
        except OSError:
            notes.append(f"skipped (read error): {raw}")
            continue
        text = data.decode("utf-8", errors="replace")
        if total + len(text) > MAX_CONTEXT_TOTAL_BYTES:
            notes.append("truncated: context size budget exceeded")
            break
        try:
            rel_display = str(cand.relative_to(root_r))
        except ValueError:
            rel_display = str(cand)
        parts.append(f"### {rel_display}\n```\n{text}\n```")
        total += len(text)
    if not parts:
        return "", notes
    header = "The following workspace files were attached for context:\n\n"
    block = header + "\n\n".join(parts)
    if notes:
        block += "\n\n_(Loader: " + "; ".join(notes[:10]) + ")_"
    return block, notes
