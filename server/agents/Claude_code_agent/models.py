from typing import List, Optional

from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class ClaudeCodeRequest(BaseModel):
    """End-to-end request: prompt + the three required config values."""
    query: str
    session_id: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    github_token: Optional[str] = None
    repo_url: Optional[str] = None
    base_branch: Optional[str] = None


class ClaudeCodeResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
    requires_token: bool = False
    repo_url: Optional[str] = None
    generated_files: List[str] = []
    pr_url: Optional[str] = None
    branch: Optional[str] = None
