"""WebMCP-native agent: LLM loop over tools exposed in the user's Chrome tab."""

from typing import TYPE_CHECKING, Any

__all__ = ["WebMcpAgent", "webmcp_agent"]

if TYPE_CHECKING:
    from .agent import WebMcpAgent as WebMcpAgent
    from .agent import webmcp_agent as webmcp_agent


def __getattr__(name: str) -> Any:
    if name == "WebMcpAgent":
        from .agent import WebMcpAgent as _WebMcpAgent

        return _WebMcpAgent
    if name == "webmcp_agent":
        from .agent import webmcp_agent as _webmcp_agent

        return _webmcp_agent
    raise AttributeError(name)
