from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None


class ETLChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None
    # Optional: caller can pass a DataFrame reference or inline CSV/JSON data
    data_source: Optional[str] = None
    data_format: Optional[str] = None  # "csv", "json", "sql_table", "inline"


class ETLChatResponse(BaseModel):
    success: bool
    response: str
    query: str = ""
    thinking_steps: List[ThinkingStep] = []
    timestamp: str = ""
    generated_code: Optional[str] = None
    result_preview: Optional[Any] = None
    output_schema: Optional[Dict[str, Any]] = None
    execution_stats: Optional[Dict[str, Any]] = None
