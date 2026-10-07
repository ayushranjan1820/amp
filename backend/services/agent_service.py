from datetime import datetime
from database.mongo_connection import (
    AgentCatalogConnection,
    ToolCatalogConnection
    )
from database.schema import AgentCatalog
from models.api_res import AgentRes
from utils.logger import get_logger
from tools.tool_config import ToolConfig
from pydantic import TypeAdapter

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
    user_id: str, collection: AgentCatalogConnection    , status: str | None = None
) -> list[AgentRes]:
    logger.debug("User ID : %s", user_id)
    agents = await collection.get_all_agents(user_id, status)
    for agent in agents:
        agent["_id"] = str(agent["_id"])
    return [AgentRes(**agent) for agent in agents]


async def add_model_config(
    agent_id: str,
    user_id: str,
    req: ModelReq,
    model_collection: ModelCatalogConnection,
    agent_collection: AgentCatalogConnection,
):
    """
    Adds model config to agent config
    Args:
        agent_id (str): unique id of the agent config
        user_id: unique id of the user
        req (ModelReq): model config request
        collection (ModelCatalogConnection): Mongo connection for model_catalog collection
    Returns:
        ModelRes: Model response
    """
    model_catalog = ModelCatalog(
        **req.model_dump(), created_by=user_id, updated_by=user_id
    )
    result = await model_collection.add_model(model_catalog)
    model_id = result.inserted_id
    # Update agent config with model id
    await agent_collection.update_agent_config(agent_id, {"model": model_id})
    return ModelRes(**model_catalog.model_dump(), model_id=str(result.inserted_id))
