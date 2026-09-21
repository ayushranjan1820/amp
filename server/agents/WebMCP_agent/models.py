from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class WebMcpThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None


class WebMcpChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    clear_history: bool = False
    user_config: Optional[Dict[str, str]] = None
    bridge_base_url: str = Field(
        ...,
        description="Local bridge base URL, e.g. http://127.0.0.1:3847",
    )
    bridge_token: str = Field(
        ...,
        description="Bearer token shared with the Chrome extension and bridge server.",
    )

    @field_validator("bridge_base_url", "bridge_token")
    @classmethod
    def _strip_nonempty_bridge(cls, v: str) -> str:
        if v is None:
            raise ValueError("bridge_base_url and bridge_token are required")
        s = str(v).strip()
        if not s:
            raise ValueError("bridge_base_url and bridge_token are required")
        return s
    allowed_hosts: Optional[List[str]] = Field(
        default=None,
        description="When set (non-empty), the active tab hostname must match one entry (case-insensitive). Supports *.example.com wildcards.",
    )
    require_host_allowlist: bool = Field(
        default=False,
        description="When true, allowed_hosts must be non-empty or the request is rejected.",
    )
    max_steps: int = Field(default=20, ge=1, le=100, description="Maximum LLM tool-loop iterations per message.")
    bridge_timeout_sec: float = Field(default=60.0, ge=5.0, le=600.0)
    wall_time_sec: float = Field(default=300.0, ge=30.0, le=3600.0, description="Maximum wall time for the whole run.")


class WebMcpChatResponse(BaseModel):
    success: bool
    response: str
    query: str = ""
    thinking_steps: List[WebMcpThinkingStep] = []
    timestamp: str = ""
    session_id: Optional[str] = None
    tool_calls: int = 0
    webmcp_agent_version: str = ""
    bridge_version: Optional[str] = None
    session_url: Optional[str] = None
