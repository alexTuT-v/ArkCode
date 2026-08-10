"""与供应商无关的消息、流事件和 Provider 协议。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from ..tools.base import ToolDefinition as ToolDefinition

ROLE_USER: Literal["user"] = "user"
ROLE_ASSISTANT: Literal["assistant"] = "assistant"
ROLE_TOOL: Literal["tool"] = "tool"


@dataclass(frozen=True)
class ToolCall:
    """协议无关的模型工具调用。"""

    id: str
    name: str
    input: str


@dataclass(frozen=True)
class ToolResult:
    """协议无关的工具执行结果。"""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class Message:
    """单条对话消息。"""

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    thinking: str = ""
    thinking_signature: str = ""


@dataclass(frozen=True)
class System:
    """稳定系统提示与每轮变化的环境段。"""

    stable: str = ""
    environment: str = ""


@dataclass(frozen=True)
class Request:
    """一次模型请求所需的协议无关输入。"""

    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] | None = field(default_factory=list)
    system: System = field(default_factory=System)
    reminder: str = ""


@dataclass(frozen=True)
class TextDelta:
    """模型正文的一段增量。"""

    text: str


@dataclass(frozen=True)
class ThinkingDelta:
    """模型思考内容的一段增量。"""

    text: str


@dataclass(frozen=True)
class ThinkingComplete:
    """完整思考块及供应商要求续传的签名。"""

    thinking: str
    signature: str = ""


@dataclass(frozen=True)
class ToolCallStart:
    """一个工具调用开始产生。"""

    tool_name: str
    tool_id: str


@dataclass(frozen=True)
class ToolCallDelta:
    """一个工具调用参数 JSON 的增量。"""

    tool_id: str
    text: str


@dataclass(frozen=True)
class ToolCallComplete:
    """一个已完成且已解析的工具调用。"""

    tool_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class StreamEnd:
    """一次正常请求的唯一结束事件及完整用量。"""

    stop_reason: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_creation: int = 0
    cache_write: int = 0


@dataclass(frozen=True)
class StreamError:
    """一次异常请求的终止事件。"""

    error: Exception


StreamEvent = (
    TextDelta
    | ThinkingDelta
    | ThinkingComplete
    | ToolCallStart
    | ToolCallDelta
    | ToolCallComplete
    | StreamEnd
    | StreamError
)


class Provider(Protocol):
    """TUI 使用的协议无关模型接口。"""

    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]: ...
