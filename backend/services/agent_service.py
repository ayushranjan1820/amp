from datetime import datetime
from models.api_req import NewAgentReq, TokenReq
from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection,
    TokenCatalogConnection,
)
from database.schema import AgentCatalog, TokenCatalog
from models.api_res import AgentRes, TokenRes
from utils.logger import get_logger
from tools.tool_config import ToolConfig
from pydantic import TypeAdapter

logger = get_logger(__name__)


async def register_new_agent(
    user_id: str, req: NewAgentReq, collection: AgentCatalogConnection
) -> AgentRes:
    agent_catalog = AgentCatalog(
        **req.model_dump(), created_by=user_id, updated_by=user_id
    )
    result = await collection.register_new_agent(agent_catalog)
    return AgentRes(**agent_catalog.model_dump(), agent_id=str(result.inserted_id))


async def edit_available_agent(
    id: str, agent_id: str, req: NewAgentReq, collection: AgentCatalogConnection
) -> AgentRes | None:
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
    return AgentRes(**updated_agent_catalog.model_dump(), agent_id=agent_id)


async def get_agents(
    user_id: str, collection: AgentCatalogConnection
) -> list[AgentRes]:
    logger.debug("User ID : %s", user_id)
    agents = await collection.get_all_agents(user_id)
    return [AgentRes(**agent, agent_id=str(agent["_id"])) for agent in agents]


