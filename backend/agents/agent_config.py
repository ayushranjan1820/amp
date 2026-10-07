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
    DEPLOYED = "DEPLOYED"
    PUBLISHED = "PUBLISHED"


class ModelProvider(str, Enum):
    OPENAI = "openai"
    GOOGLE = "google_genai"
    ANTHROPIC = "anthropic"
    XAI = "xai"
    GROQ = "groq"
    AZURE_OPENAI = "azure_openai"
    AZURE_AI = "azure_ai"
    COHERE = "cohere"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    MISTRAL = "mistralai"
    HUGGINGFACE = "huggingface"
    

class ModelConfig(BaseModel):
    provider: ModelProvider
    name: str
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 0.7
    api_key: str



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
