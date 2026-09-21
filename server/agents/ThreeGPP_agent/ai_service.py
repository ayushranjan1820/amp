"""AI service for 3GPP Agent — delegates to shared BaseAIService (async)."""
import os
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService


class AIService(BaseAIService):
    def __init__(self):
        super().__init__(
            default_temperature=0.3,
            default_max_tokens=8192,
            timeout=120,
            transport="async",
        )

    async def generate(self, prompt: str, temperature: float = 0.3, max_tokens: int = 8192) -> str:
        """Async generation — preserves the original public API."""
        try:
            return await self.call_genai_async(prompt, temperature, max_tokens)
        except Exception as e:
            print(f"[3GPP AI Service] Error: {e}")
            return f"Error generating response: {str(e)}"


ai_service = AIService()
