from enum import StrEnum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator
from tools.tool_type import ToolType


class BaseToolConfig(BaseModel):
    tool_id: Optional[str] = None
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


class ChunkingStrategy(StrEnum):
    RECURSIVE = "recursive"
    TOKEN = "token"
    HIERARCHIAL = "hierarchial"
    SEMANTIC = "semantic"


class RetreivalStrategy(StrEnum):
    SIMILARITY = "similarity"
    MMR = "mmr"
    HYBRID = "hybrid"


class RerankModelProvider(StrEnum):
    COHERE = "cohere"
    VOYAGE_AI = "voyage_ai"


class VectorDBProvider(StrEnum):
    PINECONE = "pinecone"
    CHROMA = "chroma"
    QDRANT = "qdrant"
    MILVUS = "milvus"
    FAISS = "faiss"
    WEAVIATE = "weaviate"


class DistanceStrategy(StrEnum):
    COSINE = "cosine"
    DOTPRODUCT = "dotproduct"
    EUCLIDEAN = "euclidean"
    MANHATTAN = "manhattan"


class EmbeddingModelProvider(StrEnum):
    OPENAI = "openai"
    GOOGLE = "google"
    COHERE = "cohere"
    AZURE_OPENAI = "azure_openai"
    MISTRAL = "mistral"


class EmbeddingModelConfig(BaseModel):
    provider: EmbeddingModelProvider
    model: str
    api_key: str


class RAGToolAdvancedConfig(BaseModel):
    retrieval_strategy: RetreivalStrategy = RetreivalStrategy.SIMILARITY
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.RECURSIVE
    chunk_size: int = Field(default=1000)
    chunk_overlap: int = Field(default=200)
    distance_strategy: DistanceStrategy = DistanceStrategy.DOTPRODUCT
    vector_type: Literal["sparse", "dense"] = Field(default="dense")
    keyword_weight: float = Field(default=0.5, ge=0, le=1)
    semantic_weight: float = Field(default=0.5, ge=0, le=1)

    rerank_enabled: bool = False
    rerank_provider: Optional[RerankModelProvider] = None
    rerank_model: Optional[str] = None
    rerank_top_k: int = Field(default=5)

    @model_validator(mode="after")
    def confirm_weights(self):
        if self.retrieval_strategy == RetreivalStrategy.HYBRID:
            if self.keyword_weight + self.semantic_weight != 1.0:
                raise ValueError("Keyword and semantic weights must sum to 1")
        return self


class VectorDBConfig(BaseModel):
    vector_db_provider: VectorDBProvider
    vector_db_url: Optional[str] = Field(default=None)
    vector_db_api_key: str
    collection_name: str
    namespace: Optional[str] = None
    vector_db_tenant: str = None
    vector_dimension: int | None = None
    top_k: int = Field(default=15)
    cloud_provider: Optional[Literal["aws", "azure", "gcp"]] = None
    region: Optional[str] = None


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

    mcp_config: dict[str, Any] = Field(..., description="MCP server configuration")
    allowed_tools: list[str] = Field(
        default_factory=list, description="List of tool names to allow"
    )


class RAGToolConfig(BaseToolConfig):
    tool_type: Literal[ToolType.RAG] = ToolType.RAG

    vector_db_config: VectorDBConfig
    document_path: str
    embedding_model_config: EmbeddingModelConfig
    rag_advanced_config: RAGToolAdvancedConfig


AnyToolConfig = Annotated[
    Union[
        PreConfiguredToolConfig,
        ApiToolConfig,
        PythonToolConfig,
        MCPToolConfig,
        RAGToolConfig,
    ],
    Field(discriminator="tool_type"),
]

ToolConfig = AnyToolConfig
