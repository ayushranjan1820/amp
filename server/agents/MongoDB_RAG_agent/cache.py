"""Semantic cache for the MongoDB Atlas KB Agent.

Backends: memory (LRU + TTL) and Redis (with memory fallback).

Cache key strategy: cosine similarity between query embeddings.
Queries above `similarity_threshold` return the cached response
without hitting MongoDB or the LLM — saving latency and cost.

Cache entries are scoped per collection so different data sources
never produce cross-collection hits. Invalidation clears only the
affected collection's entries, not the entire cache.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import traceback
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

from .config import MongoRAGSettings


# ---------------------------------------------------------------------------
# In-memory LRU cache with TTL
# ---------------------------------------------------------------------------

class _InMemoryCache:
    def __init__(self, max_entries: int = 1000, ttl_seconds: int = 3600):
        self._store: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_entries
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            if key not in self._store:
                return None
            entry = self._store[key]
            if time.time() - entry["ts"] > self._ttl:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return entry["data"]

    def put(self, key: str, data: Dict[str, Any]) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = {"data": data, "ts": time.time()}
            else:
                if len(self._store) >= self._max:
                    self._store.popitem(last=False)
                self._store[key] = {"data": data, "ts": time.time()}

    def delete_by_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._store if k.startswith(prefix)]
            for k in keys:
                del self._store[k]
            return len(keys)

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def clear(self) -> int:
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n


# ---------------------------------------------------------------------------
# Redis cache adapter
# ---------------------------------------------------------------------------

class _RedisCache:
    def __init__(self, redis_url: str, prefix: str, max_entries: int, ttl_seconds: int):
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._client = None
        self._fallback = _InMemoryCache(max_entries=max_entries, ttl_seconds=ttl_seconds)
        self._use_fallback = False
        try:
            import redis
            self._client = redis.from_url(redis_url, decode_responses=True)
            self._client.ping()
        except Exception as e:
            print(f"[RAGCache] Redis unavailable ({e}), using in-memory fallback")
            self._use_fallback = True

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if self._use_fallback:
            return self._fallback.get(key)
        try:
            raw = self._client.get(self._key(key))
            return json.loads(raw) if raw else None
        except Exception:
            return self._fallback.get(key)

    def put(self, key: str, data: Dict[str, Any]) -> None:
        if self._use_fallback:
            self._fallback.put(key, data)
            return
        try:
            self._client.setex(self._key(key), self._ttl, json.dumps(data, default=str))
        except Exception:
            self._fallback.put(key, data)

    def delete_by_prefix(self, prefix: str) -> int:
        full = f"{self._prefix}{prefix}"
        if self._use_fallback:
            return self._fallback.delete_by_prefix(prefix)
        try:
            keys = self._client.keys(f"{full}*")
            if keys:
                return self._client.delete(*keys)
            return 0
        except Exception:
            return self._fallback.delete_by_prefix(prefix)

    def size(self) -> int:
        if self._use_fallback:
            return self._fallback.size()
        try:
            return len(self._client.keys(f"{self._prefix}*"))
        except Exception:
            return self._fallback.size()


# ---------------------------------------------------------------------------
# Semantic cache
# ---------------------------------------------------------------------------

def _cosine(a: List[float], b: List[float]) -> float:
    if not a or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class SemanticCache:
    """Semantic cache: cache responses keyed by query embedding similarity.

    Scoped per (collection, session) so invalidation is surgical.
    Embedding index kept in-process (HNSW upgrade path: replace _find_similar
    with a faiss.IndexFlatIP or hnswlib index).
    """

    def __init__(self, settings: MongoRAGSettings):
        self._threshold = settings.cache_similarity_threshold
        prefix = "mongo_rag_cache:"
        if settings.cache_backend == "redis":
            self._store = _RedisCache(
                redis_url=settings.redis_url,
                prefix=prefix,
                max_entries=settings.cache_max_entries,
                ttl_seconds=settings.cache_ttl_seconds,
            )
        else:
            self._store = _InMemoryCache(
                max_entries=settings.cache_max_entries,
                ttl_seconds=settings.cache_ttl_seconds,
            )
        # collection-scoped embedding index
        self._emb_index: Dict[str, List[float]] = {}   # cache_key → embedding
        self._collection_keys: Dict[str, List[str]] = {}  # collection_scope → [keys]
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    def lookup(
        self,
        query: str,
        collection: str,
        query_embedding: Optional[List[float]] = None,
    ) -> Optional[Dict[str, Any]]:
        scope = self._scope(collection)

        # Semantic similarity match
        if query_embedding is not None:
            best_key, best_sim = self._find_similar(query_embedding, scope)
            if best_key and best_sim >= self._threshold:
                cached = self._store.get(best_key)
                if cached:
                    cached["cache_similarity"] = round(best_sim, 4)
                    cached["cache_hit"] = True
                    return cached

        # Exact hash fallback
        exact_key = self._hash_key(query, scope)
        cached = self._store.get(exact_key)
        if cached:
            cached["cache_similarity"] = 1.0
            cached["cache_hit"] = True
            return cached

        return None

    def store(
        self,
        query: str,
        collection: str,
        response: Dict[str, Any],
        query_embedding: Optional[List[float]] = None,
    ) -> None:
        scope = self._scope(collection)
        key = self._hash_key(query, scope)
        self._store.put(key, response)
        if query_embedding is not None:
            with self._lock:
                self._emb_index[key] = query_embedding
                self._collection_keys.setdefault(scope, []).append(key)

    def invalidate(self, collection: str) -> int:
        """Invalidate only entries that belong to this collection scope."""
        scope = self._scope(collection)
        n = self._store.delete_by_prefix(scope)
        with self._lock:
            keys = self._collection_keys.pop(scope, [])
            for k in keys:
                self._emb_index.pop(k, None)
        return n

    def size(self) -> int:
        return self._store.size()

    # ── Internal ──────────────────────────────────────────────────────────

    @staticmethod
    def _scope(collection: str) -> str:
        return hashlib.sha256(collection.encode()).hexdigest()[:12]

    @staticmethod
    def _hash_key(query: str, scope: str) -> str:
        raw = f"{scope}::{query.strip().lower()}"
        return f"{scope}_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"

    def _find_similar(
        self,
        query_embedding: List[float],
        scope: str,
    ) -> Tuple[Optional[str], float]:
        best_key: Optional[str] = None
        best_sim = 0.0
        with self._lock:
            keys = self._collection_keys.get(scope, [])
            for key in keys:
                emb = self._emb_index.get(key)
                if emb is None:
                    continue
                sim = _cosine(query_embedding, emb)
                if sim > best_sim:
                    best_sim = sim
                    best_key = key
        return best_key, best_sim
