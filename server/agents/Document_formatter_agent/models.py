from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class DocumentFormatterRequest(BaseModel):
    query: str = Field(..., description="Formatting instructions or description of desired output")
    file_content: Optional[str] = Field(default=None, description="Base64 encoded file content")
    file_type: Optional[str] = Field(default=None, description="File extension (pdf, docx, pptx, xlsx, txt, html, etc.)")
    file_name: Optional[str] = Field(default=None, description="Original file name")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation context")
    output_format: Optional[str] = Field(default="markdown", description="Desired output format: markdown, html, json, plain")
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    type: str = Field(..., description="Type: thinking, tool_call, tool_result, observation")
    content: str = Field(..., description="Content of the thinking step")
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class DocumentFormatterResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str = ""
    formatted_content: Optional[str] = None
    extracted_text: Optional[str] = None
    extracted_images: List[Dict[str, Any]] = []
    file_name: Optional[str] = None
    output_format: str = "markdown"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    thinking_steps: List[ThinkingStep] = []
