from datetime import datetime

from database.mongo_connection import (
    AgentCatalogConnection,
    TokenCatalogConnection,
    ToolCatalogConnection,
)
from database.schema import AgentCatalog, TokenCatalog
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from models.api_req import NewAgentReq, TokenReq
from models.api_res import AgentRes, MCPToolRes, TokenRes
from pydantic import TypeAdapter
from tools.tool_config import ToolConfig
from utils.logger import get_logger

logger = get_logger(__name__)


async def add_new_tools_to_agent(
    agent_id: str,
    tool_config: list[dict],
    user_id: str,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
) -> AgentRes:
    """
    Add new tool(s) to an existing agent
    Args:
        agent_id (str): unique id of the agent config
        tool_config (list[dict]): new tool config(s) to add in agent config
        user_id: unique id of the user
        agent_catalog_collection (AgentCatalogConnection): Mongo connection for agent_catalog collection
        tool_catalog_collection (ToolCatalogConnection): Mongo connection for tool_catalog collection
    Returns:
        AgentRes: Agent response
    """
    agent_config = await agent_catalog_collection.get_agent_config(agent_id)
    agent_catalog = AgentCatalog(**agent_config)
    agent_catalog.updated_at = datetime.now()
    agent_catalog.updated_by = user_id

    # Add tool config
    new_tools = await tool_catalog_collection.add_new_tool(tool_config)
    new_tool_ids = [str(tool_id) for tool_id in new_tools.inserted_ids]

    # Add new tool ids into agent catalog
    agent_catalog.tools.extend(new_tool_ids)
    updated_agent_config = await agent_catalog_collection.update_agent_config(
        agent_id, agent_catalog
    )

    return AgentRes(**updated_agent_config, agent_id=agent_id)


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


async def add_new_token(
    token_req: TokenReq,
    user_id: str,
    token_catalog_collection: TokenCatalogConnection,
):
    """
    Add new token for user authentication.
    Args:
        token_req (TokenReq): Token request
        user_id (str): User id
        token_catalog_collection (TokenCatalogConnection): Mongo connection for token_catalog collection
    Returns:
        TokenRes: Token response
    """
    new_token = TokenCatalog(**token_req.model_dump(), owner_id=user_id)
    result = await token_catalog_collection.add_token(new_token)
    return TokenRes(**new_token.model_dump(), token_id=str(result.inserted_id))


async def get_tokens_by_user_id(
    user_id: str, token_catalog_collection: TokenCatalogConnection
):
    """
    Get all tokens for a user.
    Args:
        user_id (str): User id
        token_catalog_collection (TokenCatalogCollection): Mongo connection for token_catalog collection
    Returns:
        list[TokenRes]: List of TokenRes
    """
    tokens = await token_catalog_collection.get_tokens_by_user_id(user_id)
    return [TokenRes(**token, token_id=str(token["_id"])) for token in tokens]


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
