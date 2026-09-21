"""AI service for ETL Agent — delegates to shared BaseAIService."""
import os
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService


class ETLAIService(BaseAIService):
    def __init__(self):
        model = os.getenv("ETL_AGENT_MODEL", "").strip()
        super().__init__(
            default_model=model,
            default_temperature=0.1,
            default_max_tokens=8192,
            timeout=180,
            agent_name="ETL Agent",
        )


ai_service = ETLAIService()
