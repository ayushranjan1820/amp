import json
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.local_llm import describe_missing_llm_credentials, get_llm_provider

from .ai_service import company_solution_ai_service
from .models import CompanySolutionResponse, ThinkingStep, UploadedSolutionFile


class CompanySolutionAgent:
    def __init__(self):
        self.ai = company_solution_ai_service
        self.sessions: Dict[str, Dict[str, Any]] = {}

        llm_labels = {
            "pwc_genai": "PwC GenAI",
            "local_llm": "local LLM",
            "ollama_cloud": "Ollama Cloud",
        }
        if self.ai.llm_configured:
            provider = get_llm_provider()
            print(f"🏭 Company Solution Agent - LLM: {llm_labels.get(provider, provider)}")
        else:
            print(f"⚠️ Company Solution Agent - {describe_missing_llm_credentials()}")

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        return re.sub(r"\n{3,}", "\n\n", (text or "").strip())

    @staticmethod
    def _extract_company_name(details_text: str, fallback_name: Optional[str]) -> Optional[str]:
        if fallback_name and fallback_name.strip():
            return fallback_name.strip()

        patterns = [
            r"(?im)^\s*company\s*[:\-]\s*([^\n]{2,120})$",
            r"(?im)^\s*organization\s*[:\-]\s*([^\n]{2,120})$",
            r"(?im)^\s*client\s*[:\-]\s*([^\n]{2,120})$",
        ]
        for pattern in patterns:
            m = re.search(pattern, details_text)
            if m:
                return m.group(1).strip(" .:-")

        first_line = (details_text.splitlines() or [""])[0].strip()
        if 2 <= len(first_line) <= 80 and len(first_line.split()) <= 8:
            return first_line.strip(" .:-")
        return None

    @staticmethod
    def _split_into_chunks(text: str, max_chars: int = 4200, overlap_chars: int = 260) -> List[str]:
        if len(text) <= max_chars:
            return [text]

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

        chunks: List[str] = []
        current = ""

        for para in paragraphs:
            candidate = para if not current else f"{current}\n\n{para}"
            if len(candidate) <= max_chars:
                current = candidate
                continue

            if current:
                chunks.append(current)
            if len(para) <= max_chars:
                current = para
                continue

            start = 0
            while start < len(para):
                end = min(start + max_chars, len(para))
                part = para[start:end].strip()
                if part:
                    chunks.append(part)
                if end >= len(para):
                    break
                start = max(end - overlap_chars, start + 1)
            current = ""

        if current:
            chunks.append(current)

        cleaned = [c.strip() for c in chunks if c and c.strip()]
        return cleaned or [text]

    @staticmethod
    def _extract_uploaded_catalog(
        uploaded_files: Optional[List[UploadedSolutionFile]],
    ) -> tuple[str, List[str], List[str]]:
        """Return (combined_text, file_names, extraction_errors)."""
        if not uploaded_files:
            return "", [], []

        try:
            from agents.Document_formatter_agent.tools.file_extractor import extract_file_content
        except Exception as e:
            return "", [], [f"File extractor unavailable: {e}"]

        parts: List[str] = []
        names: List[str] = []
        errors: List[str] = []
        for f in uploaded_files:
            name = f.file_name or f"solution_catalog.{f.file_type}"
            names.append(name)
            text, ok, _images = extract_file_content(f.file_content, f.file_type, name)
            if ok and text and text.strip():
                parts.append(f"--- File: {name} ---\n{text.strip()}")
            else:
                errors.append(f"{name}: {text[:180] if text else 'no text extracted'}")
        return "\n\n".join(parts), names, errors

    @staticmethod
    def _parse_json_block(raw: str) -> Any:
        txt = (raw or "").strip()
        if txt.startswith("```"):
            lines = txt.split("\n")
            txt = "\n".join(lines[1:])
            if txt.rstrip().endswith("```"):
                txt = txt.rstrip()[:-3]
            txt = txt.strip()
        start = txt.find("{")
        if start < 0:
            start = txt.find("[")
        end = max(txt.rfind("}"), txt.rfind("]"))
        if start >= 0 and end > start:
            txt = txt[start : end + 1]
        try:
            return json.loads(txt)
        except Exception:
            try:
                fixed = re.sub(r",\s*([}\]])", r"\1", txt)
                return json.loads(fixed)
            except Exception:
                return None

    async def _extract_solutions_from_catalog(self, catalog_text: str) -> List[Dict[str, Any]]:
        if not catalog_text.strip():
            return []

        prompt = f"""You are an information extraction specialist. Parse the document(s) below, which describe AI solutions that an organization already offers or has built.

Extract each distinct AI solution as a JSON array. For each solution capture:
- name: concise solution name
- description: 1-3 sentence description of what it does
- capabilities: list of short capability tags (e.g. "document OCR", "fraud detection", "forecasting")
- industries: list of applicable industries if stated, else []
- tech_stack: list of technologies/platforms mentioned, else []
- source_file: the file name the solution came from (look for "--- File: <name> ---" markers)

DOCUMENT CONTENT:
---
{catalog_text[:45000]}
---

Return ONLY a valid JSON array (no prose, no markdown fences). If no solutions can be identified, return [].
"""
        raw = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=3500)
        parsed = self._parse_json_block(raw)
        if isinstance(parsed, list):
            cleaned: List[Dict[str, Any]] = []
            for item in parsed:
                if isinstance(item, dict) and item.get("name"):
                    cleaned.append(
                        {
                            "name": str(item.get("name", "")).strip(),
                            "description": str(item.get("description", "")).strip(),
                            "capabilities": item.get("capabilities") or [],
                            "industries": item.get("industries") or [],
                            "tech_stack": item.get("tech_stack") or [],
                            "source_file": item.get("source_file") or "",
                        }
                    )
            return cleaned
        return []

    @staticmethod
    def _format_catalog_for_prompt(solutions: List[Dict[str, Any]]) -> str:
        if not solutions:
            return "(no existing-solution catalog provided)"
        lines: List[str] = []
        for i, s in enumerate(solutions, 1):
            caps = ", ".join(s.get("capabilities") or []) or "—"
            inds = ", ".join(s.get("industries") or []) or "—"
            tech = ", ".join(s.get("tech_stack") or []) or "—"
            lines.append(
                f"[C{i}] {s.get('name')}\n"
                f"    Description: {s.get('description') or '—'}\n"
                f"    Capabilities: {caps}\n"
                f"    Industries: {inds}\n"
                f"    Tech: {tech}"
            )
        return "\n".join(lines)

    @staticmethod
    def _fit_for_synthesis(chunk_summaries: List[str], max_chars: int = 26000) -> str:
        if not chunk_summaries:
            return ""
        joined = "\n\n".join(chunk_summaries)
        if len(joined) <= max_chars:
            return joined

        kept: List[str] = []
        total = 0
        for idx, summary in enumerate(chunk_summaries, 1):
            item = f"### Chunk {idx} Summary\n{summary}"
            if total + len(item) > max_chars:
                break
            kept.append(item)
            total += len(item)

        return "\n\n".join(kept)

    @staticmethod
    def _chunk_prompt(chunk_text: str, company_name: Optional[str], idx: int, total: int) -> str:
        company_label = company_name or "the company"
        return f"""You are an expert enterprise transformation analyst.

Analyze this chunk ({idx}/{total}) from a detailed company context document for {company_label}.

CHUNK CONTENT:
---
{chunk_text}
---

Return concise markdown only with these sections:
## Problems Observed
- bullet points (specific pain points, bottlenecks, risks)

## Current Process Improvement Opportunities
- bullet points (current process gaps and practical improvements)

## Potential AI / Agentic Opportunities
- bullet points (where AI or agentic AI can improve the process)

## Evidence Signals
- bullet points with direct facts, metrics, or process clues from this chunk

Rules:
- Focus only on what is supported by this chunk.
- Keep it concise and factual.
- No intro and no conclusion outside the sections above.
"""

    @staticmethod
    def _final_prompt(
        company_name: Optional[str],
        full_details: str,
        chunk_summaries: str,
        chunk_count: int,
        chunk_limit_hit: bool,
        catalog_text: str,
        has_catalog: bool,
    ) -> str:
        company_label = company_name or "this company"
        trunc_note = (
            "Note: The source was very large; only the first set of chunks was analyzed. "
            "Call out assumptions and suggest what additional documents are needed to improve precision."
            if chunk_limit_hit
            else ""
        )
        details_preview = full_details[:4500]

        catalog_block = (
            f"""EXISTING AI SOLUTION CATALOG (provided by the user — PREFER these when relevant):
---
{catalog_text}
---

SMART-MATCH RULES (MANDATORY when a catalog is provided):
1. For each problem identified, FIRST check the catalog for a relevant existing solution.
2. If a catalog solution genuinely fits (capability or industry match), recommend THAT solution by its exact name and cite the catalog entry as `[C#]`. Mark Source: "From Your Catalog".
3. Only propose a NEW solution when the catalog has no reasonable match. Mark Source: "Newly Suggested".
4. Do not force-fit catalog solutions to unrelated problems — be honest about gaps.
5. Every recommended solution MUST declare its Source line explicitly.
"""
            if has_catalog
            else "EXISTING AI SOLUTION CATALOG: (none provided — all solutions will be Newly Suggested based on industry best practice)\n"
        )

        source_line_rule = (
            '- Source: "From Your Catalog [C#]" OR "Newly Suggested"'
            if has_catalog
            else '- Source: "Newly Suggested"'
        )

        return f"""You are a principal AI transformation consultant.

You have chunk-wise analysis for {company_label}. Produce an executive-ready recommendation report.

COMPANY DETAILS (preview):
---
{details_preview}
---

CHUNK ANALYSIS INPUT ({chunk_count} chunks):
---
{chunk_summaries}
---

{catalog_block}

{trunc_note}

Output markdown with the following sections and exact headings:

# Executive Summary
- 5-8 bullets summarizing the business situation and key challenges.
- If a catalog was provided, include one bullet stating how many catalog solutions were matched vs. newly suggested.

# Key Problems The Company Is Facing
- Ranked list with severity labels: High / Medium / Low.

# Current Process Improvement Areas
- Concrete process improvements independent of AI (quick operational wins).

# Recommended AI and Agentic AI Solutions
For each solution, include (in this order):
- Solution Name
{source_line_rule}
- Type: AI or Agentic AI
- Why This Is Relevant For This Company
- High-Level Implementation Plan
- Data / System Dependencies
- Expected Business Impact (with measurable KPIs)
- Delivery Horizon (30/60/90 days or quarter-based)

Provide 6-10 solutions, prioritized most relevant first. Catalog-matched solutions should generally appear before newly suggested ones when relevance is comparable.

# Implementation Roadmap
- Phase 1 (0-30 days)
- Phase 2 (31-90 days)
- Phase 3 (90+ days)

# Risks and Mitigations
- Key execution risks and how to reduce each risk.

# Assumptions and Missing Inputs
- Clearly list assumptions made.

# Structured JSON
- After all markdown sections, include a fenced ```json block containing ONE valid JSON object with this exact top-level shape:
    - executive_summary: string[]
    - key_problems: string[]
    - process_improvement_areas: string[]
    - recommended_solutions: object[]
    - implementation_roadmap: object[]
    - risks_and_mitigations: object[]
    - assumptions_and_missing_inputs: string[]
- For each item in recommended_solutions use keys:
    - solution_name, source, type, why_relevant, implementation_plan, dependencies, expected_business_impact, delivery_horizon
- For each item in implementation_roadmap use keys:
    - phase, actions (string[])
- For each item in risks_and_mitigations use keys:
    - risk, mitigation
- JSON must be valid and parseable by standard parsers.
- Do not wrap the full response in JSON; keep the leadership markdown first, then the fenced JSON block.

Rules:
- Keep recommendations realistic and specific to the provided context.
- Avoid generic statements.
- Prefer business language suitable for leadership and delivery teams.
- NEVER invent catalog entries. Only cite [C#] values that appear in the catalog above.
- Keep markdown and JSON semantically aligned (same recommendations, order, and priorities).
"""

    @staticmethod
    def _parse_solutions_from_report(report: str) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Best-effort split of recommended solutions into matched-from-catalog vs newly-suggested
        by scanning the 'Recommended AI and Agentic AI Solutions' section."""
        matched: List[Dict[str, Any]] = []
        suggested: List[Dict[str, Any]] = []

        section_match = re.search(
            r"#\s*Recommended AI and Agentic AI Solutions\s*\n(.*?)(?=\n#\s|\Z)",
            report,
            flags=re.DOTALL | re.IGNORECASE,
        )
        if not section_match:
            return matched, suggested

        body = section_match.group(1)
        blocks = re.split(r"\n(?=(?:\s*[-*]\s*)?Solution Name\s*[:\-])", body, flags=re.IGNORECASE)
        for block in blocks:
            if not block.strip() or "Solution Name" not in block:
                continue
            name_m = re.search(r"Solution Name\s*[:\-]\s*(.+)", block, flags=re.IGNORECASE)
            source_m = re.search(r"Source\s*[:\-]\s*(.+)", block, flags=re.IGNORECASE)
            if not name_m:
                continue
            name = name_m.group(1).strip().rstrip("*_ ").strip()
            source = (source_m.group(1).strip() if source_m else "").lower()
            entry = {"name": name, "source_line": source_m.group(1).strip() if source_m else ""}
            if "from your catalog" in source or re.search(r"\[C\d+\]", source):
                catalog_ref_m = re.search(r"\[C(\d+)\]", source)
                if catalog_ref_m:
                    entry["catalog_index"] = int(catalog_ref_m.group(1))
                matched.append(entry)
            else:
                suggested.append(entry)
        return matched, suggested

    async def analyze(
        self,
        query: str,
        company_name: Optional[str] = None,
        company_details: Optional[str] = None,
        uploaded_files: Optional[List[UploadedSolutionFile]] = None,
        session_id: Optional[str] = None,
    ) -> CompanySolutionResponse:
        current_session_id = session_id or str(uuid.uuid4())
        thinking_steps: List[ThinkingStep] = []

        input_text = self._collapse_whitespace(
            "\n\n".join(
                [
                    x
                    for x in [query, company_details]
                    if x and isinstance(x, str) and x.strip()
                ]
            )
        )

        if len(input_text) < 180:
            return CompanySolutionResponse(
                success=False,
                query=query,
                response=(
                    "Please share more detailed company information so I can analyze it in chunks and propose "
                    "relevant AI/agentic solutions. Include business context, current process details, pain points, "
                    "and existing systems if possible."
                ),
                company_name=company_name,
                session_id=current_session_id,
                thinking_steps=[
                    ThinkingStep(
                        type="thinking",
                        content="Input is too short for a reliable chunked company analysis",
                    )
                ],
            )

        if not self.ai.llm_configured:
            hint = describe_missing_llm_credentials()
            return CompanySolutionResponse(
                success=False,
                query=query,
                response=f"**Company Solution Agent is not available.** {hint}",
                company_name=company_name,
                session_id=current_session_id,
                thinking_steps=[
                    ThinkingStep(
                        type="thinking",
                        content=f"LLM not configured for provider `{get_llm_provider()}`",
                    )
                ],
            )

        resolved_company_name = self._extract_company_name(input_text, company_name)

        catalog_text, uploaded_file_names, extraction_errors = self._extract_uploaded_catalog(uploaded_files)
        existing_solutions: List[Dict[str, Any]] = []
        if uploaded_file_names:
            thinking_steps.append(
                ThinkingStep(
                    type="tool_call",
                    content=f"Extracting text from {len(uploaded_file_names)} uploaded file(s): {', '.join(uploaded_file_names)}",
                    tool_name="file_extractor",
                    tool_input=f"files={len(uploaded_file_names)}",
                )
            )
            for err in extraction_errors:
                thinking_steps.append(
                    ThinkingStep(
                        type="observation",
                        content=f"File extraction warning: {err}",
                    )
                )

            if catalog_text.strip():
                thinking_steps.append(
                    ThinkingStep(
                        type="tool_call",
                        content="Parsing existing AI solution catalog from uploaded files",
                        tool_name="catalog_solution_parser",
                    )
                )
                existing_solutions = await self._extract_solutions_from_catalog(catalog_text)
                thinking_steps.append(
                    ThinkingStep(
                        type="tool_result",
                        content=(
                            f"Identified {len(existing_solutions)} existing AI solution(s) in the uploaded catalog"
                            if existing_solutions
                            else "No recognizable AI solutions found in the uploaded files — will suggest new solutions"
                        ),
                        tool_name="catalog_solution_parser",
                    )
                )

        thinking_steps.append(
            ThinkingStep(
                type="thinking",
                content=(
                    f"Analyzing detailed company context for {resolved_company_name or 'the provided company'} "
                    "by splitting the input into multiple chunks"
                ),
            )
        )

        chunks = self._split_into_chunks(input_text)
        chunk_limit = 12
        chunk_limit_hit = len(chunks) > chunk_limit
        if chunk_limit_hit:
            chunks = chunks[:chunk_limit]

        thinking_steps.append(
            ThinkingStep(
                type="tool_call",
                content=f"Chunked the input into {len(chunks)} analysis chunks",
                tool_name="chunk_analyzer",
                tool_input=f"chunks={len(chunks)}",
            )
        )

        chunk_summaries: List[str] = []
        for idx, chunk in enumerate(chunks, 1):
            thinking_steps.append(
                ThinkingStep(
                    type="tool_call",
                    content=f"Analyzing chunk {idx}/{len(chunks)}",
                    tool_name="genai_chunk_analysis",
                    tool_input=f"chunk_index={idx}",
                )
            )

            chunk_analysis = await self.ai.call_genai(
                self._chunk_prompt(chunk, resolved_company_name, idx, len(chunks)),
                temperature=0.15,
                max_tokens=1800,
            )

            if chunk_analysis.startswith("Error"):
                chunk_analysis = (
                    "## Problems Observed\n"
                    "- Analysis failed for this chunk due to LLM error.\n\n"
                    "## Current Process Improvement Opportunities\n"
                    "- Not available for this chunk.\n\n"
                    "## Potential AI / Agentic Opportunities\n"
                    "- Not available for this chunk.\n\n"
                    "## Evidence Signals\n"
                    "- Chunk analysis could not be completed."
                )

            chunk_summaries.append(chunk_analysis.strip())
            thinking_steps.append(
                ThinkingStep(
                    type="tool_result",
                    content=f"Completed chunk {idx}/{len(chunks)} analysis",
                    tool_name="genai_chunk_analysis",
                )
            )

        synthesis_input = self._fit_for_synthesis(chunk_summaries)

        thinking_steps.append(
            ThinkingStep(
                type="tool_call",
                content="Synthesizing all chunk insights into a prioritized AI solution report",
                tool_name="genai_solution_synthesis",
            )
        )

        catalog_prompt_text = self._format_catalog_for_prompt(existing_solutions)
        has_catalog = bool(existing_solutions)

        final_report = await self.ai.call_genai(
            self._final_prompt(
                company_name=resolved_company_name,
                full_details=input_text,
                chunk_summaries=synthesis_input,
                chunk_count=len(chunks),
                chunk_limit_hit=chunk_limit_hit,
                catalog_text=catalog_prompt_text,
                has_catalog=has_catalog,
            ),
            temperature=0.2,
            max_tokens=8192,
        )

        if final_report.startswith("Error"):
            return CompanySolutionResponse(
                success=False,
                query=query,
                response=f"Failed to synthesize company solutions: {final_report}",
                company_name=resolved_company_name,
                chunk_count=len(chunks),
                uploaded_file_names=uploaded_file_names,
                session_id=current_session_id,
                thinking_steps=thinking_steps,
            )

        if chunk_limit_hit:
            final_report += (
                "\n\n---\n"
                "Note: Input was very large. The report was generated from the first "
                f"{chunk_limit} chunks to keep response quality and runtime stable."
            )

        matched_in_report, newly_suggested = self._parse_solutions_from_report(final_report)
        existing_solutions_used: List[Dict[str, Any]] = []
        for m in matched_in_report:
            ref: Dict[str, Any] = {"name": m.get("name", ""), "source_line": m.get("source_line", "")}
            idx = m.get("catalog_index")
            if isinstance(idx, int) and 1 <= idx <= len(existing_solutions):
                ref["catalog_entry"] = existing_solutions[idx - 1]
            existing_solutions_used.append(ref)

        if has_catalog:
            thinking_steps.append(
                ThinkingStep(
                    type="observation",
                    content=(
                        f"Smart pick: {len(existing_solutions_used)} solution(s) sourced from your catalog, "
                        f"{len(newly_suggested)} newly suggested."
                    ),
                )
            )

        thinking_steps.append(
            ThinkingStep(
                type="tool_result",
                content="Generated final prioritized AI and agentic AI recommendations",
                tool_name="genai_solution_synthesis",
            )
        )
        thinking_steps.append(
            ThinkingStep(
                type="observation",
                content="Company solution analysis completed successfully",
            )
        )

        self.sessions[current_session_id] = {
            "company_name": resolved_company_name,
            "last_input": input_text[:12000],
            "last_report": final_report,
            "timestamp": datetime.now().isoformat(),
        }

        return CompanySolutionResponse(
            success=True,
            query=query,
            response=final_report,
            company_name=resolved_company_name,
            chunk_count=len(chunks),
            existing_solutions_used=existing_solutions_used,
            suggested_solutions=newly_suggested,
            uploaded_file_names=uploaded_file_names,
            session_id=current_session_id,
            thinking_steps=thinking_steps,
        )


company_solution_agent = CompanySolutionAgent()
