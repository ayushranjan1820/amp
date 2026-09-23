from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
from tools.tool_config import ToolConfig
import json


class Visibility(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    GROUP = "GROUP"


class Status(str, Enum):
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"
    PUBLISHED = "PUBLISHED"


class ModelProvider(str, Enum):
    OPENAI = "openai"
    GOOGLE = "google_genai"
    ANTHROPIC = "anthropic"
    GROK = "grok"
    GROQ = "groq"
    AWS_BEDROCK = "aws bedrock"
    AZURE_OPENAI = "azure openai"


class ModelConfig(BaseModel):
    _id: str
    provider: ModelProvider
    name: str
    max_tokens: Optional[int] = None



class AgentConfig(BaseModel):
    _id: str
    name: str
    description: str
    system_prompt: str
    tools: list[ToolConfig]
    model: ModelConfig
    capabilities: list[str]
    enabled: bool = True
    version: str
    visibility: Visibility = Field(default_factory=lambda: Visibility.PRIVATE)
    status: Status = Field(default_factory=lambda: Status.DRAFT)

    @classmethod
    def from_json(cls, json_str):
        data = json.loads(json_str)
        return cls(**data)
