"""Multi-provider reranking for the MongoDB Atlas KB Agent.

Providers:
  - cohere        : Cohere Rerank API (highest quality, cloud)
  - cross-encoder : Local cross-encoder via sentence-transformers (no network)
  - llm           : LLM-as-judge relevance scoring (no extra deps, default)

All providers return documents sorted by relevance with a `rerank_score` field.
On any failure the original cosine-ranked order is preserved.
"""

from __future__ import annotations

import json
import re
import traceback
from typing import Any, Dict, List, Optional, Tuple

from .config import MongoRAGSettings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def rerank(
    query: str,
    documents: List[Dict[str, Any]],
    settings: MongoRAGSettings,
    top_k: Optional[int] = None,
    ai_service: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Rerank documents by relevance to query.

    Parameters
    ----------
    query      : user query string
    documents  : list of dicts with at least a 'text' key
    settings   : MongoRAGSettings
    top_k      : number of results to return (default: settings.reranker_top_k)
    ai_service : required only when provider == 'llm'
    """
    if not documents or not query.strip():
        return documents

    k = top_k or settings.reranker_top_k
    provider = settings.reranker_provider.lower()

    try:
        if provider == "cohere":
            return _rerank_cohere(query, documents, settings, k)
        elif provider == "cross-encoder":
            return _rerank_cross_encoder(query, documents, settings, k)
        else:
            return _rerank_llm(query, documents, settings, k, ai_service)
    except Exception as e:
        print(f"[Reranker:{provider}] failed ({e}), returning original order")
        traceback.print_exc()
        return documents[:k]


# ---------------------------------------------------------------------------
# Cohere
# ---------------------------------------------------------------------------

def _rerank_cohere(
    query: str,
    documents: List[Dict[str, Any]],
    settings: MongoRAGSettings,
    top_k: int,
) -> List[Dict[str, Any]]:
    if not settings.cohere_api_key:
        raise ValueError("COHERE_API_KEY required for Cohere reranking")

    import cohere  # lazy import
    client = cohere.Client(api_key=settings.cohere_api_key)
    doc_texts = [d.get("text", "") for d in documents]
    response = client.rerank(
        model=settings.cohere_model,
        query=query,
        documents=doc_texts,
        top_n=min(top_k, len(documents)),
    )
    reranked: List[Dict[str, Any]] = []
    for r in response.results:
        doc = dict(documents[r.index])
        doc["rerank_score"] = r.relevance_score
        doc["original_score"] = doc.get("score")
        doc["score"] = r.relevance_score
        reranked.append(doc)
    return reranked


# ---------------------------------------------------------------------------
# Cross-encoder (local)
# ---------------------------------------------------------------------------

_ce_cache: Dict[str, Any] = {}


def _rerank_cross_encoder(
    query: str,
    documents: List[Dict[str, Any]],
    settings: MongoRAGSettings,
    top_k: int,
) -> List[Dict[str, Any]]:
    model_name = settings.cross_encoder_model
    if model_name not in _ce_cache:
        from sentence_transformers import CrossEncoder  # lazy import
        _ce_cache[model_name] = CrossEncoder(model_name)

    model = _ce_cache[model_name]
    doc_texts = [d.get("text", "") for d in documents]
    pairs = [(query, t) for t in doc_texts]
    scores = model.predict(pairs)

    scored: List[Tuple[float, int]] = sorted(
        [(float(s), i) for i, s in enumerate(scores)],
        reverse=True,
    )
    reranked: List[Dict[str, Any]] = []
    for score, idx in scored[:top_k]:
        doc = dict(documents[idx])
        doc["rerank_score"] = score
        doc["original_score"] = doc.get("score")
        doc["score"] = score
        reranked.append(doc)
    return reranked


# ---------------------------------------------------------------------------
# LLM-as-judge (no extra deps)
# ---------------------------------------------------------------------------

_LLM_PROMPT = """\
You are a relevance scoring system. Score how relevant each document is to the query.

Query: {query}

Documents:
{documents}

For each document provide a relevance score 0.0 (irrelevant) to 1.0 (highly relevant).
Return ONLY a JSON array: [{{"index": 0, "score": 0.95}}, ...]

JSON:"""


def _rerank_llm(
    query: str,
    documents: List[Dict[str, Any]],
    settings: MongoRAGSettings,
    top_k: int,
    ai_service: Optional[Any],
) -> List[Dict[str, Any]]:
    if ai_service is None:
        raise ValueError("ai_service required for LLM reranking")

    doc_texts = [d.get("text", "")[:800] for d in documents]
    docs_str = "\n\n".join(f"[Document {i}]\n{t}" for i, t in enumerate(doc_texts))
    prompt = _LLM_PROMPT.format(query=query, documents=docs_str)

    try:
        raw = ai_service.call_genai(prompt, temperature=0.0, max_tokens=1024)
    except Exception as e:
        print(f"[Reranker:LLM] generation failed: {e}")
        return documents[:top_k]

    try:
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        scores_list = json.loads(m.group()) if m else []
    except (json.JSONDecodeError, AttributeError):
        return documents[:top_k]

    score_map: Dict[int, float] = {}
    for item in scores_list:
        if isinstance(item, dict) and "index" in item and "score" in item:
            idx = int(item["index"])
            if 0 <= idx < len(documents):
                score_map[idx] = float(item["score"])

    scored: List[Tuple[float, int]] = sorted(
        [(score_map.get(i, 0.5), i) for i in range(len(documents))],
        reverse=True,
    )
    reranked: List[Dict[str, Any]] = []
    for score, idx in scored[:top_k]:
        doc = dict(documents[idx])
        doc["rerank_score"] = score
        doc["original_score"] = doc.get("score")
        doc["score"] = score
        reranked.append(doc)
    return reranked
