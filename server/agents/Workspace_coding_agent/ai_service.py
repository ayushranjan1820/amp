"""LLM for Workspace context Agent — respects LLM_PROVIDER (same stack as other agents)."""

import os
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc

    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService


class AIService(BaseAIService):
    def __init__(self):
        super().__init__(default_temperature=0.3, default_max_tokens=8192, timeout=180, agent_name="Workspace context Agent")


ai_service = AIService()
