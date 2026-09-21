"""RAGAS-style RAG evaluation pipeline for the MongoDB Atlas KB Agent.

Metrics (all computed via LLM-as-judge, no external framework required):
  - faithfulness      : Does the answer use only information from the context?
  - answer_relevancy  : Does the answer actually address the question?
  - context_precision : Are retrieved chunks relevant to the question?
  - context_recall    : Does the context cover what's needed to answer?
  - overall_score     : Weighted combination of all four.

Evaluation is gated by settings.evaluation_enabled and
settings.evaluation_sample_rate to avoid running on every query.
"""

from __future__ import annotations

import json
import random
import re
import traceback
from typing import Any, Dict, List

from .config import MongoRAGSettings


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_FAITHFULNESS = """\
Evaluate the faithfulness of the answer below.
Faithfulness = the answer uses ONLY information present in the context.

Context:
{context}

Question: {question}
Answer: {answer}

Score 0.0–1.0:
- 1.0: every claim is traceable to the context
- 0.5: some claims from context, some hallucinated
- 0.0: answer is mostly not in the context

Return ONLY JSON: {{"score": <float>, "reason": "<brief>"}}"""

_RELEVANCY = """\
Evaluate how well the answer addresses the question.

Question: {question}
Answer: {answer}

Score 0.0–1.0:
- 1.0: directly and completely answers the question
- 0.5: partially addresses it
- 0.0: irrelevant

Return ONLY JSON: {{"score": <float>, "reason": "<brief>"}}"""

_CONTEXT_PRECISION = """\
Evaluate whether the retrieved chunks are relevant to the question.

Question: {question}

Retrieved chunks:
{chunks}

Score 0.0–1.0:
- 1.0: all chunks highly relevant
- 0.5: about half relevant
- 0.0: none relevant

Return ONLY JSON: {{"score": <float>, "reason": "<brief>"}}"""

_CONTEXT_RECALL = """\
Evaluate whether the context contains enough information to answer the question.

Question: {question}

Context:
{context}

Answer (generated from this context): {answer}

Score 0.0–1.0:
- 1.0: context has everything needed
- 0.5: context has some but not all
- 0.0: context is missing critical information

Return ONLY JSON: {{"score": <float>, "reason": "<brief>"}}"""


# ---------------------------------------------------------------------------
# Score parser
# ---------------------------------------------------------------------------

def _parse(raw: str) -> tuple:
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            d = json.loads(m.group())
            return max(0.0, min(1.0, float(d.get("score", 0.5)))), str(d.get("reason", ""))
    except Exception:
        pass
    nums = re.findall(r'(?:^|[^.\d])([01]?\.\d+|[01]\.0)', raw)
    return (max(0.0, min(1.0, float(nums[0]))), "") if nums else (0.5, "parse error")


# ---------------------------------------------------------------------------
# Individual evaluators
# ---------------------------------------------------------------------------

def _faithfulness(q, a, ctx, svc):
    try:
        raw = svc.call_genai(_FAITHFULNESS.format(context=ctx[:4000], question=q, answer=a[:2000]), temperature=0.0, max_tokens=256)
        return _parse(raw)
    except Exception as e:
        return 0.5, f"eval error: {e}"


def _relevancy(q, a, svc):
    try:
        raw = svc.call_genai(_RELEVANCY.format(question=q, answer=a[:2000]), temperature=0.0, max_tokens=256)
        return _parse(raw)
    except Exception as e:
        return 0.5, f"eval error: {e}"


def _context_precision(q, chunks, svc):
    chunks_str = "\n\n".join(f"[Chunk {i+1}] {c[:500]}" for i, c in enumerate(chunks[:10]))
    try:
        raw = svc.call_genai(_CONTEXT_PRECISION.format(question=q, chunks=chunks_str), temperature=0.0, max_tokens=256)
        return _parse(raw)
    except Exception as e:
        return 0.5, f"eval error: {e}"


def _context_recall(q, a, ctx, svc):
    try:
        raw = svc.call_genai(_CONTEXT_RECALL.format(question=q, context=ctx[:4000], answer=a[:2000]), temperature=0.0, max_tokens=256)
        return _parse(raw)
    except Exception as e:
        return 0.5, f"eval error: {e}"


# ---------------------------------------------------------------------------
# Public pipeline
# ---------------------------------------------------------------------------

def evaluate_rag_response(
    question: str,
    answer: str,
    context: str,
    chunks: List[str],
    settings: MongoRAGSettings,
    ai_service: Any,
) -> Dict[str, Any]:
    """Run full RAGAS-style evaluation. Returns empty dict when disabled or skipped."""
    if not settings.evaluation_enabled:
        return {}
    if random.random() > settings.evaluation_sample_rate:
        return {}

    results: Dict[str, Any] = {
        "faithfulness": None,
        "answer_relevancy": None,
        "context_precision": None,
        "context_recall": None,
        "overall_score": None,
        "details": {},
    }
    try:
        f_s, f_r = _faithfulness(question, answer, context, ai_service)
        r_s, r_r = _relevancy(question, answer, ai_service)
        cp_s, cp_r = _context_precision(question, chunks, ai_service)
        cr_s, cr_r = _context_recall(question, answer, context, ai_service)

        results.update({
            "faithfulness": f_s,
            "answer_relevancy": r_s,
            "context_precision": cp_s,
            "context_recall": cr_s,
            "details": {
                "faithfulness_reason": f_r,
                "relevancy_reason": r_r,
                "context_precision_reason": cp_r,
                "context_recall_reason": cr_r,
            },
        })

        weights = {"faithfulness": 0.3, "answer_relevancy": 0.3, "context_precision": 0.2, "context_recall": 0.2}
        results["overall_score"] = round(
            sum((results[k] or 0.5) * w for k, w in weights.items()), 4
        )
    except Exception as e:
        print(f"[Evaluator] pipeline error: {e}")
        traceback.print_exc()

    return results
