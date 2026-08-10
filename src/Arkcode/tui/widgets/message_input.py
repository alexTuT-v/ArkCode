"""Enter 提交、Alt+Enter 换行的多行输入框。"""

from textual.binding import Binding
from textual.message import Message as TextualMessage
from textual.widgets import TextArea


class MessageInput(TextArea):
    """Enter 提交、Alt+Enter 换行的多行输入框。"""

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", priority=True),
        Binding("alt+enter", "insert_newline", "New line", priority=True),
    ]

    class Submitted(TextualMessage):
        """输入框提交事件。"""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def action_submit_message(self) -> None:
        self.post_message(self.Submitted(self.text))

    def action_insert_newline(self) -> None:
        self.insert("\n")
