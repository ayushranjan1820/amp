import re
from abc import abstractmethod
from typing import Any

from errors.global_exception_handler import AgentMartException
from langchain_core.tools import BaseTool, StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from pydantic import BaseModel
from tools.api.api_executor import ApiToolExecutor
from tools.api.api_schema import ApiInputSchemaFactory
from tools.mcp.mcp_tools_filter import MCPToolFilter
from tools.rag.vector_store import VectorStoreFactory
from tools.tool_config import ApiToolConfig, MCPToolConfig, RAGToolConfig, ToolConfig
from utils.logger import get_logger

logger = get_logger(__name__)


class ToolProvider(BaseModel):
    """Converts tool config into callable Langchain tools"""

    @abstractmethod
    async def create_tools(self, config: ToolConfig):
        raise NotImplementedError

    @staticmethod
    def _sanitize_tool_name(name: str) -> str:
        """
        Sanitizes tool names to comply with LLM function naming rules:
        - Alphanumeric and underscore characters only
        - Cannot start with a digit
        - Collapses duplicate underscores and limits length to 64 chars
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
        sanitized = re.sub(r"_+", "_", sanitized)
        if not sanitized:
            sanitized = "tool"
        if sanitized[0].isdigit():
            sanitized = f"tool_{sanitized}"
        sanitized = sanitized[:64]
        logger.debug("Sanitized Tool Name %s", sanitized)
        return sanitized


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


class MCPToolProvider(ToolProvider):
    """
    Convert MCP config into Langchain tools
    """

    def __init__(self, tool_filter: MCPToolFilter):
        self._tool_filter = tool_filter

    async def create_tools(self, config) -> list[BaseTool]:
        if not isinstance(config, MCPToolConfig):
            raise AgentMartException("MCPToolProvider needs MCPToolConfig")
        client = MultiServerMCPClient(config.mcp_config)

        tools = await client.get_tools()
        tools = self._tool_filter.filter(tools, config)
        logger.info(
            f"Fetched MCP tools: {[{tool.name: tool.description} for tool in tools]}"
        )
        return tools


class RAGToolProvider(ToolProvider):

    async def create_tools(self, config: RAGToolConfig) -> list[BaseTool]:
        if not isinstance(config, RAGToolConfig):
            raise AgentMartException("RAGToolProvider needs RagTOOLConfig")

        vector_db_config = config.vector_db_config
        vectore_store_type = config.vector_db_config.vector_db_provider
        embedding_config = config.embedding_model_config
        rag_advanced_config = config.rag_advanced_config

        vector_store = VectorStoreFactory.get_vector_store(
            vector_store_type=config.vector_db_config.vector_db_provider,
            vector_db_config=vector_db_config,
            embedding_config=embedding_config,
            advanced_config=rag_advanced_config,
        )

        async def search_knowledge_base(query: str):
            documents = await vector_store.get_retrieved_documents(query)
            if not documents:
                return "No relevant documents found"
            results: list[str] = []

            for index, document in enumerate(
                documents,
                start=1,
            ):
                source = document.metadata.get(
                    "source",
                    document.metadata.get(
                        "file_name",
                        "Unknown source",
                    ),
                )

                page = document.metadata.get("page")

                results.append(
                    f"Source {index}: {source}\n"
                    f"Page: {page if page is not None else 'N/A'}\n"
                    f"Content:\n{document.page_content}"
                )

            return "\n\n---\n\n".join(results)

        tool = StructuredTool.from_function(
            coroutine=search_knowledge_base,
            name=self._sanitize_tool_name(config.name),
            description=config.description,
        )
        return [tool]
