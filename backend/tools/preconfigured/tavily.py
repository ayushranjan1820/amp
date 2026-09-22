
from tools.tool_provider import ToolProvider
from tools.tool_config import PreConfiguredToolConfig
from langchain_core.tools import BaseTool
from typing import Any
from langchain_tavily import TavilySearch

class TavilyToolProvider(ToolProvider):

    async def create_tools(self, config: PreConfiguredToolConfig) -> list[BaseTool]:
        options: dict[str, Any] = config.config

        api_key = options.get("api_key")
        max_results = options.get("max_results", 3)

        if not api_key:
            raise ValueError("Tavily API key not found")

        return [TavilySearch(tavily_api_key=api_key, max_results=max_results)]