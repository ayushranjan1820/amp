from tools.preconfigured.duckduckgo import DuckDuckGoToolProvider
from tools.preconfigured.tavily import TavilyToolProvider
from tools.tool_registry import ToolRegistry


def create_preconfigured_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("tavily_search", TavilyToolProvider)
    registry.register("duckduckgo_search", DuckDuckGoToolProvider)
    return registry
