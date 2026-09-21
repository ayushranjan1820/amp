import asyncio
import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import urlparse

from .tools.perplexity_client import perplexity_client
from .ai_service import web_search_ai_service
from .models import (
    WebSearchResponse,
    ThinkingStep,
    SearchSource,
)


class WebSearchAgent:

    def __init__(self):
        self.client = perplexity_client
        self.ai = web_search_ai_service
        self.sessions: Dict[str, List[Dict[str, str]]] = {}

        if self.client.is_configured():
            if self.client.current_provider() == "free_ollama":
                print("🌐 Web Search Agent - Ready (Ollama free web search)")
            elif self.client.current_provider() == "free_duckduckgo":
                print("🌐 Web Search Agent - Ready (DuckDuckGo free web search)")
            else:
                print("🌐 Web Search Agent - Ready (Perplexity)")
        else:
            print("⚠️ Web Search Agent - provider credentials not configured")

    def clear_session(self, session_id: str):
        if session_id in self.sessions:
            del self.sessions[session_id]

    async def search(
        self,
        query: str,
        search_focus: Optional[str] = None,
        session_id: Optional[str] = None,
        clear_history: bool = False,
    ) -> WebSearchResponse:

        current_session_id = session_id or str(uuid.uuid4())

        if clear_history:
            self.clear_session(current_session_id)

        thinking_steps: List[ThinkingStep] = []
        tool_results: List[dict] = []

        if not query.strip():
            return WebSearchResponse(
                success=True,
                query=query,
                response="Session cleared.",
                timestamp=datetime.now().isoformat(),
                session_id=current_session_id,
            )

        if not self.client.is_configured():
            provider = self.client.current_provider()
            if provider == "free_ollama":
                msg = "**Web Search Agent is not available.** The `OLLAMA_API_KEY` environment variable is not configured for free Ollama web search."
                reason = "Ollama API key not configured"
            elif provider == "free_duckduckgo":
                msg = "**Web Search Agent is not available.** DuckDuckGo free web search is selected but the `ddgs` package is not installed on the server."
                reason = "DuckDuckGo search backend not installed"
            else:
                msg = "**Web Search Agent is not available.** The `PERPLEXITY_API_KEY` environment variable is not configured. Please set it to enable web search."
                reason = "Perplexity API key not configured"
            return WebSearchResponse(
                success=False,
                query=query,
                response=msg,
                timestamp=datetime.now().isoformat(),
                session_id=current_session_id,
                thinking_steps=[ThinkingStep(type="thinking", content=reason)],
            )

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content=f"Analyzing query: \"{query}\""
        ))

        if not search_focus:
            thinking_steps.append(ThinkingStep(
                type="tool_call",
                content="Classifying search intent using LLM to determine optimal search parameters",
                tool_name="llm_intent_classifier",
                tool_input=query,
            ))
            tool_results.append({"tool": "llm_intent_classifier", "input": {"query": query}, "status": "running"})

            intent = await self.ai.classify_search_intent(query)
            search_focus = intent["search_focus"]
            optimized_query = intent["optimized_query"]
            recency_filter = intent.get("recency_filter")

            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = intent

            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Search focus: **{search_focus}** | Optimized query: \"{optimized_query}\"" +
                        (f" | Recency: {recency_filter}" if recency_filter else ""),
                tool_name="llm_intent_classifier",
            ))
        else:
            optimized_query = query
            recency_filter = None

        print(f"\n{'='*60}")
        print(f"🌐 Web Search: {optimized_query}")
        print(f"   Focus: {search_focus}")
        print(f"{'='*60}")

        provider = self.client.current_provider()
        if provider == "free_ollama":
            provider_label = "Ollama free web search"
            search_tool_name = "ollama_web_search"
        elif provider == "free_duckduckgo":
            provider_label = "DuckDuckGo free web search"
            search_tool_name = "duckduckgo_web_search"
        else:
            provider_label = "Perplexity"
            search_tool_name = "perplexity_search"

        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content=f"Searching the web with {provider_label} ({search_focus} mode)",
            tool_name=search_tool_name,
            tool_input=optimized_query,
        ))
        tool_results.append({"tool": search_tool_name, "input": {"query": optimized_query, "focus": search_focus}, "status": "running"})

        conversation_history = self.sessions.get(current_session_id, [])

        if conversation_history:
            result = await self.client.search_with_context(
                query=optimized_query,
                conversation_history=conversation_history,
                search_focus=search_focus,
            )
        else:
            result = await self.client.search(
                query=optimized_query,
                search_focus=search_focus,
                search_recency_filter=recency_filter,
                return_images=True,
                return_related_questions=True,
            )

        tool_results[-1]["status"] = "completed"
        tool_results[-1]["result"] = {
            "citations_count": len(result.get("citations", [])),
            "images_count": len(result.get("images", [])),
            "has_answer": bool(result.get("answer")),
        }

        raw_answer = result.get("answer", "")
        citations = result.get("citations", [])
        images = result.get("images", [])
        related_questions = result.get("related_questions", [])

        thinking_steps.append(ThinkingStep(
            type="tool_result",
            content=f"Search completed: {len(citations)} sources, {len(images)} images, {len(related_questions)} follow-up questions",
            tool_name=search_tool_name,
        ))

        print(f"✅ Got answer with {len(citations)} citations, {len(images)} images")

        sources: List[SearchSource] = []
        source_urls = []
        for c in citations:
            url = c if isinstance(c, str) else c.get("url", "") if isinstance(c, dict) else ""
            if url and url not in source_urls:
                source_urls.append(url)
                domain = self.client.extract_domain(url)
                title = c.get("title", domain) if isinstance(c, dict) else domain
                snippet_text = c.get("snippet", "") if isinstance(c, dict) else ""
                sources.append(SearchSource(
                    title=title,
                    url=url,
                    snippet=snippet_text,
                    domain=domain,
                ))

        if sources:
            thinking_steps.append(ThinkingStep(
                type="tool_call",
                content=f"Fetching preview images for {min(len(sources), 5)} sources",
                tool_name="og_image_fetcher",
            ))
            tool_results.append({"tool": "og_image_fetcher", "input": {"count": min(len(sources), 5)}, "status": "running"})

            og_tasks = [self.client.fetch_og_image(s.url) for s in sources[:5]]
            og_results = await asyncio.gather(*og_tasks, return_exceptions=True)
            for i, og in enumerate(og_results):
                if i < len(sources) and isinstance(og, str) and og:
                    sources[i].image_url = og

            tool_results[-1]["status"] = "completed"
            images_found = sum(1 for s in sources if s.image_url)
            tool_results[-1]["result"] = {"images_found": images_found}

            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Found {images_found} preview images from sources",
                tool_name="og_image_fetcher",
            ))

        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content="Formatting search results into a professional response using LLM",
            tool_name="llm_formatter",
        ))
        tool_results.append({"tool": "llm_formatter", "input": {"search_focus": search_focus}, "status": "running"})

        formatted_response = await self.ai.format_response(
            raw_answer=raw_answer,
            query=query,
            citations=citations,
            images=images,
            search_focus=search_focus,
        )

        tool_results[-1]["status"] = "completed"

        thinking_steps.append(ThinkingStep(
            type="observation",
            content=f"Response formatted ({len(formatted_response)} chars). Search complete."
        ))

        if current_session_id not in self.sessions:
            self.sessions[current_session_id] = []
        self.sessions[current_session_id].append({"role": "user", "content": query})
        self.sessions[current_session_id].append({"role": "assistant", "content": raw_answer})

        if len(self.sessions[current_session_id]) > 12:
            self.sessions[current_session_id] = self.sessions[current_session_id][-12:]

        image_urls = []
        for img in images:
            if isinstance(img, str):
                image_urls.append(img)
            elif isinstance(img, dict):
                image_urls.append(img.get("url", img.get("image_url", "")))

        return WebSearchResponse(
            success=True,
            query=query,
            search_focus=search_focus,
            response=formatted_response,
            sources=sources,
            images=image_urls[:8],
            timestamp=datetime.now().isoformat(),
            session_id=current_session_id,
            thinking_steps=thinking_steps,
            tool_results=tool_results,
            follow_up_questions=related_questions[:5] if related_questions else [],
        )


web_search_agent = WebSearchAgent()
