from enum import StrEnum
from pydantic import BaseModel, Field
from typing import Literal, Any, Optional, Union, Annotated
from tools.tool_type import ToolType


class BaseToolConfig(BaseModel):
    _id: str
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
    query_params: dict[str, str] = Field(default_factory=dict)
    parameters: list[ApiParamConfig] = Field(default_factory=list)

    timeout_seconds: int

    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None


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