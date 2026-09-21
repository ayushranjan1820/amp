"""Generate per-feature codebase context from a natural-language description.

Pipeline:
  1. Split the user's input into independent features via the LLM.
  2. For each feature, retrieve the top-K most relevant existing files
     using the workspace TF-IDF index.
  3. Extract code symbols (classes, functions, routes) from each file.
  4. Run a focused LLM call per feature to summarize the existing code context.
  5. Return structured context: one context block per feature.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .ai_service import ai_service
from .feature_planner import _split_features
from .workspace_tools import _get_index

_PER_FILE_CHARS = 3_000
_MAX_CONTEXT_CHARS = 40_000

_SYMBOL_PATTERNS = [
    (r"^(?:async\s+)?def\s+(\w+)\s*\(", "fn"),
    (r"^class\s+(\w+)[\s(:]", "class"),
    (r"@(?:app|router|blueprint|api)\.\w+\(['\"]([^'\"]+)['\"]", "route"),
    (r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(", "fn"),
    (r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)", "class"),
    (r"^(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(", "fn"),
]


def _extract_symbols(content: str) -> List[str]:
    symbols: List[str] = []
    seen: set = set()
    for line in content.splitlines()[:300]:
        stripped = line.strip()
        for pattern, kind in _SYMBOL_PATTERNS:
            m = re.match(pattern, stripped)
            if m:
                name = m.group(1)
                if name not in seen and not name.startswith("_"):
                    seen.add(name)
                    symbols.append(f"{kind}:{name}")
    return symbols[:20]


_CONTEXT_PROMPT = """\
You are a senior engineer. Summarize what already exists in the codebase for this feature.

Feature: {feature_name}
Description: {feature_summary}

Relevant files and excerpts:
{excerpts}

Write a concise technical summary (3-5 sentences):
1. What existing code is relevant to this feature
2. Which files / modules are central
3. Any obvious gaps

Summary:"""


def _build_excerpt_block(file_contexts: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    total = 0
    for fc in file_contexts:
        block = f"\n--- {fc['path']} (score: {fc['relevance_score']:.2f}) ---\n{fc['excerpt']}"
        if total + len(block) > _MAX_CONTEXT_CHARS:
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts) or "(no excerpts)"


async def _summarize_feature_context(
    feature: Dict[str, str],
    file_contexts: List[Dict[str, Any]],
) -> str:
    if not file_contexts:
        return "No relevant files found in the codebase for this feature."
    prompt = _CONTEXT_PROMPT.format(
        feature_name=feature["name"],
        feature_summary=feature["summary"],
        excerpts=_build_excerpt_block(file_contexts),
    )
    try:
        return await ai_service.call_genai_async(prompt, max_tokens=512, temperature=0.1)
    except Exception as exc:
        return f"(LLM summarization failed: {exc})"


def _render_markdown(
    repo_name: str,
    branch_sha: str,
    features_context: List[Dict[str, Any]],
) -> str:
    lines: List[str] = [f"# Codebase Context — {repo_name}"]
    if branch_sha:
        lines.append(f"_Snapshot: {branch_sha}_")
    lines.append("")

    for i, fc in enumerate(features_context, 1):
        feat = fc["feature"]
        lines.append(f"---")
        lines.append("")
        lines.append(f"## Feature {i}: {feat['name']}")
        lines.append("")

        # Section 1 — Overview
        lines.append(f"### Overview")
        lines.append(feat["summary"])
        lines.append("")

        # Section 2 — Relevant Files
        lines.append(f"### Relevant Files")
        rfiles = fc.get("relevant_files", [])
        if rfiles:
            for rf in rfiles:
                syms = rf.get("symbols", [])
                sym_str = f"  \n  _Symbols: `{'`, `'.join(syms[:6])}`_" if syms else ""
                lines.append(
                    f"- **`{rf['path']}`** (relevance: {rf['relevance_score']:.2f}){sym_str}"
                )
        else:
            lines.append("_No strongly-matching files found in the codebase._")
        lines.append("")

        # Section 3 — Codebase Context
        lines.append(f"### Codebase Context")
        lines.append(fc.get("context_summary") or "_No context generated._")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def generate_context(
    repo_path: str,
    repo_name: str,
    query: str,
    branch_sha: str = "",
    k_per_feature: int = 10,
) -> Dict[str, Any]:
    """Split `query` into features and return per-feature codebase context.

    Returns:
        {
            "markdown": str,
            "json": { "features": [...] },
            "features": [{"name": ..., "summary": ...}, ...]
        }
    """
    index = _get_index(repo_path)
    features = _split_features(query)

    features_context: List[Dict[str, Any]] = []
    for feat in features:
        search_q = f"{feat['name']} {feat['summary']}"
        hits = index.top_k(search_q, k=k_per_feature, min_score=0.0)

        file_contexts: List[Dict[str, Any]] = []
        for path, score in hits:
            content = index.read_file(path)
            if not content:
                continue
            excerpt = content[:_PER_FILE_CHARS]
            if len(content) > _PER_FILE_CHARS:
                excerpt += "\n... (truncated)"
            file_contexts.append({
                "path": path,
                "relevance_score": round(score, 4),
                "excerpt": excerpt,
                "symbols": _extract_symbols(content),
            })

        summary = await _summarize_feature_context(feat, file_contexts)

        slim_files = [
            {k: v for k, v in fc.items() if k != "excerpt"}
            for fc in file_contexts
        ]
        features_context.append({
            "feature": feat,
            "relevant_files": slim_files,
            "context_summary": summary.strip(),
        })

    return {
        "markdown": _render_markdown(repo_name, branch_sha, features_context),
        "json": {"features": features_context},
        "features": features,
    }
