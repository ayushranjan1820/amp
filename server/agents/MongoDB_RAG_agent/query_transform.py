"""Query transformation strategies for the MongoDB Atlas KB Agent.

Strategies:
  - multi_query : Generate N alternative phrasings → broader recall
  - hyde        : Generate a hypothetical answer → better semantic match
  - decompose   : Break complex questions into sub-questions
  - none        : Return original query unchanged

All use the shared AI service; failures gracefully return the original query.
"""

from __future__ import annotations

import traceback
from typing import Any, List, Optional

from .config import MongoRAGSettings


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_MULTI_QUERY_PROMPT = """\
You are an expert at reformulating search queries to improve document retrieval.
Given the user's question, generate {count} alternative versions using different
wording, perspective, or specificity to surface documents the original might miss.

Original question: {query}

Generate exactly {count} alternative questions, one per line.
Do NOT number them. Do NOT repeat the original. Output ONLY the alternatives:"""


_HYDE_PROMPT = """\
You are a domain expert. Write a short paragraph that would appear in a knowledge
base document answering the question below. Write as if authoring the document,
not answering a user. Be specific and factual.

Question: {query}

Hypothetical document passage:"""


_DECOMPOSE_PROMPT = """\
You are an expert at breaking complex questions into simpler independent sub-questions.
Decompose the question below into {count} simpler questions that together cover all aspects.

Complex question: {query}

Generate exactly {count} sub-questions, one per line. Do NOT number them. Output ONLY the sub-questions:"""


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def multi_query_expand(
    query: str,
    settings: MongoRAGSettings,
    ai_service: Any,
    count: Optional[int] = None,
) -> List[str]:
    n = count or settings.query_expansion_count
    prompt = _MULTI_QUERY_PROMPT.format(query=query, count=n)
    try:
        raw = ai_service.call_genai(prompt, temperature=0.7, max_tokens=512)
    except Exception as e:
        print(f"[QueryTransform:multi_query] failed: {e}")
        return [query]

    lines = [
        line.strip().lstrip("0123456789.-) ").strip()
        for line in raw.strip().split("\n")
        if line.strip() and len(line.strip()) > 8
    ]
    return [query] + lines[:n]


def hyde_transform(
    query: str,
    settings: MongoRAGSettings,
    ai_service: Any,
) -> List[str]:
    prompt = _HYDE_PROMPT.format(query=query)
    try:
        hyp = ai_service.call_genai(prompt, temperature=0.3, max_tokens=512)
    except Exception as e:
        print(f"[QueryTransform:hyde] failed: {e}")
        return [query]

    hyp = hyp.strip()
    if not hyp or len(hyp) < 20:
        return [query]
    return [hyp, query]


def decompose_query(
    query: str,
    settings: MongoRAGSettings,
    ai_service: Any,
    count: Optional[int] = None,
) -> List[str]:
    n = count or settings.query_expansion_count
    prompt = _DECOMPOSE_PROMPT.format(query=query, count=n)
    try:
        raw = ai_service.call_genai(prompt, temperature=0.3, max_tokens=512)
    except Exception as e:
        print(f"[QueryTransform:decompose] failed: {e}")
        return [query]

    lines = [
        line.strip().lstrip("0123456789.-) ").strip()
        for line in raw.strip().split("\n")
        if line.strip() and len(line.strip()) > 8
    ]
    return lines[:n] if lines else [query]


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------

def transform_query(
    query: str,
    settings: MongoRAGSettings,
    ai_service: Any,
    strategy_override: Optional[str] = None,
) -> List[str]:
    """Return a list of query strings.

    The first element is always the primary search query.
    For multi_query/decompose, additional queries broaden recall.
    For HyDE, the hypothetical document comes first (best semantic match).
    """
    strategy = (strategy_override or settings.query_transform_strategy).lower().strip()

    if strategy in ("none", "disabled", ""):
        return [query]

    try:
        if strategy == "multi_query":
            return multi_query_expand(query, settings, ai_service)
        elif strategy == "hyde":
            return hyde_transform(query, settings, ai_service)
        elif strategy == "decompose":
            return decompose_query(query, settings, ai_service)
        else:
            print(f"[QueryTransform] Unknown strategy '{strategy}', using original")
            return [query]
    except Exception as e:
        print(f"[QueryTransform] {strategy} error: {e}")
        traceback.print_exc()
        return [query]
