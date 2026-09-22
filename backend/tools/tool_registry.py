from collections.abc import Callable

from tools.tool_provider import ToolProvider
from tools.tool_config import ToolConfig
from tools.tool_type import ToolType

ProviderFactory = Callable[[ToolConfig], ToolProvider]


class ToolRegistry:
    def __init__(self):
        self._providers: dict[str, ProviderFactory] = {}

    def register(self, name: str, provider_factory: ProviderFactory):
        """Register a new provider factory."""
        if name in self._providers:
            raise ValueError(f"Provider '{name}' already registered.")
        self._providers[name] = provider_factory

    def get_provider(self, name: str) -> ProviderFactory:
        """Get a provider by name."""
        provider = self._providers.get(name)
        if provider is None:
            raise ValueError(f"Provider '{name}' not registered.")
        return provider

    def contains(self, name: str) -> bool:
        """Check if a provider is registered."""
        return name in self._providers

    def list_tools(self) -> list[str]:
        return list(self._providers.keys())
