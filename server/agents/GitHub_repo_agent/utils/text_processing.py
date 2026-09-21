"""Text processing utilities for query analysis"""

from .git_utils import extract_repo_url


def extract_user_query(full_query: str) -> str:
    """
    Extract the actual user query from a formatted message that may contain context.
    
    Args:
        full_query: The full query string that may include context markers
        
    Returns:
        The extracted user query
    """
    if "[Current request]" in full_query:
        parts = full_query.split("[Current request]")
        raw = parts[-1].strip()
        if raw.startswith("IMPORTANT:"):
            lines = raw.split("\n")
            for line in lines:
                line = line.strip()
                if line and not line.startswith("IMPORTANT:"):
                    return line
        return raw.split("\n")[0].strip() if raw else full_query
    if "Current user message:" in full_query:
        parts = full_query.split("Current user message:")
        return parts[-1].strip().split("\n")[0].strip()
    return full_query


def detect_intent(query: str) -> str:
    """
    Detect the user's intent from their query.
    
    Args:
        query: User's query string
        
    Returns:
        Intent category: 'clone', 'push', 'tech_stack', 'architecture', 
        'features', 'documentation', 'modify', or 'general'
    """
    q = query.lower()
    
    if any(k in q for k in ['clone', 'load', 'fetch', 'import', 'github.com']):
        if extract_repo_url(query):
            return 'clone'
    
    if any(k in q for k in ['push', 'commit', 'deploy to github', 'push code', 'push change']):
        return 'push'
    
    if any(k in q for k in ['tech stack', 'technology', 'technologies', 'framework', 'language used', 'dependencies']):
        return 'tech_stack'
    
    if any(k in q for k in ['architecture', 'diagram', 'flow', 'system design', 'component', 'structure']):
        return 'architecture'
    
    if any(k in q for k in ['feature', 'functionality', 'what does', 'capabilities', 'what can']):
        return 'features'
    
    if any(k in q for k in ['document', 'documentation', 'technical doc', 'reverse engineer', 'readme']):
        return 'documentation'
    
    if any(k in q for k in ['change', 'modify', 'update', 'edit', 'fix', 'refactor', 'add', 'remove', 'delete']):
        return 'modify'
    
    return 'general'
