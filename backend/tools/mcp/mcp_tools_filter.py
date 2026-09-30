from langchain_core.tools import BaseTool
class MCPToolFilter:

    def filter(self, tools: list[BaseTool], mcp_config: dict) -> list[BaseTool]:
        """
        Filters the list of MCP tools based on the allowed_tools in the MCPToolConfig
        Args:
            tools (list[BaseTool]): List of MCP tools to filter
            mcp_config (MCPToolConfig): MCPToolConfig object
        Returns:
            list[BaseTool]: List of filtered MCP tools
        """
        allowed_tools = mcp_config.allowed_tools

        result = []
        for tool in tools:
            if tool.name in allowed_tools:
                result.append(tool)
        return result
                