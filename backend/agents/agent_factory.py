from tools.tool_factory import ToolFactory
from agents.agent_config import AgentConfig
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model


class AgentFactory:

    def __init__(self, tool_factory: ToolFactory):
        self._tool_factory = tool_factory

    async def create(self, config: AgentConfig) -> Agent:
        runtime_tools = []

        for tool_config in config.tools:
            tools = await self._tool_factory.create_tools(tool_config)
            runtime_tools.extend(tools)

        llm = init_chat_model(
            model=config.model.name,
            model_provider=config.model.provider,
            api_key=config.model.api_key,
        )

        agent = create_deep_agent(
            model=llm,
            tools=runtime_tools,
            system_prompt=config.system_prompt,
            name=config.name,
        )
        return agent
