"""BRD generation tool — renders a structured BRD JSON into a professionally laid-out markdown document.

Designed to render correctly in react-markdown + remark-gfm (no raw HTML; uses GFM tables,
Mermaid code blocks, blockquotes, and emoji-driven badges instead).
"""

from langchain_core.tools import tool
from pathlib import Path
from datetime import datetime
from typing import Any, Iterable


# ---------- helpers ----------

PRIORITY_BADGE = {
    "high": "🔴 **High**",
    "medium": "🟡 **Medium**",
    "low": "🟢 **Low**",
}

TYPE_BADGE = {
    "story": "🟦 Story",
    "task": "🟪 Task",
    "bug": "🟥 Bug",
    "epic": "🟧 Epic",
    "spike": "🟨 Spike",
}

STATUS_BADGE = {
    "to do": "⚪ To Do",
    "todo": "⚪ To Do",
    "in progress": "🔵 In Progress",
    "done": "🟢 Done",
    "blocked": "🔴 Blocked",
    "qa": "🟣 QA",
}


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _badge(value: str, mapping: dict) -> str:
    if not value:
        return ""
    return mapping.get(str(value).strip().lower(), str(value))


def _md_escape(s: Any) -> str:
    """Escape pipes and newlines so values render correctly inside GFM tables."""
    if s is None:
        return ""
    text = str(s)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _ensure_list(v: Any) -> list:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _bullets(items: Iterable[Any], prefix: str = "- ") -> str:
    out = []
    for item in items:
        if _is_empty(item):
            continue
        if isinstance(item, dict):
            # Render dict as inline key/value pairs
            parts = [f"**{k.replace('_', ' ').title()}:** {v}" for k, v in item.items() if not _is_empty(v)]
            out.append(f"{prefix}{' | '.join(parts)}")
        else:
            out.append(f"{prefix}{item}")
    return "\n".join(out)


def _table(headers: list, rows: list) -> str:
    if not rows:
        return ""
    head = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = []
    for row in rows:
        body_lines.append("| " + " | ".join(_md_escape(c) for c in row) + " |")
    return "\n".join([head, sep, *body_lines])


# ---------- section renderers ----------

def render_cover(content: dict) -> str:
    name = content.get("project_name") or "BRD"
    code = content.get("project_code")
    audience = content.get("audience") or "Business, Product, Engineering, QA, Design"
    date = datetime.now().strftime("%B %d, %Y")

    meta_rows = [
        ["**Document**", "Business Requirements Document (BRD)"],
        ["**Project**", name],
    ]
    if code:
        meta_rows.append(["**Program / Epic**", code])
    meta_rows.extend([
        ["**Version**", "1.0"],
        ["**Status**", "Draft"],
        ["**Date**", date],
        ["**Audience**", audience],
    ])

    tickets = content.get("source_tickets") or []
    ticket_chips = ""
    if tickets:
        chips = []
        for t in tickets:
            tid = t.get("id", "")
            title = t.get("title", "")
            ttype = _badge(t.get("type", ""), TYPE_BADGE)
            prio = _badge(t.get("priority", ""), PRIORITY_BADGE)
            chips.append(f"- **`{tid}`** — {title}  \n  {ttype} · {prio}")
        ticket_chips = "\n".join(chips)

    parts = [
        f"# 📘 {name}",
        f"### Business Requirements Document",
        "",
        _table(["Field", "Value"], meta_rows),
        "",
    ]
    if ticket_chips:
        parts.append("**Source Tickets**\n")
        parts.append(ticket_chips)
        parts.append("")
    return "\n".join(parts)


def render_at_a_glance(content: dict) -> str:
    """A two-pane TL;DR — one for business, one for tech — derived only from supplied fields."""
    biz = content.get("executive_summary") or content.get("business_context")
    tech_lines = []
    arch = content.get("architecture") or {}
    stack = content.get("technology_stack") or []
    files = []
    for f in (content.get("feature_breakdown") or []):
        files.extend(f.get("scope_files") or [])
    files = list(dict.fromkeys(files))[:6]

    if arch.get("summary"):
        tech_lines.append(arch["summary"])
    if stack:
        layers = ", ".join(sorted({s.get("technology", "") for s in stack if s.get("technology")}))
        if layers:
            tech_lines.append(f"**Stack:** {layers}")
    if files:
        tech_lines.append("**Key files:** " + ", ".join(f"`{p}`" for p in files))

    if not biz and not tech_lines:
        return ""

    out = ["## 🎯 At a Glance", ""]
    if biz:
        first_para = biz.split("\n\n")[0].strip() if isinstance(biz, str) else str(biz)
        out.append("> **For Business Readers**  ")
        out.append(f"> {first_para}")
        out.append("")
    if tech_lines:
        out.append("> **For Technical Readers**  ")
        for line in tech_lines:
            out.append(f"> {line}")
        out.append("")
    return "\n".join(out)


def render_paragraph_section(title: str, body: Any, icon: str = "") -> str:
    if _is_empty(body):
        return ""
    heading = f"## {icon + ' ' if icon else ''}{title}"
    return f"{heading}\n\n{body}\n"


def render_scope(scope: dict) -> str:
    if _is_empty(scope):
        return ""
    in_scope = scope.get("in_scope") or []
    out_scope = scope.get("out_of_scope") or []
    parts = ["## 🧭 Scope", ""]
    if in_scope:
        parts.append("**In Scope**\n")
        parts.append(_bullets(in_scope, "- ✅ "))
        parts.append("")
    if out_scope:
        parts.append("**Out of Scope**\n")
        parts.append(_bullets(out_scope, "- ❌ "))
        parts.append("")
    return "\n".join(parts)


def render_stakeholders(stakeholders: list) -> str:
    if _is_empty(stakeholders):
        return ""
    rows = [[s.get("role", ""), s.get("interest", "")] for s in stakeholders]
    return "## 👥 Stakeholders\n\n" + _table(["Role", "Primary Interest"], rows) + "\n"


def render_user_journey(steps: list) -> str:
    if _is_empty(steps):
        return ""
    out = ["## 🚶 User Journey", ""]
    for i, step in enumerate(steps, 1):
        out.append(f"{i}. {step}")
    out.append("")
    return "\n".join(out)


def render_architecture(arch: dict) -> str:
    if _is_empty(arch):
        return ""
    out = ["## 🏗️ Architecture", ""]
    summary = arch.get("summary")
    if summary:
        out.append(summary)
        out.append("")

    diagram = arch.get("diagram_mermaid")
    if diagram:
        out.append("**Component Flow**")
        out.append("")
        out.append("```mermaid")
        out.append(diagram.strip())
        out.append("```")
        out.append("")

    components = arch.get("components") or []
    if components:
        rows = [
            [c.get("name", ""), c.get("file", ""), c.get("responsibility", ""), c.get("tech", "")]
            for c in components
        ]
        out.append("**Component Responsibilities**\n")
        out.append(_table(["Component", "File / Path", "Responsibility", "Tech"], rows))
        out.append("")
    return "\n".join(out)


def render_tech_stack(stack: list) -> str:
    if _is_empty(stack):
        return ""
    rows = [[s.get("layer", ""), s.get("technology", ""), s.get("purpose", "")] for s in stack]
    return "## 🧰 Technology Stack\n\n" + _table(["Layer", "Technology", "Purpose"], rows) + "\n"


def render_ui_guidelines(ui: dict) -> str:
    if _is_empty(ui):
        return ""
    out = ["## 🎨 UI & Brand Guidelines", ""]

    colors = ui.get("colors") or []
    if colors:
        rows = []
        for c in colors:
            hex_ = (c.get("hex") or "").upper()
            swatch = f"`{hex_}`" if hex_ else ""
            rows.append([c.get("name", ""), swatch, c.get("usage", "")])
        out.append("**Color Palette**\n")
        out.append(_table(["Token", "Hex", "Usage"], rows))
        out.append("")

    typography = ui.get("typography") or []
    if typography:
        rows = [[t.get("family", ""), t.get("fallback", ""), t.get("usage", "")] for t in typography]
        out.append("**Typography**\n")
        out.append(_table(["Font Family", "Fallback", "Usage"], rows))
        out.append("")

    logo_rules = ui.get("logo_rules") or []
    if logo_rules:
        out.append("**Logo Rules**\n")
        out.append(_bullets(logo_rules))
        out.append("")

    component_styles = ui.get("component_styles") or []
    if component_styles:
        out.append("**Component Styling**\n")
        out.append(_bullets(component_styles))
        out.append("")

    notes = ui.get("notes")
    if notes:
        out.append(f"> {notes}")
        out.append("")

    return "\n".join(out)


def render_feature_breakdown(features: list) -> str:
    if _is_empty(features):
        return ""
    out = ["## 🧩 Feature Breakdown", "", "*Each card maps directly to a source ticket.*", ""]
    last_idx = len(features) - 1
    for idx, f in enumerate(features):
        fid = f.get("id", "")
        title = f.get("title", "")
        type_b = _badge(f.get("type", ""), TYPE_BADGE)
        prio_b = _badge(f.get("priority", ""), PRIORITY_BADGE)
        out.append(f"### `{fid}` — {title}")
        out.append("")
        meta_bits = [b for b in [type_b, prio_b] if b]
        if meta_bits:
            out.append(" · ".join(meta_bits))
            out.append("")
        if f.get("summary"):
            out.append(f"**Summary** — {f['summary']}")
            out.append("")
        if f.get("user_value"):
            out.append(f"**User / Business Value** — {f['user_value']}")
            out.append("")
        if f.get("scope_files"):
            files_md = ", ".join(f"`{p}`" for p in f["scope_files"])
            out.append(f"**Scope Files:** {files_md}")
            out.append("")
        if f.get("acceptance_criteria"):
            out.append("**Acceptance Criteria**")
            out.append(_bullets(f["acceptance_criteria"], "- ☑ "))
            out.append("")
        if f.get("notes"):
            out.append(f"> 📝 {f['notes']}")
            out.append("")
        if idx != last_idx:
            out.append("---")
            out.append("")
    return "\n".join(out)


def render_requirements_table(title: str, icon: str, items: list, columns: list, keys: list) -> str:
    if _is_empty(items):
        return ""
    rows = [[item.get(k, "") if k != "priority" else _badge(item.get(k, ""), PRIORITY_BADGE) for k in keys] for item in items]
    return f"## {icon} {title}\n\n" + _table(columns, rows) + "\n"


def render_validation_rules(rules: list) -> str:
    if _is_empty(rules):
        return ""
    rows = [[r.get("field", ""), r.get("rule", ""), r.get("error_handling", ""), r.get("source_ticket", "")] for r in rules]
    return "## ✅ Validation Rules\n\n" + _table(["Field", "Rule", "Error Handling", "Source"], rows) + "\n"


def render_dependencies(deps: list) -> str:
    if _is_empty(deps):
        return ""
    return "## 🔗 Dependencies\n\n" + _bullets(deps) + "\n"


def render_assumptions(items: list) -> str:
    if _is_empty(items):
        return ""
    rows = [[i.get("type", ""), i.get("description", ""), i.get("source", "")] for i in items]
    return "## 📌 Assumptions & Constraints\n\n" + _table(["Type", "Description", "Source"], rows) + "\n"


def render_acceptance_master(items: list) -> str:
    if _is_empty(items):
        return ""
    rows = [[i.get("id", ""), i.get("criterion", ""), i.get("source_ticket", "")] for i in items]
    return "## ☑ Acceptance Criteria (Master)\n\n" + _table(["ID", "Criterion", "Source"], rows) + "\n"


def render_traceability(items: list) -> str:
    if _is_empty(items):
        return ""
    rows = [
        [
            i.get("req_id", ""),
            i.get("ticket", ""),
            i.get("files", ""),
            i.get("acceptance", ""),
            _badge(i.get("priority", ""), PRIORITY_BADGE),
        ]
        for i in items
    ]
    return (
        "## 🧮 Traceability Matrix\n\n"
        + _table(["Requirement", "Ticket", "Files", "Acceptance", "Priority"], rows)
        + "\n"
    )


def render_test_strategy(ts: dict) -> str:
    if _is_empty(ts):
        return ""
    out = ["## 🧪 Test Strategy", ""]
    if ts.get("summary"):
        out.append(ts["summary"])
        out.append("")
    if ts.get("types"):
        out.append("**Test Types**")
        out.append(_bullets(ts["types"]))
        out.append("")
    if ts.get("tools"):
        out.append("**Tools / Frameworks**")
        out.append(_bullets(ts["tools"]))
        out.append("")
    return "\n".join(out)


def render_risks(risks: list) -> str:
    if _is_empty(risks):
        return ""
    rows = [
        [
            r.get("risk", ""),
            _badge(r.get("impact", ""), PRIORITY_BADGE),
            _badge(r.get("probability", ""), PRIORITY_BADGE),
            r.get("mitigation", ""),
        ]
        for r in risks
    ]
    return "## ⚠️ Risks & Mitigation\n\n" + _table(["Risk", "Impact", "Probability", "Mitigation"], rows) + "\n"


def render_glossary(items: list) -> str:
    if _is_empty(items):
        return ""
    rows = [[i.get("term", ""), i.get("definition", "")] for i in items]
    return "## 📚 Glossary\n\n" + _table(["Term", "Definition"], rows) + "\n"


# ---------- main ----------

@tool
def generate_brd(content: dict) -> str:
    """Generate a professional Business Requirements Document (BRD) in markdown format.

    Args:
        content: Structured BRD data dictionary (see BRD_PROMPT_TEMPLATE schema).

    Returns:
        Path to the generated BRD file
    """
    try:
        outputs_dir = Path(__file__).parent.parent / "outputs"
        outputs_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = (content.get("project_name") or "Project").replace(" ", "_")
        filename = f"BRD_{project_name}_{timestamp}.md"
        filepath = outputs_dir / filename

        # Render every section in order; empty ones return ""
        section_blocks = [
            render_cover(content),
            render_at_a_glance(content),
            render_paragraph_section("Executive Summary", content.get("executive_summary"), "🧭"),
            render_paragraph_section("Business Context", content.get("business_context"), "💼"),
            render_scope(content.get("scope") or {}),
            render_stakeholders(content.get("stakeholders") or []),
            render_paragraph_section("Solution Overview", content.get("solution_overview"), "🛠️"),
            render_user_journey(content.get("user_journey") or []),
            render_architecture(content.get("architecture") or {}),
            render_tech_stack(content.get("technology_stack") or []),
            render_ui_guidelines(content.get("ui_brand_guidelines") or {}),
            render_feature_breakdown(content.get("feature_breakdown") or []),
            render_requirements_table(
                "Functional Requirements", "⚙️",
                content.get("functional_requirements") or [],
                ["ID", "Description", "Priority", "Source"],
                ["id", "description", "priority", "source_ticket"],
            ),
            render_requirements_table(
                "Non-Functional Requirements", "🛡️",
                content.get("non_functional_requirements") or [],
                ["ID", "Category", "Description", "Source"],
                ["id", "category", "description", "source_ticket"],
            ),
            render_validation_rules(content.get("validation_rules") or []),
            render_requirements_table(
                "Integration Requirements", "🔌",
                content.get("integration_requirements") or [],
                ["Name", "Description", "Source"],
                ["name", "description", "source_ticket"],
            ),
            render_requirements_table(
                "Data Requirements", "🗄️",
                content.get("data_requirements") or [],
                ["Entity", "Fields", "Persistence", "Source"],
                ["entity", "fields", "persistence", "source_ticket"],
            ),
            render_dependencies(content.get("dependencies") or []),
            render_assumptions(content.get("assumptions_constraints") or []),
            render_acceptance_master(content.get("acceptance_criteria_master") or []),
            render_traceability(content.get("traceability_matrix") or []),
            render_test_strategy(content.get("test_strategy") or {}),
            render_risks(content.get("risks_mitigation") or []),
            render_glossary(content.get("glossary") or []),
        ]

        # Build TOC from non-empty sections (skip cover/at-a-glance which are top matter)
        toc_titles = [
            ("Executive Summary", "🧭"),
            ("Business Context", "💼"),
            ("Scope", "🧭"),
            ("Stakeholders", "👥"),
            ("Solution Overview", "🛠️"),
            ("User Journey", "🚶"),
            ("Architecture", "🏗️"),
            ("Technology Stack", "🧰"),
            ("UI & Brand Guidelines", "🎨"),
            ("Feature Breakdown", "🧩"),
            ("Functional Requirements", "⚙️"),
            ("Non-Functional Requirements", "🛡️"),
            ("Validation Rules", "✅"),
            ("Integration Requirements", "🔌"),
            ("Data Requirements", "🗄️"),
            ("Dependencies", "🔗"),
            ("Assumptions & Constraints", "📌"),
            ("Acceptance Criteria (Master)", "☑"),
            ("Traceability Matrix", "🧮"),
            ("Test Strategy", "🧪"),
            ("Risks & Mitigation", "⚠️"),
            ("Glossary", "📚"),
        ]

        rendered_text = "\n".join(b for b in section_blocks if b)

        toc_lines = []
        idx = 1
        for title, icon in toc_titles:
            if f"## {icon} {title}" in rendered_text or f"## {title}" in rendered_text:
                anchor = title.lower()
                for ch in [" & ", " ", "(", ")", "&", "/"]:
                    anchor = anchor.replace(ch, "-")
                while "--" in anchor:
                    anchor = anchor.replace("--", "-")
                anchor = anchor.strip("-")
                toc_lines.append(f"{idx}. [{title}](#{anchor})")
                idx += 1
        toc_md = "\n".join(toc_lines) if toc_lines else "_No detailed sections — the prompt did not contain enough structured information._"

        # Stitch everything: cover, TOC, at-a-glance, then sections
        cover = section_blocks[0]
        at_a_glance = section_blocks[1]
        body_blocks = [b for b in section_blocks[2:] if b]

        brd_content = (
            cover
            + "\n---\n\n"
            + "## 📑 Table of Contents\n\n"
            + toc_md
            + "\n\n---\n\n"
            + (at_a_glance + "\n---\n\n" if at_a_glance else "")
            + "\n\n---\n\n".join(body_blocks)
            + "\n\n---\n\n"
            + "## 🗂️ Document Control\n\n"
            + _table(
                ["Field", "Value"],
                [
                    ["Prepared By", "BRD Generation Agent"],
                    ["Last Updated", datetime.now().strftime("%B %d, %Y at %I:%M %p")],
                    ["Version", "1.0 — Initial Draft"],
                    ["Classification", "Internal Use Only"],
                ],
            )
            + "\n\n*This document is confidential and intended for internal use only. All claims in this BRD are traceable to the source prompt provided to the BRD Generation Agent.*\n"
        )

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(brd_content)

        return str(filepath)

    except Exception as e:
        return f"Error generating BRD: {str(e)}"
