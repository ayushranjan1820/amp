# PPT Generator Agent — System Prompt

**Source:** `server/agents/PPT_generator_agent/agent.py`
**Agent:** PPT Generator Agent
**Purpose:** Generate professional, consulting-grade PowerPoint presentations with logical business narrative

---

## Overview

The PPT Generator Agent uses two prompt variants:
- **Full prompt** (`_build_outline_prompt`) — for PwC GenAI / Gemini. McKinsey/BCG-caliber with comprehensive content standards.
- **Compact prompt** (`_build_outline_prompt_compact`) — for Ollama Cloud / local LLMs. Same content rules, shorter format.

Both prompts enforce:

### Content Standards
- **Assertion Headlines** — slide titles must state conclusions, not topics (e.g. "Market Growing at 23% CAGR" not "Market Overview")
- **Numeric Density** — >=90% of bullets, stat labels, and descriptions must contain hard numbers
- **SII Framework** — Situation, Insight, Implication in every bullet
- **Critical Information Checklist** — TAM, CAGR, named competitors, quotes, financial impact, timeline, risks, regulatory, benchmarks

### Narrative Arc (Slide-Position-to-Purpose Mapping)
- Slide 1 (title): Frame the central business question
- Slides 2-3 CONTEXT: Establish problem/opportunity with hard evidence
- Slides 4-6 EVIDENCE: Market sizing, competitive landscape, trends, quotes
- Slides 7-9 STRATEGIC RESPONSE: Recommended solution with actions, process flows, comparisons
- Slides 10-12 BUSINESS CASE & EXECUTION: Financial impact, timeline, risks
- Final slide (closing): Call-to-action with expected outcome

### Coherence Rules
- Title sequence must form a readable connected argument
- Every slide must be directly relevant to the user's specific query
- Adjacent slides must share at least one connecting thread
- Logical order: Opening -> Problem/Context -> Evidence -> Solution -> Execution -> Risks -> CTA

### Post-Generation Validation
After LLM generation, `_validate_slide_flow` checks:
1. First slide is title, last is closing
2. No empty titles
3. No duplicate consecutive titles (LLM loop detection)
4. No 3+ consecutive same-type slides
5. Topic keyword presence across slide titles
6. Content/stats/list/flow slides have required data fields

If issues are found, a corrective re-prompt is sent to the LLM with explicit fix instructions.

## Supported Slide Types (11)

| Type | Key Fields |
|------|-----------|
| `title` | title, subtitle, image_query |
| `section` | title, subtitle, image_query |
| `closing` | title, subtitle, image_query |
| `content` | title, bullets (4-5), image_query |
| `stats` | title, stats [{value, label}] (2-4), image_query |
| `quote` | title, quote, attribution, image_query |
| `comparison` | title, left {title, bullets}, right {title, bullets}, image_query |
| `two_column` | title, left {title, bullets}, right {title, bullets}, image_query |
| `timeline` | title, steps [{title, description}] (3-5), image_query |
| `numbered_list` | title, items [{title, description}] (3-6), image_query |
| `process_flow` | title, steps [{title, description, icon}] (3-5), image_query |
| `icon_grid` | title, items [{title, description, icon}] (3-4), image_query |

## Pipeline

1. **Input** — User provides topic, optional slide count (2-30), theme, web search toggle
2. **Web Research** (optional) — provider from config:
	- `perplexity`: tiered Perplexity search
	- `free_ollama`: Ollama free web search (`OLLAMA_API_KEY`)
	- `free_duckduckgo`: DuckDuckGo free web search (`ddgs` backend, no API key)
	Both paths feed the same freshness-tiered research block into LLM distillation.
3. **Outline Generation** — LLM produces JSON slide array
4. **Flow Validation** — Programmatic coherence check; corrective re-prompt if needed
5. **Image Resolution** — AI generation or stock fallback per slide
6. **PPTX Build** — python-pptx assembles themed 16:9 widescreen deck
7. **Delivery** — SSE stream with download URL
