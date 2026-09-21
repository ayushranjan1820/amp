"""Perplexity Sonar *chat* API — fetch relevant image URLs for meeting prep (Search API has no images)."""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

PERPLEXITY_CHAT_URL = "https://api.perplexity.ai/chat/completions"


def _normalize_one_image(item: Any) -> Optional[Tuple[str, str]]:
    """Return (url, short_label) or None."""
    if isinstance(item, str):
        u = item.strip()
        if u.startswith("https://"):
            return u, "Image"
        return None
    if isinstance(item, dict):
        u = item.get("image_url") or item.get("url") or item.get("origin_url")
        if not isinstance(u, str) or not u.startswith("https://"):
            return None
        label = (
            item.get("title")
            or item.get("description")
            or item.get("name")
            or "Image"
        )
        if not isinstance(label, str):
            label = "Image"
        return u.strip(), label.strip()[:200] or "Image"
    return None


def _dedupe_preserve_order(urls: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _build_user_prompt(ctx: Dict[str, Any]) -> str:
    person = (ctx.get("person_name") or ctx.get("person_role") or "").strip()
    role = (ctx.get("person_role") or "").strip()
    company = (ctx.get("company") or "").strip()
    industry = (ctx.get("industry") or "").strip()
    topics = ctx.get("specific_topics") or []
    purpose = (ctx.get("meeting_purpose") or "").strip()
    topic_line = ", ".join(str(t) for t in topics) if topics else purpose or "general business discussion"

    parts = [
        "You are helping gather visuals for an executive meeting preparation document.",
        f"Meeting context: {company or 'the company'}",
    ]
    if industry:
        parts.append(f"Industry: {industry}")
    if person or role:
        parts.append(f"Key contact: {person or role}" + (f", {role}" if person and role and role not in person else ""))
    parts.append(f"Topics / purpose: {topic_line}")
    parts.append(
        "What are the most relevant publicly viewable images for this brief? "
        "Think: official or recent photo of the executive (if identifiable), company logo or branded asset, "
        "headquarters or flagship visual, and at most one chart/infographic/product shot tied to the topic. "
        "Answer in 2–4 short sentences naming what to illustrate; the API will attach image search results."
    )
    return "\n".join(parts)


async def fetch_meeting_prep_images(
    context: Dict[str, Any],
    *,
    timeout: float = 90.0,
    max_images: int = 8,
) -> Tuple[List[str], List[Dict[str, str]], str]:
    """
    Call Perplexity chat completions with return_images.

    Returns
    -------
    urls :
        Deduped HTTPS image URLs (max ``max_images``).
    records :
        ``{"url", "label"}`` for prompt context.
    answer_snippet :
        Short model text (optional, for debugging / future use).
    """
    api_key = (os.getenv("PERPLEXITY_API_KEY") or "").strip()
    if not api_key:
        return [], [], ""

    user_content = _build_user_prompt(context)
    payload = {
        "model": "sonar",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You assist with meeting preparation. Be concise. "
                    "Focus on legitimate news, company, and official sources for imagery."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        "return_citations": True,
        "return_images": True,
        "return_related_questions": False,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(PERPLEXITY_CHAT_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"  ⚠️ Perplexity chat (images) error: {e}")
        return [], [], ""

    try:
        from cost_tracker import log_cost_event

        log_cost_event(
            event_type="perplexity_chat_images",
            agent_name="Meeting Prep Agent",
            metadata={"prompt_len": len(user_content)},
        )
    except Exception:
        pass

    answer = ""
    if data.get("choices"):
        answer = (data["choices"][0].get("message") or {}).get("content") or ""
    raw_images = data.get("images") or []
    if not isinstance(raw_images, list):
        raw_images = []

    records: List[Dict[str, str]] = []
    for item in raw_images:
        parsed = _normalize_one_image(item)
        if not parsed:
            continue
        url, label = parsed
        records.append({"url": url, "label": label})

    urls = _dedupe_preserve_order([r["url"] for r in records])
    if len(urls) > max_images:
        urls = urls[:max_images]
        records = [r for r in records if r["url"] in urls]

    return urls, records, (answer or "")[:1200]


def format_image_candidates_for_prompt(records: List[Dict[str, str]]) -> str:
    if not records:
        return (
            "No image URLs were returned by the image search pass. "
            "Do **not** invent or guess image URLs. Omit images unless you already have URLs from research text."
        )
    lines = []
    for i, r in enumerate(records, 1):
        lines.append(f"{i}. **URL:** {r['url']}\n   **Suggested alt text:** {r['label']}")
    return "\n".join(lines)
