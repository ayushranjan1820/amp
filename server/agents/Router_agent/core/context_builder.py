"""
Context Builder Module for Router Agent
Builds contextualized queries with conversation history.
"""

from typing import Optional, List, Dict
from ..core.token_manager import TokenManager


class ContextBuilder:
    """Builds contextual queries from conversation history."""
    
    def __init__(self, token_manager: TokenManager):
        self.token_manager = token_manager
    
    def _get_last_assistant_response(self, conversation_history: Optional[List[Dict]] = None) -> Optional[str]:
        """Extract the last assistant response from conversation history."""
        if not conversation_history:
            return None
        for msg in reversed(conversation_history):
            if msg.get("role") == "assistant":
                return msg.get("content", "")
        return None
    
    def build_context_query(self, query: str, conversation_history: Optional[List[Dict]] = None, agent_id: Optional[str] = None, references_context: bool = False) -> str:
        """Build contextualized query with token-aware history management."""
        if not conversation_history:
            return query

        # Calculate available tokens for context (agents can have large context windows)
        # Reserve space for query and response
        available_tokens = 100000  # Conservative limit for agent context

        if references_context:
            last_response = self._get_last_assistant_response(conversation_history)
            user_msgs = [m for m in conversation_history if m.get("role") == "user"]
            summary_parts = []
            used_tokens = 0
            
            for m in user_msgs[-3:]:
                content = m.get("content", "")
                msg_tokens = self.token_manager.count_tokens(content)
                
                if used_tokens + msg_tokens > available_tokens // 2:
                    # Truncate to fit
                    remaining = (available_tokens // 2) - used_tokens
                    if remaining > 50:
                        content = content[:remaining * 4] + "..."
                        summary_parts.append(f"- User previously asked: {content}")
                        used_tokens += remaining
                    break
                else:
                    summary_parts.append(f"- User previously asked: {content}")
                    used_tokens += msg_tokens
            
            if last_response:
                # Include full last response (it's the source content)
                summary_parts.append(f"- Last assistant response (USE THIS AS SOURCE CONTENT):\n{last_response}")
            
            summary = "\n".join(summary_parts)
            return f"""[Previous conversation context - the user's current request references this content]
{summary}

[Current request]
{query}

IMPORTANT: The user is referring to the previous assistant response above. Use the full content of that response as the source/input for fulfilling their current request."""

        structured_agents = {'bpmn_generator', 'jira_agent', 'github_repo', 'unit_test_agent'}
        if agent_id in structured_agents:
            user_msgs = [m for m in conversation_history if m.get("role") == "user"]
            assistant_msgs = [m for m in conversation_history if m.get("role") == "assistant"]
            summary_parts = []
            used_tokens = 0
            
            # Add recent user messages
            for m in user_msgs[-3:]:
                content = m.get("content", "")
                msg_tokens = self.token_manager.count_tokens(content)
                
                if used_tokens + msg_tokens > available_tokens // 3:
                    remaining = (available_tokens // 3) - used_tokens
                    if remaining > 50:
                        content = content[:remaining * 4] + "..."
                        summary_parts.append(f"- User previously asked: {content}")
                        used_tokens += remaining
                    break
                else:
                    summary_parts.append(f"- User previously asked: {content}")
                    used_tokens += msg_tokens
            
            # Add last assistant response (important for structured agents)
            if assistant_msgs:
                last_reply = assistant_msgs[-1].get("content", "")
                reply_tokens = self.token_manager.count_tokens(last_reply)
                max_reply_tokens = available_tokens // 2
                
                if reply_tokens > max_reply_tokens:
                    # Truncate but keep substantial content
                    last_reply = last_reply[:max_reply_tokens * 4] + "..."
                
                summary_parts.append(f"- Last assistant response:\n{last_reply}")
            
            summary = "\n".join(summary_parts)
            return f"""[Conversation context - use this to understand what the user is referring to]
{summary}

[Current request]
{query}"""

        # For other agents, include more messages with token management
        recent_messages = conversation_history[-10:]
        context_parts = []
        used_tokens = 0
        max_context_tokens = available_tokens
        
        for msg in recent_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            msg_tokens = self.token_manager.count_tokens(content)
            
            if used_tokens + msg_tokens > max_context_tokens:
                # Truncate this message to fit
                remaining = max_context_tokens - used_tokens
                if remaining > 50:
                    content = content[:remaining * 4] + "..."
                    context_parts.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
                break
            else:
                context_parts.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
                used_tokens += msg_tokens

        context_str = "\n".join(context_parts)
        return f"""Previous conversation context:
---
{context_str}
---

Current user message: {query}

Important: Use the conversation context above to understand what the user is referring to. Respond to the current message while maintaining continuity with the previous discussion."""
