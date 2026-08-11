"""模型无关的工具契约。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class Result:
    """工具执行产生的文本结果。"""

    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    """提供给语言模型的工具描述。"""

    name: str
    description: str
    input_schema: dict[str, Any]


class Tool[ParamsT: BaseModel](ABC):
    """所有模型可调用工具的统一抽象基类。"""

    params_model: type[ParamsT]
    should_defer: bool = False

    @property
    @abstractmethod
    def read_only(self) -> bool:
        """工具是否没有外部副作用。"""

    @abstractmethod
    def name(self) -> str:
        """返回稳定、唯一的工具名。"""

    @abstractmethod
    def description(self) -> str:
        """返回供模型理解用途的说明。"""

    def get_schema(self) -> dict[str, Any]:
        """从参数模型生成工具 schema（模型驱动的单一真相源）。"""

        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name(),
            "description": self.description(),
            "input_schema": schema,
        }

    @abstractmethod
    async def execute(self, params: ParamsT) -> Result:
        """执行已解析的参数模型并返回结果。"""
