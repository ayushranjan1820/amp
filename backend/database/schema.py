from pydantic import BaseModel, Field
from typing import List, Dict, Any, Annotated
from datetime import datetime
from agents.agent_config import Status, ModelConfig, ToolConfig, Visibility
from tools.tool_config import ToolType, PreConfiguredToolConfig, ApiToolConfig, PythonToolConfig, MCPToolConfig, TokenType
class UserProfile(BaseModel):
    name: str
    email: str
    password: str
    created_at: datetime
    updated_at: datetime


class AgentCatalog(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str] = []
    model: Optional[ModelConfig] = None
    capabilities: list[str] = []
    enabled: bool = True
    version: str
    visibility: Visibility = Field(default_factory=lambda: Visibility.PRIVATE)
    status: Status = Field(default_factory=lambda: Status.DRAFT)
    
    created_by: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_by: str
    updated_at: datetime = Field(default_factory=datetime.now)