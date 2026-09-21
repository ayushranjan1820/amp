"""Optional LLM refinement between workflow steps (Prompt Harness)."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _format_instructions(output_format: str) -> str:
    fmt = (output_format or "markdown").strip().lower()
    if fmt == "json":
        return (
            "Respond with valid JSON only. Do not wrap in markdown fences unless JSON strings "
            "must contain them. No explanatory prose outside the JSON payload."
        )
    if fmt == "text":
        return "Respond with plain text only (no markdown headings or fenced code blocks)."
    return "Respond using GitHub-flavored Markdown with clear structure where helpful."


def _parse_positive_int_cap(raw: Any) -> Optional[int]:
    """Optional max length / similar caps stored on harness config (int or numeric string)."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    if isinstance(raw, float) and raw.is_integer():
        n = int(raw)
        return n if n > 0 else None
    try:
        s = str(raw).strip()
        if not s:
            return None
        n = int(s)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def _build_harness_prompt(
    *,
    raw_text: str,
    expected: str,
    output_format: str,
    max_output_chars: Optional[int] = None,
) -> str:
    cap_line = ""
    if max_output_chars is not None and max_output_chars > 0:
        cap_line = (
            f"\nHARD CONSTRAINT: The transformed output must be at most {max_output_chars} Unicode "
            "characters (Python len(str)). If the source is longer, compress or summarize until it fits. "
            "If you cannot fit everything, keep the most important facts for the downstream step.\n"
        )
    return (
        "You are a workflow prompt harness. Your task is to transform the upstream agent output "
        "so the next workflow step receives exactly what the author described.\n\n"
        f"Output format: {output_format.upper()}\n"
        f"{_format_instructions(output_format)}"
        f"{cap_line}\n\n"
        "Author specification:\n"
        f"{expected.strip()}\n\n"
        "--- BEGIN UPSTREAM OUTPUT ---\n"
        f"{raw_text.strip()}\n"
        "--- END UPSTREAM OUTPUT ---\n\n"
        "Produce only the transformed content."
    )


async def _call_llm_under_merged_env(prompt: str, merged: Dict[str, str]) -> str:
    """Dispatch to the correct async LLM call based on LLM_PROVIDER in *merged* env."""
    from user_config import apply_user_config
    from agents.local_llm import get_llm_provider, async_local_llm_call, async_ollama_cloud_call
    from agents.llm_continuation import async_call_with_continuation

    ctx = apply_user_config(merged or {})
    ctx.__enter__()
    try:
        prov = get_llm_provider()

        if prov == "local_llm":
            return await async_local_llm_call(prompt, temperature=0.2, timeout=120.0)

        if prov == "ollama_cloud":
            return await async_ollama_cloud_call(prompt, temperature=0.2, timeout=120.0)

        # pwc_genai (default)
        endpoint_url = os.getenv(
            "PWC_GENAI_ENDPOINT_URL",
            "https://genai-sharedservice-americas.pwc.com/completions",
        )
        api_key = os.getenv("PWC_GENAI_API_KEY") or os.getenv("GEMINI_API_KEY") or ""
        bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN")

        if not api_key and not bearer_token:
            raise ValueError("PwC GenAI API key missing under merged harness configuration.")

        headers: Dict[str, str] = {
            "accept": "application/json",
            "Content-Type": "application/json",
        }
        if api_key:
            headers["API-Key"] = api_key
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        payload = {
            "model": os.getenv("PREMIUM_MODEL", ""),
            "prompt": prompt,
            "temperature": 0.2,
            "top_p": 1,
            "max_tokens": 8192,
        }

        return await async_call_with_continuation(
            endpoint_url=endpoint_url,
            headers=headers,
            request_body=payload,
            original_prompt=prompt,
            timeout=120.0,
        )
    finally:
        ctx.__exit__(None, None, None)


async def apply_edge_prompt_harness(
    *,
    raw_text: str,
    harness: Optional[Dict[str, Any]],
    consuming_agent_id: str,
    agent_user_configs: Optional[Dict[str, Dict[str, str]]],
) -> str:
    """Return LLM-shaped text or *raw_text* when harness inactive / on failure."""
    if not harness or not isinstance(harness, dict):
        return raw_text
    expected = (harness.get("expected_output_description") or "").strip()
    if not expected:
        return raw_text

    output_format = (harness.get("output_format") or "markdown").strip().lower()
    if output_format not in {"markdown", "json", "text"}:
        output_format = "markdown"

    max_output_chars = _parse_positive_int_cap(
        harness.get("max_output_chars") if harness.get("max_output_chars") is not None else harness.get("max_chars")
    )

    from user_config import merge_configs_for_agent_id

    base = merge_configs_for_agent_id(consuming_agent_id, (agent_user_configs or {}).get(consuming_agent_id))
    overlay = harness.get("default_config") or {}
    overlay_dict = overlay if isinstance(overlay, dict) else {}
    merged: Dict[str, str] = {**(base or {})}
    for k, v in overlay_dict.items():
        if v is None:
            continue
        merged[str(k)] = v if isinstance(v, str) else str(v)

    prompt = _build_harness_prompt(
        raw_text=raw_text,
        expected=expected,
        output_format=output_format,
        max_output_chars=max_output_chars,
    )

    try:
        text = await _call_llm_under_merged_env(prompt, merged)
    except Exception:
        logger.exception(
            "Prompt harness LLM failed; using raw upstream output (consumer=%s)",
            consuming_agent_id,
        )
        return raw_text

    if output_format == "json":
        from .dispatch import _strip_code_fences
        text = _strip_code_fences(text or "")
    text = text or ""
    if max_output_chars is not None and len(text) > max_output_chars:
        text = text[:max_output_chars]
    return text or raw_text


async def build_dep_response_overrides(
    step: Dict[str, Any],
    results: Dict[int, Dict],
    agent_user_configs: Optional[Dict[str, Dict[str, str]]],
) -> Dict[int, str]:
    """Map dependency step numbers to text injected into query resolution / KB assembly."""
    from .step_helpers import coerce_workflow_dep_step

    overrides: Dict[int, str] = {}
    agent_id = step.get("agent_id") or ""
    for raw_dep in step.get("depends_on") or []:
        dep = coerce_workflow_dep_step(raw_dep)
        if dep is None or dep not in results:
            continue
        raw = results[dep].get("response", str(results[dep]))
        harness = (step.get("prompt_harness") or {}).get(str(dep))
        overrides[dep] = await apply_edge_prompt_harness(
            raw_text=str(raw),
            harness=harness if isinstance(harness, dict) else None,
            consuming_agent_id=str(agent_id),
            agent_user_configs=agent_user_configs,
        )
    return overrides
