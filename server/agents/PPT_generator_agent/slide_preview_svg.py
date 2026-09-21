"""Lightweight 16:9 SVG previews for streaming slide snapshots (no extra dependencies)."""

import base64
import html
import json
from typing import Any, Dict, List


def _truncate(text: str, max_len: int) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "..."


def _preview_theme(theme: str) -> Dict[str, str]:
    t = (theme or "").strip().lower()
    if t == "pwc":
        return {
            "accent": "#DC6900",
            "accent_2": "#E0301E",
            "bg_top": "#FFFFFF",
            "bg_bot": "#F7F7F7",
            "muted": "#6E6E6E",
            "body": "#1A1A1A",
            "title": "#0B1426",
            "card": "#F7F7F7",
            "stroke": "#D9D9D9",
            "font": "PwCNext,Arial,Calibri,Helvetica,sans-serif",
            "quote_font": "PwCNext,Arial,Calibri,Helvetica,sans-serif",
            "footer_brand": "PwC",
            "sidebar": "#2D2D2D",
        }
    if t == "midnight":
        return {
            "accent": "#FF6B47",
            "accent_2": "#60A5FA",
            "bg_top": "#0B1220",
            "bg_bot": "#141B2E",
            "muted": "#6B7280",
            "body": "#D1D5DB",
            "title": "#F5F3EF",
            "card": "#1A2138",
            "stroke": "#2A3350",
            "font": "Segoe UI,Inter,sans-serif",
            "quote_font": "Georgia,serif",
            "footer_brand": "",
            "sidebar": "",
        }
    # ── aurora (default) — warm paper, coral accent, indigo secondary ──
    return {
        "accent": "#F26B4F",
        "accent_2": "#2E3A59",
        "bg_top": "#FAF9F6",
        "bg_bot": "#F1EDE4",
        "muted": "#A8A29E",
        "body": "#1F2937",
        "title": "#0B1426",
        "card": "#FFFFFF",
        "stroke": "#E6E1D8",
        "font": "Segoe UI,Inter,sans-serif",
        "quote_font": "Georgia,serif",
        "footer_brand": "",
        "sidebar": "",
    }


def slide_dict_to_preview_payload(slide: Dict[str, Any], index: int, theme: str = "aurora") -> Dict[str, str]:
    """Return mime + base64 SVG suitable for SSE `ppt_slide_snapshot` events."""
    svg = build_slide_svg(slide, index, theme=theme)
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return {
        "mime": "image/svg+xml",
        "image": b64,
    }


def build_slide_svg(slide: Dict[str, Any], index: int, theme: str = "aurora", w: int = 960, h: int = 540) -> str:
    stype = html.escape((slide.get("type") or "slide").strip() or "slide")
    title = html.escape(_truncate(slide.get("title") or "", 120))
    palette = _preview_theme(theme)
    accent = palette["accent"]
    accent_2 = palette["accent_2"]
    muted = palette["muted"]
    body = palette["body"]
    title_fill = palette["title"]
    card_fill = palette["card"]
    stroke = palette["stroke"]
    font_family = palette["font"]
    quote_font = palette["quote_font"]

    st = slide.get("type", "")
    parts: List[str] = []
    # Editorial layout: content sits under the title bar (title ends ~100px)
    content_x = 56
    y = 150

    if st == "content" and isinstance(slide.get("bullets"), list):
        for idx_b, b in enumerate(slide["bullets"][:5]):
            parts.append(
                f'<text x="{content_x}" y="{y}" fill="{accent}" font-size="11" font-weight="700" font-family="{font_family}">{idx_b + 1:02d}</text>'
                f'<text x="{content_x + 30}" y="{y}" fill="{body}" font-size="14" font-family="{font_family}">'
                f'{html.escape(_truncate(str(b), 100))}</text>'
            )
            y += 34

    elif st == "stats" and isinstance(slide.get("stats"), list):
        stats_list = [s for s in slide["stats"][:4] if isinstance(s, dict)]
        n = max(1, len(stats_list))
        col_w = (w - 112) / n
        for i, s in enumerate(stats_list):
            cx = content_x + int(i * col_w)
            val = html.escape(_truncate(str(s.get("value", "")), 12))
            lab = html.escape(_truncate(str(s.get("label", "")), 52))
            parts.append(
                f'<text x="{cx}" y="170" fill="{muted}" font-size="10" font-weight="700" font-family="{font_family}">{i + 1:02d}</text>'
                f'<text x="{cx}" y="230" fill="{accent}" font-size="42" font-weight="700" font-family="{font_family}">{val}</text>'
                f'<rect x="{cx}" y="250" width="30" height="3" fill="{accent_2}"/>'
                f'<text x="{cx}" y="280" fill="{body}" font-size="12" font-family="{font_family}">{lab}</text>'
            )

    elif st == "quote":
        q = html.escape(_truncate(slide.get("quote") or "", 200))
        att = html.escape(_truncate(slide.get("attribution") or "", 90))
        parts.append(
            f'<text x="{content_x}" y="230" fill="{accent}" font-size="90" font-weight="700" font-family="{font_family}">&#x201C;</text>'
            f'<text x="{content_x + 70}" y="220" fill="{body}" font-size="18" font-style="italic" font-family="{quote_font}">{q}</text>'
            f'<rect x="{content_x + 70}" y="310" width="36" height="3" fill="{accent}"/>'
            f'<text x="{content_x + 70}" y="335" fill="{muted}" font-size="11" font-weight="700" font-family="{font_family}">{att.upper()}</text>'
        )

    elif st in ("comparison", "two_column") and isinstance(slide.get("left"), dict):
        left = slide["left"]
        right = slide.get("right") or {}
        lt = html.escape(_truncate(str(left.get("title", "Left")), 36))
        rt = html.escape(_truncate(str(right.get("title", "Right")), 36))
        mid_x = w // 2
        parts.append(f'<rect x="{mid_x}" y="155" width="1" height="260" fill="{muted}"/>')
        parts.append(f'<text x="{content_x}" y="165" fill="{accent}" font-size="10" font-weight="700" font-family="{font_family}">PART A</text>')
        parts.append(f'<text x="{content_x}" y="195" fill="{title_fill}" font-size="16" font-weight="700" font-family="{font_family}">{lt}</text>')
        parts.append(f'<text x="{mid_x + 20}" y="165" fill="{accent_2}" font-size="10" font-weight="700" font-family="{font_family}">PART B</text>')
        parts.append(f'<text x="{mid_x + 20}" y="195" fill="{title_fill}" font-size="16" font-weight="700" font-family="{font_family}">{rt}</text>')
        yy = 230
        for b in (left.get("bullets") or [])[:3]:
            parts.append(
                f'<rect x="{content_x}" y="{yy - 8}" width="6" height="6" fill="{accent}"/>'
                f'<text x="{content_x + 16}" y="{yy}" fill="{body}" font-size="12" font-family="{font_family}">{html.escape(_truncate(str(b), 70))}</text>'
            )
            yy += 26
        yy = 230
        for b in (right.get("bullets") or [])[:3]:
            parts.append(
                f'<rect x="{mid_x + 20}" y="{yy - 8}" width="6" height="6" fill="{accent_2}"/>'
                f'<text x="{mid_x + 36}" y="{yy}" fill="{body}" font-size="12" font-family="{font_family}">{html.escape(_truncate(str(b), 70))}</text>'
            )
            yy += 26

    elif slide.get("subtitle"):
        parts.append(
            f'<text x="{content_x}" y="180" fill="{muted}" font-size="16" font-family="{font_family}">'
            f'{html.escape(_truncate(str(slide.get("subtitle")), 130))}</text>'
        )
    elif isinstance(slide.get("items"), list):
        for item in slide["items"][:4]:
            if isinstance(item, dict):
                t = html.escape(_truncate(str(item.get("title", "")), 90))
                parts.append(
                    f'<text x="{content_x}" y="{y}" fill="{body}" font-size="15" font-family="{font_family}">{t}</text>'
                )
                y += 30
    elif isinstance(slide.get("steps"), list):
        for step in slide["steps"][:4]:
            if isinstance(step, dict):
                t = html.escape(_truncate(str(step.get("title", "")), 80))
                parts.append(
                    f'<text x="{content_x}" y="{y}" fill="{body}" font-size="14" font-family="{font_family}">- {t}</text>'
                )
                y += 28

    body_svg = "\n".join(parts)

    # ── Editorial footer: hairline + deck label + page number ──
    if palette["footer_brand"]:
        footer = (
            f'<rect x="40" y="{h - 30}" width="{w - 80}" height="2" fill="{accent}"/>'
            f'<text x="{w - 56}" y="{h - 10}" fill="{accent_2}" text-anchor="end" font-size="12" font-weight="700" font-family="{font_family}">{palette["footer_brand"]}</text>'
        )
    else:
        foot_y = h - 30
        footer = (
            f'<rect x="56" y="{foot_y - 14}" width="{w - 112}" height="1" fill="{muted}"/>'
            f'<text x="{w - 56}" y="{foot_y}" fill="{accent}" text-anchor="end" font-size="13" font-weight="700" font-family="{font_family}">{index:02d}</text>'
            f'<text x="56" y="{foot_y}" fill="{muted}" font-size="10" font-weight="700" font-family="{font_family}">EXECUTIVE BRIEFING</text>'
        )

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">
  <rect width="100%" height="100%" fill="{palette["bg_top"]}"/>
  <!-- Eyebrow dot + label -->
  <circle cx="62" cy="55" r="4" fill="{accent}"/>
  <text x="76" y="60" fill="{accent}" font-size="11" font-weight="700" font-family="{font_family}">{html.escape(stype.upper())}</text>
  <!-- Vertical accent bar beside title -->
  <rect x="56" y="85" width="4" height="36" fill="{accent}"/>
  <!-- Title -->
  <text x="72" y="112" fill="{title_fill}" font-size="22" font-weight="700" font-family="{font_family}">{title}</text>
  {body_svg}
  {footer}
</svg>'''


def slide_json_summary(slide: Dict[str, Any]) -> str:
    try:
        return json.dumps(slide, ensure_ascii=False)[:4000]
    except Exception:
        return "{}"
