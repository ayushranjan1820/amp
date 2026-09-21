"""Planner stage for the PPT Generator Agent — deck structure before per-slide research and generation."""

import json
import re
from typing import Any, Dict, List, Optional

from .models import MAX_SLIDES, MIN_SLIDES


ALLOWED_SLIDE_TYPES = frozenset({
    "title", "section", "closing", "content", "stats", "quote", "comparison",
    "two_column", "timeline", "numbered_list", "process_flow", "icon_grid",
})


DEFAULT_NARRATIVE_BLUEPRINT: Dict[str, str] = {
    "name": "evidence-first",
    "sequence": "Title -> Context/Problem -> Evidence/Data -> Strategy/Options -> Execution/Timeline -> Risks -> CTA",
    "planner_instruction": "Quantify the problem and evidence before strategy choices, then land the deck with execution and risk treatment.",
}


def _resolve_narrative_blueprint(narrative_blueprint: Optional[Dict[str, str]]) -> Dict[str, str]:
    bp = dict(DEFAULT_NARRATIVE_BLUEPRINT)
    if isinstance(narrative_blueprint, dict):
        for k in ("name", "sequence", "planner_instruction"):
            v = narrative_blueprint.get(k)
            if isinstance(v, str) and v.strip():
                bp[k] = v.strip()
    return bp


def _parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    s = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", s)
    if m:
        s = m.group(1).strip()
    try:
        data = json.loads(s)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def build_planner_prompt(
    query: str,
    slide_count: Optional[int],
    compact: bool,
    research_brief: Optional[str] = None,
    narrative_blueprint: Optional[Dict[str, str]] = None,
    raw_user_content: Optional[str] = None,
) -> str:
    blueprint = _resolve_narrative_blueprint(narrative_blueprint)
    count_rule = (
        f"The deck must contain exactly {slide_count} slides (including title and closing)."
        if slide_count
        else (
            f"Choose an integer slide count between {MIN_SLIDES} and {MAX_SLIDES} based on topic depth: "
            "prefer 10–14 for executive deep-dives, 6–8 for briefings."
        )
    )
    types_line = ", ".join(sorted(ALLOWED_SLIDE_TYPES))

    raw_block = ""
    raw_mandate = ""
    if raw_user_content and raw_user_content.strip():
        # Compact providers (Ollama Cloud / local) need short prompts to stay
        # within reliable generation window; PwC GenAI keeps the rich cap.
        raw_cap = 2500 if compact else 12000
        raw_block = (
            "\n\nUSER-PROVIDED CONTENT (PRIMARY SOURCE — verbatim, do NOT summarise or ignore; "
            "every section below must be represented by at least one slide, and every hard number / named entity "
            "must land on a slide):\n"
            f"{raw_user_content[:raw_cap]}\n"
        )
        raw_mandate = (
            "\n- USER CONTENT IS THE SPINE: scan the USER-PROVIDED CONTENT above and map its sections to slides 1:1 "
            "where possible. Do NOT drop whole sections. If the user lists N problems or N recommendations, allocate "
            "slides to cover all N (use numbered_list / icon_grid / process_flow when N>4).\n"
            "- DYNAMIC LAYOUT PER SLIDE: choose slide_type from the content shape, NOT from a fixed template. "
            "Lists → numbered_list/icon_grid; phased plans → timeline/process_flow; opposing options → comparison/two_column; "
            "metrics → stats; narrative analysis → content; attributed statements → quote.\n"
            "- data_prompt_for_slide_author MUST quote or point to the exact section of USER-PROVIDED CONTENT that "
            "feeds the slide (e.g., 'pull items from the Recommended AI Solutions section, entries 1–3').\n"
        )

    brief_block = ""
    brief_mandate = ""
    if research_brief:
        brief_block = f"\n\nINTELLIGENCE BRIEF (your PRIMARY source — structure the deck so these facts can be cited):\n{research_brief}\n"
        brief_mandate = (
            "\n- PLAN AGAINST FACTS: every slide's `data_prompt_for_slide_author` MUST reference specific "
            "[BREAKING]/[STAT]/[PLAYER]/[INSIGHT]/[RISK]/[QUOTE]/[REG] entries from the brief by their topic "
            "(e.g. 'cite the TAM [STAT] with year anchor; name the top 3 [PLAYER] entries'). Do not request facts the brief lacks.\n"
            "- FRESHNESS: if [BREAKING] entries exist, reserve slide 1 or 2 to surface them as the deck's news hook.\n"
            "- CROSS-SLIDE THREADING: specify at least one metric or entity that carries across ≥3 slides "
            "(introduced → quantified → compared → acted upon → risk-adjusted) so the deck reads as one argument, not N siloed tiles."
        )

    if compact:
        return f"""You are the PLANNING agent for an executive PowerPoint. You do NOT write slide body copy — you only structure the deck.

USER REQUEST:
{query}{raw_block}{brief_block}
RULES:
- {count_rule}
- Slide 1 MUST be type "title". Last slide MUST be type "closing".
- Every other slide type MUST be one of: {types_line}
- ACTIVE BLUEPRINT: {blueprint['name']} — {blueprint['sequence']}
- Use the active blueprint as a guiding hypothesis, not a rigid order; adapt middle-slide sequencing to the user's objective and available facts.
- You may merge, skip, or reorder blueprint beats when it improves narrative relevance and clarity for this specific request.
- {blueprint['planner_instruction']}
- For EACH slide, pick the single best layout type for that narrative beat.
- "per_slide_search_queries": 2–4 very specific web search strings for THAT slide only (include dates/years, entity names, metrics). Optimised for news + data (earnings, %, $, regulatory filings).
- "data_prompt_for_slide_author": short instructions for the downstream author LLM (what numbers, comparisons, and sources to insist on for this slide).
- "assertion_title_hint": the headline direction (not final wording).{raw_mandate}{brief_mandate}

Return ONLY valid JSON (no markdown fences):
{{
  "target_slide_count": <int>,
  "deck_arc_summary": "<one sentence>",
  "threaded_metrics": ["<metric or entity that spans ≥3 slides>", "..."],
  "slides": [
    {{
      "position": 1,
      "slide_type": "title",
      "assertion_title_hint": "<string>",
      "layout_choice": "<short id>",
      "layout_variant": "<one of: default | callout | split | hero | grid — picked to fit THIS slide's content density>",
      "layout_rationale": "<string>",
      "data_prompt_for_slide_author": "<string>",
      "per_slide_search_queries": ["<q1>", "<q2>"]
    }}
  ]
}}"""

    return f"""You are the senior PLANNING agent for a McKinsey-calibre PowerPoint. You do not draft bullets or stat values — you architect the deck so downstream agents can inject fresh web research per slide.

USER REQUEST:
{query}{raw_block}{brief_block}
{count_rule}

STRUCTURAL RULES:
1. First slide: slide_type "title". Final slide: slide_type "closing".
2. Every slide_type must be one of: {types_line}
3. ACTIVE BLUEPRINT: {blueprint['name']} — {blueprint['sequence']}
4. Narrative arc (adapt beats to query + evidence; compress or expand positions to hit target_slide_count):
    Use the active blueprint as guidance, not a fixed template.
    Reorder, merge, or skip beats when that produces a clearer argument for this specific request, while preserving title-first and CTA-strong close.
    {blueprint['planner_instruction']}
5. Vary layouts — never more than two adjacent slides of the same slide_type except "content".
6. Each slide needs a sharp "assertion_title_hint" (direction for an assertion headline, not a bland topic label).
7. "layout_choice": a short internal label (e.g. "evidence_stats_grid", "risk_register") + "layout_rationale" (one sentence why this layout fits the beat).
8. "data_prompt_for_slide_author": concrete instructions for the slide author model — mandate numeric density, source names in labels, freshness (prefer figures from the supplied research block), and what must not be invented.
9. "per_slide_search_queries": 2–4 DISTINCT search strings optimised for Perplexity/web (include organisation names, years, metric keywords like CAGR, revenue, market share, regulation). These run in parallel across slides — keep each list focused on THIS slide only.{raw_mandate}{brief_mandate}

Return ONLY valid JSON (no markdown, no commentary):
{{
  "target_slide_count": <int between {MIN_SLIDES} and {MAX_SLIDES}>,
  "deck_arc_summary": "<string>",
  "threaded_metrics": ["<metric/entity spanning ≥3 slides — enables cross-slide narrative>", "..."],
  "slides": [
    {{
      "position": 1,
      "slide_type": "title",
      "assertion_title_hint": "<string>",
      "layout_choice": "<string>",
      "layout_variant": "<one of: default | callout | split | hero | grid — chosen to fit THIS slide's content density>",
      "layout_rationale": "<string>",
      "data_prompt_for_slide_author": "<string>",
      "per_slide_search_queries": ["<string>", "..."]
    }}
  ]
}}"""


def build_planner_prompt_minimal(
    query: str,
    slide_count: Optional[int],
    narrative_blueprint: Optional[Dict[str, str]] = None,
    raw_user_content: Optional[str] = None,
) -> str:
    """Ultra-short planner prompt for compact LLMs (Ollama Cloud / local).

    Trades richness for reliability: no brief, no layout rationale, no deck arc
    summary, no threaded metrics. Just slide count, types, title hints, and
    2 search queries per slide — enough for the per-slide author to run.
    Total prompt ~700 chars; generation fits comfortably inside a 2k token cap.
    """
    count_rule = (
        f"exactly {slide_count} slides"
        if slide_count
        else f"between {MIN_SLIDES} and {MAX_SLIDES} slides (choose based on topic depth)"
    )
    types_line = ", ".join(sorted(ALLOWED_SLIDE_TYPES))
    blueprint = _resolve_narrative_blueprint(narrative_blueprint)
    raw_block = ""
    if raw_user_content and raw_user_content.strip():
        # Minimal-skeleton prompt runs first on compact providers — keep the
        # injected user content small so the total prompt stays ~1.5KB.
        raw_block = (
            "\n\nUSER CONTENT (map every section to at least one slide):\n"
            f"{raw_user_content[:2000]}\n"
        )
    return f"""You are the PLANNER for an executive PowerPoint. Output JSON only.

TOPIC: {query}{raw_block}

RULES:
- Plan {count_rule}. Slide 1 type "title", last slide type "closing".
- Other types from: {types_line}
- Active blueprint: {blueprint['name']} — {blueprint['sequence']}.
- Order: treat the blueprint as guidance; adapt middle-slide order to the user's query and available evidence.
- {blueprint['planner_instruction']}
- Vary types; no 3+ same-type in a row.

Return ONLY this JSON (no markdown):
{{"target_slide_count":<int>,"slides":[
  {{"position":1,"slide_type":"title","assertion_title_hint":"<string>","per_slide_search_queries":["<q1>","<q2>"]}}
]}}"""


def extract_planner_meta(data: Dict[str, Any]) -> Dict[str, Any]:
    """Pull deck-level fields (arc summary, threaded metrics) from planner JSON."""
    arc = (data.get("deck_arc_summary") or "").strip() if isinstance(data, dict) else ""
    tm = data.get("threaded_metrics") if isinstance(data, dict) else None
    threaded: List[str] = []
    if isinstance(tm, list):
        threaded = [str(x).strip() for x in tm if str(x).strip()][:6]
    elif isinstance(tm, str) and tm.strip():
        threaded = [tm.strip()]
    return {"deck_arc_summary": arc, "threaded_metrics": threaded}


def normalize_planner_output(data: Dict[str, Any], requested_slide_count: Optional[int]) -> Optional[List[Dict[str, Any]]]:
    """Validate and return ordered slide plan rows, or None if invalid."""
    slides = data.get("slides")
    if not isinstance(slides, list) or len(slides) < MIN_SLIDES:
        return None

    target = data.get("target_slide_count")
    try:
        target = int(target) if target is not None else len(slides)
    except (TypeError, ValueError):
        target = len(slides)

    if requested_slide_count is not None:
        target = max(MIN_SLIDES, min(MAX_SLIDES, int(requested_slide_count)))
    else:
        target = max(MIN_SLIDES, min(MAX_SLIDES, target))

    # Sort by position
    rows: List[Dict[str, Any]] = []
    for item in slides:
        if not isinstance(item, dict):
            continue
        try:
            pos = int(item.get("position", 0))
        except (TypeError, ValueError):
            continue
        st = (item.get("slide_type") or "").strip().lower()
        if st not in ALLOWED_SLIDE_TYPES:
            continue
        queries = item.get("per_slide_search_queries") or []
        if isinstance(queries, str):
            queries = [queries]
        queries = [str(q).strip() for q in queries if str(q).strip()][:6]

        variant = (item.get("layout_variant") or "").strip().lower()
        if variant not in {"default", "callout", "split", "hero", "grid"}:
            variant = "default"
        rows.append({
            "position": pos,
            "slide_type": st,
            "assertion_title_hint": (item.get("assertion_title_hint") or "").strip(),
            "layout_choice": (item.get("layout_choice") or "").strip(),
            "layout_variant": variant,
            "layout_rationale": (item.get("layout_rationale") or "").strip(),
            "data_prompt_for_slide_author": (item.get("data_prompt_for_slide_author") or "").strip(),
            "per_slide_search_queries": queries if queries else [item.get("assertion_title_hint") or "key facts"],
        })

    if len(rows) < MIN_SLIDES:
        return None

    rows.sort(key=lambda r: r["position"])
    # Trim or pad to target (prefer trim from end before closing)
    if len(rows) > target:
        # keep first and last types stable
        first = rows[0]
        last = rows[-1]
        mid = rows[1:-1]
        budget = max(0, target - 2)
        mid = mid[:budget]
        rows = [first] + mid + [last]

    if rows[0]["slide_type"] != "title":
        return None
    if rows[-1]["slide_type"] != "closing":
        return None

    return rows
