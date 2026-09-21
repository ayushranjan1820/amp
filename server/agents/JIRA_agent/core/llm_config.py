"""LLM configuration for JIRA agent."""
from dataclasses import dataclass
from typing import Dict


@dataclass
class LLMModelConfig:
    temperature: float = 0.2
    max_tokens: int = 4096


_DEFAULT_CONFIG: Dict[str, LLMModelConfig] = {
    "jira_agent": LLMModelConfig(temperature=0.2, max_tokens=4096),
}


def get_llm_config() -> Dict[str, LLMModelConfig]:
    return _DEFAULT_CONFIG
