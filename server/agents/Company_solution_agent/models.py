from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UploadedSolutionFile(BaseModel):
    file_content: str = Field(..., description="Base64 encoded file content")
    file_type: str = Field(..., description="File extension (pdf, docx, doc, txt, md, html, etc.)")
    file_name: Optional[str] = Field(default=None, description="Original file name")


class CompanySolutionRequest(BaseModel):
    query: str = Field(..., description="Detailed company context, challenges, and current process details")
    company_name: Optional[str] = Field(default=None, description="Optional explicit company name")
    company_details: Optional[str] = Field(default=None, description="Optional extra company details text")
    uploaded_files: Optional[List[UploadedSolutionFile]] = Field(
        default=None,
        description="Optional catalog of the user's existing AI solutions (PDF/Word/text). If provided, the agent will prefer relevant solutions from this catalog before suggesting its own.",
    )
    file_content: Optional[str] = Field(
        default=None,
        description="Single-file convenience field (base64) — used by the in-app chat uploader. Merged into uploaded_files server-side.",
    )
    file_type: Optional[str] = Field(default=None, description="Single-file convenience field: extension (pdf, docx, txt, ...)")
    file_name: Optional[str] = Field(default=None, description="Single-file convenience field: original filename")
    session_id: Optional[str] = Field(default=None, description="Session ID for conversation context")
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    type: str = Field(..., description="Type: thinking, tool_call, tool_result, observation")
    content: str = Field(..., description="Content of the thinking step")
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


class CompanySolutionResponse(BaseModel):
    success: bool = True
    query: str = ""
    response: str = ""
    company_name: Optional[str] = None
    chunk_count: int = 0
    existing_solutions_used: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of solutions picked from the user's uploaded catalog with matched problem(s)",
    )
    suggested_solutions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of new solutions suggested by the agent where the user's catalog had no match",
    )
    uploaded_file_names: List[str] = Field(
        default_factory=list,
        description="Names of files the user uploaded for this run",
    )
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    session_id: Optional[str] = None
    thinking_steps: List[ThinkingStep] = []
