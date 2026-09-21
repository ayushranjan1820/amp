"""Tool wrapper functions for Knowledge Base operations."""
import json
from typing import Dict, Any

from ..core.logging import log_info, log_error
from ..core.database import get_db
from ..services.knowledge_base_service import KnowledgeBaseService
from ..services.ai_service import AIService
from ..prompts import prompt_loader
from ..utils.prompt_utils import safe_fmt


async def search_knowledge_base_tool(query: str, project_id: str = "default", limit: int = 5) -> str:
    """Search the knowledge base for relevant information.
    
    Args:
        query: Search query string
        project_id: Project ID to scope the search (default: "default")
        limit: Maximum number of results to return (default: 5)
        
    Returns:
        Formatted search results from the knowledge base
    """
    try:
        log_info(f"🔍 Searching knowledge base: {query}", "kb_tool")
        
        # Initialize services
        db = get_db()
        kb_service = KnowledgeBaseService(db)
        ai_service = AIService()
        
        results = await kb_service.search_knowledge_base_async(
            project_id=project_id,
            query=query,
            limit=limit
        )
        
        if not results:
            return f"No relevant information found in knowledge base for: {query}\n\nYou may need to create content based on general knowledge or ask the user for more details."
        
        # Collect all content from results
        all_content = []
        sources = []
        for result in results:
            content = result.get('content', '').strip()
            filename = result.get('filename', 'Unknown')
            score = result.get('score', 0)
            
            all_content.append(content)
            sources.append(f"{filename} (relevance: {score:.0%})")
        
        # Combine all content
        combined_content = "\n\n".join(all_content)
        sources_list = "\n- ".join(sources)
        
        # Use LLM to synthesize and format the information
        synthesis_prompt = safe_fmt(
            prompt_loader.get_prompt("tools.yml", "knowledge_base_synthesis"),
            query=query,
            combined_content=combined_content,
            sources_list=sources_list
        )

        log_info(f"🤖 Using LLM to synthesize {len(results)} knowledge base results", "kb_tool")
        
        # Get LLM-formatted response
        formatted_response = await ai_service.call_genai(
            prompt=synthesis_prompt,
            temperature=0.3,
            max_tokens=2048,
            task_name="jira_knowledge_base"
        )
        
        log_info(f"✅ Successfully formatted knowledge base results using LLM", "kb_tool")
        
        return formatted_response
        
    except Exception as error:
        log_error(f"Error searching knowledge base: {error}", "kb_tool")
        return f"Error searching knowledge base: {str(error)}"


async def get_knowledge_stats_tool(project_id: str = "default") -> str:
    """Get statistics about the knowledge base.
    
    Args:
        project_id: Project ID to scope the stats (default: "default")
        
    Returns:
        Formatted statistics about the knowledge base
    """
    try:
        log_info(f"📊 Getting knowledge base stats for project: {project_id}", "kb_tool")
        
        # Initialize KB service
        db = get_db()
        kb_service = KnowledgeBaseService(db)
        
        # Get stats
        stats = kb_service.get_knowledge_stats(project_id)
        
        output = (
            f"Knowledge Base Statistics:\n"
            f"- Total Documents: {stats.get('documentCount', 0)}\n"
            f"- Total Chunks: {stats.get('chunkCount', 0)}\n"
        )
        
        log_info(f"✅ Retrieved knowledge base stats", "kb_tool")
        return output
        
    except Exception as error:
        log_error(f"Error getting knowledge base stats: {error}", "kb_tool")
        return f"Error getting knowledge base stats: {str(error)}"


async def query_mongodb_tool(collection: str, query_json: str, limit: int = 10) -> str:
    """Query MongoDB directly with custom filters.
    
    Args:
        collection: Collection name to query
        query_json: JSON string representing MongoDB query filter
        limit: Maximum number of results to return (default: 10)
        
    Returns:
        Formatted query results from MongoDB
    """
    try:
        log_info(f"🗄️ Querying MongoDB collection: {collection}", "kb_tool")
        
        # Parse query JSON
        try:
            query_filter = json.loads(query_json)
        except json.JSONDecodeError as e:
            return f"Invalid JSON query: {str(e)}"
        
        # Get database connection
        db = get_db()
        
        # Execute query
        results = list(db[collection].find(query_filter).limit(limit))
        
        if not results:
            return f"No results found in collection '{collection}' with query: {query_json}"
        
        # Format results
        formatted_results = []
        for idx, doc in enumerate(results, 1):
            # Remove MongoDB _id for cleaner output
            doc_copy = {k: v for k, v in doc.items() if k != '_id'}
            formatted_results.append(
                f"Document {idx}:\n{json.dumps(doc_copy, indent=2, default=str)}"
            )
        
        output = "\n---\n".join(formatted_results)
        log_info(f"✅ Found {len(results)} documents in {collection}", "kb_tool")
        
        return f"Found {len(results)} documents in '{collection}':\n\n{output}"
        
    except Exception as error:
        log_error(f"Error querying MongoDB: {error}", "kb_tool")
        return f"Error querying MongoDB: {str(error)}"
