"""Architecture diagram generation tool"""

import re
from ..ai_service import ai_service
from ..utils.file_operations import (
    get_file_tree,
    read_key_files,
    collect_source_files,
    format_files_for_prompt
)
from ..utils.mermaid_sanitizer import enforce_architecture_section


def generate_architecture(repo_path: str, repo_name: str) -> str:
    """
    Generate architecture analysis with diagrams for a repository.
    
    Args:
        repo_path: Path to the repository
        repo_name: Name of the repository
        
    Returns:
        Combined architecture document with diagrams
    """
    key_files = read_key_files(repo_path)
    source_files = collect_source_files(repo_path)
    tree = get_file_tree(repo_path)

    # Build file summaries
    file_summaries = ""
    for name, content in list(source_files.items())[:30]:
        lines = content.split('\n')
        imports = [l for l in lines[:30] if any(k in l for k in ['import ', 'from ', 'require(', 'include'])]
        classes = [l.strip() for l in lines if any(k in l for k in ['class ', 'def ', 'function ', 'export ', 'interface '])][:10]
        file_summaries += f"\n--- {name} ---\nImports: {'; '.join(imports[:5])}\nDefinitions: {'; '.join(classes[:5])}\n"

    base_context = f"""Repository: {repo_name}
File Structure:
{tree}

Key Configuration Files:
{format_files_for_prompt(key_files)}

Source File Analysis:
{file_summaries[:8000]}"""

    # Step 1: Generate architecture document
    doc_prompt = f"""Analyze this repository and generate a detailed architecture document.
IMPORTANT: Do NOT generate any Mermaid diagrams in this response. The diagrams will be generated separately.

{base_context}

Generate the following sections in markdown:

## 🏗️ Architecture Overview: {repo_name}

### System Architecture
(describe the overall architecture pattern: monolith, microservices, MVC, etc. Be detailed about layers, tiers, and how components are organized.)

### Component Breakdown
(describe each major component/module and its responsibility in detail. Include how they interact with each other.)

### Key Design Patterns
(identify design patterns used in the codebase with specific examples from the code)

### Technology Interactions
(describe how different technologies and services interact: APIs, databases, message queues, external services, etc.)

Do NOT include any mermaid code blocks. Focus purely on the written architectural analysis."""

    doc_response = ai_service.call_genai(doc_prompt, max_tokens=8192)

    # Step 2: Generate architecture diagram
    arch_prompt = f"""You are generating a Mermaid architecture diagram for a software repository.

{base_context}

Generate ONLY an Architecture Diagram using Mermaid `graph TD` syntax.
The diagram should show all major components, their relationships, and how they connect.

LABELING & SIMPLICITY GUIDELINES:
Keep the diagram HIGH-LEVEL and SIMPLE. Show only the major building blocks of the system — typically 8 to 15 nodes maximum. Do NOT break things down into individual files, functions, or micro-components.

Label each node with a short, plain-English name that describes its purpose. Add the technology in parentheses only for the main ones.
Examples: "Web App (React)", "API Server (FastAPI)", "Database (PostgreSQL)", "Email Service", "Authentication", "File Storage"

Use 2-4 subgraphs at most, grouped by broad area. Keep subgraph labels short and simple.
Examples: "User-Facing", "Backend Services", "Data & Storage", "External Services"

Think of it as a whiteboard overview you'd draw in 2 minutes to explain the system to someone new. If a non-technical person can't understand it in 30 seconds, it's too complex.

CRITICAL MERMAID SYNTAX RULES — you MUST follow these exactly:
1. For node labels with special characters like parentheses, use QUOTED square brackets: A["Client App (React)"] NOT A[Client App (React)]
2. ALWAYS quote labels that contain parentheses (), curly braces {{}}, pipes |, angle brackets <>, or ampersands &
3. Node ID must be simple alphanumeric: A, B, API, DB1 — no spaces or special chars in IDs
4. Correct examples:
   - A["Order Processing (FastAPI)"] --> B["Customer Database (PostgreSQL)"]
   - C["User Interface (React)"] --> D["API Gateway"]
   - subgraph UserMgmt["User Management"]
5. WRONG examples (these will cause parse errors):
   - A[Client App (React)] — parentheses break the parser
   - A(Component Name (v2)) — nested parentheses break the parser
6. For arrows use: -->, ---|label|, -->|label|
7. subgraph labels with special chars must also be quoted: subgraph BE["Backend (Python)"]

Your response MUST follow this EXACT format:

### Architecture Diagram
```mermaid
graph TD
    ... (your diagram here)
```

Output ONLY the section above. Do not include any other text, explanation, or sections."""

    arch_diagram_response = ai_service.call_genai(arch_prompt, max_tokens=8192)
    arch_diagram_section = enforce_architecture_section(arch_diagram_response, "### Architecture Diagram")

    # Step 3: Generate data flow diagram
    flow_prompt = f"""You are generating a Mermaid data flow diagram for a software repository.

{base_context}

Generate ONLY a Data Flow Architecture Diagram using Mermaid syntax.
The diagram should show how data flows through the system: user requests, API calls, data processing, database operations, and responses.
Make the diagram comprehensive — use the full context provided to capture all important data flows.

Use `sequenceDiagram` syntax. Show the complete data journey from user interaction through all system layers and back.

CRITICAL MERMAID SYNTAX RULES — you MUST follow these exactly:
1. participant names with special characters MUST be aliased: participant FE as Frontend (React) — NOT participant Frontend (React)
2. Correct participant declaration: participant API as FastAPI Backend
3. Messages: FE->>API: Send login request
4. Activations: activate API / deactivate API
5. Notes: Note over FE,API: Authentication flow
6. Alt blocks: alt Success / else Failure / end
7. NEVER use parentheses in participant names directly — always use the alias form
8. NEVER use square brackets, curly braces, angle brackets < >, or special characters in message text — use plain English only
9. Keep participant IDs short and simple: FE, API, DB, Auth, Cache, etc.

Your response MUST follow this EXACT format:

### Data Flow Architecture Diagram
```mermaid
sequenceDiagram
    ... (your diagram here)
```

Output ONLY the section above. Do not include any other text, explanation, or sections."""

    flow_diagram_response = ai_service.call_genai(flow_prompt, max_tokens=8192)
    flow_diagram_section = enforce_architecture_section(flow_diagram_response, "### Data Flow Architecture Diagram")

    # Remove any mermaid blocks from the doc body
    doc_body = re.sub(r'```mermaid\s*\n.*?```', '', doc_response.strip(), flags=re.DOTALL).strip()

    # Combine all sections
    combined = doc_body + "\n\n" + arch_diagram_section + "\n\n" + flow_diagram_section

    return combined
