import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.local_llm import describe_missing_llm_credentials, get_llm_provider
from agents.Document_formatter_agent.tools.file_extractor import extract_file_content

from .ai_service import coder_ai_service
from .models import CoderAgentResponse, ThinkingStep


class CoderAgent:
    def __init__(self):
        self.ai = coder_ai_service
        self.sessions: Dict[str, Dict[str, Any]] = {}

        labels = {
            "pwc_genai": "PwC GenAI",
            "local_llm": "Local LLM",
            "ollama_cloud": "Ollama Cloud",
        }
        if self.ai.llm_configured:
            provider = get_llm_provider()
            print(f"Coder Agent initialized - LLM: {labels.get(provider, provider)}")
        else:
            print(f"Coder Agent initialized with missing config: {describe_missing_llm_credentials()}")

    def _get_session(self, session_id: Optional[str]) -> Dict[str, Any]:
        sid = session_id or str(uuid.uuid4())
        if sid not in self.sessions:
            self.sessions[sid] = {
                "id": sid,
                "source_text": "",
                "source_file": None,
                "last_html": "",
                "history": [],
                "created_at": datetime.now().isoformat(),
            }
        return self.sessions[sid]

    @staticmethod
    def _add_step(steps: List[Dict[str, Any]], step_type: str, content: str, tool_name: Optional[str] = None, tool_input: Optional[str] = None) -> None:
        step: Dict[str, Any] = {"type": step_type, "content": content}
        if tool_name:
            step["tool_name"] = tool_name
        if tool_input:
            step["tool_input"] = tool_input
        steps.append(step)

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n\n[...truncated for prompt safety...]"

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_\-]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    @staticmethod
    def _extract_html(text: str) -> str:
        if not text:
            return ""
        html_block = re.search(r"```html\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        if html_block:
            return html_block.group(1).strip()
        if "<!DOCTYPE html" in text or "<html" in text.lower():
            return text.strip()
        return ""

    @staticmethod
    def _default_rewrite(query: str) -> Dict[str, Any]:
        return {
            "expanded_problem_statement": query.strip(),
            "business_outcomes": [
                {"outcome": "Deliver a working user-facing solution", "metric": "Single HTML file runs without external dependencies"},
                {"outcome": "Improve business decision clarity", "metric": "Clear KPIs, insights, and action prompts in the UI"},
                {"outcome": "Reduce handoff friction", "metric": "Readable structure and maintainable sections"},
            ],
            "core_user_flows": [
                "Review uploaded business context",
                "Explore generated insights and recommended actions",
                "Interact with controls and visual summaries",
            ],
            "assumptions": [
                "The user needs a standalone HTML deliverable",
                "Uploaded file content should inform business-focused UI output",
            ],
        }

    @staticmethod
    def _detect_data_context(source_text: str, query_text: str) -> Dict[str, Any]:
        combined = (source_text or "").strip()
        if not combined:
            combined = (query_text or "").strip()

        numeric_tokens = re.findall(r"-?\d+(?:\.\d+)?", combined)
        numeric_values: List[float] = []
        for token in numeric_tokens[:80]:
            try:
                numeric_values.append(float(token))
            except Exception:
                continue

        lines = [ln.strip() for ln in combined.splitlines() if ln.strip()][:120]
        csv_like_lines = [ln for ln in lines if ln.count(",") >= 2]
        table_like_lines = [ln for ln in lines if "\t" in ln or "|" in ln]

        header_fields: List[str] = []
        if csv_like_lines:
            first_csv = csv_like_lines[0]
            first_parts = [p.strip() for p in first_csv.split(",") if p.strip()]
            alpha_count = sum(1 for p in first_parts if re.search(r"[A-Za-z]", p))
            if alpha_count >= max(1, len(first_parts) // 2):
                header_fields = first_parts[:8]

        has_data = (
            len(numeric_values) >= 8
            or len(csv_like_lines) >= 2
            or len(table_like_lines) >= 2
        )

        recommended_chart = "bar"
        if len(numeric_values) >= 24:
            recommended_chart = "line"
        elif 3 <= len(numeric_values) <= 8:
            recommended_chart = "pie"

        return {
            "has_data": has_data,
            "recommended_chart": recommended_chart,
            "numeric_sample": numeric_values[:24],
            "header_fields": header_fields,
            "data_line_sample": csv_like_lines[:5],
            "signals": {
                "csv_like_lines": len(csv_like_lines),
                "table_like_lines": len(table_like_lines),
                "numeric_count": len(numeric_values),
            },
        }

    @staticmethod
    def _pwc_brand_guidelines_text() -> str:
        return """Brand: PwC
Positioning: Build, sustain, accelerate momentum
Tone: bold, collaborative, optimistic
Style: clean, insight-driven, minimal
Logo rules: place top-left or bottom-right, no modification, maintain clear space, use on light background
Colors:
- Primary: orange #DC6900, dark_orange #EB8C00, red #E0301E, dark_red #A32020, black #000000
- Accent: yellow #F3BE26, pink #E669A2
- Usage: orange for highlights, black/white base, limit multi-color usage per slide
Typography: PwCNext with fallbacks Arial, Calibri, Helvetica; no mixed font families
Layout principle: one slide one message
Content structure: title, key_message, supporting_data, conclusion
Content style: MECE and pyramid principle; short bullets; data-backed insights; no long paragraphs or clutter
Data visualization: bar/line/pie only, minimal gridlines, highlight key data in orange
Imagery/icons: real, professional, inclusive; flat minimal consistent icons
Spacing: strong whitespace, strict alignment, avoid overcrowding
Voice: direct, business-focused, insightful"""

    @staticmethod
    def _default_architecture(rewrite_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "page_title": "PwC Executive Insight Brief",
            "visual_direction": "Modern PwC business brief on light background with strong whitespace and disciplined hierarchy",
            "sections": [
                {
                    "id": "title",
                    "name": "Title",
                    "purpose": "State one precise business message for the page.",
                    "key_elements": ["title", "subtitle", "date"],
                },
                {
                    "id": "executive-summary",
                    "name": "Executive Summary",
                    "purpose": "Present key message first using pyramid principle.",
                    "key_elements": ["key message", "3 concise bullets", "impact metric"],
                },
                {
                    "id": "analysis",
                    "name": "Analysis",
                    "purpose": "Provide MECE supporting data and drivers.",
                    "key_elements": ["supporting data", "bar or line chart", "insight callout"],
                },
                {
                    "id": "recommendation",
                    "name": "Recommendation",
                    "purpose": "Define direct business actions with ownership.",
                    "key_elements": ["prioritized actions", "owner", "timeline"],
                },
                {
                    "id": "roadmap",
                    "name": "Roadmap",
                    "purpose": "Sequence execution in clear phases.",
                    "key_elements": ["phase timeline", "milestones", "success KPI"],
                },
            ],
            "style_tokens": {
                "primary": "#DC6900",
                "primary_deep": "#EB8C00",
                "danger": "#E0301E",
                "danger_deep": "#A32020",
                "accent": "#F3BE26",
                "accent_secondary": "#E669A2",
                "surface": "#FFFFFF",
                "text": "#000000",
            },
            "problem_statement": rewrite_data.get("expanded_problem_statement", ""),
        }

    @staticmethod
    def _safe_section_list(architecture: Dict[str, Any]) -> List[Dict[str, Any]]:
        sections = architecture.get("sections", [])
        if not isinstance(sections, list):
            return []
        out: List[Dict[str, Any]] = []
        for idx, sec in enumerate(sections[:8], start=1):
            if not isinstance(sec, dict):
                continue
            sid = str(sec.get("id") or f"section-{idx}").strip().lower().replace(" ", "-")
            out.append({
                "id": sid or f"section-{idx}",
                "name": str(sec.get("name") or f"Section {idx}"),
                "purpose": str(sec.get("purpose") or ""),
                "key_elements": sec.get("key_elements") if isinstance(sec.get("key_elements"), list) else [],
            })
        return out

    @staticmethod
    def _build_base_html(title: str, body: str) -> str:
        safe_title = title.strip() or "Standalone Business App"
        return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>{safe_title}</title>
    <style>
        :root {{
            --pwc-orange: #DC6900;
            --pwc-dark-orange: #EB8C00;
            --pwc-red: #E0301E;
            --pwc-dark-red: #A32020;
            --pwc-yellow: #F3BE26;
            --pwc-pink: #E669A2;
            --pwc-black: #000000;
            --pwc-white: #FFFFFF;
            --surface: #F8F8F6;
            --border: #E7E4DF;
        }}

        * {{ box-sizing: border-box; }}

        body {{
            margin: 0;
            font-family: 'PwCNext', Arial, Calibri, Helvetica, sans-serif;
            background: linear-gradient(180deg, #FFFFFF 0%, var(--surface) 100%);
            color: var(--pwc-black);
            text-align: left;
            line-height: 1.45;
        }}

        .pwc-page {{
            width: min(1120px, 94vw);
            margin: 36px auto;
            padding: 28px;
            background: var(--pwc-white);
            border: 1px solid var(--border);
            border-radius: 18px;
            position: relative;
            box-shadow: 0 14px 28px rgba(0, 0, 0, 0.06);
            overflow: hidden;
        }}

        .pwc-page::before {{
            content: '';
            position: absolute;
            left: 0;
            top: 0;
            width: 100%;
            height: 6px;
            background: linear-gradient(90deg, var(--pwc-orange), var(--pwc-dark-orange));
        }}

        .logo-slot {{
            position: absolute;
            right: 24px;
            bottom: 16px;
            font-size: 12px;
            color: #666666;
            padding: 6px 8px;
            border: 1px dashed #C9C1B8;
            border-radius: 8px;
            background: #FFFFFF;
            letter-spacing: 0.01em;
        }}

        section {{
            margin: 22px 0;
            padding: 16px 0;
            border-bottom: 1px solid #EFECE7;
        }}

        section:last-child {{ border-bottom: 0; }}

        h1, h2, h3 {{
            margin: 0 0 10px;
            line-height: 1.2;
            color: var(--pwc-black);
            font-weight: 700;
        }}

        h1 {{ font-size: clamp(1.65rem, 2.8vw, 2.3rem); }}
        h2 {{ font-size: clamp(1.2rem, 2.1vw, 1.5rem); }}
        p, li {{ font-size: 0.98rem; }}

        .highlight {{ color: var(--pwc-orange); font-weight: 700; }}

        ul {{ margin: 8px 0 0 20px; padding: 0; }}

        @media (max-width: 760px) {{
            .pwc-page {{ margin: 14px auto; padding: 16px; border-radius: 12px; }}
            .logo-slot {{ position: static; margin-top: 14px; display: inline-block; }}
            section {{ margin: 16px 0; padding: 10px 0; }}
        }}
    </style>
</head>
<body>
    <main class=\"pwc-page\" aria-label=\"PwC business brief\">{body}
        <div class=\"logo-slot\" aria-label=\"PwC logo placement\">PwC logo placement area</div>
    </main>
</body>
</html>"""

    @staticmethod
    def _run_html_checks(html: str, require_chart: bool = False) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = []

        def add(name: str, ok: bool, detail: str) -> None:
            checks.append({"name": name, "pass": ok, "detail": detail})

        low = html.lower()
        add("doctype", "<!doctype html" in low, "Document should include <!DOCTYPE html>.")
        add("html-tag", "<html" in low and "</html>" in low, "Document should include <html> root tags.")
        add("head-body", "<head" in low and "<body" in low, "Document should include head and body tags.")
        add("inline-style", "<style" in low, "Document should include inline CSS.")
        add("self-sufficient", not bool(re.search(r"<script[^>]+src=|<link[^>]+href=", low)), "Avoid external JS/CSS references for standalone output.")
        add("placeholder-free", "todo" not in low and "lorem ipsum" not in low, "Output should not contain placeholder TODO/Lorem text.")
        add("pwc-brand-color", "#dc6900" in low or "--pwc-orange" in low, "Use PwC orange (#DC6900) as highlight color.")
        add("left-aligned", "text-align:left" in low or "text-align: left" in low, "Text should be left aligned.")
        add("pwc-font-stack", "pwcnext" in low and ("arial" in low or "calibri" in low or "helvetica" in low), "Use PwCNext with approved fallback fonts.")
        add("logo-slot", "logo" in low, "Include a logo area at top-left or bottom-right with clear space.")
        if require_chart:
            add(
                "data-chart-present",
                ("<svg" in low or "<canvas" in low) and ("chart" in low or "axis" in low or "bar" in low or "line" in low or "pie" in low),
                "When dataset context is provided, include at least one chart (bar/line/pie) using inline SVG or canvas.",
            )

        return checks

    async def _rewrite_query(self, query: str, source_excerpt: str, data_context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are a PwC strategy query rewriter.
    Expand the user's problem into concrete business outcomes using MECE and pyramid principle.
    Use a direct, business-focused tone with data-ready phrasing.
Return JSON only with this exact shape:
{{
  "expanded_problem_statement": "string",
  "business_outcomes": [{{"outcome": "string", "metric": "string"}}],
  "core_user_flows": ["string"],
  "assumptions": ["string"]
}}

    Brand and communication guardrails:
    {self._pwc_brand_guidelines_text()}

    Structured data context:
    {json.dumps(data_context, ensure_ascii=True)}

    If has_data=true, outcomes and metrics must explicitly leverage measurable values from the provided data context.

User problem:
{query}

Optional source context from uploaded file:
{source_excerpt if source_excerpt else "No uploaded file context."}
"""
        raw = await self.ai.call_genai(prompt, temperature=0.2, max_tokens=2200)
        parsed = self._extract_json(raw)
        return parsed if parsed else self._default_rewrite(query)

    async def _build_architecture(self, rewritten: Dict[str, Any], source_excerpt: str, data_context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are a senior PwC HTML page architect.
    Design a modern standalone page blueprint from the rewritten business requirement.
    Strictly follow the brand, typography, and layout system below.
Return JSON only with this exact shape:
{{
  "page_title": "string",
  "visual_direction": "string",
  "sections": [
    {{"id": "string", "name": "string", "purpose": "string", "key_elements": ["string"]}}
  ],
  "style_tokens": {{"primary": "#hex", "accent": "#hex", "surface": "#hex", "text": "#hex"}}
}}

Mandatory architecture rules:
- One section equals one message.
- Sections must align to: title, key_message, supporting_data, conclusion.
- Keep text left aligned and concise.
- Prioritize whitespace and clean alignment over decorative effects.
- Use PwC orange as the main highlight and black/white as base.
- Avoid color overload; only introduce accent colors sparingly.
- Prefer slide-ready section types: title, executive_summary, problem_statement, analysis, data, recommendation, roadmap, appendix.
- If has_data=true in data context, include a dedicated data section with a recommended bar/line/pie chart plan and storytelling insight.

Brand and content guardrails:
{self._pwc_brand_guidelines_text()}

Structured data context:
{json.dumps(data_context, ensure_ascii=True)}

Rewritten requirement JSON:
{json.dumps(rewritten, ensure_ascii=True)}

Optional source context:
{source_excerpt if source_excerpt else "No uploaded source context."}
"""
        raw = await self.ai.call_genai(prompt, temperature=0.2, max_tokens=2200)
        parsed = self._extract_json(raw)
        base = self._default_architecture(rewritten)
        if not parsed:
            return base
        for key in ("page_title", "visual_direction", "style_tokens"):
            if key in parsed:
                base[key] = parsed[key]
        if "sections" in parsed:
            base["sections"] = parsed["sections"]
        return base

    async def _generate_section_html(
        self,
        section: Dict[str, Any],
        rewritten: Dict[str, Any],
        architecture: Dict[str, Any],
        source_excerpt: str,
        data_context: Dict[str, Any],
    ) -> str:
        prompt = f"""You are a senior PwC frontend implementation specialist.
Generate HTML for one section only.
Rules:
- Return ONLY valid HTML markup for this section (no markdown fences).
- Use semantic tags and include useful class names.
- Include realistic content tied to business outcomes.
    - Keep content MECE and pyramid-driven.
    - Keep one dominant message per section.
    - Use short bullets and data-backed statements.
    - Keep text left aligned; avoid long paragraphs.
    - Avoid decorative noise and visual clutter.
    - Use the PwC palette with orange highlight and black/white base.
    - Ensure markup can be styled with PwCNext fallback stack.
    - If has_data=true and the section is analysis/data/executive-summary, include modern chart markup (inline SVG preferred) with clear labels, minimal gridlines, and highlighted key value in PwC orange.

    Brand guardrails:
    {self._pwc_brand_guidelines_text()}

Structured data context:
{json.dumps(data_context, ensure_ascii=True)}

Section spec:
{json.dumps(section, ensure_ascii=True)}

Rewritten requirement:
{json.dumps(rewritten, ensure_ascii=True)}

Architecture:
{json.dumps(architecture, ensure_ascii=True)}

Source excerpt:
{source_excerpt if source_excerpt else "No source excerpt."}
"""
        raw = await self.ai.call_genai(prompt, temperature=0.25, max_tokens=2600)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z0-9_\-]*\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        if "<" not in cleaned or ">" not in cleaned:
            name = section.get("name", "Section")
            sid = section.get("id", "section")
            return f"<section id=\"{sid}\"><h2>{name}</h2><p>{cleaned}</p></section>"
        return cleaned

    async def _review_and_fix(self, html_draft: str, checks: List[Dict[str, Any]], query: str, data_context: Dict[str, Any]) -> str:
        failed = [c for c in checks if not c.get("pass")]
        failed_text = "\n".join(f"- {c['name']}: {c['detail']}" for c in failed) if failed else "No failed checks. Improve polish and robustness."
        prompt = f"""You are a senior PwC frontend reviewer, designer, and QA fixer.
Improve, fix, and test the HTML draft.
Requirements:
- Keep it a single standalone self-sufficient HTML file.
- Include inline CSS and inline JS only if needed.
- Ensure responsive layout on mobile and desktop.
- Ensure valid basic structure with doctype/html/head/body.
    - Keep business-focused UX and clear sections.
    - Build a modern, intentional visual system (not generic template styling).
    - Keep a light background and strong whitespace discipline.
    - Enforce typography stack: 'PwCNext', Arial, Calibri, Helvetica, sans-serif.
    - Keep all body text left aligned with consistent sizing.
    - Use CSS variables for PwC colors and apply orange as primary highlight.
    - Limit color usage and avoid visual clutter.
    - Keep one-message-per-section and concise, data-driven wording.
    - Include a dedicated logo slot at top-left or bottom-right with clear spacing on light background.
    - If charts are used, keep gridlines minimal and highlight key data in orange.
    - If has_data=true in structured data context, chart is mandatory: include at least one relevant bar/line/pie chart with clear axis/labels and storytelling annotation.

    Brand and messaging guardrails:
    {self._pwc_brand_guidelines_text()}

    Structured data context:
    {json.dumps(data_context, ensure_ascii=True)}

Failed checks to address:
{failed_text}

Original user problem:
{query}

Current HTML draft:
{html_draft}

Return ONLY the full final HTML document.
"""
        raw = await self.ai.call_genai(prompt, temperature=0.15, max_tokens=7000)
        final_html = self._extract_html(raw)
        return final_html or html_draft

    async def process_query(
        self,
        query: str,
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> CoderAgentResponse:
        thinking_steps: List[Dict[str, Any]] = []
        session = self._get_session(session_id)
        sid = session["id"]

        self._add_step(thinking_steps, "thinking", "Starting Coder Agent pipeline: rewrite -> architecture -> section coding -> review/test.")

        source_text = ""
        if file_content and (file_type or file_name):
            inferred_type = (file_type or "").strip().lower().strip(".")
            if not inferred_type and file_name and "." in file_name:
                inferred_type = file_name.rsplit(".", 1)[-1].lower()

            self._add_step(
                thinking_steps,
                "tool_call",
                "Extracting uploaded file content for business-context grounding.",
                "file_extractor",
                file_name or inferred_type,
            )
            extracted_text, success, _images = extract_file_content(file_content, inferred_type, file_name or "")
            if not success:
                self._add_step(thinking_steps, "tool_result", f"File extraction failed: {extracted_text}")
                return CoderAgentResponse(
                    success=False,
                    query=query,
                    response=f"I could not extract the uploaded file: {extracted_text}",
                    session_id=sid,
                    thinking_steps=[ThinkingStep(**s) for s in thinking_steps],
                )
            source_text = extracted_text
            session["source_text"] = extracted_text
            session["source_file"] = file_name
            self._add_step(
                thinking_steps,
                "tool_result",
                f"Extracted {len(extracted_text)} characters from uploaded data ({file_name or inferred_type}).",
                "file_extractor",
                file_name or inferred_type,
            )
        else:
            source_text = session.get("source_text", "")
            if source_text:
                self._add_step(thinking_steps, "thinking", "Using previously uploaded file context from this session.")

        source_excerpt = self._clip(source_text, 12000) if source_text else ""
        data_context = self._detect_data_context(source_excerpt, query)
        has_data_context = bool(data_context.get("has_data"))
        if has_data_context:
            self._add_step(
                thinking_steps,
                "thinking",
                "Detected structured data context; chart generation will be enforced in architecture, sections, and final QA.",
            )

        self._add_step(thinking_steps, "tool_call", "Running Query Rewriter agent.", "query_rewriter", query[:180])
        rewritten = await self._rewrite_query(query, source_excerpt, data_context)
        self._add_step(thinking_steps, "tool_result", "Query rewrite complete with business outcomes.", "query_rewriter")

        self._add_step(thinking_steps, "tool_call", "Running HTML Architecture agent.", "html_architect")
        architecture = await self._build_architecture(rewritten, source_excerpt, data_context)
        sections = self._safe_section_list(architecture)
        if not sections:
            architecture = self._default_architecture(rewritten)
            sections = self._safe_section_list(architecture)
        self._add_step(thinking_steps, "tool_result", f"Architecture complete with {len(sections)} sections.", "html_architect")

        self._add_step(thinking_steps, "tool_call", "Running Section Code Generator agent.", "section_codegen")
        section_blocks: List[str] = []
        for section in sections:
            block = await self._generate_section_html(section, rewritten, architecture, source_excerpt, data_context)
            section_blocks.append(block)
        self._add_step(thinking_steps, "tool_result", f"Generated code for {len(section_blocks)} sections.", "section_codegen")

        page_title = str(architecture.get("page_title") or "Standalone Business App")
        html_draft = self._build_base_html(page_title, "\n\n".join(section_blocks))

        self._add_step(thinking_steps, "tool_call", "Running Reviewer/Fixer/Tester agent.", "review_fix_test")
        checks = self._run_html_checks(html_draft, require_chart=has_data_context)
        reviewed_html = await self._review_and_fix(html_draft, checks, query, data_context)
        final_checks = self._run_html_checks(reviewed_html, require_chart=has_data_context)
        if any(not c["pass"] for c in final_checks):
            reviewed_html = await self._review_and_fix(reviewed_html, final_checks, query, data_context)
            final_checks = self._run_html_checks(reviewed_html, require_chart=has_data_context)
        self._add_step(thinking_steps, "tool_result", "Review, fix, and static test pass complete.", "review_fix_test")

        final_html = reviewed_html.strip()
        if "<!DOCTYPE html" not in final_html:
            final_html = self._build_base_html(page_title, final_html)

        session["last_html"] = final_html
        session["history"].append({
            "query": query,
            "timestamp": datetime.now().isoformat(),
            "sections": len(section_blocks),
            "source_file": session.get("source_file"),
        })

        outcomes = rewritten.get("business_outcomes", [])
        if not isinstance(outcomes, list):
            outcomes = []

        failed_checks = [c for c in final_checks if not c.get("pass")]
        check_summary = "All structural checks passed." if not failed_checks else (
            "Remaining check warnings:\n" + "\n".join(f"- {c['name']}: {c['detail']}" for c in failed_checks)
        )

        safe_html = final_html.replace("```", "``\\`")
        response = (
            "## Coder Agent Completed\n\n"
            "Built the multi-agent pipeline you asked for:\n"
            "1. Query Rewriter expanded your problem into business outcomes\n"
            "2. HTML Architect designed the page blueprint\n"
            "3. Section Code Generator created section-wise code\n"
            "4. Reviewer/Fixer/Tester validated and improved the final output\n\n"
            f"{check_summary}\n\n"
            "### Final Standalone HTML\n"
            f"```html\n{safe_html}\n```"
        )

        return CoderAgentResponse(
            success=True,
            query=query,
            response=response,
            standalone_html=final_html,
            architecture=architecture,
            business_outcomes=[o for o in outcomes if isinstance(o, dict)],
            session_id=sid,
            thinking_steps=[ThinkingStep(**s) for s in thinking_steps],
        )


coder_agent = CoderAgent()
