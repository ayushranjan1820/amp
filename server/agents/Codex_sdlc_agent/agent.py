from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from agents.Claude_code_agent.workspace_context import bind_workspace, build_context_files_block
from agents.GitHub_repo_agent.tools.clone_tool import clone_repo
from agents.GitHub_repo_agent.utils.git_utils import extract_repo_url

from .codex_executor import CodexExecutor
from .feedback_loop import build_retry_prompt
from .memory_store import append_run_log, load_repo_memory, save_repo_memory
from .models import PlanStep, RunState
from .planner import build_plan
from .services.git_service import get_git_diff
from .services.pr_service import build_pr_payload
from .services.workspace_manager import create_isolated_workspace, isolated_workspaces_enabled
from .validator import validate_step


class CodexSDLCAgent:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.executor = CodexExecutor()
        self.repos_dir = Path(__file__).resolve().parents[3] / "repos"
        self.repos_dir.mkdir(exist_ok=True)
        print("Codex SDLC Agent initialized (planner + validator + feedback loop)")

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "repo_path": None,
                "repo_name": None,
                "modified_files": [],
                "last_plan": [],
            }
        return self.sessions[session_id]

    async def process_query(
        self,
        query: str,
        session_id: str = "default",
        user_id: Optional[str] = None,
        run_id: Optional[str] = None,
        workspace_root: Optional[str] = None,
        context_files: Optional[list] = None,
        dry_run: bool = False,
        create_pr: bool = False,
        github_token: Optional[str] = None,
        max_retries: int = 2,
        target_coverage: Optional[int] = None,
    ) -> Dict[str, Any]:
        thinking_steps: List[Dict[str, Any]] = []
        session = self._get_session(session_id)
        run_id = run_id or uuid.uuid4().hex

        wr = (workspace_root or "").strip()
        if wr:
            ok, err = bind_workspace(session, wr)
            if not ok:
                return {"success": False, "response": err or "Invalid workspace_root.", "thinking_steps": thinking_steps}
            thinking_steps.append({"type": "thinking", "content": f"Workspace bound: {session['repo_path']}"})

        if not session.get("repo_path"):
            repo_url = extract_repo_url(query)
            if repo_url:
                thinking_steps.append({
                    "type": "tool_call",
                    "content": f"Cloning repository: {repo_url}",
                    "tool_name": "clone_repo",
                })
                clone_result = clone_repo(repo_url, self.repos_dir, session_id)
                if not clone_result["success"]:
                    return {
                        "success": False,
                        "response": f"Failed to clone repository: {clone_result['error']}",
                        "thinking_steps": thinking_steps,
                    }
                ok, err = bind_workspace(session, clone_result["path"])
                if not ok:
                    return {
                        "success": False,
                        "response": err or "Repository cloned but workspace binding failed.",
                        "thinking_steps": thinking_steps,
                    }
                session["repo_url"] = repo_url
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"Repository cloned and bound: {session['repo_path']}",
                    "tool_name": "clone_repo",
                })

        if not session.get("repo_path"):
            return {
                "success": False,
                "response": (
                    "This agent requires a local project. Pass `workspace_root` on the first call "
                    "and optionally `context_files` for focused context."
                ),
                "thinking_steps": thinking_steps,
            }

        execution_root = session["repo_path"]
        isolated_mode = None
        if isolated_workspaces_enabled():
            execution_root, isolated_mode = create_isolated_workspace(session["repo_path"], run_id)
            thinking_steps.append({
                "type": "thinking",
                "content": f"Created isolated workspace for this run using {isolated_mode}: {execution_root}",
            })

        context_block = ""
        if context_files:
            block, notes = build_context_files_block(Path(execution_root), [str(x) for x in context_files])
            context_block = block
            if block:
                thinking_steps.append({"type": "thinking", "content": f"Injected {len(context_files)} context file(s)."})
            elif notes:
                thinking_steps.append({"type": "thinking", "content": "context_files were provided but no readable content was loaded."})

        plan = build_plan(
            query=query,
            target_coverage=target_coverage,
            create_pr=create_pr,
            max_retries=max_retries,
        )
        session["last_plan"] = [step.__dict__ for step in plan]
        thinking_steps.append({"type": "thinking", "content": f"Planner produced {len(plan)} step(s)."})

        state = RunState(
            session_id=session_id,
            run_id=run_id,
            query=query,
            workspace_root=execution_root,
            repo_name=Path(execution_root).name or session["repo_name"],
            user_id=user_id,
            dry_run=dry_run,
            create_pr=create_pr,
            github_token=github_token,
            context_block=context_block,
            target_coverage=target_coverage,
            memory=load_repo_memory(session["repo_path"]),
            plan=plan,
        )
        state.memory["source_workspace_root"] = session["repo_path"]
        state.memory["isolated_workspace_mode"] = isolated_mode

        final_messages: List[str] = []
        validation_summary: Dict[str, Any] = {}

        append_run_log(run_id, self._build_run_log(state, success=False, status="started"))

        for step in plan:
            thinking_steps.append({"type": "tool_call", "content": f"Executing plan step: {step.title}", "tool_name": step.kind})
            current_step = step
            step_success = False

            for attempt in range(1, step.max_retries + 1):
                execution = await self.executor.execute(current_step, state)
                if not execution.success:
                    state.execution_history.append({
                        "step_id": current_step.step_id,
                        "attempt": attempt,
                        "backend": execution.backend,
                        "files_changed": execution.files_changed,
                        "error": execution.response[:1000],
                    })
                    thinking_steps.append({
                        "type": "tool_result",
                        "content": f"{current_step.title}: Codex execution failed.",
                        "tool_name": current_step.kind,
                    })
                    final_messages.append(f"### {current_step.title}\n{execution.response}")
                    save_repo_memory(session["repo_path"], self._update_memory(state))
                    append_run_log(run_id, self._build_run_log(state, success=False, status="failed"))
                    return {
                        "success": False,
                        "response": "\n\n".join(final_messages),
                        "thinking_steps": thinking_steps,
                        "plan": [s.__dict__ for s in plan],
                        "validation_summary": validation_summary,
                        "files_changed": state.files_changed,
                        "run_id": run_id,
                        "user_id": user_id,
                    }
                state.files_changed.extend([p for p in execution.files_changed if p not in state.files_changed])
                state.execution_history.append({
                    "step_id": current_step.step_id,
                    "attempt": attempt,
                    "backend": execution.backend,
                    "files_changed": execution.files_changed,
                })

                validation = validate_step(current_step, state, execution)
                validation_summary[current_step.validator_profile] = validation.metrics
                state.validation_history.append({
                    "step_id": current_step.step_id,
                    "attempt": attempt,
                    "success": validation.success,
                    "summary": validation.summary,
                    "checks": validation.checks,
                })

                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"{current_step.title}: {validation.summary}",
                    "tool_name": current_step.kind,
                })

                if validation.success:
                    final_messages.append(f"### {current_step.title}\n{execution.response}")
                    step_success = True
                    break

                if attempt < current_step.max_retries:
                    retry_prompt = build_retry_prompt(current_step, execution, validation)
                    current_step = PlanStep(
                        step_id=current_step.step_id,
                        kind=current_step.kind,
                        title=current_step.title,
                        prompt=retry_prompt,
                        validator_profile=current_step.validator_profile,
                        metadata=current_step.metadata,
                        max_retries=current_step.max_retries,
                    )
                    thinking_steps.append({
                        "type": "thinking",
                        "content": f"Validation failed for {current_step.title}; retrying attempt {attempt + 1}/{current_step.max_retries}.",
                    })
                else:
                    final_messages.append(f"### {current_step.title}\nValidation failed after {attempt} attempt(s).\n{execution.response}")

            if not step_success and step.validator_profile in {"quality_gate", "security_gate"}:
                save_repo_memory(session["repo_path"], self._update_memory(state))
                append_run_log(run_id, self._build_run_log(state, success=False, status="failed"))
                return {
                    "success": False,
                    "response": "\n\n".join(final_messages),
                    "thinking_steps": thinking_steps,
                    "plan": [s.__dict__ for s in plan],
                    "validation_summary": validation_summary,
                    "files_changed": state.files_changed,
                    "run_id": run_id,
                    "user_id": user_id,
                }

        save_repo_memory(session["repo_path"], self._update_memory(state))

        if create_pr or any(step.kind == "pr" for step in plan):
            state.pr_payload = build_pr_payload(query, state.files_changed, validation_summary)
            final_messages.append(f"### Pull Request Draft\n{state.pr_payload['body']}")

        append_run_log(run_id, self._build_run_log(state, success=True, status="completed"))
        return {
            "success": True,
            "response": "\n\n".join(final_messages) or "No output produced.",
            "thinking_steps": thinking_steps,
            "plan": [s.__dict__ for s in plan],
            "validation_summary": validation_summary,
            "pr_payload": state.pr_payload,
            "files_changed": state.files_changed,
            "run_id": run_id,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "diff": get_git_diff(execution_root) if not dry_run else "",
        }

    def _update_memory(self, state: RunState) -> Dict[str, Any]:
        memory = dict(state.memory)
        patterns = set(memory.get("repo_patterns", []))
        patterns.update(state.files_changed[:20])
        memory["repo_patterns"] = sorted(patterns)[:50]

        previous = memory.get("previous_fixes", [])
        previous.append({
            "query": state.query[:300],
            "files_changed": state.files_changed[:20],
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
        memory["previous_fixes"] = previous[-20:]

        failures = memory.get("common_failures", [])
        for item in state.validation_history:
            if not item["success"]:
                failures.append({
                    "step_id": item["step_id"],
                    "summary": item["summary"],
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                })
        memory["common_failures"] = failures[-20:]
        return memory

    def _build_run_log(self, state: RunState, success: bool, status: str) -> Dict[str, Any]:
        return {
            "session_id": state.session_id,
            "run_id": state.run_id,
            "user_id": state.user_id,
            "query": state.query,
            "workspace_root": state.workspace_root,
            "source_workspace_root": state.memory.get("source_workspace_root", state.workspace_root),
            "status": status,
            "success": success,
            "files_changed": state.files_changed,
            "plan": [step.__dict__ for step in state.plan],
            "validation_history": state.validation_history,
            "execution_history": state.execution_history,
            "pr_payload": state.pr_payload,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }


codex_sdlc_agent = CodexSDLCAgent()
