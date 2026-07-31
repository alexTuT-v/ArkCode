"""模型无关的工具契约。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


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


class Tool(ABC):
    """所有模型可调用工具的统一抽象基类。"""

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

    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """返回 JSON Schema 参数定义。"""

    @abstractmethod
    async def execute(self, args: str) -> Result:
        """执行序列化 JSON 参数并返回结果。"""
