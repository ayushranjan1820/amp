# AI Agents Platform

## Overview

This project is a full-stack web application showcasing and facilitating interaction with multiple AI agents through a marketplace-style interface. It features a Global Chat with intelligent routing to specialized AI agents for tasks like web search, document generation, regulatory compliance, market analysis, and advanced code operations (GitHub management, unit test generation, code sandboxing). The platform aims to be a versatile AI interaction hub.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### UI/UX Decisions
The platform features a modern, marketplace-style interface built with React 19 and TypeScript, using Tailwind CSS v4 and adhering to PwC brand guidelines. Key components include an agent marketplace, individual agent chat interfaces, a ChatGPT-style Global Chat, and an authenticated Admin Dashboard for management.

### Technical Implementations
The frontend uses React Context API for state management, React Router DOM v7 for routing, and Vite 7 for building.
The backend is built with FastAPI (Python) and uses a modular, agent-based architecture. It integrates primarily with PwC GenAI service (Gemini 2.0 Flash) and supports an optional local Ollama provider for development. Each agent is self-contained, defining its own tools and logic. Core features include an LLM-based Global Chat Router, a centralized `agents_catalog.json` for agent metadata, JWT-based Admin authentication, and PostgreSQL for chat session management. A `tiktoken`-based module handles token counting and prompt validation.

### Feature Specifications
- **Global Chat Router**: Classifies user queries and routes them to relevant specialized agents.
- **Admin Dashboard**: Manages agents, chat sessions, and cost analytics. Includes a maintenance mode toggle.
- **External Agent Support**: Allows onboarding of agents hosted outside the platform via `external_api_url` in the Admin Dashboard.
- **Agent Capabilities**:
    - **Basic Agent**: Web search, weather, data export.
    - **JIRA Agent**: JIRA ticket management (search, create, update, analytics) with input validation, error handling, and a dedicated analytics dashboard.
    - **BRD Generation Agent**: Automates Business Requirements Document creation via web research.
    - **RBI Circular Agent**: Fetches, searches, and summarizes RBI regulatory notifications using multi-domain search and LLM-driven synthesis.
    - **BPMN Generator Agent**: Generates BPMN 2.0 diagrams from various document types.
    - **Market Research Agent**: Conducts comprehensive market research and generates reports.
    - **GitHub Repo Agent**: Handles GitHub repository operations (cloning, tech stack extraction, documentation generation, code modification, pushing).
    - **Unit Test Generator Agent**: Generates comprehensive unit tests for codebases, integrated with the GitHub Agent.
    - **Code Sandbox Agent**: Clones repositories, installs dependencies, and runs applications in isolated environments.
    - **Web Test Agent**: Analyzes webpages by URL to generate manual and automated test cases (Selenium, Playwright).
    - **MongoDB Atlas KB Agent**: Ingests documents, creates vector embeddings, and enables semantic Q&A using MongoDB Atlas. Uses a 10-step ingestion pipeline: parse → caption images (gemini) → interleave captions → create doc record → chunk (~500 chars) → extract keywords (TF-IDF) → generate 768d embeddings (vertex_ai.text-embedding-005) → store chunks → update doc status. Two collections per project: `knowledge_documents_{project_id}` (metadata) and `knowledge_chunks_{project_id}` (text + keywords + embedding).
    - **Company Research Agent**: Performs comprehensive company research using parallel web searches and synthesizes executive-grade reports.
    - **Meeting Prep Agent**: Prepares for meetings by clarifying context, conducting multi-dimensional research, and synthesizing talking points and peer benchmarking.
    - **Email Agent**: Interactive agent for composing and sending professional HTML emails.
    - **Document Formatter Agent**: Extracts and reformats content from various document types, supports summarization and content restructuring.
    - **PPT Generator Agent**: Generates professional PowerPoint (.pptx) presentations from any topic. Uses LLM to create structured slide content and Gemini (`vertex_ai.gemini-2.5-flash-image`) via the `/images/generations` endpoint to generate relevant AI images for every slide. Falls back to categorized stock photos if AI generation fails. Supports 4 themes (professional, modern, dark, vibrant) and produces downloadable files with background images on title/section/closing slides and inline images on content slides.
    - **Claude Code Agent**: Advanced code generation and repository management using Claude Code CLI with full tool access.
    - **3GPP Specifications Agent**: Indexes and searches 3GPP TSG RAN FTP repository for telecommunications standards documents.
    - **Web Search Agent**: Advanced web search using the Perplexity API with multiple search modes (general, news, academic, writing, math, deep research). Uses LLM to classify query intent, optimize search parameters, and format results with citations, images, sources, and follow-up questions. Features a custom `WebSearchResultView` frontend component for rich result presentation.
- **User Management & Access Control**: Three-tier role system: `super_admin` (the built-in `admin` account — permanent full access, immutable, can create admins and assign any permissions), `admin` (created by super_admin — full access to all menus, can create/manage regular users but NOT create other admins or change permissions), `user` (restricted to assigned menu permissions). Each user can be assigned specific menu permissions (overview, agents, sessions, costs, usage, workflows, knowledge-base, settings, chat). Users only see the sidebar menus they have permission to access. Admins and super_admin have a "User Management" tab. User management includes create, edit, delete, activate/deactivate, and password reset. All user data stored in `admin_users` table with `role`, `menu_permissions` (JSONB), and `is_active` columns. JWT tokens include role and permissions for frontend enforcement. Server-side enforcement on all protected endpoints.
- **Workflow Orchestrator**: Feature for creating and executing multi-agent workflows from natural language instructions, with real-time SSE streaming and dependency resolution. All workflows are scoped to the user who created them (`user_id` column in `workflows` and `workflow_executions` tables). Admin users can see all workflows; regular users only see their own. Includes **Execution History** persistence: each workflow run saves step-by-step results (query, response, status, download URLs) to `workflow_executions` + `workflow_execution_steps` DB tables. Past executions are listed with timestamp/status/duration when loading a workflow, and clicking one shows full step detail in a read-only viewer with markdown rendering.
- **External Agent LLM Layer**: All external (onboarded) agents are wrapped with a two-phase LLM layer: (1) LLM adapts the user's natural language query into the correct API payload format based on the cURL/config template, (2) LLM formats the raw API response into a clean, user-friendly markdown answer. Graceful fallback to template substitution if LLM adaptation fails. Applied uniformly across direct chat, Global Chat Router, and Workflow Orchestrator paths.

### System Design Choices
The system uses PostgreSQL for persistence. LLM integration includes features like token management with `tiktoken` for validation and auto-truncation. Cross-agent collaboration is facilitated by the Router agent and the Workflow Orchestrator, which allows chaining agents with automatic output piping. Streaming execution provides real-time updates and interactive follow-ups. External agents use `_llm_call_async()` (in `api.py`) for lightweight async LLM calls with the same GenAI endpoint used by all platform agents.

## External Dependencies

### AI/LLM Services
- PwC GenAI Service (Gemini 2.5 Flash Image)
- Perplexity AI (Sonar models for web search)
- Ollama (optional, for local development)

### External APIs
- DuckDuckGo Search
- Perplexity API (Web Search Agent)
- Open-Meteo API
- JIRA Cloud API
- Resend Email API

### Key Libraries
- **Backend**: FastAPI, Uvicorn, LangChain, Pydantic, httpx, MCP (`mcp[cli]`), ReportLab, BeautifulSoup4, python-docx, pypdf, openpyxl, python-pptx, duckduckgo_search, Pillow, Resend.
- **Frontend**: bpmn-js, Mermaid, react-simple-maps, sql-formatter, recharts, react-markdown, react-router-dom.

### Deployment
- **Target**: Autoscale
- **Build**: `bash build.sh` (builds frontend into `frontend/dist`)
- **Run**: `cd server && gunicorn --bind=0.0.0.0:5000 --reuse-port --workers=2 --timeout=120 --worker-class=uvicorn.workers.UvicornWorker api:app`
- **Architecture**: FastAPI serves both the API (`/api/*`) and the built React frontend as static files from `frontend/dist`

### MCP (Cursor / VS Code) — remote HTTP connection

The API mounts an MCP server so IDEs can call catalog agents as tools over the network.

- **Recommended URL (Streamable HTTP)**  
  Use the **mount root** as the MCP server URL in Cursor settings (`.cursor/mcp.json` → `mcpServers.<name>.url`):

  - Local: `http://localhost:8000/mcp` (or whatever host/port your API uses)
  - Production: `https://<your-domain>/mcp`

  Cursor sends **GET**, **POST**, and **DELETE** to this path. Your reverse proxy must forward all three and use a generous timeout for long-running tools.

- **Legacy SSE URL**  
  `https://<your-domain>/mcp/sse` (GET) with client POSTs to `/mcp/messages/?session_id=...`. Prefer the Streamable HTTP URL above; it avoids transport fallback issues in the IDE.

- **Credentials and agent allowlist (remote URL transport)**  
  Pass a JSON object in the HTTP header **`X-Marketplace-Agent-Env`** (stringify JSON for `mcp.json` `headers`). Include at least **`AGENTS_API_BASE`** (e.g. `https://your-domain`) and any agent keys (JIRA, DB, etc.). Optional **`MCP_ALLOWED_AGENT_IDS`**: comma-separated catalog ids or JSON array string; when set, only those tools are listed and callable.

- **Stdio transport (local dev)**  
  Run `python mcp_server.py` from `server/` and point `mcp.json` at the **stdio** command transport. Set the same env vars in `mcp.json` `env` instead of the header.

- **Implementation**  
  `server/mcp_sse.py` (Streamable HTTP + SSE + message POST), mounted in `api.py` at `/mcp`. The FastAPI lifespan runs `StreamableHTTPSessionManager` so sessions stay valid for the process lifetime (avoid `uvicorn --reload` or frequent restarts if the IDE keeps disconnecting).