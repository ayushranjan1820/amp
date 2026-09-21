from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, List, Optional
from datetime import datetime


MAX_SLIDES = 30
MIN_SLIDES = 2


class PPTGeneratorRequest(BaseModel):
    query: str = Field(..., description="Topic or instructions for the presentation", min_length=1, max_length=16000)
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation context")
    slide_count: Optional[int] = Field(default=None, description="Desired number of slides (auto if not set)", ge=MIN_SLIDES, le=MAX_SLIDES)
    theme: Optional[str] = Field(default="aurora", description="Visual theme: aurora, midnight, professional, modern, dark, vibrant, consulting, pwc")
    file_content: Optional[str] = Field(default=None, description="Base64 file content for uploaded input documents")
    file_type: Optional[str] = Field(default=None, description="Uploaded file extension (csv, xlsx, xls, pdf, txt, docx)")
    file_name: Optional[str] = Field(default=None, description="Uploaded source file name")
    web_search_enabled: Optional[bool] = Field(
        default=None,
        description="Omit or null to use agent config (PPT_WEB_SEARCH_ENABLED). True forces search on; False forces off.",
    )
    user_config: Optional[Dict[str, str]] = None

    @field_validator("theme")
    @classmethod
    def _validate_theme(cls, v: Optional[str]) -> str:
        allowed = {"aurora", "midnight", "professional", "modern", "dark", "vibrant", "consulting", "pwc"}
        if not v or v.lower() not in allowed:
            return "aurora"
        return v.lower()


class ThinkingStep(BaseModel):
    type: str = Field(..., description="Type: thinking, tool_call, tool_result, observation")
    content: str = Field(..., description="Content of the thinking step")
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class PPTGeneratorResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str = ""
    download_url: Optional[str] = None
    file_name: Optional[str] = None
    slide_count: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    thinking_steps: List[ThinkingStep] = []
    research_sources: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="URLs distilled from Perplexity slide research (title, url, date).",
    )
