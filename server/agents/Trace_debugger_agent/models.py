from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TraceDebuggerRequest(BaseModel):
    trace_id: Optional[str] = Field(default=None, description="Langfuse trace identifier")
    query: Optional[str] = Field(
        default=None,
        description="Open-ended query: search, investigate, debug, get logs, explore sessions, etc.",
    )
    session_id: Optional[str] = Field(default=None, description="Optional chat session identifier")
    user_config: Optional[Dict[str, str]] = None


class TraceDebuggerResponse(BaseModel):
    success: bool = True
    trace_id: str = ""
    response: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    thinking_steps: List[Dict[str, Any]] = []
    analysis: Dict[str, Any] = Field(default_factory=dict)
    normalized_trace: Dict[str, Any] = Field(default_factory=dict)
    operation: str = Field(default="", description="What operation was performed")
    data: Dict[str, Any] = Field(default_factory=dict, description="Raw data payload for the frontend")
