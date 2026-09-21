"""Generate a structured feature-plan report for a workspace.

Pipeline (per `feature_plan` intent):
  1. Split the user request into individual features via the LLM.
  2. For each feature, retrieve the top-K most relevant existing files using
     the workspace TF-IDF index.
  3. Run a single synthesis LLM call that produces a deterministic JSON
     report with: tech_stack, features[], architecture, coding_structure,
     coding_patterns, reference_files.
  4. Render the JSON to a human-readable Markdown report.

The deterministic `tech_stack` block from `manifest_scanner.scan_repo()` is
authoritative — the LLM is instructed not to override it, only to enrich it
where manifest data is missing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ai_service import ai_service
from .manifest_scanner import render_stack_markdown, scan_repo
from .workspace_index import WorkspaceIndex
from .workspace_tools import _get_index  # internal: in-process index cache

# ---------------------------------------------------------------------------
# Step 1 — split request into features
# ---------------------------------------------------------------------------

_SPLIT_PROMPT = """\
Split the user's product request into a list of independent features. Each
feature should be a self-contained capability that maps to one or more files.

Return ONLY valid JSON — no markdown fences:
{{
  "features": [
    {{ "name": "<short name>", "summary": "<one-sentence description>" }},
    ...
  ]
}}

User request:
{query}

JSON:"""


def _split_features(query: str) -> List[Dict[str, str]]:
    try:
        raw = ai_service.call_genai(
            _SPLIT_PROMPT.format(query=query[:4_000]),
            max_tokens=512,
            temperature=0.0,
        )
        raw = re.sub(r"^```[^\n]*\n", "", raw.strip())
        raw = re.sub(r"```$", "", raw.strip())
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            raise ValueError("no JSON in feature-split response")
        data = json.loads(m.group(0))
        feats = data.get("features") or []
        clean: List[Dict[str, str]] = []
        for f in feats:
            name = str(f.get("name", "")).strip()
            summary = str(f.get("summary", "")).strip()
            if name:
                clean.append({"name": name, "summary": summary or name})
        if clean:
            return clean
    except Exception as exc:
        print(f"[FeaturePlanner] split failed ({exc}); falling back to single feature")

    # Fallback: treat the whole request as one feature
    return [{"name": query[:60].strip() or "Feature", "summary": query}]


# ---------------------------------------------------------------------------
# Step 2 — retrieve relevant files per feature
# ---------------------------------------------------------------------------

def _retrieve_per_feature(
    index: WorkspaceIndex,
    features: List[Dict[str, str]],
    k_per_feature: int = 8,
) -> Dict[str, List[Tuple[str, float]]]:
    out: Dict[str, List[Tuple[str, float]]] = {}
    for f in features:
        q = f"{f['name']} {f['summary']}"
        hits = index.top_k(q, k=k_per_feature, min_score=0.0)
        out[f["name"]] = hits
    return out


# ---------------------------------------------------------------------------
# Step 3 — synthesize report (single LLM call)
# ---------------------------------------------------------------------------

_SYNTHESIS_PROMPT = """\
You are a principal engineer producing a feature-plan report for an existing
codebase. Use the supplied repository context to produce a STRUCTURED JSON
report — no prose, no markdown fences.

Return JSON matching exactly this schema:
{{
  "features": [
    {{
      "name": "<feature name>",
      "summary": "<one-sentence description>",
      "related_files": ["<repo-relative path>", ...],
      "analogous_existing_features": ["<short description>", ...],
      "implementation_notes": "<2-4 sentences on how to add this in THIS codebase>"
    }}
  ],
  "architecture": "<2-4 sentences describing the layering/module boundaries the new code should follow>",
  "coding_structure": ["<rule>", "<rule>", ...],
  "coding_patterns": ["<pattern>", "<pattern>", ...],
  "reference_files": ["<repo-relative path>", ...]
}}

Rules:
- `related_files` MUST be paths drawn from the candidates list provided. Do
  not invent paths.
- `coding_structure` describes folder layout, file naming, layering rules.
- `coding_patterns` describes idioms (e.g. "repository pattern via
  SQLAlchemy sessions", "React Query for server state", "DI via FastAPI
  Depends").
- Keep the response compact. No comments, no trailing text.

Repository: {repo_name}
Default branch / SHA: {branch_sha}

Tech stack (manifest-derived, authoritative — do NOT override):
{stack_md}

Per-feature retrieval candidates:
{per_feature_block}

Selected source-file excerpts:
{file_excerpts}

JSON:"""


def _format_candidates_block(per_feature: Dict[str, List[Tuple[str, float]]]) -> str:
    parts: List[str] = []
    for name, hits in per_feature.items():
        if not hits:
            parts.append(f"- **{name}**: (no strong matches found)")
            continue
        formatted = ", ".join(f"`{p}` ({s:.2f})" for p, s in hits[:8])
        parts.append(f"- **{name}**: {formatted}")
    return "\n".join(parts) if parts else "(no candidates)"


def _format_excerpts(
    index: WorkspaceIndex,
    paths: List[str],
    max_total_chars: int = 60_000,
    per_file_chars: int = 6_000,
) -> str:
    parts: List[str] = []
    total = 0
    for rel in paths:
        content = index.read_file(rel)
        if not content:
            continue
        snippet = content[:per_file_chars]
        if len(content) > per_file_chars:
            snippet += "\n... (truncated)"
        block = f"\n--- {rel} ---\n{snippet}"
        if total + len(block) > max_total_chars:
            parts.append(f"\n--- {rel} --- (omitted: budget exceeded)")
            break
        parts.append(block)
        total += len(block)
    return "\n".join(parts) if parts else "(no excerpts)"


def _parse_synthesis(raw: str) -> Optional[Dict[str, Any]]:
    cleaned = re.sub(r"^```[^\n]*\n", "", raw.strip())
    cleaned = re.sub(r"```$", "", cleaned.strip())
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Step 4 — render markdown
# ---------------------------------------------------------------------------

def _render_markdown(
    repo_name: str,
    branch_sha: str,
    stack: Dict[str, Any],
    report: Dict[str, Any],
) -> str:
    lines: List[str] = []
    lines.append(f"# Feature Plan — {repo_name}")
    if branch_sha:
        lines.append(f"_Snapshot: {branch_sha}_")
    lines.append("")

    lines.append("## 1. Tech stack")
    lines.append(render_stack_markdown(stack))
    lines.append("")

    lines.append("## 2. Features")
    for feat in report.get("features", []):
        lines.append(f"### {feat.get('name', 'Feature')}")
        if feat.get("summary"):
            lines.append(f"_{feat['summary']}_")
            lines.append("")
        related = feat.get("related_files") or []
        if related:
            lines.append("**Related files:**")
            for p in related:
                lines.append(f"- `{p}`")
        analogues = feat.get("analogous_existing_features") or []
        if analogues:
            lines.append("")
            lines.append("**Analogous existing features:**")
            for a in analogues:
                lines.append(f"- {a}")
        if feat.get("implementation_notes"):
            lines.append("")
            lines.append(f"**Implementation notes:** {feat['implementation_notes']}")
        lines.append("")

    arch = report.get("architecture")
    if arch:
        lines.append("## 3. Tech architecture to follow")
        lines.append(arch)
        lines.append("")

    cs = report.get("coding_structure") or []
    if cs:
        lines.append("## 4. Coding structure & best practices")
        for r in cs:
            lines.append(f"- {r}")
        lines.append("")

    cp = report.get("coding_patterns") or []
    if cp:
        lines.append("## 5. Coding patterns")
        for r in cp:
            lines.append(f"- {r}")
        lines.append("")

    refs = report.get("reference_files") or []
    if refs:
        lines.append("## 6. Reference files")
        for p in refs:
            lines.append(f"- `{p}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def build_feature_plan(
    repo_path: str,
    repo_name: str,
    query: str,
    branch_sha: str = "",
) -> Dict[str, Any]:
    """Produce a feature-plan report.

    Returns:
        {
            "markdown": str,
            "json": dict,        # raw structured report
            "stack": dict,       # manifest_scanner output
            "features": [...]    # split features
        }
    """
    root = Path(repo_path)
    stack = scan_repo(repo_path)
    index = _get_index(repo_path)

    features = _split_features(query)
    per_feature = _retrieve_per_feature(index, features)

    # Union the candidate paths so we excerpt each only once
    union_paths: List[str] = []
    seen: set = set()
    for hits in per_feature.values():
        for p, _ in hits:
            if p not in seen:
                seen.add(p)
                union_paths.append(p)
    union_paths = union_paths[:25]  # cap excerpts

    candidates_block = _format_candidates_block(per_feature)
    excerpts = _format_excerpts(index, union_paths)
    stack_md = render_stack_markdown(stack)

    prompt = _SYNTHESIS_PROMPT.format(
        repo_name=repo_name,
        branch_sha=branch_sha or "(local)",
        stack_md=stack_md,
        per_feature_block=candidates_block,
        file_excerpts=excerpts,
    )

    raw = await ai_service.call_genai_async(prompt, max_tokens=4096, temperature=0.1)
    report = _parse_synthesis(raw) or {
        "features": [
            {
                "name": f["name"],
                "summary": f["summary"],
                "related_files": [p for p, _ in per_feature.get(f["name"], [])][:5],
                "analogous_existing_features": [],
                "implementation_notes": "(LLM did not return structured output; using retrieval candidates only.)",
            }
            for f in features
        ],
        "architecture": "",
        "coding_structure": [],
        "coding_patterns": [],
        "reference_files": union_paths[:5],
    }

    # Overlay manifest stack so the LLM cannot override deterministic facts
    report["tech_stack"] = stack

    markdown = _render_markdown(repo_name, branch_sha, stack, report)
    return {
        "markdown": markdown,
        "json": report,
        "stack": stack,
        "features": features,
    }
