from typing import Dict, Any, Optional, List
from datetime import datetime

# Import modular components
from .config.catalog_loader import CatalogLoader
from .services.llm_service import LLMService
from .services.agent_loader import AgentLoader
from .services.agent_invoker import AgentInvoker
from .core.token_manager import TokenManager
from .core.classifier import QueryClassifier
from .core.context_builder import ContextBuilder


class RouterAgent:
    """
    Intelligent Router Agent for AI Agent Marketplace.
    
    This router uses LLM-powered intent analysis to intelligently route user queries
    to the most appropriate specialized agent. Key features:
    
    - **AI-First Routing**: Always uses LLM to deeply analyze user intent with full context
    - **Context-Aware**: Considers conversation history, previous agent interactions, and references
    - **Data-Driven**: Fully configured via agents_catalog.json - no hardcoded agent logic
    - **Dynamic Loading**: Agents are loaded on-demand using importlib reflection
    - **Unified Invocation**: Generic agent calling interface configured per agent
    - **Intelligent Fallback**: Multi-tier fallback strategy (keyword hints → history → default)
    - **Modular Architecture**: Clean separation of concerns across multiple modules
    
    The routing process:
    1. Extract keyword hints (supporting info, not decision)
    2. Build comprehensive context from conversation history
    3. Call LLM to analyze true user intent
    4. Route to optimal agent with full contextual data
    5. Track conversation state for continuity
    
    Version: 3.0 (Modular Architecture)
    """
    def __init__(self):
        # Initialize all service components
        self.catalog_loader = CatalogLoader()
        self.llm_service = LLMService()
        self.token_manager = TokenManager()
        self.agent_loader = AgentLoader(self.catalog_loader)
        self.context_builder = ContextBuilder(self.token_manager)
        self.classifier = QueryClassifier(self.catalog_loader, self.llm_service, self.token_manager)
        self.agent_invoker = AgentInvoker(self.catalog_loader, self.agent_loader, self.context_builder)

    async def classify_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        allowed_agent_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Delegate to classifier module."""
        return await self.classifier.classify_query(
            query, session_id, conversation_history, allowed_agent_ids=allowed_agent_ids
        )

    async def route_and_respond(
        self,
        query: str,
        session_id: Optional[str] = None,
        conversation_history: Optional[List[Dict]] = None,
        github_token: Optional[str] = None,
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        target_agent: Optional[str] = None,
        allowed_agent_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Route query to appropriate agent and return response."""
        thinking_steps = []

        allow_set = set(allowed_agent_ids) if allowed_agent_ids else None

        if target_agent:
            if allow_set is not None and target_agent not in allow_set:
                return {
                    "success": False,
                    "query": query,
                    "response": "You do not have access to this agent. Ask your administrator to grant access.",
                    "routed_to": {
                        "agent_id": target_agent,
                        "agent_name": target_agent,
                        "confidence": 0.0,
                        "reasoning": "Access denied",
                    },
                    "thinking_steps": thinking_steps,
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat(),
                }
            agent_info = self.catalog_loader.get_agent_info(target_agent)
            if agent_info:
                agent_id = target_agent
                agent_name = agent_info["name"]
                confidence = 1.0
                reasoning = f"User selected {agent_name} directly"
                references_context = False

                thinking_steps.append({
                    "type": "thinking",
                    "content": f"📍 User selected {agent_name} — skipping auto-routing"
                })
            else:
                target_agent = None

        if not target_agent:
            context_info = ""
            if conversation_history and len(conversation_history) > 0:
                context_info = f" (with {len(conversation_history)} messages of context)"
            
            thinking_steps.append({
                "type": "thinking",
                "content": f"🧠 Using AI to intelligently analyze query intent{context_info}: \"{query}\""
            })

            thinking_steps.append({
                "type": "tool_call",
                "content": "Calling LLM for deep intent analysis with full contextual awareness",
                "tool_name": "intent_analyzer",
                "tool_input": "Analyzing user's true intent, conversation history, and selecting optimal agent"
            })

            classification = await self.classifier.classify_query(
                query, session_id, conversation_history, allowed_agent_ids=allowed_agent_ids
            )
            agent_id = classification["agent_id"]
            confidence = classification.get("confidence", 0)
            reasoning = classification.get("reasoning", "")
            references_context = classification.get("references_context", False)

            agent_info = self.catalog_loader.get_agent_info(agent_id)
            agent_name = agent_info["name"] if agent_info else agent_id

            thinking_steps.append({
                "type": "tool_result",
                "content": f"✓ Intent Analysis Complete: {reasoning}",
                "tool_name": "intent_analyzer"
            })

            thinking_steps.append({
                "type": "thinking",
                "content": f"📍 Routing to {agent_name} (confidence: {confidence:.0%})"
            })

        if references_context:
            thinking_steps.append({
                "type": "thinking",
                "content": "Detected contextual reference — including full previous response as source content"
            })

        if conversation_history:
            thinking_steps.append({
                "type": "thinking",
                "content": f"Including {len(conversation_history)} previous messages as context"
            })

        thinking_steps.append({
            "type": "thinking",
            "content": f"Calling {agent_name} with conversation context..."
        })

        # Use agent invoker module
        agent_response = await self.agent_invoker.invoke_agent(
            agent_id, query, session_id, conversation_history, references_context, github_token,
            file_content=file_content, file_type=file_type, file_name=file_name
        )

        agent_thinking = agent_response.get("thinking_steps", [])
        if agent_thinking:
            thinking_steps.extend(agent_thinking)

        thinking_steps.append({
            "type": "tool_result",
            "content": f"Response received from {agent_name}",
            "tool_name": agent_name
        })

        # Track conversation
        if session_id:
            self.classifier.track_conversation(session_id, query, agent_id, agent_name)

        result = {
            "success": agent_response.get("success", True),
            "query": query,
            "response": agent_response.get("response", ""),
            "routed_to": {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "confidence": confidence,
                "reasoning": reasoning
            },
            "thinking_steps": thinking_steps,
            "bpmn_xml": agent_response.get("bpmn_xml"),
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }

        # Pass through additional agent-specific fields
        if agent_response.get("latest_news_cards"):
            result["latest_news_cards"] = agent_response["latest_news_cards"]

        if agent_response.get("report_image_urls") is not None:
            result["report_image_urls"] = agent_response["report_image_urls"]

        if agent_response.get("requires_token"):
            result["requires_token"] = True

        if agent_response.get("task_id"):
            result["task_id"] = agent_response["task_id"]

        if agent_response.get("requires_uri"):
            result["requires_uri"] = True

        if agent_response.get("chart_data"):
            result["chart_data"] = agent_response["chart_data"]

        return result


router_agent = RouterAgent()
