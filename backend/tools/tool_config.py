from enum import Enum
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

class HTTPMethod(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


class ApiAuthenticationConfig(BaseModel):
    base_url: str
    method: HTTPMethod
    username: str
    password: str


class MCPTransport(str, Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


class MCPAuthenticationConfig(BaseModel):
    auth_type: Optional[str] = None
    token: Optional[str] = None
    headers: dict[str, str] = {}


# --------------------------------------------
#        Tool Config Implementations
# --------------------------------------------
class PreConfiguredToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.PRECONFIGURED] = ToolType.PRECONFIGURED
    provider: str
    config: dict[str, Any] = {}


class ApiToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.API] = ToolType.API

    base_url: str
    method: HTTPMethod
    endpoint: str

    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}

    authentication: ApiAuthenticationConfig | None = None

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