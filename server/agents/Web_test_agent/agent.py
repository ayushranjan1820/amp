"""Web Test Agent — enterprise-grade webpage analysis and test generation.

Analyses any webpage by URL, extracts features, and produces a comprehensive
QA test report including manual test cases, automated test specifications,
and ready-to-run Selenium / Playwright scripts.
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .ai_service import ai_service
from .core.config import Settings, get_settings
from .prompts.templates import PromptTemplates
from .tools.web_scraper import scrape_webpage

logger = logging.getLogger(__name__)


class WebTestAgent:
    """Analyses webpages and generates enterprise-grade test deliverables."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.ai_service = ai_service
        self.sessions: Dict[str, Dict[str, Any]] = {}

        self.playwright_available = self._check_playwright()

        if self.playwright_available:
            logger.info("Web Test Agent initialised (SPA support enabled)")
        else:
            logger.info("Web Test Agent initialised (fallback mode — limited SPA support)")

    # ── Playwright availability ───────────────────────────────────────

    @staticmethod
    def _check_playwright() -> bool:
        try:
            import playwright  # noqa: F401
            import shutil

            return shutil.which("chromium") is not None or shutil.which("chromium-browser") is not None
        except ImportError:
            return False

    # ── Session management ────────────────────────────────────────────

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "url": None,
                "page_data": None,
                "features": None,
                "test_cases": None,
                "history": [],
            }
        return self.sessions[session_id]

    # ── URL extraction ────────────────────────────────────────────────

    @staticmethod
    def _extract_url(text: str) -> Optional[str]:
        patterns = [
            r'https?://[^\s<>"\'`,;)}\]]+',
            r'www\.[^\s<>"\'`,;)}\]]+',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                url = match.group(0).rstrip(".")
                if not url.startswith("http"):
                    url = "https://" + url
                return url
        return None

    # ── Main entry point ──────────────────────────────────────────────

    def process_query(
        self,
        query: str,
        session_id: Optional[str] = None,
        clear_history: bool = False,
    ) -> Dict[str, Any]:
        """Process a user query — scrape + generate or handle follow-up."""
        self.settings = get_settings()
        thinking_steps: List[Dict[str, Any]] = []
        session_id = session_id or f"webtest_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        session = self._get_session(session_id)

        if clear_history:
            self.sessions[session_id] = {
                "url": None,
                "page_data": None,
                "features": None,
                "test_cases": None,
                "history": [],
            }
            session = self.sessions[session_id]

        url = self._extract_url(query)

        # ── New URL → full analysis ──────────────────────────────────
        if url and (not session["url"] or url != session["url"]):
            return self._analyse_url(url, query, session, session_id, thinking_steps)

        # ── Follow-up on existing analysis ───────────────────────────
        if session.get("page_data"):
            return self._handle_followup_query(query, session, session_id, thinking_steps)

        # ── No URL, no prior context → welcome message ───────────────
        return {
            "success": True,
            "response": PromptTemplates.WELCOME,
            "thinking_steps": [],
            "session_id": session_id,
        }

    # ── Full URL analysis pipeline ────────────────────────────────────

    def _analyse_url(
        self,
        url: str,
        query: str,
        session: Dict[str, Any],
        session_id: str,
        thinking_steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Scrape URL → extract features → generate complete test report."""
        thinking_steps.append({
            "type": "tool_call",
            "content": f"Scraping webpage: {url}",
            "tool_name": "web_scraper",
            "tool_input": url,
        })

        page_data = scrape_webpage(url)

        if not page_data.get("success"):
            error_msg = page_data.get("error", "Unknown error")
            thinking_steps.append({
                "type": "error",
                "content": f"Failed to scrape: {error_msg}",
                "tool_name": "web_scraper",
                "tool_input": None,
            })
            return {
                "success": False,
                "response": (
                    f"I couldn't access the webpage at **{url}**.\n\n"
                    f"Error: {error_msg}\n\n"
                    "Please check that the URL is correct and the site is accessible."
                ),
                "thinking_steps": thinking_steps,
                "session_id": session_id,
            }

        session["url"] = url
        session["page_data"] = page_data

        stats = page_data.get("page_stats", {})
        thinking_steps.append({
            "type": "tool_result",
            "content": (
                f"Successfully scraped page: {page_data.get('title', 'Untitled')} — "
                f"{stats.get('total_buttons', 0)} buttons, "
                f"{stats.get('total_forms', 0)} forms, "
                f"{stats.get('total_links', 0)} links, "
                f"{stats.get('total_inputs', 0)} inputs"
            ),
            "tool_name": "web_scraper",
            "tool_input": None,
        })

        thinking_steps.append({
            "type": "thinking",
            "content": "Extracting features from the page structure...",
            "tool_name": None,
            "tool_input": None,
        })

        features = self._extract_features(page_data)
        session["features"] = features

        thinking_steps.append({
            "type": "tool_result",
            "content": f"Identified {len(features)} features from the webpage",
            "tool_name": "feature_extractor",
            "tool_input": None,
        })

        test_output, report_meta = self._generate_report(page_data, features, url, thinking_steps)
        session["test_cases"] = test_output

        session["history"].append({"role": "user", "content": query})
        session["history"].append({"role": "assistant", "content": test_output})

        result: Dict[str, Any] = {
            "success": True,
            "response": test_output,
            "thinking_steps": thinking_steps,
            "session_id": session_id,
        }
        if report_meta:
            result["metadata"] = report_meta
        return result

    # ── Feature extraction ────────────────────────────────────────────

    def _extract_features(self, page_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Use the LLM to extract user-facing features from page data."""
        page_summary = self._build_page_summary(page_data)
        prompt = PromptTemplates.FEATURE_EXTRACTION.format(page_summary=page_summary)

        try:
            result = self.ai_service.call_genai(prompt, temperature=0.3, max_tokens=4096)
            json_match = re.search(r"\[.*\]", result, re.DOTALL)
            if json_match:
                features = json.loads(json_match.group(0))
                max_features = self.settings.web_test_max_features
                return features[:max_features]
        except Exception as e:
            logger.warning("Feature extraction via LLM failed: %s — using fallback", e)

        return self._fallback_feature_extraction(page_data)

    # ── Report generation (sequential sections) ───────────────────────

    def _generate_report(
        self,
        page_data: Dict[str, Any],
        features: List[Dict[str, str]],
        url: str,
        thinking_steps: List[Dict[str, Any]],
    ) -> tuple:
        """Generate the full test report by iterating through section configs.

        Returns (report_markdown, ReportMetadata_dict_or_None).
        """
        features_text = self._format_features_text(features)
        page_summary = self._build_page_summary(page_data)
        title = page_data.get("title", "Web Application")
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M")

        base_context = (
            f"**Target URL:** {url}\n"
            f"**Page Title:** {title}\n\n"
            f"**IDENTIFIED FEATURES:**\n{features_text}\n"
            f"**PAGE STRUCTURE:**\n{page_summary}"
        )

        header = (
            f"# QA Test Report: {title}\n\n"
            f"| Field | Value |\n"
            f"|-------|-------|\n"
            f"| **Application URL** | {url} |\n"
            f"| **Report Date** | {report_date} |\n"
            f"| **Prepared By** | Web Test Agent (AI-Powered QA) |\n"
            f"| **Features Identified** | {len(features)} |\n"
            f"| **Page Rendering** | {'Browser (Playwright)' if page_data.get('rendered_with_browser') else 'HTTP (static)'} |\n\n"
            f"---\n\n"
        )

        section_configs = PromptTemplates.get_section_configs(base_context)
        sections: List[str] = []
        sections_generated: List[str] = []
        sections_failed: List[str] = []

        for config in section_configs:
            thinking_steps.append({
                "type": "thinking",
                "content": config["thinking"],
                "tool_name": None,
                "tool_input": None,
            })

            try:
                result = self.ai_service.call_genai(
                    config["prompt"],
                    temperature=0.4,
                    max_tokens=self.settings.web_test_max_tokens,
                )
                result = self._enforce_section_heading(result, config["heading"])
                sections.append(result)
                sections_generated.append(config["name"])
                thinking_steps.append({
                    "type": "tool_result",
                    "content": f"{config['name']} generated successfully",
                    "tool_name": "test_generator",
                    "tool_input": None,
                })
            except Exception as e:
                error_msg = f"Error generating {config['name']}: {e}"
                logger.error(error_msg)
                sections.append(f"{config['heading']}\n\n_{error_msg}_\n")
                sections_failed.append(config["name"])
                thinking_steps.append({
                    "type": "error",
                    "content": error_msg,
                    "tool_name": "test_generator",
                    "tool_input": None,
                })

        report = header + "\n\n".join(sections)

        metadata = {
            "application_url": url,
            "page_title": title,
            "report_date": report_date,
            "prepared_by": "Web Test Agent (AI-Powered QA)",
            "total_features": len(features),
            "sections_generated": sections_generated,
            "sections_failed": sections_failed,
        }

        return report, metadata

    # ── Follow-up handling ────────────────────────────────────────────

    def _handle_followup_query(
        self,
        query: str,
        session: Dict[str, Any],
        session_id: str,
        thinking_steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Handle a follow-up question about an already-analysed page."""
        thinking_steps.append({
            "type": "thinking",
            "content": f"Follow-up question about {session['url']}",
            "tool_name": None,
            "tool_input": None,
        })

        max_turns = self.settings.web_test_max_history_turns
        history_text = ""
        for msg in session["history"][-max_turns:]:
            history_text += f"\n{msg['role'].upper()}: {msg['content'][:500]}\n"

        features_text = self._format_features_text(session.get("features") or [])

        prompt = PromptTemplates.FOLLOWUP.format(
            url=session.get("url", "N/A"),
            page_title=session.get("page_data", {}).get("title", "N/A"),
            features_text=features_text,
            history_text=history_text,
            query=query,
        )

        try:
            followup_response = self.ai_service.call_genai(
                prompt,
                temperature=0.4,
                max_tokens=self.settings.web_test_max_tokens,
            )
        except Exception as e:
            logger.error("Follow-up generation failed: %s", e)
            followup_response = f"Error processing follow-up: {e}"

        session["history"].append({"role": "user", "content": query})
        session["history"].append({"role": "assistant", "content": followup_response})

        return {
            "success": True,
            "response": followup_response,
            "thinking_steps": thinking_steps,
            "session_id": session_id,
        }

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _format_features_text(features: List[Dict[str, str]]) -> str:
        lines = []
        for f in features:
            priority = f.get("priority", "")
            priority_tag = f" [{priority}]" if priority else ""
            lines.append(
                f"- **{f.get('id', '')}**: {f.get('name', '')} — "
                f"{f.get('description', '')}{priority_tag}"
            )
        return "\n".join(lines)

    @staticmethod
    def _enforce_section_heading(content: str, expected_heading: str) -> str:
        content = content.strip()
        lines = content.split("\n")
        body_lines = []
        found_body = False
        for line in lines:
            if not found_body and re.match(r"^#{1,3}\s+", line.strip()):
                continue
            if not found_body and line.strip() == "":
                continue
            if not found_body and line.strip() == "---":
                continue
            found_body = True
            if re.match(r"^##\s+\d+\.\s+", line.strip()):
                continue
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
        return f"{expected_heading}\n\n{body}"

    @staticmethod
    def _build_page_summary(page_data: Dict[str, Any]) -> str:
        parts: List[str] = []
        parts.append(f"Title: {page_data.get('title', 'N/A')}")
        parts.append(f"Description: {page_data.get('meta_description', 'N/A')}")

        stats = page_data.get("page_stats", {})
        parts.append(
            f"\nPage Stats: {stats.get('total_forms', 0)} forms, "
            f"{stats.get('total_buttons', 0)} buttons, "
            f"{stats.get('total_links', 0)} links, "
            f"{stats.get('total_inputs', 0)} standalone inputs, "
            f"{stats.get('total_images', 0)} images"
        )

        navs = page_data.get("navigation", [])
        if navs:
            parts.append("\nNavigation:")
            for nav in navs[:3]:
                items = [item["text"] for item in nav.get("items", [])[:10]]
                parts.append(f"  [{nav.get('label', 'main')}]: {', '.join(items)}")

        headings = page_data.get("headings", [])
        if headings:
            parts.append("\nHeadings:")
            for h in headings[:15]:
                parts.append(f"  {h['level']}: {h['text']}")

        forms = page_data.get("forms", [])
        if forms:
            parts.append("\nForms:")
            for i, form in enumerate(forms):
                parts.append(
                    f"  Form {i + 1} (action={form.get('action', '')}, "
                    f"method={form.get('method', '')}):"
                )
                for field in form.get("fields", []):
                    label_text = ""
                    if field.get("name") or field.get("id"):
                        for lbl in form.get("labels", []):
                            if lbl.get("for") and (
                                lbl["for"] == field.get("id") or lbl["for"] == field.get("name")
                            ):
                                label_text = f" label='{lbl['text']}'"
                                break
                    required = " [required]" if field.get("required") else ""
                    parts.append(
                        f"    - {field['tag']} type={field.get('type', '')} "
                        f"name={field.get('name', '')} "
                        f"placeholder={field.get('placeholder', '')}"
                        f"{label_text}{required}"
                    )
                    if field.get("options"):
                        parts.append(f"      options: {', '.join(field['options'])}")
                if form.get("labels") and not any(f.get("name") for f in form.get("fields", [])):
                    parts.append(
                        f"    Labels: {', '.join(lbl['text'] for lbl in form['labels'])}"
                    )
                if form.get("submit_button"):
                    parts.append(f"    Submit: {form['submit_button']}")

        buttons = page_data.get("buttons", [])
        if buttons:
            parts.append(f"\nButtons ({len(buttons)}):")
            for btn in buttons[:20]:
                parts.append(
                    f"  - '{btn['text']}' type={btn.get('type', '')} id={btn.get('id', '')}"
                )

        inputs = page_data.get("inputs", [])
        if inputs:
            parts.append(f"\nStandalone Inputs ({len(inputs)}):")
            for inp in inputs[:15]:
                parts.append(
                    f"  - {inp['tag']} type={inp.get('type', '')} "
                    f"name={inp.get('name', '')} placeholder={inp.get('placeholder', '')}"
                )

        interactive = page_data.get("interactive_elements", [])
        if interactive:
            parts.append(f"\nInteractive Elements ({len(interactive)}):")
            for el in interactive[:10]:
                parts.append(
                    f"  - role={el.get('role', '')} id={el.get('id', '')} "
                    f"label={el.get('aria_label', '')} "
                    f"preview={el.get('text_preview', '')[:50]}"
                )

        text_sections = page_data.get("text_sections", [])
        if text_sections:
            parts.append(f"\nContent Sections ({len(text_sections)}):")
            for sec in text_sections[:10]:
                parts.append(
                    f"  - [{sec['tag']}] {sec.get('heading', 'No heading')}: "
                    f"{sec.get('content_preview', '')[:100]}"
                )

        return "\n".join(parts)

    @staticmethod
    def _fallback_feature_extraction(page_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """Rule-based feature extraction when LLM is unavailable."""
        features: List[Dict[str, str]] = []
        fid = 1

        for nav in page_data.get("navigation", []):
            features.append({
                "id": f"F{fid:03d}",
                "name": f"Navigation — {nav.get('label', 'Main')}",
                "description": f"Navigation with {len(nav.get('items', []))} links",
                "category": "Navigation",
                "elements": [item["text"] for item in nav.get("items", [])[:5]],
                "priority": "Medium",
                "testability": "Fully Automatable",
            })
            fid += 1

        for form in page_data.get("forms", []):
            field_names = [
                f.get("name") or f.get("placeholder") or f.get("type")
                for f in form.get("fields", [])
            ]
            features.append({
                "id": f"F{fid:03d}",
                "name": f"Form — {form.get('submit_button', 'Submit')}",
                "description": f"Form with fields: {', '.join(filter(None, field_names))}",
                "category": "Form",
                "elements": field_names,
                "priority": "High",
                "testability": "Fully Automatable",
            })
            fid += 1

        for btn in page_data.get("buttons", []):
            if btn.get("text"):
                features.append({
                    "id": f"F{fid:03d}",
                    "name": f"Button — {btn['text']}",
                    "description": f"Interactive button: {btn['text']}",
                    "category": "Interactive",
                    "elements": [btn["text"]],
                    "priority": "Medium",
                    "testability": "Fully Automatable",
                })
                fid += 1

        return features


web_test_agent = WebTestAgent()
