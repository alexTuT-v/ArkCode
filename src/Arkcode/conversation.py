"""进程内的单会话对话历史。"""

from .llm import ROLE_ASSISTANT, ROLE_TOOL, Message, ToolCall, ToolResult


class Conversation:
    """按发生顺序保存用户与助手消息。"""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add_user(self, text: str) -> None:
        """追加用户消息。"""

        self._messages.append(Message(role="user", content=text))

    def add_assistant(
        self,
        text: str,
        *,
        thinking: str = "",
        thinking_signature: str = "",
    ) -> None:
        """追加助手消息。"""

        self._messages.append(
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

        self._messages.append(
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

        self._messages.append(Message(role=ROLE_TOOL, tool_results=list(results)))

    def messages(self) -> list[Message]:
        """返回历史副本，避免调用方意外篡改内部状态。"""

        return list(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息角色；空历史返回空字符串。"""

        return self._messages[-1].role if self._messages else ""
