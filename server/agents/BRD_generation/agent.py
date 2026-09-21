import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import json

from langchain_classic.memory import ConversationBufferMemory

from agents.session_memory import memory_for_session
from .tools import tools_list, generate_brd
from .ai_service import ai_service


def _is_empty(value: Any) -> bool:
    """True when a value is None, blank, or a placeholder like 'N/A'."""
    if value is None:
        return True
    if isinstance(value, str):
        s = value.strip()
        return (not s) or s.lower() in {
            "n/a", "na", "none", "not specified", "not provided",
            "unknown", "tbd", "null",
        }
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def prune_empty(obj: Any) -> Any:
    """Recursively remove empty/placeholder values from the BRD structure.

    Keeps the document grounded — sections without prompt-supported content
    disappear instead of being rendered as empty stubs.
    """
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            pruned = prune_empty(v)
            if not _is_empty(pruned):
                cleaned[k] = pruned
        return cleaned
    if isinstance(obj, list):
        cleaned_list = [prune_empty(v) for v in obj]
        cleaned_list = [v for v in cleaned_list if not _is_empty(v)]
        return cleaned_list
    return obj


# Load .env from the server root directory (PwC GenAI keys stripped — agent config only)
if not os.getenv("_AGENTSERVER_RUNNING"):
    from user_config import load_dotenv_then_scrub_pwc
    env_path = Path(__file__).parent.parent.parent / '.env'
    load_dotenv_then_scrub_pwc(dotenv_path=env_path)


BRD_PROMPT_TEMPLATE = """You are a Senior Business Analyst + Solutions Architect drafting a Business Requirements Document (BRD) that a CTO, Product Manager, Designer, and Developer should all be able to read and act on.

# Source of Truth
The user prompt below is the ONLY source of truth.
- Do NOT invent metrics, KPIs, stakeholders, integrations, risks, compliance, timelines, or constraints that aren't in the prompt.
- DO extract and surface every piece of structured information already in the prompt: ticket IDs, ticket types, priorities, file paths, tech stack hints, UI/brand guidelines (colors, typography, logos), validation rules, acceptance criteria, parent epic links, and any "additional notes".
- DO synthesise a clear narrative (executive summary, solution overview, user journey, component responsibilities) BY REPHRASING what is already in the prompt. Synthesis ≠ fabrication — you are organising and explaining the same facts.
- DO infer obvious technical reality (e.g. if files include `src/pages/UserManagement.js` and `src/App.js` and the stack says "React + React Router", the architecture has a React SPA with route registration in App.js). Anything beyond such direct inference is forbidden.

# User Prompt
{user_input}

# Output Schema (JSON)
Return ONLY a single JSON object. Omit any key whose value would be empty, placeholder ("N/A", "TBD", "Unknown"), or unsupported by the prompt. Never emit empty arrays or empty strings.

{{
  "project_name": "Concise, business-friendly project name derived from the tickets' theme",
  "project_code": "Parent epic / program code if mentioned (e.g. KAN-264)",
  "audience": "Comma-separated list of who this BRD is for, e.g. 'Product, Engineering, QA, Design'",

  "source_tickets": [
    {{
      "id": "KAN-XXX",
      "title": "Ticket summary",
      "type": "Story | Task | Bug | Epic",
      "priority": "High | Medium | Low",
      "status": "Status from prompt"
    }}
  ],

  "executive_summary": "3 short paragraphs in plain business English. Paragraph 1: what is being built and for whom. Paragraph 2: why now / business value. Paragraph 3: how success will look. Keep it traceable to the prompt — no invented metrics.",

  "business_context": "Problem statement and motivation drawn from the prompt (parent epic, additional notes, etc.).",

  "scope": {{
    "in_scope": ["Bullet items derived from ticket summaries and notes"],
    "out_of_scope": ["Only include items explicitly excluded by the prompt; otherwise omit this key"]
  }},

  "stakeholders": [
    {{"role": "e.g. End User / Product Owner / QA / Designer", "interest": "What they care about per the prompt"}}
  ],

  "solution_overview": "A flowing narrative (2-4 paragraphs) that describes the end-to-end solution: what page/feature exists, how the user reaches it, what they do, what the system validates, where data is persisted, and what tests guard it. Reference ticket IDs inline like (KAN-265).",

  "user_journey": [
    "Step 1 in plain language",
    "Step 2 ...",
    "Step N — should map to the tickets"
  ],

  "architecture": {{
    "summary": "1-2 paragraphs explaining the architectural approach grounded in the prompt's tech stack and file references.",
    "components": [
      {{"name": "Component / module name (e.g. UserManagement Page)", "file": "Path from prompt", "responsibility": "What it does", "tech": "Framework/library from prompt"}}
    ],
    "diagram_mermaid": "A valid Mermaid 'flowchart LR' or 'graph TD' diagram using ONLY components and flows that the prompt supports. Use simple node names and arrow labels. No styling directives that could break parsing. Example:\\nflowchart LR\\n  A[User] --> B[Top Nav]\\n  B --> C[User Page /users]\\n  C --> D[FormValidator]\\n  C --> E[Users Table]\\n  D -->|valid| F[(DB)]\\n  E --> F"
  }},

  "technology_stack": [
    {{"layer": "Frontend | Backend | Data | Testing | Tooling", "technology": "Specific tech named in prompt", "purpose": "What it's used for here"}}
  ],

  "ui_brand_guidelines": {{
    "colors": [
      {{"name": "Primary | Secondary | Accent", "hex": "#XXXXXX", "usage": "Where it applies"}}
    ],
    "typography": [
      {{"family": "Font family", "fallback": "Fallback family", "usage": "Base | Headings | etc."}}
    ],
    "logo_rules": ["Any logo constraint mentioned"],
    "component_styles": ["e.g. Navigation primary color cue"],
    "notes": "Any other branding/UX guidance from the prompt"
  }},

  "feature_breakdown": [
    {{
      "id": "KAN-XXX",
      "title": "Feature title",
      "type": "Story | Task",
      "priority": "High | Medium | Low",
      "summary": "1-2 sentence business description",
      "user_value": "Why a user/business cares",
      "scope_files": ["src/pages/UserManagement.js", "..."],
      "acceptance_criteria": ["Bullet ACs from this ticket only"],
      "notes": "Any additional notes from this ticket"
    }}
  ],

  "functional_requirements": [
    {{"id": "FR-001", "description": "Imperative statement", "priority": "High | Medium | Low", "source_ticket": "KAN-XXX"}}
  ],

  "non_functional_requirements": [
    {{"id": "NFR-001", "category": "Usability | Performance | Accessibility | Security | Reliability | Compliance", "description": "...", "source_ticket": "KAN-XXX"}}
  ],

  "validation_rules": [
    {{"field": "Field name", "rule": "Rule from prompt", "error_handling": "If described", "source_ticket": "KAN-XXX"}}
  ],

  "integration_requirements": [
    {{"name": "Integration name", "description": "...", "source_ticket": "KAN-XXX"}}
  ],

  "data_requirements": [
    {{"entity": "Entity name", "fields": "Fields if listed", "persistence": "Where it lives", "source_ticket": "KAN-XXX"}}
  ],

  "dependencies": ["Parent epics, prerequisite tickets, external systems — only when in prompt"],

  "assumptions_constraints": [
    {{"type": "Assumption | Constraint", "description": "...", "source": "KAN-XXX or 'Prompt'"}}
  ],

  "acceptance_criteria_master": [
    {{"id": "AC-01", "criterion": "Testable statement", "source_ticket": "KAN-XXX"}}
  ],

  "traceability_matrix": [
    {{"req_id": "FR-001 | NFR-001", "ticket": "KAN-XXX", "files": "comma-separated", "acceptance": "AC-01, AC-02", "priority": "High | Medium | Low"}}
  ],

  "test_strategy": {{
    "summary": "Approach in 2-4 lines, only if prompt mentions tests",
    "types": ["Functional", "Integration", "UI", "Brand compliance"],
    "tools": ["e.g. React test setup", "Manual API verification"]
  }},

  "risks_mitigation": [
    {{"risk": "Risk statement", "impact": "High | Medium | Low", "probability": "High | Medium | Low", "mitigation": "..."}}
  ],

  "glossary": [
    {{"term": "Term", "definition": "Definition aligned with the prompt"}}
  ]
}}

# Quality Bar
- Use ticket IDs (KAN-XXX) inside narrative paragraphs so every claim is traceable.
- Prefer arrays of objects (structured) over long markdown blobs. The renderer turns objects into tables.
- The Mermaid diagram is required when the prompt has enough components/files to draw one. If the prompt is too thin for a diagram, omit the `diagram_mermaid` key (do not produce a fake one).
- Be concise but specific. Business readers should grasp the "what & why" in 60 seconds; engineers should find the file paths, tech, and acceptance criteria without scrolling forever.
- Output JSON only. No markdown fences, no commentary."""


class BRDGenerationAgent:
    """An AI agent specialized in generating professional Business Requirements Documents."""

    def __init__(self):
        """Initialize the BRD Generation Agent with PwC GenAI service."""
        print("📄 BRD Generation Agent - Using PwC GenAI service")
        self.ai_service = ai_service
        self._conversation_by_session: Dict[str, ConversationBufferMemory] = {}
        self.tools = tools_list

    def invoke_tool(self, tool_name: str, tool_input: str):
        """Invoke a tool by name and input."""
        for tool in self.tools:
            if tool.name == tool_name:
                try:
                    result = tool.invoke(tool_input)
                    return result
                except Exception as e:
                    return f"Error invoking {tool_name}: {str(e)}"
        return f"Tool '{tool_name}' not found"

    def get_tools_description(self):
        """Get description of all available tools."""
        descriptions = []
        for tool in self.tools:
            descriptions.append(f"- {tool.name}: {tool.description}")
        return "\n".join(descriptions)

    def process_query(
        self,
        user_input: str,
        clear_history: bool = False,
        session_id: Optional[str] = None,
        emit: Optional[Callable[[str, Any], None]] = None,
    ) -> dict:
        """Process a user query and generate a prompt-grounded BRD."""
        thinking_steps: list = []
        brd_file_path = None

        def _thinking(step: dict) -> None:
            if emit:
                emit("thinking", step)
            else:
                thinking_steps.append(step)

        def _progress(stage: str, message: str) -> None:
            if emit:
                emit("progress", {"stage": stage, "message": message})

        memory = memory_for_session(self._conversation_by_session, session_id)

        if clear_history:
            memory.clear()

        memory.chat_memory.add_user_message(user_input)

        _progress("analyze", "Analyzing your requirement…")
        _thinking({
            "type": "thinking",
            "content": f"Analyzing user requirement for BRD generation: '{user_input[:100]}...'",
            "tool_name": None,
            "tool_input": None,
        })
        _thinking({
            "type": "thinking",
            "content": "Using only the user's prompt as the source of truth — extracting tickets, tech stack, UI guidelines, files, validation rules, and acceptance criteria into a structured schema",
            "tool_name": None,
            "tool_input": None,
        })

        _progress("source", "Using prompt-only source material")
        _progress("llm", "Generating structured BRD JSON with the LLM (streaming)…")
        _thinking({
            "type": "thinking",
            "content": "Drafting structured BRD sections (executive summary, architecture, tech stack, UI guidelines, per-ticket breakdown, traceability)",
            "tool_name": None,
            "tool_input": None,
        })

        brd_prompt = BRD_PROMPT_TEMPLATE.format(user_input=user_input)

        def _on_llm_chunk(text: str) -> None:
            if text and emit:
                emit("response_chunk", {"chunk": text, "phase": "llm_json"})

        brd_data_json = self.ai_service.call_genai(
            brd_prompt,
            temperature=0.4,
            on_stream_chunk=_on_llm_chunk if emit else None,
        )

        _thinking({
            "type": "thinking",
            "content": "Structured BRD JSON received — parsing and rendering professional layout",
            "tool_name": None,
            "tool_input": None,
        })

        try:
            json_start = brd_data_json.find('{')
            json_end = brd_data_json.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                brd_data_json = brd_data_json[json_start:json_end]

            brd_data = json.loads(brd_data_json)
            brd_data = prune_empty(brd_data) or {}

            if not brd_data.get("project_name"):
                brd_data["project_name"] = "BRD"

            _progress("document", "Building professional BRD layout…")
            _thinking({
                "type": "tool_call",
                "content": "Rendering professional BRD document",
                "tool_name": "generate_brd",
                "tool_input": json.dumps(brd_data, indent=2)[:1500],
            })

            brd_file_path = generate_brd.invoke({"content": brd_data})

            _thinking({
                "type": "tool_result",
                "content": f"BRD document generated successfully at: {brd_file_path}",
                "tool_name": "generate_brd",
                "tool_input": None,
            })

            brd_content = ""
            try:
                with open(brd_file_path, 'r', encoding='utf-8') as f:
                    brd_content = f.read()
            except Exception as read_error:
                print(f"Warning: Could not read BRD file: {read_error}")

            section_titles = {
                "executive_summary": "Executive Summary",
                "business_context": "Business Context",
                "scope": "Scope",
                "stakeholders": "Stakeholders",
                "solution_overview": "Solution Overview",
                "user_journey": "User Journey",
                "architecture": "Architecture",
                "technology_stack": "Technology Stack",
                "ui_brand_guidelines": "UI & Brand Guidelines",
                "feature_breakdown": "Feature Breakdown",
                "functional_requirements": "Functional Requirements",
                "non_functional_requirements": "Non-Functional Requirements",
                "validation_rules": "Validation Rules",
                "integration_requirements": "Integration Requirements",
                "data_requirements": "Data Requirements",
                "dependencies": "Dependencies",
                "assumptions_constraints": "Assumptions & Constraints",
                "acceptance_criteria_master": "Acceptance Criteria",
                "traceability_matrix": "Traceability Matrix",
                "test_strategy": "Test Strategy",
                "risks_mitigation": "Risks & Mitigation",
                "glossary": "Glossary",
            }
            included_sections = [
                title for key, title in section_titles.items()
                if not _is_empty(brd_data.get(key))
            ]
            included_sections_text = "\n".join(
                f"{i}. ✓ {t}" for i, t in enumerate(included_sections, 1)
            ) or "No detailed sections were included because the prompt did not provide enough section-specific information."

            final_response = f"""✅ **Business Requirements Document Generated Successfully!**

**Project:** {brd_data.get('project_name', 'BRD')}

---

## 📄 Complete BRD Document

{brd_content}

---

**Document Sections Included:**
{included_sections_text}
---

📥 **[Download BRD Document]({brd_file_path})**

Would you like me to refine any specific section or generate additional documentation?"""

        except json.JSONDecodeError:
            _thinking({
                "type": "thinking",
                "content": "JSON parsing failed — returning raw LLM output for review",
                "tool_name": None,
                "tool_input": None,
            })

            final_response = f"""⚠️ **BRD Generated with Partial Data**

Based on your requirement: "{user_input}"

The AI generated detailed content but the JSON structure could not be parsed. Raw output:

{brd_data_json[:1500]}...

Please try rephrasing your requirement for better results."""

        memory.chat_memory.add_ai_message(final_response)

        _progress("complete", "BRD document ready")

        out: Dict[str, Any] = {
            "response": final_response,
            "thinking_steps": [] if emit else thinking_steps,
            "brd_file_path": brd_file_path,
        }
        if emit:
            out["_emit_reset_before_response_chunks"] = True
        return out


def main():
    """Main function to run the BRD Generation agent."""
    agent = BRDGenerationAgent()

    print("=" * 70)
    print("📄 BRD Generation Agent - AI-Powered Business Requirements")
    print("=" * 70)
    print("\nThis agent will:")
    print("  • Use only your prompt as source material")
    print("  • Generate a professional Business Requirements Document")
    print("  • Include only BRD sections supported by your prompt")
    print("\nType 'quit' or 'exit' to stop the agent.")
    print("Type 'clear' to clear conversation history.\n")

    while True:
        user_input = input("👤 You: ").strip()

        if not user_input:
            continue

        if user_input.lower() in ['quit', 'exit', 'q']:
            print("\n👋 Thank you for using BRD Generation Agent!")
            break

        if user_input.lower() == 'clear':
            agent._conversation_by_session.clear()
            print("✓ Conversation history cleared.\n")
            continue

        print("\n🤖 BRD Agent: Processing your requirement...\n")

        try:
            result = agent.process_query(user_input)

            if result.get('thinking_steps'):
                print("💭 Thinking Process:")
                for step in result['thinking_steps']:
                    if step['type'] == 'thinking':
                        print(f"   → {step['content']}")
                    elif step['type'] == 'tool_call':
                        print(f"   🔧 {step['content']}")
                    elif step['type'] == 'tool_result':
                        print(f"   ✓ Result received")
                print()

            print(result['response'])
            print()

        except Exception as e:
            print(f"\n❌ Error: {str(e)}\n")


if __name__ == "__main__":
    main()
