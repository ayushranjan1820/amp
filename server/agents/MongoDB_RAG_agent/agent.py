"""MongoDB Atlas KB Agent — Enterprise orchestration.

Full pipeline (query path):
  Input → Guardrails → Sanitise → Session Load
  → Semantic Cache Lookup
  → Query Transform (multi_query / HyDE / decompose)
  → Parallel Multi-Query Retrieval (ThreadPoolExecutor)
  → Deduplication + RRF merge across query variants
  → Parent Chunk Expansion
  → Reranking (Cohere / cross-encoder / LLM)
  → Context Assembly
  → LLM Generation
  → Output Guardrails
  → RAGAS Evaluation (sampled)
  → Cache Store
  → Session Append
  → Response

Ingestion pipeline:
  File/Text → Text Extraction (native handlers + OCR)
  → Token-Aware Chunking (parent-child)
  → Embeddings (bge-large / OpenAI)
  → Upsert with chunk-hash deduplication
  → Document versioning (soft-delete old chunks)
  → Index readiness polling
  → Cache invalidation

All subsystems wired through MongoRAGSettings (from_environ()).
Langfuse tracing emitted via the shared langfuse_tracer module.
"""

from __future__ import annotations

import os
import re
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.local_llm import get_llm_provider, is_llm_provider_configured, describe_missing_llm_credentials

from .ai_service import ai_service
from .cache import SemanticCache
from .config import MongoRAGSettings
from .evaluator import evaluate_rag_response
from .guardrails import sanitize_query, validate_input, validate_output
from .models import ThinkingStep
from .query_transform import transform_query
from .reranker import rerank
from .session_store import create_session_store, hash_uri
from .tools.embedding_service import (
    get_embedding_dimension,
    get_embeddings,
    get_single_embedding,
)
from .tools.mongo_service import mongo_service
from .utils.chunker import chunk_document
from .utils.text_extractor import extract_text_from_file


# ---------------------------------------------------------------------------
# Langfuse helper (no-op when disabled)
# ---------------------------------------------------------------------------

def _looks_like_connection_status_question(query: str) -> bool:
    t = (query or "").strip().lower()
    if not t:
        return False
    needles = (
        "mongodb connected",
        "mongo db connected",
        "mongo connected",
        "database connected",
        "atlas connected",
        "still connected",
        "connection status",
        "am i connected",
        "are we connected",
        "is the database connected",
        "connected to mongo",
    )
    return any(n in t for n in needles)


def _config_errors() -> List[str]:
    """Preflight credential validation — matches SQL DB Agent pattern."""
    if is_llm_provider_configured():
        return []
    return [describe_missing_llm_credentials()]


def _lf_span(name: str, input_: Any = None, output: Any = None, metadata: Any = None) -> None:
    try:
        from langfuse_tracer import trace_llm_call  # shared tracer
        # The shared tracer is LLM-call oriented; for span events we just log.
        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class MongoDBRAGAgent:

    def __init__(self):
        self.ai_service = ai_service
        self._settings: Optional[MongoRAGSettings] = None
        self._session_store = None
        self._cache: Optional[SemanticCache] = None
        print(
            "[MongoDB RAG] Singleton loaded in this server process (one-time; unrelated to LLM/Ollama auth)."
        )

    def _connection_status_response(
        self,
        query: str,
        session_id: str,
        session: Dict[str, Any],
        col_name: str,
    ) -> Optional[str]:
        """Answer meta-questions about Atlas connectivity without running RAG + LLM."""
        if not _looks_like_connection_status_question(query):
            return None
        cfg = self._cfg()
        db_name = session.get("db_name", cfg.default_db_name)
        if not mongo_service.is_connected(session_id):
            return (
                "**No** — this session is **not** connected to MongoDB Atlas.\n\n"
                "Set **MONGODB_URI** in the **Config** tab (save), or include your URI when connecting."
            )
        try:
            stats = mongo_service.get_collection_stats(session_id, col_name, db_name)
            n_chunks = int(stats.get("total_chunks", 0) or 0)
        except Exception:
            n_chunks = 0
        ingested = bool(session.get("ingested")) or n_chunks > 0
        if ingested:
            return (
                "**Yes** — this session **is connected** to MongoDB Atlas"
                f" (`{db_name}` / `{col_name}`). Ingested chunks in this collection: **{n_chunks}**.\n\n"
                "You can ask questions about your documents."
            )
        return (
            "**Yes** — this session **is connected** to MongoDB Atlas.\n\n"
            "No documents are ingested yet. Upload a file or paste text to build your knowledge base."
        )

    # ── Settings / subsystems (lazy, singleton per instance) ─────────────

    def _cfg(self) -> MongoRAGSettings:
        if self._settings is None:
            self._settings = MongoRAGSettings.from_environ()
        return self._settings

    def _sessions(self):
        if self._session_store is None:
            self._session_store = create_session_store(self._cfg())
        return self._session_store

    def _cache_store(self) -> SemanticCache:
        if self._cache is None:
            self._cache = SemanticCache(self._cfg())
        return self._cache

    # ── Connection ────────────────────────────────────────────────────────

    def connect(self, session_id: str, mongodb_uri: str) -> Dict[str, Any]:
        thinking: List[ThinkingStep] = []
        thinking.append(ThinkingStep(type="tool", content="Validating MongoDB URI…", tool_name="validate_uri"))

        if not mongodb_uri or not mongodb_uri.startswith("mongodb"):
            return {
                "success": False,
                "message": "Invalid URI. Must start with 'mongodb://' or 'mongodb+srv://'.",
                "databases": [], "thinking_steps": thinking,
            }

        thinking.append(ThinkingStep(type="tool", content="Connecting to MongoDB Atlas…", tool_name="mongo_connect"))
        cfg = self._cfg()
        success, message, databases = mongo_service.connect(session_id, mongodb_uri, cfg)

        if success:
            uri_hash = hash_uri(mongodb_uri)
            self._sessions().set(session_id, {
                "connected": True,
                "uri_hash": uri_hash,
                "mongodb_uri": mongodb_uri,   # memory-only; not persisted to Redis
                "db_name": cfg.default_db_name,
                "collection_name": cfg.default_collection,
                "files_ingested": [],
            })
            thinking.append(ThinkingStep(type="result", content=f"Connected. Found {len(databases)} databases."))
        else:
            thinking.append(ThinkingStep(type="observation", content=f"Connection failed: {message}"))

        return {"success": success, "message": message, "databases": databases, "thinking_steps": thinking}

    # ── Ingestion ─────────────────────────────────────────────────────────

    def ingest(
        self,
        session_id: str,
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        raw_text: Optional[str] = None,
        collection_name: Optional[str] = None,
        access_roles: Optional[List[str]] = None,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> Dict[str, Any]:
        thinking: List[ThinkingStep] = []
        cfg = self._cfg()
        session = self._sessions().get(session_id) or {}
        db_name = session.get("db_name", cfg.default_db_name)
        col_name = collection_name or session.get("collection_name", cfg.default_collection)

        if not mongo_service.is_connected(session_id):
            return {"success": False, "message": "Not connected. Provide a MongoDB URI.", "chunks_count": 0, "thinking_steps": thinking}

        # ── Text extraction ───────────────────────────────────────────────
        thinking.append(ThinkingStep(type="tool", content="Extracting text from document…", tool_name="text_extractor"))
        try:
            if file_content and file_type:
                text = extract_text_from_file(
                    file_content, file_type, file_name or "",
                    ocr_enabled=cfg.ocr_enabled,
                    ocr_language=cfg.ocr_language,
                    scanned_page_threshold=cfg.scanned_page_char_threshold,
                )
                source_name = file_name or f"uploaded_file.{file_type}"
            elif raw_text:
                text = raw_text
                source_name = "pasted_text"
            else:
                return {"success": False, "message": "No content provided.", "chunks_count": 0, "thinking_steps": thinking}

            if not text.strip():
                return {"success": False, "message": "Could not extract any text from the content.", "chunks_count": 0, "thinking_steps": thinking}
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "message": f"Extraction error: {e}", "chunks_count": 0, "thinking_steps": thinking}

        thinking.append(ThinkingStep(type="observation", content=f"Extracted {len(text):,} characters from '{source_name}'"))

        # ── Document version ──────────────────────────────────────────────
        version = 1
        if cfg.enable_document_versioning:
            version = mongo_service.get_document_version(session_id, source_name, col_name, db_name)

        # ── Chunking ──────────────────────────────────────────────────────
        ext = (file_type or "").lower().strip(".")
        is_csv = ext in ("csv", "tsv")
        strategy = "csv" if is_csv else "recursive"

        thinking.append(ThinkingStep(
            type="tool",
            content=f"Chunking with '{strategy}' strategy (tokens={cfg.chunk_size_tokens}, parent-child={cfg.enable_parent_child})…",
            tool_name="chunker",
        ))

        extra_meta = {
            "source_doc_id": str(uuid.uuid4()),
            "version": version,
            "file_type": ext,
        }
        chunks = chunk_document(
            text,
            strategy=strategy,
            chunk_size_tokens=cfg.chunk_size_tokens,
            chunk_overlap_tokens=cfg.chunk_overlap_tokens,
            enable_parent_child=cfg.enable_parent_child,
            parent_chunk_size_tokens=cfg.parent_chunk_size_tokens,
            csv_rows_per_chunk=cfg.csv_rows_per_chunk,
            source_label=source_name,
            extra_metadata=extra_meta,
            is_csv=is_csv,
        )

        if not chunks:
            return {"success": False, "message": "No chunks produced.", "chunks_count": 0, "thinking_steps": thinking}

        child_count = sum(1 for c in chunks if c.get("metadata", {}).get("chunk_type") == "child")
        parent_count = len(chunks) - child_count
        thinking.append(ThinkingStep(type="observation", content=f"Created {child_count} child + {parent_count} parent chunks"))

        # ── Embeddings (child chunks only) ────────────────────────────────
        thinking.append(ThinkingStep(
            type="tool",
            content=f"Generating embeddings ({cfg.embedding_provider}, dim={get_embedding_dimension(cfg)})…",
            tool_name="embedding_service",
        ))

        child_chunks = [c for c in chunks if c.get("metadata", {}).get("chunk_type") != "parent"]
        parent_chunks = [c for c in chunks if c.get("metadata", {}).get("chunk_type") == "parent"]

        try:
            child_texts = [c["text"] for c in child_chunks]
            child_embeddings = get_embeddings(child_texts, cfg)
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "message": f"Embedding failed: {e}", "chunks_count": 0, "thinking_steps": thinking}

        # Parent chunks stored with zero-vector (retrieved by ID, not similarity)
        parent_embeddings = [[0.0] * get_embedding_dimension(cfg)] * len(parent_chunks)

        all_chunks = child_chunks + parent_chunks
        all_embeddings = child_embeddings + parent_embeddings

        thinking.append(ThinkingStep(type="observation", content=f"Generated {len(child_embeddings)} embeddings"))

        # ── Store ─────────────────────────────────────────────────────────
        thinking.append(ThinkingStep(type="tool", content="Upserting chunks into MongoDB Atlas…", tool_name="mongo_upsert"))
        try:
            stored = mongo_service.store_chunks(
                session_id=session_id,
                chunks=all_chunks,
                embeddings=all_embeddings,
                collection_name=col_name,
                file_name=source_name,
                db_name=db_name,
                settings=cfg,
                access_roles=access_roles,
                version=version,
            )
        except Exception as e:
            traceback.print_exc()
            return {"success": False, "message": f"Storage failed: {e}", "chunks_count": 0, "thinking_steps": thinking}

        thinking.append(ThinkingStep(type="observation", content=f"Upserted {stored} documents (v{version}) into '{col_name}'"))

        # ── Index ─────────────────────────────────────────────────────────
        thinking.append(ThinkingStep(type="tool", content="Ensuring vector search index (polling for READY)…", tool_name="vector_index"))
        if progress_callback:
            progress_callback("Waiting for Atlas vector index to become ready…")

        index_result = mongo_service.ensure_vector_index(
            session_id=session_id,
            collection_name=col_name,
            db_name=db_name,
            embedding_dim=get_embedding_dimension(cfg),
            settings=cfg,
        )
        thinking.append(ThinkingStep(type="observation", content=f"Index status: {index_result}"))

        # ── Cache invalidation ────────────────────────────────────────────
        if cfg.cache_enabled:
            self._cache_store().invalidate(col_name)

        # ── Session update ────────────────────────────────────────────────
        sess = self._sessions().get(session_id) or {}
        files = sess.get("files_ingested", [])
        if source_name not in files:
            files.append(source_name)
        self._sessions().set(session_id, {"ingested": True, "collection_name": col_name, "files_ingested": files})

        stats = mongo_service.get_collection_stats(session_id, col_name, db_name)

        return {
            "success": True,
            "message": (
                f"Ingested **'{source_name}'** (v{version}).\n\n"
                f"- Chunks stored: **{stored}** ({child_count} child + {parent_count} parent)\n"
                f"- Embedding model: **{cfg.embedding_provider}** ({get_embedding_dimension(cfg)}-dim)\n"
                f"- Total in collection: **{stats['total_chunks']}** chunks\n"
                f"- Vector index: **{index_result}**\n"
                f"- Files indexed: {', '.join(stats['files'])}"
            ),
            "chunks_count": stored,
            "index_name": index_result,
            "version": version,
            "thinking_steps": thinking,
        }

    # ── Query ─────────────────────────────────────────────────────────────

    def query(
        self,
        session_id: str,
        user_query: str,
        collection_name: Optional[str] = None,
        top_k: int = 5,
        metadata_filters: Optional[Dict[str, Any]] = None,
        access_roles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        thinking: List[ThinkingStep] = []
        cfg = self._cfg()
        session = self._sessions().get(session_id) or {}
        db_name = session.get("db_name", cfg.default_db_name)
        col_name = collection_name or session.get("collection_name", cfg.default_collection)
        t_start = time.monotonic()

        if not mongo_service.is_connected(session_id):
            return {"success": False, "query": user_query, "response": "Not connected. Provide a MongoDB URI.", "sources": [], "thinking_steps": thinking}

        # ── Input guardrails ──────────────────────────────────────────────
        validation = validate_input(user_query, cfg)
        if not validation.is_valid:
            return {"success": False, "query": user_query, "response": validation.message, "sources": [], "thinking_steps": thinking}

        clean_query = sanitize_query(user_query)
        query_cfg = cfg

        # ── Query embedding ───────────────────────────────────────────────
        thinking.append(ThinkingStep(type="tool", content="Generating query embedding…", tool_name="embedding"))
        try:
            q_embedding = get_single_embedding(clean_query, query_cfg)
        except Exception as e:
            return {"success": False, "query": user_query, "response": f"Embedding error: {e}", "sources": [], "thinking_steps": thinking}

        # Keep query embedding dimension aligned with the active Atlas vector index.
        try:
            index_dim = mongo_service.get_vector_index_dimension(
                session_id=session_id,
                collection_name=col_name,
                db_name=db_name,
                settings=cfg,
            )
        except Exception:
            index_dim = None

        if index_dim and len(q_embedding) != index_dim:
            thinking.append(
                ThinkingStep(
                    type="observation",
                    content=(
                        f"Detected vector dimension mismatch (query={len(q_embedding)}d, index={index_dim}d). "
                        "Trying a dimension-compatible embedding provider..."
                    ),
                )
            )
            try:
                query_cfg = replace(cfg, embedding_dimension_override=index_dim)
                q_embedding = get_single_embedding(clean_query, query_cfg)
                if len(q_embedding) != index_dim:
                    raise ValueError(f"provider returned {len(q_embedding)}d, expected {index_dim}d")
                thinking.append(
                    ThinkingStep(
                        type="observation",
                        content=f"Using {index_dim}d query embeddings to match Atlas index.",
                    )
                )
            except Exception as e:
                return {
                    "success": False,
                    "query": user_query,
                    "response": (
                        f"Embedding/index dimension mismatch: index is {index_dim}d but current embedding provider "
                        f"produced {len(q_embedding)}d and no compatible fallback succeeded ({e}). "
                        "Fix by either (1) restoring a provider that can output the index dimension, or "
                        "(2) rebuilding the collection/index after re-ingesting documents with a single provider."
                    ),
                    "sources": [],
                    "thinking_steps": thinking,
                }

        # ── Semantic cache lookup ─────────────────────────────────────────
        if cfg.cache_enabled:
            cached = self._cache_store().lookup(clean_query, col_name, q_embedding)
            if cached:
                thinking.append(ThinkingStep(type="observation", content=f"Cache hit (similarity={cached.get('cache_similarity', 1.0):.3f})"))
                cached["thinking_steps"] = thinking
                cached["cache_hit"] = True
                return cached

        # ── Query transformation ──────────────────────────────────────────
        queries = [clean_query]
        if cfg.query_transform_enabled:
            thinking.append(ThinkingStep(
                type="tool",
                content=f"Transforming query ({cfg.query_transform_strategy}, n={cfg.query_expansion_count})…",
                tool_name="query_transform",
            ))
            queries = transform_query(clean_query, cfg, self.ai_service)
            thinking.append(ThinkingStep(type="observation", content=f"Expanded to {len(queries)} query variants"))

        # ── Parallel multi-query retrieval ────────────────────────────────
        thinking.append(ThinkingStep(
            type="tool",
            content=f"Searching Atlas for top-{top_k} chunks ({len(queries)} queries in parallel)…",
            tool_name="vector_search",
        ))

        all_results: List[Dict[str, Any]] = []
        fetch_per_query = max(top_k * 2, 10)

        def _search_one(q: str) -> List[Dict[str, Any]]:
            try:
                emb = get_single_embedding(q, query_cfg)
                if cfg.hybrid_enabled:
                    return mongo_service.hybrid_search(
                        session_id, q, emb, col_name, db_name,
                        top_k=fetch_per_query, settings=query_cfg,
                        metadata_filters=metadata_filters, access_roles=access_roles,
                    )
                else:
                    return mongo_service.vector_search(
                        session_id, emb, col_name, db_name,
                        top_k=fetch_per_query, settings=query_cfg,
                        metadata_filters=metadata_filters, access_roles=access_roles,
                    )
            except Exception as e:
                print(f"[Agent] search failed for variant '{q[:60]}': {e}")
                return []

        with ThreadPoolExecutor(max_workers=min(len(queries), 4)) as pool:
            futures = {pool.submit(_search_one, q): q for q in queries}
            for fut in as_completed(futures):
                all_results.extend(fut.result())

        if not all_results:
            return {
                "success": True, "query": user_query,
                "response": "No relevant documents found. Please ingest documents first.",
                "sources": [], "thinking_steps": thinking,
            }

        # ── Deduplicate across query variants (keep best score per chunk) ─
        seen: Dict[str, Dict[str, Any]] = {}
        for doc in all_results:
            key = f"{doc.get('source_doc_id', '')}_{doc.get('chunk_id', '')}"
            existing = seen.get(key)
            if existing is None or (doc.get("score") or 0) > (existing.get("score") or 0):
                seen[key] = doc
        deduped = sorted(seen.values(), key=lambda d: d.get("score") or 0, reverse=True)[:top_k * 2]

        thinking.append(ThinkingStep(type="observation", content=f"Retrieved {len(deduped)} unique chunks (best score: {deduped[0].get('score', 0):.4f})"))

        # ── Parent expansion ──────────────────────────────────────────────
        parent_ids = list({d.get("parent_id") for d in deduped if d.get("parent_id")})
        expanded_texts: Dict[str, str] = {}
        if parent_ids and cfg.enable_parent_child:
            thinking.append(ThinkingStep(type="tool", content=f"Expanding {len(parent_ids)} parent chunks for richer context…", tool_name="parent_expand"))
            expanded_texts = mongo_service.fetch_parent_chunks(session_id, parent_ids, col_name, db_name)

        # ── Reranking ─────────────────────────────────────────────────────
        if cfg.reranker_enabled and len(deduped) > 1:
            thinking.append(ThinkingStep(
                type="tool",
                content=f"Reranking with '{cfg.reranker_provider}'…",
                tool_name="reranker",
            ))
            deduped = rerank(clean_query, deduped, cfg, top_k=top_k, ai_service=self.ai_service)
        else:
            deduped = deduped[:top_k]

        thinking.append(ThinkingStep(type="observation", content=f"Final {len(deduped)} chunks after reranking"))

        # ── Context assembly ──────────────────────────────────────────────
        context_parts: List[str] = []
        for i, doc in enumerate(deduped):
            src = doc.get("file_name", "unknown")
            sec = f" [{doc['section']}]" if doc.get("section") else ""
            score = doc.get("score") or doc.get("rerank_score") or 0
            pid = doc.get("parent_id")
            # Use parent text for richer context if available
            body = expanded_texts.get(pid, doc["text"]) if pid and expanded_texts.get(pid) else doc["text"]
            context_parts.append(f"--- Source {i+1}: {src}{sec} (score: {score:.4f}) ---\n{body}")

        context = "\n\n".join(context_parts)

        # ── Conversation history ──────────────────────────────────────────
        history = self._sessions().get_history(session_id)
        conv_snippet = "\n".join(
            f"{m['role'].capitalize()}: {m['content'][:400]}"
            for m in history[-6:]
        )

        # ── LLM generation ────────────────────────────────────────────────
        thinking.append(ThinkingStep(type="tool", content="Generating answer with retrieved context…", tool_name="llm_generate"))
        prompt = self._build_prompt(clean_query, context, conv_snippet)

        try:
            response_text = self.ai_service.call_genai(prompt, temperature=0.2, max_tokens=4096)
        except Exception as e:
            response_text = self._fallback_response(user_query, deduped)

        # ── Output guardrails ─────────────────────────────────────────────
        out_check = validate_output(response_text, cfg)
        if not out_check.is_valid:
            response_text = "Response could not be returned due to content policy limits."
        if out_check.pii_detected:
            thinking.append(ThinkingStep(type="observation", content=f"PII detected in output: {out_check.pii_detected}"))

        if not (response_text or "").strip():
            response_text = (
                "The model returned an empty reply. Check **LLM_PROVIDER** and credentials in **Config**, "
                "or ask a **connection status** question (e.g. “Is MongoDB connected?”) for a direct answer."
            )

        # ── Evaluation (sampled) ──────────────────────────────────────────
        chunk_texts_for_eval = [d.get("text", "") for d in deduped]
        eval_results = evaluate_rag_response(clean_query, response_text, context, chunk_texts_for_eval, cfg, self.ai_service)
        if eval_results:
            thinking.append(ThinkingStep(
                type="observation",
                content=f"RAGAS eval — faithfulness: {eval_results.get('faithfulness', '-')}, relevancy: {eval_results.get('answer_relevancy', '-')}, overall: {eval_results.get('overall_score', '-')}",
            ))

        # ── Latency ───────────────────────────────────────────────────────
        latency_ms = round((time.monotonic() - t_start) * 1000)
        thinking.append(ThinkingStep(type="result", content=f"Pipeline complete in {latency_ms}ms"))

        # ── Session update ────────────────────────────────────────────────
        self._sessions().append_turn(session_id, "user", user_query)
        self._sessions().append_turn(session_id, "assistant", response_text)

        _prev_len = 600
        sources = [
            {
                "file_name": d.get("file_name", ""),
                "section": d.get("section", ""),
                "score": round(d.get("score") or d.get("rerank_score") or 0, 4),
                "preview": d["text"][:_prev_len] + ("…" if len(d["text"]) > _prev_len else ""),
            }
            for d in deduped
        ]

        result = {
            "success": True,
            "query": user_query,
            "response": response_text,
            "sources": sources,
            "thinking_steps": thinking,
            "latency_ms": latency_ms,
            "cache_hit": False,
        }
        if eval_results:
            result["evaluation"] = eval_results

        # ── Cache store ───────────────────────────────────────────────────
        if cfg.cache_enabled:
            self._cache_store().store(clean_query, col_name, result, q_embedding)

        # ── Langfuse trace ────────────────────────────────────────────────
        self._trace(session_id, user_query, response_text, latency_ms, col_name)

        return result

    # ── Chat dispatcher ───────────────────────────────────────────────────

    def process_chat(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        session_id = request_data.get("session_id") or str(uuid.uuid4())
        query = (request_data.get("query") or request_data.get("message") or "").strip()
        mongodb_uri = (request_data.get("mongodb_uri") or "").strip()
        uri_from_request_body = bool(mongodb_uri)
        if not mongodb_uri:
            mongodb_uri = (os.getenv("MONGODB_URI") or "").strip()
        file_content = request_data.get("file_content")
        file_type = request_data.get("file_type")
        file_name = request_data.get("file_name")
        raw_text = request_data.get("raw_text")
        col_name = request_data.get("collection_name") or self._cfg().default_collection
        top_k = int(request_data.get("top_k", 5))
        access_roles = request_data.get("access_roles")
        metadata_filters = request_data.get("metadata_filters")
        clear_history = request_data.get("clear_history", False)

        if clear_history:
            self._sessions().clear_history(session_id)

        now = datetime.utcnow().isoformat()
        session = self._sessions().get(session_id) or {}

        # ── Step 1: Connect ───────────────────────────────────────────────
        # URI in the JSON body always triggers (re)connect. URI from env connects only
        # when this session has no client yet — otherwise every request would reconnect
        # and never reach ingest/query.
        if mongodb_uri and (uri_from_request_body or not mongo_service.is_connected(session_id)):
            result = self.connect(session_id, mongodb_uri)
            session = self._sessions().get(session_id) or {}
            if not result["success"]:
                return {
                    "success": False,
                    "response": result["message"],
                    "query": query or "connect",
                    "thinking_steps": result.get("thinking_steps", []),
                    "timestamp": now,
                    "phase": "connection_failed",
                    "databases": result.get("databases", []),
                    "connected": False,
                    "ingested": session.get("ingested", False),
                    "requires_uri": False,
                    "requires_upload": False,
                    "session_id": session_id,
                }
            connect_only = (
                not file_content
                and not raw_text
                and (not query.strip() or query.strip().lower() == "connect")
            )
            if connect_only:
                return {
                    "success": True,
                    "response": result["message"],
                    "query": query or "connect",
                    "thinking_steps": result.get("thinking_steps", []),
                    "timestamp": now,
                    "phase": "connected",
                    "databases": result.get("databases", []),
                    "connected": True,
                    "ingested": session.get("ingested", False),
                    "requires_uri": False,
                    "requires_upload": True,
                    "session_id": session_id,
                }
            # Connected in this same request; continue to ingest / Q&A below.

        # ── Step 2: Ingest ────────────────────────────────────────────────
        if file_content or raw_text:
            result = self.ingest(
                session_id=session_id,
                file_content=file_content,
                file_type=file_type,
                file_name=file_name,
                raw_text=raw_text,
                collection_name=col_name,
                access_roles=access_roles,
            )
            return {
                "success": result["success"],
                "response": result["message"],
                "query": query or "ingest",
                "thinking_steps": result.get("thinking_steps", []),
                "timestamp": now,
                "phase": "ingested" if result["success"] else "ingestion_failed",
                "chunks_count": result.get("chunks_count", 0),
                "connected": session.get("connected", False),
                "ingested": result["success"] or session.get("ingested", False),
                "requires_uri": False,
                "requires_upload": False,
                "session_id": session_id,
            }

        # ── Awaiting URI ──────────────────────────────────────────────────
        if not mongo_service.is_connected(session_id):
            status_msg = self._connection_status_response(query, session_id, session, col_name)
            return {
                "success": True,
                "response": status_msg
                or (
                    "Welcome to the **MongoDB Atlas KB Agent**.\n\n"
                    "Set **MONGODB_URI** (your Atlas connection string) in the **Config** tab "
                    "on the agent page, save, then try again."
                ),
                "query": query, "thinking_steps": [], "timestamp": now,
                "phase": "connection_status" if status_msg else "awaiting_uri",
                "requires_uri": True,
                "requires_upload": False,
                "connected": False, "ingested": False, "session_id": session_id,
            }

        # ── Awaiting upload ───────────────────────────────────────────────
        if not session.get("ingested"):
            stats = mongo_service.get_collection_stats(session_id, col_name, session.get("db_name", self._cfg().default_db_name))
            if stats.get("total_chunks", 0) > 0:
                self._sessions().set(session_id, {"ingested": True})
            else:
                status_msg = self._connection_status_response(query, session_id, session, col_name)
                return {
                    "success": True,
                    "response": status_msg
                    or (
                        "Connected!\n\n"
                        "Upload a file (PDF, DOCX, XLSX, PPTX, CSV, TXT, MD, HTML) "
                        "or paste text to build your knowledge base."
                    ),
                    "query": query, "thinking_steps": [], "timestamp": now,
                    "phase": "connection_status" if status_msg else "awaiting_upload",
                    "requires_uri": False, "requires_upload": not status_msg,
                    "connected": True, "ingested": False, "session_id": session_id,
                }

        session = self._sessions().get(session_id) or session

        # ── LLM credential preflight (matches SQL DB Agent pattern) ────────
        if query:
            status_msg = self._connection_status_response(query, session_id, session, col_name)
            if status_msg:
                return {
                    "success": True,
                    "response": status_msg,
                    "query": query,
                    "thinking_steps": [],
                    "timestamp": now,
                    "phase": "connection_status",
                    "connected": True,
                    "ingested": bool(session.get("ingested")),
                    "requires_uri": False,
                    "requires_upload": False,
                    "session_id": session_id,
                }
            errs = _config_errors()
            if errs:
                return {
                    "success": False,
                    "response": "**Configuration incomplete**\n\n" + "\n".join(f"- {e}" for e in errs),
                    "query": query, "thinking_steps": [], "timestamp": now,
                    "phase": "config_error", "connected": True,
                    "ingested": session.get("ingested", False),
                    "requires_uri": False, "requires_upload": False,
                    "session_id": session_id,
                }

        # ── Query ─────────────────────────────────────────────────────────
        if query:
            result = self.query(
                session_id=session_id,
                user_query=query,
                collection_name=col_name,
                top_k=top_k,
                metadata_filters=metadata_filters,
                access_roles=access_roles,
            )
            return {
                "success": result["success"],
                "response": result["response"],
                "query": result["query"],
                "thinking_steps": result.get("thinking_steps", []),
                "timestamp": now,
                "phase": "query_response",
                "sources": result.get("sources", []),
                "connected": True,
                "ingested": True,
                "requires_uri": False,
                "requires_upload": False,
                "session_id": session_id,
                "cache_hit": result.get("cache_hit", False),
                "latency_ms": result.get("latency_ms"),
                "evaluation": result.get("evaluation"),
            }

        return {
            "success": True, "response": "Provide a query or upload a document.",
            "query": query, "thinking_steps": [], "timestamp": now,
            "phase": "idle", "connected": True, "ingested": session.get("ingested", False),
            "session_id": session_id,
        }

    # ── Prompt builder ────────────────────────────────────────────────────

    def _build_prompt(self, query: str, context: str, history: str) -> str:
        try:
            from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS
            _cite = f"\n{MANDATORY_MARKDOWN_SOURCE_LINKS}\n"
        except Exception:
            _cite = ""
        conv = f"Recent conversation:\n{history}\n\n" if history.strip() else ""
        return (
            f"{conv}"
            "You are a precise, grounded assistant. Answer using ONLY the retrieved context below.\n"
            "Rules:\n"
            "1. If the context contains the answer, provide it with source references.\n"
            "2. If context is insufficient, clearly state what is missing.\n"
            "3. Never fabricate information not in the context.\n"
            "4. Cite source name and section when referencing specific data, with a markdown link if the context includes a URL or file path that can be expressed as a link to the document.\n"
            "5. Quote exact figures and values from the context.\n"
            f"{_cite}\n"
            f"Retrieved Context:\n{context}\n\n"
            f"Question: {query}\n\nAnswer:"
        )

    # ── Fallback response ─────────────────────────────────────────────────

    def _fallback_response(self, query: str, results: List[Dict[str, Any]]) -> str:
        parts = [f"Here is what I found relevant to: *\"{query}\"*\n"]
        for i, r in enumerate(results):
            src = r.get("file_name", "unknown")
            sec = r.get("section", "")
            score = r.get("score") or 0
            parts.append(
                f"**Source {i+1}** ({src}{f' – {sec}' if sec else ''}, relevance: {score:.3f}):\n"
                f"> {r['text'][:300]}…"
            )
        parts.append("\n*LLM unavailable — showing raw retrieved context.*")
        return "\n\n".join(parts)

    # ── Langfuse ──────────────────────────────────────────────────────────

    def _trace(
        self,
        session_id: str,
        query: str,
        response: str,
        latency_ms: int,
        collection: str,
    ) -> None:
        try:
            if not self._cfg().langfuse_enabled:
                return
            from langfuse_tracer import set_langfuse_context, trace_llm_call
            set_langfuse_context(
                session_id=session_id,
                agent_name="MongoDB Atlas KB Agent",
            )
            trace_llm_call(
                model=self.ai_service.default_model if hasattr(self.ai_service, "default_model") else "unknown",
                prompt=query[:500],
                completion=response[:500],
                latency_ms=latency_ms,
            )
        except Exception:
            pass


mongodb_rag_agent = MongoDBRAGAgent()
