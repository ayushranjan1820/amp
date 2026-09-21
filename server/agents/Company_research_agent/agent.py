import asyncio
import re
import uuid
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

from agents.local_llm import describe_missing_llm_credentials, get_llm_provider

from .tools.perplexity_search import company_perplexity_search
from .tools.email_sender import send_company_research_email, format_company_report_as_html
from .ai_service import company_ai_service
from .models import CompanyResearchResponse, ThinkingStep, NewsCard
from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS


class CompanyResearchAgent:

    def __init__(self):
        self.search = company_perplexity_search
        self.ai = company_ai_service
        self.sessions: Dict[str, Any] = {}
        self.last_reports: Dict[str, Dict[str, str]] = {}

        _llm_labels = {"pwc_genai": "PwC GenAI", "local_llm": "local LLM", "ollama_cloud": "Ollama Cloud"}
        if self.ai.llm_configured:
            prov = get_llm_provider()
            print(f"🏢 Company Research Agent — LLM: {_llm_labels.get(prov, prov)}")
        else:
            print(f"⚠️ Company Research Agent — {describe_missing_llm_credentials()}")

    @staticmethod
    async def _emit_trace_step(step: ThinkingStep) -> None:
        """Mirror thinking/tool steps onto the SSE LLM activity queue so they appear *before*
        LLM trace events while ``research()`` is running (see api._merge_async_generator_with_llm_queue)."""
        try:
            from agents.llm_activity_stream import emit_llm_activity

            await emit_llm_activity(step.model_dump(exclude_none=True))
        except Exception:
            pass

    def _is_share_request(self, query: str) -> bool:
        lower = query.lower().strip()
        share_patterns = [
            r'^(share|send|email|forward|mail)\s+(it|this|the\s+report|report|results)',
            r'^(share|send|email|forward|mail)\s+(to|with)\s+',
            r'^(can you |please )?(share|send|email|forward|mail)\s+',
        ]
        for pattern in share_patterns:
            if re.search(pattern, lower):
                return True
        return False

    def _extract_company_name(self, query: str) -> str:
        lower = query.lower()
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        cleaned = re.sub(email_pattern, '', query).strip()
        for prefix in [
            "research on ", "research about ", "research ",
            "company research on ", "company research about ", "company research ",
            "analyze ", "analysis of ", "analysis on ",
            "tell me about ", "information about ", "info on ",
            "details about ", "details on ", "profile of ",
        ]:
            if lower.startswith(prefix):
                name = query[len(prefix):].strip().rstrip('.!?')
                name = re.sub(email_pattern, '', name).strip()
                for suffix in ["and share", "and send", "and email", "and forward"]:
                    if name.lower().endswith(suffix):
                        name = name[:-(len(suffix))].strip()
                return name if name else cleaned
        cleaned = cleaned.rstrip('.!?').strip()
        return cleaned if cleaned else query.strip().rstrip('.!?')

    @staticmethod
    def _search_provider() -> str:
        raw = (os.getenv("COMPANY_RESEARCH_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if raw in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
            return "free_ollama"
        if raw in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
            return "free_duckduckgo"
        return "perplexity"

    @staticmethod
    def _search_tool_name() -> str:
        provider = CompanyResearchAgent._search_provider()
        if provider == "free_ollama":
            return "ollama_web_search"
        if provider == "free_duckduckgo":
            return "duckduckgo_web_search"
        return "perplexity_search"

    @staticmethod
    def _search_provider_label() -> str:
        provider = CompanyResearchAgent._search_provider()
        if provider == "free_ollama":
            return "Ollama web"
        if provider == "free_duckduckgo":
            return "DuckDuckGo"
        return "Perplexity"

    def _extract_emails_from_query(self, query: str) -> List[str]:
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        return list(set(re.findall(email_pattern, query)))

    def _fix_table_formatting(self, text: str) -> str:
        lines = text.split('\n')
        fixed = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('|') and stripped.endswith('|'):
                pipe_count = stripped.count('|')
                if pipe_count > 14:
                    parts = [p for p in stripped.split('|') if p != '']
                    sep_idx = next((i for i, p in enumerate(parts) if re.match(r'^[\s\-:]+$', p.strip())), None)
                    if sep_idx and sep_idx > 0 and len(parts) % sep_idx == 0 and len(parts) // sep_idx >= 3:
                        col_count = sep_idx
                        rows = [
                            '| ' + ' | '.join(c.strip() for c in parts[i:i + col_count]) + ' |'
                            for i in range(0, len(parts), col_count)
                        ]
                        fixed.extend(rows)
                        continue
            fixed.append(line)
        return '\n'.join(fixed)

    def _format_search_data(self, results: List[Dict[str, Any]]) -> str:
        if not results:
            return "No data found."
        parts = []
        for i, r in enumerate(results, 1):
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

    def _append_numbered_source_link_index(
        self, report: str, search_results_list: list
    ) -> str:
        """Append a numbered list of real URLs so UIs can link bare [Source N] when the model omits the URL."""
        urls: list = []
        seen: set = set()
        for _name, data in search_results_list:
            for r in data or []:
                u = (r or {}).get("url") or ""
                u = (u or "").strip()
                if u and (u.startswith("http://") or u.startswith("https://")) and u not in seen:
                    seen.add(u)
                    urls.append(u)
        if not urls:
            return report
        lines = [
            "",
            "---",
            "",
            "### Source links (numbered)",
            "",
            "Each number matches optional `[Source N]` citations in the report above.",
            "",
        ]
        for i, u in enumerate(urls, 1):
            lines.append(f"{i}. [Source {i}]({u})")
        return report.rstrip() + "\n" + "\n".join(lines)

    async def research(
        self,
        query: str,
        email_recipients: Optional[List[str]] = None,
        session_id: Optional[str] = None
    ) -> CompanyResearchResponse:

        current_session_id = session_id or str(uuid.uuid4())
        thinking_steps = []
        tool_results = []

        extracted_emails = self._extract_emails_from_query(query)

        if self._is_share_request(query) and extracted_emails:
            last_report = self.last_reports.get(current_session_id)
            if last_report:
                thinking_steps.append(ThinkingStep(
                    type="thinking",
                    content=f"User wants to share the previous report with {', '.join(extracted_emails)}"
                ))

                company_name = last_report["company_name"]
                report = last_report["report"]

                thinking_steps.append(ThinkingStep(
                    type="tool_call",
                    content=f"Sending previous report for {company_name} via email",
                    tool_name="email_sender",
                    tool_input=f'{{"recipients": {extracted_emails}}}'
                ))

                tool_results.append({"tool": "email_sender", "input": {"recipients": extracted_emails}, "status": "running"})

                email_html = await self._generate_email_html(company_name, report)
                html_content = format_company_report_as_html(
                    company_name=company_name,
                    report_html=email_html
                )

                email_result = send_company_research_email(
                    recipients=extracted_emails,
                    subject=f"Company Research Report: {company_name}",
                    html_content=html_content
                )

                if email_result["success"]:
                    tool_results[-1]["status"] = "completed"
                    thinking_steps.append(ThinkingStep(
                        type="tool_result",
                        content=f"Email sent successfully to {', '.join(extracted_emails)}",
                        tool_name="email_sender"
                    ))
                    return CompanyResearchResponse(
                        success=True,
                        query=query,
                        response=f"The company research report for **{company_name}** has been sent to {', '.join(extracted_emails)}.",
                        timestamp=datetime.now().isoformat(),
                        session_id=current_session_id,
                        email_sent=True,
                        email_recipients=extracted_emails,
                        thinking_steps=thinking_steps,
                        tool_results=tool_results
                    )
                else:
                    tool_results[-1]["status"] = "error"
                    return CompanyResearchResponse(
                        success=False,
                        query=query,
                        response=f"Failed to send the report: {email_result.get('error', 'Unknown error')}. Please check the email configuration.",
                        timestamp=datetime.now().isoformat(),
                        session_id=current_session_id,
                        thinking_steps=thinking_steps,
                        tool_results=tool_results
                    )
            else:
                return CompanyResearchResponse(
                    success=False,
                    query=query,
                    response="No previous company research report found for this session. Please first research a company, then ask me to share it.",
                    timestamp=datetime.now().isoformat(),
                    session_id=current_session_id,
                    thinking_steps=[ThinkingStep(type="thinking", content="User asked to share but no previous report exists in this session")],
                )

        company_name = self._extract_company_name(query)

        if not self.search.is_configured():
            provider = (os.getenv("COMPANY_RESEARCH_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
            if provider in ("free", "free_web", "free_ollama", "ollama", "ollama_free"):
                msg = (
                    "**Company Research Agent is not available.** Free web search is selected but "
                    "`OLLAMA_API_KEY` is not configured."
                )
            elif provider in ("free_duckduckgo", "duckduckgo", "duck", "ddg"):
                msg = (
                    "**Company Research Agent is not available.** DuckDuckGo free web search is selected "
                    "but the `ddgs` package is not installed on the server."
                )
            else:
                msg = (
                    "**Company Research Agent is not available.** Perplexity web search is selected but "
                    "`PERPLEXITY_API_KEY` is not configured."
                )
            return CompanyResearchResponse(
                success=False,
                query=query,
                response=msg,
                timestamp=datetime.now().isoformat(),
                session_id=current_session_id,
                thinking_steps=[ThinkingStep(type="thinking", content="Web search credentials not configured for selected provider")],
            )

        if not self.ai.llm_configured:
            hint = describe_missing_llm_credentials()
            return CompanyResearchResponse(
                success=False,
                query=query,
                response=f"**Company Research Agent is not available.** {hint}",
                timestamp=datetime.now().isoformat(),
                session_id=current_session_id,
                thinking_steps=[
                    ThinkingStep(
                        type="thinking",
                        content=f"LLM not configured for provider `{get_llm_provider()}`",
                    )
                ],
            )

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content=f"Identified company: {company_name}. Starting comprehensive research with 7 parallel provider-backed web searches (freshness-biased queries and recency filters for news)."
        ))
        await self._emit_trace_step(thinking_steps[-1])

        print(f"\n{'='*60}")
        print(f"🏢 Company Research: {company_name}")
        print(f"{'='*60}")

        search_tool_name = self._search_tool_name()
        provider_label = self._search_provider_label()

        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content=f"Searching for company overview of {company_name}",
            tool_name=search_tool_name,
            tool_input=f"Company overview: {company_name}"
        ))
        await self._emit_trace_step(thinking_steps[-1])

        search_base_idx = len(tool_results)
        tool_results.append({"tool": search_tool_name, "input": {"section": "overview"}, "status": "running"})
        tool_results.append({"tool": search_tool_name, "input": {"section": "financials"}, "status": "running"})
        tool_results.append({"tool": search_tool_name, "input": {"section": "balance_sheet"}, "status": "running"})
        tool_results.append({"tool": search_tool_name, "input": {"section": "focus_areas"}, "status": "running"})
        tool_results.append({"tool": search_tool_name, "input": {"section": "relevant_news"}, "status": "running"})
        tool_results.append({"tool": search_tool_name, "input": {"section": "latest_news"}, "status": "running"})
        tool_results.append({"tool": search_tool_name, "input": {"section": "financial_snapshot"}, "status": "running"})

        print(f"📡 Gathering data from 7 {provider_label} searches...")

        overview_data, financial_data, balance_sheet_data, focus_data, relevant_news_data, latest_news_data, snapshot_data = await asyncio.gather(
            self.search.search_company_overview(company_name),
            self.search.search_financials(company_name),
            self.search.search_balance_sheet(company_name),
            self.search.search_focus_areas(company_name),
            self.search.search_relevant_news(company_name),
            self.search.search_latest_news(company_name),
            self.search.search_financial_snapshot(company_name),
        )

        search_results_list = [
            ("overview", overview_data),
            ("financials", financial_data),
            ("balance_sheet", balance_sheet_data),
            ("focus_areas", focus_data),
            ("relevant_news", relevant_news_data),
            ("latest_news", latest_news_data),
            ("financial_snapshot", snapshot_data),
        ]
        for idx, (name, data) in enumerate(search_results_list):
            tool_results[search_base_idx + idx]["status"] = "completed"
            tool_results[search_base_idx + idx]["result"] = {"found": len(data)}

        total_results = sum(len(d) for _, d in search_results_list)
        print(f"✅ Total search results gathered: {total_results}")

        thinking_steps.append(ThinkingStep(
            type="tool_result",
            content=f"Gathered {total_results} results across 7 categories: overview({len(overview_data)}), financials({len(financial_data)}), balance_sheet({len(balance_sheet_data)}), focus({len(focus_data)}), relevant_news({len(relevant_news_data)}), latest_news({len(latest_news_data)}), snapshot({len(snapshot_data)})",
            tool_name=search_tool_name
        ))
        await self._emit_trace_step(thinking_steps[-1])

        thinking_steps.append(ThinkingStep(
            type="thinking",
            content="Synthesizing all research data into a comprehensive company report using LLM"
        ))
        await self._emit_trace_step(thinking_steps[-1])

        tool_results.append({"tool": "ai_report_generation", "input": {"company": company_name}, "status": "running"})

        report_prompt = f"""You are a senior strategy consultant preparing a comprehensive company research report for a client-facing sales pitch. Create an executive-grade, data-driven report about **{company_name}**.

**MANDATORY CURRENCY & UNIT RULE — EXTREMELY IMPORTANT:**
- ALL financial amounts MUST be in Indian Rupees (INR) with the ₹ symbol.
- You MUST preserve the EXACT scale/unit from the source data. Pay extreme attention to:
  - "Lakh Crore" (= 1,00,000 Crore) — used for very large companies' revenue, market cap. Example: ₹2.44 Lakh Crore
  - "Crore" (= 1,00,00,000) — used for profit, EBITDA, smaller figures. Example: ₹18,540 Crore
  - "Lakh" (= 1,00,000) — rarely used for large companies
- NEVER drop "Lakh" from "Lakh Crore". ₹2.44 Lakh Crore is NOT the same as ₹2.44 Crore. The difference is 100,000x.
- For large Indian companies (like Reliance, TCS, Infosys, HDFC, etc.):
  - Quarterly Revenue is typically ₹50,000+ Crore to ₹2+ Lakh Crore
  - Annual Revenue is typically ₹1+ Lakh Crore to ₹10+ Lakh Crore
  - Net Profit is typically ₹5,000-30,000 Crore per quarter
  - Market Cap is typically ₹5-20+ Lakh Crore
  - If your number seems too small for a large company, you are likely MISSING the "Lakh" prefix — go back and check.
- Write the full denomination clearly: "₹2,44,000 Crore" or "₹2.44 Lakh Crore" — both are acceptable.
- If source data is in USD or other currencies, convert to INR and note "(converted from USD)".

**MANDATORY RECENCY RULE — CRITICAL FOR WEB RESEARCH:**
- The client expects the **most up-to-date** picture: same-day and **yesterday’s** developments must appear when the research data contains them; do not summarize only older items if newer ones are in the data.
- When sources conflict, prefer the **newer** dated or clearly more recent source for news, strategy, and market-moving facts; keep older figures only when they are still the latest **filed** number (e.g. most recent quarterly filing).
- For the **Latest 4 News Items** section, order by **actual recency** (newest first) using dates/snippets from the research data; include items from the last 24–72 hours when present.

**MANDATORY DATA ACCURACY RULE — THIS IS CRITICAL:**
- You MUST ONLY use financial numbers that are EXPLICITLY stated in the research data below.
- NEVER estimate, approximate, calculate, interpolate, or invent any financial figure. If a number is not explicitly mentioned in the data, write "Data not available" in that cell.
- Do NOT change the scale of numbers. If the source says "₹2,69,000 crore" or "₹2.69 lakh crore", write exactly that — do NOT shorten it to "₹2.69 Cr".
- Each table cell value must come directly from a specific source. Do NOT combine numbers from different sources.
- If the research data shows conflicting numbers, use the one from the most authoritative source (BSE/NSE filings > financial portals > news articles).
- For QoQ/YoY growth percentages, only calculate them if both period values are available from the same source. Otherwise write "—".
- SANITY CHECK: Before finalizing, verify that revenue figures for large-cap companies are in thousands of crores or lakh crores — NOT single-digit crores.

**MANDATORY REFERENCE RULE:** Every factual claim, data point, and key insight MUST include a markdown reference link at the end pointing to the source URL from the research data provided below. Format: `[Source](URL)`. Use the URLs provided in the research data sections below. Each bullet point or paragraph with factual data must end with its source link. For tables, add source links in the trend observation line after the table.

{MANDATORY_MARKDOWN_SOURCE_LINKS}

**DATA GATHERED FROM WEB RESEARCH:**

### COMPANY OVERVIEW DATA:
{self._format_search_data(overview_data)}

### FINANCIAL DATA (Quarterly & Annual):
{self._format_search_data(financial_data)}

### BALANCE SHEET DATA:
{self._format_search_data(balance_sheet_data)}

### STRATEGIC FOCUS & LEADERSHIP:
{self._format_search_data(focus_data)}

### RELEVANT INDUSTRY/COMPANY NEWS:
{self._format_search_data(relevant_news_data)}

### LATEST NEWS:
{self._format_search_data(latest_news_data)}

---

**REPORT STRUCTURE (Follow this exactly):**

## Company Overview & Business Profile
Provide a concise summary of what the company does, its products/services, headquarters, industry, key markets, and market position. Include founding year if available.

## Financial Performance Analysis

**IMPORTANT: INDUSTRY-ADAPTIVE METRICS**
First determine if the company is a Bank/NBFC/Financial Institution or a Non-Banking company:
- **Banks/NBFCs** (e.g., ICICI Bank, SBI, HDFC Bank, Kotak, Axis Bank, Bajaj Finance): Use banking-specific metrics below
- **Non-Banking companies** (e.g., Reliance, TCS, Infosys, Tata Motors): Use standard corporate metrics below

### Quarterly Performance (Last 3 Quarters)
You MUST present this as a markdown table.

**FOR BANKS/NBFCs use this table:**
| Metric | [Quarter 1 Name] | [Quarter 2 Name] | [Quarter 3 Name] | QoQ Growth |
|---|---|---|---|---|
| Total Income | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Net Interest Income (NII) | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Net Profit | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Net Interest Margin (NIM) | X.XX% | X.XX% | X.XX% | [x.xxpp] |
| EPS | ₹XX.XX | ₹XX.XX | ₹XX.XX | [x.xx%] |

**FOR NON-BANKING companies use this table:**
| Metric | [Quarter 1 Name] | [Quarter 2 Name] | [Quarter 3 Name] | QoQ Growth |
|---|---|---|---|---|
| Revenue | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | [x.xx%] |
| Net Profit | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| EBITDA | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Operating Margin | XX.X% | XX.X% | XX.X% | [x.xxpp] |
| EPS | ₹XX.XX | ₹XX.XX | ₹XX.XX | [x.xx%] |

CRITICAL: Revenue/Total Income for large-cap Indian companies is in LAKH CRORE range (e.g., ₹2,44,000 Crore NOT ₹2.44 Crore). Net Profit is in THOUSANDS of Crore (e.g., ₹18,540 Crore NOT ₹18 Crore). Always write the full number with correct magnitude.
The QoQ Growth column compares the latest quarter (Q3) vs the previous quarter (Q2) only.

After the table, add a one-line trend observation starting with "Trend:".

### Annual Performance (Last 3 Years)
You MUST present this as a markdown table.

**FOR BANKS/NBFCs use this table:**
| Metric | [FY Year 1] | [FY Year 2] | [FY Year 3] | YoY Growth |
|---|---|---|---|---|
| Total Income | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | [x.xx%] |
| Net Interest Income (NII) | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Net Profit | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Total Assets | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | [x.xx%] |
| Gross NPA (%) | X.XX% | X.XX% | X.XX% | [x.xxpp] |

**FOR NON-BANKING companies use this table:**
| Metric | [FY Year 1] | [FY Year 2] | [FY Year 3] | YoY Growth |
|---|---|---|---|---|
| Revenue | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | [x.xx%] |
| Net Profit | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| EBITDA | ₹XX,XXX Crore | ₹XX,XXX Crore | ₹XX,XXX Crore | [x.xx%] |
| Total Assets | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | [x.xx%] |
| Market Cap | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | ₹X,XX,XXX Crore | [x.xx%] |

CRITICAL: Annual Revenue/Total Income for large companies is in LAKH CRORE range (e.g., ₹10,00,122 Crore or ₹10.00 Lakh Crore). Market Cap is also in LAKH CRORE range (e.g., ₹19,50,000 Crore). Never write single-digit or double-digit crore for these metrics.
The YoY Growth column compares the latest year (FY3) vs the previous year (FY2) only.

After the table, add a one-line trend observation starting with "Trend:".

### Key Financial Insights
Summarize the most significant financial trends, any inflection points, and what the numbers indicate about company health.

## Balance Sheet Analysis (Latest Quarter)
Analyze the most recent balance sheet data available:
- Total Assets, Total Liabilities, Shareholder Equity
- Debt-to-Equity ratio, Current Ratio
- Cash and cash equivalents position
- Key observations about financial health and leverage

## Current Focus Areas & Future Strategy
- What is the company currently investing in?
- Digital transformation initiatives
- New market expansions or product launches
- R&D priorities
- Include **direct leadership quotes** from CEO, CTO, or other executives (with attribution)
- Future outlook and stated goals

## Relevant News & Developments
Summarize important news items that a consultant should know:
- Major partnerships, acquisitions, or deals
- Regulatory developments affecting the company
- Industry shifts impacting their business
- Any controversies or risks

## Latest 4 News Items
List the 4 most recent news items about the company in chronological order:
1. **[Date]** - Headline and brief summary
2. **[Date]** - Headline and brief summary
3. **[Date]** - Headline and brief summary
4. **[Date]** - Headline and brief summary

## Sales Pitch Focus Areas (Consultant Advisory)
Based on the company's current strategic priorities and challenges, recommend:

### Primary Focus Areas for Sales Pitch
- 3-4 areas where consulting services would be most valuable
- Why each area matters based on company's stated priorities
- How to position your firm's capabilities

### Critical Pain Points to Address
- Specific challenges the company is facing
- Areas where they're lagging behind competitors
- Regulatory or compliance pressures

### Conversation Starters for Leadership
- 2-3 specific talking points tied to recent company announcements
- References to leadership quotes that show their priorities

---

**CRITICAL FORMATTING RULES:**
1. Use clean markdown formatting throughout
2. Quarterly Performance and Annual Performance sections MUST use markdown tables as shown above — never use bullet points or paragraphs for these sections
3. Bold all key numbers, percentages, and important terms
4. ALL financial figures MUST be in INR (₹). Write the FULL number in Crore — e.g., ₹2,44,000 Crore (NOT ₹2.44 Crore). NEVER drop "lakh" from "lakh crore"
5. If specific data is not available, write "Data not available" in the table cell — NEVER guess, estimate, or fabricate numbers
6. ONLY use numbers that appear VERBATIM in the research data above. Do not invent any financial figure. Preserve the EXACT magnitude/scale
7. Keep the tone professional and consultant-ready
8. Growth percentages must show + or - sign (e.g., +3.68% or -6.12%)
9. Use bullet points for lists, numbered items for sequential items
10. EVERY bullet point, paragraph, or data claim MUST end with a source reference link in the format [Source Name](URL) using the URLs from the research data above. This is mandatory — no point should be without a reference link
11. Table values: include a combined source reference in the "Trend:" line below each table

"""

        report = await self.ai.call_genai(report_prompt, temperature=0.2, max_tokens=8192)
        report = self._fix_table_formatting(report)
        report = self._append_numbered_source_link_index(report, search_results_list)

        tool_results[-1]["status"] = "completed"
        tool_results[-1]["result"] = {"report_length": len(report)}

        thinking_steps.append(ThinkingStep(
            type="observation",
            content=f"Company research report generated successfully ({len(report)} characters)"
        ))
        await self._emit_trace_step(thinking_steps[-1])

        print(f"📝 Report generated: {len(report)} characters")

        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content="Generating interactive chart data from financial figures",
            tool_name="chart_data_generator",
            tool_input='{"source": "report_financials"}'
        ))
        await self._emit_trace_step(thinking_steps[-1])
        tool_results.append({"tool": "chart_data_generator", "input": {"source": "report_financials"}, "status": "running"})

        import json
        print("=" * 50)
        print("📊 STEP 2: CHART DATA + FINANCIAL SNAPSHOT (Parallel LLM Calls)")
        print("=" * 50)

        async def _extract_charts_with_retry():
            for attempt in range(1, 4):
                print(f"📊 Chart extraction attempt {attempt}/3...")
                cd = await self.extract_chart_data(report)
                if cd and any(cd.get(k) for k in ["quarterly", "annual", "revenue_segments", "balance_sheet"]):
                    print(f"📊 Chart extraction succeeded on attempt {attempt}")
                    return cd
                print(f"⚠️ Chart extraction attempt {attempt} returned empty data")
            return None

        chart_data, snapshot_metrics = await asyncio.gather(
            _extract_charts_with_retry(),
            self.extract_financial_snapshot(company_name, snapshot_data),
        )

        if not chart_data:
            chart_data = {
                "quarterly": [],
                "annual": [],
                "revenue_segments": [],
                "key_metrics": {},
                "balance_sheet": {}
            }
            print("⚠️ Chart extraction failed after 3 attempts, embedding skeleton")

        if snapshot_metrics:
            existing_km = chart_data.get("key_metrics", {})
            existing_km.update({k: v for k, v in snapshot_metrics.items() if v and v != "N/A"})
            chart_data["key_metrics"] = existing_km
            print(f"💰 Snapshot KPIs merged into chart data: {list(snapshot_metrics.keys())}")
        else:
            print("⚠️ Snapshot extraction returned no data, using chart-extracted KPIs")

        chart_json = json.dumps(chart_data, ensure_ascii=False)
        report = report.rstrip() + f"\n\n```chartdata\n{chart_json}\n```"

        sections_found = [k for k in ["quarterly", "annual", "revenue_segments", "balance_sheet"] if chart_data.get(k)]
        if sections_found:
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"charts_generated": True, "sections": sections_found}
            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Chart data generated successfully: {', '.join(sections_found)}",
                tool_name="chart_data_generator"
            ))
            await self._emit_trace_step(thinking_steps[-1])
            print(f"📊 Chart data embedded: {len(chart_json)} chars ({', '.join(sections_found)})")
        else:
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"charts_generated": False, "fallback": "skeleton_embedded"}
            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content="Chart data skeleton embedded - frontend will attempt re-extraction",
                tool_name="chart_data_generator"
            ))
            await self._emit_trace_step(thinking_steps[-1])
            print("📊 Skeleton chart data embedded for frontend fallback")

        self.last_reports[current_session_id] = {
            "company_name": company_name,
            "report": report
        }

        news_tool_name = self._search_tool_name()
        print("=" * 50)
        print(f"📰 STEP 3: DEDICATED NEWS CARDS SEARCH (Separate {provider_label} call)")
        print("=" * 50)
        thinking_steps.append(ThinkingStep(
            type="tool_call",
            content=f"Fetching 5 latest news articles for {company_name}",
            tool_name=news_tool_name,
            tool_input=f'{{"company": "{company_name}", "count": 5}}'
        ))
        await self._emit_trace_step(thinking_steps[-1])
        tool_results.append({"tool": news_tool_name, "input": {"company": company_name}, "status": "running"})

        try:
            news_cards_data = await self.search.search_news_cards(company_name)
            news_cards = [
                NewsCard(
                    title=nc.get('title', ''),
                    url=nc.get('url', ''),
                    date=nc.get('date'),
                    snippet=nc.get('snippet', '')[:250] if nc.get('snippet') else '',
                    source=nc.get('source', ''),
                    image_url=nc.get('image_url'),
                )
                for nc in news_cards_data[:5]
                if nc.get('title')
            ]
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"news_found": len(news_cards)}
            thinking_steps.append(ThinkingStep(
                type="tool_result",
                content=f"Found {len(news_cards)} latest news articles for {company_name}",
                tool_name=news_tool_name
            ))
            await self._emit_trace_step(thinking_steps[-1])
            print(f"📰 News cards: {len(news_cards)} articles found")
        except Exception as e:
            news_cards = []
            tool_results[-1]["status"] = "completed"
            tool_results[-1]["result"] = {"error": str(e)}
            print(f"⚠️ News cards search failed: {e}")

        email_sent = False
        email_recipients_sent = []

        if extracted_emails:
            final_recipients = extracted_emails
            thinking_steps.append(ThinkingStep(
                type="thinking",
                content=f"Detected email address(es) in query: {', '.join(extracted_emails)}"
            ))
        elif email_recipients and len(email_recipients) > 0:
            final_recipients = email_recipients
        else:
            final_recipients = []

        if final_recipients:
            thinking_steps.append(ThinkingStep(
                type="tool_call",
                content=f"Sending company research report via email to {len(final_recipients)} recipient(s)",
                tool_name="email_sender",
                tool_input=f'{{"recipients": {final_recipients}}}'
            ))

            tool_results.append({"tool": "email_sender", "input": {"recipients": final_recipients}, "status": "running"})

            thinking_steps.append(ThinkingStep(
                type="thinking",
                content="Converting report to professional HTML email format"
            ))

            email_html = await self._generate_email_html(company_name, report)

            html_content = format_company_report_as_html(
                company_name=company_name,
                report_html=email_html
            )

            email_result = send_company_research_email(
                recipients=final_recipients,
                subject=f"Company Research Report: {company_name}",
                html_content=html_content
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
            else:
                email_recipients_sent = final_recipients
                tool_results[-1]["status"] = "error"
                tool_results[-1]["result"] = {"error": email_result["error"]}
                thinking_steps.append(ThinkingStep(
                    type="tool_result",
                    content=f"Email delivery failed: {email_result['error']}",
                    tool_name="email_sender"
                ))

        print(f"{'='*60}\n")

        return CompanyResearchResponse(
            success=True,
            query=query,
            response=report,
            timestamp=datetime.now().isoformat(),
            session_id=current_session_id,
            email_sent=email_sent,
            email_recipients=email_recipients_sent,
            thinking_steps=thinking_steps,
            tool_results=tool_results,
            latest_news_cards=news_cards
        )

    async def _generate_email_html(self, company_name: str, markdown_report: str) -> str:
        prompt = f"""Convert the following company research report into a polished, executive-ready HTML email format.

**CRITICAL RULES:**
1. DO NOT include email headers (NO "To:", "From:", "Subject:", "Date:")
2. DO NOT include greetings or signatures
3. Use proper HTML formatting with executive-level polish
4. Use inline styles for ALL elements
5. Emphasize key metrics, dates, and actionable insights
6. Use data callouts or highlight boxes for critical statistics
7. Make financial tables clean and scannable

**Company:** {company_name}

**Report (Markdown):**
{markdown_report}

**Professional Color Scheme:**
- Primary headings: color: #1e3a5f; font-weight: 600
- Section headings: color: #2c5f8a; font-weight: 600
- Body text: color: #2d3748; line-height: 1.7
- Accent: color: #D85604; font-weight: 500
- Data highlights: background: #f0f4f8; border-left: 3px solid #1e3a5f; padding: 10px

**Output:** Return ONLY the HTML content (NO <!DOCTYPE>, NO <html>, NO <head>, NO <body> tags).
Use inline styles for ALL elements. Make it polished and worthy of executive attention."""

        html = await self.ai.call_genai(prompt, temperature=0.3, max_tokens=8192)
        html = html.replace("```html", "").replace("```", "").strip()
        return html


    async def extract_financial_snapshot(self, company_name: str, snapshot_data: list) -> dict:
        if not snapshot_data:
            return {}

        formatted = self._format_search_data(snapshot_data)

        prompt = f"""You are a financial data extraction specialist. Extract the 5 key financial metrics for **{company_name}** from the web search data below.

WEB SEARCH DATA:
{formatted}

Extract these 5 metrics and return ONLY valid JSON:
{{
  "market_cap": "₹19,50,000 Crore",
  "latest_revenue": "₹2,94,000 Crore",
  "latest_profit": "₹22,290 Crore",
  "operating_margin": "17.0%",
  "debt_equity": "0.42"
}}

RULES:
1. ALL values MUST be in INR (₹) with Crore denomination. Write the FULL number in Crore.
2. CRITICAL UNIT RULE: Large Indian companies have:
   - Market Cap in LAKH CRORE range: ₹19,50,000 Crore (NOT ₹19,500 Crore or ₹19.5 Crore)
   - Revenue in LAKH CRORE range: ₹2,44,000 Crore (NOT ₹2.44 Crore)
   - Net Profit in THOUSANDS of Crore: ₹22,290 Crore (NOT ₹22 Crore)
   - If the source says "₹2.44 lakh crore", write "₹2,44,000 Crore"
   - If the source says "₹10.71 lakh crore", write "₹10,71,000 Crore"
3. Use the most recent/latest officially reported values only
4. For "latest_revenue": use Revenue (non-banking) OR Total Income (for banks/NBFCs like ICICI Bank, SBI, HDFC Bank, etc.)
5. For "operating_margin": use Operating Margin (non-banking) OR Net Interest Margin/NIM (for banks/NBFCs)
6. Debt/Equity ratio as a decimal number (e.g., "0.42")
7. Use "N/A" if a metric is genuinely not available in the data
8. Format numbers with Indian comma notation (e.g., ₹19,50,000 Crore)
9. Return ONLY the JSON — no explanation, no markdown fences

Return the JSON now:"""

        try:
            print("💰 [Snapshot] Extracting financial KPIs from dedicated search data...")
            result = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=1024)
            result = result.strip()

            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:])
                if result.rstrip().endswith("```"):
                    result = result.rstrip()[:-3]
            result = result.strip()

            if not result.startswith("{"):
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    result = json_match.group(0)
                else:
                    print("💰 [Snapshot] No JSON found in response")
                    return {}

            import json
            data = json.loads(result)

            required_keys = ["market_cap", "latest_revenue", "latest_profit", "operating_margin", "debt_equity"]
            for key in required_keys:
                if key not in data:
                    data[key] = "N/A"

            print(f"💰 [Snapshot] Extracted KPIs: {data}")
            return data
        except json.JSONDecodeError as e:
            print(f"💰 [Snapshot] JSON parse error: {e}")
            try:
                result_fixed = re.sub(r',\s*([}\]])', r'\1', result)
                data = json.loads(result_fixed)
                print(f"💰 [Snapshot] Recovered with trailing comma fix")
                return data
            except:
                pass
            return {}
        except Exception as e:
            print(f"💰 [Snapshot] Error: {e}")
            return {}

    async def extract_chart_data(self, report_text: str) -> dict:
        clean_report = re.sub(r'```chartdata[\s\S]*?```', '', report_text).strip()

        prompt = f"""You are a financial data extraction specialist. Your ONLY job is to extract numerical data from the report below and return VALID JSON.

CRITICAL RULES:
1. Return ONLY the JSON object - no explanation, no markdown fences, no text before or after
2. ALL raw numbers MUST be in CRORE as the base unit. Convert lakh crore to crore:
   - ₹2.44 Lakh Crore = 244000 (in crore)
   - ₹2,44,000 Crore = 244000 (in crore)
   - ₹10,00,122 Crore = 1000122 (in crore)
   - ₹19,50,000 Crore = 1950000 (in crore)
   - ₹18,540 Crore = 18540 (in crore)
   - ₹26,994 Crore = 26994 (in crore)
   NEVER use small numbers like 2.44 or 5.50 for revenue/assets/market cap — those would mean ₹2 Crore which is wrong for large companies
3. Use null for any data not found in the report
4. Extract ALL quarters and years mentioned in the report
5. For revenue_segments, extract at least 3-5 segments from business lines, geographies, or service areas
6. If percentages aren't stated, calculate them from revenue values
7. BANKING/NBFC COMPANIES: If the report is about a bank (ICICI Bank, SBI, HDFC Bank, Kotak, Axis Bank, etc.):
   - Use "Total Income" or "NII" for the "revenue" field
   - Use "Operating Profit" or "Pre-Provision Profit" for the "ebitda" field
   - Use "Net Interest Margin (NIM)" for the "operating_margin" field
   - Do NOT leave these as null just because the bank doesn't report traditional "Revenue" or "EBITDA"

REPORT TO EXTRACT FROM:
{clean_report}

Return EXACTLY this JSON structure (all numbers in Crore as base unit):
{{
  "quarterly": [
    {{"quarter": "Q3 FY26", "revenue": 294000, "net_profit": 22290, "ebitda": 50932, "operating_margin": 17.0, "eps": 14.5}}
  ],
  "annual": [
    {{"year": "FY25", "revenue": 1071174, "net_profit": 79020, "total_assets": 1800000, "market_cap": 1950000}}
  ],
  "revenue_segments": [
    {{"name": "Oil to Chemicals", "percentage": 55, "value": 589145}},
    {{"name": "Digital Services", "percentage": 25, "value": 267793}},
    {{"name": "Retail", "percentage": 20, "value": 214235}}
  ],
  "key_metrics": {{
    "market_cap": "₹19,50,000 Crore",
    "latest_revenue": "₹2,94,000 Crore",
    "latest_profit": "₹22,290 Crore",
    "operating_margin": "17.0%",
    "employees": "3,89,000",
    "debt_equity": "0.4",
    "currency": "INR Cr"
  }},
  "balance_sheet": {{
    "total_assets": 1800000,
    "total_liabilities": 900000,
    "equity": 900000,
    "cash": 180000,
    "debt": 350000
  }}
}}

SANITY CHECK before returning:
- Large-cap company revenue should be 50000+ (₹50,000+ Crore) per quarter, 200000+ (₹2+ Lakh Crore) annually
- If revenue is < 100 in your output, you have a UNIT ERROR — multiply by 100000 for lakh crore conversion
- Market cap for top companies should be 500000+ (₹5+ Lakh Crore)

NOW extract the real data from the report above. Return ONLY valid JSON:"""

        try:
            print("📊 [Chart Extraction] Starting dedicated LLM call for chart data...")
            result = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=4096)
            result = result.strip()

            if result.startswith("```"):
                lines = result.split("\n")
                result = "\n".join(lines[1:])
                if result.rstrip().endswith("```"):
                    result = result.rstrip()[:-3]
            result = result.strip()

            if not result.startswith("{"):
                json_match = re.search(r'\{[\s\S]*"quarterly"[\s\S]*\}', result)
                if json_match:
                    result = json_match.group(0)
                else:
                    print("📊 [Chart Extraction] No JSON object found in LLM response")
                    return {}

            import json
            data = json.loads(result)

            report_lower = clean_report.lower()
            report_has_lakh_crore = "lakh crore" in report_lower or "l crore" in report_lower
            report_has_thousand_crore = bool(re.search(r'\d{1,3},\d{3}\s*crore', report_lower))

            def _maybe_scale(val, small_threshold, multiplier, label, require_lakh_crore=True):
                if val is None or val <= 0 or val >= small_threshold:
                    return val
                if require_lakh_crore and not report_has_lakh_crore:
                    return val
                print(f"⚠️ [Chart Extraction] Rescaling {label} {val} → {val * multiplier} (source uses lakh crore notation)")
                return int(val * multiplier) if multiplier >= 1000 else val * multiplier

            for q in data.get("quarterly", []):
                q["revenue"] = _maybe_scale(q.get("revenue"), 100, 100000, "quarterly revenue")
                q["net_profit"] = _maybe_scale(q.get("net_profit"), 50, 1000, "quarterly net_profit", require_lakh_crore=False) if report_has_thousand_crore else q.get("net_profit")
                q["ebitda"] = _maybe_scale(q.get("ebitda"), 100, 1000, "quarterly ebitda", require_lakh_crore=False) if report_has_thousand_crore else q.get("ebitda")

            for a in data.get("annual", []):
                a["revenue"] = _maybe_scale(a.get("revenue"), 500, 100000, "annual revenue")
                a["total_assets"] = _maybe_scale(a.get("total_assets"), 500, 100000, "annual total_assets")
                a["market_cap"] = _maybe_scale(a.get("market_cap"), 1000, 100000, "annual market_cap")
                a["net_profit"] = _maybe_scale(a.get("net_profit"), 100, 1000, "annual net_profit", require_lakh_crore=False) if report_has_thousand_crore else a.get("net_profit")

            banking_signals = ["net interest income", "nii", "net interest margin", "nim", "gross npa", "net npa", "casa ratio", "total income", "advances", "deposits"]
            banking_count = sum(1 for s in banking_signals if s in report_lower)
            if banking_count >= 3:
                data["company_type"] = "bank"
                print(f"📊 [Chart Extraction] Detected BANKING company ({banking_count} signals)")
            else:
                data["company_type"] = "corporate"

            sections = [k for k in ["quarterly", "annual", "revenue_segments", "balance_sheet"] if data.get(k)]
            print(f"📊 [Chart Extraction] Success - extracted sections: {', '.join(sections)}")
            return data
        except json.JSONDecodeError as e:
            print(f"📊 [Chart Extraction] JSON parse error: {e}")
            try:
                result_fixed = re.sub(r',\s*([}\]])', r'\1', result)
                data = json.loads(result_fixed)
                print(f"📊 [Chart Extraction] Recovered with trailing comma fix")
                return data
            except:
                pass
            return {}
        except Exception as e:
            print(f"📊 [Chart Extraction] Error: {e}")
            return {}


company_research_agent = CompanyResearchAgent()
