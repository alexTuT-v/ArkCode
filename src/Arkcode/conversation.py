"""进程内的单会话对话历史。"""

import copy
import threading
from collections.abc import Callable

from .llm import ROLE_ASSISTANT, ROLE_TOOL, Message, ToolCall, ToolResult


class Conversation:
    """按发生顺序保存用户与助手消息。"""

    def __init__(
        self,
        *,
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._messages: list[Message] = []
        self._on_append = on_append
        self._on_replace = on_replace

    @classmethod
    def from_messages(
        cls,
        messages: list[Message],
        *,
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> "Conversation":
        """从既有历史恢复对话，初始化过程不触发持久化回调。"""

        conversation = cls(on_append=on_append, on_replace=on_replace)
        with conversation._lock:
            conversation._messages = copy.deepcopy(messages)
        return conversation

    def _append(self, message: Message) -> None:
        with self._lock:
            self._messages.append(copy.deepcopy(message))
        if self._on_append is not None:
            self._on_append(copy.deepcopy(message))

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
        """用输入消息的深拷贝整体替换当前历史。"""

        replacement = copy.deepcopy(messages or [])
        with self._lock:
            self._messages = replacement
        if self._on_replace is not None:
            self._on_replace(copy.deepcopy(replacement))

    def replace_history(self, messages: list[Message] | None) -> None:
        """兼容已有调用方的历史替换别名。"""

        self.replace_messages(messages)

    def length(self) -> int:
        """返回当前消息条数。"""

        with self._lock:
            return len(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息角色；空历史返回空字符串。"""

        with self._lock:
            return self._messages[-1].role if self._messages else ""
