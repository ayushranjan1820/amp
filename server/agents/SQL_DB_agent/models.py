"""Request / response contracts for the SQL DB Agent."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None


class ExplainWarning(BaseModel):
    """Warning from EXPLAIN plan analysis before query execution."""
    step: int
    estimated_rows: Optional[int] = None
    estimated_cost: Optional[float] = None
    seq_scans: List[str] = []
    warning: str


class SqlDbChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    show_sql: bool = True
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None
    page: int = 1
    page_size: int = 500


class SqlDbChatResponse(BaseModel):
    success: bool
    response: str
    query: str = ""
    thinking_steps: List[ThinkingStep] = []
    timestamp: str = ""
    generated_sql: Optional[str] = None
    result_preview: Optional[Any] = None
    mermaid_erd: Optional[str] = None
    page_info: Optional[Dict[str, Any]] = None
    explain_warnings: List[Dict[str, Any]] = []
    cached: bool = False
