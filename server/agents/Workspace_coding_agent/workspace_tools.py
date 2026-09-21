"""Read-only workspace tooling for the Workspace context Agent.

The agent does not write to disk. This module exposes:

  - ``analyze_workspace()``  — answer a Q&A request over the indexed repo
  - ``_get_index()``         — in-process TF-IDF index cache (used by
                                 ``feature_planner.py``)
  - ``refresh_index()``      — force-rebuild the index for a workspace

Earlier revisions exposed ``generate_workspace_files`` and
``modify_workspace_files``; those were removed when the agent was made
read-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .ai_service import ai_service
from .workspace_index import WorkspaceIndex

# ---------------------------------------------------------------------------
# In-process index cache  {str(resolved_root): WorkspaceIndex}
# ---------------------------------------------------------------------------

_INDEX_CACHE: Dict[str, WorkspaceIndex] = {}


def _get_index(repo_path: str) -> WorkspaceIndex:
    root = Path(repo_path).resolve()
    key = str(root)
    if key not in _INDEX_CACHE or not _INDEX_CACHE[key].is_ready():
        idx = WorkspaceIndex(root)
        idx.build()
        _INDEX_CACHE[key] = idx
    return _INDEX_CACHE[key]


def refresh_index(repo_path: str) -> None:
    """Force a full rebuild of the TF-IDF index for this workspace."""
    root = Path(repo_path).resolve()
    key = str(root)
    idx = WorkspaceIndex(root)
    idx.build(force=True)
    _INDEX_CACHE[key] = idx


# ---------------------------------------------------------------------------
# File selection helpers
# ---------------------------------------------------------------------------

def _collect_relevant_files(
    index: WorkspaceIndex,
    query: str,
    k: int = 25,
    target_files: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Return ``{rel_path: content}`` for the most relevant workspace files."""
    priority: Dict[str, float] = {}

    if target_files:
        for hint in target_files:
            hint_lower = hint.lower()
            for fp in index.all_files():
                if hint_lower in fp.lower():
                    priority[fp] = 999.0

    for path, score in index.top_k(query, k=k + len(priority)):
        if path not in priority:
            priority[path] = score

    top = sorted(priority.items(), key=lambda x: x[1], reverse=True)[:k]

    result: Dict[str, str] = {}
    for rel_path, _ in top:
        content = index.read_file(rel_path)
        if content:
            result[rel_path] = content
    return result


def _format_files_for_prompt(
    files: Dict[str, str],
    max_total_chars: int = 100_000,
) -> str:
    """Format files for prompt inclusion within a character budget."""
    parts: List[str] = []
    total = 0
    for name, content in files.items():
        if len(content) > 15_000:
            content = content[:15_000] + "\n\n... (file truncated for context window)"
        chunk = f"\n--- {name} ---\n{content}"
        if total + len(chunk) > max_total_chars:
            parts.append(f"\n--- {name} --- (omitted: context budget exceeded)")
            break
        parts.append(chunk)
        total += len(chunk)
    return "\n".join(parts)


def _get_file_tree(repo_path: str, max_depth: int = 5) -> str:
    try:
        from agents.GitHub_repo_agent.utils.file_operations import get_file_tree
        return get_file_tree(repo_path, max_depth=max_depth)
    except Exception:
        return "(file tree unavailable)"


# ---------------------------------------------------------------------------
# Public read-only operation
# ---------------------------------------------------------------------------

async def analyze_workspace(
    repo_path: str,
    repo_name: str,
    query: str,
    target_files: Optional[List[str]] = None,
) -> str:
    """Answer a question about the indexed workspace. Returns Markdown."""
    index = _get_index(repo_path)
    tree = _get_file_tree(repo_path)
    relevant = _collect_relevant_files(
        index, query, k=25, target_files=target_files
    )

    if not relevant:
        return (
            "No source files were found in this workspace. "
            "Verify that **workspace_root** points to a non-empty project directory."
        )

    files_block = _format_files_for_prompt(relevant, max_total_chars=100_000)

    prompt = f"""You are a principal engineer answering a question about an
existing codebase. You DO NOT write or modify code — you only explain,
locate, and reference what is already present.

Repository: {repo_name}
Question: {query}

Directory structure:
{tree}

Source files ({len(relevant)} selected by semantic relevance):
{files_block}

Provide a clear, well-structured Markdown response. Cite specific file
paths whenever you reference code. If additional files (not shown above)
would help answer fully, list their relative paths and explain why."""

    return await ai_service.call_genai_async(prompt, max_tokens=8192)
