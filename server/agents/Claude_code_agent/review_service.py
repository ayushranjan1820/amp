"""Validation/review pass for the Claude Code Agent.

Calls the Anthropic Messages API directly with a strict ``submit_review`` tool,
so the verdict comes back as guaranteed-shape JSON via ``tool_use.input`` —
not parsed out of free-text. The model also gets ``read_file`` / ``glob_files``
/ ``grep_files`` tools to inspect the working tree, plus the diff vs. the base
branch inlined into the user message for high-signal review.

Replaces the previous CLI-based review pass which lost JSON to three layers of
truncation in ``claude_service.py`` (per-block 16 KB cap, sliding window over
``summary_chunks``, and the ``" ".join(...)[:64000]`` final cap).
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import subprocess
from typing import Any, Callable, Dict, List, Optional

import anthropic

DEFAULT_REVIEW_MODEL = os.getenv("CLAUDE_CODE_REVIEW_MODEL", "claude-opus-4-7")
DEFAULT_MAX_TOOL_LOOPS = int(os.getenv("CLAUDE_CODE_REVIEW_MAX_TOOL_LOOPS", "20"))
DEFAULT_MAX_TOKENS = int(os.getenv("CLAUDE_CODE_REVIEW_MAX_TOKENS", "8000"))
DEFAULT_FILE_READ_BYTES = int(os.getenv("CLAUDE_CODE_REVIEW_FILE_READ_BYTES", "60000"))
DEFAULT_DIFF_BYTES = int(os.getenv("CLAUDE_CODE_REVIEW_DIFF_BYTES", "120000"))
DEFAULT_GREP_MAX_HITS = 200

SKIP_DIRS = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    ".next", "dist", "build", ".cache", "target", ".claude_code_agent",
})

# Pricing (USD per 1M tokens) — keep in lockstep with shared/models.md.
_PRICING = {
    "claude-opus-4-7":   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write_5m": 6.25},
    "claude-opus-4-6":   {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_write_5m": 6.25},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write_5m": 3.75},
    "claude-haiku-4-5":  {"input": 1.00, "output":  5.00, "cache_read": 0.10, "cache_write_5m": 1.25},
}


REVIEW_SYSTEM_PROMPT = (
    "You are a strict code-review validator. Decide whether the repository "
    "changes in this run satisfy the user's request.\n\n"
    "How to work:\n"
    "1. Read the diff carefully. Use read_file/glob_files/grep_files to "
    "inspect any file the diff touches or any supporting code you need to "
    "judge correctness.\n"
    "2. Check for: missing requirements, regressions, obviously broken code, "
    "and divergence from the user's stated intent. Style is secondary.\n"
    "3. Do not modify files. You only have read tools.\n"
    "4. Once you have enough information, call submit_review exactly once. "
    "That ends the review — keep the explanation in `summary` short.\n\n"
    "Set `is_aligned=true` only if `alignment_score >= target_score` AND "
    "`mismatches` is empty. Otherwise set false and list concrete mismatches "
    "and fix instructions a follow-up engineer can act on."
)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

REVIEW_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read the full text of a file in the repository. Path is "
            "relative to the repo root. Returns up to ~60KB; large files "
            "are truncated with a marker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative path."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "glob_files",
        "description": (
            "List files matching a glob pattern (e.g. 'src/**/*.py'). "
            "Skips vendor/build dirs. Returns up to 200 paths."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_files",
        "description": (
            "Search for a regex pattern across files. Optional "
            "path_glob narrows the search (e.g. '*.py'). Returns matching "
            "lines with file:lineno prefixes, capped at 200 hits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python-style regex."},
                "path_glob": {"type": "string", "description": "Optional glob filter."},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "submit_review",
        "description": (
            "Submit the final review verdict. Call this exactly once when "
            "you've gathered enough evidence. This ends the review."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "alignment_score": {
                    "type": "number",
                    "description": "0-100, how well the changes match the user's request.",
                },
                "is_aligned": {
                    "type": "boolean",
                    "description": "True only if score >= target AND mismatches is empty.",
                },
                "mismatches": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Concrete divergences from the request. Empty if aligned.",
                },
                "fix_instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Actionable follow-up steps. Empty if aligned.",
                },
                "summary": {
                    "type": "string",
                    "description": "One-paragraph explanation of the verdict.",
                },
            },
            "required": [
                "alignment_score", "is_aligned", "mismatches",
                "fix_instructions", "summary",
            ],
        },
        "strict": True,
    },
]


# ---------------------------------------------------------------------------
# Tool execution (host-side)
# ---------------------------------------------------------------------------

def _safe_join(repo_path: str, rel: str) -> Optional[str]:
    """Resolve ``rel`` against ``repo_path`` and refuse paths outside it."""
    try:
        full = os.path.realpath(os.path.join(repo_path, rel))
    except Exception:
        return None
    repo_real = os.path.realpath(repo_path)
    if not (full == repo_real or full.startswith(repo_real + os.sep)):
        return None
    return full


def _exec_read_file(repo_path: str, path: str) -> str:
    full = _safe_join(repo_path, path)
    if full is None:
        return f"Error: path '{path}' is outside the repository."
    if not os.path.exists(full):
        return f"Error: file '{path}' does not exist."
    if os.path.isdir(full):
        return f"Error: '{path}' is a directory, not a file."
    try:
        with open(full, "rb") as fh:
            data = fh.read(DEFAULT_FILE_READ_BYTES + 1)
    except OSError as e:
        return f"Error reading '{path}': {e}"
    truncated = len(data) > DEFAULT_FILE_READ_BYTES
    text = data[:DEFAULT_FILE_READ_BYTES].decode("utf-8", errors="replace")
    if truncated:
        text += f"\n\n[... truncated at {DEFAULT_FILE_READ_BYTES} bytes ...]"
    return text


def _walk_repo(repo_path: str):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            yield os.path.join(root, f)


def _exec_glob(repo_path: str, pattern: str) -> str:
    if not pattern.strip():
        return "Error: empty pattern."
    matches: List[str] = []
    for full in _walk_repo(repo_path):
        rel = os.path.relpath(full, repo_path).replace(os.sep, "/")
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(rel), pattern):
            matches.append(rel)
            if len(matches) >= 200:
                matches.append("[... 200-result cap reached ...]")
                break
    return "\n".join(matches) if matches else f"(no files match {pattern!r})"


def _exec_grep(repo_path: str, pattern: str, path_glob: Optional[str] = None) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    hits: List[str] = []
    for full in _walk_repo(repo_path):
        rel = os.path.relpath(full, repo_path).replace(os.sep, "/")
        if path_glob and not (
            fnmatch.fnmatch(rel, path_glob)
            or fnmatch.fnmatch(os.path.basename(rel), path_glob)
        ):
            continue
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as fh:
                for lineno, line in enumerate(fh, start=1):
                    if regex.search(line):
                        snippet = line.rstrip("\n")[:240]
                        hits.append(f"{rel}:{lineno}: {snippet}")
                        if len(hits) >= DEFAULT_GREP_MAX_HITS:
                            hits.append("[... 200-hit cap reached ...]")
                            return "\n".join(hits)
        except OSError:
            continue
    return "\n".join(hits) if hits else f"(no matches for {pattern!r})"


def _execute_tool(repo_path: str, name: str, inp: Dict[str, Any]) -> str:
    try:
        if name == "read_file":
            return _exec_read_file(repo_path, str(inp.get("path", "")))
        if name == "glob_files":
            return _exec_glob(repo_path, str(inp.get("pattern", "")))
        if name == "grep_files":
            return _exec_grep(
                repo_path,
                str(inp.get("pattern", "")),
                inp.get("path_glob") or None,
            )
        return f"Error: unknown tool {name!r}"
    except Exception as e:
        return f"Error executing {name}: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Diff capture
# ---------------------------------------------------------------------------

def _capture_diff(repo_path: str, base_branch: str) -> str:
    """Return the working-tree diff against ``base_branch``, capped in size."""
    cmds = [
        ["git", "diff", f"{base_branch}...HEAD", "--", "."],
        ["git", "diff", "HEAD", "--", "."],
        ["git", "diff", "--", "."],
    ]
    parts: List[str] = []
    for cmd in cmds:
        try:
            res = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        out = (res.stdout or "").strip()
        if out:
            parts.append(out)
    combined = "\n\n".join(parts)
    if len(combined) > DEFAULT_DIFF_BYTES:
        combined = combined[:DEFAULT_DIFF_BYTES] + (
            f"\n\n[... diff truncated at {DEFAULT_DIFF_BYTES} bytes ...]"
        )
    return combined or "(no diff captured — base branch may be missing locally)"


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

def _estimate_cost(model: str, usage: Dict[str, int]) -> float:
    p = _PRICING.get(model)
    if not p:
        return 0.0
    return (
        usage.get("input_tokens", 0)         * p["input"]          / 1_000_000
        + usage.get("output_tokens", 0)        * p["output"]         / 1_000_000
        + usage.get("cache_read_input_tokens", 0)  * p["cache_read"]     / 1_000_000
        + usage.get("cache_creation_input_tokens", 0) * p["cache_write_5m"] / 1_000_000
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

async def run_review(
    *,
    user_request: str,
    repo_path: str,
    base_branch: str,
    changed_files: List[Dict[str, Any]],
    target_score: float,
    anthropic_api_key: str,
    emit: Optional[Callable[[Dict[str, Any]], None]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the review loop, returning the canonical review dict + cost/duration.

    Returned shape::

        {
            "success": bool,
            "review": {alignment_score, is_aligned, mismatches,
                       fix_instructions, summary},
            "cost_usd": float,
            "duration_seconds": float,
            "error": Optional[str],
        }
    """

    def _emit(step: Dict[str, Any]) -> None:
        if emit:
            try:
                emit(step)
            except Exception:
                pass

    if not anthropic_api_key:
        return _err_result("Anthropic API key required for review pass.")
    if not os.path.isdir(repo_path):
        return _err_result(f"Repo path does not exist: {repo_path}")

    resolved_model = model or DEFAULT_REVIEW_MODEL

    diff_text = await asyncio.to_thread(_capture_diff, repo_path, base_branch)

    changed_lines = "\n".join(
        f"- {c.get('file_path', '')} ({c.get('action', 'modify')})"
        for c in (changed_files or [])[:200]
    ) or "- (no changed files reported)"

    user_message = (
        f"Target alignment score: {target_score:.0f}%\n\n"
        f"User request:\n{user_request.strip()}\n\n"
        f"Changed files in this run:\n{changed_lines}\n\n"
        f"Diff (vs {base_branch}):\n```diff\n{diff_text}\n```\n\n"
        "Inspect what you need with read_file/glob_files/grep_files, then "
        "call submit_review."
    )

    client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)
    messages: List[Dict[str, Any]] = [{"role": "user", "content": user_message}]

    total_usage = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
    }
    started = asyncio.get_event_loop().time()
    review_payload: Optional[Dict[str, Any]] = None
    inspected: List[Dict[str, str]] = []  # {"tool": "...", "target": "..."}

    try:
        for loop_idx in range(DEFAULT_MAX_TOOL_LOOPS):
            response = await client.messages.create(
                model=resolved_model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=[{
                    "type": "text",
                    "text": REVIEW_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                tools=REVIEW_TOOLS,
                tool_choice={"type": "any"},
                messages=messages,
            )

            usage = response.usage
            total_usage["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
            total_usage["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
            total_usage["cache_read_input_tokens"] += getattr(usage, "cache_read_input_tokens", 0) or 0
            total_usage["cache_creation_input_tokens"] += getattr(usage, "cache_creation_input_tokens", 0) or 0

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                _emit({
                    "type": "thinking",
                    "content": "Validator returned no tool call; ending review.",
                })
                break

            messages.append({"role": "assistant", "content": response.content})

            tool_results: List[Dict[str, Any]] = []
            for block in tool_uses:
                if block.name == "submit_review":
                    review_payload = dict(block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Review submitted.",
                    })
                    continue

                target = _tool_target(block.name, block.input)
                inspected.append({"tool": block.name, "target": target})
                _emit({
                    "type": "tool_call",
                    "tool_name": block.name,
                    "content": _describe_tool_call(block.name, block.input),
                })
                result = await asyncio.to_thread(
                    _execute_tool, repo_path, block.name, dict(block.input)
                )
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

            if review_payload is not None:
                break

            if response.stop_reason == "end_turn":
                break
        else:
            _emit({
                "type": "thinking",
                "content": (
                    f"Validator hit tool-loop cap ({DEFAULT_MAX_TOOL_LOOPS}) "
                    "without calling submit_review."
                ),
            })

    except anthropic.APIStatusError as e:
        return _err_result(
            f"Anthropic API error ({e.status_code}): {e.message}",
            cost_usd=_estimate_cost(resolved_model, total_usage),
            duration=asyncio.get_event_loop().time() - started,
        )
    except anthropic.APIConnectionError as e:
        return _err_result(
            f"Anthropic API connection error: {e}",
            cost_usd=_estimate_cost(resolved_model, total_usage),
            duration=asyncio.get_event_loop().time() - started,
        )

    duration = asyncio.get_event_loop().time() - started
    cost = _estimate_cost(resolved_model, total_usage)

    if review_payload is None:
        review = _default_review("Validator did not submit a review.")
        _emit({
            "type": "tool_result",
            "tool_name": "review_agent",
            "content": format_review_report(review, target_score, inspected),
        })
        return {
            "success": False,
            "review": review,
            "inspected": inspected,
            "cost_usd": cost,
            "duration_seconds": round(duration, 1),
            "error": "Validator did not submit a review.",
        }

    review = _normalize_review(review_payload, target_score)
    _emit({
        "type": "tool_result",
        "tool_name": "review_agent",
        "content": format_review_report(review, target_score, inspected),
    })
    return {
        "success": True,
        "review": review,
        "inspected": inspected,
        "cost_usd": cost,
        "duration_seconds": round(duration, 1),
        "error": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _describe_tool_call(name: str, inp: Dict[str, Any]) -> str:
    if name == "read_file":
        return f"Reading `{inp.get('path', '')}`"
    if name == "glob_files":
        return f"Listing `{inp.get('pattern', '')}`"
    if name == "grep_files":
        scope = inp.get("path_glob")
        scope_part = f" in `{scope}`" if scope else ""
        return f"Searching `{inp.get('pattern', '')}`{scope_part}"
    return f"Using {name}"


def _tool_target(name: str, inp: Dict[str, Any]) -> str:
    if name == "read_file":
        return str(inp.get("path", ""))
    if name == "glob_files":
        return str(inp.get("pattern", ""))
    if name == "grep_files":
        scope = inp.get("path_glob")
        return f"{inp.get('pattern', '')}" + (f" in {scope}" if scope else "")
    return ""


def format_review_report(
    review: Dict[str, Any],
    target_score: float,
    inspected: List[Dict[str, str]],
) -> str:
    """Render the canonical review verdict as Markdown for UI / PR display."""
    score = float(review.get("alignment_score", 0.0) or 0.0)
    is_aligned = bool(review.get("is_aligned", False))
    mismatches = review.get("mismatches", []) or []
    fixes = review.get("fix_instructions", []) or []
    summary = (review.get("summary") or "").strip()

    lines: List[str] = []
    verdict = "ALIGNED" if is_aligned else "NOT ALIGNED"
    lines.append(f"**Verdict:** {verdict} — alignment {score:.1f}% (target {target_score:.0f}%)")
    lines.append("")
    if summary:
        lines.append(f"**Summary:** {summary}")
        lines.append("")
    if inspected:
        lines.append(f"**Reviewed ({len(inspected)} action(s)):**")
        for item in inspected[:50]:
            tool = item.get("tool", "")
            target = item.get("target", "")
            label = {"read_file": "read", "glob_files": "glob", "grep_files": "grep"}.get(tool, tool)
            lines.append(f"- {label}: `{target}`")
        if len(inspected) > 50:
            lines.append(f"- … {len(inspected) - 50} more")
        lines.append("")
    if mismatches:
        lines.append(f"**Mismatches ({len(mismatches)}):**")
        for m in mismatches[:20]:
            lines.append(f"- {m}")
        if len(mismatches) > 20:
            lines.append(f"- … {len(mismatches) - 20} more")
        lines.append("")
    if fixes:
        lines.append(f"**Suggested fixes ({len(fixes)}):**")
        for f in fixes[:20]:
            lines.append(f"- {f}")
        if len(fixes) > 20:
            lines.append(f"- … {len(fixes) - 20} more")
        lines.append("")
    return "\n".join(lines).strip()


def _normalize_review(payload: Dict[str, Any], target_score: float) -> Dict[str, Any]:
    try:
        score = float(payload.get("alignment_score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(100.0, score))

    mismatches = [str(m).strip() for m in (payload.get("mismatches") or []) if str(m).strip()]
    fixes = [str(f).strip() for f in (payload.get("fix_instructions") or []) if str(f).strip()]

    declared = payload.get("is_aligned")
    if isinstance(declared, bool):
        is_aligned = declared and not mismatches and score >= target_score
    else:
        is_aligned = score >= target_score and not mismatches

    return {
        "alignment_score": score,
        "is_aligned": is_aligned,
        "mismatches": mismatches,
        "fix_instructions": fixes,
        "summary": str(payload.get("summary", "")).strip(),
    }


def _default_review(reason: str) -> Dict[str, Any]:
    return {
        "alignment_score": 0.0,
        "is_aligned": False,
        "mismatches": [reason],
        "fix_instructions": [],
        "summary": "",
    }


def _err_result(msg: str, *, cost_usd: float = 0.0, duration: float = 0.0) -> Dict[str, Any]:
    return {
        "success": False,
        "review": _default_review(msg),
        "cost_usd": cost_usd,
        "duration_seconds": round(duration, 1),
        "error": msg,
    }
