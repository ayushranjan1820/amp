"""Enterprise chunking strategies for the MongoDB Atlas KB Agent.

Strategies:
  - recursive : Structure-aware recursive splitting (markdown-aware).
                Token-counted via tiktoken (falls back to word count).
  - semantic  : Embedding-similarity boundary detection (requires embed_fn).
  - csv       : Row-group chunking — every chunk prefixes column headers
                so each embedding carries column context.
  - line      : Legacy character-based splitting (backward compat).

Parent-child mode (enabled by default):
  Produces two tiers of chunks per document:
    parent  : large context windows (2048 tokens) stored for context expansion
    child   : small search-optimised chunks (512 tokens) stored for retrieval
  Child chunks carry a `parent_id` linking to their parent for expansion.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Any, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Token counting (tiktoken preferred, word-count fallback)
# ---------------------------------------------------------------------------

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        try:
            import tiktoken
            _tokenizer = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _tokenizer = None
    return _tokenizer


def _count_tokens(text: str) -> int:
    enc = _get_tokenizer()
    if enc:
        return len(enc.encode(text, disallowed_special=()))
    return len(text.split())


# ---------------------------------------------------------------------------
# Separator sets
# ---------------------------------------------------------------------------

_RECURSIVE_SEPS = [
    "\n\n\n", "\n\n", "\n",
    ". ", "? ", "! ", "; ", ", ", " ", "",
]

_MARKDOWN_SEPS = [
    "\n# ", "\n## ", "\n### ", "\n#### ", "\n##### ", "\n###### ",
    "\n---", "\n***", "\n```",
    "\n\n\n", "\n\n", "\n",
    ". ", "? ", "! ", "; ", ", ", " ", "",
]


def _detect_seps(text: str) -> List[str]:
    if re.search(r'^#{1,6}\s', text, re.MULTILINE):
        return _MARKDOWN_SEPS
    return _RECURSIVE_SEPS


# ---------------------------------------------------------------------------
# Recursive splitter (token-aware)
# ---------------------------------------------------------------------------

def _recursive_split(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    separators: List[str],
) -> List[str]:
    if not text.strip():
        return []
    if _count_tokens(text) <= max_tokens:
        return [text]

    chosen = ""
    for sep in separators:
        if sep == "" or sep in text:
            chosen = sep
            break

    if chosen == "":
        enc = _get_tokenizer()
        if enc:
            tokens = enc.encode(text, disallowed_special=())
            chunks = []
            for i in range(0, len(tokens), max_tokens - overlap_tokens):
                chunk_tokens = tokens[i:i + max_tokens]
                chunks.append(enc.decode(chunk_tokens))
            return chunks
        words = text.split()
        return [
            " ".join(words[i:i + max_tokens])
            for i in range(0, len(words), max_tokens - overlap_tokens)
        ]

    parts = text.split(chosen)
    remaining = separators[separators.index(chosen) + 1:] if chosen in separators else separators

    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    for part in parts:
        pt = _count_tokens(part)
        sep_t = _count_tokens(chosen) if current else 0
        if current_tokens + sep_t + pt > max_tokens and current:
            merged = chosen.join(current)
            if _count_tokens(merged) <= max_tokens:
                chunks.append(merged)
            else:
                chunks.extend(_recursive_split(merged, max_tokens, overlap_tokens, remaining))
            # Overlap
            overlap: List[str] = []
            ot = 0
            for p in reversed(current):
                pk = _count_tokens(p)
                if ot + pk > overlap_tokens:
                    break
                overlap.insert(0, p)
                ot += pk
            current = overlap
            current_tokens = ot
        current.append(part)
        current_tokens += pt + (sep_t if len(current) > 1 else 0)

    if current:
        merged = chosen.join(current)
        if _count_tokens(merged) <= max_tokens:
            chunks.append(merged)
        else:
            chunks.extend(_recursive_split(merged, max_tokens, overlap_tokens, remaining))

    return chunks


# ---------------------------------------------------------------------------
# Semantic splitter
# ---------------------------------------------------------------------------

def _semantic_split(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    embed_fn: Optional[Callable],
    breakpoint_threshold: float = 0.3,
    window_size: int = 3,
) -> List[str]:
    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if len(sentences) <= window_size * 2 or embed_fn is None:
        return _recursive_split(text, max_tokens, overlap_tokens, _detect_seps(text))

    windows = [
        " ".join(sentences[max(0, i - window_size // 2): i + window_size // 2 + 1])
        for i in range(len(sentences))
    ]
    try:
        embeddings = embed_fn(windows)
    except Exception:
        return _recursive_split(text, max_tokens, overlap_tokens, _detect_seps(text))

    def _cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    sims = [_cosine(embeddings[i], embeddings[i + 1]) for i in range(len(embeddings) - 1)]
    if not sims:
        return _recursive_split(text, max_tokens, overlap_tokens, _detect_seps(text))

    mean_s = sum(sims) / len(sims)
    std_s = (sum((s - mean_s) ** 2 for s in sims) / len(sims)) ** 0.5
    threshold = mean_s - breakpoint_threshold * std_s

    bps = [0]
    for i, s in enumerate(sims):
        if s < threshold:
            bps.append(i + 1)
    bps.append(len(sentences))

    raw_chunks = [
        " ".join(sentences[bps[i]:bps[i + 1]])
        for i in range(len(bps) - 1)
        if " ".join(sentences[bps[i]:bps[i + 1]]).strip()
    ]

    final: List[str] = []
    for chunk in raw_chunks:
        if _count_tokens(chunk) <= max_tokens:
            final.append(chunk)
        else:
            final.extend(_recursive_split(chunk, max_tokens, overlap_tokens, _RECURSIVE_SEPS))
    return final


# ---------------------------------------------------------------------------
# CSV-aware chunker (row-group with header context)
# ---------------------------------------------------------------------------

def _csv_split(
    text: str,
    rows_per_chunk: int = 20,
) -> List[str]:
    reader = csv.reader(io.StringIO(text))
    all_rows = list(reader)
    if not all_rows:
        return [text]

    headers = all_rows[0]
    header_str = " | ".join(headers)
    data_rows = all_rows[1:]

    if not data_rows:
        return [header_str]

    chunks: List[str] = []
    for i in range(0, len(data_rows), rows_per_chunk):
        group = data_rows[i: i + rows_per_chunk]
        lines = [header_str]
        for row in group:
            row_str = " | ".join(
                f"{h}: {v}" for h, v in zip(headers, row) if v.strip()
            )
            if row_str.strip():
                lines.append(row_str)
        if len(lines) > 1:
            chunks.append("\n".join(lines))

    return chunks or [header_str]


# ---------------------------------------------------------------------------
# Parent-child builder
# ---------------------------------------------------------------------------

def _build_parent_child(
    text: str,
    source_label: str,
    child_texts: List[str],
    parent_chunk_size_tokens: int,
    source_doc_id: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Build interleaved parent + child chunk list.

    Parents are larger context windows. Children are the small search chunks.
    Each child carries a `parent_id` for post-retrieval context expansion.
    """
    result: List[Dict[str, Any]] = []
    base_meta = dict(extra_metadata or {})

    parent_texts = _recursive_split(text, parent_chunk_size_tokens, 0, _detect_seps(text))

    parent_ids: List[str] = []
    parent_ranges: List[tuple] = []
    offset = 0
    for pi, ptxt in enumerate(parent_texts):
        pid = f"{source_doc_id}_parent_{pi}"
        parent_ids.append(pid)
        start = text.find(ptxt, offset)
        if start < 0:
            start = offset
        end = start + len(ptxt)
        parent_ranges.append((start, end))
        offset = end

        result.append({
            "id": pid,
            "text": ptxt,
            "metadata": {
                **base_meta,
                "source_doc_id": source_doc_id,
                "chunk_index": pi,
                "source_name": source_label,
                "chunk_type": "parent",
                "parent_id": pid,
                "child_count": 0,
                "is_deleted": False,
                "version": base_meta.get("version", 1),
            },
        })

    child_offset = 0
    for ci, ctxt in enumerate(child_texts):
        child_start = text.find(ctxt, child_offset)
        if child_start < 0:
            child_start = child_offset
        child_mid = child_start + len(ctxt) // 2

        parent_idx = 0
        for pi, (ps, pe) in enumerate(parent_ranges):
            if ps <= child_mid < pe:
                parent_idx = pi
                break

        pid = parent_ids[parent_idx] if parent_idx < len(parent_ids) else parent_ids[-1]
        cid = f"{source_doc_id}_child_{ci}"

        result.append({
            "id": cid,
            "text": ctxt,
            "metadata": {
                **base_meta,
                "source_doc_id": source_doc_id,
                "chunk_index": ci,
                "source_name": source_label,
                "chunk_type": "child",
                "parent_id": pid,
                "is_deleted": False,
                "version": base_meta.get("version", 1),
            },
        })

        # Update parent child_count
        for r in result:
            if r.get("id") == pid and r["metadata"].get("chunk_type") == "parent":
                r["metadata"]["child_count"] = r["metadata"].get("child_count", 0) + 1
                break

        child_offset = child_start + len(ctxt)

    return result


# ---------------------------------------------------------------------------
# Legacy line chunker (backward compat)
# ---------------------------------------------------------------------------

def _line_chunk(text: str, chunk_size_chars: int = 4096, source_label: str = "") -> List[Dict[str, Any]]:
    source_doc_id = str(uuid.uuid4())
    lines = text.splitlines()
    chunks: List[Dict[str, Any]] = []
    buf: List[str] = []
    buf_len = 0
    idx = 0

    def flush():
        nonlocal buf, buf_len, idx
        if buf:
            chunks.append({
                "id": f"{source_doc_id}_child_{idx}",
                "text": "\n".join(buf),
                "metadata": {
                    "source_doc_id": source_doc_id,
                    "chunk_index": idx,
                    "source_name": source_label,
                    "chunk_type": "child",
                    "is_deleted": False,
                    "version": 1,
                },
            })
            idx += 1
            buf.clear()
            buf_len = 0

    for line in lines:
        ll = len(line)
        if buf_len + ll + 1 > chunk_size_chars:
            flush()
        buf.append(line)
        buf_len += ll + 1
    flush()
    return chunks


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def chunk_document(
    text: str,
    *,
    strategy: str = "recursive",
    chunk_size_tokens: int = 512,
    chunk_overlap_tokens: int = 64,
    enable_parent_child: bool = True,
    parent_chunk_size_tokens: int = 2048,
    csv_rows_per_chunk: int = 20,
    source_label: str = "",
    embed_fn: Optional[Callable] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
    is_csv: bool = False,
) -> List[Dict[str, Any]]:
    """Chunk a document into a list of chunk dicts.

    Each chunk dict has keys: id, text, metadata.
    metadata always contains: source_doc_id, chunk_index, source_name,
    chunk_type ('child' or 'parent'), is_deleted, version.
    """
    if not text.strip():
        return []

    source_doc_id = extra_metadata.get("source_doc_id", str(uuid.uuid4())) if extra_metadata else str(uuid.uuid4())

    # CSV path
    if is_csv or strategy == "csv":
        child_texts = _csv_split(text, rows_per_chunk=csv_rows_per_chunk)
    elif strategy == "semantic" and embed_fn is not None:
        child_texts = _semantic_split(text, chunk_size_tokens, chunk_overlap_tokens, embed_fn)
    elif strategy == "line":
        return _line_chunk(text, chunk_size_chars=chunk_size_tokens * 5, source_label=source_label)
    else:
        child_texts = _recursive_split(text, chunk_size_tokens, chunk_overlap_tokens, _detect_seps(text))

    if not child_texts:
        return []

    if enable_parent_child and len(child_texts) > 1:
        return _build_parent_child(
            text=text,
            source_label=source_label,
            child_texts=child_texts,
            parent_chunk_size_tokens=parent_chunk_size_tokens,
            source_doc_id=source_doc_id,
            extra_metadata=extra_metadata,
        )

    # Child-only
    base_meta = dict(extra_metadata or {})
    return [
        {
            "id": f"{source_doc_id}_child_{ci}",
            "text": ctxt,
            "metadata": {
                **base_meta,
                "source_doc_id": source_doc_id,
                "chunk_index": ci,
                "source_name": source_label,
                "chunk_type": "child",
                "is_deleted": False,
                "version": base_meta.get("version", 1),
            },
        }
        for ci, ctxt in enumerate(child_texts)
    ]
