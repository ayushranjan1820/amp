"""AI service for SEBI Circular Agent — delegates to shared BaseAIService."""
import os
from pathlib import Path
from typing import List, Dict, Any

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

    async def call_genai(self, prompt: str, temperature: float = 0.3, max_tokens: int = 4096) -> str:
        """Call PWC GenAI service with auto-continuation."""
        try:
            return await self.call_genai_async(prompt, temperature, max_tokens)
        except Exception as e:
            return f"Error calling AI service: {str(e)}"

    async def summarize_content(self, content: str, query: str) -> str:
        """Summarize notification content based on user query."""
        prompt = f"""You are an expert at analyzing SEBI (Securities and Exchange Board of India) circulars and notifications.

User Query: {query}

SEBI Notification Content:
{content}

Provide a clear, professional summary that:
1. Directly addresses the user's query
2. Highlights the key points and implications
3. Mentions important dates, deadlines, or compliance requirements
4. Notes which entities/institutions are affected
5. Summarizes any actions required

Format your response in a clear, structured manner using markdown:
- Use headers for main sections
- Use bullet points for lists
- Highlight important terms in bold
- Include relevant dates and deadlines prominently

Keep the summary comprehensive but concise."""

        return await self.call_genai(prompt, temperature=0.2)

    async def summarize_multiple_documents(self, combined_content: str, query: str) -> str:
        """Summarize multiple documents based on user query."""
        prompt = f"""You are an expert at analyzing SEBI (Securities and Exchange Board of India) circulars and notifications.

User Query: {query}

I have retrieved the following SEBI documents that may be relevant:

{combined_content}

Based on these documents, provide a comprehensive response that:
1. Directly addresses the user's query
2. Synthesizes information from all relevant documents
3. Highlights the key points, regulations, and guidelines
4. Mentions important dates, deadlines, or compliance requirements
5. Notes which entities/institutions are affected
6. Summarizes any actions required
7. References specific documents by their title/name when citing information (e.g., "According to Document 1: Master Circular on Listing Obligations...")

IMPORTANT: When providing information, always cite which document it comes from. This ensures proper references and verifiability.

If the documents don't directly answer the query, explain what information is available and suggest what the user might be looking for.

Format your response in a clear, structured manner using markdown:
- Use headers for main sections
- Use bullet points for lists
- Highlight important terms in bold
- Include relevant dates and deadlines prominently

Keep the response comprehensive but focused on answering the user's query."""

        return await self.call_genai(prompt, temperature=0.2, max_tokens=4096)

    async def extract_key_points_and_format(self, search_results: List[Dict[str, Any]], query: str) -> str:
        content_parts = []
        for i, result in enumerate(search_results, 1):
            title = result.get('title', 'Unknown')
            url = result.get('url', '')
            date = result.get('date', 'Date not available')
            snippet = result.get('snippet', '')
            content = result.get('content', '')

            doc_info = f"""
Document {i}: {title}
URL: {url}
Date: {date}
"""
            if snippet:
                doc_info += f"Summary: {snippet}\n"
            if content:
                doc_info += f"Content: {content}\n"

            content_parts.append(doc_info)

        combined_content = "\n---\n".join(content_parts)

        prompt = f"""You are an expert analyst specializing in SEBI (Securities and Exchange Board of India) regulations and circulars.

**User Query:** {query}

**Retrieved Documents from SEBI Website:**

{combined_content}

**Your Task:**
Analyze the above documents and provide a comprehensive response that directly addresses the user's query. 

**MANDATORY ELEMENTS (Must Always Include):**

1. **📅 Publish Date(s):** Always mention the publication date(s) of the relevant circulars/notifications
2. **🔗 Reference(s):** Always cite the document reference numbers, titles, and URLs
3. **🔑 Key Points:** Always extract and list the most important points (minimum 3-5 points)

**Response Guidelines:**

- **Dynamic Format:** Structure your response naturally based on what the user is asking for. Don't force a rigid template.
- **User-Centric:** Focus on answering the specific question asked. If they want a summary, provide a summary. If they want details, provide details. If they want specific information (like compliance requirements, deadlines, affected entities), focus on that.
- **Flexible Structure:** Organize information in the way that best serves the user's query - this could be chronological, by topic, by affected party, or any other logical structure.
- **Clear and Professional:** Use clear language, proper formatting (headers, bullet points, bold for emphasis)
- **Accurate Citations:** When mentioning information, reference which document it comes from
- **Completeness:** If the documents don't fully answer the query, explain what information IS available

**Formatting Tips:**
- Use markdown formatting for clarity
- Use **bold** for important terms, dates, and entities
- Use bullet points or numbered lists where appropriate
- Create sections/headers only if they help organize the response
- Adapt the level of detail to the user's query

Remember: Be flexible and adaptive in your response structure, but ALWAYS include the three mandatory elements (Publish Date, Reference, Key Points) somewhere in your response."""

        return await self.call_genai(prompt, temperature=0.3, max_tokens=4096)

    async def analyze_query(self, query: str) -> dict:
        """Analyze user query to determine search keywords."""
        prompt = f"""Analyze this query about SEBI circulars/notifications and extract search keywords.

Query: {query}

Return a JSON object with:
1. "keywords": list of important search terms
2. "topic": main topic (e.g., "securities", "mutual funds", "stock exchange", "insider trading")
3. "intent": what the user wants (e.g., "find circular", "understand regulation", "compliance requirements")

Return ONLY the JSON object, no other text."""

        response = await self.call_genai(prompt, temperature=0.1)

        try:
            import json
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
        except:
            pass

        return {
            "keywords": query.split(),
            "topic": "general",
            "intent": "search"
        }

    async def reformat_response(self, previous_response: str, follow_up_query: str, original_query: str) -> str:
        query_lower = follow_up_query.lower()

        if any(word in query_lower for word in ['only', 'just']) and any(word in query_lower for word in ['key', 'main', 'important', 'points']):
            prompt = f"""Extract ONLY the key points from the following SEBI analysis.

**Previous Response:**
{previous_response}

**Instructions:**
- Extract ONLY the key points/findings
- Remove all formatting, headers, disclaimers, and metadata
- Present as a clean, numbered list
- Keep each point concise but complete
- Preserve all important facts, dates, and figures
- Do NOT add any new information

Format as:
# 🔑 Key Points

1. [First key point]
2. [Second key point]
...

Keep it focused and actionable."""

            return await self.call_genai(prompt, temperature=0.1, max_tokens=2048)

        prompt = f"""You are reformatting a previous SEBI circular analysis based on a user's follow-up request.

**Original Query:** {original_query}

**Previous Response:**
{previous_response}

**User's Follow-Up Request:** {follow_up_query}

**Your Task:**
Reformat, restructure, or transform the above response according to the user's follow-up request.

Common requests:
- "in email format" → Convert to professional email with Subject, Dear [Recipient], body, signature
- "make it shorter/brief" → Create concise summary with key points only
- "in table format" → Organize information in markdown table
- "in bullet points" → Convert to clear bullet list
- "simpler language" → Simplify technical terms while keeping facts
- "more detailed" → Expand on key points with more explanation
- "only key points" → Extract just the essential information

**Important:**
- Preserve ALL factual information, dates, references, and URLs from the original
- Maintain the same level of accuracy
- Adjust ONLY the format/structure/style as requested
- Do NOT add new information not in the original response
- Do NOT perform new research or search

Format your output according to what the user requested."""

        return await self.call_genai(prompt, temperature=0.2, max_tokens=4096)


ai_service = AIService()
