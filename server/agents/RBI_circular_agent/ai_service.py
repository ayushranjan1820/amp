"""AI service for RBI Circular Agent — delegates to shared BaseAIService."""
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
        prompt = f"""You are an expert at analyzing RBI (Reserve Bank of India) circulars and notifications.

User Query: {query}

RBI Notification Content:
{content}

Provide a clear, professional summary that:
1. Directly addresses the user's query
2. Highlights the key points and implications
3. Mentions important dates, deadlines, or compliance requirements
4. Notes which entities/institutions are affected
5. Summarizes any actions required

**CRITICAL - REFERENCE LINKS:**
- Every point or fact MUST include an inline source link in [Title](URL) format
- If the source URL is available in the content, use it. Otherwise reference the RBI notification by its circular number.

Format your response in a clear, structured manner using markdown:
- Use headers for main sections
- Use bullet points for lists, each with a source reference link
- Highlight important terms in bold
- Include relevant dates and deadlines prominently

Keep the summary comprehensive but concise."""

        return await self.call_genai(prompt, temperature=0.2)

    async def summarize_multiple_documents(self, combined_content: str, query: str) -> str:
        """Summarize multiple documents based on user query."""
        from datetime import datetime
        current_year = datetime.now().year
        current_month = datetime.now().strftime("%B %Y")

        prompt = f"""You are an expert at analyzing RBI (Reserve Bank of India) circulars and notifications.

User Query: {query}
Current Date: {current_month} (Year: {current_year})

I have retrieved the following RBI documents that may be relevant:

{combined_content}

Based on these documents, provide a comprehensive response that:
1. Directly addresses the user's query
2. Presents the COMPLETE REGULATORY TIMELINE showing how regulations evolved on this topic
3. Identifies the BASE framework, major amendments, and the LATEST CONSOLIDATED direction
4. Synthesizes information from all relevant documents
5. Highlights the key points, regulations, and guidelines
6. Mentions important dates, deadlines, or compliance requirements
7. Notes which entities/institutions are affected
8. Summarizes any actions required

**CRITICAL - REGULATORY TIMELINE:**
- Always show the chronological evolution: original framework → amendments → latest consolidated position
- If a newer consolidated direction supersedes earlier fragmented guidelines, state this clearly
- The LATEST framework in force must be prominently highlighted as the current regulatory position
- Never present only older regulations while ignoring newer consolidated ones

**CRITICAL - REFERENCE LINKS:**
- EVERY point, fact, or piece of information MUST include an inline source link
- Format: [Document Title](URL) after the relevant statement
- Example: "NBFCs must maintain minimum capital of ₹10 crore ([Master Direction - NBFC](https://rbi.org.in/...))"
- Do NOT present any information without a clickable source reference

**RECENCY:**
- If user asks for "latest" circulars, prioritize {current_year} and {current_year - 1} documents
- Clearly mark dates on all circulars. Do NOT present old circulars as "latest"
- The latest consolidated framework is the most important finding — highlight it prominently

If the documents don't directly answer the query, explain what information is available.

Format your response in a clear, structured manner using markdown:
- Start with a regulatory timeline/evolution summary
- Highlight the latest/current regulatory position prominently
- Use headers for main sections
- Use bullet points for lists with source links on each point
- Highlight important terms in bold
- Include relevant dates and deadlines prominently

Keep the response comprehensive but focused on answering the user's query."""

        return await self.call_genai(prompt, temperature=0.2, max_tokens=6144)

    async def extract_key_points_and_format(self, search_results: List[Dict[str, Any]], query: str) -> str:
        content_parts = []
        for i, result in enumerate(search_results, 1):
            title = result.get('title', 'Unknown')
            url = result.get('url', '')
            date = result.get('date', 'Date not available')
            snippet = result.get('snippet', '')
            content = result.get('content', '')

            source_type = result.get('source_type', 'web')
            source_label = {
                'official': '⭐ Official RBI',
                'legal': '📜 Trusted Legal',
                'financial_media': '📰 Financial Media',
                'web': '🌐 Web'
            }.get(source_type, '🌐 Web')

            doc_info = f"""
Document {i}: {title}
URL: {url}
Date: {date}
Source Type: {source_label}
"""
            if snippet:
                doc_info += f"Summary: {snippet}\n"
            if content:
                doc_info += f"Content: {content}\n"

            content_parts.append(doc_info)

        combined_content = "\n---\n".join(content_parts)

        from datetime import datetime
        current_year = datetime.now().year
        current_month = datetime.now().strftime("%B %Y")

        prompt = f"""You are an expert analyst specializing in RBI (Reserve Bank of India) regulations and circulars.

**User Query:** {query}

**Current Date Context:** {current_month} (Year: {current_year})

**Retrieved Documents from Multiple Trusted Sources:**
(Sources include: Official RBI website, trusted legal databases, financial media, and regulatory analysis sites)

{combined_content}

**Your Task:**
Analyze the above documents and provide a comprehensive, TOPIC-FOCUSED response that directly addresses the user's query.

**SOURCE RELIABILITY:**
- Prioritize ⭐ Official RBI sources for exact circular references, dates, and regulatory text
- Use 📜 Trusted Legal and 📰 Financial Media sources for regulatory analysis, timeline context, and interpretation
- Cross-reference across sources for accuracy — if multiple sources confirm a regulation, it's more reliable
- Always cite the original RBI circular reference number when available, even if the information came from a secondary source

**CRITICAL: REGULATORY TIMELINE / EVOLUTION**
- Present the COMPLETE regulatory evolution for the topic, showing how regulations developed over time.
- Identify the BASE framework (original guidelines), subsequent AMENDMENTS/UPDATES, and the LATEST CONSOLIDATED framework.
- Clearly distinguish between: (a) Original guidelines, (b) Major amendments/updates, (c) Latest consolidated directions that supersede earlier ones.
- If a consolidated direction (e.g., "RBI Directions 2025") replaces or consolidates earlier fragmented guidelines, explicitly state this.
- Include a brief regulatory timeline table or chronological summary showing year-by-year evolution.
- NEVER present only the oldest regulations and ignore newer consolidated ones.

**CRITICAL: RELEVANCE FILTER**
- ONLY include circulars/directions that are DIRECTLY relevant to the user's specific query topic.
- If the user asks about "NBFC guidelines", do NOT include circulars meant for banks, AD Category-I banks, payment banks, etc. unless they explicitly apply to NBFCs.
- If a circular is meant for a different entity type, SKIP it entirely — do NOT list it as "may have implications" or "indirectly relevant".
- Focus ONLY on master directions, circulars, and notifications that specifically name or regulate the queried entity/topic.

**CRITICAL: RECENCY RULE**
- Today's date is in {current_month}. If the user asks for "latest" or "recent", ONLY include items from {current_year} or late {current_year - 1}.
- Do NOT present {current_year - 2} or older items as "latest". If all retrieved documents are old, explicitly state that and present the most recent available ones with their actual dates clearly marked.
- Sort results by date (newest first).
- The LATEST CONSOLIDATED FRAMEWORK is the most important — always identify and highlight it prominently.

**CRITICAL: COMPREHENSIVE COVERAGE**
- Cover ALL major regulatory areas found in the documents: governance, capital adequacy, risk management, prudential norms, asset classification, registration, compliance, outsourcing, reporting, etc.
- Group related regulations by theme/topic for clarity.
- Don't just list circulars — extract and present the KEY REGULATORY REQUIREMENTS from each.

**MANDATORY: REFERENCE LINKS ON EVERY POINT**
Every single piece of information, key point, or fact you mention MUST include its source reference link:
- Use inline markdown links: [Circular Title/Reference Number](URL)
- Example: "NBFCs must maintain a minimum CRAR of 15% ([RBI/2025-26/XX - Master Direction on NBFC](https://rbi.org.in/...))"
- Do NOT present any point without a traceable source link — this is non-negotiable.

**MANDATORY ELEMENTS:**

1. **📅 Regulatory Timeline:** Show the chronological evolution of regulations on this topic (year → regulation → significance)
2. **⭐ Latest Position:** Clearly identify and highlight the MOST RECENT/CURRENT regulatory framework in force
3. **📅 Publish Date(s):** Mention the publication date prominently for each circular/notification
4. **🔗 Reference(s):** Every point must have an inline link to its source document
5. **🔑 Key Points:** Extract the most important regulatory requirements (minimum 5-8 points), each with its source link

**Response Guidelines:**
- **Timeline First:** Start with a regulatory evolution summary showing how rules developed
- **Latest Framework Highlighted:** The most recent consolidated direction should be prominently featured
- **Topic-Focused:** Only include regulations directly applicable to the queried entity/topic
- **Organized by Theme:** Group related regulations (e.g., Capital, Governance, Risk, Compliance, etc.)
- **Clear and Professional:** Headers, bullet points, bold for emphasis
- **Actionable:** Focus on what entities need to DO or COMPLY with

**Formatting:**
- Use markdown headers (##) to organize sections
- Start with a "## 📊 Regulatory Timeline" section showing chronological evolution
- Follow with "## ⭐ Latest Regulatory Position" highlighting the current framework
- Then organize detailed requirements by regulatory theme
- Use bullet points with source links on each point
- Use **bold** for important terms, dates, deadlines, thresholds

Remember: Be STRICTLY topic-relevant. Filter out unrelated circulars. EVERY point needs a source link. Show the COMPLETE regulatory evolution, not just the oldest circulars."""

        return await self.call_genai(prompt, temperature=0.3, max_tokens=6144)

    async def analyze_query(self, query: str) -> dict:
        """Analyze user query to determine search keywords."""
        prompt = f"""Analyze this query about RBI circulars/notifications and extract search keywords.

Query: {query}

Return a JSON object with:
1. "keywords": list of important search terms
2. "topic": main topic (e.g., "banking", "forex", "payment systems", "monetary policy")
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
            prompt = f"""Extract ONLY the key points from the following RBI analysis.

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

        prompt = f"""You are reformatting a previous RBI circular analysis based on a user's follow-up request.

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
