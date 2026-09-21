"""Adaptive per-repo memory for the Claude Code Agent.

Each cloned repository gets a JSON memory record (file tree, key configs,
language hint, recent run notes). On every CLI run we inject the memory into
``CLAUDE.md`` inside the repo so Claude Code reads it automatically as
persistent context — and we snapshot the original ``CLAUDE.md`` so the
managed memory block is never committed to the user's remote.

The memory is keyed by repository URL so the same repo cloned by the same
user across sessions reuses prior analysis instead of re-scanning.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MEMORY_DIR = Path(__file__).parent / "data" / "memories"

CLAUDE_MD_BEGIN = "<!-- BEGIN CLAUDE-CODE-AGENT MEMORY -->"
CLAUDE_MD_END = "<!-- END CLAUDE-CODE-AGENT MEMORY -->"
CLAUDE_MD_FILE = "CLAUDE.md"
SNAPSHOT_DIR = ".claude_code_agent"

SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".cache", "target", ".idea",
    ".vscode", "coverage", "vendor",
})

KEY_FILES = (
    "package.json", "pyproject.toml", "requirements.txt", "Pipfile",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "tsconfig.json",
    "Dockerfile", "docker-compose.yml", "README.md",
)

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".go": "go",
    ".rs": "rust", ".java": "java", ".rb": "ruby", ".php": "php",
}


# ---------------------------------------------------------------------------
# Repo key + path helpers
# ---------------------------------------------------------------------------

def _repo_key(repo_url: str) -> str:
    return hashlib.sha256((repo_url or "").strip().lower().encode()).hexdigest()[:16]


def _memory_path(repo_url: str) -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR / f"{_repo_key(repo_url)}.json"


# ---------------------------------------------------------------------------
# Repo analysis (file tree, key files, language)
# ---------------------------------------------------------------------------

def _build_file_tree(repo_path: str, max_files: int = 200, max_depth: int = 4) -> str:
    lines: List[str] = []
    count = 0
    root = Path(repo_path)
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        rel = Path(cur).relative_to(root)
        depth = len(rel.parts)
        if depth > max_depth:
            dirs.clear()
            continue
        indent = "  " * depth
        if depth > 0:
            lines.append(f"{indent}{rel.name}/")
        for f in sorted(files):
            if count >= max_files:
                lines.append(f"{indent}  ... (truncated)")
                return "\n".join(lines)
            lines.append(f"{indent}  {f}")
            count += 1
    return "\n".join(lines) if lines else "(empty repository)"


def _read_key_files(repo_path: str, max_chars: int = 8000) -> str:
    parts: List[str] = []
    total = 0
    for name in KEY_FILES:
        path = Path(repo_path) / name
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        snippet = content[: max(500, max_chars - total)]
        parts.append(f"--- {name} ---\n{snippet}")
        total += len(snippet)
        if total >= max_chars:
            break
    return "\n\n".join(parts)


def _detect_primary_language(repo_path: str) -> str:
    counts: Dict[str, int] = {}
    for cur, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            lang = LANG_BY_EXT.get(ext)
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda kv: kv[1])[0]


# ---------------------------------------------------------------------------
# Memory record load / save
# ---------------------------------------------------------------------------

def load_memory(repo_url: str) -> Optional[Dict[str, Any]]:
    path = _memory_path(repo_url)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_memory(record: Dict[str, Any]) -> None:
    repo_url = record.get("repo_url", "")
    path = _memory_path(repo_url)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def build_or_refresh_memory(
    repo_url: str,
    repo_path: str,
    repo_name: str,
) -> Dict[str, Any]:
    """Build a fresh memory record from the cloned repo, merging in prior run notes."""
    prior = load_memory(repo_url) or {}
    record = {
        "repo_url": repo_url,
        "repo_name": repo_name,
        "language": _detect_primary_language(repo_path),
        "file_tree": _build_file_tree(repo_path),
        "key_files_text": _read_key_files(repo_path),
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
        "run_notes": prior.get("run_notes", [])[-5:],  # keep last 5
    }
    save_memory(record)
    return record


# ---------------------------------------------------------------------------
# CLAUDE.md injection / restoration
# ---------------------------------------------------------------------------

def _build_claude_md_block(memory: Dict[str, Any]) -> str:
    parts = [
        CLAUDE_MD_BEGIN,
        "# Project Memory (auto-injected by Claude Code Agent)",
        "",
        "Persistent context for this repository. Do not edit between the BEGIN/END",
        "markers — they are regenerated on every agent run and stripped before push.",
        "",
        f"- **Repository:** {memory.get('repo_name', 'unknown')}",
        f"- **Primary language:** {memory.get('language', 'unknown')}",
        f"- **Last refreshed:** {memory.get('refreshed_at', 'unknown')}",
        "",
    ]

    file_tree = (memory.get("file_tree") or "").strip()
    if file_tree:
        parts += ["## File Tree", "", "```", file_tree[:6000], "```", ""]

    key_files = (memory.get("key_files_text") or "").strip()
    if key_files:
        parts += ["## Key Project Files", "", "```", key_files[:6000], "```", ""]

    notes: List[Dict[str, Any]] = memory.get("run_notes", []) or []
    if notes:
        parts.append("## Recent Runs (most recent last)")
        parts.append("")
        for note in notes[-5:]:
            ts = note.get("at", "")
            summary = (note.get("summary") or "").replace("\n", " ")[:300]
            files = note.get("changed_files", [])
            parts.append(
                f"- **{ts}** — {len(files)} file(s) touched. {summary}"
            )
        parts.append("")

    parts.append(
        "## Guidance\n"
        "- Use this memory for structural questions before re-running Glob/Grep.\n"
        "- Always Read a file before Editing it.\n"
        "- If this memory looks stale, mention it in your final summary.\n"
    )
    parts.append(CLAUDE_MD_END)
    return "\n".join(parts).rstrip() + "\n"


def _replace_managed_block(existing: str, new_block: str) -> str:
    if CLAUDE_MD_BEGIN in existing and CLAUDE_MD_END in existing:
        start = existing.index(CLAUDE_MD_BEGIN)
        end = existing.index(CLAUDE_MD_END) + len(CLAUDE_MD_END)
        return existing[:start] + new_block.rstrip() + existing[end:]
    prefix = existing.rstrip() + "\n\n" if existing.strip() else ""
    return prefix + new_block


def _snapshot_original_claude_md(repo_path: str) -> None:
    target = Path(repo_path) / CLAUDE_MD_FILE
    snap = Path(repo_path) / SNAPSHOT_DIR
    snap.mkdir(exist_ok=True)
    marker_orig = snap / "claude_md.original"
    marker_missing = snap / "claude_md.missing"
    if marker_orig.exists() or marker_missing.exists():
        return
    if target.exists():
        marker_orig.write_bytes(target.read_bytes())
    else:
        marker_missing.touch()


def restore_original_claude_md(repo_path: str) -> Tuple[bool, str]:
    """Restore CLAUDE.md to its pre-run state. Returns (acted, action)."""
    snap = Path(repo_path) / SNAPSHOT_DIR
    target = Path(repo_path) / CLAUDE_MD_FILE
    if not snap.exists():
        return (False, "noop")
    marker_orig = snap / "claude_md.original"
    marker_missing = snap / "claude_md.missing"
    try:
        if marker_orig.exists():
            target.write_bytes(marker_orig.read_bytes())
            return (True, "restored")
        if marker_missing.exists() and target.exists():
            target.unlink()
            return (True, "deleted")
    except OSError as e:
        print(f"[memory] restore CLAUDE.md failed: {e}")
    return (False, "noop")


def write_claude_md(repo_path: str, memory: Dict[str, Any]) -> bool:
    if not repo_path or not os.path.isdir(repo_path):
        return False
    try:
        _snapshot_original_claude_md(repo_path)
        target = Path(repo_path) / CLAUDE_MD_FILE
        existing = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        merged = _replace_managed_block(existing, _build_claude_md_block(memory))
        target.write_text(merged, encoding="utf-8")
        return True
    except OSError as e:
        print(f"[memory] write CLAUDE.md failed: {e}")
        return False


def append_run_note(
    repo_url: str,
    summary: str,
    changed_files: List[str],
    cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
) -> None:
    """Persist a run note into the memory record so the next run sees what changed."""
    record = load_memory(repo_url)
    if not record:
        return
    note = {
        "at": datetime.now(timezone.utc).isoformat(),
        "summary": (summary or "").strip()[:600],
        "changed_files": changed_files[:50],
        "cost_usd": round(float(cost_usd or 0.0), 4),
        "duration_seconds": round(float(duration_seconds or 0.0), 1),
    }
    notes: List[Any] = record.get("run_notes", []) or []
    notes.append(note)
    record["run_notes"] = notes[-5:]
    save_memory(record)


def cleanup_snapshot_dir(repo_path: str) -> None:
    """Delete .claude_code_agent/ before staging so it isn't pushed to the remote."""
    import shutil
    snap = Path(repo_path) / SNAPSHOT_DIR
    if snap.is_dir():
        shutil.rmtree(snap, ignore_errors=True)
