from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime


class WebSearchRequest(BaseModel):
    query: str = Field(..., description="The user's search query")
    search_focus: Optional[str] = Field(default=None, description="Search focus: general, academic, writing, math, news")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation context")
    clear_history: Optional[bool] = Field(default=False, description="Clear conversation history for this session")
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    type: str = Field(..., description="Type: thinking, tool_call, tool_result, observation")
    content: str = Field(..., description="Content of the thinking step")
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class SearchSource(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    domain: str = ""
    image_url: Optional[str] = None


class WebSearchResponse(BaseModel):
    success: bool = True
    query: str = ""
    search_focus: str = "general"
    response: str = ""
    sources: List[SearchSource] = []
    images: List[str] = []
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    thinking_steps: List[ThinkingStep] = []
    tool_results: Optional[List[dict]] = None
    follow_up_questions: List[str] = []
