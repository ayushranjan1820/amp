from enum import StrEnum


class ToolType(StrEnum):
    """ Top-level tool categories"""
    
    PRECONFIGURED = "preconfigured"
    API = "api"
    CODE = "code"
    MCP = "mcp"


# class PreconfiguredTool(StrEnum):
#     """ Preconfigured tools """
#     TAVILY_SEARCH = "tavily_search"