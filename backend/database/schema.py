from pydantic import BaseModel, Field
from typing import List, Dict, Any
from datetime import datetime
from agents.agent_config import Status, ModelConfig, ToolConfig, Visibility

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
    tools: list[ToolConfig] = []
    model: ModelConfig
    capabilities: list[str] = []
    enabled: bool = True
    version: str
    visibility: Visibility = Field(default_factory=lambda: Visibility.PRIVATE)
    status: Status = Field(default_factory=lambda: Status.DRAFT)
    
    created_by: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_by: str
    updated_at: datetime = Field(default_factory=datetime.now)