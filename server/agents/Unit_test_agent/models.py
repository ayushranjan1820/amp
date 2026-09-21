from typing import Dict, List, Optional
from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class UnitTestRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    github_token: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class UnitTestResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
    requires_token: bool = False
    repo_url: Optional[str] = None
    task_id: Optional[str] = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: str
    thinking_steps: List[ThinkingStep] = []
    response: Optional[str] = None
    success: Optional[bool] = None
