from abc import ABC, abstractmethod
from typing import Any, Sequence

from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel
from tools.api.api_executor import ApiToolExecutor
from tools.api.api_schema import ApiInputSchemaFactory
from tools.tool_config import ApiToolConfig, ToolConfig, MCPToolConfig
from utils.logger import get_logger
from errors.global_exception_handler import AgentMartException
from tools.mcp.mcp_tools_filter import MCPToolFilter

logger = get_logger(__name__)


class ToolProvider(BaseModel):
    """Converts tool config into callable Langchain tools"""

    @abstractmethod
    async def create_tools(self, config: ToolConfig):
        raise NotImplementedError


class PreConfiguredToolProvider(ToolProvider):

    def create(self, config: PreConfiguredToolConfig) -> BaseTool:
        pass


class ApiToolProvider(ToolProvider):
    """
    Converts ApiToolConfig into a Langchain StructuredTool
    """

    def __init__(
        self, executor: ApiToolExecutor, schema_factory: ApiInputSchemaFactory
    ):
        self._executor = executor
        self._schema_factory = schema_factory

    async def create_tools(self, config) -> list[BaseTool]:
        if not isinstance(config, ApiToolConfig):
            raise TypeError("ApiToolProvider needs ApiToolConfig")

        input_schema = self._schema_factory.create(
            tool_name=config.name, parameters=config.parameters
        )

        async def execute_api(**arguments: Any):

            return await self._executor.execute(config, arguments)

        tool = StructuredTool.from_function(
            coroutine=execute_api,
            name=self._sanitize_tool_name(config.name),
            description=config.description,
            args_schema=input_schema,
        )

        return [tool]

    @staticmethod
    def _sanitize_tool_name(
        name: str,
    ) -> str:

        sanitized = "".join(char if char.isalnum() else "_" for char in name)

        final_tool_name = sanitized.strip("_").lower()
        logger.debug("Sanitized Tool Name {}".format(final_tool_name))
        return final_tool_name


class MCPToolProvider(ToolProvider):
    """ 
    Convert MCP config into Langchain tools
    """
    def __init__(self, tool_filter: MCPToolFilter):
        self._tool_filter = tool_filter

    async def create_tools(self, config) -> list[BaseTool]:
        if not isinstance(config, MCPToolConfig):
            raise AgentMartException("MCPToolProvider needs MCPToolConfig")
        client = MultiServerMCPClient(
            config.mcp_config
        )

        tools = await client.get_tools()
        tools = self._tool_filter.filter(tools, config)
        logger.info(f"Fetched MCP tools: {[{tool.name: tool.description} for tool in tools]}")
        return tools
