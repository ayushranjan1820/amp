from typing import Dict, List, Optional
from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class SandboxRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class SandboxResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
    stackblitz_repo: Optional[str] = None
    status: Optional[str] = None
