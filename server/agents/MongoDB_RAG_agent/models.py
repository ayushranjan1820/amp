from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ThinkingStep(BaseModel):
    type: str
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[str] = None


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class MongoConnectRequest(BaseModel):
    mongodb_uri: str
    session_id: Optional[str] = None


class MongoConnectResponse(BaseModel):
    success: bool
    message: str
    databases: List[str] = []
    session_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------

class MongoIngestRequest(BaseModel):
    session_id: str
    file_content: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    raw_text: Optional[str] = None
    collection_name: Optional[str] = "rag_documents"
    access_roles: Optional[List[str]] = None


class MongoIngestResponse(BaseModel):
    success: bool
    message: str
    chunks_count: int = 0
    index_name: Optional[str] = None
    version: Optional[int] = None
    thinking_steps: List[ThinkingStep] = []


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

class MongoQueryRequest(BaseModel):
    session_id: str
    query: str
    collection_name: Optional[str] = "rag_documents"
    top_k: int = 5
    metadata_filters: Optional[Dict[str, Any]] = None
    access_roles: Optional[List[str]] = None


class MongoQueryResponse(BaseModel):
    success: bool
    query: str
    response: str
    sources: List[Dict[str, Any]] = []
    thinking_steps: List[ThinkingStep] = []
    timestamp: str = ""
    cache_hit: bool = False
    latency_ms: Optional[int] = None
    evaluation: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Chat (unified request/response)
# ---------------------------------------------------------------------------

class MongoRAGChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    mongodb_uri: Optional[str] = None
    file_content: Optional[str] = None
    file_type: Optional[str] = None
    file_name: Optional[str] = None
    raw_text: Optional[str] = None
    collection_name: Optional[str] = "rag_documents"
    top_k: int = 5
    clear_history: bool = False
    access_roles: Optional[List[str]] = None
    metadata_filters: Optional[Dict[str, Any]] = None
    user_config: Optional[Dict[str, str]] = None


class MongoRAGChatResponse(BaseModel):
    success: bool
    response: str
    query: str = ""
    thinking_steps: List[ThinkingStep] = []
    timestamp: str = ""
    phase: str = ""
    databases: List[str] = []
    chunks_count: int = 0
    sources: List[Dict[str, Any]] = []
    requires_uri: bool = False
    requires_upload: bool = False
    connected: bool = False
    ingested: bool = False
    session_id: Optional[str] = None
    cache_hit: bool = False
    latency_ms: Optional[int] = None
    evaluation: Optional[Dict[str, Any]] = None
    version: Optional[int] = None
