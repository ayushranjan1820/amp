"""Context enrichment with knowledge base and existing JIRA tickets."""
from typing import Dict, Any

from ..core.logging import log_error, log_info
from ..core.database import get_db
from ..services.knowledge_base_service import KnowledgeBaseService
from ..prompts import prompt_loader
from ..utils.prompt_utils import safe_fmt
from .ticket_tools import TicketToolsContext


async def enrich_with_context(
    user_prompt: str,
    jira_service,
    ai_service,
    context: TicketToolsContext
) -> Dict[str, Any]:
    """Enrich the agent's understanding with knowledge base and existing Jira tickets.

    Returns:
        Dictionary with knowledge_context and jira_context
    """
    enriched_context = {
        "knowledge_context": "",
        "jira_context": "",
        "has_context": False
    }

    try:
        db = get_db()
        kb_service = KnowledgeBaseService(db)

        project_id = context.project_id if context else "global"
        kb_results = kb_service.search_knowledge_base(
            project_id=project_id,
            query=user_prompt,
            limit=5
        )

        if kb_results:
            kb_contents = []
            for result in kb_results:
                content = result.get('content', '').strip()
                source = result.get('source', 'Unknown')
                if content and len(content) > 50:
                    kb_contents.append(f"[Source: {source}]\n{content[:800]}")

            if kb_contents:
                enriched_context["knowledge_context"] = "\n\n---\n\n".join(kb_contents)
                enriched_context["kb_results"] = kb_results
                enriched_context["has_context"] = True
                log_info(f"Found {len(kb_contents)} relevant KB documents", "context_enrichment")

        try:
            jira_tickets = await jira_service.get_jira_stories()

            if jira_tickets:
                tickets_summary = "\n".join([
                    f"- {ticket['key']}: {ticket['summary']} ({ticket['status']}, {ticket['issueType']})"
                    for ticket in jira_tickets[:20]
                ])

                relevance_prompt = safe_fmt(
                    prompt_loader.get_prompt("direct_processor.yml", "relevance_check"),
                    user_prompt=user_prompt,
                    tickets_summary=tickets_summary
                )

                relevant_keys = await ai_service.call_genai(
                    prompt=relevance_prompt,
                    temperature=0.1,
                    max_tokens=100,
                    task_name="jira_context_enrichment"
                )

                relevant_keys = relevant_keys.strip()

                if relevant_keys and relevant_keys != "NONE":
                    key_list = [k.strip() for k in relevant_keys.split(',')]
                    relevant_tickets = [
                        ticket for ticket in jira_tickets
                        if ticket['key'] in key_list
                    ]

                    if relevant_tickets:
                        jira_details = []
                        for ticket in relevant_tickets[:3]:
                            jira_details.append(
                                f"{ticket['key']}: {ticket['summary']} [{ticket['status']}]"
                            )

                        enriched_context["jira_context"] = "\n".join(jira_details)
                        enriched_context["has_context"] = True
                        log_info(f"Found {len(jira_details)} relevant JIRA tickets", "context_enrichment")

        except Exception as e:
            log_error(f"Error fetching Jira context: {e}", "context_enrichment")

    except Exception as e:
        log_error(f"Error enriching context: {e}", "context_enrichment")

    return enriched_context
