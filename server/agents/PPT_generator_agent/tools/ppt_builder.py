import os
import time
import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "generated_files")

# PwC logo asset — placed on every slide footer
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
PWC_LOGO_PATH = os.path.join(_ASSETS_DIR, "pwc_logo.png")

# 16:9 widescreen — modern presentation standard
SLIDE_W_IN = 13.333
SLIDE_H_IN = 7.5
SLIDE_W = Inches(SLIDE_W_IN)
SLIDE_H = Inches(SLIDE_H_IN)

FONT_HEADING = "Segoe UI"
FONT_BODY = "Segoe UI"
# PwC brand-compliant font. PowerPoint substitutes automatically on clients
# that don't have PwCNext installed; the brand guideline fallback chain is
# Arial → Calibri → Helvetica, all of which Office ships by default.
FONT_PWC_HEADING = "PwCNext"
FONT_PWC_BODY = "PwCNext"
# Windows-native icon font — ships with Windows 10/11 and therefore every
# recent PowerPoint install. Codepoints render as clean monochrome vector
# glyphs (no colour emoji noise).
FONT_ICONS = "Segoe Fluent Icons"
FONT_ICONS_FALLBACK = "Segoe MDL2 Assets"


# ─────────── semantic icon catalog ───────────
# Maps a slide author's keyword (the LLM supplies one of these) to a glyph
# codepoint in Segoe MDL2/Fluent. Keep only well-known, universally
# understood business concepts — no decorative or ambiguous icons.
ICON_CATALOG: Dict[str, str] = {
    # Analytics / metrics
    "chart": "\uE9D9",          # LineChart
    "line_chart": "\uE9D9",
    "bar_chart": "\uE9F5",      # BarChartVerticalFill
    "pie_chart": "\uE9A9",      # PieSingle
    "analytics": "\uE9D9",
    "dashboard": "\uE80F",      # TilesLayout
    "growth": "\uF149",         # TrendingUp
    "trend": "\uF149",
    "revenue": "\uF149",
    "decline": "\uEB0D",        # TrendingDown
    # Strategy / goals
    "target": "\uF272",         # Bullseye
    "goal": "\uF272",
    "strategy": "\uF272",
    "flag": "\uEB4B",
    "milestone": "\uEB4B",
    "trophy": "\uED15",         # Trophy
    "award": "\uED15",
    # People / customer
    "people": "\uE716",         # People
    "team": "\uE716",
    "customer": "\uE77B",       # Contact
    "user": "\uE77B",
    "hr": "\uE716",
    "partner": "\uE8D0",        # ContactInfo — handshake-ish
    # Operations
    "gear": "\uE713",           # Settings
    "settings": "\uE713",
    "operations": "\uE713",
    "process": "\uE9F9",        # Processing
    "automation": "\uE945",
    "workflow": "\uEC4A",       # WorkflowSolid
    # Innovation
    "idea": "\uE945",           # Lightbulb
    "lightbulb": "\uE945",
    "innovation": "\uE945",
    "research": "\uE721",       # Search
    "discover": "\uE721",
    "insight": "\uE945",
    # Security / risk
    "shield": "\uEA18",         # Shield
    "security": "\uEA18",
    "lock": "\uE72E",           # Lock
    "privacy": "\uE72E",
    "risk": "\uE7BA",           # Warning
    "warning": "\uE7BA",
    "compliance": "\uE73A",     # Certificate
    "verified": "\uE73E",       # CheckMark
    # Finance
    "money": "\uE1D3",
    "finance": "\uE1D3",
    "cost": "\uE1D3",
    "savings": "\uE1D3",
    "investment": "\uE1D3",
    "roi": "\uF149",
    # Time
    "clock": "\uE823",          # Clock
    "time": "\uE823",
    "calendar": "\uE787",
    "schedule": "\uE787",
    "deadline": "\uE823",
    # Communication
    "mail": "\uE715",
    "message": "\uE8BD",
    "phone": "\uE717",
    "contact": "\uE77B",
    # Tech / cloud
    "cloud": "\uE753",          # Cloud
    "server": "\uEDA2",         # StorageOptical
    "database": "\uE968",       # Database
    "api": "\uE943",            # Code
    "code": "\uE943",
    "device": "\uE770",         # Devices
    # Global / scale
    "globe": "\uE774",
    "world": "\uE774",
    "global": "\uE774",
    "scale": "\uE8A3",          # ZoomOut
    "network": "\uE968",        # NetworkConnected
    "connection": "\uE968",
    # Quality / approval
    "check": "\uE73E",
    "quality": "\uE73E",
    "star": "\uE735",           # FavoriteStar
    "premium": "\uE735",
    "excellence": "\uED15",     # Trophy
    # Documents / knowledge
    "document": "\uE8A5",
    "report": "\uE9F9",
    "contract": "\uE8A5",
    "knowledge": "\uE82D",      # Library
    # Action / movement
    "rocket": "\uEF1C",         # Rocket (Fluent)
    "launch": "\uEF1C",
    "deploy": "\uEF1C",
    "build": "\uE90F",          # Construction
    "grow": "\uF149",
    # Business entities
    "building": "\uEB24",       # BuildingRetail
    "company": "\uEB24",
    "enterprise": "\uEB24",
    "factory": "\uE9F3",        # Manufacturing
    "retail": "\uEB24",
    # Default / fallback used when the LLM supplies an unknown keyword
    "default": "\uE8A9",        # Triangle bullet
}


def _resolve_icon(hint: Optional[str]) -> str:
    """Return a Segoe MDL2/Fluent glyph for the given semantic hint.
    Unknown/empty hints resolve to a neutral bullet.
    """
    if not hint:
        return ICON_CATALOG["default"]
    key = str(hint).strip().lower().replace("-", "_").replace(" ", "_")
    return ICON_CATALOG.get(key, ICON_CATALOG["default"])

THEMES = {
    # ── AURORA ── editorial, warm, contemporary. Paper-cream canvas with
    # a single bold coral accent and midnight-ink type. Inspired by Linear /
    # Stripe / editorial print design. This is the flagship modern default.
    "aurora": {
        "bg": RGBColor(0xFA, 0xF9, 0xF6),                # warm paper
        "bg_alt": RGBColor(0xF1, 0xED, 0xE4),            # soft sand
        "title_color": RGBColor(0x0B, 0x14, 0x26),       # midnight ink
        "text_color": RGBColor(0x1F, 0x29, 0x37),        # deep slate
        "accent": RGBColor(0xF2, 0x6B, 0x4F),            # sunset coral
        "accent_2": RGBColor(0x2E, 0x3A, 0x59),          # indigo navy
        "subtitle_color": RGBColor(0x47, 0x55, 0x69),
        "muted": RGBColor(0xA8, 0xA2, 0x9E),             # warm stone
        "card_bg": RGBColor(0xFF, 0xFF, 0xFF),
        "card_text": RGBColor(0x1F, 0x29, 0x37),
        "badge_color": RGBColor(0xE5, 0xA4, 0x4C),       # honey
    },
    # ── MIDNIGHT ── premium dark with glowing coral + electric sky accents.
    "midnight": {
        "bg": RGBColor(0x0B, 0x12, 0x20),                # deep navy-black
        "bg_alt": RGBColor(0x14, 0x1B, 0x2E),
        "title_color": RGBColor(0xF5, 0xF3, 0xEF),
        "text_color": RGBColor(0xD1, 0xD5, 0xDB),
        "accent": RGBColor(0xFF, 0x6B, 0x47),            # glowing coral
        "accent_2": RGBColor(0x60, 0xA5, 0xFA),          # electric sky
        "subtitle_color": RGBColor(0x9C, 0xA3, 0xAF),
        "muted": RGBColor(0x4B, 0x55, 0x63),
        "card_bg": RGBColor(0x1A, 0x21, 0x38),
        "card_text": RGBColor(0xE5, 0xE7, 0xEB),
        "badge_color": RGBColor(0xFC, 0xD3, 0x4D),
    },
    "professional": {
        "bg": RGBColor(0xFF, 0xFF, 0xFF),
        "bg_alt": RGBColor(0xF5, 0xF6, 0xF8),
        "title_color": RGBColor(0x0F, 0x1A, 0x2E),       # deep slate-ink for stronger hierarchy
        "text_color": RGBColor(0x2D, 0x35, 0x44),
        "accent": RGBColor(0xE0, 0x42, 0x2E),            # confident vermilion (richer than orange)
        "accent_2": RGBColor(0x1F, 0x3A, 0x5F),          # ocean navy
        "subtitle_color": RGBColor(0x55, 0x5D, 0x6C),
        "muted": RGBColor(0xB7, 0xBE, 0xC9),             # softer muted
        "card_bg": RGBColor(0xFB, 0xFC, 0xFD),
        "card_text": RGBColor(0x2D, 0x35, 0x44),
        "badge_color": RGBColor(0xFF, 0xB8, 0x00),
    },
    "modern": {
        "bg": RGBColor(0xF7, 0xF9, 0xFA),
        "bg_alt": RGBColor(0xEA, 0xF1, 0xF4),
        "title_color": RGBColor(0x0B, 0x1A, 0x2D),
        "text_color": RGBColor(0x2A, 0x33, 0x42),
        "accent": RGBColor(0x00, 0x8C, 0x95),            # vivid teal — modern saas
        "accent_2": RGBColor(0xFF, 0x7A, 0x59),          # warm coral counterpoint
        "subtitle_color": RGBColor(0x4B, 0x55, 0x63),
        "muted": RGBColor(0xB4, 0xBE, 0xCB),
        "card_bg": RGBColor(0xFF, 0xFF, 0xFF),
        "card_text": RGBColor(0x2A, 0x33, 0x42),
        "badge_color": RGBColor(0xFF, 0xB8, 0x00),
    },
    "dark": {
        "bg": RGBColor(0x0B, 0x10, 0x1E),
        "bg_alt": RGBColor(0x16, 0x1F, 0x33),
        "title_color": RGBColor(0xFF, 0xFF, 0xFF),
        "text_color": RGBColor(0xCF, 0xD6, 0xE2),
        "accent": RGBColor(0x00, 0xD2, 0xFF),
        "accent_2": RGBColor(0x7A, 0x5A, 0xFF),
        "subtitle_color": RGBColor(0x99, 0xA4, 0xBB),
        "muted": RGBColor(0x66, 0x72, 0x8A),
        "card_bg": RGBColor(0x16, 0x1F, 0x33),
        "card_text": RGBColor(0xE2, 0xE8, 0xF2),
        "badge_color": RGBColor(0xFF, 0xB8, 0x00),
    },
    "vibrant": {
        "bg": RGBColor(0xFF, 0xFF, 0xFF),
        "bg_alt": RGBColor(0xFA, 0xF1, 0xFF),
        "title_color": RGBColor(0x2E, 0x12, 0x57),
        "text_color": RGBColor(0x33, 0x33, 0x33),
        "accent": RGBColor(0xFF, 0x6B, 0x35),
        "accent_2": RGBColor(0x6C, 0x3A, 0xB0),
        "subtitle_color": RGBColor(0x6B, 0x4F, 0x8F),
        "muted": RGBColor(0x9A, 0x90, 0xAB),
        "card_bg": RGBColor(0xFA, 0xF1, 0xFF),
        "card_text": RGBColor(0x33, 0x2A, 0x45),
        "badge_color": RGBColor(0xFF, 0xB8, 0x00),
    },
    # Consulting / brand-compliant palette — deep red titles + vivid orange
    # accents on white. Primary #8F1917, Secondary #FF6700.
    "consulting": {
        "bg": RGBColor(0xFF, 0xFF, 0xFF),
        "bg_alt": RGBColor(0xFB, 0xF5, 0xEE),
        "title_color": RGBColor(0x8F, 0x19, 0x17),      # primary — deep red #8F1917
        "text_color": RGBColor(0x2B, 0x2B, 0x2B),
        "accent": RGBColor(0xFF, 0x67, 0x00),            # secondary — orange #FF6700
        "accent_2": RGBColor(0x8F, 0x19, 0x17),          # primary red for section markers
        "subtitle_color": RGBColor(0x55, 0x55, 0x55),
        "muted": RGBColor(0x88, 0x88, 0x88),
        "card_bg": RGBColor(0xFA, 0xF4, 0xEE),
        "card_text": RGBColor(0x2B, 0x2B, 0x2B),
        "badge_color": RGBColor(0xFF, 0xB8, 0x00),
    },
    # Brand-strict PwC palette — hex values from the brand guideline JSON.
    # Orange #DC6900 is reserved for HIGHLIGHTS only; base is black on white.
    # Titles lean black (not red) to keep orange the single accent per slide.
    "pwc": {
        "bg": RGBColor(0xFF, 0xFF, 0xFF),
        "bg_alt": RGBColor(0xF7, 0xF7, 0xF7),
        "title_color": RGBColor(0x00, 0x00, 0x00),
        "text_color": RGBColor(0x1A, 0x1A, 0x1A),
        "accent": RGBColor(0xDC, 0x69, 0x00),     # primary orange — highlight rule
        "accent_2": RGBColor(0xE0, 0x30, 0x1E),   # brand red — sparing, section markers
        "subtitle_color": RGBColor(0x3C, 0x3C, 0x3C),
        "muted": RGBColor(0x6E, 0x6E, 0x6E),
        "card_bg": RGBColor(0xF7, 0xF7, 0xF7),
        "card_text": RGBColor(0x1A, 0x1A, 0x1A),
        "badge_color": RGBColor(0xFF, 0xB8, 0x00),
        "brand_font_heading": FONT_PWC_HEADING,
        "brand_font_body": FONT_PWC_BODY,
        "brand_name": "PwC",
    },
}


# ─────────── low-level helpers ───────────

def _set_slide_bg(slide, color: RGBColor):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _add_accent_bar(slide, theme: Dict, position="top", thickness_in: float = 0.08):
    if position == "top":
        left, top = Inches(0), Inches(0)
    else:
        left, top = Inches(0), Inches(SLIDE_H_IN - thickness_in)
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, SLIDE_W, Inches(thickness_in))
    shape.fill.solid()
    shape.fill.fore_color.rgb = theme["accent"]
    shape.line.fill.background()


def _style_paragraph(p, text: str, size_pt: int, color: RGBColor, bold: bool = False,
                      italic: bool = False, font: Optional[str] = None, alignment=PP_ALIGN.LEFT):
    # Resolve at call time so the brand-font override in build_pptx takes effect.
    if font is None:
        font = FONT_BODY
    p.text = _sanitize_display_text(text)
    p.alignment = alignment
    p.font.size = Pt(size_pt)
    p.font.color.rgb = color
    p.font.bold = bold
    p.font.italic = italic
    p.font.name = font
    # Force font on the underlying run too (python-pptx sometimes drops it)
    for run in p.runs:
        run.font.name = font
        run.font.size = Pt(size_pt)
        run.font.color.rgb = color
        run.font.bold = bold
        run.font.italic = italic


def _sanitize_display_text(text: Any) -> str:
    """Normalize markdown-like artifacts into clean slide copy."""
    s = str(text or "")
    if not s:
        return ""
    # Markdown emphasis/code markers.
    s = re.sub(r"(\*\*|__)(.*?)\1", r"\2", s)
    s = re.sub(r"(?<!`)`([^`]+)`(?!`)", r"\1", s)
    # Leading list/heading markers that leak from model output.
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", s)
    s = re.sub(r"(?m)^\s*[-*•]\s+", "", s)
    s = re.sub(r"(?m)^\s*\d+\.\s+", "", s)
    # Collapse excessive whitespace/newlines.
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _add_text_box(slide, left, top, width, height, text, size_pt, color,
                   bold=False, italic=False, font: Optional[str] = None, alignment=PP_ALIGN.LEFT,
                   anchor=MSO_ANCHOR.TOP, shrink: bool = False):
    """Add a text box. When ``shrink=True`` PowerPoint's normAutofit kicks in
    at render time so text shrinks to fit instead of overflowing the box."""
    if font is None:
        font = FONT_BODY
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf = txBox.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = Inches(0.05)
    tf.margin_right = Inches(0.05)
    tf.margin_top = Inches(0.02)
    tf.margin_bottom = Inches(0.02)
    _style_paragraph(tf.paragraphs[0], text, size_pt, color, bold=bold, italic=italic, font=font, alignment=alignment)
    if shrink:
        try:
            tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        except Exception:
            pass
    return txBox


def _add_image_safe(slide, image_path: Optional[str], left, top, width, height) -> bool:
    if image_path and os.path.exists(image_path):
        try:
            slide.shapes.add_picture(image_path, left, top, width, height)
            return True
        except Exception as e:
            print(f"⚠️ Failed to add image: {e}")
    return False


def _add_background_image(slide, image_path: Optional[str]) -> bool:
    if not image_path or not os.path.exists(image_path):
        return False
    try:
        slide.shapes.add_picture(image_path, Inches(0), Inches(0), SLIDE_W, SLIDE_H)
        return True
    except Exception as e:
        print(f"⚠️ Failed to add background image: {e}")
        return False


def _add_dark_overlay(slide, opacity_pct: int = 60):
    overlay = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), SLIDE_W, SLIDE_H)
    overlay.fill.solid()
    overlay.fill.fore_color.rgb = RGBColor(0x00, 0x00, 0x00)
    alpha_val = int((opacity_pct / 100) * 100000)
    spPr = overlay._element.find(qn('p:spPr'))
    if spPr is not None:
        solid_fill = spPr.find(qn('a:solidFill'))
        if solid_fill is not None:
            srgb = solid_fill.find(qn('a:srgbClr'))
            if srgb is not None:
                alpha = srgb.makeelement(qn('a:alpha'), {})
                alpha.set('val', str(alpha_val))
                srgb.append(alpha)
    overlay.line.fill.background()


def _set_shape_alpha(shape, alpha_pct: int):
    """Apply an alpha (0–100) to a solid-fill shape's srgb fill.
    Used for ultra-soft hairlines, frosted cards, and tinted overlays.
    """
    try:
        spPr = shape._element.find(qn('p:spPr'))
        if spPr is None:
            return
        solid_fill = spPr.find(qn('a:solidFill'))
        if solid_fill is None:
            return
        srgb = solid_fill.find(qn('a:srgbClr'))
        if srgb is None:
            return
        # Clear any prior alpha then append new
        for prev in srgb.findall(qn('a:alpha')):
            srgb.remove(prev)
        alpha = srgb.makeelement(qn('a:alpha'), {})
        alpha.set('val', str(max(0, min(100, alpha_pct)) * 1000))
        srgb.append(alpha)
    except Exception:
        pass


def _add_shape_shadow(shape, blur_pt: int = 18, dist_pt: int = 4,
                       alpha_pct: int = 16, direction_deg: int = 5400000):
    """Attach a soft outer shadow to a shape via raw OOXML.

    Modern decks lean on subtle elevation — flat shapes without shadow
    read as a wireframe. ``direction_deg`` is in 60000ths of a degree
    (OOXML convention) — default is 90° (shadow drops straight down).
    """
    try:
        spPr = shape._element.find(qn('p:spPr'))
        if spPr is None:
            return
        # Remove any inherited shadow element first
        existing = spPr.find(qn('a:effectLst'))
        if existing is not None:
            spPr.remove(existing)
        from lxml import etree
        nsmap = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
        effect_xml = (
            f'<a:effectLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            f'<a:outerShdw blurRad="{blur_pt * 12700}" dist="{dist_pt * 12700}" '
            f'dir="{direction_deg}" algn="ctr" rotWithShape="0">'
            f'<a:srgbClr val="000000"><a:alpha val="{alpha_pct * 1000}"/></a:srgbClr>'
            f'</a:outerShdw></a:effectLst>'
        )
        spPr.append(etree.fromstring(effect_xml))
    except Exception:
        pass


def _add_soft_hairline(slide, left_in: float, top_in: float, width_in: float,
                        color: RGBColor, thickness_in: float = 0.008,
                        alpha_pct: int = 35):
    """Ultra-soft horizontal divider — lighter than the muted palette colour
    so rows breathe without harsh lines. Premium decks always use these."""
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(width_in), Inches(thickness_in),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = color
    rule.line.fill.background()
    rule.shadow.inherit = False
    _set_shape_alpha(rule, alpha_pct)
    return rule


def _add_vertical_hairline(slide, left_in: float, top_in: float, height_in: float,
                             color: RGBColor, thickness_in: float = 0.008,
                             alpha_pct: int = 30):
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(thickness_in), Inches(height_in),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = color
    rule.line.fill.background()
    rule.shadow.inherit = False
    _set_shape_alpha(rule, alpha_pct)
    return rule


def _add_rounded_card(slide, left, top, width, height, fill_color: RGBColor,
                       border_color: Optional[RGBColor] = None,
                       shadow: bool = False, corner: float = 0.06):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.adjustments[0] = corner
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(0.75)
    else:
        shape.line.fill.background()
    shape.shadow.inherit = False
    if shadow:
        _add_shape_shadow(shape, blur_pt=22, dist_pt=5, alpha_pct=12)
    return shape


def _add_elevated_card(slide, left_in: float, top_in: float, width_in: float,
                         height_in: float, theme: Dict,
                         accent_stripe: Optional[str] = None,
                         corner: float = 0.05):
    """Premium card: subtle fill, soft drop-shadow, optional 3pt accent stripe
    on left or top. This is the workhorse modern container.

    ``accent_stripe`` = None | "left" | "top".
    """
    card = _add_rounded_card(
        slide, Inches(left_in), Inches(top_in), Inches(width_in), Inches(height_in),
        theme.get("card_bg", theme["bg"]), shadow=True, corner=corner,
    )
    if accent_stripe == "left":
        stripe = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left_in), Inches(top_in + 0.18),
            Inches(0.06), Inches(height_in - 0.36),
        )
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = theme["accent"]
        stripe.line.fill.background()
        stripe.shadow.inherit = False
    elif accent_stripe == "top":
        stripe = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left_in + 0.2), Inches(top_in),
            Inches(min(0.8, width_in * 0.25)), Inches(0.06),
        )
        stripe.fill.solid()
        stripe.fill.fore_color.rgb = theme["accent"]
        stripe.line.fill.background()
        stripe.shadow.inherit = False
    return card


def _add_title_block(slide, title: str, theme: Dict, color: Optional[RGBColor] = None,
                      eyebrow: Optional[str] = None):
    """Modern editorial title block.

    Layout: short uppercase eyebrow tag (accent), then a confident left-aligned
    display title (30pt bold), then a precise 3pt accent rule that tucks under
    the first word. Whitespace-forward; no heavy chrome.
    """
    left_margin = 0.6
    eyebrow_top = 0.5
    title_top = 0.85 if eyebrow else 0.65
    title_height = 1.05

    if eyebrow:
        # Eyebrow square + uppercase tag
        sq = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left_margin), Inches(eyebrow_top + 0.11),
            Inches(0.13), Inches(0.06),
        )
        sq.fill.solid()
        sq.fill.fore_color.rgb = theme["accent"]
        sq.line.fill.background()
        sq.shadow.inherit = False
        _add_text_box(
            slide, Inches(left_margin + 0.25), Inches(eyebrow_top),
            Inches(SLIDE_W_IN - left_margin - 1.2), Inches(0.3),
            eyebrow.upper(), size_pt=10, color=theme["accent"], bold=True,
            font=FONT_HEADING,
        )

    # Display title — bigger, more confident; shrink-to-fit if it's very long
    t_len = len(title or "")
    title_pt = 30 if t_len <= 60 else (26 if t_len <= 90 else 22)
    _add_text_box(
        slide, Inches(left_margin), Inches(title_top),
        Inches(SLIDE_W_IN - left_margin - 0.75), Inches(title_height),
        title, size_pt=title_pt, color=color or theme["title_color"],
        bold=True, font=FONT_HEADING, shrink=True,
    )

    # Precise accent rule underneath — confident, not a hairline
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_margin), Inches(title_top + title_height + 0.05),
        Inches(0.7), Inches(0.05),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = theme["accent"]
    rule.line.fill.background()
    rule.shadow.inherit = False


def _add_icon_glyph(slide, left_in: float, top_in: float, size_in: float,
                     glyph: str, color: RGBColor, glyph_pt: Optional[int] = None):
    """Render a Segoe Fluent Icons glyph inside a bounding square.

    The glyph is vector and scales cleanly — this is the native Windows
    icon stack and requires no bundled assets.
    """
    size_pt = glyph_pt if glyph_pt is not None else max(16, int(size_in * 48))
    txBox = slide.shapes.add_textbox(
        Inches(left_in), Inches(top_in), Inches(size_in), Inches(size_in),
    )
    tf = txBox.text_frame
    tf.margin_left = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_bottom = Inches(0)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    p.text = glyph
    for run in p.runs:
        run.font.name = FONT_ICONS
        run.font.size = Pt(size_pt)
        run.font.color.rgb = color
        run.font.bold = False
        # python-pptx doesn't expose eastAsia/cs font easily — set directly on XML
        try:
            rPr = run._r.get_or_add_rPr()
            from pptx.oxml.ns import qn as _qn
            latin = rPr.find(_qn("a:latin"))
            if latin is not None:
                latin.set("typeface", FONT_ICONS)
        except Exception:
            pass
    return txBox


def _add_icon_tile(slide, left_in: float, top_in: float, size_in: float,
                    theme: Dict, glyph: str, style: str = "filled"):
    """Rounded tile with a semantic icon inside — use for icon_grid/process_flow.

    ``style`` = "filled" (accent background, white glyph) or "outline"
    (white background, accent glyph, thin accent border).
    """
    tile = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left_in), Inches(top_in), Inches(size_in), Inches(size_in),
    )
    tile.adjustments[0] = 0.15
    tile.shadow.inherit = False
    if style == "outline":
        tile.fill.solid()
        tile.fill.fore_color.rgb = theme["bg"]
        tile.line.color.rgb = theme["accent"]
        tile.line.width = Pt(1.25)
        glyph_color = theme["accent"]
    else:
        tile.fill.solid()
        tile.fill.fore_color.rgb = theme["accent"]
        tile.line.fill.background()
        glyph_color = RGBColor(0xFF, 0xFF, 0xFF)
    _add_icon_glyph(
        slide, left_in, top_in, size_in, glyph, glyph_color,
        glyph_pt=max(18, int(size_in * 42)),
    )
    return tile


def _add_number_badge(slide, left_in: float, top_in: float, size_in: float,
                       theme: Dict, number: int, style: str = "filled"):
    """Modern numbered badge — rounded square with bold "01/02/…" inside.

    Replaces letter/emoji icon fallbacks that make decks look unpolished.
    ``style`` = "filled" (accent bg, white text) or "outline" (white bg,
    accent border + accent text) for lighter rhythm on icon grids.
    """
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(left_in), Inches(top_in), Inches(size_in), Inches(size_in),
    )
    shape.adjustments[0] = 0.18
    shape.shadow.inherit = False
    if style == "outline":
        shape.fill.solid()
        shape.fill.fore_color.rgb = theme["bg"]
        shape.line.color.rgb = theme["accent"]
        shape.line.width = Pt(1.5)
        text_color = theme["accent"]
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = theme["accent"]
        shape.line.fill.background()
        text_color = RGBColor(0xFF, 0xFF, 0xFF)

    # Pick label font so it scales with the badge
    label_pt = max(14, int(size_in * 28))
    _add_text_box(
        slide, Inches(left_in), Inches(top_in),
        Inches(size_in), Inches(size_in),
        f"{number:02d}", size_pt=label_pt, color=text_color,
        bold=True, font=FONT_HEADING,
        alignment=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
    )
    return shape


def _add_left_rail(slide, theme: Dict, top_in: float = 1.7, height_in: float = 5.2):
    """Thin accent rail down the left margin — a small modern detail
    that gives content slides a premium editorial feel.
    """
    rail = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.58), Inches(top_in),
        Inches(0.04), Inches(height_in),
    )
    rail.fill.solid()
    rail.fill.fore_color.rgb = theme["accent"]
    rail.line.fill.background()


def _add_dark_sidebar(slide, width_in: float = 0.35, color: Optional[RGBColor] = None):
    """Full-height dark sidebar on the left edge — matches reference layout."""
    sidebar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0), Inches(0),
        Inches(width_in), SLIDE_H,
    )
    sidebar.fill.solid()
    sidebar.fill.fore_color.rgb = color or RGBColor(0x2D, 0x2D, 0x2D)
    sidebar.line.fill.background()


def _add_title_banner(slide, title: str, theme: Dict, sidebar_w: float = 0.35,
                       top_in: float = 0.35, height_in: float = 0.85):
    """Accent-coloured title banner spanning from the sidebar to the right edge
    with white text — matches the reference slide image layout.
    """
    banner_left = Inches(sidebar_w)
    banner_width = Inches(SLIDE_W_IN - sidebar_w - 0.7)  # leave room for icon
    banner = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, banner_left, Inches(top_in),
        banner_width, Inches(height_in),
    )
    banner.fill.solid()
    banner.fill.fore_color.rgb = theme["accent"]
    banner.line.fill.background()
    _add_text_box(
        slide, Inches(sidebar_w + 0.2), Inches(top_in + 0.08),
        Inches(SLIDE_W_IN - sidebar_w - 1.2), Inches(height_in - 0.16),
        title, size_pt=22, color=RGBColor(0xFF, 0xFF, 0xFF),
        bold=True, font=FONT_HEADING, anchor=MSO_ANCHOR.MIDDLE,
    )


def _add_slide_number_badge(slide, theme: Dict, slide_num: int):
    """Orange rounded-square badge at bottom-right with the slide number."""
    badge_size = 0.5
    badge = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE,
        Inches(SLIDE_W_IN - badge_size - 0.3), Inches(SLIDE_H_IN - badge_size - 0.25),
        Inches(badge_size), Inches(badge_size),
    )
    badge.adjustments[0] = 0.15
    badge.fill.solid()
    badge.fill.fore_color.rgb = theme["accent"]
    badge.line.fill.background()
    badge.shadow.inherit = False
    _add_text_box(
        slide,
        Inches(SLIDE_W_IN - badge_size - 0.3), Inches(SLIDE_H_IN - badge_size - 0.25),
        Inches(badge_size), Inches(badge_size),
        f"{slide_num:02d}", size_pt=14, color=RGBColor(0xFF, 0xFF, 0xFF),
        bold=True, font=FONT_HEADING,
        alignment=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
    )


def _add_footer_logo(slide, left_in: float, baseline_y_in: float,
                      height_in: float = 0.28):
    """Compact PwC logo anchored into a slide footer. Used on every slide for
    a modern, understated brand mark (logo-left / page-number-right rhythm).
    """
    if not os.path.exists(PWC_LOGO_PATH):
        return None
    logo_w = height_in * 1.57  # preserve logo aspect ratio
    return slide.shapes.add_picture(
        PWC_LOGO_PATH,
        Inches(left_in), Inches(baseline_y_in),
        Inches(logo_w), Inches(height_in),
    )


def _add_title_footer_logo(slide):
    """Logo-only footer for cover / title slides — no rule, no page number,
    just the brand mark bottom-left so the cover stays clean."""
    _add_footer_logo(slide, left_in=0.5, baseline_y_in=SLIDE_H_IN - 0.55,
                      height_in=0.34)


def _add_pwc_footer(slide, theme: Dict, slide_num: int, total: int):
    """PwC brand chrome — thin orange rule with the PwC logo anchored
    bottom-left and the page number bottom-right. Strict light-background
    treatment; no dark strip, no heavy decoration.
    """
    rule_y = SLIDE_H_IN - 0.55
    # Thin orange baseline rule spanning the safe area
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0.5), Inches(rule_y),
        Inches(SLIDE_W_IN - 1.0), Inches(0.02),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = theme["accent"]
    rule.line.fill.background()

    # PwC logo bottom-left, just under the rule
    _add_footer_logo(slide, left_in=0.5, baseline_y_in=rule_y + 0.1,
                      height_in=0.3)

    # Page number bottom-right in orange — PwCNext bold
    _add_text_box(
        slide, Inches(SLIDE_W_IN - 1.4), Inches(rule_y + 0.16),
        Inches(1.0), Inches(0.3),
        f"{slide_num:02d} / {total:02d}",
        size_pt=10, color=theme["accent"],
        bold=True, font=FONT_HEADING,
        alignment=PP_ALIGN.RIGHT,
    )


def _pwc_add_logo_topleft(slide):
    """Legacy top-left PwC logo placement. Kept for backward compatibility;
    current chrome places the logo in the footer instead."""
    if not os.path.exists(PWC_LOGO_PATH):
        return
    logo_h = 0.42
    logo_w = logo_h * 1.57  # preserve logo aspect ratio
    slide.shapes.add_picture(
        PWC_LOGO_PATH,
        Inches(0.5), Inches(0.35),
        Inches(logo_w), Inches(logo_h),
    )


def _add_minimal_footer(slide, theme: Dict, slide_num: int, total: int,
                         deck_label: Optional[str] = None):
    """Minimal editorial footer — a thin hairline, the PwC logo bottom-left,
    an optional muted deck label next to it, and a two-digit page number on
    the right. Contemporary convention with a subtle brand mark."""
    # Hairline just above footer baseline
    rule_y = SLIDE_H_IN - 0.52
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0.6), Inches(rule_y),
        Inches(SLIDE_W_IN - 1.2), Inches(0.008),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = theme["muted"]
    rule.line.fill.background()

    # PwC logo bottom-left
    logo_h = 0.26
    logo_left = 0.6
    logo_top = rule_y + 0.12
    _add_footer_logo(slide, left_in=logo_left, baseline_y_in=logo_top,
                      height_in=logo_h)

    # Optional muted deck label, placed to the right of the logo with a
    # thin vertical separator — keeps the label visually tethered to the mark
    if deck_label:
        sep_x = logo_left + logo_h * 1.57 + 0.18
        sep = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(sep_x), Inches(logo_top + 0.02),
            Inches(0.01), Inches(logo_h - 0.04),
        )
        sep.fill.solid()
        sep.fill.fore_color.rgb = theme["muted"]
        sep.line.fill.background()
        _add_text_box(
            slide, Inches(sep_x + 0.1), Inches(logo_top + 0.04),
            Inches(5.0), Inches(logo_h),
            deck_label.upper(), size_pt=8, color=theme["muted"],
            bold=False, font=FONT_BODY,
        )

    # Page number bottom-right — accent digit + muted /total
    page_w = 1.0
    _add_text_box(
        slide, Inches(SLIDE_W_IN - 0.6 - page_w), Inches(logo_top + 0.04),
        Inches(page_w), Inches(0.3),
        f"{slide_num:02d}", size_pt=10, color=theme["accent"],
        bold=True, font=FONT_HEADING,
        alignment=PP_ALIGN.RIGHT,
    )
    _add_text_box(
        slide, Inches(SLIDE_W_IN - 0.6 - page_w - 0.55), Inches(logo_top + 0.06),
        Inches(0.5), Inches(0.3),
        f"/ {total:02d}", size_pt=8, color=theme["muted"],
        font=FONT_BODY, alignment=PP_ALIGN.RIGHT,
    )


def _add_deck_footer(slide, theme: Dict, slide_num: int, total: int,
                      deck_label: Optional[str] = None):
    """Theme-aware footer dispatch. ``pwc`` uses the brand-strict light
    baseline; everything else gets the modern minimal footer."""
    if theme.get("brand_name") == "PwC":
        _add_pwc_footer(slide, theme, slide_num, total)
    else:
        _add_minimal_footer(slide, theme, slide_num, total, deck_label=deck_label)


# ─────────── PwC brand-strict primitives ───────────
# These helpers enforce the PwC brand guideline: black/white base, orange
# reserved for highlights, left-aligned PwCNext type, whitespace-first,
# no decorative noise (no eyebrow dots, no vertical bars, no medallions).


def _is_pwc(theme: Dict) -> bool:
    return theme.get("brand_name") == "PwC"


def _pwc_title_block(slide, title: str, theme: Dict, size_pt: int = 22,
                      left_in: float = 0.5, top_in: float = 1.05):
    """PwC title treatment: black bold heading, left-aligned, with a short
    orange rule underneath. That is the brand-strict convention — no eyebrow
    dots, no vertical accent bars, no extra chrome.
    """
    title_w = SLIDE_W_IN - left_in - 0.75
    _add_text_box(
        slide, Inches(left_in), Inches(top_in),
        Inches(title_w), Inches(0.9),
        title, size_pt=size_pt, color=theme["title_color"],
        bold=True, font=FONT_HEADING,
    )
    # Short orange rule below title — highlight marker only
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(left_in), Inches(top_in + 0.95),
        Inches(0.85), Inches(0.04),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = theme["accent"]
    rule.line.fill.background()


def _pwc_bullet_marker(slide, left_in: float, top_in: float,
                        color: Optional[RGBColor] = None, size_in: float = 0.11):
    """Small flat orange square — the PwC-strict bullet marker."""
    sq = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(size_in), Inches(size_in),
    )
    sq.fill.solid()
    sq.fill.fore_color.rgb = color or RGBColor(0xDC, 0x69, 0x00)
    sq.line.fill.background()
    sq.shadow.inherit = False
    return sq


def _pwc_short_rule(slide, left_in: float, top_in: float,
                     width_in: float = 0.6, color: Optional[RGBColor] = None,
                     thickness_in: float = 0.035):
    """Short horizontal orange rule — highlight element, sparingly used."""
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(width_in), Inches(thickness_in),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = color or RGBColor(0xDC, 0x69, 0x00)
    rule.line.fill.background()
    return rule


def _pwc_apply_chrome(slide, theme: Dict, slide_num: int, total: int,
                       is_title: bool = False):
    """Apply PwC brand chrome: orange footer rule with the PwC logo
    bottom-left and the page number bottom-right. Title slides get a
    logo-only footer so the cover stays cleanest."""
    if is_title:
        _add_title_footer_logo(slide)
        return
    _add_pwc_footer(slide, theme, slide_num, total)


def _add_check_icon(slide, theme: Dict, right_margin: float = 0.25, top_in: float = 0.35,
                     size_in: float = 0.65):
    """Accent-coloured checkmark icon in the top-right — matches reference layout."""
    icon_left = SLIDE_W_IN - size_in - right_margin
    _add_icon_glyph(
        slide, icon_left, top_in, size_in,
        "\uE73E",  # CheckMark glyph
        theme["accent"], glyph_pt=32,
    )


# ── Reference-image card-slide helpers ──────────────────────────────────
# Recreates the exact layout from the attached reference:
#   • White bg, bold dark title top-left
#   • Orange geometric corner (right-triangle) top-right, white icon inside
#   • Orange-tinted image strip behind cards
#   • Each card: orange banner header + gold number badge (overlapping
#     top-right of banner) + body paragraph text below
#   • Thin accent rule near bottom
#   • Small stacked-square slide number badge bottom-right


def _add_corner_triangle(slide, theme: Dict, icon_glyph: str = "\uE945"):
    """Orange right-triangle in the top-right corner with a white icon inside.
    Mimics the geometric brand element in the reference image.
    """
    # Triangle is approximated via a rectangle rotated + clipped.
    # python-pptx doesn't support rotation well, so we use a large
    # right-triangle shape.
    tri_size = 1.8  # inches
    tri = slide.shapes.add_shape(
        MSO_SHAPE.RIGHT_TRIANGLE,
        Inches(SLIDE_W_IN - tri_size), Inches(0),
        Inches(tri_size), Inches(tri_size),
    )
    tri.fill.solid()
    tri.fill.fore_color.rgb = theme["accent"]
    tri.line.fill.background()
    tri.rotation = 90.0  # so the right-angle is at the top-right corner

    # White icon inside the triangle area
    _add_icon_glyph(
        slide, SLIDE_W_IN - 1.05, 0.35, 0.65,
        icon_glyph, RGBColor(0xFF, 0xFF, 0xFF), glyph_pt=28,
    )


def _add_card_title_bar(slide, left_in: float, top_in: float, width_in: float,
                         height_in: float, title: str, theme: Dict, card_number: int):
    """Orange banner with white title text + gold number badge overlapping
    the top-right corner — exactly as in the reference image.
    """
    # Orange banner
    banner = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(width_in), Inches(height_in),
    )
    banner.fill.solid()
    banner.fill.fore_color.rgb = theme["accent"]
    banner.line.fill.background()

    # White title text inside the banner
    _add_text_box(
        slide, Inches(left_in + 0.15), Inches(top_in + 0.05),
        Inches(width_in - 0.6), Inches(height_in - 0.1),
        title, size_pt=15, color=RGBColor(0xFF, 0xFF, 0xFF),
        bold=True, italic=True, font=FONT_HEADING, anchor=MSO_ANCHOR.MIDDLE,
    )

    # Gold/yellow number badge overlapping top-right of banner
    badge_size = 0.48
    badge_color = theme.get("badge_color") or RGBColor(0xFF, 0xB8, 0x00)
    badge = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in + width_in - badge_size + 0.05),
        Inches(top_in - badge_size * 0.45),
        Inches(badge_size), Inches(badge_size),
    )
    badge.fill.solid()
    badge.fill.fore_color.rgb = badge_color
    badge.line.fill.background()
    badge.shadow.inherit = False
    _add_text_box(
        slide,
        Inches(left_in + width_in - badge_size + 0.05),
        Inches(top_in - badge_size * 0.45),
        Inches(badge_size), Inches(badge_size),
        f"{card_number:02d}", size_pt=15, color=RGBColor(0xFF, 0xFF, 0xFF),
        bold=True, font=FONT_HEADING,
        alignment=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
    )


def _add_bottom_accent_rule(slide, theme: Dict):
    """Thin accent-coloured horizontal rule near the slide bottom."""
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0.4), Inches(SLIDE_H_IN - 0.6),
        Inches(SLIDE_W_IN - 0.8), Inches(0.02),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = theme["accent"]
    rule.line.fill.background()


def _add_image_strip_tinted(slide, theme: Dict, left_in: float, top_in: float,
                              width_in: float, height_in: float):
    """Semi-transparent accent-tinted rectangle behind card columns —
    simulates the sepia building-image strip in the reference when no
    real image is available.
    """
    strip = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(width_in), Inches(height_in),
    )
    strip.fill.solid()
    strip.fill.fore_color.rgb = theme.get("bg_alt", RGBColor(0xF4, 0xF6, 0xFA))
    strip.line.fill.background()
    # Thin accent overlay on top for the tinted feel
    overlay = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(left_in), Inches(top_in),
        Inches(width_in), Inches(height_in),
    )
    overlay.fill.solid()
    overlay.fill.fore_color.rgb = theme["accent"]
    overlay.line.fill.background()
    # Set alpha for partial transparency
    spPr = overlay._element.find(qn('p:spPr'))
    if spPr is not None:
        solid_fill = spPr.find(qn('a:solidFill'))
        if solid_fill is not None:
            srgb = solid_fill.find(qn('a:srgbClr'))
            if srgb is not None:
                alpha = srgb.makeelement(qn('a:alpha'), {})
                alpha.set('val', '12000')  # 12% opacity
                srgb.append(alpha)


def _add_slide_footer(slide, theme: Dict, slide_num: int, total: int):
    _add_text_box(
        slide, Inches(SLIDE_W_IN - 1.6), Inches(SLIDE_H_IN - 0.45),
        Inches(1.3), Inches(0.3),
        f"{slide_num} / {total}", size_pt=10, color=theme["muted"],
        alignment=PP_ALIGN.RIGHT,
    )


# ─────────── slide builders ───────────

def build_title_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern cover: massive display title, accent block + eyebrow tag, soft
    geometric corner accent, subtitle, refined baseline. Reads as a confident
    magazine cover with deliberate negative space."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title = data.get("title", "")
    subtitle = data.get("subtitle", "")

    has_bg = _add_background_image(slide, image_path)
    if has_bg:
        _add_dark_overlay(slide, 68)
        title_color = RGBColor(0xFF, 0xFF, 0xFF)
        subtitle_color = RGBColor(0xE6, 0xEA, 0xF2)
        date_color = RGBColor(0xC9, 0xCE, 0xDA)
        eyebrow_color = theme["accent"]
        hairline_color = RGBColor(0xB8, 0xBD, 0xCC)
    else:
        _set_slide_bg(slide, theme["bg"])
        title_color = theme["title_color"]
        subtitle_color = theme["subtitle_color"]
        date_color = theme["muted"]
        eyebrow_color = theme["accent"]
        hairline_color = theme["muted"]

        # Soft geometric corner accent — large faint accent block top-right
        # gives the cover composition without taking attention from the title.
        corner = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(SLIDE_W_IN - 3.2), Inches(0),
            Inches(3.2), Inches(3.2),
        )
        corner.fill.solid()
        corner.fill.fore_color.rgb = theme["accent"]
        corner.line.fill.background()
        corner.shadow.inherit = False
        _set_shape_alpha(corner, 8)

        # Small solid accent square inside the faint block (anchor)
        anchor = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(SLIDE_W_IN - 0.95), Inches(0.6),
            Inches(0.35), Inches(0.35),
        )
        anchor.fill.solid()
        anchor.fill.fore_color.rgb = theme["accent"]
        anchor.line.fill.background()
        anchor.shadow.inherit = False

    # ── Eyebrow: accent square + uppercase tag ──
    eyebrow_top = 1.1
    sq = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(0.9), Inches(eyebrow_top + 0.12),
        Inches(0.18), Inches(0.08),
    )
    sq.fill.solid()
    sq.fill.fore_color.rgb = eyebrow_color
    sq.line.fill.background()
    sq.shadow.inherit = False
    deck_tag = str(data.get("eyebrow") or "Executive Briefing").upper()
    _add_text_box(
        slide, Inches(1.18), Inches(eyebrow_top),
        Inches(7.5), Inches(0.35),
        deck_tag,
        size_pt=11, color=eyebrow_color, bold=True, font=FONT_HEADING,
    )

    # ── Oversized display title — bigger, tighter leading via two lines if long ──
    t_len = len(title)
    title_pt = 54 if t_len <= 42 else (46 if t_len <= 70 else 38)
    _add_text_box(
        slide, Inches(0.9), Inches(2.3),
        Inches(SLIDE_W_IN - 2.6), Inches(3.0),
        title, size_pt=title_pt, color=title_color, bold=True, font=FONT_HEADING,
        shrink=True,
    )

    # ── Short bold accent rule under the title ──
    rule = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(5.35),
        Inches(1.1), Inches(0.07),
    )
    rule.fill.solid()
    rule.fill.fore_color.rgb = theme["accent"]
    rule.line.fill.background()
    rule.shadow.inherit = False

    # ── Subtitle / dek ──
    if subtitle:
        _add_text_box(
            slide, Inches(0.9), Inches(5.6),
            Inches(SLIDE_W_IN - 2.5), Inches(1.0),
            subtitle, size_pt=17, color=subtitle_color, font=FONT_BODY,
            shrink=True,
        )

    # ── Baseline row: soft hairline + date + accent stamp ──
    baseline_y = 6.7
    _add_soft_hairline(
        slide, 0.9, baseline_y, SLIDE_W_IN - 1.8,
        hairline_color, thickness_in=0.008, alpha_pct=40,
    )

    date_str = datetime.now().strftime("%B %Y").upper()
    _add_text_box(
        slide, Inches(0.9), Inches(baseline_y + 0.13),
        Inches(5), Inches(0.35),
        date_str, size_pt=10, color=date_color, bold=True, font=FONT_BODY,
    )
    _add_text_box(
        slide, Inches(SLIDE_W_IN - 2.5), Inches(baseline_y + 0.13),
        Inches(1.6), Inches(0.35),
        "CONFIDENTIAL", size_pt=10, color=theme["accent"], bold=True,
        font=FONT_BODY, alignment=PP_ALIGN.RIGHT,
    )


def build_content_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern content layout: bold display title, bullet items rendered as
    elevated micro-cards (rounded, soft shadow, accent left stripe), bigger
    body type, generous gutters. Optional right-hand image well.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    bullets = data.get("bullets", [])
    has_image = image_path and os.path.exists(image_path)

    _add_title_block(slide, data.get("title", ""), theme)

    # ── Layout geometry ──
    content_top = 2.35
    content_bottom = SLIDE_H_IN - 0.95
    content_h = content_bottom - content_top
    left_margin = 0.6

    if has_image:
        text_w = 6.6
        img_left = text_w + left_margin + 0.45
        img_w = SLIDE_W_IN - img_left - 0.6
    else:
        text_w = SLIDE_W_IN - left_margin - 0.75

    # ── Bullet stack as elevated cards ──
    n_bullets = min(len(bullets), 5)
    if n_bullets:
        gap = 0.15
        row_h = (content_h - gap * (n_bullets - 1)) / n_bullets
        row_h = min(row_h, 1.1)
        for i in range(n_bullets):
            bullet = bullets[i]
            y = content_top + i * (row_h + gap)

            _add_elevated_card(
                slide, left_margin, y, text_w, row_h, theme,
                accent_stripe="left", corner=0.05,
            )

            # Numeral inside the card
            _add_text_box(
                slide, Inches(left_margin + 0.25), Inches(y + 0.12),
                Inches(0.7), Inches(row_h - 0.24),
                f"{i + 1:02d}", size_pt=20, color=theme["accent"],
                bold=True, font=FONT_HEADING,
                anchor=MSO_ANCHOR.MIDDLE,
            )

            # Body text — bigger, sits to the right of the numeral
            _add_text_box(
                slide, Inches(left_margin + 1.0), Inches(y + 0.12),
                Inches(text_w - 1.2), Inches(row_h - 0.24),
                str(bullet), size_pt=14, color=theme["card_text"],
                font=FONT_BODY, anchor=MSO_ANCHOR.MIDDLE, shrink=True,
            )

    # ── Image well on the right with subtle accent anchor ──
    if has_image:
        _add_image_safe(
            slide, image_path,
            Inches(img_left), Inches(content_top),
            Inches(img_w), Inches(content_h),
        )
        ribbon = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(img_left), Inches(content_top + content_h + 0.05),
            Inches(1.4), Inches(0.06),
        )
        ribbon.fill.solid()
        ribbon.fill.fore_color.rgb = theme["accent"]
        ribbon.line.fill.background()
        ribbon.shadow.inherit = False


def build_section_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Dramatic section divider: full-bleed tinted background on the left
    third, massive display title on the right with a chapter number and
    subtitle. Reads like a magazine section opener."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title = data.get("title", "")
    subtitle = data.get("subtitle", "")

    has_bg = _add_background_image(slide, image_path)
    if has_bg:
        _add_dark_overlay(slide, 68)
        title_color = RGBColor(0xFF, 0xFF, 0xFF)
        subtitle_color = RGBColor(0xE8, 0xEC, 0xF4)
        accent_color = theme["accent"]
        chapter_color = RGBColor(0xFF, 0xFF, 0xFF)
    else:
        _set_slide_bg(slide, theme["bg"])
        title_color = theme["title_color"]
        subtitle_color = theme["subtitle_color"]
        accent_color = theme["accent"]
        chapter_color = theme["accent"]

        # Left-side tinted sidebar panel (one-third of the slide)
        panel_w = 4.3
        panel = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(0), Inches(0),
            Inches(panel_w), Inches(SLIDE_H_IN),
        )
        panel.fill.solid()
        panel.fill.fore_color.rgb = theme["bg_alt"]
        panel.line.fill.background()

        # Oversized decorative chapter mark inside the panel
        _add_text_box(
            slide, Inches(0.75), Inches(1.5),
            Inches(panel_w - 1), Inches(3),
            "§", size_pt=140, color=theme["accent"], bold=True, font=FONT_HEADING,
        )
        _add_text_box(
            slide, Inches(0.75), Inches(5.0),
            Inches(panel_w - 1), Inches(0.4),
            "CHAPTER", size_pt=11, color=theme["muted"], bold=True, font=FONT_HEADING,
        )

    # Right-side content area
    content_left = 4.75 if not has_bg else 1.0
    content_top = 2.4

    # Short bold accent bar above the title
    bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(content_left), Inches(content_top - 0.4),
        Inches(0.8), Inches(0.06),
    )
    bar.fill.solid()
    bar.fill.fore_color.rgb = accent_color
    bar.line.fill.background()

    # Massive title — let it breathe
    t_len = len(title)
    sec_pt = 46 if t_len <= 30 else (38 if t_len <= 56 else 32)
    _add_text_box(
        slide, Inches(content_left), Inches(content_top),
        Inches(SLIDE_W_IN - content_left - 0.75), Inches(2.6),
        title, size_pt=sec_pt, color=title_color, bold=True, font=FONT_HEADING,
        shrink=True,
    )

    if subtitle:
        _add_text_box(
            slide, Inches(content_left), Inches(content_top + 2.65),
            Inches(SLIDE_W_IN - content_left - 0.75), Inches(1.3),
            subtitle, size_pt=16, color=subtitle_color, font=FONT_BODY,
            shrink=True,
        )


def build_closing_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Minimal centered closing: oversized title flanked by two short accent
    bars, subtitle below, and a quiet date/location stamp at the baseline.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    title = data.get("title", "Thank You")
    subtitle = data.get("subtitle", "")

    has_bg = _add_background_image(slide, image_path)
    if has_bg:
        _add_dark_overlay(slide, 55)
        title_color = RGBColor(0xFF, 0xFF, 0xFF)
        subtitle_color = RGBColor(0xDD, 0xDD, 0xDD)
        accent_color = theme["accent"]
        stamp_color = RGBColor(0xBB, 0xBB, 0xCC)
    else:
        _set_slide_bg(slide, theme["bg"])
        title_color = theme["title_color"]
        subtitle_color = theme["subtitle_color"]
        accent_color = theme["accent"]
        stamp_color = theme["muted"]

    # ── Two short accent bars flanking the title (symmetric editorial mark) ──
    bar_w = 1.4
    bar_y = 3.15
    bar_h = 0.06
    center_x = SLIDE_W_IN / 2
    gap = 4.2
    left_bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(center_x - gap / 2 - bar_w), Inches(bar_y),
        Inches(bar_w), Inches(bar_h),
    )
    left_bar.fill.solid()
    left_bar.fill.fore_color.rgb = accent_color
    left_bar.line.fill.background()
    right_bar = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(center_x + gap / 2), Inches(bar_y),
        Inches(bar_w), Inches(bar_h),
    )
    right_bar.fill.solid()
    right_bar.fill.fore_color.rgb = accent_color
    right_bar.line.fill.background()

    # ── Oversized centered title ──
    t_len = len(title)
    close_pt = 64 if t_len <= 14 else (54 if t_len <= 28 else 42)
    _add_text_box(
        slide, Inches(1.0), Inches(2.7),
        Inches(SLIDE_W_IN - 2), Inches(1.7),
        title, size_pt=close_pt, color=title_color, bold=True,
        font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
        anchor=MSO_ANCHOR.MIDDLE, shrink=True,
    )

    # ── Subtitle below ──
    if subtitle:
        _add_text_box(
            slide, Inches(1.5), Inches(4.35),
            Inches(SLIDE_W_IN - 3), Inches(0.7),
            subtitle, size_pt=17,
            color=subtitle_color,
            font=FONT_BODY, alignment=PP_ALIGN.CENTER,
            shrink=True,
        )

    # ── Baseline stamp: date centred under the slide ──
    date_str = datetime.now().strftime("%B %Y").upper()
    _add_text_box(
        slide, Inches(1.5), Inches(5.35),
        Inches(SLIDE_W_IN - 3), Inches(0.4),
        f"·  {date_str}  ·", size_pt=10, color=stamp_color,
        bold=True, font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
    )


def build_stats_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern KPI wall: each stat sits inside an elevated card with a top
    accent stripe, big accent numeral, short tick rule, and tight description.
    Even spacing produces a clean dashboard rhythm."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", "Key Metrics"), theme)

    stats = data.get("stats", [])[:4]
    if not stats:
        return build_content_slide(prs, data, theme, image_path)

    n = len(stats)
    side_in = 0.6
    gap_in = 0.3
    col_w_in = (SLIDE_W_IN - 2 * side_in - gap_in * (n - 1)) / n
    card_top = 2.55
    card_h = 4.0

    for i, stat in enumerate(stats):
        left_in = side_in + i * (col_w_in + gap_in)
        value = str(stat.get("value", ""))
        label = str(stat.get("label", ""))

        # Elevated card with top accent stripe
        _add_elevated_card(
            slide, left_in, card_top, col_w_in, card_h, theme,
            accent_stripe="top", corner=0.04,
        )

        inner_left = left_in + 0.35
        inner_w = col_w_in - 0.7
        inner_top = card_top + 0.45

        # Small index label
        _add_text_box(
            slide, Inches(inner_left), Inches(inner_top),
            Inches(inner_w), Inches(0.3),
            f"{i + 1:02d}", size_pt=11, color=theme["muted"],
            bold=True, font=FONT_HEADING,
        )

        # Oversized accent numeral
        val_len = len(value)
        value_pt = 56 if val_len <= 4 else (46 if val_len <= 6 else (38 if val_len <= 8 else 30))
        _add_text_box(
            slide, Inches(inner_left), Inches(inner_top + 0.4),
            Inches(inner_w), Inches(1.5),
            value, size_pt=value_pt, color=theme["accent"],
            bold=True, font=FONT_HEADING, alignment=PP_ALIGN.LEFT,
            anchor=MSO_ANCHOR.MIDDLE, shrink=True,
        )

        # Short tick rule below numeral
        tick = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(inner_left), Inches(inner_top + 2.05),
            Inches(0.55), Inches(0.05),
        )
        tick.fill.solid()
        tick.fill.fore_color.rgb = theme["accent_2"]
        tick.line.fill.background()
        tick.shadow.inherit = False

        # Description label — bigger, more readable
        _add_text_box(
            slide, Inches(inner_left), Inches(inner_top + 2.25),
            Inches(inner_w), Inches(card_h - 2.55),
            label, size_pt=13, color=theme["card_text"],
            font=FONT_BODY, shrink=True,
        )


def build_quote_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Editorial pull-quote: oversized display quote centred in a soft tinted
    canvas, framed by a huge accent-coloured open-quote glyph, with the
    attribution set in a small uppercase tag beneath a short accent rule."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    has_bg = _add_background_image(slide, image_path)
    if has_bg:
        _add_dark_overlay(slide, 72)
        text_color = RGBColor(0xFF, 0xFF, 0xFF)
        attrib_color = RGBColor(0xDD, 0xDD, 0xDD)
    else:
        _set_slide_bg(slide, theme["bg_alt"])
        text_color = theme["title_color"]
        attrib_color = theme["subtitle_color"]

    # Huge decorative quote glyph — very soft, anchor element
    _add_text_box(
        slide, Inches(0.8), Inches(0.4),
        Inches(3), Inches(3),
        "\u201C", size_pt=220, color=theme["accent"], bold=True,
        font=FONT_HEADING,
    )

    quote = data.get("quote") or data.get("title", "")
    attribution = data.get("attribution") or data.get("subtitle", "")

    # Central quote text — serif italic, sized to wrap comfortably
    q_len = len(quote)
    quote_pt = 26 if q_len <= 140 else (22 if q_len <= 220 else 18)
    _add_text_box(
        slide, Inches(1.3), Inches(2.4),
        Inches(SLIDE_W_IN - 2.6), Inches(2.8),
        quote, size_pt=quote_pt, color=text_color, italic=True,
        font="Georgia", alignment=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE,
        shrink=True,
    )

    if attribution:
        # Short accent tick + attribution tag
        tick = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(1.3), Inches(5.4),
            Inches(0.6), Inches(0.04),
        )
        tick.fill.solid()
        tick.fill.fore_color.rgb = theme["accent"]
        tick.line.fill.background()
        _add_text_box(
            slide, Inches(1.3), Inches(5.55),
            Inches(SLIDE_W_IN - 3.2), Inches(0.6),
            attribution.upper(), size_pt=11, color=attrib_color,
            bold=True, font=FONT_HEADING,
        )


def build_comparison_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern split comparison: two elevated columns, each with a coloured
    header bar carrying the option label + title in white, then a clean
    bullet stack. A floating "VS" medallion overlaps the column gap and
    visually anchors the split."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", "Comparison"), theme)

    left_data = data.get("left", {}) or {}
    right_data = data.get("right", {}) or {}

    side_in = 0.6
    gap_in = 0.4
    col_w_in = (SLIDE_W_IN - 2 * side_in - gap_in) / 2
    card_top = 2.55
    card_h = 4.1
    header_h = 0.78
    accents = [theme["accent"], theme["accent_2"]]

    for idx, col_data in enumerate([left_data, right_data]):
        left_in = side_in + idx * (col_w_in + gap_in)
        col_title = col_data.get("title", "")
        accent_color = accents[idx]

        # Elevated column card
        _add_elevated_card(
            slide, left_in, card_top, col_w_in, card_h, theme,
            accent_stripe=None, corner=0.045,
        )

        # Coloured header band on the card
        header = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(left_in), Inches(card_top),
            Inches(col_w_in), Inches(header_h),
        )
        header.adjustments[0] = 0.045
        header.fill.solid()
        header.fill.fore_color.rgb = accent_color
        header.line.fill.background()
        header.shadow.inherit = False
        # Cover the lower rounded corners with a flat rectangle so only top is rounded
        cover = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left_in), Inches(card_top + header_h - 0.15),
            Inches(col_w_in), Inches(0.15),
        )
        cover.fill.solid()
        cover.fill.fore_color.rgb = accent_color
        cover.line.fill.background()
        cover.shadow.inherit = False

        # Option chip (A/B) inside the header
        chip_size = 0.42
        chip = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(left_in + 0.3), Inches(card_top + (header_h - chip_size) / 2),
            Inches(chip_size), Inches(chip_size),
        )
        chip.fill.solid()
        chip.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        chip.line.fill.background()
        chip.shadow.inherit = False
        _add_text_box(
            slide, Inches(left_in + 0.3), Inches(card_top + (header_h - chip_size) / 2),
            Inches(chip_size), Inches(chip_size),
            "A" if idx == 0 else "B", size_pt=14, color=accent_color,
            bold=True, font=FONT_HEADING,
            alignment=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
        )

        # White header title text
        _add_text_box(
            slide, Inches(left_in + 0.3 + chip_size + 0.2),
            Inches(card_top),
            Inches(col_w_in - chip_size - 0.7), Inches(header_h),
            col_title, size_pt=16, color=RGBColor(0xFF, 0xFF, 0xFF),
            bold=True, font=FONT_HEADING, anchor=MSO_ANCHOR.MIDDLE,
            shrink=True,
        )

        # Bullets inside the card body
        bullets = col_data.get("bullets", [])[:5]
        body_top = card_top + header_h + 0.3
        body_h = card_h - header_h - 0.5
        if bullets:
            row_h = min(0.55, body_h / len(bullets))
            for i, b in enumerate(bullets):
                y = body_top + i * row_h
                # Accent square marker
                sq = slide.shapes.add_shape(
                    MSO_SHAPE.RECTANGLE,
                    Inches(left_in + 0.35), Inches(y + 0.14),
                    Inches(0.13), Inches(0.13),
                )
                sq.fill.solid()
                sq.fill.fore_color.rgb = accent_color
                sq.line.fill.background()
                sq.shadow.inherit = False
                _add_text_box(
                    slide, Inches(left_in + 0.65), Inches(y),
                    Inches(col_w_in - 0.95), Inches(row_h),
                    str(b), size_pt=12, color=theme["card_text"],
                    font=FONT_BODY, anchor=MSO_ANCHOR.MIDDLE, shrink=True,
                )

    # Centre "VS" medallion floating between columns
    medal_sz = 0.78
    center_x = SLIDE_W_IN / 2
    medal_y = card_top + card_h / 2 - medal_sz / 2
    medal = slide.shapes.add_shape(
        MSO_SHAPE.OVAL,
        Inches(center_x - medal_sz / 2), Inches(medal_y),
        Inches(medal_sz), Inches(medal_sz),
    )
    medal.fill.solid()
    medal.fill.fore_color.rgb = theme["title_color"]
    medal.line.fill.background()
    medal.shadow.inherit = False
    _add_shape_shadow(medal, blur_pt=20, dist_pt=5, alpha_pct=20)
    _add_text_box(
        slide,
        Inches(center_x - medal_sz / 2), Inches(medal_y),
        Inches(medal_sz), Inches(medal_sz),
        "VS", size_pt=15, color=RGBColor(0xFF, 0xFF, 0xFF),
        bold=True, font=FONT_HEADING,
        alignment=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
    )


def build_two_column_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Editorial two-column list: each column is framed by a small accent
    chapter label + bold header + a short accent tick, followed by bullets
    with accent dot markers. No heavy borders — just typography and rhythm.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", ""), theme)

    left_bullets = (data.get("left") or {}).get("bullets") or data.get("left_bullets") or []
    right_bullets = (data.get("right") or {}).get("bullets") or data.get("right_bullets") or []
    left_title = (data.get("left") or {}).get("title") or data.get("left_title") or ""
    right_title = (data.get("right") or {}).get("title") or data.get("right_title") or ""

    gap_in = 0.4
    side_in = 0.6
    col_w_in = (SLIDE_W_IN - 2 * side_in - gap_in) / 2
    card_top = 2.55
    card_h = 4.1
    accents = [theme["accent"], theme["accent_2"]]

    for idx, (t, bullets) in enumerate([(left_title, left_bullets), (right_title, right_bullets)]):
        left_in = side_in + idx * (col_w_in + gap_in)
        accent_color = accents[idx]

        # Elevated column card with top accent stripe
        _add_elevated_card(
            slide, left_in, card_top, col_w_in, card_h, theme,
            accent_stripe="top", corner=0.045,
        )

        inner_left = left_in + 0.4
        inner_w = col_w_in - 0.8

        # Chapter label
        _add_text_box(
            slide, Inches(inner_left), Inches(card_top + 0.35),
            Inches(inner_w), Inches(0.3),
            f"0{idx + 1}  ·  {('PART A' if idx == 0 else 'PART B')}",
            size_pt=10, color=accent_color, bold=True, font=FONT_HEADING,
        )

        # Column header
        header_top = card_top + 0.7
        if t:
            _add_text_box(
                slide, Inches(inner_left), Inches(header_top),
                Inches(inner_w), Inches(0.55),
                t, size_pt=17, color=theme["title_color"],
                bold=True, font=FONT_HEADING, shrink=True,
            )
            # Short accent tick under header
            tick = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(inner_left), Inches(header_top + 0.6),
                Inches(0.5), Inches(0.04),
            )
            tick.fill.solid()
            tick.fill.fore_color.rgb = accent_color
            tick.line.fill.background()
            tick.shadow.inherit = False

        # Bullet stack
        bullet_top = header_top + (1.0 if t else 0.15)
        bullets = bullets[:6]
        body_h = card_h - (bullet_top - card_top) - 0.4
        row_h = min(0.5, body_h / max(1, len(bullets)))
        for i, b in enumerate(bullets):
            y = bullet_top + i * row_h
            # Accent square marker
            sq = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(inner_left), Inches(y + 0.13),
                Inches(0.11), Inches(0.11),
            )
            sq.fill.solid()
            sq.fill.fore_color.rgb = accent_color
            sq.line.fill.background()
            sq.shadow.inherit = False
            _add_text_box(
                slide, Inches(inner_left + 0.28), Inches(y),
                Inches(inner_w - 0.3), Inches(row_h),
                str(b), size_pt=12, color=theme["card_text"],
                font=FONT_BODY, anchor=MSO_ANCHOR.MIDDLE, shrink=True,
            )


def build_timeline_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern horizontal timeline: accent track with numbered nodes; each step
    gets a small elevated card holding title + description. Cards alternate
    above/below the track when there are >=4 steps for a denser rhythm
    without crowding."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", "Timeline"), theme)

    steps = data.get("steps", [])[:6]
    if not steps:
        return build_content_slide(prs, data, theme, image_path)

    n = len(steps)
    accent = theme["accent"]

    side_margin = 0.7
    line_len = SLIDE_W_IN - 2 * side_margin
    line_y = 4.4
    node_size = 0.5
    slot_w = line_len / n
    card_h = 1.45
    card_gap = 0.45

    # Accent track with low alpha
    track = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(side_margin), Inches(line_y),
        Inches(line_len), Inches(0.04),
    )
    track.fill.solid()
    track.fill.fore_color.rgb = accent
    track.line.fill.background()
    track.shadow.inherit = False
    _set_shape_alpha(track, 28)

    # End arrow (Segoe Fluent ChevronRight)
    _add_icon_glyph(
        slide, side_margin + line_len - 0.05, line_y - 0.13, 0.34,
        "\uE76C", accent, glyph_pt=18,
    )

    alternate = n >= 4

    for i, step in enumerate(steps):
        cx = side_margin + slot_w * i + slot_w / 2
        above = (i % 2 == 0) if alternate else True

        # Numbered node on the track with soft shadow
        node = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(cx - node_size / 2), Inches(line_y - node_size / 2 + 0.02),
            Inches(node_size), Inches(node_size),
        )
        node.fill.solid()
        node.fill.fore_color.rgb = accent
        node.line.color.rgb = theme["bg"]
        node.line.width = Pt(2.5)
        node.shadow.inherit = False
        _add_shape_shadow(node, blur_pt=14, dist_pt=3, alpha_pct=18)
        _add_text_box(
            slide,
            Inches(cx - node_size / 2), Inches(line_y - node_size / 2 + 0.02),
            Inches(node_size), Inches(node_size),
            f"{i + 1:02d}", size_pt=11, color=RGBColor(0xFF, 0xFF, 0xFF),
            bold=True, font=FONT_HEADING,
            alignment=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE,
        )

        # Card placement above or below the line
        card_w = slot_w - 0.2
        card_x = cx - card_w / 2
        if above:
            card_y = line_y - node_size / 2 - card_gap - card_h
            connector_y_top = card_y + card_h
        else:
            card_y = line_y + node_size / 2 + card_gap
            connector_y_top = line_y + node_size / 2

        _add_vertical_hairline(
            slide, cx - 0.004, connector_y_top, card_gap,
            theme["muted"], thickness_in=0.008, alpha_pct=50,
        )

        _add_elevated_card(
            slide, card_x, card_y, card_w, card_h, theme,
            accent_stripe="top", corner=0.06,
        )

        title_text = step.get("title", "")
        _add_text_box(
            slide, Inches(card_x + 0.2), Inches(card_y + 0.2),
            Inches(card_w - 0.4), Inches(0.4),
            title_text, size_pt=12, color=theme["title_color"],
            bold=True, font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
            shrink=True,
        )

        desc = step.get("description", "")
        if desc:
            _add_text_box(
                slide, Inches(card_x + 0.2), Inches(card_y + 0.6),
                Inches(card_w - 0.4), Inches(card_h - 0.7),
                desc, size_pt=10, color=theme["card_text"],
                font=FONT_BODY, alignment=PP_ALIGN.CENTER, shrink=True,
            )


def build_numbered_list_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern numbered list: each item is an elevated card with a large accent
    numeral on the left, bold title and clean description on the right. Even
    gap rhythm — reads as a confident roster, not a stack of paragraphs.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", ""), theme)

    items = data.get("items", [])[:5]
    if not items:
        return

    n = len(items)
    top_start = 2.45
    usable_h = SLIDE_H_IN - top_start - 0.95
    gap = 0.18
    row_h = (usable_h - gap * (n - 1)) / n
    row_h = min(row_h, 1.25)
    left_margin = 0.6
    card_w = SLIDE_W_IN - 2 * left_margin
    num_w = 1.0
    text_left = left_margin + num_w + 0.4
    text_width = card_w - num_w - 0.6

    for i, item in enumerate(items):
        y = top_start + i * (row_h + gap)

        # Elevated card
        _add_elevated_card(
            slide, left_margin, y, card_w, row_h, theme,
            accent_stripe=None, corner=0.045,
        )

        # Big accent numeral on the left
        _add_text_box(
            slide, Inches(left_margin + 0.3), Inches(y),
            Inches(num_w), Inches(row_h),
            f"{i + 1:02d}", size_pt=42, color=theme["accent"],
            bold=True, font=FONT_HEADING, anchor=MSO_ANCHOR.MIDDLE,
        )

        # Vertical accent divider between number and text
        _add_vertical_hairline(
            slide, left_margin + num_w + 0.2, y + 0.25, row_h - 0.5,
            theme["muted"], alpha_pct=45,
        )

        # Title
        title_text = item.get("title", "")
        desc = item.get("description", "")
        if desc:
            title_y = y + 0.15
            title_h = 0.42
            desc_y = title_y + title_h + 0.05
            desc_h = row_h - title_h - 0.25
            _add_text_box(
                slide, Inches(text_left), Inches(title_y),
                Inches(text_width), Inches(title_h),
                title_text, size_pt=16, color=theme["title_color"],
                bold=True, font=FONT_HEADING, shrink=True,
            )
            _add_text_box(
                slide, Inches(text_left), Inches(desc_y),
                Inches(text_width), Inches(desc_h),
                desc, size_pt=12, color=theme["card_text"],
                font=FONT_BODY, shrink=True,
            )
        else:
            _add_text_box(
                slide, Inches(text_left), Inches(y + 0.1),
                Inches(text_width), Inches(row_h - 0.2),
                title_text, size_pt=16, color=theme["title_color"],
                bold=True, font=FONT_HEADING,
                anchor=MSO_ANCHOR.MIDDLE, shrink=True,
            )


def build_process_flow_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern process chain: each step is an elevated card containing an
    icon tile, step number, title, and description. Accent chevrons connect
    cards. Reads as a confident workflow, not a row of orbs.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", ""), theme)

    steps = data.get("steps", [])[:5]
    if not steps:
        return build_content_slide(prs, data, theme, image_path)

    n = len(steps)
    side = 0.55
    gap = 0.22
    chev_w = 0.35 if n > 1 else 0
    total_gap_chev = (gap + chev_w) * (n - 1)
    slot_w = (SLIDE_W_IN - 2 * side - total_gap_chev) / n
    card_top = 2.55
    card_h = 4.05
    tile_size = 0.78

    for i, step in enumerate(steps):
        slot_left = side + i * (slot_w + gap + chev_w)

        # Elevated card
        _add_elevated_card(
            slide, slot_left, card_top, slot_w, card_h, theme,
            accent_stripe="top", corner=0.05,
        )

        # Icon tile at top-left of card
        glyph = _resolve_icon(step.get("icon"))
        tile_left = slot_left + (slot_w - tile_size) / 2
        _add_icon_tile(
            slide, tile_left, card_top + 0.5, tile_size,
            theme, glyph, style="filled",
        )

        # Step number above title
        _add_text_box(
            slide, Inches(slot_left + 0.2), Inches(card_top + 0.5 + tile_size + 0.25),
            Inches(slot_w - 0.4), Inches(0.3),
            f"STEP {i + 1:02d}", size_pt=10, color=theme["muted"],
            bold=True, font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
        )

        # Title
        title_y = card_top + 0.5 + tile_size + 0.6
        _add_text_box(
            slide, Inches(slot_left + 0.2), Inches(title_y),
            Inches(slot_w - 0.4), Inches(0.5),
            step.get("title", ""), size_pt=14, color=theme["title_color"],
            bold=True, font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
            shrink=True,
        )

        # Description
        desc = step.get("description", "")
        if desc:
            _add_text_box(
                slide, Inches(slot_left + 0.2), Inches(title_y + 0.55),
                Inches(slot_w - 0.4), Inches(card_h - (title_y - card_top) - 0.7),
                desc, size_pt=11, color=theme["card_text"],
                font=FONT_BODY, alignment=PP_ALIGN.CENTER, shrink=True,
            )

        # Accent chevron between cards
        if i < n - 1:
            chev_cx = slot_left + slot_w + gap + chev_w / 2
            chev_cy = card_top + card_h / 2
            _add_icon_glyph(
                slide, chev_cx - 0.18, chev_cy - 0.18, 0.36,
                "\uE76C", theme["accent"], glyph_pt=22,  # ChevronRight
            )


def build_icon_grid_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """Modern icon grid: each item is an elevated card with a filled rounded
    icon tile, bold title, and a clean description. Even rhythm, soft shadow,
    confident type hierarchy — the SaaS-pitch grid pattern.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _add_title_block(slide, data.get("title", ""), theme)

    items = data.get("items", [])[:4]
    if not items:
        return build_content_slide(prs, data, theme, image_path)

    n = len(items)
    side = 0.6
    gap = 0.3
    slot_w = (SLIDE_W_IN - 2 * side - gap * (n - 1)) / n
    content_top = 2.5
    card_h = 4.1
    icon_size = 0.85

    for i, item in enumerate(items):
        slot_left = side + i * (slot_w + gap)

        # Elevated card
        _add_elevated_card(
            slide, slot_left, content_top, slot_w, card_h, theme,
            accent_stripe=None, corner=0.05,
        )

        # Filled rounded icon tile at top-left
        glyph = _resolve_icon(item.get("icon"))
        _add_icon_tile(
            slide, slot_left + 0.35, content_top + 0.4, icon_size,
            theme, glyph, style="filled",
        )

        # Small index tag right of the tile
        _add_text_box(
            slide,
            Inches(slot_left + 0.35 + icon_size + 0.2),
            Inches(content_top + 0.55),
            Inches(slot_w - icon_size - 0.7), Inches(0.5),
            f"0{i + 1}", size_pt=12, color=theme["muted"],
            bold=True, font=FONT_HEADING, anchor=MSO_ANCHOR.MIDDLE,
        )

        # Title
        title_y = content_top + 0.4 + icon_size + 0.35
        _add_text_box(
            slide, Inches(slot_left + 0.35), Inches(title_y),
            Inches(slot_w - 0.7), Inches(0.6),
            item.get("title", ""), size_pt=16, color=theme["title_color"],
            bold=True, font=FONT_HEADING, shrink=True,
        )

        # Short accent tick under title
        tick = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(slot_left + 0.35), Inches(title_y + 0.55),
            Inches(0.45), Inches(0.04),
        )
        tick.fill.solid()
        tick.fill.fore_color.rgb = theme["accent"]
        tick.line.fill.background()
        tick.shadow.inherit = False

        # Description
        desc = item.get("description", "")
        if desc:
            _add_text_box(
                slide, Inches(slot_left + 0.35), Inches(title_y + 0.75),
                Inches(slot_w - 0.7), Inches(card_h - (title_y - content_top) - 0.95),
                desc, size_pt=12, color=theme["card_text"],
                font=FONT_BODY, shrink=True,
            )


# ═══════════════════════════════════════════════════════════════════════════
# ░░ PwC-STRICT SLIDE BUILDERS ░░
# ═══════════════════════════════════════════════════════════════════════════
# Follows the PwC brand guideline literally:
#   • White/black base; orange reserved for highlights only
#   • PwCNext (fallback Arial/Calibri/Helvetica), left-aligned, consistent sizing
#   • One slide = one message. MECE bullets, short, data-backed
#   • Whitespace-first, no decorative noise
#   • Logo top-left on every slide; orange baseline rule + page number
#
# No eyebrow dots, no vertical accent bars, no medallions, no chapter marks —
# those belong to the editorial (aurora) path and violate PwC brand strictness.


def build_pwc_title_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC cover — white bg, oversized black title (left-aligned), orange
    rule, subtitle, and date stamp. Logo + clear space applied via chrome."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    title = data.get("title", "")
    subtitle = data.get("subtitle", "")

    # Oversized black title — left-aligned (brand rule)
    _add_text_box(
        slide, Inches(0.5), Inches(2.7),
        Inches(SLIDE_W_IN - 1.0), Inches(2.2),
        title, size_pt=38, color=theme["title_color"],
        bold=True, font=FONT_HEADING,
    )

    # Orange rule — the single highlight element on the cover
    _pwc_short_rule(slide, 0.5, 4.95, width_in=1.2, thickness_in=0.06)

    # Subtitle — muted, generous line length
    if subtitle:
        _add_text_box(
            slide, Inches(0.5), Inches(5.15),
            Inches(SLIDE_W_IN - 2.0), Inches(1.1),
            subtitle, size_pt=16, color=theme["subtitle_color"],
            font=FONT_BODY,
        )

    # Date baseline — small muted stamp
    date_str = datetime.now().strftime("%B %Y")
    _add_text_box(
        slide, Inches(0.5), Inches(6.4),
        Inches(5), Inches(0.35),
        date_str, size_pt=10, color=theme["muted"],
        bold=True, font=FONT_BODY,
    )


def build_pwc_section_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC section divider: massive section title on white, thin orange rule,
    short supporting subtitle. No chapter glyphs, no tinted panels."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    title = data.get("title", "")
    subtitle = data.get("subtitle", "")

    # Small "SECTION" marker, all caps, orange
    _add_text_box(
        slide, Inches(0.5), Inches(2.4),
        Inches(SLIDE_W_IN - 1.0), Inches(0.35),
        "SECTION", size_pt=11, color=theme["accent"],
        bold=True, font=FONT_HEADING,
    )

    # Huge black title
    _add_text_box(
        slide, Inches(0.5), Inches(2.85),
        Inches(SLIDE_W_IN - 1.0), Inches(2.0),
        title, size_pt=34, color=theme["title_color"],
        bold=True, font=FONT_HEADING,
    )

    # Orange rule
    _pwc_short_rule(slide, 0.5, 4.95, width_in=1.0, thickness_in=0.06)

    if subtitle:
        _add_text_box(
            slide, Inches(0.5), Inches(5.15),
            Inches(SLIDE_W_IN - 2.0), Inches(1.1),
            subtitle, size_pt=14, color=theme["subtitle_color"],
            font=FONT_BODY,
        )


def build_pwc_closing_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC closing: left-aligned black heading, short orange rule, optional
    subtitle. Avoids centered "Thank You" clichés — stays editorial."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    title = data.get("title", "Thank you")
    subtitle = data.get("subtitle", "")

    _add_text_box(
        slide, Inches(0.5), Inches(2.8),
        Inches(SLIDE_W_IN - 1.0), Inches(1.8),
        title, size_pt=44, color=theme["title_color"],
        bold=True, font=FONT_HEADING,
    )
    _pwc_short_rule(slide, 0.5, 4.5, width_in=1.2, thickness_in=0.06)

    if subtitle:
        _add_text_box(
            slide, Inches(0.5), Inches(4.7),
            Inches(SLIDE_W_IN - 2.0), Inches(1.0),
            subtitle, size_pt=15, color=theme["subtitle_color"],
            font=FONT_BODY,
        )

    # Date stamp
    date_str = datetime.now().strftime("%B %Y")
    _add_text_box(
        slide, Inches(0.5), Inches(6.0),
        Inches(5), Inches(0.35),
        date_str, size_pt=10, color=theme["muted"],
        bold=True, font=FONT_BODY,
    )


def build_pwc_content_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC content slide: clean title + orange rule, short-bullet list with
    small flat orange square markers. One message per slide — key message
    sits right under the title, bullets provide the supporting detail."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", ""), theme, size_pt=22)

    bullets = data.get("bullets", [])[:6]
    subtitle = data.get("subtitle") or data.get("key_message", "")
    has_image = image_path and os.path.exists(image_path)

    content_top = 2.25
    left_margin = 0.5
    # Leave room for optional image well on the right
    text_w = 7.0 if has_image else (SLIDE_W_IN - left_margin * 2)

    # Optional key-message line (single sentence headline under the title)
    if subtitle:
        _add_text_box(
            slide, Inches(left_margin), Inches(content_top),
            Inches(text_w), Inches(0.55),
            subtitle, size_pt=14, color=theme["subtitle_color"],
            italic=False, font=FONT_BODY,
        )
        bullets_top = content_top + 0.75
    else:
        bullets_top = content_top

    content_bottom = SLIDE_H_IN - 0.9
    usable_h = content_bottom - bullets_top
    n = max(1, len(bullets))
    row_h = min(0.55, usable_h / n) if bullets else 0

    for i, b in enumerate(bullets):
        y = bullets_top + i * row_h
        _pwc_bullet_marker(slide, left_margin, y + 0.12)
        _add_text_box(
            slide, Inches(left_margin + 0.28), Inches(y),
            Inches(text_w - 0.35), Inches(row_h),
            str(b), size_pt=13, color=theme["text_color"],
            font=FONT_BODY,
        )

    if has_image:
        img_left = left_margin + text_w + 0.4
        img_w = SLIDE_W_IN - img_left - 0.5
        _add_image_safe(
            slide, image_path,
            Inches(img_left), Inches(content_top),
            Inches(img_w), Inches(content_bottom - content_top),
        )


def _percent_value(raw: Any) -> tuple:
    """Parse a stat value into (numeric_pct 0-100, display_string).

    Accepts "34%", "34", "0.34", numeric types. Falls back to (50, original)
    if it can't parse — the donut still renders meaningfully.
    """
    s = str(raw or "").strip()
    try:
        cleaned = s.replace("%", "").replace(",", "").strip()
        val = float(cleaned)
    except (ValueError, TypeError):
        return 50.0, s or "—"
    if 0 < val <= 1 and "%" not in s:
        val = val * 100  # fraction form like 0.34
    val = max(0.0, min(100.0, val))
    display = s if s.endswith("%") else f"{int(val) if val == int(val) else round(val, 1)}%"
    return val, display


def build_pwc_stats_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC 'Key indicators' layout — three tall orange cards, each with a white
    donut ring showing a percentage at the top and a white body paragraph
    beneath. Matches the PwC data-viz reference (3-up percentage donuts)."""
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", "Key indicators"), theme, size_pt=22)

    stats = (data.get("stats") or [])[:3]
    if not stats:
        return build_pwc_content_slide(prs, data, theme, image_path)

    n = len(stats)
    orange = theme["accent"]
    white = RGBColor(0xFF, 0xFF, 0xFF)
    orange_deep = RGBColor(0xB5, 0x4D, 0x00)  # slightly deeper for the marker tab

    gap = 0.25
    side_margin = 0.55
    content_w = SLIDE_W_IN - 2 * side_margin
    card_w = (content_w - gap * (n - 1)) / n

    card_top = 2.45
    card_h = 4.55
    donut_d = min(1.85, card_w - 0.6)
    donut_top = card_top - donut_d * 0.38  # overlap top edge of card

    for i, stat in enumerate(stats):
        left = side_margin + i * (card_w + gap)
        cx = left + card_w / 2

        # Full-height orange card
        card = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(left), Inches(card_top),
            Inches(card_w), Inches(card_h),
        )
        card.fill.solid()
        card.fill.fore_color.rgb = orange
        card.line.fill.background()
        card.shadow.inherit = False

        # ── Donut chart ──
        value_pct, display = _percent_value(stat.get("value"))
        chart_data = CategoryChartData()
        chart_data.categories = ["filled", "remaining"]
        chart_data.add_series("", (value_pct, 100 - value_pct))

        chart_shape = slide.shapes.add_chart(
            XL_CHART_TYPE.DOUGHNUT,
            Inches(cx - donut_d / 2), Inches(donut_top),
            Inches(donut_d), Inches(donut_d),
            chart_data,
        )
        chart = chart_shape.chart
        chart.has_title = False
        chart.has_legend = False
        plot = chart.plots[0]
        plot.has_data_labels = False
        series = plot.series[0]
        slice_colors = [orange, white]
        for idx, point in enumerate(series.points):
            fill = point.format.fill
            fill.solid()
            fill.fore_color.rgb = slice_colors[idx]
            point.format.line.fill.background()

        # Percentage text overlaid in the donut hole (orange on white centre)
        txt_w = donut_d * 0.7
        txt_h = 0.55
        _add_text_box(
            slide, Inches(cx - txt_w / 2), Inches(donut_top + donut_d / 2 - txt_h / 2),
            Inches(txt_w), Inches(txt_h),
            display, size_pt=20, color=orange, bold=True,
            font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.MIDDLE,
        )

        # ── White body paragraph ──
        desc = stat.get("label") or stat.get("description") or ""
        body_top = donut_top + donut_d + 0.25
        body_h = (card_top + card_h) - body_top - 0.45
        _add_text_box(
            slide, Inches(left + 0.28), Inches(body_top),
            Inches(card_w - 0.56), Inches(body_h),
            str(desc), size_pt=11, color=white,
            font=FONT_BODY, alignment=PP_ALIGN.CENTER,
            anchor=MSO_ANCHOR.TOP,
        )

        # ── Small deeper-orange marker tab at the card's bottom edge ──
        marker_w = 0.28
        marker_h = 0.12
        marker = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(cx - marker_w / 2), Inches(card_top + card_h - marker_h - 0.05),
            Inches(marker_w), Inches(marker_h),
        )
        marker.fill.solid()
        marker.fill.fore_color.rgb = orange_deep
        marker.line.fill.background()
        marker.shadow.inherit = False


def build_pwc_quote_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC quote: simple bold black quote text, short orange rule above, tiny
    uppercase attribution below. No big decorative quote glyphs."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    quote = data.get("quote") or data.get("title", "")
    attribution = data.get("attribution") or data.get("subtitle", "")

    _pwc_short_rule(slide, 0.5, 2.3, width_in=1.2, thickness_in=0.06)

    q_len = len(quote)
    quote_pt = 26 if q_len <= 140 else (22 if q_len <= 220 else 18)
    _add_text_box(
        slide, Inches(0.5), Inches(2.55),
        Inches(SLIDE_W_IN - 1.5), Inches(3.5),
        quote, size_pt=quote_pt, color=theme["title_color"],
        bold=True, font=FONT_HEADING,
    )

    if attribution:
        _pwc_short_rule(slide, 0.5, 6.05, width_in=0.35, thickness_in=0.03)
        _add_text_box(
            slide, Inches(0.5), Inches(6.15),
            Inches(SLIDE_W_IN - 1.5), Inches(0.4),
            attribution.upper(), size_pt=10, color=theme["muted"],
            bold=True, font=FONT_HEADING,
        )


def build_pwc_comparison_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC comparison — two clean columns on white. Each column has a black
    bold header, short orange rule, and short bullet list. No pills, no
    medallion, no coloured card backgrounds."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", "Comparison"), theme, size_pt=22)

    left_data = data.get("left", {}) or {}
    right_data = data.get("right", {}) or {}

    side_in = 0.5
    gap_in = 0.5
    col_w_in = (SLIDE_W_IN - 2 * side_in - gap_in) / 2
    content_top = 2.35
    content_h = 4.1

    # Thin hairline between columns
    div_x = side_in + col_w_in + gap_in / 2
    div = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        Inches(div_x), Inches(content_top),
        Inches(0.008), Inches(content_h),
    )
    div.fill.solid()
    div.fill.fore_color.rgb = theme["muted"]
    div.line.fill.background()

    for idx, col_data in enumerate([left_data, right_data]):
        left_in = side_in + idx * (col_w_in + gap_in)
        col_title = col_data.get("title", "")
        col_body = col_data.get("body") or col_data.get("description", "")

        if col_title:
            _add_text_box(
                slide, Inches(left_in), Inches(content_top),
                Inches(col_w_in), Inches(0.55),
                col_title, size_pt=17, color=theme["title_color"],
                bold=True, font=FONT_HEADING,
            )
            _pwc_short_rule(slide, left_in, content_top + 0.6, width_in=0.6, thickness_in=0.035)

        bullets = col_data.get("bullets", [])[:5]
        bullet_top = content_top + (0.95 if col_title else 0.1)

        # If there's a paragraph body (the "2 section paragraphs" pattern),
        # render it as a clean paragraph above the bullets.
        if col_body:
            _add_text_box(
                slide, Inches(left_in), Inches(bullet_top),
                Inches(col_w_in), Inches(1.4),
                col_body, size_pt=12, color=theme["text_color"],
                font=FONT_BODY,
            )
            bullet_top += 1.5

        if bullets:
            remaining_h = content_h - (bullet_top - content_top)
            row_h = min(0.5, remaining_h / max(1, len(bullets)))
            for i, b in enumerate(bullets):
                y = bullet_top + i * row_h
                _pwc_bullet_marker(slide, left_in, y + 0.11)
                _add_text_box(
                    slide, Inches(left_in + 0.26), Inches(y),
                    Inches(col_w_in - 0.3), Inches(row_h),
                    str(b), size_pt=12, color=theme["text_color"],
                    font=FONT_BODY,
                )


def build_pwc_two_column_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC two-column — identical structure to comparison, kept as a separate
    builder so downstream code that distinguishes the two still works. Each
    column supports a paragraph body AND/OR bullet list (the "2 section
    paragraphs" pattern requested by the brand owner)."""
    return build_pwc_comparison_slide(prs, data, theme, image_path)


def build_pwc_timeline_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC roadmap timeline — two-row staggered layout.

    Matches the PwC reference design: each row has an orange horizontal rule
    with an arrowhead on the right. Each milestone stacks an orange year
    banner (filled rectangle with white label) → small orange square marker
    → light-grey description card. The second row is shifted right so the
    cards don't align vertically with the first row.
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", "Roadmap"), theme, size_pt=22)

    steps = (data.get("steps") or data.get("items") or [])[:6]
    if not steps:
        return build_pwc_content_slide(prs, data, theme, image_path)

    # Split into up to 2 rows of up to 3 items each
    if len(steps) <= 3:
        rows = [steps]
    else:
        split = (len(steps) + 1) // 2
        rows = [steps[:split], steps[split:]]

    orange = theme["accent"]
    white = RGBColor(0xFF, 0xFF, 0xFF)
    grey_card = RGBColor(0xEF, 0xEF, 0xEF)
    grey_text = RGBColor(0x55, 0x55, 0x55)

    side_margin = 0.55
    content_w = SLIDE_W_IN - 2 * side_margin
    stagger = 1.15 if len(rows) > 1 else 0.0  # push bottom row right

    banner_w = 1.85
    banner_h = 0.44
    card_w = 2.10
    card_h = 1.25
    marker_size = 0.14
    line_thickness = 0.045
    arrow_w = 0.22
    arrow_h = 0.26

    row_ys = [2.45, 4.85] if len(rows) > 1 else [3.55]

    for row_idx, row_steps in enumerate(rows):
        row_y = row_ys[row_idx]  # y of the orange rule centre
        n = max(1, len(row_steps))

        # Row horizontal bounds — stagger bottom row to the right
        if row_idx == 1:
            row_left = side_margin + stagger
            row_right = SLIDE_W_IN - side_margin
        else:
            row_left = side_margin
            row_right = SLIDE_W_IN - side_margin - (stagger if len(rows) > 1 else 0)

        # Orange rule (shape, so we can hide the outline)
        rule = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(row_left), Inches(row_y - line_thickness / 2),
            Inches(row_right - row_left - arrow_w + 0.02), Inches(line_thickness),
        )
        rule.fill.solid()
        rule.fill.fore_color.rgb = orange
        rule.line.fill.background()
        rule.shadow.inherit = False

        # Arrowhead (isosceles triangle pointing right)
        arrow = slide.shapes.add_shape(
            MSO_SHAPE.ISOSCELES_TRIANGLE,
            Inches(row_right - arrow_w), Inches(row_y - arrow_h / 2),
            Inches(arrow_w), Inches(arrow_h),
        )
        arrow.rotation = 90
        arrow.fill.solid()
        arrow.fill.fore_color.rgb = orange
        arrow.line.fill.background()
        arrow.shadow.inherit = False

        usable_w = row_right - row_left - arrow_w - 0.15
        slot_w = usable_w / n

        for i, step in enumerate(row_steps):
            cx = row_left + slot_w * (i + 0.5)

            # Year banner (filled orange rectangle, sitting on the rule)
            banner = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(cx - banner_w / 2), Inches(row_y - banner_h / 2),
                Inches(banner_w), Inches(banner_h),
            )
            banner.fill.solid()
            banner.fill.fore_color.rgb = orange
            banner.line.fill.background()
            banner.shadow.inherit = False

            tf = banner.text_frame
            tf.word_wrap = True
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf.margin_left = Inches(0.05)
            tf.margin_right = Inches(0.05)
            tf.margin_top = Inches(0.02)
            tf.margin_bottom = Inches(0.02)
            year_label = step.get("date") or step.get("phase") or step.get("year") or step.get("title") or f"{i + 1:02d}"
            _style_paragraph(
                tf.paragraphs[0], str(year_label),
                size_pt=16, color=white, bold=True,
                font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
            )

            # Small orange square marker below the banner
            marker_x = cx + banner_w / 2 - marker_size - 0.12
            marker_y = row_y + banner_h / 2 + 0.08
            marker = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(marker_x), Inches(marker_y),
                Inches(marker_size), Inches(marker_size),
            )
            marker.fill.solid()
            marker.fill.fore_color.rgb = orange
            marker.line.fill.background()
            marker.shadow.inherit = False

            # Grey description card
            card_y = row_y + banner_h / 2 + 0.32
            card = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(cx - card_w / 2), Inches(card_y),
                Inches(card_w), Inches(card_h),
            )
            card.fill.solid()
            card.fill.fore_color.rgb = grey_card
            card.line.fill.background()
            card.shadow.inherit = False

            desc = step.get("description") or (step.get("title") if year_label != step.get("title") else "") or ""
            _add_text_box(
                slide, Inches(cx - card_w / 2 + 0.12), Inches(card_y + 0.1),
                Inches(card_w - 0.24), Inches(card_h - 0.2),
                str(desc), size_pt=10, color=grey_text,
                font=FONT_BODY, alignment=PP_ALIGN.CENTER,
                anchor=MSO_ANCHOR.MIDDLE,
            )


def build_pwc_numbered_list_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC numbered list (agenda / recommendations): clean hairline-separated
    rows. Orange 01/02… numerals, black titles, grey descriptions. MECE."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", ""), theme, size_pt=22)

    items = data.get("items", [])[:6]
    if not items:
        return

    n = len(items)
    top_start = 2.3
    usable_h = SLIDE_H_IN - top_start - 0.9
    row_h = min(1.0, usable_h / n)
    left_margin = 0.5
    num_w = 0.7
    text_left = left_margin + num_w + 0.25
    text_width = SLIDE_W_IN - text_left - 0.5

    for i, item in enumerate(items):
        y = top_start + i * row_h

        # Orange numeral
        _add_text_box(
            slide, Inches(left_margin), Inches(y),
            Inches(num_w), Inches(row_h),
            f"{i + 1:02d}", size_pt=24, color=theme["accent"],
            bold=True, font=FONT_HEADING,
        )

        # Black title
        _add_text_box(
            slide, Inches(text_left), Inches(y + 0.05),
            Inches(text_width), Inches(0.45),
            item.get("title", ""), size_pt=14, color=theme["title_color"],
            bold=True, font=FONT_HEADING,
        )

        # Description
        desc = item.get("description", "")
        if desc:
            _add_text_box(
                slide, Inches(text_left), Inches(y + 0.5),
                Inches(text_width), Inches(row_h - 0.55),
                desc, size_pt=11, color=theme["text_color"],
                font=FONT_BODY,
            )

        # Hairline divider between rows
        if i < n - 1:
            sep = slide.shapes.add_shape(
                MSO_SHAPE.RECTANGLE,
                Inches(left_margin), Inches(y + row_h - 0.04),
                Inches(SLIDE_W_IN - 2 * left_margin), Inches(0.005),
            )
            sep.fill.solid()
            sep.fill.fore_color.rgb = theme["muted"]
            sep.line.fill.background()


def build_pwc_process_flow_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC process flow: horizontal row of flat orange-bordered circles with
    small Segoe Fluent glyphs, connected by a black rule. Clean labels and
    descriptions below. No filled coloured tiles."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", ""), theme, size_pt=22)

    steps = data.get("steps", [])[:5]
    if not steps:
        return build_pwc_content_slide(prs, data, theme, image_path)

    n = len(steps)
    side = 0.6
    usable = SLIDE_W_IN - 2 * side
    slot_w = usable / n
    tile_size = min(1.0, slot_w - 0.5)
    y_top = 2.6

    # Black connector line behind tiles
    line_y = y_top + tile_size / 2 - 0.015
    first_cx = side + slot_w / 2
    last_cx = side + slot_w * (n - 1) + slot_w / 2
    if n > 1:
        connector = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(first_cx + tile_size / 2 + 0.05), Inches(line_y),
            Inches(last_cx - first_cx - tile_size - 0.1), Inches(0.02),
        )
        connector.fill.solid()
        connector.fill.fore_color.rgb = theme["title_color"]
        connector.line.fill.background()

    for i, step in enumerate(steps):
        cx = side + slot_w * i + slot_w / 2
        tile_left = cx - tile_size / 2

        # Outline orange circle — clean flat mark
        circle = slide.shapes.add_shape(
            MSO_SHAPE.OVAL,
            Inches(tile_left), Inches(y_top),
            Inches(tile_size), Inches(tile_size),
        )
        circle.fill.solid()
        circle.fill.fore_color.rgb = theme["bg"]
        circle.line.color.rgb = theme["accent"]
        circle.line.width = Pt(1.75)
        circle.shadow.inherit = False

        # Icon inside
        glyph = _resolve_icon(step.get("icon"))
        _add_icon_glyph(
            slide, tile_left, y_top, tile_size,
            glyph, theme["accent"], glyph_pt=max(20, int(tile_size * 32)),
        )

        # Title below tile
        label_y = y_top + tile_size + 0.25
        _add_text_box(
            slide, Inches(cx - slot_w / 2 + 0.05), Inches(label_y),
            Inches(slot_w - 0.1), Inches(0.45),
            step.get("title", ""), size_pt=13, color=theme["title_color"],
            bold=True, font=FONT_HEADING, alignment=PP_ALIGN.CENTER,
        )
        desc = step.get("description", "")
        if desc:
            _add_text_box(
                slide, Inches(cx - slot_w / 2 + 0.05), Inches(label_y + 0.5),
                Inches(slot_w - 0.1), Inches(1.8),
                desc, size_pt=10, color=theme["text_color"],
                font=FONT_BODY, alignment=PP_ALIGN.CENTER,
            )


def build_pwc_icon_grid_slide(prs: Presentation, data: Dict, theme: Dict, image_path: Optional[str] = None):
    """PwC 'cards' slide: clean columns, each with a flat orange-outlined
    square containing an icon, a black title, and short description. This
    is the flat-card treatment the brand guide calls for."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_slide_bg(slide, theme["bg"])

    _pwc_title_block(slide, data.get("title", ""), theme, size_pt=22)

    items = data.get("items", [])[:4]
    if not items:
        return build_pwc_content_slide(prs, data, theme, image_path)

    n = len(items)
    side = 0.5
    gap = 0.3
    usable = SLIDE_W_IN - 2 * side
    slot_w = (usable - gap * (n - 1)) / n
    content_top = 2.4
    content_h = 4.0
    icon_size = 0.85

    for i, item in enumerate(items):
        slot_left = side + i * (slot_w + gap)

        # Flat orange-outlined square — card header element
        box = slide.shapes.add_shape(
            MSO_SHAPE.RECTANGLE,
            Inches(slot_left), Inches(content_top),
            Inches(icon_size), Inches(icon_size),
        )
        box.fill.solid()
        box.fill.fore_color.rgb = theme["bg"]
        box.line.color.rgb = theme["accent"]
        box.line.width = Pt(1.75)
        box.shadow.inherit = False

        glyph = _resolve_icon(item.get("icon"))
        _add_icon_glyph(
            slide, slot_left, content_top, icon_size,
            glyph, theme["accent"], glyph_pt=28,
        )

        # Short orange rule under the icon
        _pwc_short_rule(slide, slot_left, content_top + icon_size + 0.25,
                         width_in=0.5, thickness_in=0.035)

        # Black title
        _add_text_box(
            slide, Inches(slot_left), Inches(content_top + icon_size + 0.45),
            Inches(slot_w), Inches(0.55),
            item.get("title", ""), size_pt=15, color=theme["title_color"],
            bold=True, font=FONT_HEADING,
        )

        # Description
        desc = item.get("description", "")
        if desc:
            _add_text_box(
                slide, Inches(slot_left), Inches(content_top + icon_size + 1.05),
                Inches(slot_w), Inches(content_h - icon_size - 1.1),
                desc, size_pt=11, color=theme["text_color"],
                font=FONT_BODY,
            )


# ─────────── top-level orchestration ───────────

SLIDE_BUILDERS = {
    "title": build_title_slide,
    "content": build_content_slide,
    "section": build_section_slide,
    "closing": build_closing_slide,
    "stats": build_stats_slide,
    "quote": build_quote_slide,
    "comparison": build_comparison_slide,
    "two_column": build_two_column_slide,
    "timeline": build_timeline_slide,
    "numbered_list": build_numbered_list_slide,
    "process_flow": build_process_flow_slide,
    "icon_grid": build_icon_grid_slide,
}

PWC_SLIDE_BUILDERS = {
    "title": build_pwc_title_slide,
    "content": build_pwc_content_slide,
    "section": build_pwc_section_slide,
    "closing": build_pwc_closing_slide,
    "stats": build_pwc_stats_slide,
    "quote": build_pwc_quote_slide,
    "comparison": build_pwc_comparison_slide,
    "two_column": build_pwc_two_column_slide,
    "timeline": build_pwc_timeline_slide,
    "numbered_list": build_pwc_numbered_list_slide,
    "process_flow": build_pwc_process_flow_slide,
    "icon_grid": build_pwc_icon_grid_slide,
}

# Layout-variant extension point. Key format: "{slide_type}:{variant}" —
# e.g. "content:callout", "stats:hero". The planner emits layout_variant per
# slide (default|callout|split|hero|grid) and the dispatcher consults this
# map BEFORE falling back to the type-level builder. Register a variant by
# adding an entry (or a PwC-prefixed one in PWC_VARIANT_BUILDERS) with a
# function matching the standard (prs, slide_data, theme, image_path) sig.
SLIDE_VARIANT_BUILDERS: Dict[str, Any] = {}
PWC_VARIANT_BUILDERS: Dict[str, Any] = {}


def _apply_brand_footer(slide, theme: Dict, slide_num: int, total: int):
    """Legacy alias kept for external callers. Routes through the theme-aware
    dispatcher so non-PwC themes get the modern minimal footer."""
    _add_deck_footer(slide, theme, slide_num, total)


def build_pptx(slides_data: List[Dict[str, Any]], theme_name: str = "professional",
                images: List[Optional[str]] = None) -> tuple:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    theme = THEMES.get(theme_name, THEMES["professional"])

    # Brand-font override: swap module-level FONT_HEADING/FONT_BODY for the
    # duration of a themed build so every _style_paragraph / _add_text_box
    # call lands on the brand typography without touching every call site.
    global FONT_HEADING, FONT_BODY
    _saved_heading, _saved_body = FONT_HEADING, FONT_BODY
    brand_heading = theme.get("brand_font_heading")
    brand_body = theme.get("brand_font_body")
    if brand_heading:
        FONT_HEADING = brand_heading
    if brand_body:
        FONT_BODY = brand_body

    try:
        prs = Presentation()
        prs.slide_width = SLIDE_W
        prs.slide_height = SLIDE_H

        images = images or []

        # ── Guarantee the final slide is a "Thank You" closing ──
        # Never mutate the caller's list. If the author already ended the deck
        # with a closing, force its title so the last page always reads
        # "Thank You"; otherwise the post-loop block appends a fresh one.
        slides_data = list(slides_data)
        if slides_data and slides_data[-1].get("type") == "closing":
            final = dict(slides_data[-1])
            final["title"] = "Thank You"
            slides_data[-1] = final

        total = len(slides_data)
        is_branded = bool(theme.get("brand_name"))
        pwc_mode = _is_pwc(theme)
        builders_dict = PWC_SLIDE_BUILDERS if pwc_mode else SLIDE_BUILDERS
        default_builder = builders_dict.get("content", build_content_slide)

        variant_map = PWC_VARIANT_BUILDERS if pwc_mode else SLIDE_VARIANT_BUILDERS

        for i, slide_data in enumerate(slides_data):
            slide_type = slide_data.get("type", "content")
            variant = (slide_data.get("layout_variant") or "default").lower()
            image_path = images[i] if i < len(images) else None
            # Per-slide variant wins if registered; otherwise fall back to the
            # slide_type-level builder. Keeps the default deck unchanged while
            # letting the planner drive layout variety when variants are added.
            variant_key = f"{slide_type}:{variant}"
            builder = variant_map.get(variant_key) or builders_dict.get(slide_type, default_builder)
            builder(prs, slide_data, theme, image_path)

            last_slide = prs.slides[len(prs.slides) - 1]
            if pwc_mode:
                _pwc_apply_chrome(last_slide, theme, i + 1, total,
                                   is_title=(slide_type == "title"))
            elif slide_type == "title":
                # Cover stays clean — logo only, no rule or page number
                _add_title_footer_logo(last_slide)
            else:
                _add_deck_footer(last_slide, theme, i + 1, total)

        # ── Always ensure a Thank-You closing slide at the end ──
        last_type = slides_data[-1].get("type", "content") if slides_data else ""
        if last_type != "closing":
            closing_data = {"type": "closing", "title": "Thank You", "subtitle": ""}
            closing_builder = builders_dict.get("closing", build_closing_slide)
            closing_builder(prs, closing_data, theme, None)
            closing_slide = prs.slides[len(prs.slides) - 1]
            if pwc_mode:
                _pwc_apply_chrome(closing_slide, theme, total + 1, total + 1, is_title=False)
            else:
                _add_deck_footer(closing_slide, theme, total + 1, total + 1)

        safe_title = slides_data[0].get("title", "Presentation")[:50] if slides_data else "Presentation"
        safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '' for c in safe_title).strip().replace(' ', '_')
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"PPT_{safe_title}_{timestamp}.pptx"
        filepath = os.path.join(OUTPUT_DIR, filename)

        prs.save(filepath)
        return filepath, filename
    finally:
        FONT_HEADING, FONT_BODY = _saved_heading, _saved_body


def cleanup_old_generated_pptx(max_age_hours: int = 24) -> int:
    """Delete .pptx files in OUTPUT_DIR older than max_age_hours. Returns count removed."""
    if not os.path.isdir(OUTPUT_DIR):
        return 0
    cutoff = time.time() - (max_age_hours * 3600)
    removed = 0
    try:
        for name in os.listdir(OUTPUT_DIR):
            if not name.lower().endswith(".pptx"):
                continue
            path = os.path.join(OUTPUT_DIR, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    if removed:
        print(f"🧹 Cleaned {removed} stale .pptx files (>{max_age_hours}h old)")
    return removed
