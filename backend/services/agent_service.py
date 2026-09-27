from datetime import datetime
from models.api_req import NewAgentReq, TokenReq
from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection,
    TokenCatalogConnection,
)
from database.schema import AgentCatalog, TokenCatalog
from models.api_res import NewAgentRes, NewTokenRes
from utils.logger import get_logger

logger = get_logger(__name__)


async def register_new_agent(
    user_id: str, req: NewAgentReq, collection: AgentCatalogConnection
) -> NewAgentRes:
    agent_catalog = AgentCatalog(
        **req.model_dump(), created_by=user_id, updated_by=user_id
    )
    result = await collection.register_new_agent(agent_catalog)
    return NewAgentRes(**agent_catalog.model_dump(), agent_id=str(result.inserted_id))


async def add_new_tools_to_agent(
    agent_id: str,
    tool_config: list[dict],
    user_id: str,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
) -> NewAgentRes:
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

    return NewAgentRes(**updated_agent_config, agent_id=agent_id)


async def edit_available_agent(
    id: str, agent_id: str, req: NewAgentReq, collection: AgentCatalogConnection
) -> NewAgentRes | None:
    available_agent_dict = await collection.get_agent_config(agent_id)
    if available_agent_dict is None:
        return None
    created_by = available_agent_dict.get("created_by", id)
    created_at = available_agent_dict.get("created_at", datetime.now())

    updated_agent_catalog = AgentCatalog(
        **req.model_dump(),
        created_by=created_by,
        created_at=created_at,
        updated_by=id,
        updated_at=datetime.now(),
    )

    await collection.update_agent_config(agent_id, updated_agent_catalog)
    return NewAgentRes(**updated_agent_catalog.model_dump(), agent_id=agent_id)


async def get_agents(
    user_id: str, collection: AgentCatalogConnection
) -> list[NewAgentRes]:
    logger.debug("User ID : %s", user_id)
    agents = await collection.get_all_agents(user_id)
    return [NewAgentRes(**agent, agent_id=str(agent["_id"])) for agent in agents]


async def add_new_tokens(
    token_req: TokenReq,
    user_id: str,
    token_catalog_collection: TokenCatalogConnection,
):
    new_token = TokenCatalog(**token_req.model_dump(), owner_id=user_id)
    result = await token_catalog_collection.add_token(new_token)
    return NewTokenRes(
        **new_token.model_dump(), token_id=str(result.inserted_id)
    )

async def get_tokens_by_user_id(user_id: str, token_catalog_collection: TokenCatalogConnection

):
    tokens = await token_catalog_collection.get_tokens_by_user_id(user_id)
    return [NewTokenRes(**token, token_id=str(token["_id"])) for token in tokens]
