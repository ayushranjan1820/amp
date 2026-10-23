from enum import StrEnum


class ToolType(StrEnum):
    """Top-level tool categories"""

    PRECONFIGURED = "PRECONFIGURED"
    API = "API"
    CODE = "CODE"
    MCP = "MCP"
    RAG = "RAG"


# class PreconfiguredTool(StrEnum):
#     """ Preconfigured tools """
#     TAVILY_SEARCH = "tavily_search"
