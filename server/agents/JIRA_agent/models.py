"""Request / Response models for JIRA Agent API.

Enterprise improvements:
- RBAC context fields (user_id, user_role) on request
- Audit trail fields (performed_by, audit_id) on response
- Structured error field with code + detail
"""
from typing import Dict, Any, Optional, List

from pydantic import BaseModel, Field


class ThinkingStep(BaseModel):
    """Represents an intermediate thinking step from the agent."""
    type: str  # 'thinking', 'tool_call', 'tool_result', 'observation'
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class JIRAAgentRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    context_data: Optional[Dict[str, Any]] = None
    user_config: Optional[Dict[str, str]] = None

    # RBAC context — populated by API gateway / auth middleware
    user_id: Optional[str] = Field(default=None, description="Authenticated user identifier")
    user_role: Optional[str] = Field(default=None, description="User role for RBAC (admin, editor, viewer)")


class ErrorDetail(BaseModel):
    """Structured error info — never leak internal tracebacks."""
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."


class JIRAAgentResponse(BaseModel):
    success: bool
    query: str
    response: str
    state: Optional[str] = None
    session_id: Optional[str] = None
    tickets: list = []
    missing_fields: list = []
    collected_data: Dict[str, Any] = {}
    thinking_steps: List[ThinkingStep] = []
    timestamp: str
    duration_ms: Optional[int] = None

    # Audit trail
    performed_by: Optional[str] = Field(default=None, description="User who triggered the action")
    audit_id: Optional[str] = Field(default=None, description="Unique audit trace ID for compliance")

    # Structured error (replaces bare string errors)
    error: Optional[ErrorDetail] = None
