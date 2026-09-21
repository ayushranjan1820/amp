"""
Response Formatter Module for Router Agent
Formats and normalizes agent responses.
"""

from typing import Any, List, Dict


class ResponseFormatter:
    """Formats and normalizes responses from various agents."""
    
    @staticmethod
    def normalize_thinking_steps(steps: Any) -> List[Dict[str, Any]]:
        """Normalize thinking steps from various agent formats."""
        if not steps or not isinstance(steps, list):
            return []

        normalized = []
        for step in steps:
            if isinstance(step, dict) and "type" in step:
                normalized.append({
                    "type": step.get("type", "thinking"),
                    "content": str(step.get("content", "")),
                    "tool_name": step.get("tool_name"),
                    "tool_input": str(step.get("tool_input", "")) if step.get("tool_input") else None
                })
            elif isinstance(step, (list, tuple)) and len(step) >= 2:
                action = step[0]
                observation = step[1]
                if hasattr(action, 'tool'):
                    normalized.append({
                        "type": "tool_call",
                        "content": f"Using {action.tool}",
                        "tool_name": action.tool,
                        "tool_input": str(action.tool_input) if hasattr(action, 'tool_input') else None
                    })
                    normalized.append({
                        "type": "tool_result",
                        "content": str(observation)[:500],
                        "tool_name": action.tool,
                        "tool_input": None
                    })
        return normalized
