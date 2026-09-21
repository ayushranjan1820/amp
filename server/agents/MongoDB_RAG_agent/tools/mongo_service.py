"""MongoDB Atlas service for the RAG Agent.

Enterprise features implemented here:
  - Upsert with SHA-256 chunk-hash deduplication (no duplicates on re-ingest)
  - numCandidates = max(floor, top_k * multiplier) for high-recall ANN
  - Index readiness polling: polls list_search_indexes() until READY (no sleep(2))
  - Hybrid search: $vectorSearch + $search Atlas full-text, merged with RRF
  - RBAC metadata filter on $vectorSearch via the `filter` field
  - Document versioning: soft-delete old chunks before writing new version
  - Parent-chunk fetch for context expansion after child retrieval
  - Full-text index auto-creation alongside vector index
  - Connection management: per-session MongoClient stored here, ping-checked
"""

from __future__ import annotations

import hashlib
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pymongo import MongoClient, UpdateOne
from pymongo.errors import ConnectionFailure, OperationFailure

from ..config import MongoRAGSettings


# ---------------------------------------------------------------------------
# MongoService
# ---------------------------------------------------------------------------

class MongoService:

    def __init__(self):
        # session_id → MongoClient
        self._clients: Dict[str, MongoClient] = {}

    # ── Connection ────────────────────────────────────────────────────────

    def connect(
        self,
        session_id: str,
        uri: str,
        settings: Optional[MongoRAGSettings] = None,
    ) -> Tuple[bool, str, List[str]]:
        import re
        cfg = settings or MongoRAGSettings()
        try:
            client = MongoClient(
                uri,
                connectTimeoutMS=cfg.connect_timeout_ms,
                serverSelectionTimeoutMS=cfg.server_selection_timeout_ms,
            )
            client.admin.command("ping")
            # Close any existing client for this session cleanly
            old = self._clients.pop(session_id, None)
            if old:
                try:
                    old.close()
                except Exception:
                    pass
            self._clients[session_id] = client
            db_names = [
                db for db in client.list_database_names()
                if db not in ("admin", "local", "config")
            ]
            return True, "Connected to MongoDB Atlas.", db_names
        except ConnectionFailure as e:
            safe = re.sub(r'//[^:]+:[^@]+@', '//***:***@', str(e))
            return False, f"Connection failed: {safe}", []
        except Exception as e:
            safe = re.sub(r'//[^:]+:[^@]+@', '//***:***@', str(e))
            return False, f"Error: {safe}", []

    def is_connected(self, session_id: str) -> bool:
        client = self._clients.get(session_id)
        if not client:
            return False
        try:
            client.admin.command("ping")
            return True
        except Exception:
            self._clients.pop(session_id, None)
            return False

    def disconnect(self, session_id: str) -> None:
        client = self._clients.pop(session_id, None)
        if client:
            try:
                client.close()
            except Exception:
                pass

    def _get_collection(
        self,
        session_id: str,
        collection_name: str,
        db_name: str,
    ):
        client = self._clients.get(session_id)
        if not client:
            raise ValueError("Not connected. Please provide a MongoDB URI.")
        return client[db_name][collection_name]

    # ── Ingestion with upsert + versioning ───────────────────────────────

    def store_chunks(
        self,
        session_id: str,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        collection_name: str,
        file_name: str,
        db_name: str,
        settings: Optional[MongoRAGSettings] = None,
        access_roles: Optional[List[str]] = None,
        version: int = 1,
    ) -> int:
        cfg = settings or MongoRAGSettings()
        col = self._get_collection(session_id, collection_name, db_name)
        now = datetime.utcnow()

        # Soft-delete previous version chunks for this file
        if cfg.enable_document_versioning and version > 1:
            col.update_many(
                {"file_name": file_name, "version": {"$lt": version}, "is_deleted": False},
                {"$set": {"is_deleted": True, "deleted_at": now}},
            )

        ops: List[UpdateOne] = []
        for chunk, embedding in zip(chunks, embeddings):
            meta = chunk.get("metadata", {})
            chunk_hash = _chunk_hash(chunk.get("text", ""), file_name)
            doc: Dict[str, Any] = {
                "text": chunk["text"],
                "embedding": embedding,
                "chunk_id": meta.get("chunk_index", 0),
                "chunk_type": meta.get("chunk_type", "child"),
                "parent_id": meta.get("parent_id"),
                "section": meta.get("section", ""),
                "char_count": len(chunk.get("text", "")),
                "file_name": file_name,
                "source_doc_id": meta.get("source_doc_id", ""),
                "version": version,
                "is_deleted": False,
                "ingested_at": now,
                "updated_at": now,
            }
            # RBAC
            if access_roles:
                doc["access_roles"] = access_roles
            # TTL
            if cfg.document_ttl_days > 0:
                from datetime import timedelta
                doc["expires_at"] = now + timedelta(days=cfg.document_ttl_days)

            ops.append(UpdateOne(
                {"chunk_hash": chunk_hash},
                {"$set": doc, "$setOnInsert": {"chunk_hash": chunk_hash, "created_at": now}},
                upsert=True,
            ))

        if ops:
            result = col.bulk_write(ops, ordered=False)
            return result.upserted_count + result.modified_count
        return 0

    # ── Index management ─────────────────────────────────────────────────

    def ensure_vector_index(
        self,
        session_id: str,
        collection_name: str,
        db_name: str,
        embedding_dim: int,
        settings: Optional[MongoRAGSettings] = None,
    ) -> str:
        cfg = settings or MongoRAGSettings()
        col = self._get_collection(session_id, collection_name, db_name)
        index_name = cfg.vector_index_name

        # Check if index already exists and is ready
        status = self._get_index_status(col, index_name)
        if status == "READY":
            return index_name
        if status is not None:
            # Exists but not ready — just wait
            return self._wait_for_index(col, index_name, cfg)

        # Create vector search index
        try:
            from pymongo.operations import SearchIndexModel
            fields: List[Dict[str, Any]] = [
                {
                    "type": "vector",
                    "path": "embedding",
                    "numDimensions": embedding_dim,
                    "similarity": "cosine",
                },
                {"type": "filter", "path": "file_name"},
                {"type": "filter", "path": "chunk_type"},
                {"type": "filter", "path": "is_deleted"},
                {"type": "filter", "path": "version"},
            ]
            if cfg.rbac_enabled:
                fields.append({"type": "filter", "path": "access_roles"})

            model = SearchIndexModel(
                definition={"fields": fields},
                name=index_name,
                type="vectorSearch",
            )
            col.create_search_index(model=model)
        except OperationFailure as e:
            if "already exists" in str(e).lower():
                pass
            else:
                print(f"[MongoService] Vector index creation error: {e}")
                return f"creation_error: {e}"
        except Exception as e:
            print(f"[MongoService] Vector index creation error: {e}")
            return f"creation_error: {e}"

        # Also create full-text index if hybrid search is enabled
        if cfg.hybrid_enabled:
            self._ensure_fulltext_index(col, cfg)

        return self._wait_for_index(col, index_name, cfg)

    def _ensure_fulltext_index(self, col, cfg: MongoRAGSettings) -> None:
        ft_name = cfg.fulltext_index_name
        status = self._get_index_status(col, ft_name)
        if status is not None:
            return
        try:
            from pymongo.operations import SearchIndexModel
            model = SearchIndexModel(
                definition={
                    "mappings": {
                        "dynamic": False,
                        "fields": {
                            "text": {"type": "string", "analyzer": "lucene.standard"},
                            "file_name": {"type": "string"},
                            "is_deleted": {"type": "boolean"},
                        },
                    }
                },
                name=ft_name,
                type="search",
            )
            col.create_search_index(model=model)
        except Exception as e:
            print(f"[MongoService] Full-text index creation error: {e}")

    def _get_index_status(self, col, index_name: str) -> Optional[str]:
        try:
            for idx in col.list_search_indexes():
                if idx.get("name") == index_name:
                    return idx.get("status", "UNKNOWN")
        except Exception:
            pass
        return None

    def _is_vector_index_doc(self, idx: Dict[str, Any]) -> bool:
        if (idx.get("type") or "").lower() == "vectorsearch":
            return True

        for key in ("latestDefinition", "definition"):
            definition = idx.get(key)
            if not isinstance(definition, dict):
                continue

            fields = definition.get("fields")
            if isinstance(fields, list):
                for field in fields:
                    if isinstance(field, dict) and field.get("type") == "vector":
                        return True

            mappings = definition.get("mappings")
            if isinstance(mappings, dict):
                mapped_fields = mappings.get("fields")
                if isinstance(mapped_fields, dict):
                    for _path, cfg in mapped_fields.items():
                        if isinstance(cfg, dict) and cfg.get("type") == "vector":
                            return True
        return False

    def _list_vector_indexes(self, col) -> List[Dict[str, Any]]:
        try:
            indexes = [idx for idx in col.list_search_indexes() if isinstance(idx, dict)]
            return [idx for idx in indexes if self._is_vector_index_doc(idx)]
        except Exception:
            return []

    def _resolve_vector_index_name(self, col, cfg: MongoRAGSettings) -> str:
        preferred = (cfg.vector_index_name or "").strip()
        vector_indexes = self._list_vector_indexes(col)

        # If preferred is present and ready, use it.
        if preferred:
            for idx in vector_indexes:
                if idx.get("name") == preferred and idx.get("status") == "READY":
                    return preferred

        # Otherwise, pick any ready vector index from the collection.
        ready_indexes = [idx.get("name") for idx in vector_indexes if idx.get("status") == "READY" and idx.get("name")]
        if ready_indexes:
            chosen = sorted(ready_indexes)[0]
            if chosen != preferred:
                print(f"[MongoService] Using available vector index '{chosen}' (preferred='{preferred or '(none)'}')")
            return chosen

        # Fallback to preferred name (may trigger useful Atlas error if nothing exists yet).
        return preferred or "vector_index"

    def _get_index_vector_dimension(self, col, index_name: str) -> Optional[int]:
        try:
            for idx in col.list_search_indexes():
                if idx.get("name") != index_name:
                    continue

                # VectorSearch indexes typically keep the definition under latestDefinition/definition.
                for key in ("latestDefinition", "definition"):
                    definition = idx.get(key)
                    if not isinstance(definition, dict):
                        continue

                    fields = definition.get("fields")
                    if isinstance(fields, list):
                        for field in fields:
                            if isinstance(field, dict) and field.get("type") == "vector":
                                dims = field.get("numDimensions")
                                try:
                                    return int(dims)
                                except (TypeError, ValueError):
                                    pass

                    # Back-compat for map-style definitions.
                    mappings = definition.get("mappings")
                    if isinstance(mappings, dict):
                        mapped_fields = mappings.get("fields")
                        if isinstance(mapped_fields, dict):
                            for _path, cfg in mapped_fields.items():
                                if isinstance(cfg, dict) and cfg.get("type") == "vector":
                                    dims = cfg.get("numDimensions", cfg.get("dimensions"))
                                    try:
                                        return int(dims)
                                    except (TypeError, ValueError):
                                        pass
        except Exception:
            pass
        return None

    def get_vector_index_dimension(
        self,
        session_id: str,
        collection_name: str,
        db_name: str,
        settings: Optional[MongoRAGSettings] = None,
    ) -> Optional[int]:
        cfg = settings or MongoRAGSettings()
        col = self._get_collection(session_id, collection_name, db_name)
        index_name = self._resolve_vector_index_name(col, cfg)
        return self._get_index_vector_dimension(col, index_name)

    def _wait_for_index(
        self,
        col,
        index_name: str,
        cfg: MongoRAGSettings,
    ) -> str:
        deadline = time.monotonic() + cfg.index_ready_timeout_sec
        interval = cfg.index_ready_poll_interval_sec
        while time.monotonic() < deadline:
            status = self._get_index_status(col, index_name)
            if status == "READY":
                return index_name
            if status in (None, "FAILED"):
                return f"index_status:{status}"
            time.sleep(interval)
        return f"timeout_after_{cfg.index_ready_timeout_sec}s"

    # ── Vector search ────────────────────────────────────────────────────

    def vector_search(
        self,
        session_id: str,
        query_embedding: List[float],
        collection_name: str,
        db_name: str,
        top_k: int = 5,
        settings: Optional[MongoRAGSettings] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        access_roles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        cfg = settings or MongoRAGSettings()
        col = self._get_collection(session_id, collection_name, db_name)
        index_name = self._resolve_vector_index_name(col, cfg)

        index_dim = self._get_index_vector_dimension(col, index_name)
        query_dim = len(query_embedding) if query_embedding else 0
        if index_dim and query_dim and index_dim != query_dim:
            print(
                f"[MongoService] vectorSearch skipped due to dimension mismatch: "
                f"index={index_name} ({index_dim}) query={query_dim}"
            )
            return []

        num_candidates = max(cfg.num_candidates_floor, top_k * cfg.num_candidates_multiplier)

        # Build Atlas $vectorSearch filter
        vs_filter: Dict[str, Any] = {"is_deleted": {"$eq": False}, "chunk_type": {"$eq": "child"}}

        if metadata_filters:
            for k, v in metadata_filters.items():
                vs_filter[k] = {"$eq": v}
        if access_roles and cfg.rbac_enabled:
            vs_filter["access_roles"] = {"$in": access_roles}

        pipeline = [
            {
                "$vectorSearch": {
                    "index": index_name,
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": num_candidates,
                    "limit": top_k * 2,   # fetch extra before de-dup
                    "filter": vs_filter,
                }
            },
            {
                "$project": {
                    "text": 1,
                    "section": 1,
                    "file_name": 1,
                    "chunk_id": 1,
                    "chunk_type": 1,
                    "parent_id": 1,
                    "source_doc_id": 1,
                    "version": 1,
                    "score": {"$meta": "vectorSearchScore"},
                    "_id": 0,
                }
            },
            {"$limit": top_k},
        ]

        try:
            return list(col.aggregate(pipeline))
        except OperationFailure as e:
            msg = str(e)
            if "vector field is indexed with" in msg.lower() and "queried with" in msg.lower():
                print(f"[MongoService] vectorSearch dimension mismatch: {msg}")
                return []
            print(f"[MongoService] vectorSearch failed: {e}")
            traceback.print_exc()
            return []
        except Exception as e:
            print(f"[MongoService] vectorSearch failed: {e}")
            traceback.print_exc()
            return []

    # ── Hybrid search (vector + full-text RRF) ───────────────────────────

    def hybrid_search(
        self,
        session_id: str,
        query: str,
        query_embedding: List[float],
        collection_name: str,
        db_name: str,
        top_k: int = 5,
        settings: Optional[MongoRAGSettings] = None,
        metadata_filters: Optional[Dict[str, Any]] = None,
        access_roles: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        cfg = settings or MongoRAGSettings()
        col = self._get_collection(session_id, collection_name, db_name)

        fetch_k = max(cfg.num_candidates_floor, top_k * cfg.num_candidates_multiplier)

        # --- Dense leg ---
        dense_results = self.vector_search(
            session_id, query_embedding, collection_name, db_name,
            top_k=fetch_k, settings=cfg,
            metadata_filters=metadata_filters, access_roles=access_roles,
        )

        # --- Sparse leg (Atlas $search full-text) ---
        ft_filter: Dict[str, Any] = {"is_deleted": False, "chunk_type": "child"}
        if metadata_filters:
            ft_filter.update(metadata_filters)

        sparse_results: List[Dict[str, Any]] = []
        try:
            must_clauses: List[Dict] = [{"text": {"query": query, "path": "text"}}]
            for k, v in ft_filter.items():
                must_clauses.append({"equals": {"path": k, "value": v}})

            ft_pipeline = [
                {"$search": {"index": cfg.fulltext_index_name, "compound": {"must": must_clauses}}},
                {
                    "$project": {
                        "text": 1, "section": 1, "file_name": 1,
                        "chunk_id": 1, "chunk_type": 1, "parent_id": 1,
                        "source_doc_id": 1, "version": 1,
                        "score": {"$meta": "searchScore"},
                        "_id": 0,
                    }
                },
                {"$limit": fetch_k},
            ]
            sparse_results = list(col.aggregate(ft_pipeline))
        except Exception as e:
            print(f"[MongoService] Full-text search failed (hybrid leg): {e}")

        # --- Reciprocal Rank Fusion ---
        return _rrf_merge(dense_results, sparse_results, top_k=top_k, k=cfg.rrf_k)

    # ── Parent chunk expansion ───────────────────────────────────────────

    def fetch_parent_chunks(
        self,
        session_id: str,
        parent_ids: List[str],
        collection_name: str,
        db_name: str,
    ) -> Dict[str, str]:
        """Return {parent_id: text} for context expansion."""
        if not parent_ids:
            return {}
        col = self._get_collection(session_id, collection_name, db_name)
        try:
            docs = list(col.find(
                {"parent_id": {"$in": list(set(parent_ids))}, "chunk_type": "parent"},
                {"parent_id": 1, "text": 1, "_id": 0},
            ))
            return {d["parent_id"]: d.get("text", "") for d in docs if d.get("parent_id")}
        except Exception as e:
            print(f"[MongoService] Parent fetch failed: {e}")
            return {}

    # ── Document management ──────────────────────────────────────────────

    def get_document_version(
        self,
        session_id: str,
        file_name: str,
        collection_name: str,
        db_name: str,
    ) -> int:
        """Return the next version number for a file (1 if new)."""
        col = self._get_collection(session_id, collection_name, db_name)
        try:
            doc = col.find_one(
                {"file_name": file_name},
                {"version": 1},
                sort=[("version", -1)],
            )
            return (doc["version"] + 1) if doc else 1
        except Exception:
            return 1

    def delete_document(
        self,
        session_id: str,
        file_name: str,
        collection_name: str,
        db_name: str,
        hard_delete: bool = False,
        settings: Optional[MongoRAGSettings] = None,
    ) -> Tuple[bool, int, str]:
        cfg = settings or MongoRAGSettings()
        col = self._get_collection(session_id, collection_name, db_name)
        try:
            if hard_delete:
                r = col.delete_many({"file_name": file_name})
                return True, r.deleted_count, f"Hard-deleted {r.deleted_count} chunks."
            else:
                r = col.update_many(
                    {"file_name": file_name, "is_deleted": False},
                    {"$set": {"is_deleted": True, "deleted_at": datetime.utcnow()}},
                )
                return True, r.modified_count, f"Soft-deleted {r.modified_count} chunks."
        except Exception as e:
            return False, 0, str(e)

    # ── Collection stats ─────────────────────────────────────────────────

    def get_collection_stats(
        self,
        session_id: str,
        collection_name: str,
        db_name: str,
    ) -> Dict[str, Any]:
        col = self._get_collection(session_id, collection_name, db_name)
        try:
            total = col.count_documents({"is_deleted": False, "chunk_type": "child"})
            files = col.distinct("file_name", {"is_deleted": False})
            return {"total_chunks": total, "files": files}
        except Exception as e:
            print(f"[MongoService] stats error: {e}")
            return {"total_chunks": 0, "files": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chunk_hash(text: str, file_name: str) -> str:
    """Deterministic hash for deduplication."""
    return hashlib.sha256(f"{file_name}::{text}".encode()).hexdigest()


def _rrf_merge(
    dense: List[Dict[str, Any]],
    sparse: List[Dict[str, Any]],
    top_k: int,
    k: int = 60,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion of two ranked lists."""
    scores: Dict[str, float] = {}
    docs_by_key: Dict[str, Dict[str, Any]] = {}

    def _doc_key(d: Dict[str, Any]) -> str:
        return str(d.get("source_doc_id", "")) + "_" + str(d.get("chunk_id", ""))

    for rank, doc in enumerate(dense):
        key = _doc_key(doc)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        docs_by_key[key] = doc

    for rank, doc in enumerate(sparse):
        key = _doc_key(doc)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        if key not in docs_by_key:
            docs_by_key[key] = doc

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    results = []
    for key, rrf_score in ranked[:top_k]:
        doc = dict(docs_by_key[key])
        doc["score"] = rrf_score
        doc["rrf_score"] = rrf_score
        results.append(doc)
    return results


mongo_service = MongoService()
