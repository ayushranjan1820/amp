"""Web search tool for the BRD Generation Agent."""

from langchain_core.tools import tool
from ddgs import DDGS


@tool
def web_search(query: str) -> str:
    """Search the web for information using DuckDuckGo.
    
    Args:
        query: The search query
        
    Returns:
        Search results as string
    """
    try:
        try:
            from cost_tracker import log_cost_event
            log_cost_event(event_type="web_search", agent_name="BRD Generation Agent", metadata={"query": query})
        except Exception:
            pass
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
            
            if not results:
                return f"No search results found for: {query}"
            
            # Format results
            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted_results.append(
                    f"{i}. {result['title']}\n"
                    f"   URL: {result['href']}\n"
                    f"   {result['body']}"
                )
            
            return "\n\n".join(formatted_results)
    except Exception as e:
        return f"Error during search: {str(e)}"
