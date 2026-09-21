from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CoderAgentRequest(BaseModel):
    query: str = Field(..., description="Problem statement for the coder workflow")
    file_content: Optional[str] = Field(default=None, description="Optional base64 file content")
    file_type: Optional[str] = Field(default=None, description="Optional file extension (pdf, csv, xlsx, docx)")
    file_name: Optional[str] = Field(default=None, description="Original uploaded file name")
    session_id: Optional[str] = Field(default=None, description="Session id for conversational continuity")
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class CoderAgentResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str = ""
    standalone_html: Optional[str] = None
    architecture: Optional[Dict[str, Any]] = None
    business_outcomes: List[Dict[str, str]] = []
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    thinking_steps: List[ThinkingStep] = []
