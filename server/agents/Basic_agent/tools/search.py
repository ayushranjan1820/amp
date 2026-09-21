"""Web search tool for the Langchain agent."""

from langchain_core.tools import tool
from ddgs import DDGS


def _log_search(agent_name: str, query: str):
    try:
        from cost_tracker import log_cost_event
        log_cost_event(event_type="web_search", agent_name=agent_name, metadata={"query": query})
    except Exception:
        pass


@tool
def web_search(query: str) -> str:
    """Search the web for information using DuckDuckGo.
    
    Args:
        query: The search query
        
    Returns:
        Search results as string
    """
    try:
        _log_search("Basic Agent", query)
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=5)
            
            if not results:
                return f"No search results found for: {query}"
            
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
