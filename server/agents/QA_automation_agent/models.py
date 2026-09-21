from typing import Dict, List, Optional
from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class QAAutomationRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    github_token: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class QAAutomationResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
    pr_url: Optional[str] = None
    branch: Optional[str] = None
    pushed_files: List[str] = []
    files_changed: List[str] = []
