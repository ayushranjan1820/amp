from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Literal, Any, Optional, Union, Annotated
from tools.tool_type import ToolType


class BaseToolConfig(BaseModel):
    tool_id: str
    name: str
    description: str
    tool_type: ToolType
    enabled: bool
    version: str

class HTTPMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class MCPTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPAuthenticationConfig(BaseModel):
    auth_type: Optional[str] = None
    token: Optional[str] = None
    headers: dict[str, str] = {}


class ApiParamLocation(StrEnum):
    PATH = "path"
    QUERY = "query"
    BODY = "body"


class ApiParamDataType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


class ApiParamConfig(BaseModel):
    name: str
    description: str
    location: ApiParamLocation
    data_type: ApiParamDataType = ApiParamDataType.STRING
    required: bool = False
    default: Any = None


class TokenType(StrEnum):
    BEARER = "Bearer"
    BASIC = "Basic"


class TokenConfig(BaseModel):
    name: str
    owner_id: str
    token_type: TokenType
    token: str


# --------------------------------------------
#        Tool Config Implementations
# --------------------------------------------
class PreConfiguredToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.PRECONFIGURED] = ToolType.PRECONFIGURED
    provider: str
    config: dict[str, Any] = {}


class ApiToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.API] = ToolType.API

    url: str
    method: HTTPMethod

    headers: dict[str, str] = Field(default_factory=dict)
    parameters: list[ApiParamConfig] = Field(default_factory=list)

    timeout_seconds: int


class PythonToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.CODE] = ToolType.CODE

    source_code: str
    function_name: str

    input_schema: dict[str, Any]


class MCPToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.MCP] = ToolType.MCP

    server_url: str
    transport: MCPTransport

    authentication: MCPAuthenticationConfig | None = None


AnyToolConfig = Annotated[
    Union[PreConfiguredToolConfig, ApiToolConfig, PythonToolConfig, MCPToolConfig],
    Field(discriminator="tool_type"),
]

ToolConfig = AnyToolConfig