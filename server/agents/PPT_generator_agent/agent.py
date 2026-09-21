import asyncio
import uuid
import json
import re
import os
from typing import List, Dict, Any, Optional

from .ai_service import ppt_ai_service
from .models import PPTGeneratorResponse, ThinkingStep, MAX_SLIDES, MIN_SLIDES
from .planner import (
    build_planner_prompt,
    build_planner_prompt_minimal,
    normalize_planner_output,
    extract_planner_meta,
    _parse_json_object,
)
from .slide_preview_svg import slide_dict_to_preview_payload
from .tools.image_search import search_images_batch, cleanup_old_cached_images
from .tools.ppt_builder import build_pptx, cleanup_old_generated_pptx
from .tools.ollama_free_search import ppt_ollama_free_search
from .tools.duckduckgo_free_search import ppt_duckduckgo_free_search
from .tools.file_ingest import (
    extract_uploaded_text,
    chunk_text_for_parallel_processing,
    choose_relevant_chunks,
    chunks_to_research_rows,
)
from .tools.perplexity_search import ppt_perplexity_search, format_research_for_prompt


class PPTGeneratorAgent:

    _NARRATIVE_BLUEPRINTS = (
        {
            "name": "evidence-first",
            "sequence": "Title -> Context/Problem -> Evidence/Data -> Strategy/Options -> Execution/Timeline -> Risks -> CTA",
            "planner_instruction": "Quantify problem and evidence before prescribing strategy, then close with execution and risk treatment.",
            "holistic_instruction": "Front-load proof and data, then convert evidence into decisions and a concrete operating plan.",
        },
        {
            "name": "opportunity-pull",
            "sequence": "Title -> Opportunity/Context -> Barrier Analysis -> Strategic Response -> Capability Build -> Business Case -> Risks -> CTA",
            "planner_instruction": "Lead with market upside, surface blockers, then map the response and capabilities needed to capture value.",
            "holistic_instruction": "Keep an opportunity-led tone while still quantifying constraints before recommendations.",
        },
        {
            "name": "thesis-counterpoint",
            "sequence": "Title -> Thesis Setup -> Counter-Evidence -> Reconciled Insight -> Strategic Choices -> Execution Path -> Risks -> CTA",
            "planner_instruction": "Use a debate-style arc: state a thesis, test it with counterpoints, then converge on the strongest path.",
            "holistic_instruction": "Ensure title flow reads like claim -> challenge -> synthesis -> action, not a linear status report.",
        },
        {
            "name": "risk-to-value",
            "sequence": "Title -> Context/Exposure -> Quantified Risks -> Mitigation Strategy -> Execution Milestones -> Value Unlock -> CTA",
            "planner_instruction": "Start by sizing downside and urgency, then move to mitigation levers and upside unlocked by de-risking.",
            "holistic_instruction": "Sustain a risk-register mindset early, then pivot to measurable upside after mitigations are established.",
        },
    )

    def __init__(self):
        self.ai = ppt_ai_service
        self._last_blueprint_id: Optional[str] = None

        from agents.local_llm import describe_missing_llm_credentials, get_llm_provider

        _llm_labels = {"pwc_genai": "PwC GenAI", "local_llm": "local LLM", "ollama_cloud": "Ollama Cloud"}
        if self.ai.llm_configured:
            prov = get_llm_provider()
            print(f"📊 PPT Generator Agent — LLM: {_llm_labels.get(prov, prov)}")
        else:
            print(f"⚠️ PPT Generator Agent — {describe_missing_llm_credentials()}")

        # Best-effort startup cleanup so the generated-files folder doesn't
        # grow unbounded across restarts. Errors here never block agent init.
        try:
            cleanup_old_generated_pptx(max_age_hours=int(os.getenv("PPT_FILE_TTL_HOURS", "24")))
            cleanup_old_cached_images(max_age_hours=int(os.getenv("PPT_IMAGE_CACHE_TTL_HOURS", "168")))
        except Exception as e:
            print(f"⚠️ PPT cleanup skipped: {e}")

    def _add_thinking(self, steps: List[Dict], step_type: str, content: str, tool_name: str = None, tool_input: str = None):
        step = {"type": step_type, "content": content}
        if tool_name:
            step["tool_name"] = tool_name
        if tool_input:
            step["tool_input"] = tool_input
        steps.append(step)

    async def _detect_narrative_arc_llm(
        self,
        query: str,
        intelligence_brief: str = "",
        raw_user_content: str = "",
    ) -> Optional[Dict[str, str]]:
        """Ask the LLM for a CUSTOM narrative arc tailored to this request.

        Returns a blueprint dict with name/sequence/planner_instruction/
        holistic_instruction, or None if the call fails / parses poorly.
        The caller falls back to the keyword scorer on None.
        """
        sample_source = raw_user_content or intelligence_brief or ""
        probe = (sample_source or query)[:2400]
        prompt = f"""You are an executive presentation strategist. Read the user's request + source material below and
propose a CUSTOM narrative arc tailored to this specific deck. Do not choose from fixed templates — design the arc
from the content shape. Favour orderings that match how the content is actually organised (e.g., if the source lists
problems then recommendations then a roadmap, the arc should preserve that progression).

USER REQUEST / SHORT TOPIC:
{query[:400]}

SOURCE MATERIAL (extract the argument structure from this):
{probe}

Return ONLY this JSON (no markdown fences):
{{
  "name": "<2-4 word slug for the arc, lowercase with hyphens>",
  "sequence": "Title -> <beat 2> -> <beat 3> -> ... -> CTA  (5-9 beats reflecting THIS content; every beat must earn its place)",
  "planner_instruction": "<one sentence: how the planner should sequence middle slides for this particular request>",
  "holistic_instruction": "<one sentence: tonal and emphasis guidance for the author writing slide bodies>"
}}"""
        try:
            raw = await self.ai.call_genai(prompt, temperature=0.2, max_tokens=500)
        except Exception:
            return None
        if not raw or str(raw).startswith("Error"):
            return None
        import json as _json
        cleaned = raw.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if m:
            cleaned = m.group(1).strip()
        first, last = cleaned.find("{"), cleaned.rfind("}")
        if first == -1 or last <= first:
            return None
        try:
            data = _json.loads(cleaned[first:last + 1])
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        name = str(data.get("name", "")).strip()
        sequence = str(data.get("sequence", "")).strip()
        planner_instr = str(data.get("planner_instruction", "")).strip()
        holistic_instr = str(data.get("holistic_instruction", "")).strip()
        if not (name and sequence and planner_instr):
            return None
        return {
            "name": name[:48],
            "sequence": sequence[:400],
            "planner_instruction": planner_instr[:240],
            "holistic_instruction": (holistic_instr or planner_instr)[:240],
        }

    def _select_narrative_blueprint(
        self,
        query: str,
        intelligence_brief: str = "",
        has_uploaded_file: bool = False,
    ) -> Dict[str, str]:
        """Pick the deck blueprint from user intent + available evidence.

        This avoids locking every deck to a fixed sequence and biases flow
        toward the request semantics (risk-heavy, comparison-heavy, growth-led,
        etc.) plus any uploaded/researched content cues.
        """
        text = f"{query}\n{intelligence_brief}".lower()
        scores = {bp["name"]: 0 for bp in self._NARRATIVE_BLUEPRINTS}
        scores["evidence-first"] += 1  # safe default when intent is ambiguous

        def _boost(target: str, terms: List[str], weight: int):
            for term in terms:
                if term in text:
                    scores[target] += weight

        _boost(
            "risk-to-value",
            [
                "risk", "risks", "mitigation", "compliance", "regulation", "regulatory",
                "audit", "security", "exposure", "incident", "penalty", "governance",
            ],
            2,
        )
        _boost(
            "thesis-counterpoint",
            [
                " vs ", "versus", "compare", "comparison", "trade-off", "tradeoff",
                "counter", "pros and cons", "alternative", "option", "debate",
            ],
            2,
        )
        _boost(
            "opportunity-pull",
            [
                "opportunity", "growth", "expand", "expansion", "market entry", "go-to-market",
                "gtm", "capture", "white space", "new segment", "scale", "upside",
            ],
            2,
        )
        _boost(
            "evidence-first",
            [
                "root cause", "diagnostic", "analysis", "evidence", "data", "benchmark",
                "baseline", "fact base", "quantify", "kpi", "metrics",
            ],
            1,
        )

        # Research-file tags carry strong intent signals.
        if "[risk]" in text or "[reg]" in text:
            scores["risk-to-value"] += 2
        if "[player]" in text or "[stat]" in text or "[breaking]" in text:
            scores["evidence-first"] += 1
        if has_uploaded_file:
            scores["evidence-first"] += 1

        max_score = max(scores.values()) if scores else 0
        candidates = [
            dict(bp) for bp in self._NARRATIVE_BLUEPRINTS
            if scores.get(bp.get("name", ""), 0) == max_score
        ]
        if self._last_blueprint_id and len(candidates) > 1:
            filtered = [bp for bp in candidates if bp.get("name") != self._last_blueprint_id]
            if filtered:
                candidates = filtered

        chosen = candidates[0] if candidates else dict(self._NARRATIVE_BLUEPRINTS[0])
        self._last_blueprint_id = chosen.get("name")
        return chosen

    def _brand_prompt_block(self, theme: str, card_only: bool = False) -> str:
        if (theme or "").strip().lower() != "pwc":
            return ""
        image_rule = (
            "- Imagery and icons must feel real, professional, inclusive, flat, and minimal."
            if not card_only
            else "- Use a pure presentation system: clean cards, simple charts, and minimal icons only; no decorative noise or photo-led concepts."
        )
        return (
            "\nPWC BRAND GUIDELINE (mandatory on every slide):\n"
            "- Tone: bold, collaborative, optimistic; voice must stay direct, business-focused, and insightful.\n"
            "- Layout: one slide, one message. Structure each slide around title, key message, supporting data, and conclusion.\n"
            "- Content logic: MECE and pyramid principle. Prefer short bullets and data-backed insights; avoid long paragraphs.\n"
            "- Typography/layout: keep copy left aligned and visually consistent; do not imply mixed font systems.\n"
            "- Colour use: base is black/white on light backgrounds. Reserve PwC orange (#DC6900) for the single most important highlight and limit multi-colour usage per slide.\n"
            "- Data viz: minimal gridlines, clear storytelling, and highlight the key data point in orange.\n"
            "- Spacing: use whitespace, maintain alignment, and avoid overcrowding.\n"
            f"{image_rule}\n"
            "- If a slide feels decorative, generic, or multi-message, simplify it until the core insight is unmistakable.\n"
        )

    def _provider_token_budget(self, default: int = 8192) -> int:
        """Ollama Cloud/local models need a generous num_predict cap so that
        thinking models (qwen3.x) have tokens for both the reasoning phase
        *and* the JSON response.  8000 comfortably covers a 10–14-slide JSON
        outline (~2.5k tokens) even with some thinking overhead.
        PwC/Gemini retains the full default."""
        try:
            from agents.local_llm import get_llm_provider
            prov = get_llm_provider()
        except Exception:
            return default
        if prov in ("ollama_cloud", "local_llm"):
            return min(default, 8000)
        return default

    def _is_offline_or_ollama_provider(self) -> bool:
        """True for local / Ollama backends — no remote stock-image pipeline."""
        try:
            from agents.local_llm import get_llm_provider
            return get_llm_provider() in ("ollama_cloud", "local_llm")
        except Exception:
            return False

    def _is_compact_provider(self) -> bool:
        """True when the active LLM benefits from a shorter prompt (Ollama
        Cloud + local models). These endpoints 500 on long prompt + long
        generation combinations."""
        return self._is_offline_or_ollama_provider()

    def _resolve_agent_config(self, user_config: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Merge catalog admin defaults with the user_config dict sent by the
        client. Values read here come strictly from agent config — server/.env
        is deliberately not consulted for web-search settings.

        Boolean-control fields (e.g. ``PPT_WEB_SEARCH_ENABLED``) arrive from
        the UI as a JSON boolean; ``merge_configs`` filters out non-string
        values, so we coerce booleans/numbers to their string form before
        merging to keep the toggle intact.
        """
        normalized: Dict[str, str] = {}
        for k, v in (user_config or {}).items():
            if v is None:
                continue
            if isinstance(v, bool):
                normalized[k] = "true" if v else "false"
            elif isinstance(v, (int, float)):
                normalized[k] = str(v)
            else:
                normalized[k] = v  # merge_configs will validate/strip strings
        try:
            from user_config import merge_configs_for_agent_id
            return merge_configs_for_agent_id("ppt_generator", normalized)
        except Exception:
            return normalized

    def _resolve_web_search(
        self,
        explicit: Optional[bool],
        agent_config: Dict[str, str],
    ) -> tuple:
        """Return ``(enabled, provider, api_key, reason_if_disabled)``.

        Values are pulled from agent config only. A True toggle is honoured
        only when the selected provider has credentials in agent config.
        Otherwise we surface a clear reason instead of silently running
        without search.
        """
        provider_raw = (agent_config.get("PPT_WEB_SEARCH_PROVIDER") or "perplexity").strip().lower()
        if provider_raw in {"free", "free_web", "free_ollama", "ollama", "ollama_free"}:
            provider = "free_ollama"
        elif provider_raw in {"free_duckduckgo", "duckduckgo", "duck", "ddg"}:
            provider = "free_duckduckgo"
        else:
            provider = "perplexity"

        # Request body must use default None (omit field) so config toggle applies; defaulting
        # the API field to False would always override PPT_WEB_SEARCH_ENABLED — see PPTGeneratorRequest.
        if explicit is None:
            raw = (agent_config.get("PPT_WEB_SEARCH_ENABLED") or "").strip().lower()
            toggle_on = raw in ("1", "true", "yes", "on")
        else:
            toggle_on = bool(explicit)

        if not toggle_on:
            return False, provider, "", ""

        if provider == "perplexity":
            api_key = (agent_config.get("PERPLEXITY_API_KEY") or "").strip()
            if not api_key:
                return False, provider, "", (
                    "Web search is enabled with provider=perplexity but PERPLEXITY_API_KEY is missing in agent config."
                )
            if not ppt_perplexity_search.is_configured(api_key=api_key):
                return False, provider, "", (
                    "Web search requested but the perplexity SDK is not installed on the server."
                )
            return True, provider, api_key, ""

        if provider == "free_duckduckgo":
            if not ppt_duckduckgo_free_search.is_configured():
                return False, provider, "", (
                    "Web search requested with provider=free_duckduckgo but the ddgs package is not installed on the server."
                )
            return True, provider, "", ""

        api_key = (
            agent_config.get("OLLAMA_API_KEY")
            or agent_config.get("ON_PREM_CLOUD_ACCESS_TOKEN")
            or agent_config.get("OLLAMA_CLOUD_BEARER_TOKEN")
            or ""
        ).strip()
        if not api_key:
            return False, provider, "", (
                "Web search is enabled with provider=free_ollama but OLLAMA_API_KEY is missing in agent config."
            )
        if not ppt_ollama_free_search.is_configured(api_key=api_key):
            return False, provider, "", (
                "Web search requested but OLLAMA_API_KEY is missing from agent config."
            )
        return True, provider, api_key, ""

    def _parse_single_slide_object(self, raw: str) -> Optional[Dict[str, Any]]:
        cleaned = (raw or "").strip()
        # Strip qwen3-style <think>…</think> blocks that leak through Ollama Cloud.
        cleaned = re.sub(r"<think>[\s\S]*?</think>", "", cleaned, flags=re.IGNORECASE).strip()
        # Strip a lone unmatched <think> opener (model started thinking, never
        # closed the tag because num_predict ran out).
        cleaned = re.sub(r"^<think>[\s\S]*$", "", cleaned, flags=re.IGNORECASE).strip()
        # Strip everything before the first { and after the last } as a safety net.
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", cleaned)
        if m:
            cleaned = m.group(1).strip()

        def _accept(d: Any) -> Optional[Dict[str, Any]]:
            """Accept any dict that looks slide-shaped. Empty/missing title is
            tolerated — the caller fills from the plan row's assertion hint."""
            if not isinstance(d, dict):
                return None
            slide_keyset = {
                "title", "subtitle", "type", "bullets", "stats", "items",
                "steps", "left", "right", "quote", "attribution", "image_query",
            }
            if not (slide_keyset & set(d.keys())):
                return None
            return d

        try:
            data = json.loads(cleaned)
            accepted = _accept(data)
            if accepted is not None:
                return accepted
        except json.JSONDecodeError:
            pass
        # Greedy first-{ to last-} — handles trailing prose like "Here is the JSON: {...}. Hope this helps!"
        first = cleaned.find("{")
        last = cleaned.rfind("}")
        if first != -1 and last > first:
            candidate = cleaned[first : last + 1]
            try:
                data = json.loads(candidate)
                accepted = _accept(data)
                if accepted is not None:
                    return accepted
            except json.JSONDecodeError:
                # Try removing trailing commas and lone closing quotes.
                fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
                try:
                    data = json.loads(fixed)
                    accepted = _accept(data)
                    if accepted is not None:
                        return accepted
                except json.JSONDecodeError:
                    pass
        return None

    _RICH_QUERY_CHAR_THRESHOLD = 1200

    def _is_rich_query(self, query: str) -> bool:
        return bool(query) and len(query) >= self._RICH_QUERY_CHAR_THRESHOLD

    def _derive_short_topic(self, query: str, max_chars: int = 260) -> str:
        """First non-empty line or first sentence — used as the "TOPIC" header
        when the full query is a multi-page structured input."""
        s = (query or "").strip()
        if not s:
            return ""
        first_line = next((ln.strip() for ln in s.splitlines() if ln.strip()), "")
        if first_line and len(first_line) <= max_chars:
            return first_line
        return s[:max_chars].rsplit(" ", 1)[0] + "…"

    def _extract_user_sections(self, query: str) -> List[Dict[str, str]]:
        """Light section parser for user-pasted structured content.

        Recognises markdown-ish headings (#, ##, bold lines ending with ':' or
        lines in Title Case followed by bullets). Used by fallback slides so
        they can pull meaningful text from the user's actual input instead of
        emitting "—" placeholders.
        """
        if not query:
            return []
        out: List[Dict[str, str]] = []
        current: Optional[Dict[str, str]] = None
        for line in query.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            is_heading = False
            if stripped.startswith("#"):
                is_heading = True
                heading = stripped.lstrip("#").strip()
            elif re.match(r"^\*\*[^*]+\*\*:?\s*$", stripped):
                is_heading = True
                heading = stripped.strip("*").rstrip(":").strip()
            elif len(stripped) <= 90 and not stripped.endswith(".") and not stripped.startswith(("-", "*", "•", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
                # Title-Case heading heuristic
                words = stripped.split()
                if words and sum(1 for w in words if w[:1].isupper()) >= max(1, int(len(words) * 0.6)):
                    is_heading = True
                    heading = stripped
            if is_heading:
                if current and current["body"].strip():
                    out.append(current)
                current = {"heading": heading[:120], "body": ""}
            else:
                if current is None:
                    current = {"heading": "Overview", "body": ""}
                current["body"] += stripped + "\n"
        if current and current["body"].strip():
            out.append(current)
        return out[:24]

    def _fallback_slide_from_plan(
        self,
        query: str,
        plan_row: Dict[str, Any],
        card_only: bool,
        user_sections: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        st = plan_row.get("slide_type") or "content"
        hint = (plan_row.get("assertion_title_hint") or query)[:120]

        # Try to pair this slide with a section from the user's original input
        # so the fallback carries real content instead of "—" placeholders.
        section_match: Optional[Dict[str, str]] = None
        if user_sections:
            pos = max(1, int(plan_row.get("position") or 1))
            hint_low = (plan_row.get("assertion_title_hint") or "").lower()
            best_score = 0
            for sec in user_sections:
                head_low = (sec.get("heading") or "").lower()
                body_low = (sec.get("body") or "").lower()
                score = 0
                for tok in re.findall(r"[a-z]{4,}", hint_low):
                    if tok in head_low:
                        score += 3
                    elif tok in body_low:
                        score += 1
                if score > best_score:
                    best_score = score
                    section_match = sec
            if section_match is None and user_sections:
                idx = min(len(user_sections) - 1, max(0, pos - 2))
                section_match = user_sections[idx]

        section_heading = (section_match or {}).get("heading", "").strip()
        section_body = (section_match or {}).get("body", "").strip()
        section_lines = [
            ln.lstrip("-*•0123456789. ").strip()
            for ln in section_body.splitlines()
            if ln.strip()
        ]
        section_lines = [ln for ln in section_lines if len(ln) >= 15][:8]

        def _bullets(n: int) -> List[str]:
            if section_lines:
                return [ln[:220] for ln in section_lines[:n]] or [hint]
            return [hint, "Expand with supporting evidence from the source input.", "Quantify the impact where metrics are available."][:n]

        base: Dict[str, Any] = {"type": st, "title": (section_heading or hint)[:120]}
        if st == "title":
            base["title"] = hint
            base["subtitle"] = (section_body[:160] if section_body else f"Prepared from: {query[:160]}")
        elif st == "closing":
            base["title"] = hint[:60]
            base["subtitle"] = (section_lines[0][:160] if section_lines else "Next step: align stakeholders on scope, timeline, and capital.")
        elif st == "content":
            base["bullets"] = _bullets(5)
        elif st == "stats":
            items = []
            for ln in section_lines[:4]:
                m = re.search(r"(\d[\d,\.]*\s?(?:%|x|×|bn|B|m|M|k|K|Cr|L|₹|\$|€)?)", ln)
                val = (m.group(1) if m else "—")[:12]
                label = ln[:140]
                items.append({"value": val, "label": label})
            base["stats"] = items or [{"value": "—", "label": hint[:120]}]
        elif st == "quote":
            base["quote"] = (section_lines[0] if section_lines else hint)[:240]
            base["attribution"] = section_heading or "Source input"
        elif st in ("numbered_list", "process_flow", "timeline"):
            key = "steps" if st in ("process_flow", "timeline") else "items"
            items = []
            for i, ln in enumerate(section_lines[:6]):
                parts = ln.split(":", 1)
                t = parts[0].strip()[:60] if len(parts) == 2 and len(parts[0]) <= 60 else f"Step {i+1}"
                d = (parts[1].strip() if len(parts) == 2 else ln)[:200]
                entry = {"title": t, "description": d}
                if st == "process_flow":
                    entry["icon"] = "insight"
                items.append(entry)
            base[key] = items or [{"title": hint[:60], "description": (section_body[:180] or "Add supporting detail.")}]
        elif st == "icon_grid":
            items = []
            for ln in section_lines[:4]:
                parts = ln.split(":", 1)
                t = parts[0].strip()[:40] if len(parts) == 2 and len(parts[0]) <= 40 else ln[:40]
                d = (parts[1].strip() if len(parts) == 2 else ln)[:180]
                items.append({"title": t, "description": d, "icon": "insight"})
            base["items"] = items or [{"title": hint[:40], "description": (section_body[:160] or "Add supporting detail."), "icon": "insight"}]
        elif st in ("comparison", "two_column"):
            halves = section_lines[:6] or [hint]
            mid = max(1, len(halves) // 2)
            base["left"] = {"title": (section_heading or "A")[:40], "bullets": [ln[:160] for ln in halves[:mid]] or [hint]}
            base["right"] = {"title": "B", "bullets": [ln[:160] for ln in halves[mid:]] or [hint]}
        else:
            base["type"] = "content"
            base["bullets"] = _bullets(4)
        if not card_only:
            base["image_query"] = f"Editorial photograph illustrating: {(section_heading or hint)[:80]}"
        return base

    def _build_single_slide_author_prompt(
        self,
        query: str,
        theme: str,
        plan_row: Dict[str, Any],
        slide_research: str,
        prior_titles: List[str],
        slide_index: int,
        total_slides: int,
        card_only: bool,
    ) -> str:
        pt = "\n".join(f"  - {t}" for t in prior_titles[-6:] if t)
        img_rule = (
            'Include "image_query": one cinematic scene description (no generic "team meeting").'
            if not card_only
            else 'Do NOT include "image_query".'
        )
        brand_block = self._brand_prompt_block(theme, card_only=card_only)
        return f"""You are the SLIDE AUTHOR for slide {slide_index} of {total_slides} in a {theme} executive deck.

DECK TOPIC: {query}
{brand_block}

PLANNER LAYOUT: {plan_row.get("layout_choice", "")} — {plan_row.get("layout_rationale", "")}
ASSERTION DIRECTION: {plan_row.get("assertion_title_hint", "")}
AUTHOR INSTRUCTIONS FROM PLANNER:
{plan_row.get("data_prompt_for_slide_author", "")}

SLIDE TYPE (must match exactly): "{plan_row.get("slide_type", "content")}"

PRIOR SLIDE TITLES (stay coherent; do not repeat verbatim):
{pt or "  (none)"}

WEB RESEARCH FOR THIS SLIDE ONLY (primary source — prefer LAST 24H / THIS WEEK blocks; cite source names + dates in labels):
{slide_research or "(no research returned — use cautious qualitative framing; do NOT invent precise statistics.)"}

NUMERIC + SOURCE MANDATE:
- Every bullet, stat label, item description, or step MUST include at least one hard number when research provides any; otherwise say "data pending" instead of fabricating.
- Prefer TWO numbers where possible (fact + comparison).
- Mention source organisation and year or "(as of …)" in text for key claims.

{img_rule}

Return ONE JSON object only (not an array), matching the schema for slide type "{plan_row.get("slide_type", "content")}" from the allowed set used by this system. No markdown fences.

Allowed shapes mirror the deck generator:
- title/section/closing: {{"type":…,"title":str,"subtitle":str[, "image_query": str]}}
- content: {{"type":"content","title":str,"bullets":[str,…4-5][, "image_query"]}}
- stats: {{"type":"stats","title":str,"stats":[{{"value","label"}},…2-4][, "image_query"]}}
- quote: {{"type":"quote","title","quote","attribution"[, "image_query"]}}
- comparison/two_column: left/right with title+bullets
- timeline / numbered_list / process_flow / icon_grid: use standard fields with icons from the approved icon keyword list.

Write the JSON object now:"""

    def _build_holistic_deck_prompt(
        self,
        query: str,
        theme: str,
        plan_rows: List[Dict[str, Any]],
        planner_meta: Dict[str, Any],
        intelligence_brief: str,
        card_only: bool,
        narrative_blueprint: Optional[Dict[str, str]] = None,
        raw_user_content: Optional[str] = None,
    ) -> str:
        """One-shot prompt that writes EVERY slide in a single LLM call.

        This is the deck-quality lever: the model sees the full plan + the
        shared intelligence brief + all quality mandates and threads metrics
        across slides in one pass. Per-slide polish runs afterwards.
        """
        from datetime import datetime
        today_str = datetime.now().strftime("%B %d, %Y")

        plan_lines: List[str] = []
        for r in plan_rows:
            plan_lines.append(
                f"  {r['position']:>2}. [{r['slide_type']}] layout={r.get('layout_choice', '')} — "
                f"hint: {r.get('assertion_title_hint', '')[:120]}\n"
                f"       author-directive: {r.get('data_prompt_for_slide_author', '')[:280]}"
            )
        plan_block = "\n".join(plan_lines)

        threaded = planner_meta.get("threaded_metrics") or []
        threaded_block = ""
        if threaded:
            threaded_block = (
                "\nCROSS-SLIDE METRIC THREADING (mandatory — these metrics/entities must recur across ≥3 slides, "
                "each time with a different lens: introduce → quantify → compare → act on → risk-adjust):\n"
                + "\n".join(f"  • {t}" for t in threaded)
                + "\n"
            )

        arc = planner_meta.get("deck_arc_summary") or ""
        arc_block = f"\nDECK ARC: {arc}\n" if arc else ""

        raw_block = ""
        if raw_user_content and raw_user_content.strip():
            raw_cap = 7000 if card_only else 12000
            raw_block = (
                "\nUSER-PROVIDED CONTENT (PRIMARY SOURCE — verbatim, authoritative; every section below MUST be "
                "represented by at least one slide; every named item / hard number must land somewhere in the deck):\n"
                f"{raw_user_content[:raw_cap]}\n"
            )

        brief_block = ""
        if intelligence_brief:
            brief_block = f"\nINTELLIGENCE BRIEF — supplementary fact source (use after USER CONTENT; do NOT invent numbers):\n{intelligence_brief}\n"
        source_lock_block = ""
        if "INTELLIGENCE BRIEF — UPLOADED CONTENT" in (intelligence_brief or ""):
            source_lock_block = (
                "\nSOURCE LOCK (uploaded file mode — mandatory):\n"
                "- Use ONLY facts present in the uploaded-file brief/research snippets.\n"
                "- Do NOT use external/world knowledge, prior-company facts, or generic filler assertions.\n"
                "- If a required number is absent from uploaded content, write 'data pending from uploaded file'.\n"
                "- Every quantified claim must include an uploaded source anchor (uploaded://... chunk id or source label).\n"
                "- If uncertain, be conservative and keep wording tied to explicit uploaded evidence.\n"
            )

        img_rule = (
            'Every slide MUST include "image_query": one cinematic, specific scene description (not "team meeting" or "people discussing").'
            if not card_only
            else 'Do NOT include "image_query" on any slide — the offline renderer uses brand cards and icons only.'
        )
        brand_block = self._brand_prompt_block(theme, card_only=card_only)
        blueprint_name = (narrative_blueprint or {}).get("name") or "evidence-first"
        blueprint_sequence = (narrative_blueprint or {}).get("sequence") or (
            "Title -> Context/Problem -> Evidence/Data -> Strategy/Options -> Execution/Timeline -> Risks -> CTA"
        )
        blueprint_instruction = (narrative_blueprint or {}).get("holistic_instruction") or (
            "Follow the selected blueprint for title flow while preserving strict quantitative evidence and executive coherence."
        )

        return f"""You are a McKinsey/BCG-calibre partner writing the COMPLETE content for an executive-grade 16:9 PowerPoint deck in ONE pass.

TODAY: {today_str}
TOPIC / REQUEST: {query}
THEME: {theme}
ACTIVE NARRATIVE BLUEPRINT: {blueprint_name} — {blueprint_sequence}
BLUEPRINT GUIDANCE: {blueprint_instruction}
{brand_block}
{arc_block}{threaded_block}{raw_block}{brief_block}{source_lock_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SLIDE PLAN (execute EXACTLY — same count, same order, same slide_type per position):
{plan_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUALITY GATES (non-negotiable — deck is graded on every one):

1. NUMERIC DENSITY: ≥90% of bullets, stat labels, and descriptions MUST contain at least one hard number
   (%, $, ₹, €, ×, bps, count, year, CAGR, YoY, pp). Prefer TWO numbers per bullet (fact + comparison).
   Prose-only bullets are rejected.

2. ASSERTION TITLES: every slide title states a quantified conclusion, not a topic label.
   ✗ "Market Overview"  ✓ "Market Growing at 23% CAGR — First-Mover Window Closes in 18 Months"

3. SII STRUCTURE per bullet (20–35 words): Situation → Insight → Implication, with numbers.
   ✓ "FY24 revenue grew 34% YoY to $4.2B — outpacing category growth of 12%, signalling $1.1B expansion headroom"

4. FRESHNESS FIRST: [BREAKING] entries from the brief MUST appear in the opening 2 slides and be cited
   with "(as of {today_str})" or "(updated <date>)". When the brief gives both recent and older figures for
   the same metric, always cite the recent one.

5. SOURCE CITATION: every stat label carries "source + year" (e.g. "+8pp vs. specialist baseline (NEJM 2024)").
   The quote slide MUST use a [QUOTE] verbatim with full attribution from the brief.

6. CROSS-SLIDE COHERENCE — the most important gate:
   • A reader skimming ONLY the titles in order must understand the complete argument.
   • Each title logically follows the previous. Adjacent slides share a connecting thread.
   • The threaded metrics above MUST recur: introduced in early slides, compared mid-deck, acted upon
     in strategy slides, risk-checked in later slides. NO siloed tiles.
   • Do NOT restate identical numbers across slides — evolve them (establish → segment → compare → project).
   • Interleave slide types — never 3+ consecutive slides of the same type.

7. NARRATIVE FLOW is adaptive to the selected plan and available evidence:
    Selected blueprint (guidance): {blueprint_sequence}
    Use the blueprint as a directional pattern, not a rigid order. Reorder or compress beats when needed so titles read as a natural argument for this specific query.

8. DECK-WIDE CHECKLIST (cover every applicable item somewhere in the deck):
   □ TAM with source + year  □ CAGR with time window  □ named competitors with share  □ ≥1 verbatim quote
   □ NPV or payback period  □ execution timeline with dated milestones  □ quantified risks (probability or $)
   □ regulatory/compliance context if applicable  □ comparison benchmark (peer/industry/prior period)

9. TOPIC ANCHORING: every slide directly serves the TOPIC above. No generic "About Us" / "Thank You" filler.

10. {img_rule}

LANGUAGE REGISTER: CAGR, YoY, bps, TAM/SAM/SOM, NPV, EBITDA, payback, run-rate, headroom.
AVOID: "leverage", "best-in-class", "synergies", "innovative solutions", "move the needle", vague superlatives.

ALLOWED SLIDE SCHEMAS (use exactly these JSON shapes{' — no image_query' if card_only else ''}):
- title/section/closing: {{"type":T,"title":str,"subtitle":str{'' if card_only else ',"image_query":str'}}}
- content:       {{"type":"content","title":str,"bullets":[str,...](4-5){'' if card_only else ',"image_query":str'}}}
- stats:         {{"type":"stats","title":str,"stats":[{{"value":str,"label":str}},...](2-4){'' if card_only else ',"image_query":str'}}}
- quote:         {{"type":"quote","title":str,"quote":str,"attribution":str{'' if card_only else ',"image_query":str'}}}
- comparison/two_column: {{"type":T,"title":str,"left":{{"title":str,"bullets":[...]}},"right":{{"title":str,"bullets":[...]}}{'' if card_only else ',"image_query":str'}}}
- timeline:      {{"type":"timeline","title":str,"steps":[{{"title":str,"description":str}},...](3-5){'' if card_only else ',"image_query":str'}}}
- numbered_list: {{"type":"numbered_list","title":str,"items":[{{"title":str,"description":str}},...](3-6){'' if card_only else ',"image_query":str'}}}
- process_flow:  {{"type":"process_flow","title":str,"steps":[{{"title":str,"description":str,"icon":str}},...](3-5){'' if card_only else ',"image_query":str'}}}
- icon_grid:     {{"type":"icon_grid","title":str,"items":[{{"title":str,"description":str,"icon":str}},...](3-4){'' if card_only else ',"image_query":str'}}}

ICON KEYWORDS (for icon fields — pick ONE, do not invent, do not use emojis):
chart, bar_chart, pie_chart, analytics, dashboard, growth, trend, revenue, decline, target, goal, strategy,
flag, milestone, trophy, people, team, customer, partner, gear, operations, process, automation, workflow,
idea, innovation, research, insight, shield, security, risk, compliance, verified, money, finance, cost,
savings, investment, roi, clock, time, calendar, schedule, cloud, server, database, api, code, globe, global,
scale, network, check, quality, star, premium, document, report, contract, rocket, launch, deploy, build,
building, company, enterprise, factory.

Return ONLY a valid JSON array of exactly {len(plan_rows)} slide objects — no markdown fences, no commentary,
no trailing commas. The slide at array index i MUST have slide_type matching the plan above at position i+1.

Write the complete JSON array now:"""

    def _build_slide_polish_prompt(
        self,
        query: str,
        theme: str,
        plan_row: Dict[str, Any],
        slide_obj: Dict[str, Any],
        slide_research: str,
        slide_index: int,
        total_slides: int,
        card_only: bool,
    ) -> str:
        """Tighten a single slide in place — enforce numeric density, source
        citation, and assertion title. Keeps shape unchanged; only sharpens
        within-slide content. Runs in parallel across slides (cross-slide
        coherence is already established by the holistic author)."""
        img_rule = (
            'Preserve "image_query" if present; do not remove it.'
            if not card_only
            else 'Do NOT add "image_query"; remove it if present.'
        )
        source_lock = ""
        if "uploaded://" in (slide_research or ""):
            source_lock = (
                "\nSOURCE LOCK (uploaded file mode):\n"
                "- Do NOT inject external facts; only use evidence from TARGETED RESEARCH below.\n"
                "- Keep or add explicit uploaded source anchors in labels/parentheses.\n"
                "- Missing number => 'data pending from uploaded file' (never guess).\n"
            )
        brand_block = self._brand_prompt_block(theme, card_only=card_only)
        return f"""You are a senior consultant polishing slide {slide_index} of {total_slides} in a {theme} executive deck.
Your job is to SHARPEN this slide in place — do NOT change its shape or slide_type.

DECK TOPIC: {query}
{brand_block}
PLANNER HINT: {plan_row.get('assertion_title_hint', '')}
PLANNER DIRECTIVE: {plan_row.get('data_prompt_for_slide_author', '')}

CURRENT DRAFT (from holistic author — preserve shape, tighten content):
{json.dumps(slide_obj, ensure_ascii=False)}

TARGETED RESEARCH FOR THIS SLIDE ONLY (fresh snippets — use any NEW numbers the draft missed):
{slide_research or "(no additional research — keep draft numbers as-is; do NOT invent new ones.)"}
{source_lock}

POLISH RULES (apply each — return the tightened JSON object):
1. Title must be an ASSERTION headline with a number. If the current title is a topic label, rewrite it.
2. Every bullet / stat label / description MUST carry at least one hard number. Prefer two (fact + comparison).
3. Every stat label carries "source + year/date" anchor.
4. Keep slide_type EXACTLY as "{plan_row.get('slide_type', slide_obj.get('type', 'content'))}".
5. Do NOT add or remove bullets/stats/items/steps unless the count is below the schema minimum.
6. Keep language consultant-grade: CAGR, YoY, bps, TAM, NPV, payback. Kill "leverage", "synergies", "best-in-class".
7. If the draft already meets gates 1–3, return it unchanged.
8. {img_rule}

Return ONE valid JSON object only — same shape as the current draft, same slide_type. No markdown fences, no commentary."""

    # ── Compact / on-prem author helpers ──────────────────────────────────

    _COMPACT_SCHEMA_EXAMPLES: Dict[str, str] = {
        "title": '{"type":"title","title":"<assertion headline with number>","subtitle":"<10–18-word business tension>"}',
        "section": '{"type":"section","title":"<section label>","subtitle":"<one-line framing>"}',
        "closing": '{"type":"closing","title":"<CTA headline with number>","subtitle":"<specific next step + expected outcome>"}',
        "content": '{"type":"content","title":"<assertion headline with a number>","bullets":["<20-35 word bullet with $/%/year and source — e.g. Revenue rose 18% YoY to $4.2B in Q1 FY26 (Bloomberg Apr 2026)>","<20-35 word bullet with comparison — e.g. Operating margin expanded 220bps to 34.5%, outpacing sector avg of 28% (IBEF 2025)>","<20-35 word bullet with a hard number and context>","<20-35 word bullet with quantified insight>","<20-35 word bullet with forward-looking metric>"]}',
        "stats": '{"type":"stats","title":"<assertion headline with number>","stats":[{"value":"$47B","label":"Total addressable market by 2027, a 3x increase from $15.7B in 2021 (IBEF 2025)"},{"value":"22%","label":"Revenue CAGR 2023-28, fastest among emerging market peers (McKinsey Q1 2026)"},{"value":"480Cr","label":"Projected annual cost savings from automation, 40% above baseline (Deloitte 2025)"}]}',
        "quote": '{"type":"quote","title":"<topic headline>","quote":"<verbatim quote>","attribution":"<Name, Title, Org, Year>"}',
        "comparison": '{"type":"comparison","title":"<A vs B headline with number>","left":{"title":"Status Quo","bullets":["<20-35 word quantified bullet with source>","<20-35 word quantified bullet>","<20-35 word quantified bullet>"]},"right":{"title":"Proposed","bullets":["<20-35 word quantified bullet with source>","<20-35 word quantified bullet>","<20-35 word quantified bullet>"]}}',
        "two_column": '{"type":"two_column","title":"<headline with number>","left":{"title":"<left>","bullets":["<20-35 word bullet with number>","<20-35 word bullet with number>","<20-35 word bullet>"]},"right":{"title":"<right>","bullets":["<20-35 word bullet with number>","<20-35 word bullet with number>","<20-35 word bullet>"]}}',
        "timeline": '{"type":"timeline","title":"<headline with number>","steps":[{"title":"Q1 FY26","description":"<15-25 word milestone with quantified outcome and source>"},{"title":"Q3 FY26","description":"<15-25 word milestone with quantified outcome>"},{"title":"Q1 FY27","description":"<15-25 word milestone with quantified outcome>"},{"title":"Q1 FY28","description":"<15-25 word milestone with quantified outcome>"}]}',
        "numbered_list": '{"type":"numbered_list","title":"<headline with number>","items":[{"title":"<action verb + quantified deliverable>","description":"<20-30 word outcome with 2 numbers, payback period, and source citation>"},{"title":"<action + deliverable with number>","description":"<20-30 word outcome with comparison and source>"},{"title":"<action + deliverable with number>","description":"<20-30 word outcome with ROI and timeline>"},{"title":"<action + deliverable with number>","description":"<20-30 word outcome with metric>"}]}',
        "process_flow": '{"type":"process_flow","title":"<headline with number>","steps":[{"title":"Step 1","description":"<15-25 word measurable output with target metric and timeline>","icon":"gear"},{"title":"Step 2","description":"<15-25 word output with quantified improvement>","icon":"process"},{"title":"Step 3","description":"<15-25 word output with expected result and comparison>","icon":"check"},{"title":"Step 4","description":"<15-25 word output with final metric>","icon":"target"}]}',
        "icon_grid": '{"type":"icon_grid","title":"<headline with number>","items":[{"title":"<short title>","description":"<15-25 word data point with comparison and source citation>","icon":"growth"},{"title":"<short title>","description":"<15-25 word data point with number and context>","icon":"target"},{"title":"<short title>","description":"<15-25 word data point with metric and source>","icon":"shield"},{"title":"<short title>","description":"<15-25 word data point with quantified insight>","icon":"chart"}]}',
    }

    def _build_compact_slide_author_prompt(
        self,
        query: str,
        plan_row: Dict[str, Any],
        slide_research: str,
        slide_index: int,
        total_slides: int,
        card_only: bool,
        stricter: bool = False,
        raw_user_content: Optional[str] = None,
    ) -> str:
        """Short, type-specialised author prompt for compact (Ollama/local) LLMs.

        Includes ONE concrete schema example for the exact slide type, the
        per-slide research block, and a single line of numeric/source rules.
        Designed to fit generation + thinking inside ~3k tokens.
        """
        slide_type = (plan_row.get("slide_type") or "content").lower()
        example = self._COMPACT_SCHEMA_EXAMPLES.get(slide_type, self._COMPACT_SCHEMA_EXAMPLES["content"])
        hint = (plan_row.get("assertion_title_hint") or "")[:140]
        directive = (plan_row.get("data_prompt_for_slide_author") or "")[:220]
        img_line = (
            '' if card_only
            else '\n- Add "image_query": one short specific scene description (not "team meeting").'
        )
        # /no_think is honoured by qwen3-style models when present in the
        # user message (system-message variant is sometimes ignored by Ollama
        # Cloud — see local_llm._ollama_chat_body).
        base_preamble = (
            "/no_think\n"
            "OUTPUT JSON ONLY. No prose. No markdown fences. No <think> tags. "
            "Start with { and end with }. Do not explain.\n\n"
        )
        strict_preamble = base_preamble + (
            "STRICT: previous attempt failed to parse. Emit ONE compact JSON object — "
            "no leading/trailing whitespace, no commentary, no <think> block.\n\n"
            if stricter else ""
        )
        research_line = (
            f"\nRESEARCH (use these numbers; do NOT invent):\n{slide_research}\n"
            if slide_research else
            "\n(No research — if you don't know a number, write \"data pending\" instead of fabricating.)\n"
        )
        raw_block = ""
        if raw_user_content and raw_user_content.strip():
            # Compact provider author prompt — keep injected user content tight
            # so prompt+generation fit comfortably inside the reliable window.
            raw_cap = 1500
            raw_block = (
                "\nUSER CONTENT (authoritative — pull facts/phrasing for THIS slide from the section that matches "
                f"HEADLINE DIRECTION / FOCUS above):\n{raw_user_content[:raw_cap]}\n"
            )
        source_lock = ""
        if "uploaded://" in (slide_research or ""):
            source_lock = (
                "\nSOURCE LOCK:\n"
                "- Use ONLY facts present in RESEARCH below.\n"
                "- Do NOT add outside facts from memory/world knowledge.\n"
                "- If a number is missing, write 'data pending from uploaded file'.\n"
            )
        return f"""{strict_preamble}Write slide {slide_index}/{total_slides} of an executive deck.

TOPIC: {query}
SLIDE TYPE: {slide_type}
HEADLINE DIRECTION: {hint}
FOCUS: {directive}
{raw_block}{research_line}
{source_lock}
RULES:
- Title must be an ASSERTION with a number (not "Overview"/"Introduction").
- Every bullet / stat label / description has ≥1 hard number (%, $, ₹, ×, bps, year, CAGR).
- Stat labels include source + year (e.g. "IBEF 2024", "Reuters Apr 2026").
- Keep language tight: CAGR, YoY, NPV, payback, bps. Avoid "leverage", "best-in-class", "synergies".
- CRITICAL: Write DETAILED content. Each bullet/description MUST be 20-35 words. Do NOT write short 3-5 word bullets.
- Include 4-5 bullets for content slides, 3-4 stats for stats slides, 3-4 items for list/grid slides.
- Every text field should be a complete sentence or phrase with specific numbers, comparisons, and source citations.{img_line}

SCHEMA (fill these exact fields — keep "type" EXACTLY "{slide_type}"):
{example}

Return ONE JSON object only:"""

    def _fill_slide_from_research(
        self,
        plan_row: Dict[str, Any],
        research_results: List[Dict[str, Any]],
        card_only: bool,
    ) -> Dict[str, Any]:
        """When the LLM fails, build a non-empty slide from top research snippets.

        Beats the thin template fallback because real sources + titles land in
        the slide; downstream polish/validator can still reject it, but the
        user sees actual content instead of "data pending" placeholders.
        """
        stype = (plan_row.get("slide_type") or "content").lower()
        hint = (plan_row.get("assertion_title_hint") or "Key facts")[:160]

        # Grab up to 6 snippets with concrete text
        facts: List[Dict[str, str]] = []
        for r in research_results or []:
            txt = (r.get("snippet") or r.get("content") or "").strip()
            if not txt or len(txt) < 40:
                continue
            facts.append({
                "title": (r.get("title") or "")[:120],
                "date": (r.get("date") or "")[:30],
                "body": txt[:220],
            })
            if len(facts) >= 6:
                break

        def _src_tag(f: Dict[str, str]) -> str:
            t = f["title"].split(" - ")[0][:40]
            d = f["date"][:10] if f["date"] else ""
            return f" ({t}, {d})" if d else (f" ({t})" if t else "")

        out: Dict[str, Any] = {"type": stype, "title": hint}
        if stype in ("title", "section", "closing"):
            sub = facts[0]["body"][:120] if facts else "Key evidence summarised below."
            out["subtitle"] = sub + (_src_tag(facts[0]) if facts else "")
        elif stype == "quote" and facts:
            out["quote"] = facts[0]["body"][:200]
            out["attribution"] = (facts[0]["title"] or "Industry report") + (
                f", {facts[0]['date']}" if facts[0]["date"] else ""
            )
        elif stype == "stats":
            out["stats"] = [
                {"value": "—", "label": (f["body"][:50] + _src_tag(f))[:100]}
                for f in facts[:3]
            ] or [{"value": "—", "label": "Research pending"}]
        elif stype in ("numbered_list", "process_flow", "timeline"):
            key = "steps" if stype in ("process_flow", "timeline") else "items"
            out[key] = [
                {
                    "title": (f["title"] or f"Step {i+1}")[:60],
                    "description": (f["body"][:140] + _src_tag(f))[:200],
                    **({"icon": "insight"} if stype == "process_flow" else {}),
                }
                for i, f in enumerate(facts[:4])
            ] or [{"title": "Step 1", "description": "Research pending — add planner directive."}]
        elif stype == "icon_grid":
            out["items"] = [
                {"title": (f["title"] or f"Item {i+1}")[:40], "description": (f["body"][:120] + _src_tag(f))[:180], "icon": "insight"}
                for i, f in enumerate(facts[:3])
            ] or [{"title": "Pending", "description": "Research not available.", "icon": "insight"}]
        elif stype in ("comparison", "two_column"):
            halves = facts[:4] or []
            out["left"] = {
                "title": "Finding A",
                "bullets": [(h["body"][:120] + _src_tag(h))[:160] for h in halves[:2]] or ["Research pending"],
            }
            out["right"] = {
                "title": "Finding B",
                "bullets": [(h["body"][:120] + _src_tag(h))[:160] for h in halves[2:4]] or ["Research pending"],
            }
        else:  # content
            out["bullets"] = [
                (f["body"][:140] + _src_tag(f))[:200]
                for f in facts[:4]
            ] or ["Research pending — planner was unable to retrieve snippets for this slide."]

        if not card_only:
            out["image_query"] = f"Editorial photograph illustrating {hint[:80]}"
        return out

    def _collect_research_source_rows(self, all_results: List[List[Dict[str, Any]]], cap: int = 48) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen = set()
        for bucket in all_results:
            for r in bucket or []:
                url = (r.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                out.append({
                    "title": (r.get("title") or "")[:200],
                    "url": url[:500],
                    "date": (r.get("date") or "")[:40],
                })
                if len(out) >= cap:
                    return out
        return out

    def _strip_fences(self, text: str) -> str:
        s = (text or "").strip()
        m = re.search(r"```(?:text|markdown|md)?\s*([\s\S]*?)```", s, flags=re.IGNORECASE)
        if m:
            s = m.group(1).strip()
        return s

    async def _build_uploaded_content_brief(
        self,
        query: str,
        file_name: str,
        chunks: List[Dict[str, Any]],
    ) -> str:
        if not chunks:
            return ""

        sem = asyncio.Semaphore(5)
        # Compact providers: keep per-chunk summarisation tight to avoid long
        # generations that often time out or get cut by <think>-token overhead.
        chunk_tokens = 600 if self._is_compact_provider() else 1100

        async def _summarize_chunk(chunk: Dict[str, Any]) -> str:
            text = (chunk.get("text") or "")[:1800]
            if not text:
                return ""
            prompt = f"""You are extracting presentation intelligence from uploaded business documents.

TOPIC: {query}
SOURCE: {file_name}
CHUNK {chunk.get('chunk_id', '?')}:
{text}

STRICTNESS:
- Use ONLY facts present in CHUNK text. Do not infer, enrich, or add outside facts.
- Keep hard numbers exactly as written in CHUNK.
- If a section has no evidence in CHUNK, write "data pending from uploaded file".

Return concise markdown with exactly these sections:
SUMMARY:
- <2-3 bullets>

KEY_TERMS:
- <important business terms, entities, products, regulations>

BUSINESS_POINTS:
- <strategic implications, opportunities, decisions>

DATA_POINTS:
- <hard numbers with units and time references>

RISKS:
- <quantified or clearly stated risks>
"""
            async with sem:
                try:
                    raw = await self.ai.call_genai(prompt, temperature=0.0, max_tokens=chunk_tokens)
                except Exception:
                    raw = ""
            if not raw or raw.startswith("Error"):
                return ""
            cleaned = self._strip_fences(raw)
            return cleaned[:1400]

        summaries = await asyncio.gather(*[_summarize_chunk(c) for c in chunks])
        summaries = [s for s in summaries if s.strip()]

        if not summaries:
            fallback = "\n\n".join((c.get("text") or "")[:900] for c in chunks[:6] if c.get("text"))
            if not fallback.strip():
                return ""
            return (
                "INTELLIGENCE BRIEF — UPLOADED CONTENT\n\n"
                f"EXECUTIVE SUMMARY:\n- Derived directly from uploaded file: {file_name}\n\n"
                "KEY TERMS:\n- data pending\n\n"
                "BUSINESS POINTS:\n- data pending\n\n"
                f"RAW EXTRACTS:\n{fallback}"
            )

        merged = "\n\n".join(f"[CHUNK {i+1}]\n{s}" for i, s in enumerate(summaries[:18]))
        # Compact: shorter consolidation keeps the call inside the model's
        # reliable generation window.
        final_tokens = 1000 if self._is_compact_provider() else 2200
        final_prompt = f"""You are preparing an executive intelligence brief for a PowerPoint generator.

TOPIC: {query}
SOURCE FILE: {file_name}

CHUNK SUMMARIES:
{merged}

STRICT SOURCE POLICY:
- Use ONLY facts contained in CHUNK SUMMARIES.
- Do not introduce external facts, assumptions, or boilerplate numbers.
- Missing evidence must be written as "data pending from uploaded file".

Produce a professional brief that forces strong deck quality.
Return plain text with these sections and bullets only:

INTELLIGENCE BRIEF — UPLOADED CONTENT

EXECUTIVE SUMMARY:
- 3-5 bullets summarizing the most important storyline

KEY TERMS:
- domain/business terms and entities that should be highlighted in the deck

BUSINESS POINTS:
- strategic implications, decisions, opportunities, constraints

MARKET/FINANCIAL FACTS:
- [STAT] lines with hard numbers, units, and dates where available

RISKS & CONSTRAINTS:
- [RISK] lines with probability/impact/timeline when available

RECOMMENDED DECK STRUCTURE:
1. Executive Summary
2. Key Terms and Context
3. Core Business Points and Evidence
4. Recommendations and Execution Plan
5. Risks and Mitigations

PRIORITY SLIDE CONTENT:
- STATS slide focus
- COMPARISON slide focus
- NUMBERED_LIST slide focus
- PROCESS_FLOW slide focus
"""
        try:
            raw = await self.ai.call_genai(final_prompt, temperature=0.0, max_tokens=final_tokens)
            if raw and not raw.startswith("Error"):
                return self._strip_fences(raw)[:14000]
        except Exception:
            pass

        return (
            "INTELLIGENCE BRIEF — UPLOADED CONTENT\n\n"
            f"EXECUTIVE SUMMARY:\n- File processed: {file_name}\n\n"
            "KEY TERMS:\n- see chunk summaries\n\n"
            "BUSINESS POINTS:\n- see chunk summaries\n\n"
            f"CHUNK SUMMARIES:\n{merged[:9000]}"
        )

    async def process_stream(
        self,
        query: str,
        session_id: Optional[str] = None,
        slide_count: Optional[int] = None,
        theme: str = "aurora",
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        web_search_enabled: Optional[bool] = None,
        user_config: Optional[Dict[str, str]] = None,
    ):
        """Async generator: yields ``{{"event", "data"}}`` dicts, then a final result dict (no ``event`` key)."""
        thinking_steps: List[Dict[str, Any]] = []

        def emit_thinking(step_type: str, content: str, tool_name: str = None, tool_input: str = None):
            self._add_thinking(thinking_steps, step_type, content, tool_name, tool_input)
            step = {"type": step_type, "content": content}
            if tool_name:
                step["tool_name"] = tool_name
            if tool_input:
                step["tool_input"] = tool_input
            return {"event": "thinking", "data": step}

        if not session_id:
            session_id = str(uuid.uuid4())

        if slide_count is not None:
            try:
                slide_count = int(slide_count)
                slide_count = max(MIN_SLIDES, min(MAX_SLIDES, slide_count))
            except (TypeError, ValueError):
                slide_count = None

        theme = (theme or "aurora").lower()
        if theme not in {"aurora", "midnight", "professional", "modern", "dark", "vibrant", "consulting", "pwc"}:
            theme = "aurora"

        yield emit_thinking("thinking", f"Analyzing presentation request: {query[:200]}")

        agent_cfg = self._resolve_agent_config(user_config)
        do_search, search_provider, search_api_key, disabled_reason = self._resolve_web_search(web_search_enabled, agent_cfg)
        if search_provider == "free_ollama":
            search_client = ppt_ollama_free_search
            search_tool_name = "ollama_web_search"
            search_label = "Ollama free web search"
        elif search_provider == "free_duckduckgo":
            search_client = ppt_duckduckgo_free_search
            search_tool_name = "duckduckgo_web_search"
            search_label = "DuckDuckGo free web search"
        else:
            search_client = ppt_perplexity_search
            search_tool_name = "perplexity_search"
            search_label = "Perplexity"

        if disabled_reason:
            yield emit_thinking("observation", disabled_reason)

        compact = self._is_compact_provider()
        card_only = self._is_offline_or_ollama_provider()
        narrative_blueprint: Optional[Dict[str, str]] = None

        # ─── Rich-input detection ─────────────────────────────────────────
        # If the user pasted a long, structured input, keep the full content
        # verbatim as the primary authoring source and use a derived short
        # topic for places where the prompt needs a concise header (TOPIC
        # slot, search queries, logs). Without this, the planner/author see
        # only the distilled brief and lose most of the user's own text.
        is_rich_input = self._is_rich_query(query)
        raw_user_content: Optional[str] = query if is_rich_input else None
        short_topic: str = self._derive_short_topic(query) if is_rich_input else query
        user_sections: List[Dict[str, str]] = (
            self._extract_user_sections(query) if is_rich_input else []
        )
        if is_rich_input:
            yield emit_thinking(
                "observation",
                f"Rich user input detected ({len(query)} chars, {len(user_sections)} sections) — "
                "using it as primary source; each section will be represented on a slide.",
            )

        file_intelligence_brief = ""
        uploaded_chunks: List[Dict[str, Any]] = []
        uploaded_meta: Dict[str, Any] = {}
        has_uploaded_file = bool(file_content and (file_type or file_name))

        if has_uploaded_file:
            do_search = False
            label = (file_name or "uploaded file")[:160]
            yield emit_thinking(
                "tool_call",
                f"Extracting text from uploaded file: {label}",
                "file_ingest",
                label,
            )
            extracted_text, uploaded_meta = extract_uploaded_text(
                file_content=file_content or "",
                file_type=file_type,
                file_name=file_name,
            )
            if extracted_text:
                yield emit_thinking(
                    "observation",
                    "Uploaded file detected — web search disabled; generating deck from document intelligence.",
                )
                if bool(uploaded_meta.get("low_quality")):
                    yield emit_thinking(
                        "observation",
                        "Uploaded text extraction quality appears low (common with scanned/image-heavy PDFs). Deck will remain source-locked, but precision may be limited unless a searchable PDF is provided.",
                    )

                uploaded_chunks = chunk_text_for_parallel_processing(
                    extracted_text,
                    source_label=uploaded_meta.get("file_name") or (file_name or "uploaded_file"),
                )
                yield emit_thinking(
                    "tool_result",
                    f"Extracted {uploaded_meta.get('chars', 0)} chars and chunked into {len(uploaded_chunks)} parallel units",
                )

                if uploaded_chunks:
                    yield emit_thinking(
                        "tool_call",
                        "Parallel chunk distillation: summary, key terms, business points, and data facts",
                        "genai",
                        f"{len(uploaded_chunks)} chunks",
                    )
                    file_intelligence_brief = await self._build_uploaded_content_brief(
                        query=query,
                        file_name=uploaded_meta.get("file_name") or (file_name or "uploaded_file"),
                        chunks=uploaded_chunks,
                    )
                    if file_intelligence_brief:
                        yield emit_thinking(
                            "tool_result",
                            f"Built uploaded-content intelligence brief ({len(file_intelligence_brief)} chars)",
                        )
            else:
                reason = uploaded_meta.get("error") or "unknown extraction error"
                yield emit_thinking(
                    "observation",
                    f"Uploaded file could not be parsed: {reason}. Continuing with query-only generation.",
                )

        # ─── Phase 1: Topic-level pre-research (tiered, shared across deck) ──
        topic_results: List[Dict[str, Any]] = []
        if do_search:
            yield emit_thinking(
                "tool_call",
                f"Topic pre-research: tiered {search_label} (hour → day → week → month → evergreen)",
                search_tool_name,
                short_topic[:120],
            )
            try:
                topic_results = await search_client.research_topic(short_topic, api_key=search_api_key)
                yield emit_thinking(
                    "tool_result",
                    f"Collected {len(topic_results)} ranked snippets across freshness tiers",
                )
            except Exception as e:
                yield emit_thinking("tool_result", f"Pre-research error: {str(e)[:200]} — continuing without brief")
                topic_results = []

        # ─── Phase 2: Intelligence Brief (single distill; shared fact base) ──
        intelligence_brief = file_intelligence_brief or ""
        if topic_results:
            # Compact providers (Ollama Cloud / local) choke on long inputs — keep
            # the raw research block small so the distill prompt stays well under
            # the model's effective context limit.
            topic_char_budget = 3000 if compact else 7500
            raw_topic_block = format_research_for_prompt(topic_results, char_budget=topic_char_budget)
            yield emit_thinking("tool_call", "Distilling research into structured intelligence brief", "genai", "distill")
            try:
                intelligence_brief = await self._distill_research(query, raw_topic_block)
                if intelligence_brief and intelligence_brief.startswith("INTELLIGENCE BRIEF"):
                    yield emit_thinking(
                        "tool_result",
                        f"Brief built — {len(intelligence_brief)} chars of structured facts ([BREAKING]/[STAT]/[PLAYER]/…)",
                    )
                else:
                    yield emit_thinking("tool_result", "Brief fell back to raw research block")
            except Exception as e:
                yield emit_thinking("tool_result", f"Brief distill error: {str(e)[:200]}")
                intelligence_brief = raw_topic_block
        elif intelligence_brief:
            yield emit_thinking(
                "observation",
                "Using uploaded-file intelligence brief as the primary deck fact base.",
            )

        # LLM-designed narrative arc first (custom per request), keyword
        # scorer as fallback so the deck still flows when the detector fails.
        narrative_blueprint = None
        try:
            yield emit_thinking(
                "tool_call",
                "Detecting narrative arc from user content (intent-driven)",
                "genai",
                "arc_detect",
            )
            narrative_blueprint = await self._detect_narrative_arc_llm(
                query=short_topic,
                intelligence_brief=intelligence_brief or "",
                raw_user_content=raw_user_content or "",
            )
        except Exception:
            narrative_blueprint = None
        if not narrative_blueprint:
            narrative_blueprint = self._select_narrative_blueprint(
                query=query,
                intelligence_brief=intelligence_brief or "",
                has_uploaded_file=has_uploaded_file,
            )
            yield emit_thinking(
                "observation",
                f"Arc: keyword-fallback — {narrative_blueprint.get('name', 'evidence-first')} "
                f"({narrative_blueprint.get('sequence', '')})",
            )
        else:
            yield emit_thinking(
                "observation",
                f"Arc: custom LLM-designed — {narrative_blueprint.get('name', '')} "
                f"({narrative_blueprint.get('sequence', '')})",
            )

        # ─── Phase 3: Planner — provider-aware, retry ladder ────────────────
        # Non-compact (PwC GenAI etc.): try with brief → retry without brief.
        # Compact (Ollama Cloud / local): minimal-skeleton FIRST (highest hit
        #   rate on thinking-models like qwen3.x) → compact w/o brief → compact
        #   with trimmed brief only if one is available.
        # Output budget for compact is generous enough to absorb residual
        # <think> tokens that some Ollama Cloud models emit despite /no_think.
        planner_tokens = 4500 if compact else 6144

        async def _call_planner(prompt: str, temperature: float = 0.3) -> Dict[str, Any]:
            """Run one planner call. Returns parsed dict, or {'__raw': …} / {'__error': …}."""
            try:
                raw = await self.ai.call_genai(prompt, temperature=temperature, max_tokens=planner_tokens)
            except ValueError:
                raise
            except Exception as e:
                return {"__error": f"{e}"}
            if (raw or "").startswith("Error"):
                return {"__error": raw[:300], "__raw": (raw or "")[:400]}
            obj = _parse_json_object(raw)
            if obj is None:
                return {"__raw": (raw or "")[:500]}
            return obj

        # Each attempt: (label, prompt, temperature). Temperature varies across
        # compact retries so a deterministic empty/garbage output on tier 1 does
        # not repeat verbatim on tier 2/3.
        attempts: List[tuple] = []
        if compact:
            # Tier 1: ultra-minimal skeleton — ~700-char prompt, smallest possible
            # generation footprint. Most reliable on Ollama Cloud.
            attempts.append((
                "Planner [compact, minimal skeleton]: shortest reliable prompt",
                build_planner_prompt_minimal(
                    short_topic,
                    slide_count,
                    narrative_blueprint=narrative_blueprint,
                    raw_user_content=raw_user_content,
                ),
                0.3,
            ))
            # Tier 2: compact prompt, no brief (slightly richer; different temp
            # to break deterministic-failure cycles on Ollama Cloud).
            attempts.append((
                "Planner [compact, no brief]: slide count, types, hints, search queries",
                build_planner_prompt(
                    short_topic,
                    slide_count,
                    compact=True,
                    research_brief=None,
                    narrative_blueprint=narrative_blueprint,
                    raw_user_content=raw_user_content,
                ),
                0.55,
            ))
            # Tier 3: compact prompt with a trimmed brief — only if available.
            if intelligence_brief:
                attempts.append((
                    "Planner [compact, file brief]: concise planner with uploaded-content grounding",
                    build_planner_prompt(
                        short_topic,
                        slide_count,
                        compact=True,
                        research_brief=intelligence_brief[:1500],
                        narrative_blueprint=narrative_blueprint,
                        raw_user_content=raw_user_content,
                    ),
                    0.4,
                ))
        else:
            # Tier 1: full planner grounded in the brief
            attempts.append((
                "Planner [full]: grounded in brief, cross-slide metric threading",
                build_planner_prompt(
                    short_topic,
                    slide_count,
                    compact=False,
                    research_brief=intelligence_brief or None,
                    narrative_blueprint=narrative_blueprint,
                    raw_user_content=raw_user_content,
                ),
                0.3,
            ))
            # Tier 2: without brief (shorter prompt if the brief blew the context)
            attempts.append((
                "Planner [no brief]: retry without research injection",
                build_planner_prompt(
                    short_topic,
                    slide_count,
                    compact=False,
                    research_brief=None,
                    narrative_blueprint=narrative_blueprint,
                    raw_user_content=raw_user_content,
                ),
                0.45,
            ))

        plan_obj: Optional[Dict[str, Any]] = None
        last_preview = ""
        for label, prompt, temp in attempts:
            yield emit_thinking("tool_call", label, "ppt_planner", short_topic[:120])
            try:
                result = await _call_planner(prompt, temperature=temp)
            except ValueError as e:
                yield emit_thinking("tool_result", f"Configuration error: {str(e)}")
                yield {
                    "success": False, "query": query,
                    "response": f"AI service is not configured: {str(e)}",
                    "session_id": session_id,
                    "thinking_steps": [ThinkingStep(**s) for s in thinking_steps],
                }
                return
            if "__error" not in result and "__raw" not in result:
                plan_obj = result
                break
            last_preview = str(result.get("__raw") or result.get("__error") or "")[:200]
            yield emit_thinking("tool_result", f"Planner attempt failed. Preview: {last_preview[:160]}")

        if plan_obj is None:
            yield {
                "success": False,
                "query": query,
                "response": (
                    "The planner could not produce a valid deck plan after retries. "
                    "On Ollama Cloud this usually means a length/format issue — try a shorter topic, "
                    "specify a lower slide_count, or disable web search."
                ),
                "session_id": session_id,
                "thinking_steps": [ThinkingStep(**s) for s in thinking_steps],
            }
            return

        plan_rows = normalize_planner_output(plan_obj, slide_count)
        planner_meta = extract_planner_meta(plan_obj)
        if not plan_rows:
            yield emit_thinking("tool_result", "Planner output failed validation (title/closing or slide types)")
            yield {
                "success": False,
                "query": query,
                "response": "Deck plan validation failed. Please retry or specify slide_count explicitly.",
                "session_id": session_id,
                "thinking_steps": [ThinkingStep(**s) for s in thinking_steps],
            }
            return

        threaded_preview = ", ".join(planner_meta.get("threaded_metrics") or [])[:120]
        yield emit_thinking(
            "tool_result",
            f"Planner locked {len(plan_rows)} slides"
            + (f" — threading: {threaded_preview}" if threaded_preview else ""),
        )

        # ─── Phase 4: Author path split by provider ────────────────────────
        # Non-compact: one holistic LLM call writes the full deck (best quality).
        # Compact: skip holistic (Ollama 500s on long prompt + long gen); use
        # sequential per-slide author under Phase 5a instead.
        slides_data: List[Dict[str, Any]] = []
        holistic_tokens = 12000

        if not compact:
            yield {"event": "progress", "data": {"stage": "slides", "message": f"Authoring all {len(plan_rows)} slides in one pass (holistic)…"}}
            yield emit_thinking(
                "tool_call",
                f"Holistic author: writing complete {len(plan_rows)}-slide deck in a single LLM call",
                "genai",
                "holistic_author",
            )
            holistic_prompt = self._build_holistic_deck_prompt(
                short_topic,
                theme,
                plan_rows,
                planner_meta,
                intelligence_brief,
                card_only,
                narrative_blueprint,
                raw_user_content=raw_user_content,
            )
            try:
                holistic_raw = await self.ai.call_genai(holistic_prompt, temperature=0.3, max_tokens=holistic_tokens)
            except Exception as e:
                holistic_raw = f"Error: {e}"

            parsed = self._parse_slides_json(holistic_raw) if not str(holistic_raw).startswith("Error") else None
            if parsed:
                slides_data = parsed
                yield emit_thinking("tool_result", f"Holistic author returned {len(slides_data)} slides")
            else:
                yield emit_thinking(
                    "tool_result",
                    "Holistic author output could not be parsed — polish will author from fallbacks",
                )

        # ─── Phase 5: Per-slide parallel research + polish ─────────────────
        per_slide_results: List[List[Dict[str, Any]]] = [[] for _ in plan_rows]
        if do_search:
            yield emit_thinking(
                "tool_call",
                f"Parallel per-slide {search_label} (hour/day/week) for polish grounding",
                search_tool_name,
                f"{len(plan_rows)} slide batches",
            )
            sem = asyncio.Semaphore(6)

            async def _research_row(row: Dict[str, Any]) -> List[Dict[str, Any]]:
                fq_parts = [
                    query,
                    f"Slide {row['position']}: {row.get('assertion_title_hint', '')}",
                ] + list(row.get("per_slide_search_queries") or [])
                focus = "\n".join(p for p in fq_parts if p)
                async with sem:
                    return await search_client.research_slide_focus(focus, api_key=search_api_key)

            try:
                per_slide_results = await asyncio.gather(*[_research_row(r) for r in plan_rows])
            except Exception as e:
                yield emit_thinking("tool_result", f"Parallel search error: {str(e)[:200]}")
                per_slide_results = [[] for _ in plan_rows]

            total_hits = sum(len(x) for x in per_slide_results)
            yield emit_thinking("tool_result", f"Retrieved ~{total_hits} slide-scoped snippets")
        elif uploaded_chunks:
            yield emit_thinking(
                "tool_call",
                "Routing uploaded document chunks to slide-specific research contexts",
                "file_chunk_router",
                f"{len(uploaded_chunks)} chunks",
            )
            source_name = uploaded_meta.get("file_name") or (file_name or "uploaded_file")
            per_slide_results = []
            total_chunks = len(uploaded_chunks)
            window_size = 4
            for row in plan_rows:
                hint = " ".join(
                    [
                        row.get("assertion_title_hint", ""),
                        row.get("data_prompt_for_slide_author", ""),
                        " ".join(row.get("per_slide_search_queries") or []),
                    ]
                )

                # Relevance-driven candidates.
                chosen_ranked = choose_relevant_chunks(uploaded_chunks, query=query, slide_hint=hint, top_k=window_size)

                # Deterministic coverage window so each slide receives evidence
                # from different document regions instead of repeating first chunks.
                pos = max(1, int(row.get("position") or 1))
                start = int(((pos - 1) / max(1, len(plan_rows))) * max(1, total_chunks - 1))
                window = uploaded_chunks[start : start + window_size]
                if len(window) < window_size:
                    window = window + uploaded_chunks[: max(0, window_size - len(window))]

                merged: List[Dict[str, Any]] = []
                seen_ids = set()
                for c in chosen_ranked + window:
                    cid = int(c.get("chunk_id") or 0)
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    merged.append(c)
                    if len(merged) >= window_size:
                        break

                per_slide_results.append(chunks_to_research_rows(merged, source_name))

            total_hits = sum(len(x) for x in per_slide_results)
            yield emit_thinking("tool_result", f"Mapped {total_hits} uploaded chunk references across planned slides")

        research_sources = self._collect_research_source_rows(
            [topic_results] + per_slide_results if topic_results else per_slide_results
        )

        # ─── Phase 5a: Compact path — parallel per-slide author ────────────
        # Per-slide prompts are short; generation is bounded per slide.
        # Runs N concurrent LLM calls (bounded by semaphore) so 8–12 slides
        # complete in ~max(slide_time) instead of N×slide_time. Snapshots
        # stream out as each slide finishes (order may differ from index).
        if compact:
            slide_concurrency = int(os.getenv("PPT_COMPACT_AUTHOR_CONCURRENCY", "3"))
            slide_concurrency = max(1, min(slide_concurrency, 6))
            yield {"event": "progress", "data": {"stage": "slides", "message": f"Authoring {len(plan_rows)} slides in parallel (compact LLM, {slide_concurrency} concurrent)…"}}
            author_tokens = 3200
            slides_data = [None] * len(plan_rows)  # pre-allocated, filled by index
            compact_author_sem = asyncio.Semaphore(slide_concurrency)

            async def _author_one_compact(i: int, row: Dict[str, Any]) -> tuple:
                """Author a single slide and return (i, slide_obj, log_messages).

                Log messages are buffered (not yielded) because this runs inside
                a parallel task; the caller drains them when the task completes.
                """
                idx = i + 1
                logs: List[tuple] = []  # list of (kind, message) for emit_thinking
                raw_block = format_research_for_prompt(per_slide_results[i], char_budget=1500) if do_search else ""
                logs.append((
                    "tool_call",
                    f"Authoring slide {idx}/{len(plan_rows)} ({row.get('slide_type')})",
                    "genai",
                    (row.get("assertion_title_hint") or "")[:100],
                ))

                async with compact_author_sem:
                    prompt = self._build_compact_slide_author_prompt(
                        short_topic, row, raw_block, idx, len(plan_rows), card_only,
                        stricter=False, raw_user_content=raw_user_content,
                    )
                    try:
                        raw_slide = await self.ai.call_genai(prompt, temperature=0.3, max_tokens=author_tokens)
                    except Exception as e:
                        raw_slide = f"Error: {e}"
                    slide_obj = self._parse_single_slide_object(raw_slide) if not str(raw_slide).startswith("Error") else None

                    if not slide_obj:
                        preview = (str(raw_slide) or "").strip().replace("\n", " ")[:200]
                        diagnosis = "empty (think tokens consumed budget?)" if not preview else f"preview: {preview}"
                        logs.append((
                            "tool_result",
                            f"Slide {idx}: first parse failed — {diagnosis} — retrying with stricter prompt",
                        ))
                        prompt2 = self._build_compact_slide_author_prompt(
                            short_topic, row, raw_block, idx, len(plan_rows), card_only,
                            stricter=True, raw_user_content=raw_user_content,
                        )
                        try:
                            raw_slide2 = await self.ai.call_genai(prompt2, temperature=0.55, max_tokens=author_tokens)
                        except Exception as e:
                            raw_slide2 = f"Error: {e}"
                        slide_obj = self._parse_single_slide_object(raw_slide2) if not str(raw_slide2).startswith("Error") else None

                if not slide_obj:
                    if user_sections:
                        slide_obj = self._fallback_slide_from_plan(
                            short_topic, row, card_only, user_sections=user_sections,
                        )
                        logs.append(("tool_result", f"Slide {idx}: both LLM attempts failed — filled from user-provided content section"))
                    else:
                        slide_obj = self._fill_slide_from_research(row, per_slide_results[i], card_only)
                        logs.append(("tool_result", f"Slide {idx}: both LLM attempts failed — filled from research snippets"))
                else:
                    logs.append(("tool_result", f"Slide {idx}: draft ready"))

                slide_obj["type"] = row.get("slide_type", slide_obj.get("type", "content"))
                slide_obj["layout_variant"] = row.get("layout_variant", "default")
                if not (slide_obj.get("title") or "").strip():
                    slide_obj["title"] = (row.get("assertion_title_hint") or "Untitled slide")[:140]
                if card_only:
                    slide_obj.pop("image_query", None)
                return (i, slide_obj, logs)

            author_tasks = [asyncio.create_task(_author_one_compact(i, r)) for i, r in enumerate(plan_rows)]
            for coro in asyncio.as_completed(author_tasks):
                i, slide_obj, logs = await coro
                idx = i + 1
                for log in logs:
                    if len(log) == 4:
                        yield emit_thinking(log[0], log[1], log[2], log[3])
                    else:
                        yield emit_thinking(log[0], log[1])
                slides_data[i] = slide_obj
                try:
                    snap = slide_dict_to_preview_payload(slide_obj, idx, theme=theme)
                    yield {
                        "event": "ppt_slide_snapshot",
                        "data": {
                            "slide_index": idx,
                            "slide_type": slide_obj.get("type", ""),
                            "title": slide_obj.get("title", "")[:200],
                            "mime": snap["mime"],
                            "image": snap["image"],
                        },
                    }
                except Exception:
                    pass
        else:
            # ─── Phase 5b: Non-compact path — parallel polish of holistic draft ──
            # Ensure we have a draft slide per plan row (fallback for parse failure).
            if len(slides_data) < len(plan_rows):
                for i in range(len(slides_data), len(plan_rows)):
                    slides_data.append(self._fallback_slide_from_plan(
                        short_topic, plan_rows[i], card_only, user_sections=user_sections,
                    ))
            elif len(slides_data) > len(plan_rows):
                slides_data = slides_data[: len(plan_rows)]

            # Align slide_types to the plan (holistic author occasionally drifts).
            for i, row in enumerate(plan_rows):
                if slides_data[i].get("type") != row.get("slide_type"):
                    slides_data[i]["type"] = row.get("slide_type", slides_data[i].get("type", "content"))
                slides_data[i]["layout_variant"] = row.get("layout_variant", "default")
                if card_only:
                    slides_data[i].pop("image_query", None)

            yield emit_thinking(
                "tool_call",
                f"Parallel slide polish — sharpen titles, enforce numeric density and source citation",
                "genai",
                f"{len(slides_data)} polish tasks",
            )

            polish_tokens = 2000
            polish_sem = asyncio.Semaphore(5)

            async def _polish_one(i: int) -> tuple:
                row = plan_rows[i]
                draft = slides_data[i]
                raw_block = format_research_for_prompt(per_slide_results[i], char_budget=2600) if do_search else ""
                prompt = self._build_slide_polish_prompt(
                    query, theme, row, draft, raw_block, i + 1, len(plan_rows), card_only,
                )
                async with polish_sem:
                    try:
                        raw = await self.ai.call_genai(prompt, temperature=0.25, max_tokens=polish_tokens)
                    except Exception as e:
                        raw = f"Error: {e}"
                polished = self._parse_single_slide_object(raw) if not str(raw).startswith("Error") else None
                return i, polished

            tasks = [asyncio.create_task(_polish_one(i)) for i in range(len(slides_data))]

            for coro in asyncio.as_completed(tasks):
                i, polished = await coro
                idx = i + 1
                if polished:
                    polished["type"] = plan_rows[i].get("slide_type", polished.get("type", "content"))
                    if card_only:
                        polished.pop("image_query", None)
                    slides_data[i] = polished
                    yield emit_thinking("tool_result", f"Slide {idx}: polished")
                else:
                    yield emit_thinking("tool_result", f"Slide {idx}: polish skipped — keeping holistic draft")

                try:
                    snap = slide_dict_to_preview_payload(slides_data[i], idx, theme=theme)
                    yield {
                        "event": "ppt_slide_snapshot",
                        "data": {
                            "slide_index": idx,
                            "slide_type": slides_data[i].get("type", ""),
                            "title": slides_data[i].get("title", "")[:200],
                            "mime": snap["mime"],
                            "image": snap["image"],
                        },
                    }
                except Exception:
                    pass

        if len(slides_data) > MAX_SLIDES:
            slides_data = slides_data[:MAX_SLIDES]

        # ─── Phase 6: Validate → corrective retry (non-compact only) ───────
        is_valid, flow_issues = self._validate_slide_flow(slides_data, query)
        if not is_valid and flow_issues and compact:
            yield emit_thinking(
                "observation",
                f"Flow check: {'; '.join(flow_issues[:3])} — compact LLM, corrective pass skipped",
            )
        if not is_valid and flow_issues and not compact:
            yield emit_thinking(
                "observation",
                f"Flow check failed: {'; '.join(flow_issues[:3])} — running one corrective pass",
            )
            corrective = self._build_corrective_prompt(
                query,
                slides_data,
                flow_issues,
                slide_count,
                theme,
                intelligence_brief,
                card_only,
                narrative_blueprint,
            )
            try:
                corr_raw = await self.ai.call_genai(
                    corrective, temperature=0.25, max_tokens=holistic_tokens,
                )
                corr_parsed = self._parse_slides_json(corr_raw)
                if corr_parsed and len(corr_parsed) >= 2:
                    # Align to plan types again.
                    fixed = corr_parsed[: len(plan_rows)]
                    while len(fixed) < len(plan_rows):
                        fixed.append(self._fallback_slide_from_plan(
                            short_topic, plan_rows[len(fixed)], card_only, user_sections=user_sections,
                        ))
                    for i, row in enumerate(plan_rows):
                        if fixed[i].get("type") != row.get("slide_type"):
                            fixed[i]["type"] = row.get("slide_type", fixed[i].get("type", "content"))
                        if card_only:
                            fixed[i].pop("image_query", None)
                    slides_data = fixed
                    yield emit_thinking("tool_result", "Corrective pass applied — flow restored")
                    # Re-emit snapshots so the live preview reflects the corrected deck.
                    for i, s in enumerate(slides_data):
                        try:
                            snap = slide_dict_to_preview_payload(s, i + 1, theme=theme)
                            yield {
                                "event": "ppt_slide_snapshot",
                                "data": {
                                    "slide_index": i + 1,
                                    "slide_type": s.get("type", ""),
                                    "title": s.get("title", "")[:200],
                                    "mime": snap["mime"],
                                    "image": snap["image"],
                                },
                            }
                        except Exception:
                            pass
                else:
                    yield emit_thinking("tool_result", "Corrective pass did not parse — keeping polished draft")
            except Exception as e:
                yield emit_thinking("tool_result", f"Corrective pass error: {str(e)[:200]}")

        # ─── Phase 7: Parallel slide validation & polish ───────────────────
        # LLM validates each content slide in parallel: fixes text overflow,
        # thin content, unprofessional language, and missing fields.
        # Skipped for compact providers — the compact author already attempts
        # strict output and an extra N×LLM passes on Ollama Cloud routinely
        # pushes the run over the agent stream timeout.
        if compact:
            yield emit_thinking(
                "observation",
                "Compact LLM — skipping per-slide validation/polish to stay within stream timeout.",
            )
            # Still apply the deterministic content-minimum guard so empty
            # bullets/items don't ship.
            slides_data = [self._ensure_slide_minimum_content(s) for s in slides_data]
        else:
            yield emit_thinking(
                "tool_call",
                "Parallel slide validation — checking text fit, content quality, professionalism",
                "genai",
                f"{len(slides_data)} validation tasks",
            )
            slides_data, fixed_count = await self._validate_and_fix_slides(
                slides_data, emit_thinking, thinking_steps,
            )
            yield emit_thinking(
                "tool_result",
                f"Validation complete — {fixed_count}/{len(slides_data)} slides improved",
            )

        if card_only:
            for s in slides_data:
                if isinstance(s, dict) and "image_query" in s:
                    s.pop("image_query", None)
            yield emit_thinking(
                "observation",
                "Offline / Ollama LLM — stock images skipped; brand cards and shapes only.",
            )
            images: List[Optional[str]] = [None] * len(slides_data)
            images_found = 0
        else:
            yield emit_thinking("tool_call", "Image search batch for slides", "image_search", str(len(slides_data)))
            image_queries = []
            slide_titles = []
            for slide in slides_data:
                img_query = slide.get("image_query", "")
                if not img_query:
                    img_query = slide.get("title", query) + " professional photo"
                image_queries.append(img_query)
                slide_titles.append(slide.get("title", ""))
            images = await search_images_batch(image_queries, slide_titles)
            images_found = sum(1 for img in images if img is not None)
            yield emit_thinking("tool_result", f"Images resolved: {images_found}/{len(slides_data)}")

        yield emit_thinking("tool_call", "Building .pptx presentation file", "ppt_builder", f"theme={theme}")
        try:
            _filepath, filename = build_pptx(slides_data, theme, images)
        except Exception as e:
            yield emit_thinking("tool_result", f"PPT build error: {str(e)}")
            yield {
                "success": False,
                "query": query,
                "response": f"Failed to build the PowerPoint file: {str(e)}",
                "session_id": session_id,
                "thinking_steps": [ThinkingStep(**s) for s in thinking_steps],
            }
            return

        yield emit_thinking("tool_result", f"Presentation saved: {filename}")

        download_url = f"/api/ppt-generator/download/{filename}"
        slide_titles_out = [s.get("title", "") for s in slides_data]
        summary_lines = [f"**Slide {i+1}:** {t}" for i, t in enumerate(slide_titles_out) if t]
        summary = "\n".join(summary_lines)
        visual_line = (
            "**Visual style:** Brand-themed layout — cards, icons, typography (no stock photos).\n\n"
            if card_only
            else f"**Images:** {images_found} relevant images included\n\n"
        )
        src_line = ""
        if research_sources:
            if has_uploaded_file and not do_search:
                src_line = f"\n**Sources indexed:** {len(research_sources)} extracted references from uploaded content chunks.\n"
            else:
                src_line = f"\n**Sources indexed:** {len(research_sources)} URLs from live research (see slide copy for citations).\n"
        response_text = (
            f"Your presentation **\"{slides_data[0].get('title', 'Presentation')}\"** is ready!\n\n"
            f"**Slides ({len(slides_data)} total):**\n{summary}\n\n"
            f"**Theme:** {theme.capitalize()}\n"
            f"{src_line}{visual_line}"
            f"Click the download button below to get your .pptx file."
        )

        yield {
            "success": True,
            "query": query,
            "response": response_text,
            "download_url": download_url,
            "file_name": filename,
            "slide_count": len(slides_data),
            "session_id": session_id,
            "thinking_steps": [ThinkingStep(**s) for s in thinking_steps],
            "research_sources": research_sources or None,
        }

    async def process(
        self,
        query: str,
        session_id: Optional[str] = None,
        slide_count: Optional[int] = None,
        theme: str = "aurora",
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        web_search_enabled: Optional[bool] = None,
        user_config: Optional[Dict[str, str]] = None,
    ) -> PPTGeneratorResponse:
        final: Optional[Dict[str, Any]] = None
        async for item in self.process_stream(
            query, session_id=session_id, slide_count=slide_count,
            theme=theme,
            file_content=file_content,
            file_type=file_type,
            file_name=file_name,
            web_search_enabled=web_search_enabled,
            user_config=user_config,
        ):
            if isinstance(item, dict) and item.get("event"):
                continue
            final = item
        if not final:
            return PPTGeneratorResponse(
                success=False,
                query=query,
                response="Presentation generation produced no result.",
                session_id=session_id or str(uuid.uuid4()),
                thinking_steps=[],
            )
        try:
            return PPTGeneratorResponse.model_validate(final)
        except Exception:
            return PPTGeneratorResponse(
                success=bool(final.get("success", False)),
                query=final.get("query", query),
                response=final.get("response", ""),
                download_url=final.get("download_url"),
                file_name=final.get("file_name"),
                slide_count=int(final.get("slide_count") or 0),
                session_id=final.get("session_id") or session_id,
                thinking_steps=final.get("thinking_steps") or [],
                research_sources=final.get("research_sources"),
            )

    async def _distill_research(self, query: str, raw_context: str) -> str:
        """Call LLM to convert raw Perplexity snippets into a structured
        intelligence brief the outline LLM can cite directly in slides.
        Heavily biased toward extracting HARD NUMBERS — the downstream deck
        is graded on numeric density, not prose fluency.
        """
        from datetime import datetime
        today_str = datetime.now().strftime("%B %d, %Y")
        prompt = f"""You are a senior strategy consultant and research analyst preparing a briefing for a C-suite PowerPoint deck.

TODAY'S DATE: {today_str}
PRESENTATION TOPIC: {query}

RAW WEB RESEARCH (grouped by freshness — LAST 24 HOURS and THIS WEEK sections are the most recent and MUST take precedence when sources conflict):
{raw_context}

FRESHNESS MANDATE: the raw research is grouped by how recent it is. When extracting facts:
• LAST 24 HOURS items → tag these with [BREAKING] instead of [STAT]/[INSIGHT]; they are the deck's news hooks.
• THIS WEEK items → prefer these over older numbers when the metric is the same.
• If an evergreen source and a breaking source give different numbers for the same metric, use the breaking source and note "(updated {today_str})".
• Every extracted line MUST include a date anchor in this format: "as of <Mon YYYY>" or "(updated <date>)" so the downstream deck can cite currency.

Extract MAXIMUM numeric content. Every [STAT], [INSIGHT], [PLAYER], [RISK], and [BREAKING] entry MUST contain at least one hard number. Do not paraphrase into generalities. Preserve exact figures, units, dates, and attributions from the raw research. If the source gives a number, keep it verbatim.

Target density: ≥15 [STAT] lines, ≥5 [PLAYER] lines, ≥5 [INSIGHT] lines, ≥3 [RISK] lines, ≥2 [QUOTE] lines. Pull more if available.

Return ONLY this structured block (no preamble, no commentary):

LAST 24 HOURS / BREAKING (extract every news-hook from the LAST 24 HOURS section of the raw research — earnings, announcements, deals, regulatory moves, launches):
- [BREAKING] <exact event with date & figure> — source: <org>, <YYYY-MM-DD>
- [BREAKING] ...

MARKET SIZING & GROWTH METRICS (at least 15 lines — cover TAM, SAM, SOM, CAGR, YoY growth, unit volumes, penetration %, segment shares):
- [STAT] <exact figure with unit> — <what it measures> | source: <org/report> | year: <YYYY>
- [STAT] ...

FINANCIAL & OPERATIONAL METRICS (margins, revenue, OpEx, CAC, LTV, cycle times, NPS, defect rates):
- [STAT] <figure> — <metric & comparison, e.g. "+220bps vs. industry avg"> | source: ... | year: ...
- [STAT] ...

COMPETITIVE LANDSCAPE & KEY PLAYERS (each line needs at least one number — share %, revenue, headcount, growth):
- [PLAYER] <company name> — <market share %, revenue $X, growth N% YoY, or named action with $ or count>
- [PLAYER] ...

TRENDS & STRATEGIC INSIGHTS (each MUST quantify the "so what"):
- [INSIGHT] <specific trend with number> → implication: <quantified business consequence, e.g. "opens $1.1B addressable segment">
- [INSIGHT] ...

RISKS & CHALLENGES (quantify probability, $ exposure, or affected volume):
- [RISK] <specific risk> — probability: <N% if known>, impact: <$X or count>, timeline: <when>
- [RISK] ...

REGULATORY & COMPLIANCE CONTEXT (specific rules, deadlines, penalties):
- [REG] <rule/standard name> — <effective date, applies to whom, penalty or requirement>

VERBATIM QUOTES (attribution is mandatory):
- [QUOTE] "<exact quote>" — <Full Name, Title, Organisation, Year>

RECOMMENDED DECK STRUCTURE (4–5 sections as assertion headlines with numbers):
1. <Section title with a number, e.g. "$47B TAM by 2027 — First-Mover Window Closes in 18 Months">
2. ...

PRIORITY SLIDE CONTENT:
- STATS slide: list the 4 most important [STAT] values to showcase, each with its comparison anchor.
- COMPARISON slide: <left> vs. <right> — 3–4 quantified differentiators per side (margin, cycle time, cost, retention).
- NUMBERED_LIST slide: top 4 strategic moves; each with quantified scope + expected financial outcome + payback.
- PROCESS_FLOW slide: 4 operational steps with measurable outputs at each stage."""

        # Compact providers: keep the brief short — long generations + thinking
        # tokens are the main failure mode on Ollama Cloud.
        distil_tokens = 1200 if self._is_compact_provider() else 2200
        try:
            distilled = await self.ai.call_genai(prompt, temperature=0.1, max_tokens=distil_tokens)
            if distilled.startswith("Error") or len(distilled.strip()) < 80:
                return raw_context
            return (
                "INTELLIGENCE BRIEF — USE THESE EXACT FACTS IN THE SLIDES:\n\n"
                + distilled.strip()
            )
        except Exception:
            return raw_context

    def _build_outline_prompt(self, query: str, slide_count: Optional[int], theme: str,
                               research_context: str = "") -> str:
        count_instruction = (
            f"Create exactly {slide_count} slides."
            if slide_count
            else "Create 10–14 slides for a full presentation, or 6–8 for a brief one."
        )

        if self._is_compact_provider():
            return self._build_outline_prompt_compact(
                query, count_instruction, theme, research_context,
            )

        research_block = ""
        research_mandate = ""
        if research_context:
            research_block = f"\n\n{research_context}\n"
            from datetime import datetime
            today_str = datetime.now().strftime("%B %d, %Y")
            research_mandate = f"""

TODAY'S DATE: {today_str}. Treat every date anchor in the brief as current-relative.

RESEARCH MANDATE (non-negotiable — the deck is graded on this):
- FRESHNESS FIRST: [BREAKING] entries (last 24 hours) are the deck's most valuable currency. If any exist, dedicate at least one slide (stats or content) to them, and use them in the opening title/subtitle where possible so the deck opens with news the audience hasn't yet seen.
- When the brief offers both a recent and older figure for the same metric, always cite the recent one and label it "(as of <Mon YYYY>)" or "(updated <date>)".
- Every stats slide MUST pull values from [STAT] / [BREAKING] entries. Copy exact figures with units. Labels MUST cite source + year (e.g. "IBEF 2024", "Reuters {today_str}").
- Quote slide MUST use a [QUOTE] verbatim with full attribution from the brief.
- Every content bullet MUST cite at least one number from [BREAKING], [STAT], [INSIGHT], [PLAYER], or [RISK]. No fabricated numbers. Use TWO numbers per bullet where available (fact + comparison).
- Section structure follows RECOMMENDED DECK STRUCTURE from the brief.
- Numbered_list items come from PRIORITY SLIDE CONTENT recommendations and MUST include scope figure + outcome figure + payback/timeline.
- Include at least one slide that surfaces [RISK] entries (quantified) and one that surfaces [REG] entries if present.
- Do NOT reference any fact older than the brief's oldest source without a specific reason; the audience is paying for CURRENT intelligence.
- The intelligence brief is your PRIMARY source. Your own knowledge is a fallback ONLY for gaps the brief doesn't cover."""

        brand_block = self._brand_prompt_block(theme, card_only=False)
        return f"""You are a McKinsey/BCG-calibre senior consultant and presentation strategist. \
Your task is to write the complete content for an executive-grade 16:9 PowerPoint deck.

TOPIC / REQUEST: {query}{research_block}
{brand_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENTERPRISE CONTENT STANDARDS — follow every rule below:

SLIDE TITLES must be ASSERTION HEADLINES — they state the conclusion, not the topic.
  ✗ WEAK  : "Market Overview"
  ✓ STRONG: "Market Growing at 23% CAGR — First-Mover Window Closes in 18 Months"
  ✗ WEAK  : "Challenges"
  ✓ STRONG: "Three Structural Barriers Account for 78% of Stalled Deployments"

NUMERIC DENSITY MANDATE — this is the #1 quality gate:
  ≥90% of bullets, stat labels, and item descriptions MUST contain at least one hard number.
  Hard numbers mean: percentages (34%), currency ($4.2B, ₹480Cr, €120M), multiples (3×), counts (50 pilot sites),
  basis points (180bps), time horizons (18 months), year anchors (FY24, 2027), growth rates (34% YoY, 22% CAGR),
  ranges ($2–3B), comparisons (+8pp vs. baseline). Prose-only bullets are rejected.
  Prefer TWO numbers per bullet where possible — one establishes the fact, one gives the comparison.

BULLET POINTS must follow the Situation → Insight → Implication (SII) framework AND carry numbers.
  Every bullet must contain: a specific data point + its strategic meaning + a quantified comparison or implication.
  ✗ WEAK  : "Revenue increased last year"
  ✓ STRONG: "FY24 revenue grew 34% YoY to $4.2B — outpacing category growth of 12%, signalling durable demand shift worth $1.1B in expansion headroom"
  ✗ WEAK  : "Customers prefer digital channels"
  ✓ STRONG: "72% of enterprise buyers now shortlist vendors digitally before any sales contact, compressing top-of-funnel windows by 40% and cutting field-sales headcount requirements by ~120 FTEs"
  ✗ WEAK  : "Operating costs went up"
  ✓ STRONG: "OpEx rose 18% YoY to $2.3B in FY24 vs. 6% revenue growth — 220bps margin erosion tracing to cloud infra (+$340M) and compliance labour (+$180M)"

CRITICAL-INFORMATION CHECKLIST — the deck as a whole MUST include every applicable item below:
  □ Market size: TAM with source and year anchor (e.g. "$47B by 2027, IBEF 2024")
  □ Market growth rate: CAGR with time window (e.g. "22% CAGR 2023–28")
  □ Named competitors or players with their specific market share / position
  □ At least ONE verbatim quote with full attribution (name, title, organisation, year)
  □ Financial impact of the recommendation: NPV, payback period, or EBITDA delta
  □ Time horizon for execution (months/quarters) and key milestones with dates
  □ Quantified risks — probability or impact where known (e.g. "30% probability, $50M exposure")
  □ Regulatory/compliance context when relevant (specific rules, deadlines)
  □ Comparison benchmark (industry average, peer performance, prior period)

STATS slides: aim for 3–4 stat cards per slide. Every label MUST carry comparison context AND a time or source anchor.
  ✗ WEAK  : value="94%", label="Accuracy"
  ✓ STRONG: value="94%", label="AI diagnostic accuracy — +8pp vs. specialist baseline (NEJM 2024)"
  ✓ STRONG: value="$190B", label="India apparel TAM by 2027 — 3× 2019 levels (IBEF)"
  ✓ STRONG: value="42 days", label="Avg sales cycle in FY24 — down from 71 days (−41%) in FY22"
  Pick values that span dimensions: size (TAM), growth (CAGR), efficiency (cycle time / margin), quality (NPS / defect rate).

NUMBERED LIST items: title = specific action verb + quantified deliverable; description MUST have ≥2 numbers (scope + outcome).
  ✗ WEAK  : title="Improve supply chain", description="Make supply chain better"
  ✓ STRONG: title="Digitise 240 tier-2 suppliers across 6 states by Q2 FY27", description="Cuts lead time 35% (45→29 days), unlocks ₹480Cr working capital savings annually, payback 14 months"

PROCESS FLOW steps: description = the measurable output of that step. Include counts, thresholds, or KPI values.
  ✗ WEAK  : description="Do onboarding"
  ✓ STRONG: description="Onboard 50 pilot artisans across 4 districts in 90 days; baseline defect rate <4%, throughput ≥120 units/day"

ICON GRID items: description MUST have one hard data point + comparison or source.
  ✗ WEAK  : description="Good for business"
  ✓ STRONG: description="Cooperative model lowers entry cost 60% vs. direct factory ownership; 180bps margin uplift vs peers"

COMPARISON slides: frame a clear strategic tension with a recommendation implied.
  Left/right titles should be opposing positions (e.g. "Status Quo" vs. "Proposed Model").
  Each bullet should highlight a dimension where the difference is quantified or decisive.

NARRATIVE FLOW — the deck must tell a cohesive business story where EVERY slide advances one argument:
    Decide flow from the user query + supplied content first; do not force a fixed slide-position template.
    Use this as an example business arc only when it fits: Title -> Context -> Evidence -> Strategic Response -> Execution -> Risks -> CTA.
    You may reorder, merge, or skip beats to match topic complexity, audience, and available facts while keeping title first and closing last.

SLIDE-TO-SLIDE COHERENCE (non-negotiable — the deck is graded on this):
  - A reader skimming ONLY the slide titles must understand the full argument as a connected narrative — each title logically follows from the previous one.
  - Every slide must be DIRECTLY relevant to the TOPIC stated above. No generic filler slides ("About Us", "Agenda", "Key Takeaways" with no substance). If a slide does not serve the user's specific request, replace it with one that does.
  - Each slide answers ONE clear question the audience would have at that point: Why now? How big is this? What should we do? How exactly? What are the risks? What's the next step?
  - Adjacent slides must share at least one connecting thread — a metric, entity, or theme introduced in slide N must be referenced, compared, or acted upon in slide N+1 or N+2.
  - Do NOT front-load all stats slides together or all content slides together — INTERLEAVE evidence types (stats → content → comparison → process) to maintain audience engagement.

LANGUAGE REGISTER — write at C-suite level:
  Use: CAGR, YoY, basis points, run-rate, TAM/SAM/SOM, headroom, white space, payback period, NPV, EBITDA margin.
  Avoid: "leveraging synergies", "best-in-class", "innovative solutions", "moving the needle", vague superlatives.
{research_mandate}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRUCTURE:
1. {count_instruction}
2. First slide: type "title" — subtitle must frame the business case tension in one sentence.
3. Last slide: type "closing" — subtitle should be a crisp call-to-action, not just "Thank You".
4. Vary slide types: 25% content, 15% numbered_list, 15% process_flow, 10% icon_grid, 10% stats,
   10% comparison or two_column, 5% timeline, 5% quote, 5% section dividers.
   Every deck MUST include ≥1 numbered_list AND ≥1 process_flow.
5. Every slide MUST have "image_query": a cinematic, specific scene description
   (e.g. "Indian artisan weaving silk sari in natural light workshop" — never just "team" or "people").
6. TOPIC ANCHORING: Before generating each slide, mentally verify: "Does this slide directly serve the
   user's request about the TOPIC stated above?" If you cannot draw a direct line from the slide to the
   topic, REPLACE it with one that advances the argument. Every bullet, stat, and description must be
   about the specific subject the user asked for — not about a neighbouring topic.
7. LOGICAL ORDERING: Derive ordering from the request and evidence. Maintain a clear cause-to-decision progression, but do not force a fixed sequence when another order better fits the topic.

ALLOWED SLIDE SCHEMAS:
- "title"        : {{"type":"title","title":str,"subtitle":str,"image_query":str}}
- "section"      : {{"type":"section","title":str,"subtitle":str,"image_query":str}}
- "closing"      : {{"type":"closing","title":str,"subtitle":str,"image_query":str}}
- "content"      : {{"type":"content","title":str,"bullets":[str,...](4-5 items),"image_query":str}}
- "stats"        : {{"type":"stats","title":str,"stats":[{{"value":str,"label":str}},...](2-4),"image_query":str}}
- "quote"        : {{"type":"quote","title":str,"quote":str,"attribution":str,"image_query":str}}
- "comparison"   : {{"type":"comparison","title":str,"left":{{"title":str,"bullets":[str,...]}},"right":{{"title":str,"bullets":[str,...]}},"image_query":str}}
- "two_column"   : {{"type":"two_column","title":str,"left":{{"title":str,"bullets":[str,...]}},"right":{{"title":str,"bullets":[str,...]}},"image_query":str}}
- "timeline"     : {{"type":"timeline","title":str,"steps":[{{"title":str,"description":str}},...](3-5),"image_query":str}}
- "numbered_list": {{"type":"numbered_list","title":str,"items":[{{"title":str,"description":str}},...](3-6),"image_query":str}}
- "process_flow" : {{"type":"process_flow","title":str,"steps":[{{"title":str,"description":str,"icon":str}},...](3-5),"image_query":str}}
- "icon_grid"    : {{"type":"icon_grid","title":str,"items":[{{"title":str,"description":str,"icon":str}},...](3-4),"image_query":str}}

ICON KEYWORDS — for "icon" fields, choose ONE from this list that best matches the item meaning (do not invent new ones; do not use emojis):
  chart, bar_chart, pie_chart, analytics, dashboard, growth, trend, revenue, decline,
  target, goal, strategy, flag, milestone, trophy, award,
  people, team, customer, partner, hr,
  gear, operations, process, automation, workflow,
  idea, innovation, research, discover, insight,
  shield, security, lock, privacy, risk, warning, compliance, verified,
  money, finance, cost, savings, investment, roi,
  clock, time, calendar, schedule, deadline,
  mail, message, phone, contact,
  cloud, server, database, api, code, device,
  globe, global, scale, network, connection,
  check, quality, star, premium, excellence,
  document, report, contract, knowledge,
  rocket, launch, deploy, build, grow,
  building, company, enterprise, factory, retail

Return ONLY a valid JSON array — no markdown fences, no explanation, no trailing commas.

QUALITY BENCHMARK EXAMPLE:
[
  {{"type":"title","title":"India's Sustainable Fashion Market: A $47B Opportunity That Incumbents Are Ignoring","subtitle":"How cooperative production models can capture 18% market share by 2028 while building durable competitive moats","image_query":"Indian textile factory workers sustainable fashion production"}},
  {{"type":"stats","title":"Market Inflection Point — The Numbers Demand Attention Now","stats":[{{"value":"$47B","label":"India sustainable apparel TAM by 2027 — 3× 2021 levels (IBEF)"}},{{"value":"38%","label":"Gen-Z premium willingness-to-pay vs. fast fashion — +14pp YoY"}},{{"value":"22%","label":"CAGR of ethical fashion segment 2023–28 — 4× overall market growth"}},{{"value":"₹12,000Cr","label":"Annual artisan income gap addressable through cooperative structuring"}}],"image_query":"India fashion market growth chart analytics"}},
  {{"type":"content","title":"Existing Players Are Optimising the Wrong Variable — Cost, Not Authenticity","bullets":["Abraham & Thakore targets HNI segment (₹15K+ ASP) but lacks rural supply chain depth — distribution bottleneck constrains revenue","ABFRL's 'Shrishti' brand grew 67% in FY24 but relies on contract manufacturing, surrendering 22pp gross margin vs. direct artisan model","Fab India cooperative model demonstrates 31% higher artisan retention rate vs. purely transactional sourcing — replicable at scale","New entrants (Okhai, Tjori) growing at 40%+ CAGR but individually too small to negotiate preferential logistics rates — consolidation opportunity"],"image_query":"Indian fashion brand competitive analysis"}},
  {{"type":"comparison","title":"Contract Manufacturing vs. Cooperative Society Model — The Margin and Moat Difference","left":{{"title":"Contract Manufacturing (Status Quo)","bullets":["Gross margin 28–34% — compressed by middlemen and MOQ penalties","Zero artisan loyalty: 60% attrition rate p.a. undermines quality consistency","No IP ownership over craft techniques — easily replicated by competitors","ESG rating C–B: supply chain opacity a growing investor risk flag"]}},"right":{{"title":"Cooperative Society Model (Proposed)","bullets":["Gross margin 48–56% — direct sourcing removes 3 intermediary layers","Artisan co-ownership drives 91% retention and self-reinforcing quality improvement","Craft IP held within cooperative — legally protectable, brand-differentiated","ESG rating A: ILO-compliant, auditable, qualifies for SEBI green-bond financing"]}},"image_query":"cooperative vs corporate business model comparison"}},
  {{"type":"numbered_list","title":"Four Moves That Build a ₹2,400Cr Revenue Base by FY28","items":[{{"title":"Register 12 district-level cooperative societies in Q1 FY26","description":"Unlocks ₹48Cr in government MSME cluster development grants; establishes legal IP ownership structure for craft techniques"}},{{"title":"Deploy IoT-enabled quality monitoring at cooperative hubs","description":"Reduces defect rate from 18% to <4% within 6 months, enabling premium retail listing at Nykaa Fashion and Myntra Luxe"}},{{"title":"Launch profit-share ESOP-equivalent for member artisans at 18-month mark","description":"Targets 95% retention; positions brand for B Corp certification — unlocking EU and UK ethical retail channels worth €340M"}},{{"title":"Negotiate Category Captain status with 2 major D2C platforms by FY27","description":"Secures preferred algorithmic placement, reducing CAC by 45% vs. paid acquisition — payback period drops from 14 to 6 months"}}],"image_query":"Indian business strategy planning boardroom"}},
  {{"type":"closing","title":"The Cooperative Model Is Not CSR — It Is the Highest-Return Capital Allocation Available","subtitle":"Pilot approval requested: ₹8.5Cr seed capital, 4 cooperatives, 18-month proof-of-concept with ₹340Cr NPV at base case","image_query":"Indian entrepreneur confident boardroom presentation"}}
]

Generate the complete JSON array now:"""

    def _build_outline_prompt_compact(self, query: str, count_instruction: str,
                                        theme: str, research_context: str = "") -> str:
        """Lean prompt for Ollama Cloud / local models.

        Keeps the content-quality rules but drops the long BAD/GOOD example
        blocks and the multi-slide benchmark JSON — those balloon the prompt
        to ~14k chars and combined with a 4k-token max_tokens cap, the
        endpoint returns HTTP 500. This variant runs under ~6k chars.
        """
        research_block = f"\n\n{research_context}\n" if research_context else ""
        research_mandate = ""
        if research_context:
            from datetime import datetime
            today_str = datetime.now().strftime("%B %d, %Y")
            research_mandate = (
                f"\nTODAY: {today_str}. The brief groups findings by freshness.\n"
                "RESEARCH MANDATE:\n"
                "- FRESHNESS FIRST: if the brief contains [BREAKING] entries (last 24h), use them in the opening slides and cite them with '(as of <date>)' or '(updated <date>)'. Prefer the most recent figure whenever sources conflict on the same metric.\n"
                "- Every stat/bullet/description MUST cite a [BREAKING]/[STAT]/[INSIGHT]/[PLAYER]/[RISK]/[QUOTE]/[REG] from the brief — no fabricated numbers.\n"
                "- Stat labels must carry source + date (e.g. 'Reuters, Apr 2026', 'IBEF 2024').\n"
                "- Include ≥1 slide that uses [BREAKING] items and ≥1 that uses [RISK] items.\n"
                "- The brief is your PRIMARY source; your own knowledge fills gaps ONLY.\n"
            )

        brand_block = self._brand_prompt_block(theme, card_only=True)
        return f"""You are a senior strategy consultant writing an executive 16:9 PowerPoint deck.

TOPIC: {query}{research_block}
{brand_block}
CONTENT RULES — NUMERIC DENSITY IS THE #1 QUALITY GATE:
- ≥90% of bullets, stat labels, and descriptions MUST contain at least one hard number (%, $, ₹, €, ×, bps, count, year, CAGR, YoY, pp). Prose-only content is rejected. Prefer TWO numbers per bullet: one fact + one comparison.
- Titles: ASSERTION HEADLINES stating a quantified conclusion, e.g. "Market Growing at 23% CAGR — Window Closes in 18 Months". Never topic labels like "Market Overview".
- Bullets: Situation → Insight → Implication in 20–35 words. Example: "FY24 revenue grew 34% YoY to $4.2B — outpacing category growth of 12%, signalling $1.1B expansion headroom". 4–5 bullets per content slide.
- Stats: 3–4 cards per slide. Label must carry comparison + source/year anchor, e.g. "+8pp vs. specialist baseline (NEJM 2024)" or "3× 2019 levels (IBEF)". Span dimensions: size (TAM), growth (CAGR), efficiency (cycle time/margin), quality (NPS/defect).
- Numbered list: title = action verb + quantified deliverable ("Digitise 240 tier-2 suppliers by Q2 FY27"); description = outcome with ≥2 numbers ("Cuts lead time 35% (45→29 days), unlocks ₹480Cr savings, 14-month payback").
- Process flow: each step description = measurable output with counts/thresholds ("Onboard 50 pilot artisans in 90 days; defect rate <4%").
- Icon grid: each description has 1 hard data point + comparison ("180bps margin uplift vs peers").
- Language: use CAGR, YoY, bps, TAM/SAM/SOM, NPV, EBITDA, payback period, run-rate. Avoid "leverage", "best-in-class", "synergies", vague superlatives.
- Narrative flow — every slide must advance ONE cohesive argument:
    Decide ordering from the request and research first. A typical business arc is Title -> Context -> Evidence -> Strategy -> Execution/Risks -> CTA, but adapt or reorder when the topic demands it.
- COHERENCE: A reader skimming ONLY slide titles must understand the full argument. Each title logically follows the previous one. Adjacent slides share a connecting thread (metric, entity, theme).
- TOPIC ANCHORING: Every slide must be DIRECTLY relevant to the TOPIC above. No generic filler. Before generating each slide, verify it directly serves the user's request.
- LOGICAL ORDERING: Keep the story coherent from premise to recommendation, but avoid enforcing a fixed step order when the content supports a better sequence.

VISUAL OUTPUT (Ollama / offline renderer — no photographs):
- The .pptx builder does NOT embed stock images for this provider. Do NOT include "image_query" on any slide.
- Favour slide types that read well as pure graphics: stats (metric cards), comparison, numbered_list, process_flow, icon_grid, timeline, content (full-width bullets with accent rail).
- Assume a brand-aligned palette (deep red / orange accents on white, rounded cards, accent bars, Segoe icon tiles) — write content dense enough that slides look complete without photos.

CRITICAL INFO THE DECK MUST COVER (include every applicable item):
  TAM with year+source • CAGR with time window • named competitors with share/position • ≥1 verbatim quote with full attribution • NPV or payback period for the recommendation • execution timeline with dated milestones • quantified risks (probability or $ exposure) • regulatory context with specific rules/deadlines • comparison benchmark (peer / industry / prior period).
{research_mandate}
STRUCTURE:
- {count_instruction}
- First slide type "title"; last slide type "closing" (subtitle = crisp CTA).
- Mix types: content, stats, numbered_list, process_flow, comparison/two_column, quote, icon_grid, section, timeline.
- Include ≥1 numbered_list AND ≥1 process_flow.
- Do NOT add "image_query" fields — they are ignored and must be omitted.

SCHEMAS (use exactly these JSON shapes — no image_query):
- title/section/closing: {{"type":T,"title":str,"subtitle":str}}
- content: {{"type":"content","title":str,"bullets":[str,...]}}
- stats: {{"type":"stats","title":str,"stats":[{{"value":str,"label":str}},...2-4]}}
- quote: {{"type":"quote","title":str,"quote":str,"attribution":str}}
- comparison/two_column: {{"type":T,"title":str,"left":{{"title":str,"bullets":[...]}},"right":{{"title":str,"bullets":[...]}}}}
- timeline: {{"type":"timeline","title":str,"steps":[{{"title":str,"description":str}},...3-5]}}
- numbered_list: {{"type":"numbered_list","title":str,"items":[{{"title":str,"description":str}},...3-6]}}
- process_flow: {{"type":"process_flow","title":str,"steps":[{{"title":str,"description":str,"icon":str}},...3-5]}}
- icon_grid: {{"type":"icon_grid","title":str,"items":[{{"title":str,"description":str,"icon":str}},...3-4]}}

ICONS — for "icon" fields, pick ONE keyword from this list that matches the item's meaning. Do NOT invent keywords; do NOT use emojis:
chart, bar_chart, pie_chart, analytics, dashboard, growth, trend, revenue, decline, target, goal, strategy, flag, milestone, trophy, people, team, customer, partner, gear, operations, process, automation, workflow, idea, innovation, research, insight, shield, security, risk, compliance, verified, money, finance, cost, savings, investment, roi, clock, time, calendar, schedule, cloud, server, database, api, code, globe, global, scale, network, check, quality, star, premium, document, report, contract, rocket, launch, deploy, build, building, company, enterprise, factory.

Return ONLY a valid JSON array. No markdown fences, no commentary, no trailing commas. Start with [ and end with ].

Generate the JSON array now:"""

    def _parse_slides_json(self, raw: str) -> Optional[List[Dict]]:
        cleaned = raw.strip()

        fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
        if fence_match:
            cleaned = fence_match.group(1).strip()

        bracket_match = re.search(r'\[[\s\S]*\]', cleaned)
        if bracket_match:
            cleaned = bracket_match.group(0)

        try:
            data = json.loads(cleaned)
            if isinstance(data, list) and len(data) >= 2:
                valid = []
                for item in data:
                    if isinstance(item, dict) and "title" in item:
                        if "type" not in item:
                            item["type"] = "content"
                        valid.append(item)
                return valid if len(valid) >= 2 else None
        except json.JSONDecodeError:
            pass

        return None

    def _validate_slide_flow(self, slides: List[Dict], query: str) -> tuple:
        """Lightweight structural coherence check.

        Returns ``(is_valid, issues)`` where *issues* is a list of problem
        descriptions. This does NOT call the LLM — it's a fast programmatic
        gate that catches the most common layout anti-patterns.
        """
        issues: List[str] = []
        if not slides:
            return False, ["No slides generated"]

        # 1. First slide must be title, last must be closing
        if slides[0].get("type") != "title":
            issues.append("First slide is not type 'title'")
        if slides[-1].get("type") != "closing":
            issues.append("Last slide is not type 'closing'")

        # 2. No empty titles
        for i, s in enumerate(slides):
            if not (s.get("title") or "").strip():
                issues.append(f"Slide {i+1} has an empty title")

        # 3. No consecutive duplicate titles (sign of LLM looping)
        for i in range(1, len(slides)):
            if slides[i].get("title", "").strip() == slides[i-1].get("title", "").strip():
                issues.append(f"Slides {i} and {i+1} have identical titles — possible LLM loop")

        # 4. No more than 3 consecutive same-type slides (monotonous layout)
        for i in range(2, len(slides)):
            t = slides[i].get("type", "content")
            if t == slides[i-1].get("type") == slides[i-2].get("type") and t not in ("content",):
                issues.append(f"Three consecutive '{t}' slides at positions {i-1}–{i+1} — vary slide types")

        # 5. Topic relevance — extract key terms from query and check titles mention at least some
        query_lower = query.lower()
        query_terms = set(w for w in re.findall(r'\b[a-z]{4,}\b', query_lower)
                         if w not in {"make", "create", "about", "presentation", "slides",
                                      "please", "generate", "want", "need", "with", "that",
                                      "this", "from", "have", "been", "will", "should", "could",
                                      "would", "their", "there", "they", "what", "which", "when",
                                      "where", "your", "more", "also", "very", "some", "each"})
        if query_terms:
            titles_combined = " ".join(s.get("title", "").lower() for s in slides)
            matched = sum(1 for t in query_terms if t in titles_combined)
            if len(query_terms) >= 3 and matched < len(query_terms) * 0.3:
                issues.append(
                    f"Only {matched}/{len(query_terms)} topic keywords found across slide titles — "
                    f"content may have drifted from the user's request"
                )

        # 6. Content slides should have bullets, stats slides should have stats
        for i, s in enumerate(slides):
            stype = s.get("type", "content")
            if stype == "content" and not s.get("bullets"):
                issues.append(f"Slide {i+1} is type 'content' but has no bullets")
            if stype == "stats" and not s.get("stats"):
                issues.append(f"Slide {i+1} is type 'stats' but has no stats data")
            if stype == "numbered_list" and not s.get("items"):
                issues.append(f"Slide {i+1} is type 'numbered_list' but has no items")
            if stype in ("process_flow", "timeline") and not s.get("steps"):
                issues.append(f"Slide {i+1} is type '{stype}' but has no steps")

        is_valid = len(issues) == 0
        return is_valid, issues

    # ── Text-length limits per slide type (max chars) ──────────────────────
    _SLIDE_TEXT_LIMITS: Dict[str, Dict[str, int]] = {
        "title":         {"title": 80, "subtitle": 120},
        "section":       {"title": 80, "subtitle": 120},
        "closing":       {"title": 40, "subtitle": 80},
        "content":       {"title": 90, "bullet": 180, "max_bullets": 6},
        "stats":         {"title": 90, "value": 12, "label": 140, "max_items": 4},
        "quote":         {"title": 90, "quote": 250, "attribution": 80},
        "comparison":    {"title": 90, "col_title": 40, "bullet": 160, "max_bullets": 4},
        "two_column":    {"title": 90, "col_title": 40, "bullet": 160, "max_bullets": 4},
        "timeline":      {"title": 90, "step_title": 30, "step_desc": 150, "max_items": 6},
        "numbered_list": {"title": 90, "item_title": 50, "item_desc": 160, "max_items": 6},
        "process_flow":  {"title": 90, "step_title": 30, "step_desc": 140, "max_items": 5},
        "icon_grid":     {"title": 90, "item_title": 35, "item_desc": 140, "max_items": 4},
    }

    def _build_slide_validate_prompt(self, slide: Dict, slide_index: int, total: int) -> str:
        """Build an LLM prompt that validates and fixes a single slide for
        content quality, text overflow, and professionalism."""
        stype = slide.get("type", "content")
        limits = self._SLIDE_TEXT_LIMITS.get(stype, self._SLIDE_TEXT_LIMITS["content"])
        slide_json = json.dumps(slide, ensure_ascii=False, indent=2)

        return f"""You are a senior presentation designer and editor.
Validate and improve slide {slide_index}/{total} below. Fix ALL issues in a single pass.

SLIDE JSON:
{slide_json}

RULES — fix any violation:
1. TITLE max {limits.get('title', 90)} chars. If longer, shorten without losing meaning.
2. No text field should overflow its max length:
{self._format_limits_for_prompt(stype, limits)}
3. Every bullet/description must be a COMPLETE thought (15-35 words). Remove filler words.
4. No jargon soup: remove "leverage", "synergies", "best-in-class", "cutting-edge" unless quoting.
5. Numbers must have context (e.g. "$4.2B" not just "4.2").
6. Stat values must be SHORT (max 12 chars, e.g. "$47B", "22%", "3.5×").
7. Ensure the slide type "{stype}" has all required fields filled — no empty arrays or blank strings.
8. If text is thin (bullets < 15 words each), expand with specific detail.
9. Keep the same "type" field — do NOT change the slide type.
10. Return ONLY the fixed JSON object. No markdown fences, no commentary.

Return the corrected JSON object:"""

    def _format_limits_for_prompt(self, stype: str, limits: Dict[str, int]) -> str:
        """Format text limits into readable prompt lines."""
        lines = []
        for key, val in limits.items():
            if key in ("title", "max_bullets", "max_items"):
                continue
            lines.append(f"   - {key}: max {val} chars")
        max_items = limits.get("max_bullets") or limits.get("max_items")
        if max_items:
            lines.append(f"   - max items/bullets: {max_items}")
        return "\n".join(lines) if lines else "   (standard limits apply)"

    def _ensure_slide_minimum_content(self, slide: Dict[str, Any]) -> Dict[str, Any]:
        """Guarantee required non-empty content fields per slide type.

        Some validator LLM responses keep the title but drop body arrays/strings.
        This guard normalises thin payloads so the renderer never produces
        title-only slides for content-oriented layouts.
        """
        if not isinstance(slide, dict):
            return {"type": "content", "title": "Key findings", "bullets": ["Data pending validation."]}

        stype = str(slide.get("type") or "content").lower()
        title = str(slide.get("title") or "Key findings").strip() or "Key findings"

        def _clean_list(vals: Any, max_n: int = 6) -> List[str]:
            if not isinstance(vals, list):
                return []
            out: List[str] = []
            for v in vals:
                s = str(v or "").strip()
                if s:
                    out.append(s)
                if len(out) >= max_n:
                    break
            return out

        def _ensure_rows(rows: Any, kind: str, min_n: int, max_n: int) -> List[Dict[str, str]]:
            cleaned: List[Dict[str, str]] = []
            if isinstance(rows, list):
                for i, r in enumerate(rows):
                    if not isinstance(r, dict):
                        continue
                    rt = str(r.get("title") or "").strip()
                    rd = str(r.get("description") or "").strip()
                    if not rt:
                        rt = f"{kind} {i + 1}"
                    if not rd:
                        rd = f"Detail pending for {rt.lower()}."
                    row = {"title": rt[:80], "description": rd[:220]}
                    if stype == "process_flow":
                        row["icon"] = str(r.get("icon") or "insight").strip() or "insight"
                    cleaned.append(row)
                    if len(cleaned) >= max_n:
                        break
            while len(cleaned) < min_n:
                idx = len(cleaned) + 1
                row = {
                    "title": f"{kind} {idx}",
                    "description": f"Quantified detail pending for {title.lower()} ({idx}).",
                }
                if stype == "process_flow":
                    row["icon"] = "insight"
                cleaned.append(row)
            return cleaned

        slide["type"] = stype
        slide["title"] = title[:120]

        if stype == "content":
            bullets = _clean_list(slide.get("bullets"), max_n=6)
            if not bullets:
                bullets = [
                    f"{title} baseline established; supporting metric validation in progress.",
                    "Source-backed trend and comparison will be populated in the next pass.",
                    "Operational and financial implications will be detailed with dated references.",
                ]
            slide["bullets"] = bullets
        elif stype == "stats":
            stats = slide.get("stats")
            clean_stats: List[Dict[str, str]] = []
            if isinstance(stats, list):
                for r in stats:
                    if not isinstance(r, dict):
                        continue
                    val = str(r.get("value") or "").strip() or "TBD"
                    lbl = str(r.get("label") or "").strip() or f"Supporting metric for {title}."
                    clean_stats.append({"value": val[:20], "label": lbl[:180]})
                    if len(clean_stats) >= 4:
                        break
            if not clean_stats:
                clean_stats = [{"value": "TBD", "label": f"Supporting metric for {title}."}]
            slide["stats"] = clean_stats
        elif stype == "quote":
            quote = str(slide.get("quote") or "").strip()
            attribution = str(slide.get("attribution") or "").strip()
            if not quote:
                quote = f"{title} requires a sourced verbatim statement."
            if not attribution:
                attribution = "Source pending verification"
            slide["quote"] = quote[:280]
            slide["attribution"] = attribution[:120]
        elif stype in ("comparison", "two_column"):
            left = slide.get("left") if isinstance(slide.get("left"), dict) else {}
            right = slide.get("right") if isinstance(slide.get("right"), dict) else {}
            left_b = _clean_list(left.get("bullets"), max_n=6)
            right_b = _clean_list(right.get("bullets"), max_n=6)
            if not left_b:
                left_b = [f"Current-state metric placeholder for {title}."]
            if not right_b:
                right_b = [f"Target-state metric placeholder for {title}."]
            slide["left"] = {
                "title": str(left.get("title") or "Current state").strip() or "Current state",
                "bullets": left_b,
            }
            slide["right"] = {
                "title": str(right.get("title") or "Target state").strip() or "Target state",
                "bullets": right_b,
            }
        elif stype in ("timeline", "process_flow"):
            slide["steps"] = _ensure_rows(slide.get("steps"), "Step", min_n=3, max_n=6)
        elif stype == "numbered_list":
            slide["items"] = _ensure_rows(slide.get("items"), "Item", min_n=3, max_n=6)
        elif stype == "icon_grid":
            items = _ensure_rows(slide.get("items"), "Item", min_n=3, max_n=4)
            for row in items:
                row["icon"] = str(row.get("icon") or "insight").strip() or "insight"
            slide["items"] = items
        elif stype in ("title", "section", "closing"):
            subtitle = str(slide.get("subtitle") or "").strip()
            slide["subtitle"] = subtitle or " "
        else:
            # Unknown type: fallback to a safe content slide.
            slide["type"] = "content"
            slide["bullets"] = _clean_list(slide.get("bullets"), max_n=5) or [
                f"{title} — supporting details pending.",
                "Key evidence and implications will be added with citations.",
                "Next actions and timeline will be quantified.",
            ]
        return slide

    async def _validate_and_fix_slides(
        self,
        slides_data: List[Dict],
        emit_thinking,
        thinking_steps: List[Dict],
    ) -> List[Dict]:
        """Run parallel LLM validation on each slide — fixes text overflow,
        thin content, unprofessional language. Returns the improved slides list."""
        validate_sem = asyncio.Semaphore(6)
        total = len(slides_data)

        async def _validate_one(i: int) -> tuple:
            slide = slides_data[i]
            stype = slide.get("type", "content")
            # Skip structural slides (title/section/closing) — they're simple enough
            if stype in ("title", "section", "closing"):
                return i, slide, False

            prompt = self._build_slide_validate_prompt(slide, i + 1, total)
            async with validate_sem:
                try:
                    raw = await self.ai.call_genai(prompt, temperature=0.15, max_tokens=2048)
                except Exception:
                    return i, slide, False

            fixed = self._parse_single_slide_object(raw)
            if fixed:
                # Preserve original type
                fixed["type"] = stype
                fixed = self._ensure_slide_minimum_content(fixed)
                return i, fixed, True
            return i, self._ensure_slide_minimum_content(slide), False

        tasks = [asyncio.create_task(_validate_one(i)) for i in range(total)]
        fixed_count = 0
        result_slides = list(slides_data)  # copy

        for coro in asyncio.as_completed(tasks):
            i, slide_out, was_fixed = await coro
            result_slides[i] = self._ensure_slide_minimum_content(slide_out)
            if was_fixed:
                fixed_count += 1

        return result_slides, fixed_count

    def _build_corrective_prompt(self, query: str, slides: List[Dict],
                                  issues: List[str], slide_count: Optional[int],
                                  theme: str, research_context: str,
                                  card_only_layout: bool = False,
                                  narrative_blueprint: Optional[Dict[str, str]] = None) -> str:
        """Build a follow-up prompt that feeds the flawed outline back with
        explicit instructions to fix the identified issues."""
        issues_text = "\n".join(f"  - {iss}" for iss in issues)
        original_json = json.dumps(slides, ensure_ascii=False, indent=2)

        count_instruction = (
            f"Create exactly {slide_count} slides."
            if slide_count
            else "Create 10–14 slides for a full presentation, or 6–8 for a brief one."
        )

        brand_block = self._brand_prompt_block(theme, card_only=card_only_layout)
        blueprint_sequence = (narrative_blueprint or {}).get("sequence") or (
            "Title -> Context/Problem -> Evidence/Data -> Strategy/Options -> Execution/Timeline -> Risks -> CTA"
        )
        return f"""You previously generated the slide outline below, but it has structural and coherence problems.

TOPIC: {query}
{brand_block}

PROBLEMS FOUND:
{issues_text}

PREVIOUS (FLAWED) OUTLINE:
{original_json}

FIX INSTRUCTIONS:
1. {count_instruction}
2. First slide must be type "title"; last slide must be type "closing".
3. Every slide must be DIRECTLY relevant to the TOPIC — no generic filler.
4. Slide titles must form a connected narrative: each title logically follows the previous.
5. Use this selected blueprint as guidance (not mandatory order): {blueprint_sequence}. Adapt ordering to the query and evidence while preserving coherence.
6. Every content slide needs bullets; every stats slide needs stats; every numbered_list needs items; every process_flow/timeline needs steps.
7. Vary slide types — do not put 3+ consecutive slides of the same type.
8. Each bullet/stat/description must contain at least one hard number.
9. {"Omit every \"image_query\" field — the deck is rendered with brand-colored cards, shapes, and icons only (no stock photos)." if card_only_layout else "Keep \"image_query\" on every slide as in the original outline format."}

Return ONLY a corrected valid JSON array. No markdown fences, no explanation. Start with [ and end with ]."""


ppt_generator_agent = PPTGeneratorAgent()
