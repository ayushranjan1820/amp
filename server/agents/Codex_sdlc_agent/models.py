from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CodexSDLCRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    workspace_root: Optional[str] = None
    context_files: Optional[List[str]] = None
    dry_run: bool = False
    create_pr: bool = False
    github_token: Optional[str] = None
    max_retries: int = 2
    target_coverage: Optional[int] = None
    user_config: Optional[Dict[str, str]] = None


class CodexSDLCResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[Dict[str, Any]] = []
    timestamp: str
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    plan: List[Dict[str, Any]] = []
    validation_summary: Dict[str, Any] = {}
    pr_payload: Optional[Dict[str, Any]] = None
    files_changed: List[str] = []


@dataclass
class PlanStep:
    step_id: str
    kind: str
    title: str
    prompt: str
    validator_profile: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    max_retries: int = 2


@dataclass
class ExecutionResult:
    success: bool
    response: str
    files_changed: List[str] = field(default_factory=list)
    diff: str = ""
    artifacts: Dict[str, Any] = field(default_factory=dict)
    backend: str = "workspace_llm"


@dataclass
class ValidationResult:
    success: bool
    summary: str
    checks: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RunState:
    session_id: str
    run_id: str
    query: str
    workspace_root: str
    repo_name: str
    user_id: Optional[str] = None
    dry_run: bool = False
    create_pr: bool = False
    github_token: Optional[str] = None
    context_block: str = ""
    target_coverage: Optional[int] = None
    memory: Dict[str, Any] = field(default_factory=dict)
    plan: List[PlanStep] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    validation_history: List[Dict[str, Any]] = field(default_factory=list)
    execution_history: List[Dict[str, Any]] = field(default_factory=list)
    pr_payload: Optional[Dict[str, Any]] = None
