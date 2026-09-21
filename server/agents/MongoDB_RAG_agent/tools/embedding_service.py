"""Configurable embedding service for the MongoDB Atlas KB Agent.

Providers:
  bge-small  — BAAI/bge-small-en-v1.5  (384-dim)  fast, low memory
  bge-large  — BAAI/bge-large-en-v1.5  (1024-dim) high quality, default
    pwc_genai  — vertex_ai.text-embedding-005 (typically 768-dim) via PWC GenAI
  openai     — text-embedding-3-small  (1536-dim)  requires OPENAI_API_KEY

All models are loaded lazily and cached as module-level singletons so
the model is only loaded once per process regardless of how many agent
instances exist.
"""

from __future__ import annotations

import importlib
import os
from typing import List, Optional

import requests

from ..config import MongoRAGSettings

try:
    from request_config import get_config_value
except Exception:  # pragma: no cover
    get_config_value = None

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

_BGE_MODELS = {
    "bge-small": "BAAI/bge-small-en-v1.5",
    "bge-large": "BAAI/bge-large-en-v1.5",
}

_DIMS = {
    "bge-small": 384,
    "bge-large": 1024,
    "pwc_genai": 768,
    "openai":    1536,
}

# Module-level singletons keyed by provider name
_fastembed_models: dict = {}
_resolved_providers: dict = {}
_resolved_dims: dict = {}


def _get_cfg(key: str, default: str = "") -> str:
    if get_config_value is not None:
        val = get_config_value(key, default)
    else:
        val = os.getenv(key, default)
    return (val or default).strip()


def _normalize_provider(provider: str) -> str:
    p = (provider or "").lower().strip()
    aliases = {
        "default": "bge-large",
        "bge": "bge-large",
        "pwc": "pwc_genai",
        "genai": "pwc_genai",
        "vertex": "pwc_genai",
    }
    return aliases.get(p, p)


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _embed_fastembed(texts: List[str], provider: str) -> List[List[float]]:
    model_name = _BGE_MODELS[provider]
    if provider not in _fastembed_models:
        try:
            fastembed_mod = importlib.import_module("fastembed")
            TextEmbedding = getattr(fastembed_mod, "TextEmbedding")
            _fastembed_models[provider] = TextEmbedding(model_name=model_name)
        except Exception as exc:
            raise RuntimeError(
                f"fastembed load failed for {model_name}: {exc}. Install with `pip install fastembed`."
            ) from exc
    model = _fastembed_models[provider]
    vecs = list(model.embed(texts))
    return [v.tolist() if hasattr(v, "tolist") else list(v) for v in vecs]


def _embed_pwc_genai(texts: List[str], settings: Optional[MongoRAGSettings] = None) -> List[List[float]]:
    base_url = _get_cfg("PWC_GENAI_ENDPOINT_URL", "")
    if not base_url:
        raise ValueError("PWC_GENAI_ENDPOINT_URL is required for pwc_genai embeddings")

    root = base_url.rstrip("/")
    if root.endswith("/completions"):
        root = root[: -len("/completions")]
    elif root.endswith("/embeddings"):
        pass
    embeddings_url = root if root.endswith("/embeddings") else f"{root}/embeddings"

    # Support both PwC and Gemini key names; request-scoped config takes precedence.
    api_key = _get_cfg("PWC_GENAI_API_KEY", "") or _get_cfg("GEMINI_API_KEY", "")
    bearer = _get_cfg("PWC_GENAI_BEARER_TOKEN", "")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    model_name = (
        settings.pwc_embedding_model
        if settings and getattr(settings, "pwc_embedding_model", "")
        else (_get_cfg("MONGO_RAG_PWC_EMBEDDING_MODEL", "") or _get_cfg("EMBEDDING_MODEL", "vertex_ai.text-embedding-005") or "vertex_ai.text-embedding-005")
    )

    payload = {
        "model": model_name,
        "input": texts,
    }

    resp = requests.post(embeddings_url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    vectors = [item["embedding"] for item in data.get("data", []) if isinstance(item, dict) and "embedding" in item]
    if len(vectors) != len(texts):
        raise RuntimeError(
            f"pwc_genai returned {len(vectors)} embeddings for {len(texts)} inputs"
        )
    return vectors


def _embed_openai(texts: List[str], settings: MongoRAGSettings) -> List[List[float]]:
    api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
    try:
        openai = importlib.import_module("openai")
    except Exception as exc:
        raise RuntimeError(
            f"openai client not available: {exc}. Install with `pip install openai`."
        ) from exc
    client = openai.OpenAI(api_key=api_key)
    response = client.embeddings.create(
        model=settings.openai_embedding_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_embeddings(
    texts: List[str],
    settings: Optional[MongoRAGSettings] = None,
) -> List[List[float]]:
    """Embed a batch of texts using the configured provider.

    Parameters
    ----------
    texts    : non-empty list of strings
    settings : MongoRAGSettings; if None defaults to bge-large
    """
    if not texts:
        return []

    configured_provider = _normalize_provider(settings.embedding_provider if settings else "bge-large")
    target_dim = int(getattr(settings, "embedding_dimension_override", 0) or 0) if settings else 0

    fallback_order = [configured_provider]
    if configured_provider == "bge-large":
        fallback_order.extend(["pwc_genai", "bge-small", "openai"])
    elif configured_provider == "bge-small":
        fallback_order.extend(["bge-large", "pwc_genai", "openai"])
    elif configured_provider == "pwc_genai":
        fallback_order.extend(["bge-large", "bge-small", "openai"])
    elif configured_provider == "openai":
        fallback_order.extend(["pwc_genai", "bge-large", "bge-small"])
    else:
        print(f"[Embedding] Unknown provider '{configured_provider}', trying fallback chain")
        fallback_order = ["pwc_genai", "bge-large", "bge-small", "openai"]

    seen = set()
    ordered_candidates = []
    for p in fallback_order:
        if p not in seen:
            seen.add(p)
            ordered_candidates.append(p)

    errors: List[str] = []
    for provider in ordered_candidates:
        try:
            # When a target dimension is required (usually to match an existing index),
            # skip fallback providers with known incompatible dimensions.
            if target_dim > 0 and provider != configured_provider:
                hinted_dim = _DIMS.get(provider)
                if hinted_dim and hinted_dim != target_dim:
                    errors.append(f"{provider}: skipped (dim {hinted_dim} != required {target_dim})")
                    continue

            if provider == "openai":
                if settings is None:
                    raise ValueError("settings required for OpenAI embeddings")
                vectors = _embed_openai(texts, settings)
            elif provider == "pwc_genai":
                vectors = _embed_pwc_genai(texts, settings)
            elif provider in _BGE_MODELS:
                vectors = _embed_fastembed(texts, provider)
            else:
                raise ValueError(f"unsupported provider: {provider}")

            dim = len(vectors[0]) if vectors and vectors[0] else _DIMS.get(provider, 1024)
            if target_dim > 0 and dim != target_dim:
                raise RuntimeError(f"returned {dim}d, required {target_dim}d")

            _resolved_providers[configured_provider] = provider
            _resolved_dims[configured_provider] = dim
            _resolved_dims[provider] = dim

            if provider != configured_provider:
                reason = errors[0] if errors else "unknown reason"
                print(
                    f"[Embedding] Provider '{configured_provider}' unavailable ({reason}); using '{provider}' ({dim}d)"
                )
            return vectors
        except Exception as exc:
            errors.append(f"{provider}: {exc}")

    raise RuntimeError(
        f"Could not generate embeddings with provider '{configured_provider}'. "
        f"Tried: {' | '.join(errors)}"
    )


def get_single_embedding(
    text: str,
    settings: Optional[MongoRAGSettings] = None,
) -> List[float]:
    return get_embeddings([text], settings)[0]


def get_embedding_dimension(
    settings: Optional[MongoRAGSettings] = None,
) -> int:
    configured_provider = _normalize_provider(settings.embedding_provider if settings else "bge-large")
    resolved_provider = _resolved_providers.get(configured_provider, configured_provider)

    if configured_provider in _resolved_dims:
        return _resolved_dims[configured_provider]
    if resolved_provider in _resolved_dims:
        return _resolved_dims[resolved_provider]

    if settings and getattr(settings, "embedding_dimension_override", 0) > 0:
        return int(settings.embedding_dimension_override)

    return _DIMS.get(resolved_provider, _DIMS.get(configured_provider, 1024))
