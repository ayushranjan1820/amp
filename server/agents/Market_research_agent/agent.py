import os
import asyncio
import json
import httpx
import uuid
import re
from datetime import datetime
from typing import Optional, List, Callable, Awaitable, Dict, Any
from .tools.web_search import search_web, get_search_provider_label
from .tools.email_sender import send_research_email, format_research_as_html
from .models import MarketResearchResponse, ResearchSource, ThinkingStep
from agents.llm_continuation import sync_call_with_continuation_httpx
from agents.local_llm import get_llm_provider, uses_pwc_genai_credentials
from agents.source_citation_mandate import MANDATORY_MARKDOWN_SOURCE_LINKS

class MarketResearchAgent:
    """
    Market Research Agent that:
    1. Takes user queries about market research topics
    2. Searches the web for detailed information
    3. Summarizes findings in a professional format with references
    4. Optionally sends the report via email
    """
    
    def __init__(self):
        self.sessions = {}
        self.pwc_api_key = os.environ.get("PWC_GENAI_API_KEY")
        self.pwc_bearer_token = os.environ.get("PWC_GENAI_BEARER_TOKEN")
        self.pwc_endpoint = os.environ.get("PWC_GENAI_ENDPOINT_URL")
        
        prov = get_llm_provider()
        if prov == "local_llm":
            print("📊 Market Research Agent - Using Local LLM service")
        elif prov == "ollama_cloud":
            print("📊 Market Research Agent - Using Ollama Cloud")
        elif self.pwc_api_key and self.pwc_endpoint:
            print("📊 Market Research Agent - Using PwC GenAI service")
        else:
            print("⚠️ Market Research Agent - PwC GenAI credentials not configured")
    
    def _call_llm(self, prompt: str) -> str:
        """Call the PwC GenAI service for summarization with auto-continuation."""
        pwc_api_key = (os.environ.get("PWC_GENAI_API_KEY") or "").strip()
        pwc_bearer_token = (os.environ.get("PWC_GENAI_BEARER_TOKEN") or "").strip()
        pwc_endpoint = (os.environ.get("PWC_GENAI_ENDPOINT_URL") or "").strip()

        try:
            from langfuse_tracer import set_current_agent
            set_current_agent("Market Research Agent")
        except Exception:
            pass
        if uses_pwc_genai_credentials() and (not pwc_api_key or not pwc_endpoint):
            return "Error: LLM service not configured. Please set PWC_GENAI_API_KEY and PWC_GENAI_ENDPOINT_URL."
        
        try:
            headers = {
                "accept": "application/json",
                "API-Key": pwc_api_key,
                "Content-Type": "application/json"
            }
            
            if pwc_bearer_token:
                headers["Authorization"] = f"Bearer {pwc_bearer_token}"
            
            payload = {
                "model": os.getenv("PREMIUM_MODEL", ""),
                "prompt": prompt,
                "temperature": 0.7,
                "max_tokens": 8192,
                "top_p": 1,
                "presence_penalty": 0,
                "stream": False,
                "stream_options": None,
                "seed": 25,
                "stop": None
            }
            
            return sync_call_with_continuation_httpx(
                endpoint_url=pwc_endpoint,
                headers=headers,
                request_body=payload,
                original_prompt=prompt,
                timeout=120.0,
            )
                
        except Exception as e:
            print(f"LLM error: {e}")
            return f"Error calling LLM service: {str(e)}"
    
    def _extract_emails_from_query(self, query: str) -> List[str]:
        """Extract email addresses from the query text using regex."""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, query)
        return list(set(emails))  # Remove duplicates
    
    def _generate_email_html(self, query: str, markdown_report: str, sources: List[dict]) -> str:
        """Use LLM to convert markdown report to clean, professional HTML email."""
        
        sources_list = "\n".join([
            f"- {source['title']}: {source['url']}"
            for source in sources[:10]
        ])
        
        prompt = f"""Convert the following strategic market research report into a polished, CEO-ready HTML email format.

**CRITICAL RULES:**
1. DO NOT include email headers (NO "To:", "From:", "Subject:", "Date:", etc.)
2. DO NOT include greetings or signatures
3. Start with a brief executive context statement (1-2 lines)
4. Use proper HTML formatting with executive-level polish
5. Emphasize key metrics, dates, and actionable insights
6. Use professional typography and spacing suitable for C-suite
7. Highlight publication dates in a subtle but visible way
8. Use data callouts or highlight boxes for critical statistics
9. Maintain scannable format with clear hierarchy
10. Include a clean sources section at the end

**Research Query:** {query}

**Market Research Report (Markdown):**
{markdown_report}

**Output Format:**
Return ONLY the HTML content (NO <!DOCTYPE>, NO <html>, NO <head>, NO <body> tags).
Start with a brief context line, then immediately begin the report.
Use inline styles for ALL elements.

**Professional Color Scheme for Executives:**
- Primary headings: color: #1a1a1a; font-weight: 600
- Section headings: color: #2c3e50; font-weight: 600
- Body text: color: #2d3748; line-height: 1.7
- Accent/Links: color: #D85604; font-weight: 500
- Publication dates: color: #718096; font-style: italic; font-size: 13px
- Data highlights: background: #fef6e7; border-left: 3px solid #D85604; padding: 10px

**Example Structure:**
<p style="color: #718096; font-size: 14px; margin-bottom: 20px; font-style: italic;">Strategic Market Research Report | Compiled {datetime.now().strftime('%B %d, %Y')}</p>

<h2 style="color: #1a1a1a; font-size: 22px; margin: 25px 0 15px 0; font-weight: 600; border-bottom: 2px solid #D85604; padding-bottom: 10px;">Executive Summary</h2>
<p style="color: #2d3748; font-size: 15px; line-height: 1.7; margin-bottom: 15px;">Content with <span style="color: #718096; font-style: italic; font-size: 13px;">(Published: January 2026)</span></p>

<div style="background: #fef6e7; border-left: 3px solid #D85604; padding: 12px 15px; margin: 15px 0;">
  <strong style="color: #1a1a1a;">Key Insight:</strong> <span style="color: #2d3748;">Critical data point here</span>
</div>

**Sources Section Format:**
Create a clean, professional sources list at the end with publication dates clearly visible.

Make it polished, strategic, and worthy of executive attention."""

        html_body = self._call_llm(prompt)
        
        # Clean up any potential markdown that might have slipped through
        html_body = html_body.replace("```html", "").replace("```", "").strip()
        
        return html_body

    async def _call_llm_async(self, prompt: str) -> str:
        return await asyncio.to_thread(self._call_llm, prompt)

    async def _search_web_async(self, query: str, max_results: int = 8) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(search_web, query, max_results)

    def _dedupe_sources(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for item in raw_items:
            url = str(item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            key = url or f"{title}|{snippet[:140]}"
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append({
                "title": title,
                "url": url,
                "snippet": snippet,
                "published_date": item.get("published_date"),
                "theme": item.get("theme", "general"),
            })
        return deduped

    def _format_sources_for_prompt(self, sources: List[Dict[str, Any]], limit: int = 30) -> str:
        lines: List[str] = []
        for i, src in enumerate(sources[:limit], 1):
            sid = src.get("source_id") or f"S{i}"
            lines.append(
                f"[{sid}] [{src.get('theme', 'general')}] {src.get('title', '')} | "
                f"{src.get('url', '')} | {src.get('snippet', '')}"
            )
        return "\n".join(lines) if lines else "No external sources were retrieved."

    def _prepare_sources_with_ids(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for i, s in enumerate(sources, 1):
            row = dict(s)
            row["source_id"] = f"S{i}"
            out.append(row)
        return out

    def _section_has_numeric_evidence(self, txt: str) -> bool:
        t = txt or ""
        return bool(re.search(r"\b\d+(?:\.\d+)?\b|%|\$|USD|INR|₹|million|billion", t, flags=re.IGNORECASE))

    def _section_has_source_citation(self, txt: str) -> bool:
        t = txt or ""
        return bool(re.search(r"\[S\d+\]", t))

    def _extract_quant_bullets(self, sources: List[Dict[str, Any]], max_points: int = 4) -> List[str]:
        bullets: List[str] = []
        for src in sources:
            snippet = re.sub(r"\s+", " ", str(src.get("snippet") or "")).strip()
            if not snippet or not re.search(r"\d", snippet):
                continue
            sid = src.get("source_id") or "S?"
            url = str(src.get("url") or "").strip()
            title = str(src.get("title") or "Source").strip()
            snippet = snippet[:260].rstrip(" ,.;")
            if url:
                bullets.append(f"- {snippet}. [{sid}] [{title}]({url})")
            else:
                bullets.append(f"- {snippet}. [{sid}] {title}")
            if len(bullets) >= max_points:
                break
        return bullets

    def _enrich_section_with_evidence(self, heading: str, text: str, sources: List[Dict[str, Any]]) -> str:
        body = (text or "").strip()
        needs_numeric = not self._section_has_numeric_evidence(body)
        needs_source = not self._section_has_source_citation(body)
        if not (needs_numeric or needs_source):
            return body

        bullets = self._extract_quant_bullets(sources, max_points=4)
        if not bullets:
            return body

        addon = ["", "### Source-backed Quant Signals"]
        addon.extend(bullets)
        addon.append("- These points are included to strengthen evidence depth for executive decisions.")
        return body + "\n" + "\n".join(addon)

    def _build_toc(self, headings: List[str]) -> str:
        return "\n".join([f"{i}. {h}" for i, h in enumerate(headings, 1)])

    def _fallback_section_text(self, heading: str, query: str) -> str:
        if heading == "Title Page":
            return (
                f"Report: {query}\n"
                f"Prepared on: {datetime.now().strftime('%B %d, %Y')}\n"
                "Prepared for: Executive stakeholders"
            )
        if heading == "Appendices":
            return "- Appendix A: Query matrix used for web research\n- Appendix B: Source quality notes"
        if heading == "Glossary":
            return "- CAC: Customer Acquisition Cost\n- ROAS: Return on Ad Spend\n- NPS: Net Promoter Score"
        return (
            f"This section analyzes {heading.lower()} for \"{query}\" using currently available sources. "
            "Where public data is limited, assumptions are explicitly noted."
        )

    def _parse_sections_json(self, raw: str, headings: List[str], query: str) -> Dict[str, str]:
        obj: Dict[str, Any] = {}
        txt = (raw or "").strip()
        start = txt.find("{")
        end = txt.rfind("}")
        if start >= 0 and end > start:
            txt = txt[start:end + 1]
        try:
            parsed = json.loads(txt)
            if isinstance(parsed, dict):
                obj = parsed
        except Exception:
            obj = {}

        out: Dict[str, str] = {}
        for h in headings:
            v = obj.get(h)
            if isinstance(v, str) and v.strip():
                out[h] = v.strip()
            else:
                out[h] = self._fallback_section_text(h, query)
        return out

    async def _generate_group_sections(
        self,
        group_name: str,
        headings: List[str],
        query: str,
        sources: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        prompt = f"""You are producing the \"{group_name}\" section group for a market research report.

Research topic: {query}

Headings that MUST be present as JSON keys (exactly as written):
{json.dumps(headings, ensure_ascii=True)}

Sources:
{self._format_sources_for_prompt(sources, limit=35)}

Rules:
1. Return ONLY a valid JSON object.
2. Use exactly the provided headings as keys.
3. Each value must be markdown content (no markdown heading markers).
4. Every section MUST include quantitative evidence: market size, growth rates, share, conversion, cost, KPI, penetration, or benchmarks where relevant.
5. Every quantitative or factual claim MUST cite one or more source IDs in this exact format: [S#], and when the source entry includes a URL, also add a markdown link in the same line or sentence: [short label](https://url-from-source-list).
6. Include a short subsection named "Key Numbers" in each section with at least 3 bullet points, each bullet containing a number and [S#] plus a clickable link to the source URL when available.
7. Include implications and assumptions when data is estimated or uncertain.
8. For forecasting/roadmap/KPIs, include clearly labeled assumptions and expected ranges.

{MANDATORY_MARKDOWN_SOURCE_LINKS}

Return JSON only.
"""
        raw = await self._call_llm_async(prompt)
        return self._parse_sections_json(raw, headings, query)
    
    async def research(
        self,
        query: str,
        email_recipients: Optional[List[str]] = None,
        session_id: Optional[str] = None,
        stream_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ) -> MarketResearchResponse:
        """
        Perform market research on the given query.
        """
        async def _emit(event: str, data: Dict[str, Any]) -> None:
            if not stream_callback:
                return
            try:
                await stream_callback({"event": event, "data": data})
            except Exception:
                # Streaming should never break research generation.
                pass

        async def _emit_step(step: ThinkingStep) -> None:
            await _emit("thinking", step.model_dump())

        async def _add_step(step_type: str, content: str, tool_name: Optional[str] = None, tool_input: Optional[str] = None):
            step = ThinkingStep(type=step_type, content=content, tool_name=tool_name, tool_input=tool_input)
            thinking_steps.append(step)
            await _emit_step(step)

        current_session_id = session_id or str(uuid.uuid4())
        tool_results = []
        thinking_steps = []

        await _emit("progress", {"stage": "init", "message": "Analyzing research request..."})
        await _add_step("thinking", f"Analyzing market research request: {query}")

        await _emit("progress", {"stage": "search", "message": "Running parallel web-search workstreams..."})
        await _add_step(
            "tool_call",
            f"Launching multiple web searches with {get_search_provider_label()}",
            tool_name="parallel_web_search",
            tool_input=query,
        )

        search_workstreams: Dict[str, List[str]] = {
            "market_overview": [
                f"{query} market size CAGR TAM SAM SOM latest report",
                f"{query} market maturity lifecycle adoption stage",
            ],
            "segmentation": [
                f"{query} market segmentation by customer product geography",
            ],
            "industry_forces": [
                f"{query} PESTEL analysis regulatory macro factors",
                f"{query} porters five forces supplier buyer threat rivalry",
            ],
            "competition": [
                f"{query} top competitors market share positioning",
            ],
            "customer_marketing": [
                f"{query} customer behavior journey touchpoints NPS sentiment reviews",
                f"{query} marketing channels SEO SEM social media CAC ROAS benchmarks",
                f"{query} pricing strategy willingness to pay elasticity",
            ],
            "ai_scope": [
                f"{query} AI use cases implementation benchmark",
                f"{query} AI tech stack vendors martech CRM tools",
                f"{query} AI governance privacy bias compliance GDPR DPDP",
            ],
            "forecast_risk": [
                f"{query} market forecast projections next 5 years",
                f"{query} market risks barriers challenges",
            ],
        }

        search_jobs = []
        for theme, queries in search_workstreams.items():
            for q in queries:
                search_jobs.append((theme, q))

        tool_results.append({
            "tool": "parallel_web_search",
            "input": {"query_count": len(search_jobs)},
            "status": "running",
        })

        async def _run_search_job(theme: str, q: str):
            return theme, q, await self._search_web_async(q, max_results=7)

        search_tasks = [
            asyncio.create_task(_run_search_job(theme, q))
            for theme, q in search_jobs
        ]

        themed_items: Dict[str, List[Dict[str, Any]]] = {}
        completed = 0
        for task in asyncio.as_completed(search_tasks):
            theme, q, items = await task
            themed_items.setdefault(theme, [])
            for it in items:
                row = dict(it)
                row["theme"] = theme
                themed_items[theme].append(row)
            completed += 1
            await _emit(
                "progress",
                {
                    "stage": "search",
                    "message": f"Web search {completed}/{len(search_jobs)} complete ({theme}).",
                },
            )
            await _add_step(
                "tool_result",
                f"Completed web search workstream query for {theme}: {q}",
                tool_name="web_search",
            )

        all_raw_items: List[Dict[str, Any]] = []
        for rows in themed_items.values():
            all_raw_items.extend(rows)
        deduped_sources = self._dedupe_sources(all_raw_items)
        cited_sources = self._prepare_sources_with_ids(deduped_sources)

        tool_results[-1]["status"] = "completed"
        tool_results[-1]["result"] = {
            "workstreams": len(search_workstreams),
            "queries": len(search_jobs),
            "raw_hits": len(all_raw_items),
            "unique_sources": len(deduped_sources),
            "top_sources": [{"id": s.get("source_id"), "title": s["title"], "url": s["url"]} for s in cited_sources[:8]],
        }
        await _emit("progress", {"stage": "search", "message": f"Collected {len(deduped_sources)} unique sources."})

        sources = [
            ResearchSource(
                title=s.get("title", ""),
                url=s.get("url", ""),
                snippet=s.get("snippet", ""),
                published_date=s.get("published_date"),
            )
            for s in cited_sources
        ]

        await _emit("progress", {"stage": "synthesis", "message": "Running parallel LLM section drafting..."})
        await _add_step("thinking", "Generating report sections in parallel and composing one consolidated report")

        section_groups = {
            "front_matter": [
                "Title Page",
                "Executive Summary",
            ],
            "core": [
                "Introduction & Background",
                "Research Methodology",
                "Market Overview (size, growth, maturity)",
                "Market Segmentation",
                "Industry Analysis (PESTEL + Porter's Five Forces)",
                "Competitive Landscape",
                "Customer Analysis",
                "Market Trends & Drivers",
                "Challenges, Risks & Barriers",
                "SWOT Analysis",
                "Market Forecast & Projections",
            ],
            "marketing": [
                "Brand & Positioning Analysis — how existing players are positioned, brand perception, share of voice, and whitespace opportunities.",
                "Marketing Mix Assessment (4Ps / 7Ps) — product, price, place, promotion (plus people, process, physical evidence for services). Benchmarks current strategies in the market.",
                "Customer Journey & Touchpoint Mapping — awareness, consideration, purchase, retention, and advocacy stages, with friction points at each.",
                "Channel & Distribution Analysis — performance of digital vs. offline channels, e-commerce penetration, retail partnerships, direct-to-consumer trends.",
                "Digital Marketing & Media Landscape — SEO/SEM, social platforms, influencer ecosystem, content trends, paid media benchmarks, CAC and ROAS norms in the category.",
                "Pricing Strategy & Consumer Willingness-to-Pay — price elasticity, discounting patterns, premium vs. value segments.",
                "Brand Health & Sentiment Analysis — NPS, social listening insights, reviews, earned media themes.",
                "Go-to-Market Recommendations — campaign ideas, messaging pillars, target segments to prioritize, channel mix suggestions.",
            ],
            "ai_scope": [
                "AI Readiness Assessment of the Market — how mature the industry is in adopting AI, leading use cases, laggards vs. leaders.",
                "AI Use Cases & Applications — concrete opportunities across the value chain: demand forecasting, personalization, chatbots, dynamic pricing, content generation, fraud detection, supply chain optimization, etc.",
                "AI-Powered Marketing Opportunities — predictive segmentation, generative AI for creative, programmatic ad optimization, hyper-personalization, conversational commerce, AI-driven SEO/AEO (answer engine optimization).",
                "Competitive AI Benchmarking — what competitors are already doing with AI, tools they use, visible outcomes.",
                "Technology Stack & Vendor Landscape — key AI platforms, tools, and partners relevant to the industry (e.g., CRM AI add-ons, MarTech AI tools, industry-specific models).",
                "Data Infrastructure & Requirements — data availability, quality, governance needs, and gaps that must be closed before AI can deliver value.",
                "AI Risks, Ethics & Compliance — bias, hallucination, data privacy (GDPR, DPDP Act in India), IP concerns, regulatory outlook.",
                "Implementation Roadmap — phased approach: quick wins (0–6 months), mid-term builds (6–18 months), long-term transformation (18+ months), with estimated investment and ROI.",
                "Success Metrics & KPIs for AI Initiatives — efficiency gains, revenue lift, cost savings, customer experience improvements.",
            ],
            "strategic_close": [
                "Opportunities & Strategic Recommendations (now synthesizing market + marketing + AI insights)",
                "Conclusion",
            ],
            "back_matter": [
                "Appendices",
                "Glossary (helpful since AI and marketing jargon can overwhelm non-specialist readers)",
            ],
        }

        group_to_themes = {
            "front_matter": ["market_overview", "competition", "customer_marketing", "ai_scope", "forecast_risk"],
            "core": ["market_overview", "segmentation", "industry_forces", "competition", "forecast_risk"],
            "marketing": ["customer_marketing", "competition", "segmentation"],
            "ai_scope": ["ai_scope", "competition", "forecast_risk"],
            "strategic_close": ["market_overview", "competition", "customer_marketing", "ai_scope", "forecast_risk"],
            "back_matter": ["market_overview", "customer_marketing", "ai_scope"],
        }

        tool_results.append({
            "tool": "parallel_llm_section_builder",
            "input": {"groups": len(section_groups)},
            "status": "running",
        })

        async def _run_group(name: str, headings: List[str]):
            focused_sources: List[Dict[str, Any]] = []
            for t in group_to_themes.get(name, []):
                focused_sources.extend([s for s in cited_sources if s.get("theme") == t])

            # Keep global [S#] IDs stable across all sections and references.
            unique: List[Dict[str, Any]] = []
            seen = set()
            for s in focused_sources:
                key = s.get("url") or f"{s.get('title', '')}|{(s.get('snippet', '') or '')[:120]}"
                if not key or key in seen:
                    continue
                seen.add(key)
                unique.append(s)
            focused_sources = unique or cited_sources
            sections = await self._generate_group_sections(name, headings, query, focused_sources)
            # Safety net: enforce numeric + source-backed content even when model response is shallow.
            for heading in headings:
                sections[heading] = self._enrich_section_with_evidence(
                    heading,
                    sections.get(heading, ""),
                    focused_sources,
                )
            return name, sections

        group_tasks = [
            asyncio.create_task(_run_group(name, headings))
            for name, headings in section_groups.items()
        ]

        grouped_sections: Dict[str, Dict[str, str]] = {}
        llm_done = 0
        for task in asyncio.as_completed(group_tasks):
            gname, gsections = await task
            grouped_sections[gname] = gsections
            llm_done += 1
            await _emit(
                "progress",
                {
                    "stage": "synthesis",
                    "message": f"LLM section batch {llm_done}/{len(section_groups)} complete ({gname}).",
                },
            )
            await _add_step("tool_result", f"Completed section batch: {gname}", tool_name="llm_section_builder")

        tool_results[-1]["status"] = "completed"
        tool_results[-1]["result"] = {"batches": len(grouped_sections), "sections": sum(len(v) for v in grouped_sections.values())}

        all_report_headings = [
            "Executive Summary",
            "Introduction & Background",
            "Research Methodology",
            "Market Overview (size, growth, maturity)",
            "Market Segmentation",
            "Industry Analysis (PESTEL + Porter's Five Forces)",
            "Competitive Landscape",
            "Customer Analysis",
            "Market Trends & Drivers",
            "Challenges, Risks & Barriers",
            "SWOT Analysis",
            "Market Forecast & Projections",
            "Brand & Positioning Analysis — how existing players are positioned, brand perception, share of voice, and whitespace opportunities.",
            "Marketing Mix Assessment (4Ps / 7Ps) — product, price, place, promotion (plus people, process, physical evidence for services). Benchmarks current strategies in the market.",
            "Customer Journey & Touchpoint Mapping — awareness, consideration, purchase, retention, and advocacy stages, with friction points at each.",
            "Channel & Distribution Analysis — performance of digital vs. offline channels, e-commerce penetration, retail partnerships, direct-to-consumer trends.",
            "Digital Marketing & Media Landscape — SEO/SEM, social platforms, influencer ecosystem, content trends, paid media benchmarks, CAC and ROAS norms in the category.",
            "Pricing Strategy & Consumer Willingness-to-Pay — price elasticity, discounting patterns, premium vs. value segments.",
            "Brand Health & Sentiment Analysis — NPS, social listening insights, reviews, earned media themes.",
            "Go-to-Market Recommendations — campaign ideas, messaging pillars, target segments to prioritize, channel mix suggestions.",
            "AI Readiness Assessment of the Market — how mature the industry is in adopting AI, leading use cases, laggards vs. leaders.",
            "AI Use Cases & Applications — concrete opportunities across the value chain: demand forecasting, personalization, chatbots, dynamic pricing, content generation, fraud detection, supply chain optimization, etc.",
            "AI-Powered Marketing Opportunities — predictive segmentation, generative AI for creative, programmatic ad optimization, hyper-personalization, conversational commerce, AI-driven SEO/AEO (answer engine optimization).",
            "Competitive AI Benchmarking — what competitors are already doing with AI, tools they use, visible outcomes.",
            "Technology Stack & Vendor Landscape — key AI platforms, tools, and partners relevant to the industry (e.g., CRM AI add-ons, MarTech AI tools, industry-specific models).",
            "Data Infrastructure & Requirements — data availability, quality, governance needs, and gaps that must be closed before AI can deliver value.",
            "AI Risks, Ethics & Compliance — bias, hallucination, data privacy (GDPR, DPDP Act in India), IP concerns, regulatory outlook.",
            "Implementation Roadmap — phased approach: quick wins (0–6 months), mid-term builds (6–18 months), long-term transformation (18+ months), with estimated investment and ROI.",
            "Success Metrics & KPIs for AI Initiatives — efficiency gains, revenue lift, cost savings, customer experience improvements.",
            "Opportunities & Strategic Recommendations (now synthesizing market + marketing + AI insights)",
            "Conclusion",
            "Appendices",
            "References / Sources",
            "Glossary (helpful since AI and marketing jargon can overwhelm non-specialist readers)",
        ]

        merged_sections: Dict[str, str] = {}
        for g in grouped_sections.values():
            merged_sections.update(g)

        references_lines: List[str] = []
        for s in cited_sources[:80]:
            sid = s.get("source_id") or "S?"
            title = s.get("title", "Untitled source")
            url = s.get("url", "")
            if url:
                references_lines.append(f"[{sid}] [{title}]({url})")
            else:
                references_lines.append(f"[{sid}] {title}")
        references_text = "\n".join(references_lines) if references_lines else "No external references retrieved."

        report_parts: List[str] = []
        report_parts.append("# Front Matter")
        report_parts.append("## Title Page\n" + merged_sections.get("Title Page", self._fallback_section_text("Title Page", query)))
        report_parts.append("## Table of Contents\n" + self._build_toc(all_report_headings))
        report_parts.append("## Executive Summary\n" + merged_sections.get("Executive Summary", self._fallback_section_text("Executive Summary", query)))

        report_parts.append("# Core Market Research Sections")
        for h in section_groups["core"]:
            report_parts.append(f"## {h}\n" + merged_sections.get(h, self._fallback_section_text(h, query)))

        report_parts.append("# Marketing Perspective Sections (new)")
        for h in section_groups["marketing"]:
            report_parts.append(f"## {h}\n" + merged_sections.get(h, self._fallback_section_text(h, query)))

        report_parts.append("# AI Implementation Scope Sections (new)")
        for h in section_groups["ai_scope"]:
            report_parts.append(f"## {h}\n" + merged_sections.get(h, self._fallback_section_text(h, query)))

        report_parts.append("# Strategic Close")
        for h in section_groups["strategic_close"]:
            report_parts.append(f"## {h}\n" + merged_sections.get(h, self._fallback_section_text(h, query)))

        report_parts.append("# Back Matter")
        report_parts.append("## Appendices\n" + merged_sections.get("Appendices", self._fallback_section_text("Appendices", query)))
        report_parts.append("## References / Sources\n" + references_text)
        report_parts.append(
            "## Glossary (helpful since AI and marketing jargon can overwhelm non-specialist readers)\n"
            + merged_sections.get(
                "Glossary (helpful since AI and marketing jargon can overwhelm non-specialist readers)",
                self._fallback_section_text("Glossary", query),
            )
        )

        summary = "\n\n".join(report_parts)
        await _emit("progress", {"stage": "synthesis", "message": "Unified report assembled with all required sections."})
        await _add_step("observation", "Composed a single consolidated report with front matter, core, marketing, AI, strategic close, and back matter sections")
        
        # Determine email recipients: prioritize query emails, then API param, then defaults
        email_sent = False
        email_recipients_sent = []
        extracted_emails = self._extract_emails_from_query(query)
        
        # Priority: 1. Extracted from query, 2. API parameter, 3. Hardcoded defaults
        if extracted_emails:
            final_recipients = extracted_emails
            await _add_step("thinking", f"Detected email address(es) in query: {', '.join(extracted_emails)}")
        elif email_recipients and len(email_recipients) > 0:
            final_recipients = email_recipients
        else:
            final_recipients = ["daspapun21@gmail.com"]
            await _add_step("thinking", f"Using default email recipients: {', '.join(final_recipients)}")
        
        # Always send email if we have recipients
        if final_recipients and len(final_recipients) > 0:
            await _emit("progress", {"stage": "email", "message": "Preparing email-ready report..."})

            await _add_step(
                "tool_call",
                f"Sending research report via email to {len(final_recipients)} recipient(s): {', '.join(final_recipients)}",
                tool_name="email_sender",
                tool_input=f'{{"recipients": {final_recipients}}}',
            )
            
            tool_results.append({
                "tool": "email_sender",
                "input": {"recipients": final_recipients},
                "status": "running"
            })
            
            # Use LLM to generate clean HTML email body
            await _add_step("thinking", "Generating professional HTML email format using LLM")
            
            email_body_html = self._generate_email_html(
                query=query,
                markdown_report=summary,
                sources=[s.dict() for s in sources[:10]]
            )
            
            # Wrap in email template
            html_content = format_research_as_html(
                query=query,
                summary=email_body_html,
                sources=[s.dict() for s in sources[:10]]
            )
            
            email_result = send_research_email(
                recipients=final_recipients,
                subject=f"Market Research Report: {query[:50]}...",
                html_content=html_content
            )
            
            if email_result["success"]:
                email_sent = True
                email_recipients_sent = final_recipients
                tool_results[-1]["status"] = "completed"
                tool_results[-1]["result"] = {"message": email_result["message"]}
                await _add_step("tool_result", f"Email sent successfully to {', '.join(final_recipients)}", tool_name="email_sender")
                await _emit("progress", {"stage": "email", "message": "Research report emailed successfully."})
            else:
                email_recipients_sent = final_recipients
                tool_results[-1]["status"] = "error"
                tool_results[-1]["result"] = {"error": email_result["error"]}
                await _add_step("tool_result", f"Email delivery failed: {email_result['error']}", tool_name="email_sender")
                await _emit("progress", {"stage": "email", "message": "Report generated; email delivery failed."})

        await _emit("progress", {"stage": "final", "message": "Market research generation complete."})
        
        return MarketResearchResponse(
            success=True,
            query=query,
            response=summary,
            timestamp=datetime.now().isoformat(),
            session_id=current_session_id,
            sources=sources,
            email_sent=email_sent,
            email_recipients=email_recipients_sent,
            thinking_steps=thinking_steps,
            tool_results=tool_results
        )
