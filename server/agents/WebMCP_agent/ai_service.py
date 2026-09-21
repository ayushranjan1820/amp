"""LLM service for the WebMCP agent."""

import logging
import os
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc

    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService

logger = logging.getLogger(__name__)


class WebMcpAIService(BaseAIService):
    def __init__(self):
        model = os.getenv("WEBMCP_AGENT_MODEL", "")
        super().__init__(
            default_model=model,
            default_temperature=0.2,
            default_max_tokens=4096,
            timeout=180,
            agent_name="WebMCP Agent",
        )


webmcp_ai_service = WebMcpAIService()
