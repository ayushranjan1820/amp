import asyncio
import uuid
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from .tools.file_extractor import extract_file_content, SUPPORTED_EXTENSIONS, IMAGE_EXTENSIONS
from .ai_service import formatter_ai_service
from .models import DocumentFormatterResponse, ThinkingStep


class DocumentFormatterAgent:

    def __init__(self):
        self.ai = formatter_ai_service
        self.sessions: Dict[str, Any] = {}

        from agents.local_llm import describe_missing_llm_credentials, get_llm_provider

        _llm_labels = {"pwc_genai": "PwC GenAI", "local_llm": "local LLM", "ollama_cloud": "Ollama Cloud"}
        if self.ai.llm_configured:
            prov = get_llm_provider()
            print(f"📄 Document Formatter Agent — LLM: {_llm_labels.get(prov, prov)}")
        else:
            print(f"⚠️ Document Formatter Agent — {describe_missing_llm_credentials()}")

    def _add_thinking(self, steps: List[Dict], step_type: str, content: str, tool_name: str = None, tool_input: str = None):
        step = {"type": step_type, "content": content}
        if tool_name:
            step["tool_name"] = tool_name
        if tool_input:
            step["tool_input"] = tool_input
        steps.append(step)

    def _get_session(self, session_id: Optional[str]) -> Dict[str, Any]:
        if not session_id:
            session_id = str(uuid.uuid4())

        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "id": session_id,
                "extracted_text": None,
                "extracted_images": [],
                "file_name": None,
                "file_type": None,
                "history": [],
                "created_at": datetime.now().isoformat(),
            }

        return self.sessions[session_id]

    async def process(
        self,
        query: str,
        file_content: Optional[str] = None,
        file_type: Optional[str] = None,
        file_name: Optional[str] = None,
        session_id: Optional[str] = None,
        output_format: str = "markdown",
    ) -> DocumentFormatterResponse:
        thinking_steps = []
        session = self._get_session(session_id)
        session_id = session["id"]

        has_new_file = file_content and file_type

        if has_new_file:
            self._add_thinking(thinking_steps, "thinking", f"Received file: {file_name or 'unnamed'} (type: {file_type})")
            self._add_thinking(thinking_steps, "tool_call", f"Extracting content from {file_type} file", "file_extractor", file_name or file_type)

            extracted_text, success, extracted_images = extract_file_content(
                file_content, file_type, file_name or ""
            )

            if not success:
                self._add_thinking(thinking_steps, "tool_result", f"Extraction failed: {extracted_text}")
                return DocumentFormatterResponse(
                    success=False,
                    query=query,
                    response=f"I couldn't extract content from the uploaded file. {extracted_text}",
                    session_id=session_id,
                    thinking_steps=[ThinkingStep(**s) for s in thinking_steps],
                )

            session["extracted_text"] = extracted_text
            session["extracted_images"] = extracted_images
            session["file_name"] = file_name
            session["file_type"] = file_type

            text_preview = extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text
            self._add_thinking(thinking_steps, "tool_result",
                f"Extracted {len(extracted_text)} characters, {len(extracted_images)} images. Preview: {text_preview}")

        extracted_text = session.get("extracted_text")
        extracted_images = session.get("extracted_images", [])

        if not extracted_text and not has_new_file:
            self._add_thinking(thinking_steps, "thinking", "No document in session, providing guidance")
            supported = ", ".join(sorted(set(SUPPORTED_EXTENSIONS.values())))
            return DocumentFormatterResponse(
                success=True,
                query=query,
                response=(
                    "Please upload a document and I'll help you extract and reformat its content. "
                    f"I support the following file types: {supported}.\n\n"
                    "You can also tell me how you'd like the content formatted — for example:\n"
                    "- \"Convert this to a clean markdown document\"\n"
                    "- \"Extract all tables and format them nicely\"\n"
                    "- \"Summarize the key points from this document\"\n"
                    "- \"Reformat this as a professional report\"\n"
                    "- \"Extract and organize the data into sections\""
                ),
                session_id=session_id,
                output_format=output_format,
                thinking_steps=[ThinkingStep(**s) for s in thinking_steps],
            )

        self._add_thinking(thinking_steps, "thinking", f"Processing formatting request: {query}")
        self._add_thinking(thinking_steps, "tool_call", "Calling LLM for document formatting", "genai", query[:200])

        prompt = self._build_formatting_prompt(query, extracted_text, extracted_images, output_format, file_name or session.get("file_name", ""))
        formatted = await self.ai.call_genai(prompt, temperature=0.2, max_tokens=8192)

        if formatted.startswith("Error"):
            self._add_thinking(thinking_steps, "tool_result", f"LLM error: {formatted}")
            return DocumentFormatterResponse(
                success=False,
                query=query,
                response=f"I encountered an error while formatting: {formatted}",
                extracted_text=extracted_text[:2000] if extracted_text else None,
                extracted_images=extracted_images,
                session_id=session_id,
                thinking_steps=[ThinkingStep(**s) for s in thinking_steps],
            )

        self._add_thinking(thinking_steps, "tool_result", f"Formatted output: {len(formatted)} characters")
        self._add_thinking(thinking_steps, "observation", "Document formatted successfully")

        session["history"].append({
            "query": query,
            "output_format": output_format,
            "timestamp": datetime.now().isoformat(),
        })

        image_summary = ""
        if extracted_images:
            image_summary = f"\n\n*Note: {len(extracted_images)} image(s) were detected in the document but could not be included in the text output.*"

        return DocumentFormatterResponse(
            success=True,
            query=query,
            response=formatted + image_summary,
            formatted_content=formatted,
            extracted_text=extracted_text[:5000] if extracted_text else None,
            extracted_images=extracted_images,
            file_name=file_name or session.get("file_name"),
            output_format=output_format,
            session_id=session_id,
            thinking_steps=[ThinkingStep(**s) for s in thinking_steps],
        )

    def _build_formatting_prompt(
        self,
        query: str,
        extracted_text: str,
        extracted_images: List[Dict],
        output_format: str,
        file_name: str,
    ) -> str:
        image_info = ""
        if extracted_images:
            image_info = f"\n\nNote: The document contains {len(extracted_images)} embedded image(s). Indicate where images appeared with placeholders like [Image 1], [Image 2], etc."

        max_text = 30000
        if len(extracted_text) > max_text:
            extracted_text = extracted_text[:max_text] + f"\n\n[... Content truncated. Original document has {len(extracted_text)} characters total ...]"

        format_instructions = {
            "markdown": "Format the output as clean, well-structured Markdown with proper headings, lists, tables, and emphasis.",
            "html": "Format the output as clean HTML with proper semantic tags, headings, tables, and styling classes.",
            "json": "Format the output as structured JSON with logical keys and nested objects for sections, tables, and content blocks.",
            "plain": "Format the output as clean plain text with clear section separators and proper spacing.",
        }

        format_instruction = format_instructions.get(output_format, format_instructions["markdown"])

        prompt = f"""You are a professional document formatter. Your task is to take extracted document content and reformat it according to the user's instructions.

SOURCE DOCUMENT: {file_name or 'Uploaded Document'}
{image_info}

USER'S FORMATTING REQUEST:
{query}

OUTPUT FORMAT: {output_format}
{format_instruction}

EXTRACTED DOCUMENT CONTENT:
---
{extracted_text}
---

IMPORTANT — PAGE/SECTION TRACKING:
The extracted content includes page markers like "--- Page X ---" (for PDFs and Word docs), "--- Slide X ---" (for PowerPoint), or "--- Sheet X: Name ---" (for Excel). You MUST preserve these page/slide/sheet references in your output so the reader knows which content belongs to which page. Use annotations like "(Page X)" or "[Page X]" or section headers to clearly indicate page origins.

INSTRUCTIONS:
1. Carefully read the extracted content above.
2. Apply the user's formatting request to transform the content.
3. Preserve all important information, data, and structure from the original.
4. ALWAYS indicate which page/slide/sheet each piece of content came from.
5. If the document has tables, reproduce them accurately in the target format with their page reference.
6. If the user asks to summarize, include page references for each key point so readers can find the original.
7. If the user asks to restructure, organize logically with clear headings but still note original page numbers.
8. Output ONLY the formatted content — no meta-commentary about the formatting process.
9. Make the output professional, clean, and ready to use.

FORMATTED OUTPUT:"""

        return prompt


document_formatter_agent = DocumentFormatterAgent()
