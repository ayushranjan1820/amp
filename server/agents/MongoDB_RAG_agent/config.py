"""Environment-driven settings for the MongoDB Atlas KB Agent.

All values are read from environment variables at startup.
Covers: embedding, chunking, hybrid search, reranking, query transformation,
caching, sessions, guardrails, document lifecycle, evaluation, and Langfuse.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Env helpers
# ---------------------------------------------------------------------------

def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except (ValueError, AttributeError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except (ValueError, AttributeError):
        return default


def _str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _list(name: str, default: str = "") -> List[str]:
    raw = os.getenv(name, default).strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MongoRAGSettings:

    # ── MongoDB ──────────────────────────────────────────────────────────────
    default_db_name: str = "rag_knowledge_base"
    default_collection: str = "rag_documents"
    connect_timeout_ms: int = 10_000
    server_selection_timeout_ms: int = 10_000

    # ── Embedding ────────────────────────────────────────────────────────────
    # "bge-small"  → BAAI/bge-small-en-v1.5  (384-dim, fast)
    # "bge-large"  → BAAI/bge-large-en-v1.5  (1024-dim, higher quality)
    # "pwc_genai"  → PWC GenAI /embeddings endpoint (default model vertex_ai.text-embedding-005)
    # "openai"     → text-embedding-3-small   (1536-dim, requires OPENAI_API_KEY)
    embedding_provider: str = "bge-large"
    pwc_embedding_model: str = "vertex_ai.text-embedding-005"
    embedding_dimension_override: int = 0
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Chunking ─────────────────────────────────────────────────────────────
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    enable_parent_child: bool = True
    parent_chunk_size_tokens: int = 2048
    # For CSV: number of rows per chunk
    csv_rows_per_chunk: int = 20

    # ── Vector search ────────────────────────────────────────────────────────
    vector_index_name: str = "vector_index"
    num_candidates_multiplier: int = 20   # numCandidates = max(150, top_k * multiplier)
    num_candidates_floor: int = 150
    index_ready_poll_interval_sec: float = 3.0
    index_ready_timeout_sec: float = 300.0

    # ── Hybrid search ────────────────────────────────────────────────────────
    hybrid_enabled: bool = False           # requires Atlas full-text index
    fulltext_index_name: str = "fulltext_index"
    hybrid_vector_weight: float = 0.7
    hybrid_text_weight: float = 0.3
    rrf_k: int = 60

    # ── Query transformation ─────────────────────────────────────────────────
    query_transform_enabled: bool = True
    query_transform_strategy: str = "multi_query"  # "multi_query" | "hyde" | "decompose" | "none"
    query_expansion_count: int = 3

    # ── Reranking ────────────────────────────────────────────────────────────
    reranker_enabled: bool = True
    reranker_provider: str = "llm"         # "cohere" | "cross-encoder" | "llm"
    reranker_top_k: int = 5
    cohere_api_key: str = ""
    cohere_model: str = "rerank-v3.5"
    cross_encoder_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # ── Semantic cache ───────────────────────────────────────────────────────
    cache_enabled: bool = True
    cache_backend: str = "memory"          # "redis" | "memory"
    cache_ttl_seconds: int = 3600
    cache_similarity_threshold: float = 0.92
    cache_max_entries: int = 1000
    redis_url: str = "redis://localhost:6379/0"

    # ── Session store ────────────────────────────────────────────────────────
    session_backend: str = "memory"        # "redis" | "memory"
    session_max_turns: int = 20
    session_ttl_seconds: int = 86400

    # ── Guardrails ───────────────────────────────────────────────────────────
    guardrails_enabled: bool = True
    max_query_length: int = 10000
    max_response_length: int = 50000
    blocked_input_patterns: List[str] = field(default_factory=list)
    pii_detection_enabled: bool = True

    # ── Document lifecycle ───────────────────────────────────────────────────
    enable_document_versioning: bool = True
    enable_soft_delete: bool = True
    document_ttl_days: int = 0             # 0 = never expires

    # ── RBAC ─────────────────────────────────────────────────────────────────
    rbac_enabled: bool = False

    # ── Evaluation ───────────────────────────────────────────────────────────
    evaluation_enabled: bool = False       # LLM-as-judge; expensive
    evaluation_sample_rate: float = 0.1

    # ── OCR ──────────────────────────────────────────────────────────────────
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    scanned_page_char_threshold: int = 100  # chars/page below which OCR is triggered

    # ── Langfuse ─────────────────────────────────────────────────────────────
    langfuse_enabled: bool = False

    @classmethod
    def from_environ(cls) -> MongoRAGSettings:
        return cls(
            default_db_name=_str("MONGO_RAG_DB_NAME", "rag_knowledge_base"),
            default_collection=_str("MONGO_RAG_COLLECTION", "rag_documents"),
            connect_timeout_ms=_int("MONGO_CONNECT_TIMEOUT_MS", 10_000),
            server_selection_timeout_ms=_int("MONGO_SERVER_SELECTION_TIMEOUT_MS", 10_000),

            embedding_provider=_str("MONGO_RAG_EMBEDDING_PROVIDER", "bge-large"),
            pwc_embedding_model=_str("MONGO_RAG_PWC_EMBEDDING_MODEL", "vertex_ai.text-embedding-005"),
            embedding_dimension_override=_int("MONGO_RAG_EMBEDDING_DIM", 0),
            openai_api_key=_str("OPENAI_API_KEY"),
            openai_embedding_model=_str("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),

            chunk_size_tokens=_int("MONGO_RAG_CHUNK_SIZE_TOKENS", 512),
            chunk_overlap_tokens=_int("MONGO_RAG_CHUNK_OVERLAP_TOKENS", 64),
            enable_parent_child=_bool("MONGO_RAG_PARENT_CHILD", True),
            parent_chunk_size_tokens=_int("MONGO_RAG_PARENT_CHUNK_TOKENS", 2048),
            csv_rows_per_chunk=_int("MONGO_RAG_CSV_ROWS_PER_CHUNK", 20),

            vector_index_name=_str("MONGO_RAG_VECTOR_INDEX", "vector_index"),
            num_candidates_multiplier=_int("MONGO_RAG_NUM_CANDIDATES_MULT", 20),
            num_candidates_floor=_int("MONGO_RAG_NUM_CANDIDATES_FLOOR", 150),
            index_ready_poll_interval_sec=_float("MONGO_RAG_INDEX_POLL_SEC", 3.0),
            index_ready_timeout_sec=_float("MONGO_RAG_INDEX_TIMEOUT_SEC", 300.0),

            hybrid_enabled=_bool("MONGO_RAG_HYBRID", False),
            fulltext_index_name=_str("MONGO_RAG_FULLTEXT_INDEX", "fulltext_index"),
            hybrid_vector_weight=_float("MONGO_RAG_HYBRID_VECTOR_WEIGHT", 0.7),
            hybrid_text_weight=_float("MONGO_RAG_HYBRID_TEXT_WEIGHT", 0.3),
            rrf_k=_int("MONGO_RAG_RRF_K", 60),

            query_transform_enabled=_bool("MONGO_RAG_QUERY_TRANSFORM", True),
            query_transform_strategy=_str("MONGO_RAG_QUERY_STRATEGY", "multi_query"),
            query_expansion_count=_int("MONGO_RAG_QUERY_EXPANSION_COUNT", 3),

            reranker_enabled=_bool("MONGO_RAG_RERANKER_ENABLED", True),
            reranker_provider=_str("MONGO_RAG_RERANKER_PROVIDER", "llm"),
            reranker_top_k=_int("MONGO_RAG_RERANKER_TOP_K", 5),
            cohere_api_key=_str("COHERE_API_KEY"),
            cohere_model=_str("MONGO_RAG_COHERE_MODEL", "rerank-v3.5"),
            cross_encoder_model=_str("MONGO_RAG_CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"),

            cache_enabled=_bool("MONGO_RAG_CACHE_ENABLED", True),
            cache_backend=_str("MONGO_RAG_CACHE_BACKEND", "memory"),
            cache_ttl_seconds=_int("MONGO_RAG_CACHE_TTL_SECONDS", 3600),
            cache_similarity_threshold=_float("MONGO_RAG_CACHE_SIM_THRESHOLD", 0.92),
            cache_max_entries=_int("MONGO_RAG_CACHE_MAX_ENTRIES", 1000),
            redis_url=_str("REDIS_URL", "redis://localhost:6379/0"),

            session_backend=_str("MONGO_RAG_SESSION_BACKEND", "memory"),
            session_max_turns=_int("MONGO_RAG_SESSION_MAX_TURNS", 20),
            session_ttl_seconds=_int("MONGO_RAG_SESSION_TTL_SECONDS", 86400),

            guardrails_enabled=_bool("MONGO_RAG_GUARDRAILS_ENABLED", True),
            max_query_length=_int("MONGO_RAG_MAX_QUERY_LENGTH", 10000),
            max_response_length=_int("MONGO_RAG_MAX_RESPONSE_LENGTH", 50000),
            blocked_input_patterns=_list("MONGO_RAG_BLOCKED_PATTERNS"),
            pii_detection_enabled=_bool("MONGO_RAG_PII_DETECTION", True),

            enable_document_versioning=_bool("MONGO_RAG_DOC_VERSIONING", True),
            enable_soft_delete=_bool("MONGO_RAG_SOFT_DELETE", True),
            document_ttl_days=_int("MONGO_RAG_DOC_TTL_DAYS", 0),

            rbac_enabled=_bool("MONGO_RAG_RBAC_ENABLED", False),

            evaluation_enabled=_bool("MONGO_RAG_EVALUATION_ENABLED", False),
            evaluation_sample_rate=_float("MONGO_RAG_EVAL_SAMPLE_RATE", 0.1),

            ocr_enabled=_bool("MONGO_RAG_OCR_ENABLED", True),
            ocr_language=_str("MONGO_RAG_OCR_LANGUAGE", "eng"),
            scanned_page_char_threshold=_int("MONGO_RAG_SCANNED_PAGE_THRESHOLD", 100),

            langfuse_enabled=_bool("LANGFUSE_ENABLED", False),
        )
