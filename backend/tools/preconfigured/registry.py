from tools.tool_registry import ToolRegistry
from tools.preconfigured.tavily import TavilyToolProvider
from tools.preconfigured.duckduckgo import DuckDuckGoToolProvider


def create_preconfigured_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register("tavily_search", TavilyToolProvider)
    registry.register("duckduckgo_search", DuckDuckGoToolProvider)
    return registry

    