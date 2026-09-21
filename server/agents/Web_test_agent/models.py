"""Pydantic models for Web Test Agent request / response schemas."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class WebTestRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None


class ThinkingStep(BaseModel):
    """A single reasoning / tool-use step surfaced to the caller."""
    type: str = Field(description="Step type: thinking | tool_call | tool_result | error")
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[Any] = None


class ReportMetadata(BaseModel):
    """Metadata block attached to every generated test report."""
    application_url: str = ""
    page_title: str = ""
    report_date: str = ""
    prepared_by: str = "Web Test Agent (AI-Powered QA)"
    total_features: int = 0
    total_test_cases: int = 0
    sections_generated: List[str] = []
    sections_failed: List[str] = []


class WebTestResponse(BaseModel):
    success: bool
    query: str
    response: str
    thinking_steps: List[Dict[str, Any]] = []
    metadata: Optional[ReportMetadata] = None
    timestamp: str
    session_id: Optional[str] = None


class WebTestPlaywrightRunRequest(BaseModel):
    """Run generated Playwright TypeScript from the Web Test report in a server subprocess."""

    spec_source: str = Field(..., description="Full contents of a .spec.ts file")
    headed: bool = Field(default=True, description="If true, run with a visible browser window on the server")
    timeout_sec: int = Field(default=600, ge=60, le=3600)


class WebTestPlaywrightRunResponse(BaseModel):
    success: bool
    exit_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    message: Optional[str] = Field(
        default=None,
        description="Validation or environment error when success is false",
    )
