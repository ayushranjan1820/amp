"""Canned agent responses keyed by display name (as passed to _stream_agent_response)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

_BPMN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
  id="Definitions_1">
  <bpmn:process id="Process_1" isExecutable="false">
    <bpmn:startEvent id="StartEvent_1" name="Request received"/>
    <bpmn:task id="Task_Review" name="Review request"/>
    <bpmn:task id="Task_Approve" name="Manager approval"/>
    <bpmn:exclusiveGateway id="Gateway_1" name="Approved?"/>
    <bpmn:task id="Task_Process" name="Process request"/>
    <bpmn:task id="Task_Revise" name="Revise and resubmit"/>
    <bpmn:endEvent id="EndEvent_1" name="Completed"/>
    <bpmn:endEvent id="EndEvent_2" name="Rejected"/>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Task_Review"/>
    <bpmn:sequenceFlow id="Flow_2" sourceRef="Task_Review" targetRef="Task_Approve"/>
    <bpmn:sequenceFlow id="Flow_3" sourceRef="Task_Approve" targetRef="Gateway_1"/>
    <bpmn:sequenceFlow id="Flow_4" sourceRef="Gateway_1" targetRef="Task_Process" name="Yes"/>
    <bpmn:sequenceFlow id="Flow_5" sourceRef="Gateway_1" targetRef="Task_Revise" name="No"/>
    <bpmn:sequenceFlow id="Flow_6" sourceRef="Task_Process" targetRef="EndEvent_1"/>
    <bpmn:sequenceFlow id="Flow_7" sourceRef="Task_Revise" targetRef="EndEvent_2"/>
  </bpmn:process>
</bpmn:definitions>"""

_COMPANY_RESEARCH = """## Company Overview & Business Profile

Acme Corporation operates in enterprise software with a focus on workflow automation. The company serves mid-market and enterprise clients across financial services, healthcare, and manufacturing. Founded in 2008, Acme has grown through a combination of organic expansion and three strategic acquisitions in the last five years.

**Headquarters:** San Francisco, CA · **Employees:** ~4,200 · **Primary segments:** B2B SaaS, professional services

## Financial Performance Analysis

| Metric | FY2024 | FY2023 | Change |
|--------|--------|--------|--------|
| Revenue | $2.4B | $2.1B | +14.3% |
| Gross Margin | 72.1% | 70.8% | +1.3 pp |
| EBITDA | $480M | $410M | +17.1% |
| Net Income | $312M | $268M | +16.4% |
| Free Cash Flow | $198M | $165M | +20.0% |

Revenue growth was driven primarily by expansion in existing accounts (+18% net retention) and new logo acquisition in EMEA (+22% YoY).

## Balance Sheet Analysis

Total assets grew to **$3.8B**, driven by cash reserves ($920M) and goodwill from the DataFlow acquisition. Debt-to-equity remains conservative at **0.42**, with no near-term maturities. Working capital improved by 8% due to tighter receivables management.

## Competitive Landscape

| Competitor | Market Share | Key Differentiator |
|------------|--------------|-------------------|
| WorkFlow Pro | 28% | Low-code builder |
| ProcessEdge | 19% | AI-native automation |
| Acme Corp | 14% | Enterprise compliance + integrations |
| AutomateNow | 11% | SMB pricing |

## Sales Pitch Focus Areas

1. **Digital transformation ROI** — proven 30% efficiency gains in pilot deployments across 12 Fortune 500 clients
2. **Compliance automation** — SOC 2 Type II and ISO 27001 certified platform with audit-ready logging
3. **Integration ecosystem** — 200+ pre-built connectors (Salesforce, SAP, ServiceNow, JIRA)
4. **Time-to-value** — average 6-week implementation vs. 16-week industry benchmark

## Recommended Next Steps

- Schedule a technical deep-dive with their VP Engineering
- Prepare a tailored ROI model based on their stated automation goals
- Share the FinServ case study (similar scale, 34% cost reduction)
"""

_COMPANY_AI_SOLUTIONS = """## Recommended AI Solutions for Acme Corporation

Based on Acme's industry profile, operational scale, and stated priorities around cost reduction and customer experience, I've identified four high-impact AI initiatives ranked by feasibility and expected ROI.

### Solution 1: Intelligent Document Processing (IDP)
**Type:** Process Automation · **Priority:** High · **Timeline:** 8–12 weeks

**Why This Is Relevant:** Acme processes an estimated 45,000 invoices and contracts monthly across AP, legal, and procurement. Current manual extraction error rate is ~4.2%.

**Implementation Plan:**
1. Deploy OCR + LLM extraction pipeline integrated with SAP ERP
2. Human-in-the-loop review queue for confidence scores below 92%
3. Feedback loop to fine-tune extraction models on Acme-specific templates

**Expected Impact:** 60% reduction in manual data entry · 95% field-level accuracy · $1.2M annual savings

---

### Solution 2: Customer Support Copilot
**Type:** Customer Experience · **Priority:** High · **Timeline:** 6–10 weeks

**Why This Is Relevant:** Support ticket volume grew 22% YoY while CSAT declined 6 points to 74. Tier-1 tickets account for 68% of volume.

**Implementation Plan:**
1. RAG over knowledge base (2,400 articles) with citation-backed responses
2. Escalation rules for billing, security, and outage categories
3. Agent assist panel for human reps on complex cases

**Expected Impact:** 40% faster resolution · CSAT +12 points · 25% reduction in tier-1 headcount

---

### Solution 3: Predictive Maintenance for SaaS Infrastructure
**Type:** Operations · **Priority:** Medium · **Timeline:** 12–16 weeks

**Why This Is Relevant:** Three unplanned outages in Q4 2024 cost an estimated $890K in SLA credits.

**Expected Impact:** 45% reduction in MTTR · 99.95% uptime target · $600K annual SLA savings

---

### Solution 4: Sales Intelligence & Lead Scoring
**Type:** Revenue · **Priority:** Medium · **Timeline:** 10–14 weeks

**Expected Impact:** 18% improvement in lead-to-opportunity conversion · 12-day reduction in sales cycle
"""

_JIRA_CHART = {
    "summary": {
        "total": 24,
        "by_status": {"To Do": 8, "In Progress": 10, "Done": 6},
        "by_priority": {"Highest": 2, "High": 7, "Medium": 11, "Low": 4},
    },
    "tickets": [
        {"key": "PROJ-101", "summary": "Implement SSO integration", "status": "In Progress", "priority": "High", "assignee": "Alex Chen"},
        {"key": "PROJ-102", "summary": "Fix dashboard loading performance", "status": "To Do", "priority": "Highest", "assignee": "Maria Santos"},
        {"key": "PROJ-103", "summary": "Update API documentation", "status": "Done", "priority": "Medium", "assignee": "James Wilson"},
        {"key": "PROJ-104", "summary": "Migrate auth service to OAuth 2.1", "status": "In Progress", "priority": "High", "assignee": "Alex Chen"},
        {"key": "PROJ-105", "summary": "Add rate limiting to public API", "status": "To Do", "priority": "High", "assignee": "Unassigned"},
        {"key": "PROJ-106", "summary": "Resolve SonarQube blocker on payment module", "status": "In Progress", "priority": "Highest", "assignee": "James Wilson"},
    ],
}


def _thinking(steps: List[str | Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for step in steps:
        if isinstance(step, dict):
            out.append(step)
        else:
            out.append({"type": "thinking", "content": step, "tool_name": None, "tool_input": None})
    return out


def _tool_step(content: str, tool_name: str, tool_input: Optional[str] = None) -> Dict[str, Any]:
    return {"type": "tool_call", "content": content, "tool_name": tool_name, "tool_input": tool_input}


def _tool_result(content: str, tool_name: str) -> Dict[str, Any]:
    return {"type": "tool_result", "content": content, "tool_name": tool_name, "tool_input": None}


def _base(query: Optional[str], response: str, **extra) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "success": True,
        "query": query or "",
        "response": response,
        "thinking_steps": extra.pop("thinking_steps", _thinking(["Analyzing your request…", "Preparing response…"])),
        "timestamp": datetime.now().isoformat(),
    }
    out.update(extra)
    return out


def build_agent_result(
    agent_name: str,
    query: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    q = (query or "").strip()
    q_preview = q[:80] + ("…" if len(q) > 80 else "") if q else "your request"

    name = agent_name.lower()

    if name == "global chat":
        routed = {"agent_id": "jira_agent", "agent_name": "JIRA Agent", "confidence": 0.92, "reasoning": "Query references sprint tickets and project status"}
        return _base(
            q,
            f"I've analyzed your message and routed it to the **JIRA Agent** with 92% confidence.\n\n"
            f"Regarding *{q_preview}*, here's what I found in **Sprint 42** (Mar 10 – Mar 24):\n\n"
            "### Sprint Snapshot\n"
            "- **8** tickets in To Do · **10** in Progress · **6** Done\n"
            "- **2** Highest-priority items need attention before sprint end\n"
            "- Velocity trending at **34 story points** (target: 38)\n\n"
            "### Items Requiring Action\n"
            "| Key | Summary | Assignee | Due |\n"
            "|-----|---------|----------|-----|\n"
            "| PROJ-102 | Dashboard perf fix | Maria Santos | Mar 22 |\n"
            "| PROJ-106 | SonarQube blocker | James Wilson | Mar 21 |\n\n"
            "Would you like a breakdown by assignee, priority, or blocked dependencies?",
            routed_to=routed,
            session_id=session_id or "",
            chart_data=_JIRA_CHART,
            thinking_steps=_thinking([
                "Parsing user intent and conversation context…",
                _tool_step("Scoring 28 registered agents against query embedding", "agent_router", q_preview),
                _tool_result("Top match: JIRA Agent (0.92) — keywords: sprint, tickets, status", "agent_router"),
                "Fetching sprint board data from JIRA Cloud…",
            ]),
        )

    if "jira" in name:
        return _base(
            q,
            f"## Sprint 42 Summary\n\n"
            f"Query: *{q_preview}*\n\n"
            "### Board Overview\n"
            "Sprint 42 runs **Mar 10 – Mar 24**. Team capacity is 320 hours; **287 hours** are currently allocated.\n\n"
            "| Key | Summary | Status | Priority | Assignee | Story Pts |\n"
            "|-----|---------|--------|----------|----------|----------|\n"
            "| PROJ-101 | Implement SSO integration | In Progress | High | Alex Chen | 8 |\n"
            "| PROJ-102 | Fix dashboard loading performance | To Do | Highest | Maria Santos | 5 |\n"
            "| PROJ-103 | Update API documentation | Done | Medium | James Wilson | 3 |\n"
            "| PROJ-104 | Migrate auth to OAuth 2.1 | In Progress | High | Alex Chen | 13 |\n"
            "| PROJ-105 | Add rate limiting to public API | To Do | High | Unassigned | 5 |\n"
            "| PROJ-106 | Resolve SonarQube blocker | In Progress | Highest | James Wilson | 3 |\n\n"
            "### Risk Flags\n"
            "- **PROJ-102** has no progress in 4 days — likely blocked on infra provisioning\n"
            "- **PROJ-105** is unassigned with 3 days remaining\n"
            "- SSO migration (PROJ-104) is on track but depends on PROJ-101 completing first\n\n"
            "**Recommendation:** Reassign PROJ-105 to Maria Santos after PROJ-102, and escalate PROJ-106 to daily standup.",
            chart_data=_JIRA_CHART,
            tickets=_JIRA_CHART["tickets"],
            success=True,
            state="complete",
            thinking_steps=_thinking([
                _tool_step("Connecting to JIRA Cloud API", "jira_client", "project=PROJ, sprint=42"),
                _tool_result("Retrieved 24 issues across 4 statuses", "jira_client"),
                "Analyzing blockers, dependencies, and velocity trends…",
            ]),
        )

    if "bpmn" in name:
        return _base(
            q,
            f"## BPMN Process Diagram Generated\n\n"
            f"I've modeled the workflow you described (*{q_preview}*) as a **BPMN 2.0** process diagram.\n\n"
            "### Process Summary\n"
            "1. **Start** — Request received via portal or email\n"
            "2. **Review request** — Analyst validates completeness and attachments\n"
            "3. **Manager approval** — Approver reviews within SLA (2 business days)\n"
            "4. **Decision gateway** — Approved requests proceed to processing; rejected requests return for revision\n"
            "5. **End states** — Completed (success) or Rejected (requires resubmission)\n\n"
            "### Elements Included\n"
            "- 1 start event · 4 tasks · 1 exclusive gateway · 2 end events · 7 sequence flows\n\n"
            "The diagram is rendered below. You can export it to Camunda, Signavio, or any BPMN 2.0-compatible tool.",
            bpmn_xml=_BPMN_XML,
            thinking_steps=_thinking([
                "Extracting process steps and decision points from natural language…",
                _tool_step("Generating BPMN 2.0 XML", "bpmn_generator", q_preview),
                _tool_result("Valid XML produced — 4 tasks, 1 gateway, 2 end events", "bpmn_generator"),
            ]),
        )

    if "company research" in name:
        return _base(
            q,
            _COMPANY_RESEARCH,
            latest_news_cards=[
                {"title": "Acme Corp Q4 earnings beat estimates by 8%", "url": "https://example.com/news/1", "snippet": "Revenue up 14% YoY; raises FY2025 guidance", "source": "Financial Times", "date": "2025-03-15"},
                {"title": "Acme announces strategic AI partnership with NovaTech", "url": "https://example.com/news/2", "snippet": "Joint go-to-market for enterprise document AI", "source": "Reuters", "date": "2025-03-10"},
                {"title": "Acme expands EMEA presence with London office", "url": "https://example.com/news/3", "snippet": "Plans to hire 200 engineers over 18 months", "source": "Bloomberg", "date": "2025-03-05"},
            ],
            thinking_steps=_thinking([
                _tool_step("Searching financial databases and news sources", "perplexity_search", q_preview),
                _tool_result("12 relevant sources found — aggregating company profile", "perplexity_search"),
                "Structuring report: overview, financials, competitive landscape…",
            ]),
        )

    if "company ai solutions" in name:
        return _base(
            q,
            _COMPANY_AI_SOLUTIONS,
            thinking_steps=_thinking([
                "Analyzing company profile and industry vertical…",
                _tool_step("Matching against AI solution catalog (847 patterns)", "solution_matcher", q_preview),
                _tool_result("4 high-fit solutions identified — ranking by ROI", "solution_matcher"),
            ]),
        )

    if "rbi circular" in name:
        return _base(
            q,
            f"## RBI Circular Analysis\n\n"
            f"**Query:** *{q_preview}*\n\n"
            "### Applicable Circular\n"
            "**RBI/2024-25/112** — *Framework for Regulated Entities on Digital Lending and Data Governance* "
            "(Issued: January 15, 2025 · Effective: April 1, 2025)\n\n"
            "### Key Provisions\n"
            "1. **Data localization** — Customer financial data must remain on servers physically located in India\n"
            "2. **Consent architecture** — Explicit, granular consent required before data sharing with third-party lenders\n"
            "3. **Algorithmic transparency** — Credit scoring models must be explainable; bias audits mandatory annually\n"
            "4. **Grievance redressal** — 72-hour SLA for digital lending complaints; dedicated nodal officer required\n\n"
            "### Compliance Gap Assessment\n"
            "| Requirement | Current Status | Gap | Priority |\n"
            "|-------------|---------------|-----|----------|\n"
            "| Data localization | Partial — 2 of 5 vendors compliant | Medium | High |\n"
            "| Consent management | Legacy checkbox model | Significant | Critical |\n"
            "| Model explainability | Not implemented | Critical | Critical |\n"
            "| Grievance SLA tracking | Manual spreadsheet | Moderate | High |\n\n"
            "### Recommended Actions\n"
            "1. Conduct vendor audit for data residency by **March 31, 2025**\n"
            "2. Deploy consent management platform with audit trail\n"
            "3. Engage compliance counsel for model documentation review\n"
            "4. Establish RBI reporting dashboard with automated deadline tracking",
            thinking_steps=_thinking([
                _tool_step("Searching RBI circular database", "rbi_search", q_preview),
                _tool_result("Matched RBI/2024-25/112 — extracting key provisions", "rbi_search"),
                "Cross-referencing against standard compliance framework…",
            ]),
        )

    if "sebi circular" in name:
        return _base(
            q,
            f"## SEBI Circular Analysis\n\n"
            f"**Query:** *{q_preview}*\n\n"
            "### Applicable Circular\n"
            "**SEBI/HO/IMD/IMD-PoD-1/P/CIR/2025/018** — *Cyber Security and Cyber Resilience Framework for Market Infrastructure Institutions* "
            "(Issued: February 3, 2025)\n\n"
            "### Key Requirements\n"
            "1. **VAPT frequency** — Vulnerability assessment and penetration testing every 6 months (was annual)\n"
            "2. **Incident reporting** — Material cyber incidents reported to SEBI within **6 hours** (was 24 hours)\n"
            "3. **Third-party risk** — All vendor access must use zero-trust architecture with MFA\n"
            "4. **Board oversight** — Quarterly cyber resilience reports to board audit committee\n\n"
            "### Compliance Timeline\n"
            "| Milestone | Deadline | Owner |\n"
            "|-----------|----------|-------|\n"
            "| VAPT vendor engagement | Apr 15, 2025 | CISO |\n"
            "| Zero-trust rollout (Phase 1) | Jun 30, 2025 | Infrastructure |\n"
            "| Incident response playbook update | May 1, 2025 | Security Ops |\n"
            "| Board reporting template | Apr 30, 2025 | Compliance |\n\n"
            "### Risk Summary\n"
            "Current posture meets **62%** of new requirements. Critical gaps in incident reporting automation and vendor access controls.",
            thinking_steps=_thinking([
                _tool_step("Querying SEBI circular repository", "sebi_search", q_preview),
                _tool_result("Primary match: CIR/2025/018 — cyber resilience framework", "sebi_search"),
                "Building compliance gap matrix and action plan…",
            ]),
        )

    if "market research" in name:
        return _base(
            q,
            f"## Market Research Report\n\n"
            f"**Topic:** *{q_preview}*\n\n"
            "### Executive Summary\n"
            "The enterprise AI agents market is projected to reach **$47.1B by 2028** (CAGR 44.8%). "
            "Adoption is shifting from pilot projects to production deployments, with governance and ROI measurement "
            "emerging as the primary buyer concerns in 2025.\n\n"
            "### Market Size & Growth\n"
            "| Segment | 2024 | 2025E | 2028E | CAGR |\n"
            "|---------|------|-------|-------|------|\n"
            "| Agent platforms | $4.2B | $6.8B | $18.3B | 48% |\n"
            "| RAG infrastructure | $2.1B | $3.4B | $9.7B | 52% |\n"
            "| Agent governance | $0.8B | $1.6B | $5.2B | 58% |\n\n"
            "### Key Trends\n"
            "1. **Agentic workflows** — Multi-step autonomous agents replacing single-turn chatbots\n"
            "2. **Model routing** — Cost optimization via intelligent model selection (frontier vs. efficient models)\n"
            "3. **Observability** — Langfuse, Arize, and custom tracing becoming table stakes\n"
            "4. **Vertical specialization** — Industry-specific agents outperforming general-purpose platforms by 2.3x on task completion\n\n"
            "### Competitive Landscape\n"
            "Top vendors by enterprise adoption: Microsoft Copilot Studio, Salesforce Agentforce, custom internal platforms (34% of Fortune 500).\n\n"
            "### Recommendations\n"
            "- Prioritize governance framework before scaling agent deployments\n"
            "- Start with high-ROI, low-risk use cases (document processing, internal support)\n"
            "- Budget 15–20% of AI spend on observability and evaluation infrastructure",
            thinking_steps=_thinking([
                _tool_step("Running web search across industry reports", "web_search", q_preview),
                _tool_result("18 sources aggregated — synthesizing market data", "web_search"),
                "Generating structured report with sizing, trends, and recommendations…",
            ]),
        )

    if "meeting prep" in name:
        return _base(
            q,
            f"## Meeting Preparation Brief\n\n"
            f"**Meeting context:** *{q_preview}*\n\n"
            "### Attendees\n"
            "| Name | Role | Company | Notes |\n"
            "|------|------|---------|-------|\n"
            "| Sarah Chen | VP Engineering | Acme Corp | Decision maker · technical background |\n"
            "| David Park | Director, IT | Acme Corp | Budget owner · cost-focused |\n"
            "| You | Account Executive | — | Lead presenter |\n\n"
            "### Agenda (60 min)\n"
            "1. **Introductions & objectives** (5 min)\n"
            "2. **Current state assessment** — their automation maturity (10 min)\n"
            "3. **Demo: IDP + Support Copilot** (20 min)\n"
            "4. **ROI discussion** — $1.2M projected savings (15 min)\n"
            "5. **Next steps & timeline** (10 min)\n\n"
            "### Talking Points\n"
            "- Reference their Q4 earnings call mention of \"operational efficiency initiatives\"\n"
            "- Lead with the FinServ case study (similar company size, 34% cost reduction)\n"
            "- Address likely objection: implementation timeline — our avg is 6 weeks vs. 16-week industry\n\n"
            "### Questions to Ask\n"
            "1. What's your current ticket resolution time for tier-1 support?\n"
            "2. How many FTEs are dedicated to manual document processing today?\n"
            "3. What's your timeline for the digital transformation roadmap?\n\n"
            "### Pre-Read Materials\n"
            "- Acme Corp company profile (attached in CRM)\n"
            "- Product one-pager: Intelligent Document Processing\n"
            "- ROI calculator pre-filled with their estimated volumes",
            thinking_steps=_thinking([
                _tool_step("Researching attendee profiles and company news", "perplexity_search", q_preview),
                _tool_result("3 attendees identified — pulling recent company announcements", "perplexity_search"),
                _tool_step("Generating tailored agenda and talking points", "meeting_brief_generator"),
                _tool_result("60-min brief ready with 3 discussion questions", "meeting_brief_generator"),
            ]),
        )

    if "web search" in name:
        return _base(
            q,
            f"## Web Search Results\n\n"
            f"**Query:** *{q_preview}*\n\n"
            "### Summary\n"
            "Enterprise AI adoption accelerated significantly in H1 2025. Organizations are moving beyond proof-of-concept "
            "chatbots toward production agent workflows with built-in governance. Key drivers include cost pressure "
            "(avg 23% IT budget increase for AI), competitive urgency, and improved model reliability.\n\n"
            "Three dominant patterns emerged across sources:\n"
            "1. **RAG-first architecture** — Grounding agents in proprietary data before adding tool use\n"
            "2. **Human-in-the-loop by default** — Approval gates for high-stakes actions (financial, legal, external comms)\n"
            "3. **Multi-model strategies** — Frontier models for reasoning, efficient models for classification and routing\n\n"
            "### Key Sources\n"
            "See cited references below for full reports from Gartner, McKinsey, and vendor benchmarks.",
            is_web_search=True,
            search_focus="general",
            sources=[
                {"title": "Enterprise AI Trends 2025 — Gartner", "url": "https://example.com/a", "snippet": "72% of enterprises plan agent deployments by Q3 2025", "domain": "gartner.com"},
                {"title": "The State of AI Agents — McKinsey", "url": "https://example.com/b", "snippet": "Agent workflows deliver 3.7x ROI vs. standalone chatbots", "domain": "mckinsey.com"},
                {"title": "Agent Platform Comparison 2025", "url": "https://example.com/c", "snippet": "Feature matrix across 12 leading platforms", "domain": "example.com"},
            ],
            web_search_sources=[
                {"title": "Enterprise AI Trends 2025 — Gartner", "url": "https://example.com/a", "snippet": "72% of enterprises plan agent deployments by Q3 2025", "domain": "gartner.com", "image_url": None},
                {"title": "The State of AI Agents — McKinsey", "url": "https://example.com/b", "snippet": "Agent workflows deliver 3.7x ROI vs. standalone chatbots", "domain": "mckinsey.com", "image_url": None},
            ],
            web_search_follow_ups=["What are the top agent platforms?", "Show implementation timelines", "Compare build vs. buy approaches"],
            web_search_focus="general",
            thinking_steps=_thinking([
                _tool_step("Searching the web via Perplexity", "perplexity_search", q_preview),
                _tool_result("14 sources found — synthesizing across 3 authoritative reports", "perplexity_search"),
            ]),
        )

    if "ppt" in name or "presentation" in name:
        return _base(
            q,
            f"## Presentation Generated\n\n"
            f"Your presentation **Q4 Strategy Review** has been created based on *{q_preview}*.\n\n"
            "### Slide Outline (8 slides)\n"
            "1. **Title** — Q4 Strategy Review · March 2025\n"
            "2. **Executive Summary** — Key wins, challenges, outlook\n"
            "3. **Market Context** — Industry trends and competitive shifts\n"
            "4. **Financial Highlights** — Revenue, margin, cash flow\n"
            "5. **Product Roadmap** — Shipped features and upcoming releases\n"
            "6. **Customer Metrics** — NRR, churn, expansion revenue\n"
            "7. **Strategic Priorities** — Top 3 initiatives for Q2\n"
            "8. **Next Steps** — Action items and ownership\n\n"
            "Research from 3 industry sources was incorporated into slides 3–4. "
            "Download the deck below or ask me to regenerate specific slides.",
            download_url="/api/ppt-generator/download/sample-deck.pptx",
            download_file_name="Q4_Strategy_Review.pptx",
            ppt_research_sources=[
                {"title": "Industry outlook 2025 — Deloitte", "url": "https://example.com/r1", "date": "2025-01"},
                {"title": "SaaS benchmarks Q4 2024", "url": "https://example.com/r2", "date": "2025-02"},
            ],
            thinking_steps=_thinking([
                _tool_step("Researching topic via web search", "perplexity_search", q_preview),
                _tool_result("3 industry reports retrieved for slide content", "perplexity_search"),
                _tool_step("Generating PowerPoint via python-pptx", "ppt_generator", "8 slides, corporate template"),
                _tool_result("Deck saved — Q4_Strategy_Review.pptx (2.4 MB)", "ppt_generator"),
            ]),
        )

    if "email" in name:
        return _base(
            q,
            f"I've drafted the email below based on your request (*{q_preview}*). Review the preview and let me know if you'd like any changes before sending.",
            email_preview={
                "to": "stakeholders@example.com",
                "cc": "engineering-leads@example.com",
                "subject": "Sprint 42 Update — Progress, Blockers & Next Steps",
                "body_html": (
                    "<p>Hi team,</p>"
                    "<p>Here's the Sprint 42 update as of March 18:</p>"
                    "<p><strong>Progress</strong></p>"
                    "<ul>"
                    "<li>SSO integration (PROJ-101) — 70% complete, on track for Mar 22</li>"
                    "<li>API documentation (PROJ-103) — Done ✓</li>"
                    "<li>OAuth 2.1 migration (PROJ-104) — In progress, no blockers</li>"
                    "</ul>"
                    "<p><strong>Blockers</strong></p>"
                    "<ul>"
                    "<li>Dashboard perf fix (PROJ-102) — waiting on infra provisioning</li>"
                    "<li>Rate limiting (PROJ-105) — unassigned, needs owner by EOD</li>"
                    "</ul>"
                    "<p><strong>Next Steps</strong></p>"
                    "<ul>"
                    "<li>Escalate PROJ-106 (SonarQube blocker) in tomorrow's standup</li>"
                    "<li>Reassign PROJ-105 after PROJ-102 completes</li>"
                    "</ul>"
                    "<p>Please reply with any questions or concerns.</p>"
                    "<p>Best regards</p>"
                ),
                "status": "draft",
            },
            thinking_steps=_thinking([
                "Analyzing context and tone requirements…",
                _tool_step("Drafting email with structured sections", "email_composer", q_preview),
                _tool_result("Draft ready — 342 words, professional tone", "email_composer"),
            ]),
        )

    if "browser" in name and "webmcp" not in name:
        return _base(
            q,
            f"## Browser Automation Complete\n\n"
            f"**Task:** *{q_preview}*\n\n"
            "### Execution Summary\n"
            "Successfully completed a 4-step browser workflow with full screenshot capture at each stage.\n\n"
            "| Step | Action | Target | Result | Duration |\n"
            "|------|--------|--------|--------|----------|\n"
            "| 1 | Navigate | https://example.com/login | Page loaded (200 OK) | 1.2s |\n"
            "| 2 | Fill form | Username & password fields | Credentials entered | 0.8s |\n"
            "| 3 | Click | Submit button | Redirected to dashboard | 2.1s |\n"
            "| 4 | Extract | Dashboard table data | 12 rows captured | 1.4s |\n\n"
            "**Total duration:** 5.5s · **Status:** Success · **Screenshots:** 4 captured\n\n"
            "The HTML report and step-by-step screenshots are available below.",
            browser_html_report_file="sample-report.html",
            browser_screenshots=[
                {"step": 1, "action": "navigate", "url": "https://example.com/login", "screenshot_base64": ""},
                {"step": 2, "action": "fill", "url": "https://example.com/login", "screenshot_base64": ""},
                {"step": 3, "action": "click", "url": "https://example.com/dashboard", "screenshot_base64": ""},
                {"step": 4, "action": "extract", "url": "https://example.com/dashboard", "screenshot_base64": ""},
            ],
            thinking_steps=_thinking([
                _tool_step("Launching headless browser session", "browser_launch", "chromium, viewport=1280x720"),
                _tool_result("Browser ready — executing 4-step workflow", "browser_launch"),
                _tool_step("Capturing screenshots at each step", "screenshot_capture"),
                _tool_result("4 screenshots saved — generating HTML report", "screenshot_capture"),
            ]),
        )

    if "webmcp" in name:
        return _base(
            q,
            f"## WebMCP Agent Response\n\n"
            f"**Query:** *{q_preview}*\n\n"
            "I connected to the browser via the WebMCP bridge and executed the requested actions using MCP tool calls.\n\n"
            "### Tools Invoked\n"
            "| Tool | Input | Result |\n"
            "|------|-------|--------|\n"
            "| `browser_navigate` | `https://example.com/docs` | Page loaded |\n"
            "| `browser_snapshot` | accessibility tree | 847 nodes captured |\n"
            "| `browser_click` | `#search-button` | Search panel opened |\n"
            "| `browser_type` | `{q_preview}` | 12 results found |\n\n"
            "### Extracted Content\n"
            "The documentation page confirms that API rate limits are **1,000 requests/minute** for standard tier "
            "and **10,000 requests/minute** for enterprise. Authentication requires OAuth 2.1 with PKCE.\n\n"
            "All interactions were performed through the MCP protocol — no direct DOM manipulation outside the bridge.",
            thinking_steps=_thinking([
                _tool_step("Connecting to WebMCP bridge", "mcp_connect", "ws://localhost:8931"),
                _tool_result("Bridge connected — 6 browser tools available", "mcp_connect"),
                _tool_step("Executing browser_navigate + browser_snapshot", "browser_navigate"),
                _tool_result("Page captured — running search interaction", "browser_navigate"),
            ]),
        )

    if "mongodb" in name or ("rag" in name and "kb" in name):
        return _base(
            q,
            f"## Knowledge Base Answer\n\n"
            f"**Question:** *{q_preview}*\n\n"
            "### Answer\n"
            "Based on the indexed policy documents, expenses above **$500** require prior manager approval before purchase. "
            "Receipts must be submitted through the expense portal within **30 days** of the transaction date. "
            "Late submissions require VP Finance approval and may be denied after 60 days.\n\n"
            "For international travel, per diem rates follow the GSA schedule. "
            "Mileage reimbursement is calculated at the current IRS standard rate ($0.67/mile for 2025).\n\n"
            "### Supporting Evidence\n"
            "The answer is grounded in 2 document sections with high relevance scores (see sources below).",
            sources=[
                {"file_name": "expense-policy.pdf", "section": "Section 4.2 — Approval Thresholds", "score": 0.94, "preview": "Expenses above $500 require manager approval prior to purchase. Employees must obtain written approval via the expense portal…"},
                {"file_name": "expense-policy.pdf", "section": "Section 5.1 — Receipt Submission", "score": 0.89, "preview": "All receipts must be submitted within 30 calendar days of the transaction. Late submissions require VP Finance approval…"},
                {"file_name": "travel-policy.pdf", "section": "Section 2.3 — Per Diem Rates", "score": 0.82, "preview": "International travel per diem follows GSA published rates. Mileage reimbursed at IRS standard rate…"},
            ],
            mongodb_rag_sources=[
                {"file_name": "expense-policy.pdf", "section": "Section 4.2 — Approval Thresholds", "score": 0.94, "preview": "Expenses above $500 require manager approval prior to purchase…"},
                {"file_name": "expense-policy.pdf", "section": "Section 5.1 — Receipt Submission", "score": 0.89, "preview": "All receipts must be submitted within 30 calendar days…"},
            ],
            thinking_steps=_thinking([
                _tool_step("Embedding query and searching vector index", "mongodb_vector_search", q_preview),
                _tool_result("3 chunks retrieved — top score 0.94", "mongodb_vector_search"),
                "Synthesizing answer with citation-backed evidence…",
            ]),
        )

    if "sql" in name:
        return _base(
            q,
            f"## SQL Query Results\n\n"
            f"**Question:** *{q_preview}*\n\n"
            "I analyzed your database schema and generated the following query:\n\n"
            "```sql\n"
            "SELECT\n"
            "    c.customer_id,\n"
            "    c.company_name,\n"
            "    COUNT(o.order_id) AS order_count,\n"
            "    SUM(o.amount) AS total_revenue,\n"
            "    AVG(o.amount) AS avg_order_value\n"
            "FROM customers c\n"
            "JOIN orders o ON c.customer_id = o.customer_id\n"
            "WHERE o.order_date >= '2025-01-01'\n"
            "  AND o.status = 'completed'\n"
            "GROUP BY c.customer_id, c.company_name\n"
            "ORDER BY total_revenue DESC\n"
            "LIMIT 10;\n"
            "```\n\n"
            "### Top 10 Customers by Revenue (2025 YTD)\n"
            "| Customer | Orders | Total Revenue | Avg Order |\n"
            "|----------|--------|---------------|----------|\n"
            "| Acme Industries | 142 | $284,500 | $2,003 |\n"
            "| GlobalTech Ltd | 98 | $196,200 | $2,002 |\n"
            "| Nova Systems | 87 | $173,400 | $1,993 |\n"
            "| Pacific Corp | 76 | $152,800 | $2,011 |\n"
            "| Summit Partners | 71 | $142,000 | $2,000 |\n\n"
            "*Showing top 5 of 10 results. Query executed in 124ms against PostgreSQL.*",
            thinking_steps=_thinking([
                _tool_step("Inspecting database schema", "sql_schema_inspect", "customers, orders"),
                _tool_result("12 tables found — identifying relevant joins", "sql_schema_inspect"),
                _tool_step("Generating and executing SQL query", "sql_execute"),
                _tool_result("10 rows returned in 124ms", "sql_execute"),
            ]),
        )

    if "github" in name or "repo" in name:
        return _base(
            q,
            f"## Repository Analysis\n\n"
            f"**Repository:** *{q_preview}*\n\n"
            "### Overview\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            "| Primary language | TypeScript (62%) |\n"
            "| Secondary languages | Python (28%), Shell (6%), Dockerfile (4%) |\n"
            "| Stars | 1,247 · Forks 183 |\n"
            "| Open PRs | 12 (3 draft) |\n"
            "| Open issues | 34 (8 labeled `bug`, 14 `enhancement`) |\n"
            "| Last commit | 2 hours ago by @alex-chen |\n"
            "| Default branch | `main` (protected) |\n\n"
            "### Code Health\n"
            "- **Test coverage:** 78.2% (Jest + pytest)\n"
            "- **CI status:** All checks passing on `main`\n"
            "- **Dependabot alerts:** 2 moderate (lodash, axios — patches available)\n"
            "- **Health score:** 8.4/10\n\n"
            "### Recent Activity\n"
            "| PR | Title | Author | Status |\n"
            "|----|-------|--------|--------|\n"
            "| #142 | Add OAuth 2.1 support | @alex-chen | Review requested |\n"
            "| #139 | Fix dashboard N+1 query | @maria-s | Approved, pending merge |\n"
            "| #137 | Update API docs for v3 | @james-w | Merged 2 days ago |\n\n"
            "### Recommendations\n"
            "1. Merge PR #139 — performance fix with full test coverage\n"
            "2. Address Dependabot alerts before next release\n"
            "3. Triage 8 open bugs — 3 are older than 30 days",
            thinking_steps=_thinking([
                _tool_step("Fetching repository metadata from GitHub API", "github_api", q_preview),
                _tool_result("Repo found — analyzing languages, PRs, and health metrics", "github_api"),
            ]),
        )

    if "sonarqube" in name:
        return _base(
            q,
            f"## SonarQube Analysis Report\n\n"
            f"**Project:** *{q_preview}*\n\n"
            "### Quality Gate: ⚠️ WARN\n"
            "| Metric | Value | Threshold | Status |\n"
            "|--------|-------|-----------|--------|\n"
            "| Bugs | 3 | ≤ 0 (blocker) | ❌ Fail |\n"
            "| Vulnerabilities | 1 | ≤ 0 (blocker) | ❌ Fail |\n"
            "| Code Smells | 47 | ≤ 50 | ✅ Pass |\n"
            "| Coverage | 78.2% | ≥ 80% | ⚠️ Warn |\n"
            "| Duplications | 2.1% | ≤ 3% | ✅ Pass |\n"
            "| Security Hotspots | 4 | 0 unreviewed | ⚠️ Warn |\n\n"
            "### Critical Issues\n"
            "1. **NullPointerException** in `PaymentService.process()` — line 142 (Bug, Blocker)\n"
            "2. **SQL injection risk** in `UserRepository.findByEmail()` — line 87 (Vulnerability, Critical)\n"
            "3. **Hardcoded credential** in test config — line 23 (Hotspot, High)\n\n"
            "### Recommended Fixes\n"
            "- Add null check before `paymentGateway.charge()` in PaymentService\n"
            "- Parameterize the SQL query in UserRepository\n"
            "- Move test credentials to environment variables\n\n"
            "*Analysis run on `main` branch · commit `a3f8c21` · 847 files analyzed*",
            thinking_steps=_thinking([
                _tool_step("Triggering SonarQube scan", "sonarqube_scan", "project=agents-platform"),
                _tool_result("Scan complete — Quality Gate: WARN (2 blocker conditions failed)", "sonarqube_scan"),
            ]),
        )

    if "shannon" in name:
        return _base(
            q,
            f"## Shannon Security Assessment\n\n"
            f"**Scope:** *{q_preview}*\n\n"
            "### Scan Summary\n"
            "Shannon completed a full-stack security assessment across application, infrastructure, and dependency layers.\n\n"
            "| Category | Findings | Critical | High | Medium | Low |\n"
            "|----------|----------|----------|------|--------|-----|\n"
            "| Application | 7 | 1 | 2 | 3 | 1 |\n"
            "| Infrastructure | 4 | 0 | 1 | 2 | 1 |\n"
            "| Dependencies | 12 | 0 | 3 | 6 | 3 |\n"
            "| Configuration | 3 | 1 | 1 | 1 | 0 |\n\n"
            "### Critical Findings\n"
            "1. **CVE-2024-38819** — Spring Framework path traversal (CVSS 9.8) — patch available\n"
            "2. **Exposed admin endpoint** — `/api/admin/debug` accessible without auth\n"
            "3. **Weak TLS configuration** — TLS 1.0/1.1 still enabled on load balancer\n\n"
            "### Remediation Priority\n"
            "1. Patch Spring Framework to 6.1.14+ (immediate)\n"
            "2. Restrict `/api/admin/*` to authenticated admin roles\n"
            "3. Disable TLS 1.0/1.1 — enforce TLS 1.2+ only\n\n"
            "**Overall risk score:** 7.2/10 (High) · Estimated remediation effort: 3–5 engineering days",
            thinking_steps=_thinking([
                _tool_step("Initializing Shannon security scan", "shannon_scan", q_preview),
                _tool_result("26 findings across 4 categories — 2 critical", "shannon_scan"),
                "Prioritizing remediation by CVSS score and exploitability…",
            ]),
        )

    if "unit test" in name:
        return _base(
            q,
            f"## Unit Test Report\n\n"
            f"**Target:** *{q_preview}*\n\n"
            "**Status:** ✅ PASSED\n\n"
            "### Summary\n"
            "| Metric | Value |\n"
            "|--------|-------|\n"
            "| Tests executed | 24 |\n"
            "| Passed | 24 |\n"
            "| Failed | 0 |\n"
            "| Skipped | 0 |\n"
            "| Duration | 12.4s |\n"
            "| Coverage (new) | +4.2% (72.1% → 76.3%) |\n\n"
            "### Generated Test Files\n"
            "- `tests/test_payment_service.py` — 8 tests (charge, refund, validation)\n"
            "- `tests/test_user_repository.py` — 6 tests (CRUD, edge cases)\n"
            "- `tests/test_auth_middleware.py` — 10 tests (token validation, expiry, roles)\n\n"
            "### Key Test Cases\n"
            "```python\n"
            "def test_process_payment_with_valid_card():\n"
            "    result = payment_service.process(card=VALID_CARD, amount=100.00)\n"
            "    assert result.status == 'success'\n"
            "    assert result.transaction_id is not None\n\n"
            "def test_process_payment_rejects_null_card():\n"
            "    with pytest.raises(ValidationError):\n"
            "        payment_service.process(card=None, amount=100.00)\n"
            "```\n\n"
            "All tests pass. Ready for PR creation.",
            thinking_steps=_thinking([
                _tool_step("Cloning repository and analyzing source files", "github_clone", q_preview),
                _tool_result("847 files scanned — 12 modules need test coverage", "github_clone"),
                _tool_step("Generating unit tests with LLM", "test_generator", "pytest, target=coverage+4%"),
                _tool_result("24 tests generated — running pytest", "test_generator"),
                _tool_result("All 24 tests passed in 12.4s", "pytest_runner"),
            ]),
        )

    if "qa automation" in name:
        return _base(
            q,
            f"## QA Automation Report\n\n"
            f"**Test suite:** *{q_preview}*\n\n"
            "**Status:** ✅ PASSED\n\n"
            "### End-to-End Test Results\n"
            "| Suite | Tests | Passed | Failed | Duration |\n"
            "|-------|-------|--------|--------|----------|\n"
            "| Login flow | 6 | 6 | 0 | 18.2s |\n"
            "| Checkout flow | 8 | 8 | 0 | 34.7s |\n"
            "| Admin dashboard | 5 | 5 | 0 | 12.1s |\n"
            "| API integration | 10 | 10 | 0 | 8.4s |\n"
            "| **Total** | **29** | **29** | **0** | **73.4s** |\n\n"
            "### Browser Coverage\n"
            "- Chromium 122 · Firefox 124 · WebKit 17.4\n"
            "- Viewport: 1280×720 (desktop) + 390×844 (mobile)\n\n"
            "### Artifacts\n"
            "- Screenshots: 29 captured (on failure + key steps)\n"
            "- Video recording: available for checkout flow\n"
            "- Trace files: Playwright trace for debugging",
            thinking_steps=_thinking([
                _tool_step("Launching Playwright test runner", "playwright_run", "3 browsers, 29 tests"),
                _tool_result("29/29 passed across Chromium, Firefox, WebKit", "playwright_run"),
            ]),
        )

    if "web test" in name:
        return _base(
            q,
            f"## Web Test Report\n\n"
            f"**URL tested:** *{q_preview}*\n\n"
            "**Status:** ✅ PASSED\n\n"
            "### Test Results\n"
            "| Check | Result | Details |\n"
            "|-------|--------|--------|\n"
            "| Page load | ✅ Pass | 1.8s (target: <3s) |\n"
            "| Accessibility (WCAG 2.1 AA) | ✅ Pass | 0 violations |\n"
            "| Responsive layout | ✅ Pass | 3 breakpoints tested |\n"
            "| Form validation | ✅ Pass | 12 input scenarios |\n"
            "| Link integrity | ⚠️ Warn | 2 broken links found |\n"
            "| SEO meta tags | ✅ Pass | Title, description, OG tags present |\n\n"
            "### Broken Links\n"
            "1. `/docs/legacy-api` — 404 Not Found\n"
            "2. `/blog/2024-roadmap` — 301 redirect loop\n\n"
            "**Overall score:** 94/100 · 24 checks passed, 2 warnings",
            thinking_steps=_thinking([
                _tool_step("Running automated web test suite", "web_test_runner", q_preview),
                _tool_result("26 checks completed — 2 warnings (broken links)", "web_test_runner"),
            ]),
        )

    if "code sandbox" in name:
        return _base(
            q,
            f"## Code Sandbox Ready\n\n"
            f"I've built an interactive sandbox for *{q_preview}*.\n\n"
            "### Project Structure\n"
            "```\n"
            "src/\n"
            "├── App.tsx          # Main component with your implementation\n"
            "├── components/\n"
            "│   └── Dashboard.tsx # Data visualization panel\n"
            "├── hooks/\n"
            "│   └── useFetch.ts   # Custom data fetching hook\n"
            "└── index.tsx         # Entry point\n"
            "```\n\n"
            "### What's Included\n"
            "- React 18 + TypeScript with strict mode\n"
            "- Tailwind CSS for styling\n"
            "- Sample data and API mock layer\n"
            "- Hot module replacement enabled\n\n"
            "Open the sandbox below to edit and preview live. Changes sync in real time.",
            stackblitz_repo="@stackblitz/react-typescript",
            thinking_steps=_thinking([
                _tool_step("Analyzing requirements and selecting template", "sandbox_init", "react-typescript"),
                _tool_result("Project scaffolded — injecting generated code", "sandbox_init"),
            ]),
        )

    if "coder" in name and "claude" not in name and "codex" not in name:
        return _base(
            q,
            f"## Code Generated\n\n"
            f"**Task:** *{q_preview}*\n\n"
            "I've implemented the solution in a working sandbox. Here's the core logic:\n\n"
            "```typescript\n"
            "interface FetchResult<T> {\n"
            "  data: T | null;\n"
            "  loading: boolean;\n"
            "  error: string | null;\n"
            "}\n\n"
            "export function useFetch<T>(url: string): FetchResult<T> {\n"
            "  const [data, setData] = useState<T | null>(null);\n"
            "  const [loading, setLoading] = useState(true);\n"
            "  const [error, setError] = useState<string | null>(null);\n\n"
            "  useEffect(() => {\n"
            "    fetch(url)\n"
            "      .then(res => res.json())\n"
            "      .then(setData)\n"
            "      .catch(err => setError(err.message))\n"
            "      .finally(() => setLoading(false));\n"
            "  }, [url]);\n\n"
            "  return { data, loading, error };\n"
            "}\n"
            "```\n\n"
            "The full project is available in the interactive sandbox below with tests and sample data.",
            stackblitz_repo="@stackblitz/react-typescript",
            thinking_steps=_thinking([
                "Analyzing requirements and existing codebase patterns…",
                _tool_step("Generating implementation with LLM", "code_generator", q_preview),
                _tool_result("847 lines generated — deploying to StackBlitz", "code_generator"),
            ]),
        )

    if "claude code" in name:
        return _base(
            q,
            f"## Claude Code — Implementation Complete\n\n"
            f"**Task:** *{q_preview}*\n\n"
            "### Changes Made\n"
            "| File | Action | Lines |\n"
            "|------|--------|-------|\n"
            "| `src/services/auth.ts` | Modified | +42 / -8 |\n"
            "| `src/middleware/rateLimit.ts` | Created | +67 |\n"
            "| `tests/test_auth.ts` | Created | +89 |\n"
            "| `src/types/auth.d.ts` | Modified | +12 / -3 |\n\n"
            "### Summary\n"
            "Implemented OAuth 2.1 authentication with PKCE flow and added rate limiting middleware "
            "(1,000 req/min standard, configurable via env). All 89 new tests pass.\n\n"
            "```typescript\n"
            "// src/middleware/rateLimit.ts\n"
            "export const rateLimiter = rateLimit({\n"
            "  windowMs: 60 * 1000,\n"
            "  max: parseInt(process.env.RATE_LIMIT || '1000'),\n"
            "  standardHeaders: true,\n"
            "  legacyHeaders: false,\n"
            "});\n"
            "```\n\n"
            "Run `npm test` to verify. Ready for review.",
            thinking_steps=_thinking([
                _tool_step("Reading project structure and dependencies", "claude_code_read", q_preview),
                _tool_result("4 files identified for modification", "claude_code_read"),
                _tool_step("Writing implementation and tests", "claude_code_write"),
                _tool_result("210 lines added — 89 tests passing", "claude_code_write"),
            ]),
        )

    if "workspace" in name:
        return _base(
            q,
            f"## Workspace Analysis\n\n"
            f"**Query:** *{q_preview}*\n\n"
            "I've analyzed your workspace context across open files, recent edits, and project structure.\n\n"
            "### Relevant Files\n"
            "| File | Relevance | Last Modified |\n"
            "|------|-----------|---------------|\n"
            "| `server/api.py` | Primary — agent route registry | 2 hours ago |\n"
            "| `server/prototype/responses.py` | High — mock response definitions | 15 min ago |\n"
            "| `frontend/src/pages/AgentPage.tsx` | Medium — agent chat UI | 1 day ago |\n\n"
            "### Context Summary\n"
            "The prototype API serves hardcoded SSE responses from `responses.py`. Each agent endpoint maps to a display name "
            "in `AGENT_ROUTES`. The frontend streams chunks via `prototype_stream_response` and renders markdown, "
            "BPMN diagrams, StackBlitz embeds, and structured data (JIRA charts, test reports) based on response fields.\n\n"
            "### Suggested Next Steps\n"
            "1. Add agent-specific thinking steps with tool call types for richer UI\n"
            "2. Ensure match ordering in `build_agent_result` avoids false positives\n"
            "3. Test each agent endpoint individually to verify response shape",
            thinking_steps=_thinking([
                _tool_step("Scanning workspace files and git history", "workspace_scan"),
                _tool_result("847 files indexed — 3 highly relevant matches", "workspace_scan"),
                "Synthesizing context-aware response…",
            ]),
        )

    if "codex sdlc" in name:
        return _base(
            q,
            f"## Codex SDLC Pipeline Complete\n\n"
            f"**Feature request:** *{q_preview}*\n\n"
            "### Pipeline Stages\n"
            "| Stage | Status | Duration | Output |\n"
            "|-------|--------|----------|--------|\n"
            "| 1. Requirements analysis | ✅ Done | 12s | 8 user stories, 3 acceptance criteria each |\n"
            "| 2. Architecture design | ✅ Done | 18s | Component diagram, API spec (OpenAPI 3.1) |\n"
            "| 3. Implementation | ✅ Done | 45s | 4 files created, 2 modified (210 LOC) |\n"
            "| 4. Unit tests | ✅ Done | 22s | 24 tests, 100% pass, +4.2% coverage |\n"
            "| 5. Code review | ✅ Done | 8s | 0 blockers, 2 suggestions (addressed) |\n"
            "| 6. Documentation | ✅ Done | 6s | README updated, API docs generated |\n\n"
            "**Total pipeline time:** 111s · **Quality gate:** PASSED\n\n"
            "### Deliverables\n"
            "- Feature branch: `feat/rate-limiting-oauth`\n"
            "- PR draft ready with description, test plan, and rollback strategy\n"
            "- SonarQube pre-scan: 0 blockers",
            thinking_steps=_thinking([
                "Stage 1/6 — Analyzing requirements…",
                _tool_step("Generating user stories and acceptance criteria", "sdlc_requirements"),
                _tool_result("8 stories created — proceeding to architecture", "sdlc_requirements"),
                "Stage 3/6 — Implementing code changes…",
                _tool_step("Running unit tests and code review", "sdlc_validate"),
                _tool_result("Pipeline complete — all 6 stages passed", "sdlc_validate"),
            ]),
        )

    if "document" in name or "brd" in name or "formatter" in name:
        return _base(
            q,
            f"# Business Requirements Document\n\n"
            f"**Project:** *{q_preview}*\n"
            f"**Version:** 1.0 · **Date:** {datetime.now().strftime('%B %d, %Y')} · **Author:** AI Agent Platform\n\n"
            "---\n\n"
            "## 1. Executive Summary\n\n"
            "This document defines the business and functional requirements for the proposed platform enhancement. "
            "The initiative aims to modernize user authentication, improve dashboard performance, and enable "
            "seamless API integration with third-party services.\n\n"
            "## 2. Business Objectives\n\n"
            "- Reduce authentication-related support tickets by 40%\n"
            "- Achieve sub-2-second dashboard load times for 95th percentile users\n"
            "- Enable self-service API integration for partner onboarding\n\n"
            "## 3. Scope\n\n"
            "**In scope:** SSO authentication (SAML + OAuth 2.1), dashboard redesign, REST API v3, admin audit logging\n\n"
            "**Out of scope:** Mobile app redesign, legacy API v1 deprecation, third-party billing integration\n\n"
            "## 4. Functional Requirements\n\n"
            "| ID | Requirement | Priority |\n"
            "|----|-------------|----------|\n"
            "| FR-001 | Users shall authenticate via corporate SSO (SAML 2.0 or OAuth 2.1) | Must Have |\n"
            "| FR-002 | Dashboard shall load within 2 seconds for 95th percentile | Must Have |\n"
            "| FR-003 | System shall expose REST API v3 with OpenAPI 3.1 documentation | Must Have |\n"
            "| FR-004 | Admin actions shall be logged with user, timestamp, and IP | Must Have |\n"
            "| FR-005 | Users shall manage API keys via self-service portal | Should Have |\n\n"
            "## 5. Non-Functional Requirements\n\n"
            "- **Availability:** 99.9% uptime SLA\n"
            "- **Security:** SOC 2 Type II compliance, encryption at rest and in transit\n"
            "- **Scalability:** Support 10,000 concurrent users\n\n"
            "## 6. Assumptions & Dependencies\n\n"
            "- Identity provider (Okta) is configured and available\n"
            "- Database migration window approved for maintenance slot\n"
            "- QA environment available 4 weeks before go-live",
            thinking_steps=_thinking([
                _tool_step("Analyzing input and extracting requirements", "brd_analyzer", q_preview),
                _tool_result("12 requirements identified — structuring document", "brd_analyzer"),
                "Formatting document with standard BRD template…",
            ]),
        )

    if "trace" in name or "debug" in name or "langfuse" in name:
        return _base(
            q,
            f"## Langfuse Trace Analysis\n\n"
            f"**Query:** *{q_preview}*\n\n"
            "### Trace Overview\n"
            "| Field | Value |\n"
            "|-------|-------|\n"
            "| Trace ID | `tr_7f3a9b2c-4e1d-8a6f-b0c3-d5e912345678` |\n"
            "| Session | `sess_a1b2c3d4` |\n"
            "| Agent | JIRA Agent |\n"
            "| Status | ✅ OK |\n"
            "| Total latency | 2,412ms |\n"
            "| Total tokens | 1,842 (prompt: 1,204 · completion: 638) |\n"
            "| Cost | $0.028 |\n\n"
            "### Span Breakdown\n"
            "| Span | Type | Duration | Tokens | Status |\n"
            "|------|------|----------|--------|--------|\n"
            "| `agent.process_query` | chain | 2,412ms | 1,842 | OK |\n"
            "| ↳ `router.classify` | generation | 342ms | 412 | OK |\n"
            "| ↳ `jira.fetch_sprint` | tool | 890ms | — | OK |\n"
            "| ↳ `llm.synthesize` | generation | 1,180ms | 1,430 | OK |\n\n"
            "### Observations\n"
            "- JIRA API call (`jira.fetch_sprint`) accounts for 37% of total latency — consider caching sprint data\n"
            "- Token usage is within budget (daily limit: 50,000 · used: 12,400)\n"
            "- No errors or retries detected in this trace",
            thinking_steps=_thinking([
                _tool_step("Fetching trace from Langfuse", "langfuse_fetch", "trace_id=tr_7f3a9b2c"),
                _tool_result("Trace retrieved — 4 spans, 2,412ms total", "langfuse_fetch"),
                "Analyzing latency bottlenecks and token usage…",
            ]),
        )

    if "basic" in name:
        return _base(
            q,
            f"## Response\n\n"
            f"Regarding *{q_preview}*:\n\n"
            "Here's a structured summary based on my analysis:\n\n"
            "### Key Points\n"
            "1. **Context** — I've interpreted your request and identified the core question\n"
            "2. **Analysis** — Cross-referenced available information and applied logical reasoning\n"
            "3. **Recommendation** — Based on the above, here are the suggested next steps\n\n"
            "### Detailed Answer\n"
            "Enterprise AI platforms typically follow a phased adoption approach: start with high-ROI, low-risk use cases "
            "(document processing, internal support), establish governance and observability early, then scale to "
            "more complex agentic workflows. The most successful deployments invest 15–20% of budget in evaluation "
            "and monitoring infrastructure from day one.\n\n"
            "### Suggested Actions\n"
            "- Define 2–3 pilot use cases with measurable success criteria\n"
            "- Set up tracing and cost monitoring before scaling\n"
            "- Establish a human-in-the-loop review process for high-stakes outputs\n\n"
            "Let me know if you'd like me to dive deeper into any of these areas.",
            thinking_steps=_thinking([
                "Understanding query intent and context…",
                _tool_step("Searching knowledge base for relevant information", "web_search", q_preview),
                _tool_result("Multiple relevant sources found — synthesizing answer", "web_search"),
            ]),
        )

    # Fallback for any unregistered agent names
    return _base(
        q,
        f"## {agent_name} — Response\n\n"
        f"**Query:** *{q_preview}*\n\n"
        f"I've processed your request using the **{agent_name}** pipeline. "
        "Here's a summary of the analysis and recommended output:\n\n"
        "### Results\n"
        "The agent completed its workflow successfully. All validation checks passed, "
        "and the output has been formatted for your review.\n\n"
        "### Details\n"
        "- Input validated and parsed\n"
        "- Relevant data sources queried\n"
        "- Response synthesized and formatted\n\n"
        "Let me know if you need any adjustments or want to explore specific aspects in more detail.",
        thinking_steps=_thinking([
            f"Initializing {agent_name} pipeline…",
            "Processing input and generating response…",
        ]),
    )
