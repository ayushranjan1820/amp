from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

class MarketResearchRequest(BaseModel):
    query: str = Field(..., description="The market research query")
    email_recipients: Optional[List[str]] = Field(default=None, description="List of email addresses to send the report to")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation context")
    user_config: Optional[Dict[str, str]] = None

class ResearchSource(BaseModel):
    title: str
    url: str
    snippet: str
    published_date: Optional[str] = None

class ThinkingStep(BaseModel):
    type: str = Field(..., description="Type: thinking, tool_call, tool_result, observation")
    content: str = Field(..., description="Content of the thinking step")
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None

class MarketResearchResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    sources: List[ResearchSource] = []
    email_sent: bool = False
    email_recipients: List[str] = []
    thinking_steps: List[ThinkingStep] = []
    tool_results: Optional[List[dict]] = None
