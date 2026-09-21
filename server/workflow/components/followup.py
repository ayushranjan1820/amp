"""Follow-up detection — determine if an agent response is asking the user for input."""

import logging
from typing import List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------

DIRECT_ASK_PATTERNS: tuple = (
    "could you please provide",
    "please provide me with",
    "i need more information about",
    "can you specify",
    "could you clarify",
    "please share the",
    "i need the following information",
    "can you provide me with",
    "please confirm the",
    "i need you to provide",
    "before i can proceed",
    "to proceed, i need",
    "i require the following",
    "please let me know",
)

INFORMATIONAL_MARKERS: tuple = (
    "## ", "### ", "**key takeaways", "**key findings",
    "sources:", "references:", "[http", "in conclusion",
    "## summary", "## conclusion",
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def needs_followup(response_text: str) -> bool:
    """Check whether an agent response is asking the user for more information."""
    if not response_text or len(response_text) < 20:
        return False

    lower = response_text.lower().strip()

    if len(response_text) > 1500:
        return False

    if not any(pat in lower for pat in DIRECT_ASK_PATTERNS):
        return False

    last_lines = "\n".join(response_text.strip().split("\n")[-5:]).lower()
    if "?" not in last_lines:
        return False

    if any(m in lower for m in INFORMATIONAL_MARKERS) and len(response_text) > 500:
        return False

    return True


async def extract_followup_question(response_text: str, agent_name: str) -> str:
    """Extract the specific question an agent is asking the user."""
    try:
        from api import _llm_call_async

        prompt = (
            "The following is a response from an AI agent that is asking the user for more information. "
            "Extract ONLY the specific question or request being asked of the user. "
            "Return a single concise sentence (the question itself). "
            "Do NOT include any of the agent's analysis, findings, or explanations.\n\n"
            f"Agent response:\n{response_text[-800:]}\n\n"
            "Extracted question (one line):"
        )
        question = await _llm_call_async(prompt, max_tokens=150, temperature=0.1)
        question = question.strip().strip('"').strip("'")
        if question and len(question) < 500:
            return question
    except Exception:
        logger.debug("LLM-based follow-up extraction failed; falling back to heuristic")

    for line in reversed(response_text.strip().split("\n")):
        if "?" in line and len(line.strip()) > 10:
            return line.strip()
    return f"{agent_name} needs additional information to proceed."
