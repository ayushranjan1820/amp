"""
Shared instruction block: every agent that surfaces external or retrieved facts
must emit clickable markdown source links. Import this string into prompts and
system messages so the rule stays consistent.
"""

# Full block for long-form report prompts and dynamic agent system prompts
MANDATORY_MARKDOWN_SOURCE_LINKS = """
**MANDATORY — CLICKABLE SOURCE URLs (CRITICAL, NON-OPTIONAL):**
Whenever this response states facts, figures, dates, direct quotes, regulatory text, news, or any information that comes from the web, search tools, retrieved documents, knowledge bases, research data, or other external content (not pure reasoning with zero external input), you MUST give the reader a real, clickable markdown link to that source.
- Use standard markdown only: `[short label](https://complete-url/path)` with the full `https://` (or `http://`) URL you relied on. The UI renders this as a clickable link.
- **FORBIDDEN:** Do not use bare tags like `[Source 1]`, `[1]`, or `[citation needed]` with no URL. If you use a number or “Source N”, you must still wrap it as `[Source 1](https://...)` (same for `[Title](https://...)`).
- Place at least one such link on the same line as the claim, or immediately after the sentence, for every externally grounded bullet or paragraph.
- At the end, any “Sources / References” list must use markdown links for every entry, not plain URLs or titles alone.
- If a tool provides a URL, copy it into the link target exactly; do not invent URLs.
""".strip()

# Shorter one for tight system messages (e.g. web search)
WEB_SEARCH_CITATION_APPEND = (
    " **MANDATORY:** Every fact from search must be tied to a clickable markdown link "
    "`[label](https://...)` using URLs from the search results. Never output `[Source N]` "
    "or `[1]` without the URL in parentheses right after the bracket text."
)
