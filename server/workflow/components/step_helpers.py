"""Step helpers — query dependency resolution, KB injection, result normalisation."""

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def coerce_workflow_dep_step(dep: Any) -> Optional[int]:
    """Normalize a single ``depends_on`` entry from workflow JSON (int or numeric string)."""
    if dep is None or isinstance(dep, bool):
        return None
    if isinstance(dep, int):
        return dep
    if isinstance(dep, float) and dep.is_integer():
        try:
            return int(dep)
        except (OverflowError, ValueError):
            return None
    try:
        s = str(dep).strip()
        if not s:
            return None
        return int(s)
    except (TypeError, ValueError):
        return None


def normalize_depends_on(raw: Any) -> List[int]:
    """Coerce ``depends_on`` arrays so they align with integer ``results`` / ``completed`` keys."""
    if not isinstance(raw, (list, tuple)):
        return []
    out: List[int] = []
    for item in raw:
        n = coerce_workflow_dep_step(item)
        if n is not None:
            out.append(n)
    return out


# ---------------------------------------------------------------------------
# Per-step uploads (workflow builder → attach files with prompt)
# ---------------------------------------------------------------------------

_WORKFLOW_ATTACHMENT_MAX_CHARS = int(os.getenv("WORKFLOW_ATTACHMENT_MAX_CHARS", "120000"))

_SINGLE_NATIVE_FILE_UPLOAD_AGENTS = frozenset(
    {"document_formatter", "bpmn_generator", "coder_agent", "ppt_generator"}
)
_CHAT_INGEST_UPLOAD_AGENTS = frozenset({"mongodb_rag", "sql_db"})
_UPLOAD_LIST_ONLY_AGENT = frozenset({"company_solution_advisor"})


def _flatten_one_upload(raw: Any) -> Optional[Dict[str, str]]:
    if isinstance(raw, dict):
        fc = raw.get("file_content")
        ft = (raw.get("file_type") or "").strip()
        if not fc or not ft:
            return None
        return {
            "file_content": fc,
            "file_type": ft.lower().lstrip("."),
            "file_name": (raw.get("file_name") or "") or "",
        }
    fc = getattr(raw, "file_content", None)
    ft = (getattr(raw, "file_type", "") or "").strip()
    if fc is not None and getattr(raw, "model_dump", None):
        try:
            d = raw.model_dump()
            if isinstance(d, dict) and d.get("file_content") and d.get("file_type"):
                return {
                    "file_content": str(d["file_content"]),
                    "file_type": str(d["file_type"]).lower().lstrip("."),
                    "file_name": str(d.get("file_name") or "") or "",
                }
        except Exception:
            pass
    if hasattr(raw, "file_content") and hasattr(raw, "file_type"):
        fc2 = getattr(raw, "file_content", None)
        ft2 = (getattr(raw, "file_type", "") or "").strip()
        if fc2 and ft2:
            return {
                "file_content": fc2 if isinstance(fc2, str) else str(fc2),
                "file_type": ft2.lower().lstrip("."),
                "file_name": str(getattr(raw, "file_name", "") or "") or "",
            }
    return None


def _normalized_step_upload_items(step: Dict[str, Any]) -> List[Dict[str, str]]:
    raw_list = step.get("uploaded_files")
    if not raw_list:
        return []
    out: List[Dict[str, str]] = []
    for item in raw_list:
        u = _flatten_one_upload(item)
        if u:
            out.append(u)
    return out


def _append_extracted_documents_to_prompt(
    query: str,
    uploads: List[Dict[str, str]],
    *,
    prefix: str = "Uploaded file content",
) -> str:
    if not uploads:
        return query

    chunks: List[str] = []
    try:
        from agents.Document_formatter_agent.tools.file_extractor import extract_file_content
    except Exception as imp_err:
        logger.warning("Attachment extraction unavailable: %s", imp_err)
        return (
            query.rstrip()
            + "\n\n---\nWorkflow attachments are attached but extraction dependencies "
              "are unavailable in this deployment.\n---\n"
        )

    for f in uploads:
        name = (f.get("file_name") or "").strip() or "(unnamed)"
        ext = (f.get("file_type") or "").lower().lstrip(".")
        fc = f.get("file_content") or ""
        try:
            text, ok, _images = extract_file_content(fc, ext, name)
        except Exception as ex:
            text, ok = f"Attachment extraction failed: {ex}", False
        snippet = (
            text
            if ok
            else f"[Attachment could not be read as structured text ({ext} — {text})]"
        ).strip()
        chunks.append(f"### {name} (.{ext})\n{snippet}")

    sep = "\n\n---\n\n"
    intro = (
        f"\n\n---\n{prefix}\n"
        + "Use the excerpts below together with your instructions.\n---\n"
    )
    body = sep.join(chunks)
    appendix = intro + body + "\n---\n"
    max_append = max(4096, int(_WORKFLOW_ATTACHMENT_MAX_CHARS))
    appendix_bytes = appendix.encode("utf-8")
    if len(appendix_bytes) > max_append:
        clipped = appendix_bytes[: max_append - 64].decode("utf-8", errors="ignore")
        appendix = clipped + "\n… [truncated — raise WORKFLOW_ATTACHMENT_MAX_CHARS]\n---\n"

    return query.rstrip() + appendix


def merge_attachments_into_agent_dispatch(
    agent_id: str,
    resolved_query: str,
    step: Dict[str, Any],
    dispatch_extra_out: Dict[str, Any],
) -> str:
    """Mutate ``dispatch_extra_out`` with native file kwargs when applicable; augment *resolved_query*

    otherwise (or additionally for leftover files after forwarding the first to a single-file agent).
    """
    items = _normalized_step_upload_items(step)
    if not items:
        return resolved_query

    if agent_id in _UPLOAD_LIST_ONLY_AGENT:
        existing_raw = dispatch_extra_out.get("uploaded_files") or []
        flattened: List[Dict[str, str]] = []
        for x in existing_raw:
            u = _flatten_one_upload(x)
            if u:
                flattened.append(u)
        flattened.extend(items)
        dispatch_extra_out["uploaded_files"] = flattened
        return resolved_query

    if agent_id in _SINGLE_NATIVE_FILE_UPLOAD_AGENTS:
        dispatch_extra_out["file_content"] = items[0]["file_content"]
        dispatch_extra_out["file_type"] = items[0]["file_type"]
        dispatch_extra_out["file_name"] = items[0].get("file_name") or ""
        if len(items) > 1:
            return _append_extracted_documents_to_prompt(
                resolved_query,
                items[1:],
                prefix="Additional uploaded documents (beyond the primary file)",
            )
        return resolved_query

    if agent_id in _CHAT_INGEST_UPLOAD_AGENTS:
        dispatch_extra_out["file_content"] = items[0]["file_content"]
        dispatch_extra_out["file_type"] = items[0]["file_type"]
        dispatch_extra_out["file_name"] = items[0].get("file_name") or ""
        if len(items) > 1:
            return _append_extracted_documents_to_prompt(
                resolved_query,
                items[1:],
                prefix="Additional uploads (first file triggers ingest separately)",
            )
        return resolved_query

    return _append_extracted_documents_to_prompt(
        resolved_query,
        items,
        prefix="Uploaded file content",
    )


# ---------------------------------------------------------------------------
# Query dependency resolution
# ---------------------------------------------------------------------------


def _resolved_dep_output(
    dep_step: Any,
    results: Dict[int, Dict],
    dep_overrides: Optional[Dict[int, str]],
) -> Optional[str]:
    n = coerce_workflow_dep_step(dep_step)
    if n is None:
        return None
    if dep_overrides is not None and n in dep_overrides:
        return dep_overrides[n]
    if n in results:
        return results[n].get("response", str(results[n]))
    return None


def _resolve_query_dependencies(
    query: str,
    step: Dict[str, Any],
    results: Dict[int, Dict],
    dep_overrides: Optional[Dict[int, str]] = None,
) -> str:
    """Resolve input mappings and replace ``{{step_N_output}}`` placeholders."""
    # 1. Append input-mapping instructions
    input_mapping = step.get("input_mapping") or {}
    mapping_parts: List[str] = []
    for key, val in input_mapping.items():
        if not val or not str(val).strip():
            continue
        if key.startswith("description_"):
            dep_num = key.replace("description_", "")
            mapping_parts.append(f"Step {dep_num} output instruction: {val.strip()}")
        # elif key == "description":
        #     mapping_parts.append(str(val).strip())
    if mapping_parts:
        query += "\n\n" + "\n".join(mapping_parts)

    # 2. Inject outputs from deps not already referenced by a placeholder
    deps = normalize_depends_on(step.get("depends_on"))
    existing_placeholders = {int(m) for m in re.findall(r'\{\{step_(\d+)_output\}\}', query)}
    for dep in deps:
        if dep in existing_placeholders:
            continue
        dep_response = _resolved_dep_output(dep, results, dep_overrides)
        if dep_response is None:
            continue
        query += (
            f"\n\n=== Output from Step {dep} ===\n"
            f"{dep_response}\n"
            f"=== End of Step {dep} Output ==="
        )

    # 3. Replace all {{step_N_output}} placeholders with actual data
    for match in re.findall(r'\{\{step_(\d+)_output\}\}', query):
        dep_step = int(match)
        dep_output = _resolved_dep_output(dep_step, results, dep_overrides)
        if dep_output is not None:
            query = query.replace(f"{{{{step_{dep_step}_output}}}}", dep_output)

    return query


# ---------------------------------------------------------------------------
# Knowledge-base injection
# ---------------------------------------------------------------------------


def _build_kb_retrieval_query(step: Dict[str, Any], results: Dict[int, Dict]) -> str:
    """Build a focused query string for vector search (step intent), not the full pasted dependency outputs."""
    q = (step.get("query") or "").strip()
    input_mapping = step.get("input_mapping") or {}
    mapping_parts: List[str] = []
    for key, val in input_mapping.items():
        if not val or not str(val).strip():
            continue
        if key.startswith("description_"):
            dep_num = key.replace("description_", "")
            mapping_parts.append(f"Step {dep_num} output instruction: {val.strip()}")
        # elif key == "description":
        #     mapping_parts.append(str(val).strip())
    if mapping_parts:
        q = q + "\n\n" + "\n".join(mapping_parts)

    for match in re.findall(r"\{\{step_(\d+)_output\}\}", q):
        dep_step = int(match)
        q = q.replace(
            f"{{{{step_{dep_step}_output}}}}",
            f"[Output from prior workflow step {dep_step} — full text is in STRICT TASK CONTEXT below]",
        )

    deps = normalize_depends_on(step.get("depends_on"))
    existing_ph = {int(m) for m in re.findall(r"\{\{step_(\d+)_output\}\}", step.get("query") or "")}
    if any(d not in existing_ph and d in results for d in deps):
        q += (
            "\n\n[Additional outputs from prior workflow steps are included in STRICT TASK CONTEXT below; "
            "use them together with any retrieved knowledge.]"
        )

    return q.strip() or (step.get("query") or "").strip() or "workflow task"


def _build_kb_augmented_query(
    full_task_query: str,
    kb_index: dict,
    chunk_lines: List[str],
    kb_note: str = "",
) -> str:
    """Assemble strict context: retrieved KB first, then full task (prompts + prior agent outputs)."""
    src = f"{kb_index['db_name']}.{kb_index['collection']}"
    if chunk_lines:
        kb_body = "\n\n".join(chunk_lines)
        kb_section = (
            f"=== RETRIEVED KNOWLEDGE BASE CONTEXT ===\n"
            f"Source: {src}\n"
            f"Index: {kb_index.get('index_name', 'vector_index')}\n"
            f"Chunks retrieved: {len(chunk_lines)}\n\n"
            f"{kb_body}\n"
            f"=== END OF RETRIEVED KNOWLEDGE BASE CONTEXT ===\n"
        )
    else:
        kb_section = (
            f"=== RETRIEVED KNOWLEDGE BASE CONTEXT ===\n"
            f"Source: {src}\n"
            f"No matching chunks were retrieved for this step.{kb_note}\n"
            f"Do not invent or assume knowledge-base content that was not retrieved.\n"
            f"=== END OF RETRIEVED KNOWLEDGE BASE CONTEXT ===\n"
        )

    return (
        "STRICT CONTEXT CONTRACT — A Knowledge Base index is assigned to this workflow step. "
        "Execution order is fixed: (1) Knowledge was retrieved from the index before this message was built. "
        "(2) You must treat the sections below as mandatory grounding — not optional reference.\n"
        "- For domain facts, policies, definitions, and data that appear in RETRIEVED KNOWLEDGE BASE CONTEXT, "
        "treat those chunks as authoritative; ground statements in them and cite chunk numbers where useful.\n"
        "- STRICT TASK CONTEXT contains this step's instructions (prompts, input-mapping notes) and any outputs "
        "from previous workflow steps. You must follow the task and incorporate prior-step outputs where relevant.\n"
        "- If retrieved chunks and the task conflict on facts, prefer retrieved KB chunks for domain truth; "
        "use prior-step outputs for workflow artifacts (drafts, structured data) they produced.\n"
        "- If no chunks were retrieved, say so briefly if relevant and complete the task using only STRICT TASK CONTEXT.\n\n"
        f"{kb_section}\n"
        f"=== STRICT TASK CONTEXT (prompts + prior agent outputs) ===\n"
        f"{full_task_query}\n"
        f"=== END STRICT TASK CONTEXT ===\n\n"
        "Respond by strictly adhering to the retrieved knowledge (when present) and the strict task context above."
    )


async def _retrieve_kb_context(
    step: Dict[str, Any],
    results: Dict[int, Dict],
    step_num: int,
    dep_overrides: Optional[Dict[int, str]] = None,
) -> Optional[Tuple[str, int]]:
    """When KB is enabled, retrieve from the index first, then return (augmented_query, num_chunks). Otherwise None."""
    kb_index = step.get("kb_index")
    if not kb_index or not kb_index.get("enabled"):
        return None

    full_task_query = _resolve_query_dependencies(step["query"], step, results, dep_overrides=dep_overrides)
    retrieval_query = _build_kb_retrieval_query(step, results)

    chunk_lines: List[str] = []
    kb_note = ""

    try:
        from knowledge_base_manager import KnowledgeBaseManager

        _kb = KnowledgeBaseManager()
        kb_result = _kb.vector_search_query(
            db_name=kb_index["db_name"],
            collection_name=kb_index["collection"],
            query_text=retrieval_query,
            index_name=kb_index.get("index_name", "vector_index"),
            limit=kb_index.get("top_k", 5),
        )
        if kb_result.get("success") and kb_result.get("results"):
            for i, doc in enumerate(kb_result["results"], 1):
                text = doc.get("text") or doc.get("content") or doc.get("chunk_text") or ""
                source = doc.get("source") or doc.get("filename") or doc.get("document_name") or ""
                score = doc.get("score", 0)
                chunk = f"[{i}] {text.strip()}"
                if source:
                    chunk += f" (source: {source}, relevance: {score:.3f})"
                chunk_lines.append(chunk)
            logger.info(
                "[Workflow] Step %d: Injected %d KB chunks from %s.%s",
                step_num,
                len(kb_result["results"]),
                kb_index["db_name"],
                kb_index["collection"],
            )
        else:
            kb_note = " (Vector search returned no results.)"
            logger.info(
                "[Workflow] Step %d: KB enabled but no chunks from %s.%s",
                step_num,
                kb_index["db_name"],
                kb_index["collection"],
            )
    except Exception as kb_err:
        kb_note = f" (Retrieval error: {kb_err})"
        logger.warning("[Workflow] Step %d: KB retrieval failed: %s", step_num, kb_err)

    augmented = _build_kb_augmented_query(full_task_query, kb_index, chunk_lines, kb_note=kb_note)
    return augmented, len(chunk_lines)


# ---------------------------------------------------------------------------
# Result normalisation
# ---------------------------------------------------------------------------


def _coerce_jsonable(val: Any) -> Any:
    """Recursively turn Pydantic models and other non-JSON values into JSON-safe data."""
    if val is None or isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    md = getattr(val, "model_dump", None)
    if callable(md):
        try:
            return _coerce_jsonable(md())
        except Exception:
            pass
    dict_fn = getattr(val, "dict", None)
    if callable(dict_fn) and not isinstance(val, type):
        try:
            return _coerce_jsonable(dict_fn())
        except Exception:
            pass
    if isinstance(val, dict):
        return {str(k): _coerce_jsonable(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_coerce_jsonable(v) for v in val]
    return str(val)


def _normalize_result(result: Any) -> dict:
    """Convert an agent result into a plain ``dict`` safe for ``json.dumps`` and MongoDB."""
    if hasattr(result, "model_dump"):
        result = result.model_dump()
    elif not isinstance(result, dict) and hasattr(result, "__dict__"):
        result = result.__dict__
    if not isinstance(result, dict):
        return {"response": str(result)}
    coerced = _coerce_jsonable(result)
    if not isinstance(coerced, dict):
        return {"response": str(coerced)}
    return coerced
