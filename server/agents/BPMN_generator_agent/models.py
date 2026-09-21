"""
Pydantic models for BPMN Generator Agent API.
"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class BPMNAgentRequest(BaseModel):
    """Request model for BPMN Generator Agent."""
    query: str
    session_id: Optional[str] = None
    file_content: Optional[str] = None
    file_type: Optional[str] = None
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    """Model for agent thinking steps."""
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class BPMNAgentResponse(BaseModel):
    """Response model for BPMN Generator Agent."""
    success: bool
    query: str
    response: str
    bpmn_xml: Optional[str] = None
    session_id: Optional[str] = None
    thinking_steps: List[Dict[str, Any]] = []
    timestamp: str
