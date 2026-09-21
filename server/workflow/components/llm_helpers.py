"""LLM helpers — LLM call wrapper, workflow generation, and Mermaid diagram."""

import json
import os
import re
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from .catalog import AGENT_REGISTRY
from .dispatch import _strip_code_fences

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

_PWC_ENV_FALLBACK: Optional[Dict[str, str]] = None


def _pwc_fallback_from_dotenv() -> Dict[str, str]:
    """PwC GenAI credentials read straight from ``server/.env``.

    The API server strips these from the process environment at startup
    (``user_config.load_dotenv_then_scrub_pwc``) and normally re-injects them
    per request from an agent's own config. The workflow planner has no
    per-agent config to inject them from, so it falls back to the same
    server/.env values api.py keeps as ``_SERVER_GLOBAL_CHAT_CONFIG``.
    """
    global _PWC_ENV_FALLBACK
    if _PWC_ENV_FALLBACK is None:
        from dotenv import dotenv_values

        env_path = Path(__file__).resolve().parents[2] / ".env"
        values = dotenv_values(env_path) if env_path.exists() else {}
        _PWC_ENV_FALLBACK = {
            k: v for k, v in values.items()
            if k in ("PWC_GENAI_API_KEY", "PWC_GENAI_BEARER_TOKEN", "PWC_GENAI_ENDPOINT_URL") and v
        }
    return _PWC_ENV_FALLBACK


async def call_llm(prompt: str, temperature: float = 0.2, max_tokens: int = 4096) -> str:
    """Call the configured LLM endpoint with automatic continuation handling."""
    from agents.llm_continuation import async_call_with_continuation
    try:
        from langfuse_tracer import set_langfuse_context
        set_langfuse_context(agent_name="Workflow Planner")
    except Exception:
        pass

    api_key = os.getenv("PWC_GENAI_API_KEY")
    bearer_token = os.getenv("PWC_GENAI_BEARER_TOKEN")
    endpoint_url = os.getenv("PWC_GENAI_ENDPOINT_URL")

    if not api_key:
        fallback = _pwc_fallback_from_dotenv()
        api_key = fallback.get("PWC_GENAI_API_KEY")
        bearer_token = bearer_token or fallback.get("PWC_GENAI_BEARER_TOKEN")
        endpoint_url = endpoint_url or fallback.get("PWC_GENAI_ENDPOINT_URL")

    api_key = api_key or os.getenv("GEMINI_API_KEY")
    endpoint_url = endpoint_url or "https://genai-sharedservice-americas.pwc.com/completions"

    if not api_key:
        raise ValueError("LLM service not configured. Set PWC_GENAI_API_KEY or GEMINI_API_KEY.")

    headers = {
        "accept": "application/json",
        "API-Key": api_key,
        "Content-Type": "application/json",
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    payload = {
        "model": "",
        "prompt": prompt,
        "temperature": temperature,
        "top_p": 1,
        "max_tokens": max_tokens,
    }

    return await async_call_with_continuation(
        endpoint_url=endpoint_url,
        headers=headers,
        request_body=payload,
        original_prompt=prompt,
        timeout=60.0,
    )


# ---------------------------------------------------------------------------
# Agent description builder
# ---------------------------------------------------------------------------


def _build_agent_descriptions() -> str:
    """Return a newline-delimited list of ``- agent_id: Agent Name`` strings."""
    return "\n".join(
        f"- {agent_id}: {info['name']}" for agent_id, info in AGENT_REGISTRY.items()
    )


# ---------------------------------------------------------------------------
# Workflow generation
# ---------------------------------------------------------------------------


async def generate_workflow(instruction: str) -> Dict[str, Any]:
    """Use the LLM to turn a natural-language instruction into a workflow definition."""
    agent_list = _build_agent_descriptions()

    prompt = f"""You are a workflow planner for a multi-agent AI platform. Given a user's natural language instruction, break it down into a workflow of sequential or parallel agent steps.

Available agents:
{agent_list}

CRITICAL RULES:
1. Each step must use exactly one agent from the list above.
2. Steps can depend on previous steps (sequential) or run independently (parallel).
3. When one step's output should feed into another step, define an "input_mapping" that describes which previous step's output to use and how.
4. **MANDATORY**: If a step has "depends_on" set to another step, the "query" field MUST include the placeholder {{{{step_N_output}}}} (where N is the dependency step number). This placeholder will be replaced at runtime with the actual output from that step. Without this placeholder, the dependent step will NOT receive any data from the previous step.
5. For email_agent: the query should include the recipient email and what to send. If sending output from another step, use the placeholder.
6. **DATA FLOW**: Every step that depends on a previous step MUST reference {{{{step_N_output}}}} in its query to receive the prior step's output. Simply setting "depends_on" only controls execution order — it does NOT automatically pass data. The placeholder is the ONLY mechanism for passing data between steps.

Respond with ONLY valid JSON (no markdown, no code blocks) in this exact format:
{{
  "name": "Short workflow name",
  "steps": [
    {{
      "step_number": 1,
      "agent_id": "agent_id_from_list",
      "label": "Short human-readable label for this step",
      "query": "The specific instruction/query to send to this agent",
      "depends_on": [],
      "input_mapping": null
    }},
    {{
      "step_number": 2,
      "agent_id": "another_agent_id",
      "label": "Another step label",
      "query": "Based on the following research findings, do something:\\n\\n{{{{step_1_output}}}}",
      "depends_on": [1],
      "input_mapping": {{
        "from_step": 1,
        "description": "Use the research output as input"
      }}
    }}
  ]
}}

User instruction: {instruction}

Generate the workflow JSON:"""

    response = await call_llm(prompt, temperature=0.1, max_tokens=4096)
    cleaned = _strip_code_fences(response)
    workflow_def = json.loads(cleaned)

    # Ensure every dependent step actually references its dependency outputs
    for step in workflow_def.get("steps", []):
        agent_id = step.get("agent_id", "")
        step["agent_name"] = AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id)

        deps = step.get("depends_on", [])
        query = step.get("query", "")
        if deps:
            existing_refs = {int(m) for m in re.findall(r'\{\{step_(\d+)_output\}\}', query)}
            missing_deps = [d for d in deps if d not in existing_refs]
            if missing_deps:
                dep_refs = "\n".join(
                    f"Output from step {d}:\n{{{{step_{d}_output}}}}" for d in missing_deps
                )
                step["query"] = f"{query}\n\nUse the following information from previous steps:\n{dep_refs}"

    workflow_def["mermaid"] = generate_mermaid(workflow_def)
    workflow_def["flow_graph"] = build_workflow_flow_graph(workflow_def)
    return workflow_def


# ---------------------------------------------------------------------------
# Mermaid diagram generation
# ---------------------------------------------------------------------------


def generate_mermaid(workflow_def: Dict[str, Any]) -> str:
    """Generate a Mermaid graph-TD diagram from a workflow definition."""
    steps = workflow_def.get("steps", [])
    if not steps:
        return "graph TD\n  A[No steps defined]"

    lines = ["graph TD"]

    for step in steps:
        num = step["step_number"]
        label = step.get("label", f"Step {num}")
        agent_id = step["agent_id"]
        agent_name = AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id)
        safe_label = label.replace('"', "'").replace("[", "(").replace("]", ")")
        lines.append(f'  S{num}["{num}. {safe_label}<br/><i>{agent_name}</i>"]')

    for step in steps:
        num = step["step_number"]
        deps = step.get("depends_on", [])
        if not deps:
            continue
        for dep in deps:
            mapping = step.get("input_mapping") or {}
            desc = mapping.get(f"description_{dep}", "")
            if not desc and str(mapping.get("from_step")) == str(dep):
                desc = mapping.get("description", "")
            if desc:
                safe_edge = desc.replace('"', "'")[:40]
                lines.append(f'  S{dep} -->|"{safe_edge}"| S{num}')
            else:
                lines.append(f'  S{dep} --> S{num}')

    lines.append("")
    lines.append("  classDef default fill:#1e293b,stroke:#f97316,stroke-width:2px,color:#fff")
    lines.append("  classDef active fill:#f97316,stroke:#fff,stroke-width:2px,color:#fff")

    return "\n".join(lines)


def build_workflow_flow_graph(workflow_def: Dict[str, Any]) -> Dict[str, Any]:
    """Structured DAG for API clients; UI enriches with logos and live step status."""
    steps = workflow_def.get("steps", [])
    nodes: list[Dict[str, Any]] = []
    for step in steps:
        num = step["step_number"]
        agent_id = step["agent_id"]
        agent_name = step.get("agent_name") or AGENT_REGISTRY.get(agent_id, {}).get("name", agent_id)
        title = step.get("label", f"Step {num}")
        nodes.append(
            {
                "id": f"S{num}",
                "step_number": num,
                "title": title,
                "agent_id": agent_id,
                "agent_name": agent_name,
            }
        )

    edges: list[Dict[str, Any]] = []
    for step in steps:
        num = step["step_number"]
        for dep in step.get("depends_on", []):
            mapping = step.get("input_mapping") or {}
            desc = mapping.get(f"description_{dep}", "")
            if not desc and str(mapping.get("from_step")) == str(dep):
                desc = mapping.get("description", "")
            safe = (desc or "").strip()[:56] or None
            edge: Dict[str, Any] = {"from": dep, "to": num}
            if safe:
                edge["label"] = safe
            edges.append(edge)

    return {"nodes": nodes, "edges": edges}
