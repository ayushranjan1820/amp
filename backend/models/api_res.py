from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime
from agents.agent_config import ToolConfig, ModelConfig, Visibility, Status
from tools.tool_config import TokenType


class ServerResponseWrapper(BaseModel):
    data: Optional[Any] = None
    message: Optional[str] = None
    status_code: int
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class RegisterUserRes(BaseModel):
    user_id: str
    user_name: str
    user_email: str


class LoginUserRes(BaseModel):
    name: str
    email: str
    token: str


class AgentRes(BaseModel):
    agent_id: str
    name: str
    description: str
    system_prompt: str
    tools: list[str] = []
    model: ModelConfig
    capabilities: list[str] = []
    enabled: bool = True
    version: str
    visibility: Visibility = Field(default_factory=lambda: Visibility.PRIVATE)
    status: Status = Field(default_factory=lambda: Status.DRAFT)


class TokenRes(BaseModel):
    token_id: str
    name: str
    owner_id: str
    token_type: TokenType
