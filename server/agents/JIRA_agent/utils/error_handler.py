"""Error handling utilities for JIRA agent."""
import re

from ..core.logging import log_info, log_error


def handle_parsing_error(error: Exception) -> str:
    """Handle LangChain agent parsing errors gracefully.

    Args:
        error: Exception raised by the agent

    Returns:
        Extracted answer or fallback message
    """
    error_msg = str(error)
    log_error(f"Agent parsing error: {error_msg}", "jira_agent")

    if "Final Answer:" in error_msg:
        match = re.search(r"Final Answer:\s*(.+?)(?:Action:|Observation:|$)", error_msg, re.DOTALL | re.IGNORECASE)
        if match:
            answer = match.group(1).strip()
            log_info(f"Extracted answer from parsing error: {answer[:100]}...", "jira_agent")
            return answer

    if "Parsing LLM output produced both" in error_msg:
        lines = error_msg.split('\n')
        for i, line in enumerate(lines):
            if 'Final Answer:' in line and i + 1 < len(lines):
                answer_line = lines[i].split('Final Answer:')[-1].strip()
                if answer_line:
                    return answer_line
                if i + 1 < len(lines):
                    return lines[i + 1].strip()

    return "I encountered an issue processing the response. Let me try a simpler approach."
