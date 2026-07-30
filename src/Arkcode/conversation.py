"""进程内的单会话对话历史。"""

from .llm import Message


class Conversation:
    """按发生顺序保存用户与助手消息。"""

    def __init__(self) -> None:
        self._messages: list[Message] = []

    def add_user(self, text: str) -> None:
        """追加用户消息。"""

        self._messages.append(Message(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        """追加助手消息。"""

        self._messages.append(Message(role="assistant", content=text))

    def messages(self) -> list[Message]:
        """返回历史副本，避免调用方意外篡改内部状态。"""

        return list(self._messages)
