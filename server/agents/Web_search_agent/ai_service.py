"""AI service for Web Search Agent — delegates to shared BaseAIService."""
import os
import json
from pathlib import Path

if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    load_dotenv_then_scrub_pwc(dotenv_path=Path(__file__).parent.parent.parent / ".env")

from agents.base_ai_service import BaseAIService
from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS


class WebSearchAIService(BaseAIService):
    def __init__(self):
        super().__init__(
            default_temperature=0.3,
            default_max_tokens=4096,
            timeout=60,
            transport="async",
        )

    async def classify_search_intent(self, query: str) -> dict:
        if not self._api_key() and self._needs_pwc_credentials():
            return {"search_focus": "general", "optimized_query": query, "recency_filter": None}

        prompt = f"""Analyze this user query and determine the best search parameters.

User Query: "{query}"

Return a JSON object with these fields:
- "search_focus": one of "general", "news", "academic", "writing", "math", "deep_research"
  - "general" for everyday questions, how-to, product comparisons, general knowledge
  - "news" for current events, breaking news, recent developments, trending topics
  - "academic" for research papers, scientific studies, scholarly topics, technical deep-dives
  - "writing" for content creation help, essay research, creative writing references
  - "math" for calculations, equations, mathematical proofs, scientific formulas
  - "deep_research" for complex topics requiring thorough multi-faceted analysis
- "optimized_query": a refined version of the query optimized for web search (keep it natural, expand abbreviations, add context if helpful)
- "recency_filter": null for general, or "day"/"week"/"month" for news queries based on how recent the user wants results

Return ONLY the JSON object, no other text.
"""
        try:
            result = await self.call_genai_async(prompt, temperature=0.1, max_tokens=512)

            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
                cleaned = cleaned.rsplit("```", 1)[0]
            parsed = json.loads(cleaned)
            return {
                "search_focus": parsed.get("search_focus", "general"),
                "optimized_query": parsed.get("optimized_query", query),
                "recency_filter": parsed.get("recency_filter"),
            }
        except Exception as e:
            print(f"Intent classification error: {e}")
            return {"search_focus": "general", "optimized_query": query, "recency_filter": None}

    async def format_response(self, raw_answer: str, query: str, citations: list, images: list, search_focus: str) -> str:
        if not self._api_key() and self._needs_pwc_credentials():
            return raw_answer

        citation_text = ""
        if citations:
            citation_text = "\n\nAvailable source URLs for references:\n"
            for i, c in enumerate(citations):
                if isinstance(c, str):
                    citation_text += f"[{i+1}] {c}\n"
                elif isinstance(c, dict):
                    citation_text += f"[{i+1}] {c.get('url', c.get('title', ''))}\n"

        prompt = f"""You are formatting a web search result into a professional, easy-to-read response.

**Search Focus**: {search_focus}
**User Query**: "{query}"

**Raw Search Answer**:
{raw_answer}
{citation_text}

{MANDATORY_MARKDOWN_SOURCE_LINKS}

**Instructions**:
1. Reformat the answer into clean, professional markdown
2. Use clear headings (## and ###) to organize information
3. Use bullet points for lists and key takeaways
4. Bold important terms, numbers, and key facts
5. If the raw answer has citation numbers like [1], [2], etc., convert them into proper markdown links using the source URLs provided above. Format: [Source Title](URL)
6. Add a "### Key Takeaways" section at the top with 3-5 bullet points summarizing the most important findings
7. Keep the tone informative and professional
8. If images are relevant, note where they should appear but don't generate image markdown
9. Preserve all factual content from the raw answer — do not add information that wasn't in the original
10. For news focus: organize chronologically with dates prominent
11. For academic focus: emphasize methodology, findings, and cite specific studies
12. For math focus: use proper formatting for equations and formulas
13. The final output is invalid if it contains unlinked `[Source N]` or `[1]`-style tags; every one must be `[label](https://...)` with a real URL from the citation list.

Return ONLY the formatted markdown response."""

        try:
            result = await self.call_genai_async(prompt, temperature=0.2, max_tokens=6144)
            return result
        except Exception as e:
            print(f"Response formatting error: {e}")
            return raw_answer

    def _needs_pwc_credentials(self) -> bool:
        from agents.local_llm import uses_pwc_genai_credentials
        return uses_pwc_genai_credentials()


web_search_ai_service = WebSearchAIService()
