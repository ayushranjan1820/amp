"""
Query Classifier Module for Router Agent
Handles intelligent query classification using LLM and keyword hints.
"""

import json
from typing import Dict, Any, Optional, List, Set
from ..config.catalog_loader import CatalogLoader
from ..services.llm_service import LLMService
from ..core.token_manager import TokenManager


class QueryClassifier:
    """Classifies user queries to determine appropriate agent routing."""
    
    def __init__(self, catalog_loader: CatalogLoader, llm_service: LLMService, token_manager: TokenManager):
        self.catalog_loader = catalog_loader
        self.llm_service = llm_service
        self.token_manager = token_manager
        self.conversation_history: Dict[str, List[Dict]] = {}
    
    def _keyword_classify(self, query: str, allowed: Optional[Set[str]] = None) -> Optional[Dict[str, Any]]:
        """Classify query based on keyword patterns from catalog."""
        q = query.lower()

        # Iterate through all agents in catalog and check keywords
        for agent in self.catalog_loader.get_all_agents():
            agent_id = agent["id"]
            if allowed is not None and agent_id not in allowed:
                continue
            routing = agent.get("routing", {})
            keywords = routing.get("keywords", [])
            
            if not keywords:
                continue
            
            # Check if any keyword matches
            if any(kw.lower() in q for kw in keywords):
                # Special rule for unit_test_agent
                if agent_id == "unit_test_agent":
                    has_test_kw = any(kw.lower() in q for kw in keywords if 'test' in kw.lower())
                    analyse_and_test = ('analyse' in q or 'analyze' in q) and ('test' in q)
                    if not (has_test_kw or analyse_and_test):
                        continue
                
                # Special rule for github - avoid conflict with test
                if agent_id == "github_repo" and 'test' in q and ('generate' in q or 'write' in q or 'create' in q):
                    continue
                    
                confidence = routing.get("confidence", 0.95)
                agent_name = agent.get("name", agent_id)
                reasoning = f"Query matches keywords for {agent_name}"
                
                return {
                    "agent_id": agent_id,
                    "confidence": confidence,
                    "reasoning": reasoning
                }
        
        return None
    
    def _get_last_agent_from_history(self, conversation_history: Optional[List[Dict]] = None, session_id: Optional[str] = None) -> Optional[str]:
        """Extract the last agent used from conversation history."""
        if session_id and session_id in self.conversation_history:
            recent = self.conversation_history[session_id]
            if recent:
                return recent[-1].get("agent_id")

        if conversation_history:
            for msg in reversed(conversation_history):
                routed = msg.get("routed_to")
                if routed and isinstance(routed, dict):
                    return routed.get("agent_id")
                metadata = msg.get("metadata")
                if metadata and isinstance(metadata, dict):
                    rt = metadata.get("routed_to")
                    if rt and isinstance(rt, dict):
                        return rt.get("agent_id")
        return None
    
    async def classify_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        allowed_agent_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Always use LLM to intelligently analyze query intent with full context.
        Keyword classification provides hints but LLM makes the final decision.
        """
        has_history = bool(conversation_history and len(conversation_history) > 0)
        allowed: Optional[Set[str]] = set(allowed_agent_ids) if allowed_agent_ids else None

        # Get keyword hint (not decision, just supporting information)
        keyword_hint = self._keyword_classify(query, allowed)
        keyword_context = ""
        if keyword_hint:
            keyword_context = f"\n\nKeyword analysis hint: The query contains keywords suggesting '{keyword_hint['agent_id']}' ({keyword_hint['reasoning']}). Consider this but make your own intelligent decision based on full context."
        
        last_agent = self._get_last_agent_from_history(conversation_history, session_id)
        if allowed is not None and last_agent and last_agent not in allowed:
            last_agent = None

        # Build comprehensive conversation context with token-aware truncation
        history_context = ""
        last_agent_context = ""
        if has_history:
            # Calculate available tokens for history context
            agent_summaries = self.catalog_loader.get_agent_summaries(allowed)
            base_tokens = self.token_manager.count_tokens(agent_summaries) + self.token_manager.count_tokens(query) + self.token_manager.count_tokens(keyword_context)
            available_history_tokens = self.token_manager.get_available_context_tokens() - base_tokens - 1000  # Extra buffer
            
            recent = conversation_history[-6:]
            history_parts = []
            used_tokens = 0
            
            # Build history from most recent backwards, respecting token budget
            for msg in reversed(recent):
                role = "User" if msg.get("role") == "user" else "Assistant"
                content = msg.get("content", "")
                routed = msg.get("routed_to")
                agent_label = ""
                if routed and isinstance(routed, dict):
                    agent_label = f" [handled by: {routed.get('agent_name', routed.get('agent_id', ''))}]"
                
                # Calculate tokens for this message
                message_text = f"{role}{agent_label}: {content}"
                message_tokens = self.token_manager.count_tokens(message_text)
                
                # If adding this message would exceed budget, truncate it
                if used_tokens + message_tokens > available_history_tokens:
                    remaining_tokens = available_history_tokens - used_tokens
                    if remaining_tokens > 100:  # Only include if we have reasonable space
                        # Truncate content to fit remaining tokens (approx 4 chars per token)
                        max_chars = remaining_tokens * 4
                        truncated_content = content[:max_chars] + "..." if len(content) > max_chars else content
                        message_text = f"{role}{agent_label}: {truncated_content}"
                        history_parts.insert(0, message_text)
                        used_tokens += remaining_tokens
                    break
                else:
                    history_parts.insert(0, message_text)
                    used_tokens += message_tokens
            
            if history_parts:
                history_context = f"\n\n=== CONVERSATION CONTEXT ===\nRecent conversation history (use this to understand continuity and user intent):\n" + "\n\n".join(history_parts)
                history_context += f"\n[Context uses {used_tokens:,} tokens of {available_history_tokens:,} available]"
            
            if last_agent:
                last_agent_info = self.catalog_loader.get_agent_info(last_agent)
                last_agent_name = last_agent_info["name"] if last_agent_info else last_agent
                last_agent_context = f"\n\nPrevious agent used in this conversation: {last_agent_name} (ID: {last_agent})\nConsider routing to the same agent if the query is a follow-up or continuation."
        elif session_id and session_id in self.conversation_history:
            recent = self.conversation_history[session_id][-3:]
            history_parts = []
            for msg in recent:
                history_parts.append(f"User: {msg.get('query', '')}")
                history_parts.append(f"Routed to: {msg.get('agent_id', '')} ({msg.get('agent_name', '')})")
            history_context = f"\n\n=== CONVERSATION CONTEXT ===\nRecent conversation:\n" + "\n".join(history_parts)
            if last_agent:
                last_agent_context = f"\n\nPrevious agent used: {last_agent}"

        prompt = f"""You are an intelligent query router for an AI Agent Marketplace. Analyze the user's query deeply to understand their TRUE INTENT, considering all contextual information.

=== AVAILABLE AGENTS ===
{self.catalog_loader.get_agent_summaries(allowed)}
{history_context}
{last_agent_context}
{keyword_context}

=== USER QUERY ===
"{query}"

=== YOUR TASK ===
Analyze the query comprehensively and determine:
1. The user's TRUE INTENT - what are they really trying to accomplish?
2. Which agent is BEST SUITED to handle this intent?
3. Does the query reference or depend on previous conversation context?

Consider:
- The explicit words in the query
- The implied intent behind those words
- The conversation history and flow
- Whether this is a follow-up to a previous interaction
- The capabilities of each agent
- Context from any previous responses the user might be referencing

Respond with ONLY valid JSON (no markdown, no backticks):
{{
  "agent_id": "<the best matching agent ID>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<detailed explanation of the user's intent and why this agent was chosen>",
  "references_context": <true if the query references or depends on previous conversation content, false otherwise>
}}

=== ROUTING GUIDELINES ===
{self.catalog_loader.get_routing_guidelines(allowed)}

CRITICAL DISTINCTIONS:
- If query mentions BOTH analysis AND testing → route to unit_test_agent
- ALL git/push operations (even "push tests") → route to github_repo
- Follow-up queries → strongly prefer the same agent unless intent clearly changed
- Contextual references ("do that", "same for", "now generate") → set references_context=true

Output ONLY the JSON object, nothing else."""

        try:
            result = await self.llm_service.call_llm(prompt, temperature=0.3, max_tokens=2048)
            result = result.strip()
            
            # Clean markdown formatting if present
            if result.startswith("```"):
                result = result.split("\n", 1)[1] if "\n" in result else result[3:]
                if result.endswith("```"):
                    result = result[:-3]
                result = result.strip()

            classification = json.loads(result)
            
            # Validate agent_id
            valid_ids = self.catalog_loader.get_valid_agent_ids()
            if allowed is not None:
                valid_ids = [i for i in valid_ids if i in allowed]
            chosen = classification.get("agent_id")
            if chosen not in valid_ids:
                # If LLM chose invalid agent, fallback to keyword hint or default in allowed set
                if keyword_hint and keyword_hint["agent_id"] in valid_ids:
                    classification = keyword_hint.copy()
                    classification["confidence"] = 0.6
                    classification["reasoning"] = f"LLM chose invalid agent, using keyword hint: {keyword_hint['reasoning']}"
                elif valid_ids:
                    pick = "basic_agent" if "basic_agent" in valid_ids else valid_ids[0]
                    classification["agent_id"] = pick
                    classification["confidence"] = 0.5
                    classification["reasoning"] = "Defaulting to allowed agent as fallback"
                else:
                    classification["agent_id"] = "basic_agent"
                    classification["confidence"] = 0.0
                    classification["reasoning"] = "No allowed agents configured"

            return classification
            
        except (json.JSONDecodeError, Exception) as e:
            print(f"⚠️ LLM classification error: {e}")
            
            # Fallback hierarchy: keyword hint > last agent > basic_agent
            if keyword_hint and (allowed is None or keyword_hint["agent_id"] in allowed):
                keyword_hint["references_context"] = has_history
                return keyword_hint
            
            valid_ids = self.catalog_loader.get_valid_agent_ids()
            if allowed is not None:
                valid_ids = [i for i in valid_ids if i in allowed]
            fallback_agent = None
            if last_agent and (allowed is None or last_agent in allowed) and last_agent in valid_ids:
                fallback_agent = last_agent
            elif valid_ids:
                fallback_agent = "basic_agent" if "basic_agent" in valid_ids else valid_ids[0]
            else:
                fallback_agent = "basic_agent"
            return {
                "agent_id": fallback_agent,
                "confidence": 0.3,
                "reasoning": f"LLM classification failed ({str(e)}), using fallback strategy",
                "references_context": has_history and last_agent and last_agent != "basic_agent"
            }
    
    def track_conversation(self, session_id: str, query: str, agent_id: str, agent_name: str):
        """Track query routing in conversation history."""
        from datetime import datetime
        
        if session_id not in self.conversation_history:
            self.conversation_history[session_id] = []
        self.conversation_history[session_id].append({
            "query": query,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "timestamp": datetime.now().isoformat()
        })
