"""
Token Management Module for Router Agent
Delegates to the global token_manager module for provider-aware token counting.
"""

from agents.token_manager import count_tokens as _count_tokens, get_active_context_tokens


class TokenManager:
    """Manages token counting and context window budget."""

    def __init__(self):
        available = get_active_context_tokens()
        from agents.local_llm import get_llm_provider
        provider = get_llm_provider()
        print(f"✓ Router using tiktoken for precise token counting (provider: {provider}, available context: {available:,} tokens)")

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken."""
        return _count_tokens(text)

    def get_available_context_tokens(self) -> int:
        """Calculate available tokens for conversation history."""
        return get_active_context_tokens()
