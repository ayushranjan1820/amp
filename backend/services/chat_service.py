from pydantic import TypeAdapter
from database.mongo_connection import AgentCatalogConnection, ToolCatalogConnection
from errors.global_exception_handler import AgentMartException
from agents.agent_config import AgentConfig
from agents.agent_factory import AgentFactory
from tools.tool_config import ToolConfig


async def chat_with_agent(
    agent_id: str,
    user_id: str,
    user_message: str,
    agent_factory: AgentFactory,
    agent_catalog_collection: AgentCatalogConnection,
    tool_catalog_collection: ToolCatalogConnection,
):
    available_agent = await agent_catalog_collection.get_agent_config(agent_id)
    if available_agent is None:
        raise AgentMartException("Agent not found", 404)

    tool_ids = available_agent.get("tools", None)
    if tool_ids is None:
        raise AgentMartException("No tool config section found in Agent Catalog")
    
    available_tools = []
    for tool_id in tool_ids:
        raw_tool_config = await tool_catalog_collection.get_tool_config(tool_id)
        if raw_tool_config:
            if "_id" in raw_tool_config:
                raw_tool_config["tool_id"] = str(raw_tool_config["_id"])
            tool_obj = TypeAdapter(ToolConfig).validate_python(raw_tool_config)
            available_tools.append(tool_obj)

    agent_config = AgentConfig(
        _id=str(available_agent["_id"]),
        name=available_agent["name"],
        description=available_agent["description"],
        system_prompt=available_agent["system_prompt"],
        tools=available_tools,
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
    