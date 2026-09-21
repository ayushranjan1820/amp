"""Backward-compatible re-export of conversation management classes."""
from .helpers.conversation_manager import (
    ConversationContext,
    ConversationState,
    ConversationManager,
    InfoRequest,
    create_conversation_manager,
)

conversation_manager = create_conversation_manager()

__all__ = [
    "ConversationContext",
    "ConversationState",
    "ConversationManager",
    "InfoRequest",
    "create_conversation_manager",
    "conversation_manager",
]
