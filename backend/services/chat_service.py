from database.mongo_connection import AgentCatalogConnection
from errors.global_exception_handler import AgentMartException
from agents.agent_config import AgentConfig
from agents.agent_factory import AgentFactory

async def chat_with_agent(agent_id: str, user_id: str, user_message: str, agent_factory: AgentFactory, collection: AgentCatalogConnection):
    available_agent = await collection.get_agent_config(agent_id)
    if available_agent is None:
        raise AgentMartException("Agent not found", 404)
        
    agent_config = AgentConfig(
        _id=str(available_agent["_id"]),
        name=available_agent["name"],
        description=available_agent["description"],
        system_prompt=available_agent["system_prompt"],
        tools=available_agent["tools"],
        model=available_agent["model"],
        capabilities=available_agent["capabilities"],
        enabled=available_agent["enabled"],
        version=available_agent["version"],
        visibility=available_agent["visibility"],
        status=available_agent["status"],
    )
    
    agent = await agent_factory.create(agent_config)

    agent_response = await agent.ainvoke(
        {"messages": [{"role": "user", "content": user_message}]}
    )
    return agent_response["messages"][-1].content[-1]["text"]
    