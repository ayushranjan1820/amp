from datetime import datetime
from models.api_req import NewAgentReq
from database.mongo_connection import AgentCatalogConnection
from database.schema import AgentCatalog
from models.api_res import NewAgentRes


async def register_new_agent(
    id: str, req: NewAgentReq, collection: AgentCatalogConnection
) -> NewAgentRes:
    agent_catalog = AgentCatalog(**req.model_dump(), created_by=id, updated_by=id)
    result = await collection.register_new_agent(agent_catalog)
    return NewAgentRes(**agent_catalog.model_dump(), agent_id=str(result.inserted_id))


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

    await collection.edit_agent_config(agent_id, updated_agent_catalog)
    return NewAgentRes(**updated_agent_catalog.model_dump(), agent_id=agent_id)
