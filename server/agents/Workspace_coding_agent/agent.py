"""Workspace context Agent — read-only repository context provider.

This agent NEVER writes, modifies, or pushes code. Given a repo (cloned from
a URL or bound to a local path), it indexes the codebase and answers
context questions or produces structured feature-plan reports listing the
files, patterns, and references a developer would need to implement a
feature themselves.

Capabilities (all read-only):
  - Clone / refresh a remote repository for the session (per-request URL or
    via the `WORKSPACE_REPO_URL` agent-config setting).
  - Bind to an already-cloned local workspace via `workspace_root`.
  - Q&A over the codebase (intent: ``analyze`` / ``explain``).
  - Multi-feature implementation plan with tech stack, related files,
    architecture, coding patterns, and reference files (intent:
    ``feature_plan``).
  - Persistent sessions, TF-IDF semantic index, audit log.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.Claude_code_agent.workspace_context import (
    bind_workspace,
    build_context_files_block,
)
from agents.local_llm import (
    describe_missing_llm_credentials,
    is_llm_provider_configured,
)

from .audit_log import write_audit_entry
from .context_generator import generate_context
from .feature_planner import build_feature_plan
from .intent_classifier import classify_intent
from .repo_cloner import clone_or_refresh, parse_repo_url
from .session_store import get_session, save_session
from .workspace_tools import analyze_workspace


class WorkspaceCodingAgent:
    """Read-only workspace context agent."""

    def __init__(self) -> None:
        print(
            "Workspace context Agent initialized "
            "(read-only — clone/bind, index, answer questions, produce feature plans)"
        )

    # ── Session helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load_session(session_id: str) -> Dict[str, Any]:
        return get_session(session_id)

    @staticmethod
    def _persist_session(session_id: str, session: Dict[str, Any]) -> None:
        save_session(session_id, session)

    # ── Entry point ──────────────────────────────────────────────────────────

    async def process_query(
        self,
        query: str,
        session_id: str = "default",
        workspace_root: Optional[str] = None,
        context_files: Optional[list] = None,
        repo_url: Optional[str] = None,
        repo_branch: Optional[str] = None,
        repo_token: Optional[str] = None,
        **_ignored: Any,
    ) -> Dict[str, Any]:
        """Process one user request and return repository context.

        Parameters
        ----------
        query          : Natural-language request.
        session_id     : Caller-supplied key to maintain session state across
                         calls.
        workspace_root : Absolute path of an already-cloned local project.
                         Required if ``repo_url`` is not supplied.
        context_files  : Optional list of paths whose contents are injected
                         into the prompt.
        repo_url       : Optional remote git URL. When supplied, the agent
                         clones (or refreshes) the repo into a per-session
                         workspace and uses that path.
        repo_branch    : Optional branch to clone / check out.
        repo_token     : Optional auth token for private repos. Never
                         persisted — used only for the git command.

        Any extra keyword args (e.g. legacy ``dry_run``) are accepted and
        ignored — the agent has no write paths.
        """
        thinking_steps: List[Dict[str, Any]] = []
        session = self._load_session(session_id)

        # ── Resolve repo settings: per-request param > agent-config env var ──
        repo_url = repo_url or os.environ.get("WORKSPACE_REPO_URL")
        repo_branch = repo_branch or os.environ.get("WORKSPACE_REPO_BRANCH")
        repo_token = repo_token or os.environ.get("WORKSPACE_REPO_TOKEN")

        # Skip refresh if URL came from agent config and clone already exists.
        if (
            repo_url
            and repo_url == os.environ.get("WORKSPACE_REPO_URL")
            and session.get("repo_path")
            and Path(session["repo_path"], ".git").is_dir()
        ):
            repo_url = None

        # ── Clone / refresh ──────────────────────────────────────────────────
        ru = (repo_url or "").strip()
        if ru:
            if not parse_repo_url(ru):
                return {
                    "success": False,
                    "response": f"Unrecognized repository URL: {ru!r}",
                    "thinking_steps": thinking_steps,
                }
            thinking_steps.append({
                "type": "tool_call",
                "content": f"Cloning {ru} (branch: {repo_branch or 'default'})…",
                "tool_name": "git_clone",
            })
            clone_result = clone_or_refresh(
                repo_url=ru,
                session_id=session_id,
                token=(repo_token or "").strip(),
                branch=(repo_branch or "").strip() or None,
            )
            if not clone_result.get("success"):
                return {
                    "success": False,
                    "response": f"Clone failed: {clone_result.get('error', 'unknown error')}",
                    "thinking_steps": thinking_steps,
                }
            workspace_root = clone_result["path"]
            session["repo_url"] = ru
            session["repo_branch"] = clone_result.get("default_branch")
            session["head_sha"] = clone_result.get("head_sha")
            thinking_steps.append({
                "type": "tool_result",
                "content": (
                    f"{'Refreshed' if clone_result.get('reused') else 'Cloned'} "
                    f"{clone_result.get('owner')}/{clone_result.get('name')} "
                    f"@ {(clone_result.get('head_sha') or '')[:7]} → {workspace_root}"
                ),
            })

        # ── Workspace binding ────────────────────────────────────────────────
        wr = (workspace_root or "").strip()
        if wr:
            ok, err = bind_workspace(session, wr)
            if not ok:
                return {
                    "success": False,
                    "response": err or "Invalid workspace_root.",
                    "thinking_steps": thinking_steps,
                }
            thinking_steps.append({
                "type": "thinking",
                "content": f"Workspace bound: {session['repo_path']}",
            })
            self._persist_session(session_id, session)

        if not session.get("repo_path"):
            return {
                "success": False,
                "response": (
                    "This agent needs a **workspace** before it can answer.\n\n"
                    "- Pass **repo_url** (HTTPS git URL) — the agent clones it for "
                    "this session. Optional **repo_branch** and **repo_token** for "
                    "private repos.\n"
                    "- Or pass **workspace_root** (absolute path on the API host) "
                    "to use an existing local checkout.\n\n"
                    "Optional **context_files**: list of paths relative to "
                    "workspace_root to inject as prompt context.\n\n"
                    "_This agent is **read-only** — it produces context and "
                    "references, never code changes._"
                ),
                "thinking_steps": thinking_steps,
            }

        # ── LLM provider check ───────────────────────────────────────────────
        if not is_llm_provider_configured():
            return {
                "success": False,
                "response": (
                    f"{describe_missing_llm_credentials()}\n\n"
                    "Set credentials in agent configuration for your selected "
                    "**LLM_PROVIDER** (PwC GenAI, Ollama Cloud, or local LLM)."
                ),
                "thinking_steps": thinking_steps,
            }

        # ── context_files injection ──────────────────────────────────────────
        cf_list: List[str] = []
        if context_files:
            if not isinstance(context_files, list):
                return {
                    "success": False,
                    "response": "context_files must be an array of path strings.",
                    "thinking_steps": thinking_steps,
                }
            cf_list = [str(x) for x in context_files]

        original_query = query
        effective_query = original_query
        if cf_list:
            block, _notes = build_context_files_block(
                Path(session["repo_path"]), cf_list
            )
            if block:
                effective_query = (
                    f"{block}\n\n---\n**User request:**\n{original_query}"
                )
                thinking_steps.append({
                    "type": "thinking",
                    "content": f"Injected {len(cf_list)} context file(s) into prompt.",
                })
            else:
                thinking_steps.append({
                    "type": "thinking",
                    "content": "context_files: no readable content found (check paths).",
                })

        # ── Intent classification (read-only taxonomy) ───────────────────────
        intent_result = classify_intent(original_query, use_llm=True)
        intent = intent_result["intent"]
        confidence = intent_result.get("confidence", 0.5)
        target_files: List[str] = intent_result.get("target_files", [])
        change_desc = intent_result.get("change_description", "")

        thinking_steps.append({
            "type": "thinking",
            "content": (
                f"Intent: **{intent}** (confidence {confidence:.0%})"
                + (f" — {change_desc}" if change_desc else "")
            ),
        })

        # ── Dispatch (read-only: generate_context, feature_plan, analyze/explain) ─
        try:
            if intent == "generate_context":
                return await self._handle_context_generation(
                    original_query, session, session_id, thinking_steps,
                )

            if intent == "feature_plan":
                return await self._handle_feature_plan(
                    original_query, session, session_id, thinking_steps,
                )

            return await self._handle_analyze(
                effective_query, session, session_id,
                thinking_steps, target_files, original_query,
            )

        except Exception as exc:
            write_audit_entry(
                workspace_root=session.get("repo_path", ""),
                session_id=session_id,
                query=original_query[:500],
                intent=intent,
                files_modified=[],
                response_preview="",
                error=str(exc),
            )
            return {
                "success": False,
                "response": f"Error: {exc}",
                "thinking_steps": thinking_steps,
            }

    # ── Intent handlers (read-only) ──────────────────────────────────────────

    async def _handle_analyze(
        self,
        query: str,
        session: Dict[str, Any],
        session_id: str,
        thinking_steps: List[Dict[str, Any]],
        target_files: List[str],
        original_query: str,
    ) -> Dict[str, Any]:
        thinking_steps.append({
            "type": "tool_call",
            "content": f"Semantic-indexed Q&A over {session['repo_name']}",
            "tool_name": "llm_workspace_analyze",
        })

        response = await analyze_workspace(
            repo_path=session["repo_path"],
            repo_name=session["repo_name"],
            query=query,
            target_files=target_files,
        )

        thinking_steps.append({
            "type": "tool_result",
            "content": "Analysis complete",
        })

        write_audit_entry(
            workspace_root=session["repo_path"],
            session_id=session_id,
            query=original_query[:500],
            intent="analyze",
            files_modified=[],
            response_preview=response[:300],
        )

        return {
            "success": True,
            "response": response,
            "thinking_steps": thinking_steps,
        }

    async def _handle_feature_plan(
        self,
        query: str,
        session: Dict[str, Any],
        session_id: str,
        thinking_steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        thinking_steps.append({
            "type": "tool_call",
            "content": (
                f"Building feature plan for {session['repo_name']} "
                f"(scanning manifests + retrieving relevant files per feature)"
            ),
            "tool_name": "llm_workspace_feature_plan",
        })

        plan = await build_feature_plan(
            repo_path=session["repo_path"],
            repo_name=session["repo_name"],
            query=query,
            branch_sha=session.get("head_sha", "") or "",
        )

        thinking_steps.append({
            "type": "tool_result",
            "content": (
                f"Plan ready — {len(plan.get('features', []))} feature(s), "
                f"{len(plan['stack'].get('manifests_found', []))} manifest(s) detected"
            ),
        })

        write_audit_entry(
            workspace_root=session["repo_path"],
            session_id=session_id,
            query=query[:500],
            intent="feature_plan",
            files_modified=[],
            response_preview=plan["markdown"][:300],
        )

        return {
            "success": True,
            "response": plan["markdown"],
            "thinking_steps": thinking_steps,
            "feature_plan": plan["json"],
            "tech_stack": plan["stack"],
            "features": plan["features"],
        }


    async def _handle_context_generation(
        self,
        query: str,
        session: Dict[str, Any],
        session_id: str,
        thinking_steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        thinking_steps.append({
            "type": "tool_call",
            "content": (
                f"Splitting input into features and retrieving per-feature "
                f"codebase context from {session['repo_name']}"
            ),
            "tool_name": "llm_generate_context",
        })

        result = await generate_context(
            repo_path=session["repo_path"],
            repo_name=session["repo_name"],
            query=query,
            branch_sha=session.get("head_sha", "") or "",
        )

        thinking_steps.append({
            "type": "tool_result",
            "content": (
                f"Context ready — {len(result.get('features', []))} feature(s)"
            ),
        })

        write_audit_entry(
            workspace_root=session["repo_path"],
            session_id=session_id,
            query=query[:500],
            intent="generate_context",
            files_modified=[],
            response_preview=result["markdown"][:300],
        )

        return {
            "success": True,
            "response": result["markdown"],
            "thinking_steps": thinking_steps,
            "feature_contexts": result["json"],
            "features": result["features"],
        }


workspace_coding_agent = WorkspaceCodingAgent()