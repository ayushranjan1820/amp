"""
Request/Response models for Basic Agent API.
"""
from typing import Dict, List, Optional
from pydantic import BaseModel


class ThinkingStep(BaseModel):
    """Represents an intermediate thinking step from the agent."""
    type: str  # 'thinking', 'tool_call', 'tool_result'
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class BasicAgentRequest(BaseModel):
    query: str
    clear_history: bool = False
    session_id: Optional[str] = None
    user_config: Optional[Dict[str, str]] = None


class BasicAgentResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
