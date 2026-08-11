"""进程内的单会话对话历史。"""

import copy
import threading
from collections.abc import Sequence

from ..llm import ROLE_ASSISTANT, ROLE_TOOL, Message, ToolCall, ToolResult
from ..sessions.journal import MessageSink
from ..sessions.record import CompactBoundary


class Conversation:
    """按发生顺序保存用户与助手消息，持久化采用显式 sink 提交。"""

    def __init__(self, *, sink: MessageSink | None = None) -> None:
        self._lock = threading.RLock()
        self._messages: list[Message] = []
        self._sink = sink

    @classmethod
    def from_messages(
        cls,
        messages: Sequence[Message],
        *,
        sink: MessageSink | None = None,
    ) -> "Conversation":
        """从既有历史恢复对话，初始化过程不触发任何持久化。"""

        conversation = cls(sink=sink)
        with conversation._lock:
            conversation._messages = copy.deepcopy(list(messages))
        return conversation

    def _append(self, message: Message) -> None:
        committed = copy.deepcopy(message)
        with self._lock:
            if self._sink is not None:
                self._sink.append_message(copy.deepcopy(committed))
            self._messages.append(committed)

    def add_user(self, text: str) -> None:
        """追加用户消息。"""

        self._append(Message(role="user", content=text))

    def add_assistant(
        self,
        text: str,
        *,
        thinking: str = "",
        thinking_signature: str = "",
    ) -> None:
        """追加助手消息。"""

        self._append(
            Message(
                role=ROLE_ASSISTANT,
                content=text,
                thinking=thinking,
                thinking_signature=thinking_signature,
            )
        )

    def add_assistant_with_tool_calls(
        self,
        text: str,
        calls: list[ToolCall],
        *,
        thinking: str = "",
        thinking_signature: str = "",
    ) -> None:
        """追加包含工具调用的助手回合。"""

        self._append(
            Message(
                role=ROLE_ASSISTANT,
                content=text,
                tool_calls=list(calls),
                thinking=thinking,
                thinking_signature=thinking_signature,
            )
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """追加一组工具执行结果。"""

        self._append(Message(role=ROLE_TOOL, tool_results=list(results)))

    def messages(self) -> list[Message]:
        """返回历史副本，避免调用方意外篡改内部状态。"""

        with self._lock:
            return copy.deepcopy(self._messages)

    def replace_messages(self, messages: list[Message] | None) -> None:
        """仅替换内存历史，不做任何持久化。"""

        replacement = copy.deepcopy(messages or [])
        with self._lock:
            self._messages = replacement

    def replace_history(self, messages: list[Message] | None) -> None:
        """兼容测试与已有调用方的纯内存替换别名。"""

        self.replace_messages(messages)

    def apply_compaction(
        self,
        boundary: CompactBoundary,
        messages: list[Message],
    ) -> None:
        """先持久化压缩边界，成功后才替换内存历史。"""

        replacement = copy.deepcopy(messages)
        with self._lock:
            if self._sink is not None:
                self._sink.append_boundary(copy.deepcopy(boundary))
            self._messages = replacement

    def length(self) -> int:
        """返回当前消息条数。"""

        with self._lock:
            return len(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息角色；空历史返回空字符串。"""

        with self._lock:
            return self._messages[-1].role if self._messages else ""
