from tools.tool_config import ApiParamDataType, ApiParamConfig
from pydantic import Field, create_model
from typing import Any


class ApiInputSchemaFactory:
    """
    Creates a dynamic Pydantic input schema from the Api's parameter configuration
    """

    _TYPE_MAP = {
        ApiParamDataType.STRING: str,
        ApiParamDataType.INTEGER: int,
        ApiParamDataType.BOOLEAN: bool,
        ApiParamDataType.DECIMAL: float,
    }

    @staticmethod
    def _build_model_name(
        tool_name: str,
    ) -> str:

        sanitized = "".join(char if char.isalnum() else "_" for char in tool_name)

        return f"{sanitized}Input"

    def create(self, tool_name: str, parameters: list[ApiParamConfig]):
        fields: dict[str, tuple[Any, Any]] = {}

        for param in parameters:
            lang_type = self._TYPE_MAP[param.data_type]
            field = Field(default=(... if param.required else param.default))
            fields[param.name] = (lang_type, field)
        model_name = self._build_model_name(tool_name)
        return create_model(model_name, **fields)
