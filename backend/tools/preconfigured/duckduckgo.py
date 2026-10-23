from typing import Any

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_core.tools import BaseTool
from tools.tool_config import PreConfiguredToolConfig
from tools.tool_provider import ToolProvider


class DuckDuckGoToolProvider(ToolProvider):

    def create_tools(self, config: PreConfiguredToolConfig) -> list[BaseTool]:
        options: dict[str, Any] = (
            config.config if hasattr(config, "config") and config.config else {}
        )
        max_results = options.get("max_results", 4)
        region = options.get("region", "us-en")

        api_wrapper = DuckDuckGoSearchAPIWrapper(
            region=region,
            max_results=max_results,
        )

        tool = DuckDuckGoSearchResults(
            api_wrapper=api_wrapper, handle_tool_error=True, backend="google"
        )
        return [tool]