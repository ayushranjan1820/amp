"""Meeting Prep Agent — external facts for research phases come only from the Perplexity **Search** API
(`perplexity` SDK `search.create`). No other web search backends, no Perplexity Chat completions for
retrieval, and no scraping third-party pages for enrichment."""
import asyncio
import re
import uuid
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from agents.local_llm import describe_missing_llm_credentials, get_llm_provider

from agents.Company_research_agent.models import NewsCard

from .tools.perplexity_search import meeting_perplexity_search
from .tools.email_sender import send_meeting_prep_email, format_meeting_prep_as_html
from .ai_service import meeting_prep_ai_service
from .models import MeetingPrepResponse, ThinkingStep
from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS


class MeetingPrepAgent:

    def __init__(self):
        self.search = meeting_perplexity_search
        self.ai = meeting_prep_ai_service
        self.sessions: Dict[str, Dict[str, Any]] = {}

        _llm_labels = {"pwc_genai": "PwC GenAI", "local_llm": "local LLM", "ollama_cloud": "Ollama Cloud"}
        if self.ai.llm_configured:
            prov = get_llm_provider()
            print(f"🤝 Meeting Prep Agent — LLM: {_llm_labels.get(prov, prov)}")
        else:
            print(f"⚠️ Meeting Prep Agent — {describe_missing_llm_credentials()}")

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "phase": "initial",
                "context": {},
                "history": [],
                "last_report": "",
            }
        return self.sessions[session_id]

    @staticmethod
    def _search_provider() -> str:
        raw = (os.getenv("MEETING_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "free_ollama"
        if raw in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "free_duckduckgo"
        return "perplexity"

    @staticmethod
    def _search_tool_name() -> str:
        provider = MeetingPrepAgent._search_provider()
        if provider == "free_ollama":
            return "ollama_web_search"
        if provider == "free_duckduckgo":
            return "duckduckgo_web_search"
        return "perplexity_search"

    @staticmethod
    def _search_provider_label() -> str:
        provider = MeetingPrepAgent._search_provider()
        if provider == "free_ollama":
            return "Ollama web"
        if provider == "free_duckduckgo":
            return "DuckDuckGo"
        return "Perplexity"

    def _is_share_request(self, query: str) -> bool:
        share_patterns = [
            r'^(share|send|email|forward|mail)\s+(it|this|the\s+report|report|results|brief|talking\s+points)',
            r'^(share|send|email|forward|mail)\s+(to|with)\s+',
            r'^(can you |please )?(share|send|email|forward|mail)\s+',
            r'(share|send|email|forward|mail)\s+(it|this|the\s+report|report|brief|talking\s+points)\s+(to|with)\s+',
            r'(send|share|email|forward|mail)\s+.*@',
        ]
        q = query.lower().strip()
        return any(re.search(p, q) for p in share_patterns)

    def _extract_emails_from_query(self, query: str) -> List[str]:
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return list(set(re.findall(email_pattern, query)))

    async def _generate_email_html(self, person_label: str, company: str, topic: str, markdown_report: str) -> str:
        prompt = f"""Convert the following meeting preparation brief into a polished, executive-ready HTML email format.

RULES:
1. DO NOT include email headers (NO "To:", "From:", "Subject:", "Date:")
2. Use clean, professional inline CSS styling
3. Use proper heading hierarchy (h2, h3)
4. Make data points and key numbers bold
5. Use bullet points for lists
6. Keep all source links as clickable hyperlinks
7. Use a clean color scheme with subtle section borders
8. Make emojis/icons from headings into styled spans
9. Keep all content — do not summarize or shorten

MEETING BRIEF CONTENT:
{markdown_report}"""

        html_content = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=8192)
        return format_meeting_prep_as_html(person_label, company, topic, html_content)

    async def _handle_share_request(self, query: str, session: Dict[str, Any], thinking_steps: List, tool_results: List) -> Optional[MeetingPrepResponse]:
        extracted_emails = self._extract_emails_from_query(query)
        if not extracted_emails:
            return None

        last_report = session.get("last_report", "")
        if not last_report:
            return None

        context = session.get("context", {})
        person_name = context.get("person_name", "")
        person_role = context.get("person_role", "")
        company = context.get("company", "the company")
        topics = context.get("specific_topics", [])
        topic_str = ", ".join(topics) if topics else context.get("meeting_purpose", "meeting")

        person_label = person_name or person_role or "contact"
        if person_role and person_name:
            person_label = f"{person_name} ({person_role})"

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content=f"User wants to share the meeting brief with {', '.join(extracted_emails)}"
        ))

        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content=f"Converting meeting brief to HTML email and sending to {', '.join(extracted_emails)}",
            tool_name="email_sender",
            tool_input=f'{{"recipients": {extracted_emails}}}'
        ))

        tool_results.append({"tool": "email_sender", "input": {"recipients": extracted_emails}, "status": "running"})

        email_html = await self._generate_email_html(person_label, company, topic_str, last_report)

        subject = f"Meeting Brief: {person_label} at {company} — {topic_str}"

        email_result = send_meeting_prep_email(
            recipients=extracted_emails,
            subject=subject,
            html_content=email_html
        )

        if email_result["success"]:
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"message": email_result["message"]}

            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Email sent successfully to {', '.join(extracted_emails)}",
                tool_name="email_sender"
            ))

            response_text = f"The meeting preparation brief for **{person_label}** at **{company}** has been sent to **{', '.join(extracted_emails)}**."
        else:
            tool_results[-1]["status"] = "failed"
            tool_results[-1]["result"] = {"error": email_result.get("error")}

            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Email delivery failed: {email_result.get('error')}",
                tool_name="email_sender"
            ))

            response_text = f"Failed to send the meeting brief: {email_result.get('error', 'Unknown error')}. Please check the email configuration."

        return MeetingPrepResponse(
            success=email_result["success"],
            query=query,
            response=response_text,
            session_id=None,
            thinking_steps=thinking_steps,
            tool_results=tool_results,
            phase="complete",
            email_sent=email_result["success"],
            email_recipients=extracted_emails if email_result["success"] else [],
        )

    def _format_search_data(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "No data found."
        # Present dated sources first (newest date string first for typical ISO-style values); undated last.
        def _recency_key(row: Dict[str, Any]):
            d = row.get("date")
            if d is None or d == "":
                return (0,)  # sorts last when reverse=True (below any (1, ...) tuple)
            return (1, str(d))

        ordered = sorted(results, key=_recency_key, reverse=True)

        parts = []
        for i, r in enumerate(ordered, 1):
            part = f"Source {i}: {r.get('title', 'N/A')}\n"
            part += f"URL: {r.get('url', '')}\n"
            if r.get('date'):
                part += f"Date: {r['date']}\n"
            if r.get('content'):
                part += f"Content: {r['content']}\n"
            elif r.get('snippet'):
                part += f"Snippet: {r['snippet']}\n"
            parts.append(part)
        return "\n---\n".join(parts)

    async def _clarify_context(self, query: str, session: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are a Meeting Preparation Assistant (Agent 1 — Clarification Agent).

The user wants help preparing for a meeting. Analyze their input and extract as much structured information as possible.

USER INPUT: "{query}"

CONVERSATION HISTORY:
{chr(10).join([f"- {h['role']}: {h['content']}" for h in session.get('history', [])]) or 'None'}

Extract the following fields from the user's input AND conversation history. If information was provided in earlier messages, USE it.
Return a JSON object with these fields:
- "person_name": Name of the person being met (or "" if not mentioned)
- "person_role": Their role/title (e.g., "CFO", "CEO", "VP Engineering") (or "" if not mentioned)
- "company": Company name (or "" if not mentioned)
- "industry": Industry/domain (e.g., "Banking", "Technology", "Healthcare") — infer from company name if possible
- "meeting_purpose": Purpose of the meeting (e.g., "Sales pitch", "Partnership discussion", "Strategy review")
- "desired_outcome": What the user wants to achieve (e.g., "Close deal", "Explore partnership", "Gather information")
- "meeting_format": Format (e.g., "In-person", "Video call", "Phone call") (or "" if not mentioned)
- "specific_topics": List of specific topics mentioned (array of strings)
- "user_value_proposition": What the user/their company offers (or "" if not mentioned)
- "has_enough_context": true if we have at minimum: person_name OR person_role, AND company, AND at least some sense of purpose/topic. false if critical information is missing.
- "missing_fields": List of still-missing critical fields that would help generate better talking points
- "follow_up_question": If has_enough_context is false, provide exactly ONE natural, conversational follow-up question targeting the single most critical missing piece of information. If true, provide an empty string "".

IMPORTANT RULES:
1. Be generous with "has_enough_context". If the user provides a person + company + any topic/purpose, that's enough to proceed.
2. If the user says something like "I am meeting the CFO of Bandhan Bank to discuss rural banking" — that IS enough context (person_role=CFO, company=Bandhan Bank, topic=rural banking).
3. Ask only ONE question at a time. Pick the most important missing field and ask about that only. Do NOT combine multiple questions.
4. Priority order for missing fields: company > person (name/role) > topic/purpose > desired outcome > other details.

Return ONLY valid JSON, no markdown formatting."""

        result = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=2048)

        try:
            json_match = re.search(r'\{[\s\S]*\}', result)
            if json_match:
                import json
                return json.loads(json_match.group())
        except Exception as e:
            print(f"  ⚠️ Context extraction error: {e}")

        return {"has_enough_context": True, "missing_fields": [], "follow_up_questions": []}

    async def _research_dimensions(self, context: Dict[str, Any], thinking_steps: List, tool_results: List) -> Dict[str, str]:
        person_name = context.get("person_name", "")
        person_role = context.get("person_role", "")
        company = context.get("company", "")
        topics = context.get("specific_topics", [])
        industry = context.get("industry", "")
        topic_str = ", ".join(topics) if topics else context.get("meeting_purpose", "business discussion")

        search_tool_name = self._search_tool_name()
        provider_label = self._search_provider_label()

        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content=f"Launching 12 parallel {provider_label} research dimensions for {person_name or person_role} at {company}",
            tool_name=search_tool_name
        ))

        search_labels = [
            "person_profile", "company_overview", "topic_research", "company_topic", "forecast",
            "client_challenges", "current_status", "current_technology", "best_technology", "references",
            "peer_identification", "peer_financials"
        ]
        for label in search_labels:
            tool_results.append({"tool": search_tool_name, "input": {"dimension": label}, "status": "running"})

        base_idx = len(tool_results) - len(search_labels)

        print(f"📡 Launching 12 parallel research dimensions...")

        (
            person_data, company_data, topic_data, company_topic_data, forecast_data,
            challenges_data, status_data, current_tech_data, best_tech_data, references_data,
            peer_list_data, peer_financials_data
        ) = await asyncio.gather(
            self.search.search_person(person_name or person_role, person_role, company),
            self.search.search_company(company),
            self.search.search_topic(topic_str, industry),
            self.search.search_company_topic(company, topic_str),
            self.search.search_forecast(company, topic_str),
            self.search.search_client_challenges(company, topic_str, industry),
            self.search.search_current_status(company, topic_str),
            self.search.search_current_technology(company, topic_str, industry),
            self.search.search_best_technology(topic_str, industry),
            self.search.search_references(topic_str, industry),
            self.search.search_peer_list(company, industry),
            self.search.search_peer_financials(company, "", industry),
        )

        results_map = {
            "person_profile": person_data,
            "company_overview": company_data,
            "topic_research": topic_data,
            "company_topic": company_topic_data,
            "forecast": forecast_data,
            "client_challenges": challenges_data,
            "current_status": status_data,
            "current_technology": current_tech_data,
            "best_technology": best_tech_data,
            "references": references_data,
            "peer_identification": peer_list_data,
            "peer_financials": peer_financials_data,
        }

        for i, (label, data) in enumerate(results_map.items()):
            tool_results[base_idx + i]["status"] = "completed"
            tool_results[base_idx + i]["result"] = {"found": len(data)}

        total = sum(len(d) for d in results_map.values())
        print(f"✅ Total search results: {total} across 12 dimensions")

        thinking_steps.append(ThinkingStep(
            type="tool_result",
            content=(
                f"Research complete: person({len(person_data)}), company({len(company_data)}), "
                f"topic({len(topic_data)}), company+topic({len(company_topic_data)}), forecast({len(forecast_data)}), "
                f"challenges({len(challenges_data)}), current_status({len(status_data)}), "
                f"current_tech({len(current_tech_data)}), best_tech({len(best_tech_data)}), "
                f"references({len(references_data)}), peers({len(peer_list_data)}), "
                f"peer_financials({len(peer_financials_data)}) — {total} total results"
            ),
            tool_name=search_tool_name
        ))

        return {
            "person": self._format_search_data(person_data),
            "company": self._format_search_data(company_data),
            "topic": self._format_search_data(topic_data),
            "company_topic": self._format_search_data(company_topic_data),
            "forecast": self._format_search_data(forecast_data),
            "challenges": self._format_search_data(challenges_data),
            "current_status": self._format_search_data(status_data),
            "current_technology": self._format_search_data(current_tech_data),
            "best_technology": self._format_search_data(best_tech_data),
            "references": self._format_search_data(references_data),
            "peer_identification": self._format_search_data(peer_list_data),
            "peer_financials": self._format_search_data(peer_financials_data),
        }

    async def _generate_peer_benchmarking(self, context: Dict[str, Any], research: Dict[str, str]) -> str:
        company = context.get("company", "the company")
        industry = context.get("industry", "")

        prompt = f"""You are a Financial Analyst specializing in peer benchmarking and competitive positioning.

**TASK:** Analyze the peer landscape for **{company}** in the **{industry}** industry and create a comprehensive peer benchmarking report.

**RAW RESEARCH DATA:**

### Peer Identification Data:
{research.get('peer_identification', 'No data available')}

### Financial Comparison Data:
{research.get('peer_financials', 'No data available')}

### Company Overview (for context):
{research.get('company', 'No data available')}

---

**GENERATE THE FOLLOWING STRUCTURED ANALYSIS:**

## 🏆 Peer Benchmarking: {company}

### 1. Identified Peer Group
List the **5-8 closest peers/competitors** of {company}. For each peer, provide:
- **Company Name**
- **Why they are a peer** (market segment, size, geography, product overlap)
- **Market Cap / Revenue range** (approximate)

### 2. Financial Benchmarking (Latest Financial Year)
Create a **comparison table** with {company} and its top peers across these metrics (use the latest available FY data — FY2024 or FY2025):

| Metric | {company} | Peer 1 | Peer 2 | Peer 3 | Peer 4 | Peer 5 |
|--------|-----------|--------|--------|--------|--------|--------|
| Revenue | | | | | | |
| Revenue Growth (YoY%) | | | | | | |
| Net Profit | | | | | | |
| Net Profit Margin (%) | | | | | | |
| ROE (%) | | | | | | |
| ROA (%) | | | | | | |
| Market Cap | | | | | | |
| P/E Ratio | | | | | | |

*Add industry-specific metrics if applicable (e.g., NPA% for banks, ARPU for telecom, GMV for e-commerce).*

### 3. Competitive Positioning
Where does **{company}** stand among its peers?
- **Strengths**: Areas where {company} outperforms peers (be specific with numbers)
- **Gaps**: Areas where {company} lags behind peers (be specific with numbers)
- **Market Position**: Rank/quartile positioning across key metrics

### 4. Key Takeaways for the Meeting
3-4 bullet points that can be used as conversation starters or insights during the meeting based on the peer comparison.

---

{MANDATORY_MARKDOWN_SOURCE_LINKS}

---

**RECENCY (CRITICAL):**
Web research was tuned for maximum freshness. Prefer the **newest** figures, filings, and news (including items from the last few days). When sources disagree, trust the more recent dated source unless the older one is the authoritative filing. State the period or "as of" date for key numbers.

**FORMATTING RULES:**
1. Use clean markdown with proper tables
2. Bold all company names and key numbers
3. Include source references as inline links [Source](URL) where available — never bare `[Source 1]` without `(https://...)`
4. Use actual numbers from research — do NOT fabricate data. If data is not available for a metric, write "N/A"
5. Clearly state the financial year being referenced
"""

        return await self.ai.call_genai(prompt, temperature=0.2, max_tokens=4096)

    async def _generate_talking_points(
        self,
        context: Dict[str, Any],
        research: Dict[str, str],
    ) -> str:
        person_name = context.get("person_name", "the person")
        person_role = context.get("person_role", "")
        company = context.get("company", "the company")
        topics = context.get("specific_topics", [])
        purpose = context.get("meeting_purpose", "business discussion")
        outcome = context.get("desired_outcome", "")
        value_prop = context.get("user_value_proposition", "")
        industry = context.get("industry", "")
        topic_str = ", ".join(topics) if topics else purpose

        person_label = f"{person_name}" if person_name else person_role
        if person_role and person_name:
            person_label = f"{person_name} ({person_role})"

        prompt = f"""You are Agent 3 — a Talking-Points Builder for meeting preparation. You are a senior strategy consultant preparing a comprehensive meeting brief.

**MEETING CONTEXT:**
- Meeting with: {person_label} at {company}
- Industry: {industry}
- Purpose: {purpose}
- Topics: {topic_str}
- Desired outcome: {outcome or 'Not specified'}
- User's value proposition: {value_prop or 'Not specified'}

**RESEARCH DATA GATHERED:**

### Dimension 1 — Person Profile ({person_label}):
{research['person']}

### Dimension 2 — Company Overview ({company}):
{research['company']}

### Dimension 3 — Topic/Market Research ({topic_str}):
{research['topic']}

### Dimension 4 — {company} + {topic_str} Specific:
{research['company_topic']}

### Dimension 5 — Forecast & Future Strategy:
{research['forecast']}

### Dimension 6 — Current Challenges of {company} on {topic_str}:
{research['challenges']}

### Dimension 7 — How {company} is Doing Now on {topic_str}:
{research['current_status']}

### Dimension 8 — Technology {company} is Currently Using:
{research['current_technology']}

### Dimension 9 — Best Available Technology for {topic_str}:
{research['best_technology']}

### Dimension 10 — Indian & Global Reference Cases for {topic_str}:
{research['references']}

---

{MANDATORY_MARKDOWN_SOURCE_LINKS}

---

**IMAGES / MEDIA:** Research text is sourced **only** from the Perplexity **Search** API. Do **not** embed images unless a direct `https://` image URL appears **verbatim** in the research excerpts above. Otherwise omit images entirely — do not invent or guess URLs.

---

**GENERATE A COMPREHENSIVE MEETING PREPARATION BRIEF WITH THE FOLLOWING SECTIONS:**

## 👤 Person Brief: {person_label}
A concise profile of who you're meeting — their background, expertise, recent activities, key statements, and communication style insights. What motivates them? What topics are they passionate about?

## 🏢 Company Snapshot: {company}
Key facts about the company — recent performance, strategic direction, major news, and market position. Focus on what's relevant to the meeting topic.

## 📊 Topic Deep-Dive: {topic_str}
Market landscape, key trends, challenges, and opportunities in the topic area. Include relevant data points and statistics.

## ⚠️ Current Challenges Faced by {company}
Based on research, outline the specific challenges, pain points, and obstacles {company} is currently facing related to {topic_str}. Include regulatory hurdles, operational issues, market pressures, and competitive threats. Be specific with data and examples.

## 📍 How {company} is Doing Right Now
Current status, recent progress, achievements, and performance metrics of {company} on {topic_str}. What have they accomplished? Where do they stand compared to peers?

## 💻 Technology Landscape
### Currently Used by {company}:
What technology platforms, tools, systems, and vendors {company} is currently using for {topic_str}. Include known tech partnerships and infrastructure choices.

### Best Available Technologies:
What are the leading technologies, platforms, and solutions available in the market for {topic_str}? Compare with what {company} currently uses. Highlight gaps and upgrade opportunities.

## 🌍 Indian & Global Reference Cases
Provide specific case studies and success stories — both from India and globally — of organizations that have excelled in {topic_str}. Include company names, what they did, outcomes achieved, and lessons applicable to {company}.

## 🎯 Talking Points

### 🚀 1) Intelligent Warm Opening (2-3 options)
Personalized conversation starters based on the person's recent activities, interviews, or company announcements. These should demonstrate you've done your homework and create immediate rapport.

### 📊 2) Data-Backed Insights (3-4 points)
Specific data points, statistics, and market insights that demonstrate expertise and add value to the conversation. Each point should reference source data.

### 🧠 3) Strategy & Growth Discussion (3-4 points)
Strategic questions and observations about the company's direction, growth plans, and market positioning. These should invite discussion and show strategic thinking.

### 💡 4) Value Proposition Alignment (3-4 points)
How your offerings or expertise align with their stated priorities and challenges. Frame as solutions to their specific pain points. Reference the challenges and technology gaps identified above.

### 📌 5) Risk & Challenge Discussion (2-3 points)
Thoughtful questions about the specific challenges identified in the research. Shows you understand their business deeply and have done your homework.

### 🌱 6) Future-Focused Innovation Points (2-3 points)
Forward-looking topics about technology, digital transformation, regulatory changes, or emerging trends relevant to their business. Reference the best available technologies and global benchmarks.

### 🌍 7) Reference-Based Discussion Points (2-3 points)
Bring up relevant Indian and global success stories that {company} can learn from. Frame as "Here's what [Company X] did successfully with [topic]..." conversation points.

## ⚡ Quick Reference Card
A bullet-point summary of the top 7 most impactful talking points for quick review before the meeting.

## 🚫 Topics to Avoid
Any sensitive areas, recent controversies, or topics that might derail the meeting.

---

**RECENCY (CRITICAL):**
The research snippets are ordered and retrieved for **up-to-the-minute relevance** (including news from the last 24–72 hours when available). When building the brief:
- Prefer facts tied to the **newest** sources and dates in the research; do not lead with stale trivia if newer information contradicts or updates it.
- For time-sensitive items (leadership moves, earnings, product launches, regulations), say how recent they are when the source date supports it.
- If only older material exists for a point, say so briefly rather than presenting it as current.

**FORMATTING RULES:**
1. Use clean markdown throughout
2. Each talking point should be actionable and specific — NOT generic
3. Include source references as inline links `[label](https://...)` for data-backed claims — never output unlinked `[Source N]`
4. Use conversational, natural language for talking points — as if coaching someone before a meeting
5. Bold key numbers, company names, and critical terms
6. Each talking point should include a brief "Why this works:" explanation in italics
7. Keep the tone professional but warm — this is about building relationships
8. Follow **IMAGE PLACEMENT** rules when candidate URLs are provided; otherwise skip images
"""

        return await self.ai.call_genai(prompt, temperature=0.3, max_tokens=8192)

    async def prepare(
        self,
        query: str,
        session_id: Optional[str] = None,
        clear_history: bool = False,
        email_recipients: Optional[List[str]] = None,
    ) -> MeetingPrepResponse:

        current_session_id = session_id or str(uuid.uuid4())
        session = self._get_session(current_session_id)
        thinking_steps = []
        tool_results = []

        if clear_history:
            session["phase"] = "initial"
            session["context"] = {}
            session["history"] = []
            session["last_report"] = ""

        session["history"].append({"role": "user", "content": query})

        if self._is_share_request(query):
            share_result = await self._handle_share_request(query, session, thinking_steps, tool_results)
            if share_result:
                share_result.session_id = current_session_id
                return share_result

        if not self.search.is_configured():
            provider = (os.getenv("MEETING_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
            if provider in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
                msg = "**Meeting Prep Agent is not available.** Free web search is selected but `OLLAMA_API_KEY` is not configured."
            elif provider in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
                msg = "**Meeting Prep Agent is not available.** DuckDuckGo free web search is selected but the `ddgs` package is not installed on the server."
            else:
                msg = "**Meeting Prep Agent is not available.** Perplexity web search is selected but `PERPLEXITY_API_KEY` is not configured."
            return MeetingPrepResponse(
                success=False, query=query,
                response=msg,
                session_id=current_session_id,
                thinking_steps=[ThinkingStep(type="thinking", content="Web search credentials not configured for selected provider")],
            )

        if not self.ai.llm_configured:
            hint = describe_missing_llm_credentials()
            return MeetingPrepResponse(
                success=False, query=query,
                response=f"**Meeting Prep Agent is not available.** {hint}",
                session_id=current_session_id,
                thinking_steps=[
                    ThinkingStep(
                        type="thinking",
                        content=f"LLM not configured for provider `{get_llm_provider()}`",
                    )
                ],
            )

        print(f"\n{'='*60}")
        print(f"🤝 Meeting Prep Request: {query}")
        print(f"{'='*60}")

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content=f"Phase 1 — Analyzing meeting context from user input"
        ))

        tool_results.append({"tool": "context_analyzer", "input": {"query": query}, "status": "running"})

        context = await self._clarify_context(query, session)
        session["context"].update({k: v for k, v in context.items() if v})

        tool_results[-1]["status"] = "completed"
        tool_results[-1]["result"] = {"fields_found": len([v for v in context.values() if v])}

        merged_context = session["context"]
        has_enough = context.get("has_enough_context", False)

        company = merged_context.get("company", "")
        has_person = bool(merged_context.get("person_name") or merged_context.get("person_role"))
        has_topic = bool(merged_context.get("specific_topics") or merged_context.get("meeting_purpose"))

        if has_person and company and has_topic:
            has_enough = True

        if not has_enough:
            follow_up = context.get("follow_up_question", "") or context.get("follow_up_questions", [""])[0] if isinstance(context.get("follow_up_questions"), list) else ""
            missing = context.get("missing_fields", [])

            thinking_steps.append(ThinkingStep(
                type="thinking",
                content=f"Need more context. Missing: {', '.join(missing) if missing else 'key details'}. Asking one follow-up question."
            ))

            if follow_up:
                response_text = f"{follow_up}"
            elif not merged_context.get("company"):
                response_text = "Which company or organization is this meeting with?"
            elif not has_person:
                response_text = "Who will you be meeting with? (Their name or role would help)"
            else:
                response_text = "What's the main topic or purpose of this meeting?"

            session["phase"] = "clarification"
            session["history"].append({"role": "assistant", "content": response_text})

            return MeetingPrepResponse(
                success=True, query=query,
                response=response_text,
                session_id=current_session_id,
                thinking_steps=thinking_steps,
                tool_results=tool_results,
                phase="clarification"
            )

        person_label = merged_context.get("person_name", merged_context.get("person_role", "contact"))
        company = merged_context.get("company", "the company")

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content=f"Context sufficient. Meeting: {person_label} at {company}. Starting Phase 2 — Multi-dimensional research."
        ))

        print(f"✅ Context: {person_label} at {company}")
        print(f"📍 Topics: {merged_context.get('specific_topics', [])}")

        research = await self._research_dimensions(merged_context, thinking_steps, tool_results)

        provider_label = self._search_provider_label()
        news_tool_name = self._search_tool_name()
        print("=" * 50)
        print(f"📰 Dedicated latest-news search ({provider_label}) — {company}")
        print("=" * 50)
        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content=f"Fetching 5 latest news articles for {company}",
            tool_name=news_tool_name,
            tool_input=f'{{"company": "{company}", "count": 5}}'
        ))
        tool_results.append({"tool": news_tool_name, "input": {"company": company}, "status": "running"})
        latest_news_cards: List[NewsCard] = []
        try:
            news_cards_data = await self.search.search_news_cards(company)
            latest_news_cards = [
                NewsCard(
                    title=nc.get('title', ''),
                    url=nc.get('url', ''),
                    date=nc.get('date'),
                    snippet=(nc.get('snippet', '') or '')[:250],
                    source=nc.get('source', ''),
                    image_url=nc.get('image_url'),
                )
                for nc in news_cards_data[:5]
                if nc.get('title')
            ]
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"news_found": len(latest_news_cards)}
            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Found {len(latest_news_cards)} latest news articles for {company}",
                tool_name=news_tool_name
            ))
            print(f"📰 News cards: {len(latest_news_cards)} articles")
        except Exception as e:
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"error": str(e)}
            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Latest news fetch failed: {e}",
                tool_name=news_tool_name
            ))
            print(f"⚠️ News cards search failed: {e}")

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content="Phase 3 — Synthesizing research into talking points + peer benchmarking (2 parallel LLM calls)"
        ))

        tool_results.append({"tool": "talking_points_builder", "input": {"context": "all_research"}, "status": "running"})
        tool_results.append({"tool": "peer_benchmarking_analyzer", "input": {"context": "peer_data"}, "status": "running"})

        results = await asyncio.gather(
            self._generate_talking_points(merged_context, research),
            self._generate_peer_benchmarking(merged_context, research),
            return_exceptions=True,
        )

        talking_points = results[0] if isinstance(results[0], str) else ""
        peer_benchmarking = results[1] if isinstance(results[1], str) else ""

        if isinstance(results[0], Exception):
            print(f"  ⚠️ Talking points generation failed: {results[0]}")
            tool_results[-2]["status"] = "failed"
            tool_results[-2]["result"] = {"error": str(results[0])}
        else:
            tool_results[-2]["status"] = "completed"
            tool_results[-2]["result"] = {"length": len(talking_points)}

        if isinstance(results[1], Exception):
            print(f"  ⚠️ Peer benchmarking generation failed: {results[1]}")
            tool_results[-1]["status"] = "failed"
            tool_results[-1]["result"] = {"error": str(results[1])}
        else:
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"length": len(peer_benchmarking)}

        if peer_benchmarking:
            talking_points = talking_points.rstrip() + "\n\n---\n\n" + peer_benchmarking
        elif isinstance(results[1], Exception):
            talking_points = talking_points.rstrip() + "\n\n---\n\n*Peer benchmarking analysis could not be generated at this time.*"

        if not talking_points:
            talking_points = "Meeting preparation brief could not be generated. Please try again."

        thinking_steps.append(ThinkingStep(
            type="observation",
            content=f"Meeting brief generated ({len(talking_points)} chars){f' including peer benchmarking ({len(peer_benchmarking)} chars)' if peer_benchmarking else ''}"
        ))

        print(f"📝 Talking points generated: {len(talking_points)} characters{f' (incl. peer benchmarking: {len(peer_benchmarking)} chars)' if peer_benchmarking else ''}")

        session["phase"] = "complete"
        session["last_report"] = talking_points
        session["history"].append({"role": "assistant", "content": talking_points})

        email_sent = False
        email_recipients_sent = []

        extracted_emails = self._extract_emails_from_query(query)
        final_recipients = extracted_emails if extracted_emails else (email_recipients or [])

        if final_recipients:
            person_role = merged_context.get("person_role", "")
            person_name_full = person_label
            if person_role and person_label and person_role not in person_label:
                person_name_full = f"{person_label} ({person_role})"

            topics = merged_context.get("specific_topics", [])
            topic_str = ", ".join(topics) if topics else merged_context.get("meeting_purpose", "meeting")

            thinking_steps.append(ThinkingStep(
                type="tool_call",
                content=f"Sending meeting brief via email to {', '.join(final_recipients)}",
                tool_name="email_sender",
                tool_input=f'{{"recipients": {final_recipients}}}'
            ))

            tool_results.append({"tool": "email_sender", "input": {"recipients": final_recipients}, "status": "running"})

            email_html = await self._generate_email_html(person_name_full, company, topic_str, talking_points)

            subject = f"Meeting Brief: {person_name_full} at {company} — {topic_str}"

            email_result = send_meeting_prep_email(
                recipients=final_recipients,
                subject=subject,
                html_content=email_html
            )

            if email_result["success"]:
                email_sent = True
                email_recipients_sent = final_recipients
                tool_results[-1]["status"] = "completed"
                tool_results[-1]["result"] = {"message": email_result["message"]}
                thinking_steps.append(ThinkingStep(
                    type="tool_result",
                    content=f"Email sent successfully to {', '.join(final_recipients)}",
                    tool_name="email_sender"
                ))
                talking_points += f"\n\n---\n\n📧 **Meeting brief sent to:** {', '.join(final_recipients)}"
                print(f"📧 Email sent to: {', '.join(final_recipients)}")
            else:
                tool_results[-1]["status"] = "failed"
                tool_results[-1]["result"] = {"error": email_result.get("error")}
                thinking_steps.append(ThinkingStep(
                    type="tool_result",
                    content=f"Email delivery failed: {email_result.get('error')}",
                    tool_name="email_sender"
                ))
                talking_points += f"\n\n---\n\n⚠️ **Email delivery failed:** {email_result.get('error', 'Unknown error')}"

        return MeetingPrepResponse(
            success=True, query=query,
            response=talking_points,
            session_id=current_session_id,
            thinking_steps=thinking_steps,
            tool_results=tool_results,
            phase="complete",
            email_sent=email_sent,
            email_recipients=email_recipients_sent,
            report_image_urls=[],
            latest_news_cards=latest_news_cards,
        )


meeting_prep_agent = MeetingPrepAgent()
