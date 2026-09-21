"""LangChain agents for SDLC tool."""

def __getattr__(name):
    if name == "JiraAgent":
        from .jira_agent import JiraAgent
        return JiraAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["JiraAgent"]
