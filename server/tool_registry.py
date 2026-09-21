"""Tool Registry — comprehensive enterprise-grade tool definitions.

Seeded once at startup into tool_definitions table.
Each tool has: identity, schema, implementation reference, category, and required env keys.
The dynamic_agent_runtime resolves these at invocation time.
"""

import json
from typing import List, Dict, Any
from agent_registry import upsert_tool, list_tools


BUILTIN_TOOLS: List[Dict[str, Any]] = [

    # =====================================================================
    # CATEGORY: Search & Research
    # =====================================================================
    {
        "id": "tool_web_search",
        "slug": "web-search",
        "name": "Web Search",
        "description": 'Search the web in real-time using Ollama Web Search API. Use parameter: {"query": "<your search terms>"}. Returns summarized results with source URLs. Great for current events, fact-checking, and research.',
        "tool_type": "builtin",
        "schema_config": {
            "category": "search",
            "input": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search terms to look up"},
                },
                "required": ["query"],
            },
            "output": {"type": "string"},
            "env_keys": ["OLLAMA_API_KEY"],
        },
        "implementation": {
            "type": "ollama_web_search",
            "api_url": "https://ollama.com/api/web_search",
        },
    },
    {
        "id": "tool_web_scrape",
        "slug": "web-scrape",
        "name": "Web Page Scraper",
        "description": "Fetch and extract clean text content from any URL. Strips HTML, handles JavaScript-rendered pages. Returns structured text for analysis.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "search",
            "input": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            "output": {"type": "string"},
        },
        "implementation": {"type": "http_scraper"},
    },

    # =====================================================================
    # CATEGORY: LLM & AI
    # =====================================================================
    {
        "id": "tool_llm_call",
        "slug": "llm-call",
        "name": "LLM Call (PwC / Ollama)",
        "description": "Make a direct LLM call with a custom prompt. Supports PwC GenAI (Gemini, GPT, Claude) and Ollama Cloud. Use for sub-tasks, summarization, translation, or chain-of-thought reasoning within your agent.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "ai",
            "input": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "model": {"type": "string", "default": ""},
                    "temperature": {"type": "number", "default": 0.7},
                    "max_tokens": {"type": "integer", "default": 4096},
                },
                "required": ["prompt"],
            },
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {"type": "llm_call", "service": "base_ai_service"},
    },
    {
        "id": "tool_ocr",
        "slug": "ocr",
        "name": "OCR — Image to Text",
        "description": "Extract text from images using Gemini Vision. Supports scanned documents, receipts, handwritten notes, screenshots, and photographs. Returns structured text with layout preservation.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "ai",
            "input": {
                "type": "object",
                "properties": {
                    "image_base64": {"type": "string", "description": "Base64-encoded image"},
                    "image_url": {"type": "string", "description": "URL to an image"},
                    "prompt": {"type": "string", "default": "Extract all text from this image, preserving layout and structure."},
                },
            },
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {"type": "vision_llm", "model": ""},
    },
    {
        "id": "tool_text_to_speech",
        "slug": "text-to-speech",
        "name": "Text to Speech",
        "description": "Convert text to natural-sounding speech audio using ElevenLabs. Returns audio data. Great for accessibility, voice bots, and audio content generation.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "ai",
            "input": {"type": "object", "properties": {"text": {"type": "string"}, "voice_id": {"type": "string"}}, "required": ["text"]},
            "output": {"type": "string"},
            "env_keys": ["ELEVENLABS_API_KEY"],
        },
        "implementation": {"type": "elevenlabs_tts"},
    },
    {
        "id": "tool_embeddings",
        "slug": "embeddings",
        "name": "Text Embeddings",
        "description": "Generate vector embeddings for text using PwC GenAI. Use for semantic search, similarity matching, clustering, and RAG pipelines.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "ai",
            "input": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            "output": {"type": "array"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {"type": "embeddings", "service": "base_ai_service"},
    },

    # =====================================================================
    # CATEGORY: File Processing
    # =====================================================================
    {
        "id": "tool_file_processor",
        "slug": "file-processor",
        "name": "File Processor (PDF, CSV, Excel, PPT, Images)",
        "description": "Parse and extract content from documents: PDF (text + tables), CSV/TSV, Excel (.xlsx), PowerPoint (.pptx), Word (.docx), and images. Uses Gemini Vision for image-based files. Returns structured text.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "files",
            "input": {
                "type": "object",
                "properties": {
                    "file_content_b64": {"type": "string", "description": "Base64-encoded file content"},
                    "file_name": {"type": "string"},
                    "file_type": {"type": "string", "enum": ["pdf", "csv", "tsv", "xlsx", "pptx", "docx", "txt", "json", "png", "jpg", "jpeg", "gif", "webp"]},
                },
                "required": ["file_content_b64", "file_name", "file_type"],
            },
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {"type": "file_processor"},
    },
    {
        "id": "tool_csv_analyzer",
        "slug": "csv-analyzer",
        "name": "CSV / Excel Analyzer",
        "description": "Load CSV or Excel files and perform data analysis: summary statistics, column profiling, filtering, grouping, and pivot tables. Uses pandas under the hood.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "files",
            "input": {
                "type": "object",
                "properties": {
                    "file_content_b64": {"type": "string"},
                    "file_name": {"type": "string"},
                    "analysis_query": {"type": "string", "description": "What analysis to perform"},
                },
                "required": ["file_content_b64", "analysis_query"],
            },
            "output": {"type": "string"},
        },
        "implementation": {"type": "csv_analyzer"},
    },
    {
        "id": "tool_document_formatter",
        "slug": "document-formatter",
        "name": "Document Formatter & Converter",
        "description": "Format and convert documents between Markdown, HTML, PDF, and DOCX. Apply templates, styling, and structure transformations.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "files",
            "input": {"type": "object", "properties": {"content": {"type": "string"}, "from_format": {"type": "string"}, "to_format": {"type": "string"}}, "required": ["content", "to_format"]},
            "output": {"type": "string"},
        },
        "implementation": {
            "module": "agents.Document_formatter_agent",
            "source_agent": "document_formatter_agent",
        },
    },

    # =====================================================================
    # CATEGORY: Content Generation
    # =====================================================================
    {
        "id": "tool_ppt_generator",
        "slug": "ppt-generator",
        "name": "PowerPoint Generator",
        "description": "Generate professional multimodal PowerPoint presentations from text. Creates slides with titles, bullet points, charts, and relevant stock images. Returns a downloadable .pptx file.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "content",
            "input": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "num_slides": {"type": "integer", "default": 8},
                    "style": {"type": "string", "default": "professional", "enum": ["professional", "creative", "minimal", "corporate"]},
                },
                "required": ["topic"],
            },
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {
            "module": "agents.PPT_generator_agent.agent",
            "source_agent": "ppt_generator_agent",
            "function": "generate_ppt",
        },
    },
    {
        "id": "tool_brd_generator",
        "slug": "brd-generator",
        "name": "BRD Generator",
        "description": "Generate prompt-grounded Business Requirements Documents from project descriptions. Includes only sections supported by the provided prompt.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "content",
            "input": {"type": "object", "properties": {"project_description": {"type": "string"}}, "required": ["project_description"]},
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {
            "module": "agents.BRD_generation.agent",
            "source_agent": "brd_agent",
        },
    },
    {
        "id": "tool_email_composer",
        "slug": "email-composer",
        "name": "Email Composer & Sender",
        "description": "Compose professional emails from natural language instructions and send them. Supports HTML formatting, attachments, and multiple recipients.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "content",
            "input": {
                "type": "object",
                "properties": {
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "html": {"type": "boolean", "default": False},
                },
                "required": ["to", "subject", "body"],
            },
            "output": {"type": "string"},
            "env_keys": ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"],
        },
        "implementation": {
            "module": "agents.Email_agent.tools",
            "source_agent": "email_agent",
        },
    },

    # =====================================================================
    # CATEGORY: Code & Execution
    # =====================================================================
    {
        "id": "tool_code_executor",
        "slug": "code-executor",
        "name": "Code Executor (Python)",
        "description": "Execute Python code in a sandboxed environment with pre-installed data science libraries (pandas, numpy, matplotlib, scikit-learn). Returns stdout, stderr, and generated files.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "code",
            "input": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "language": {"type": "string", "default": "python", "enum": ["python"]},
                    "timeout_seconds": {"type": "integer", "default": 30},
                },
                "required": ["code"],
            },
            "output": {"type": "string"},
        },
        "implementation": {
            "module": "agents.Code_sandbox_agent.tools",
            "source_agent": "code_sandbox_agent",
            "function": "execute_code",
        },
    },
    {
        "id": "tool_unit_test_gen",
        "slug": "unit-test-generator",
        "name": "Unit Test Generator",
        "description": "Analyze source code and generate comprehensive unit tests. Supports Python (pytest), JavaScript (Jest), TypeScript, Java (JUnit). Includes edge cases and mocking.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "code",
            "input": {
                "type": "object",
                "properties": {
                    "source_code": {"type": "string"},
                    "language": {"type": "string", "default": "python"},
                    "framework": {"type": "string", "default": "pytest"},
                },
                "required": ["source_code"],
            },
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {
            "module": "agents.Unit_test_agent.agent",
            "source_agent": "unit_test_agent",
        },
    },

    # =====================================================================
    # CATEGORY: Integrations (JIRA, GitHub, etc.)
    # =====================================================================
    {
        "id": "tool_jira",
        "slug": "jira-integration",
        "name": "JIRA Integration",
        "description": "Connect to Atlassian JIRA: create issues, update status, search tickets, add comments, manage sprints, and query project boards. Full JIRA REST API access.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["create_issue", "update_issue", "search", "get_issue", "add_comment", "transition", "list_projects"]},
                    "project_key": {"type": "string"},
                    "issue_key": {"type": "string"},
                    "summary": {"type": "string"},
                    "description": {"type": "string"},
                    "issue_type": {"type": "string", "default": "Task"},
                    "jql": {"type": "string"},
                    "comment": {"type": "string"},
                },
            },
            "output": {"type": "string"},
            "env_keys": ["JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"],
        },
        "implementation": {
            "module": "agents.JIRA_agent.tools",
            "source_agent": "jira_agent",
            "function": "jira_tool",
        },
    },
    {
        "id": "tool_github",
        "slug": "github-integration",
        "name": "GitHub Integration",
        "description": "Interact with GitHub: read repo files, analyze code, create/update issues, list PRs, search code, and manage repositories. Supports public and private repos.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["read_file", "list_files", "search_code", "create_issue", "list_issues", "list_prs", "get_repo_info"]},
                    "repo_url": {"type": "string"},
                    "path": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": ["repo_url"],
            },
            "output": {"type": "string"},
            "env_keys": ["GITHUB_TOKEN"],
        },
        "implementation": {
            "module": "agents.GitHub_repo_agent.tools",
            "source_agent": "github_repo_agent",
        },
    },
    {
        "id": "tool_slack_notify",
        "slug": "slack-notification",
        "name": "Slack Notification",
        "description": "Send messages, notifications, and alerts to Slack channels or users via webhook. Supports rich formatting with blocks, attachments, and mentions.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "message": {"type": "string"},
                    "blocks": {"type": "array"},
                },
                "required": ["message"],
            },
            "output": {"type": "string"},
            "env_keys": ["SLACK_WEBHOOK_URL"],
        },
        "implementation": {"type": "slack_webhook"},
    },
    {
        "id": "tool_telegram_notify",
        "slug": "telegram-notification",
        "name": "Telegram Notification",
        "description": "Send messages, alerts, and notifications to a Telegram chat or channel via the Bot API. Supports Markdown/HTML formatting and silent notifications.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "chat_id": {"type": "string", "description": "Target chat/channel id (e.g. @mychannel or 123456789). Falls back to TELEGRAM_DEFAULT_CHAT_ID."},
                    "message": {"type": "string"},
                    "parse_mode": {"type": "string", "enum": ["Markdown", "MarkdownV2", "HTML", ""], "default": ""},
                    "disable_notification": {"type": "boolean", "default": False},
                },
                "required": ["message"],
            },
            "output": {"type": "string"},
            "env_keys": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_DEFAULT_CHAT_ID"],
        },
        "implementation": {"type": "telegram_bot"},
    },
    {
        "id": "tool_google_drive",
        "slug": "google-drive",
        "name": "Google Drive",
        "description": "Read, list, download, and upload files in Google Drive. Supports folder navigation, search, and overwriting existing files. Authenticates via OAuth2 access token.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "search", "read", "upload", "download", "delete"]},
                    "file_id": {"type": "string", "description": "Drive file id (for read/download/delete)"},
                    "folder_id": {"type": "string", "description": "Parent folder id (for list/upload)"},
                    "query": {"type": "string", "description": "Drive search query, e.g. name contains 'report'"},
                    "file_name": {"type": "string"},
                    "mime_type": {"type": "string", "default": "application/octet-stream"},
                    "file_content_b64": {"type": "string", "description": "Base64 file content for upload"},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["GOOGLE_DRIVE_ACCESS_TOKEN"],
        },
        "implementation": {"type": "google_drive"},
    },
    {
        "id": "tool_sharepoint",
        "slug": "sharepoint",
        "name": "SharePoint / OneDrive",
        "description": "Read, list, download, and upload files in Microsoft SharePoint or OneDrive via Microsoft Graph API. Supports site/drive navigation and file overwrites.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "search", "read", "upload", "download", "delete"]},
                    "drive_id": {"type": "string", "description": "Graph drive id (omit to use default user drive)"},
                    "item_id": {"type": "string", "description": "Drive item id (for read/download/delete)"},
                    "folder_path": {"type": "string", "description": "Path within drive (e.g. /Documents/Reports)"},
                    "file_name": {"type": "string"},
                    "query": {"type": "string"},
                    "file_content_b64": {"type": "string", "description": "Base64 file content for upload"},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["MS_GRAPH_ACCESS_TOKEN", "SHAREPOINT_SITE_ID"],
        },
        "implementation": {"type": "sharepoint_graph"},
    },
    {
        "id": "tool_gmail",
        "slug": "gmail",
        "name": "Gmail (Read / Summarize / Draft)",
        "description": "Connect to Gmail to list and read inbox messages, summarize threads, and create draft replies. Uses OAuth2 access token. Drafts are saved (not auto-sent) for review.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read", "search", "summarize", "draft", "send_draft"]},
                    "query": {"type": "string", "description": "Gmail search query, e.g. from:boss@x.com is:unread"},
                    "message_id": {"type": "string"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["GMAIL_ACCESS_TOKEN"],
        },
        "implementation": {"type": "gmail_api"},
    },
    {
        "id": "tool_outlook",
        "slug": "outlook",
        "name": "Outlook (Read / Summarize / Draft)",
        "description": "Connect to Outlook / Microsoft 365 mail to list and read messages, summarize conversations, and create draft replies via Microsoft Graph. Drafts are saved for review.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read", "search", "summarize", "draft", "send_draft"]},
                    "query": {"type": "string", "description": "Graph $search query"},
                    "message_id": {"type": "string"},
                    "folder": {"type": "string", "default": "inbox"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["MS_GRAPH_ACCESS_TOKEN"],
        },
        "implementation": {"type": "outlook_graph"},
    },

    # ---------------------------------------------------------------------
    # Zoho suite. All five share one OAuth app: ZOHO_CLIENT_ID /
    # ZOHO_CLIENT_SECRET / ZOHO_REFRESH_TOKEN, plus ZOHO_DC for the region.
    # Writes respect ZOHO_DRY_RUN, matching the Zoho workflow agents.
    # ---------------------------------------------------------------------
    {
        "id": "tool_zoho_mail",
        "slug": "zoho-mail",
        "name": "Zoho Mail (Read / Send)",
        "description": "List and read Zoho Mail messages and send mail from the connected mailbox. Runs over a pre-authorized Zoho MCP connection (ZOHO_MCP_URL) when one is set, otherwise the REST API with an OAuth refresh token. Honours ZOHO_DRY_RUN for sends.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "read", "search", "send"]},
                    "query": {"type": "string", "description": "Zoho Mail search term"},
                    "message_id": {"type": "string"},
                    "folder_id": {"type": "string"},
                    "to": {"type": "array", "items": {"type": "string"}},
                    "cc": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                    "unread_only": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["ZOHO_MCP_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC"],
        },
        "implementation": {"type": "zoho_mail"},
    },
    {
        "id": "tool_zoho_calendar",
        "slug": "zoho-calendar",
        "name": "Zoho Calendar (List / Create Events)",
        "description": "List Zoho calendars and events, and create events with attendees. Times are ISO 8601 and converted to Zoho's format automatically. Honours ZOHO_DRY_RUN.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list_calendars", "list_events", "create_event"]},
                    "title": {"type": "string"},
                    "start": {"type": "string", "description": "ISO 8601 start, e.g. 2026-09-18T15:00:00"},
                    "end": {"type": "string", "description": "ISO 8601 end. Omit to use duration_minutes."},
                    "duration_minutes": {"type": "integer", "default": 30},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "calendar_uid": {"type": "string"},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["ZOHO_MCP_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_CALENDAR_ID"],
        },
        "implementation": {"type": "zoho_calendar"},
    },
    {
        "id": "tool_zoho_crm",
        "slug": "zoho-crm",
        "name": "Zoho CRM (Contacts / Accounts / Tasks)",
        "description": "Search Zoho CRM contacts and accounts, read a contact, and create follow-up tasks or notes against a record (API v6). Honours ZOHO_DRY_RUN for writes.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "search_contacts",
                            "get_contact",
                            "latest_contact",
                            "search_accounts",
                            "create_task",
                            "create_note",
                        ],
                    },
                    "email": {"type": "string"},
                    "name": {"type": "string"},
                    "contact_id": {"type": "string"},
                    "subject": {"type": "string", "description": "Task subject"},
                    "due_date": {"type": "string", "description": "YYYY-MM-DD or ISO 8601"},
                    "description": {"type": "string"},
                    "priority": {"type": "string", "default": "High"},
                    "related_contact_id": {"type": "string"},
                    "related_account_id": {"type": "string"},
                    "parent_id": {"type": "string", "description": "Record the note attaches to"},
                    "module": {"type": "string", "default": "Contacts"},
                    "title": {"type": "string", "description": "Note title"},
                    "content": {"type": "string", "description": "Note content"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["ZOHO_MCP_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_CRM_OWNER_ID"],
        },
        "implementation": {"type": "zoho_crm"},
    },
    {
        "id": "tool_zoho_desk",
        "slug": "zoho-desk",
        "name": "Zoho Desk (Tickets / Reply)",
        "description": "List and read Zoho Desk tickets, read their threads, reply to the customer, and add comments. Requires ZOHO_ORG_ID. Honours ZOHO_DRY_RUN for replies and comments.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "read", "latest_high_priority", "threads", "reply", "comment"],
                    },
                    "ticket_id": {"type": "string"},
                    "priority": {"type": "string", "description": "Filter: Low, Medium, High, Urgent"},
                    "status": {"type": "string", "default": "Open"},
                    "content": {"type": "string", "description": "Reply or comment body"},
                    "to_address": {"type": "string"},
                    "is_public": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "default": 10},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": ["ZOHO_MCP_URL", "ZOHO_CLIENT_ID", "ZOHO_CLIENT_SECRET", "ZOHO_REFRESH_TOKEN", "ZOHO_DC", "ZOHO_ORG_ID"],
        },
        "implementation": {"type": "zoho_desk"},
    },
    {
        "id": "tool_zoho_cliq",
        "slug": "zoho-cliq",
        "name": "Zoho Cliq (Post Message)",
        "description": "Post a message to a Zoho Cliq channel. Uses ZOHO_CLIQ_WEBHOOK_URL when set (no OAuth scope needed), otherwise the Cliq API with ZOHO_CLIQ_CHANNEL. Honours ZOHO_DRY_RUN.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "integrations",
            "input": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["post", "list_channels"], "default": "post"},
                    "text": {"type": "string"},
                    "channel": {"type": "string", "description": "Channel name; defaults to ZOHO_CLIQ_CHANNEL"},
                    "card_title": {"type": "string"},
                },
                "required": ["action"],
            },
            "output": {"type": "string"},
            "env_keys": [
                "ZOHO_MCP_URL",
                "ZOHO_CLIENT_ID",
                "ZOHO_CLIENT_SECRET",
                "ZOHO_REFRESH_TOKEN",
                "ZOHO_DC",
                "ZOHO_CLIQ_CHANNEL",
                "ZOHO_CLIQ_WEBHOOK_URL",
            ],
        },
        "implementation": {"type": "zoho_cliq"},
    },

    # =====================================================================
    # CATEGORY: Database & Data (platform persistence is MongoDB; SQL tool is user-provided DB)
    # =====================================================================
    {
        "id": "tool_sql_query",
        "slug": "sql-query",
        "name": "SQL Database Query",
        "description": "Execute SQL queries against PostgreSQL, MySQL, or SQLite databases. Includes safety guardrails: read-only mode, query validation, and result size limits. Returns tabular results.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "data",
            "input": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "connection_string": {"type": "string"},
                    "read_only": {"type": "boolean", "default": True},
                },
                "required": ["query"],
            },
            "output": {"type": "string"},
            "env_keys": ["DATABASE_URL"],
        },
        "implementation": {
            "module": "agents.SQL_DB_agent.tools",
            "source_agent": "sql_db_agent",
        },
    },
    {
        "id": "tool_mongodb",
        "slug": "mongodb-query",
        "name": "MongoDB Query & Vector Search",
        "description": "Query MongoDB collections: find, aggregate, vector search (Atlas). Supports CRUD operations, text search, and geospatial queries.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "data",
            "input": {
                "type": "object",
                "properties": {
                    "database": {"type": "string"},
                    "collection": {"type": "string"},
                    "operation": {"type": "string", "enum": ["find", "aggregate", "vector_search", "insert", "count"]},
                    "query": {"type": "object"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["collection", "operation"],
            },
            "output": {"type": "string"},
            "env_keys": ["MONGODB_URI"],
        },
        "implementation": {
            "module": "agents.MongoDB_RAG_agent.tools",
            "source_agent": "mongodb_rag_agent",
        },
    },

    # =====================================================================
    # CATEGORY: Communication & HTTP
    # =====================================================================
    {
        "id": "tool_http_api",
        "slug": "http-api-call",
        "name": "HTTP API Client",
        "description": "Make HTTP requests to any REST API. Supports GET, POST, PUT, PATCH, DELETE with custom headers, authentication, query params, and JSON/form body. Handles pagination and retries.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "communication",
            "input": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "default": "GET", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                    "headers": {"type": "object"},
                    "body": {"type": "object"},
                    "params": {"type": "object"},
                    "auth_type": {"type": "string", "enum": ["none", "bearer", "basic", "api_key"]},
                    "auth_value": {"type": "string"},
                },
                "required": ["url"],
            },
            "output": {"type": "string"},
        },
        "implementation": {"type": "http_client"},
    },

    # =====================================================================
    # CATEGORY: Browser & Automation
    # =====================================================================
    {
        "id": "tool_browser_automation",
        "slug": "browser-automation",
        "name": "Browser Automation (Playwright)",
        "description": "Automate browser interactions: navigate pages, click buttons, fill forms, take screenshots, extract structured data. Uses headless Chromium via Playwright. Great for web scraping and UI testing.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "automation",
            "input": {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "actions": {"type": "array", "items": {"type": "object"}},
                    "screenshot": {"type": "boolean", "default": False},
                    "extract_text": {"type": "boolean", "default": True},
                },
                "required": ["url"],
            },
            "output": {"type": "string"},
        },
        "implementation": {
            "module": "agents.Browser_agent.tools",
            "source_agent": "browser_agent",
        },
    },

    # =====================================================================
    # CATEGORY: Security & Compliance
    # =====================================================================
    {
        "id": "tool_security_scan",
        "slug": "security-scan",
        "name": "Security Vulnerability Scanner",
        "description": "Scan code or URLs for security vulnerabilities: OWASP Top 10, SQL injection, XSS, CSRF, dependency CVEs, secrets leakage. Returns severity-ranked findings with remediation guidance.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "security",
            "input": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Code snippet or URL to scan"},
                    "scan_type": {"type": "string", "enum": ["code", "url", "dependency"], "default": "code"},
                },
                "required": ["target"],
            },
            "output": {"type": "string"},
            "env_keys": ["PWC_GENAI_API_KEY"],
        },
        "implementation": {
            "module": "agents.Shannon_security_agent.tools",
            "source_agent": "shannon_security_agent",
        },
    },

    # =====================================================================
    # CATEGORY: Utilities
    # =====================================================================
    {
        "id": "tool_json_processor",
        "slug": "json-processor",
        "name": "JSON Processor",
        "description": "Parse, query (JSONPath / jq syntax), transform, validate, and diff JSON data. Handles nested structures, arrays, and large payloads efficiently.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "utilities",
            "input": {
                "type": "object",
                "properties": {
                    "json_data": {"type": "string"},
                    "operation": {"type": "string", "enum": ["parse", "query", "transform", "validate", "diff"]},
                    "expression": {"type": "string"},
                },
                "required": ["json_data", "operation"],
            },
            "output": {"type": "string"},
        },
        "implementation": {"type": "json_processor"},
    },
    {
        "id": "tool_regex",
        "slug": "regex-processor",
        "name": "Regex / Text Processor",
        "description": "Apply regex patterns to extract, replace, or validate text. Supports named groups, lookaheads, and multi-line matching. Includes common pattern library (email, phone, URL, etc.).",
        "tool_type": "builtin",
        "schema_config": {
            "category": "utilities",
            "input": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "pattern": {"type": "string"},
                    "operation": {"type": "string", "enum": ["match", "findall", "replace", "split", "validate"]},
                    "replacement": {"type": "string"},
                },
                "required": ["text", "pattern"],
            },
            "output": {"type": "string"},
        },
        "implementation": {"type": "regex_processor"},
    },
    {
        "id": "tool_calculator",
        "slug": "calculator",
        "name": "Calculator & Math",
        "description": "Evaluate mathematical expressions, unit conversions, financial calculations (NPV, IRR, compound interest), statistical formulas, and date arithmetic.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "utilities",
            "input": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
            "output": {"type": "string"},
        },
        "implementation": {"type": "calculator"},
    },
    {
        "id": "tool_datetime",
        "slug": "datetime",
        "name": "Date & Time Utils",
        "description": "Get current date/time, convert timezones, calculate durations, parse date strings, generate cron expressions, and format dates for different locales.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "utilities",
            "input": {
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "enum": ["now", "convert_tz", "duration", "parse", "format", "cron"]},
                    "input_value": {"type": "string"},
                    "timezone": {"type": "string", "default": "UTC"},
                },
            },
            "output": {"type": "string"},
        },
        "implementation": {"type": "datetime_utils"},
    },
    {
        "id": "tool_knowledge_base",
        "slug": "knowledge-base-search",
        "name": "Knowledge Base Search (RAG)",
        "description": "Search your organization's knowledge base using semantic vector search. Query ingested documents (PDFs, docs, wikis) for relevant context. Powers retrieval-augmented generation.",
        "tool_type": "builtin",
        "schema_config": {
            "category": "data",
            "input": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "collection": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
            "output": {"type": "string"},
            "env_keys": ["MONGODB_URI"],
        },
        "implementation": {"type": "vector_search", "source_agent": "mongodb_rag_agent"},
    },
]


def get_tools_as_dicts() -> List[Dict[str, Any]]:
    """Return tool definitions as dicts (for fallback when DB is empty)."""
    return [
        {
            "id": t["id"],
            "slug": t["slug"],
            "name": t["name"],
            "description": t["description"],
            "tool_type": t["tool_type"],
            "schema_config": t["schema_config"],
            "implementation": t["implementation"],
            "is_system": True,
            "created_at": "2026-01-01T00:00:00Z",
        }
        for t in BUILTIN_TOOLS
    ]


def seed_builtin_tools():
    """Insert/update all built-in tool definitions. Idempotent."""
    for tool in BUILTIN_TOOLS:
        try:
            upsert_tool(tool)
        except Exception as e:
            print(f"  Warning seeding tool {tool['id']}: {e}")
    print(f"Seeded {len(BUILTIN_TOOLS)} built-in tools")
