from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

from agents.Company_research_agent.models import NewsCard


class MeetingPrepRequest(BaseModel):
    query: str = Field(..., description="Meeting context or query")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation context")
    clear_history: Optional[bool] = Field(default=False, description="Clear session history")
    email_recipients: Optional[List[str]] = Field(default=None, description="Email addresses to send the meeting brief to")
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    type: str = Field(..., description="Type: thinking, tool_call, tool_result, observation")
    content: str = Field(..., description="Content of the thinking step")
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class MeetingPrepResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    thinking_steps: List[ThinkingStep] = []
    tool_results: Optional[List[dict]] = None
    phase: str = "complete"
    email_sent: bool = False
    email_recipients: List[str] = []
    # Candidate image URLs from Perplexity Sonar (chat); brief may embed a subset in markdown.
    report_image_urls: List[str] = Field(default_factory=list)
    # Dedicated Perplexity news-cards pass (same shape as Company Research Agent).
    latest_news_cards: List[NewsCard] = Field(default_factory=list)
