from tools.tool_factory import ToolFactory
from agents.agent_config import AgentConfig
from deepagents import create_deep_agent


class AgentFactory:

    def __init__(self, tool_factory: ToolFactory):
        self._tool_factory = tool_factory

    async def create(self, config: AgentConfig) -> Agent:
        runtime_tools = []

        for tool_config in config.tools:
            tools = await self._tool_factory.create_tools(tool_config)
            runtime_tools.extend(tools)

        llm = config.model.provider + ":" + config.model.name

        agent = create_deep_agent(
            model=llm,
            tools=runtime_tools,
            system_prompt=config.system_prompt,
            name=config.name,
        )
        return agent
