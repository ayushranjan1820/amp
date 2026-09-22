from tools.tool_provider import ToolProvider
from tools.tool_config import PreConfiguredToolConfig
from langchain_core.tools import BaseTool
from typing import Any
from langchain_community.tools import DuckDuckGoSearchResults

class DuckDuckGoToolProvider(ToolProvider):

    def create_tools(self, config: PreConfiguredToolConfig) -> list[BaseTool]:
        options: dict[str, Any] = config.config

        return [DuckDuckGoSearchResults()]
        