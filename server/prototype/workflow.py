"""Hardcoded workflow generate/execute responses."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict

from fastapi.responses import StreamingResponse


def prototype_workflow_generate(instruction: str) -> Dict[str, Any]:
    return {
        "name": "Automated Research Pipeline",
        "instruction": instruction,
        "definition": {
            "nodes": [
                {"id": "step_1", "agent_id": "web_search_agent", "label": "Web Search", "depends_on": []},
                {"id": "step_2", "agent_id": "company_research", "label": "Company Research", "depends_on": ["step_1"]},
                {"id": "step_3", "agent_id": "document_formatter", "label": "Format Report", "depends_on": ["step_2"]},
            ],
            "batches": [["step_1"], ["step_2"], ["step_3"]],
        },
        "mermaid_code": (
            "flowchart LR\n"
            "  A[Web Search] --> B[Company Research]\n"
            "  B --> C[Format Report]"
        ),
    }


def prototype_workflow_execute(definition: Dict[str, Any]) -> Dict[str, Any]:
    execution_id = str(uuid.uuid4())
    steps = []
    for node in definition.get("nodes", []):
        steps.append({
            "step_id": node.get("id"),
            "agent_id": node.get("agent_id"),
            "status": "completed",
            "output": f"Completed step: {node.get('label', node.get('agent_id'))}",
        })
    return {
        "execution_id": execution_id,
        "status": "completed",
        "steps": steps,
        "final_output": "Workflow completed successfully. All agents executed in sequence.",
    }


async def prototype_workflow_execute_stream(definition: Dict[str, Any]):
    execution_id = str(uuid.uuid4())
    nodes = definition.get("nodes", [])

    async def event_generator():
        yield ": " + " " * 2048 + "\n\n"
        yield f"data: {json.dumps({'event': 'execution_started', 'data': {'execution_id': execution_id}})}\n\n"
        await asyncio.sleep(0.1)

        for i, node in enumerate(nodes):
            step_id = node.get("id", f"step_{i}")
            agent_id = node.get("agent_id", "basic_agent")
            label = node.get("label", agent_id)
            yield f"data: {json.dumps({'event': 'step_started', 'data': {'step_id': step_id, 'agent_id': agent_id, 'index': i}})}\n\n"
            await asyncio.sleep(0.3)
            yield f"data: {json.dumps({'event': 'step_thinking', 'data': {'step_id': step_id, 'content': f'Running {label}…'}})}\n\n"
            await asyncio.sleep(0.2)
            yield f"data: {json.dumps({'event': 'step_completed', 'data': {'step_id': step_id, 'agent_id': agent_id, 'output': f'Step {label} completed successfully.'}})}\n\n"
            await asyncio.sleep(0.15)

        yield f"data: {json.dumps({'event': 'execution_completed', 'data': {'execution_id': execution_id, 'status': 'completed', 'final_output': 'All workflow steps finished.'}})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
