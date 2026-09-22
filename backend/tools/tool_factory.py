import inspect
from typing import Any
from langchain_core.tools import BaseTool
from tools.tool_registry import ToolRegistry
from tools.tool_config import ToolConfig, PreConfiguredToolConfig, BaseToolConfig
from tools.tool_type import ToolType

class ToolFactory:

    def __init__(self, preconfigured_registry: ToolRegistry):
        self._preconfigured_registry = preconfigured_registry

    async def _create_preconfigured_tools(self, config: Any) -> list[BaseTool]:
        if not isinstance(config, PreConfiguredToolConfig):
            if hasattr(config, "model_dump"):
                config = PreConfiguredToolConfig(**config.model_dump())
            elif isinstance(config, dict):
                config = PreConfiguredToolConfig(**config)
            else:
                raise ValueError("Expected Pre-configured Tool Configs")

        provider_factory = self._preconfigured_registry.get_provider(config.provider)

        provider = provider_factory()
        res = provider.create_tools(config)
        if inspect.isawaitable(res):
            return await res
        return res
            

    async def create_tools(self, config: Any) -> list[BaseTool]:
        tool_enabled = getattr(config, "enabled", True)
        if isinstance(config, dict):
            tool_enabled = config.get("enabled", True)

        if not tool_enabled:
            return []
        
        tool_type = getattr(config, "tool_type", None)
        if isinstance(config, dict):
            tool_type = config.get("tool_type")

        if tool_type == ToolType.PRECONFIGURED:
            return await self._create_preconfigured_tools(config)
        
        raise ValueError(f"Unsupported tool type: {tool_type}")
