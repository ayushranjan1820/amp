from datetime import datetime

from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection,
)
from database.schema import AgentCatalog
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from models.api_req import TokenReq
from models.api_res import AgentRes, MCPToolRes, TokenRes
from pydantic import TypeAdapter
from tools.tool_config import ToolConfig
from utils.logger import get_logger
from errors.global_exception_handler import AgentMartException

logger = get_logger(__name__)


async def add_new_tools_to_agent(
    agent_id: str,
    user_id: str,
    tool_config: list[dict],
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
) -> AgentRes:
    """
    Add new tool(s) to an existing agent
    Args:
        agent_id (str): unique id of the agent config
        tool_id (str): unique id of the tool config
        user_id: unique id of the user
        tool_config (list[dict]): new tool config(s) to add in agent config
        agent_catalog_collection (AgentCatalogConnection): Mongo connection for agent_catalog collection
        tool_catalog_collection (ToolCatalogConnection): Mongo connection for tool_catalog collection
    Returns:
        AgentRes: Agent response
    """
    agent_config = await agent_catalog_collection.get_agent_config(agent_id)
    if not agent_config:
        raise AgentMartException("Agent not found", 404)

    # Add tool config
    new_tools = await tool_catalog_collection.add_new_tool(tool_config)
    new_tool_ids = [str(tool_id) for tool_id in new_tools.inserted_ids]

    # Add new tool ids into agent catalog
    agent_config["updated_at"] = datetime.now()
    agent_config["updated_by"] = user_id
    agent_config["tools"] = agent_config.get("tools", []) + new_tool_ids
    updated_agent_config = await agent_catalog_collection.update_agent_config(
        agent_id, agent_config
    )
    updated_agent_config["_id"] = str(updated_agent_config["_id"])
    return AgentRes(**updated_agent_config)


async def fetch_tools_by_tool_ids(
    tool_ids: list[str],
    tool_catalog_collection: ToolCatalogConnection,
) -> list[ToolConfig]:
    """
    Fetch the tool configs based on the tool id(s)
    Args:
        tool_ids (list[str]): list of tool ids to fetch
        tool_catalog_collection (ToolCatalogConnection): Mongo connection for tool_catalog collection
    Returns:
        list[ToolConfig]: list of ToolConfig
    """
    result = await tool_catalog_collection.get_all_tool_configs(tool_ids)
    for tool in result:
        if "_id" in tool:
            tool["tool_id"] = str(tool["_id"])
    return [TypeAdapter(ToolConfig).validate_python(tool) for tool in result]


async def get_all_tools_from_mcp_config(mcp_config: dict) -> list[MCPToolRes]:
    """
    Fetch all tools from MCP config
    Args:
        mcp_config (dict): MCP config
    Returns:
        list[dict[str, str]]: List of tool names and descriptions
    """
    client = MultiServerMCPClient(mcp_config)
    tools = await client.get_tools()
    return [
        MCPToolRes(tool_name=tool.name, tool_description=tool.description)
        for tool in tools
    ]
