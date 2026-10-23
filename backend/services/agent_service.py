from datetime import datetime

from database.mongo_connection import AgentCatalogConnection
from models.api_res import AgentRes
from utils.logger import get_logger

logger = get_logger(__name__)


async def register_new_agent(
    user_id: str, agent_config: dict, collection: AgentCatalogConnection
) -> AgentRes:
    agent_id = agent_config.get("_id", None)
    agent_config["updated_by"] = user_id
    agent_config["updated_at"] = datetime.utcnow()
    agent_config["created_by"] = user_id
    agent_config["created_at"] = datetime.utcnow()
    agent_config.pop("_id", None)

    result = await collection.update_agent_config(agent_id, agent_config)
    result["_id"] = str(result["_id"])
    return AgentRes(**result)


async def get_agents(
    user_id: str, collection: AgentCatalogConnection, status: str | None = None
) -> list[AgentRes]:
    logger.debug("User ID : %s", user_id)
    agents = await collection.get_all_agents(user_id, status)
    for agent in agents:
        agent["_id"] = str(agent["_id"])
    return [AgentRes(**agent) for agent in agents]
