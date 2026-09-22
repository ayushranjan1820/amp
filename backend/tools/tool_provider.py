from pydantic import BaseModel
from abc import ABC, abstractmethod
from langchain_core.tools import BaseTool
from typing import Sequence

from tools.tool_config import ToolConfig

class ToolProvider(BaseModel):
    """ Converts tool config into callable Langchain tools"""

    @abstractmethod
    async def create_tools(self, config: ToolConfig):
        raise NotImplementedError



class PreConfiguredToolProvider(ToolProvider):

    def create(self, config: PreConfiguredToolConfig) -> BaseTool:
        pass