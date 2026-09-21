from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class GitHubRepoRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    github_token: Optional[str] = None
    repo_url: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class GitHubRepoResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
    requires_token: bool = False
    repo_url: Optional[str] = None
    architecture_diagram: Optional[str] = None
