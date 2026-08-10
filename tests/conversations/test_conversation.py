"""Conversation 显式提交与持久化优先测试。"""

import pytest

from Arkcode.conversations import Conversation
from Arkcode.llm import ROLE_ASSISTANT, ROLE_TOOL, Message, ToolCall, ToolResult
from Arkcode.sessions.record import CompactBoundary


class RecordingSink:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.boundaries: list[CompactBoundary] = []

    def append_message(self, message: Message) -> None:
        self.messages.append(message)

    def append_boundary(self, boundary: CompactBoundary) -> None:
        self.boundaries.append(boundary)


def test_keeps_messages_in_turn_order() -> None:
    conversation = Conversation()

    conversation.add_user("我叫小明")
    conversation.add_assistant("你好，小明")
    conversation.add_user("我叫什么？")

    assert conversation.messages() == [
        Message(role="user", content="我叫小明"),
        Message(role="assistant", content="你好，小明"),
        Message(role="user", content="我叫什么？"),
    ]


def test_messages_returns_a_copy() -> None:
    conversation = Conversation()
    conversation.add_user("原始消息")

    returned = conversation.messages()
    returned.append(Message(role="assistant", content="外部修改"))

    assert conversation.messages() == [Message(role="user", content="原始消息")]


def test_last_role_tracks_empty_user_tool_and_assistant_tails() -> None:
    conversation = Conversation()
    call = ToolCall(id="call-1", name="read_file", input="{}")

    assert conversation.last_role() == ""
    conversation.add_user("读取")
    assert conversation.last_role() == "user"
    conversation.add_assistant_with_tool_calls("", [call])
    conversation.add_tool_results([ToolResult(tool_call_id="call-1", content="done")])
    assert conversation.last_role() == "tool"
    conversation.add_assistant("完成")
    assert conversation.last_role() == "assistant"


def test_keeps_tool_calls_and_results_in_protocol_neutral_history() -> None:
    conversation = Conversation()
    call = ToolCall(id="call-1", name="read_file", input='{"path":"a.txt"}')
    result = ToolResult(tool_call_id="call-1", content="content")

    conversation.add_user("读取文件")
    conversation.add_assistant_with_tool_calls("我先读取。", [call])
    conversation.add_tool_results([result])
    conversation.add_assistant("读取完成。")

    messages = conversation.messages()
    assert len(messages) == 4
    assert [message.role for message in messages] == [
        "user",
        ROLE_ASSISTANT,
        ROLE_TOOL,
        ROLE_ASSISTANT,
    ]
    assert messages[1].tool_calls == [call]
    assert messages[2].tool_results == [result]


def test_sink_commits_before_message_is_visible() -> None:
    conversation: Conversation

    class ObservingSink(RecordingSink):
        def append_message(self, message: Message) -> None:
            assert conversation.messages() == []
            super().append_message(message)

    conversation = Conversation(sink=ObservingSink())
    conversation.add_user("hello")
    assert conversation.messages() == [Message(role="user", content="hello")]


def test_sink_failure_prevents_memory_append() -> None:
    class FailingSink(RecordingSink):
        def append_message(self, message: Message) -> None:
            raise OSError("disk full")

    conversation = Conversation(sink=FailingSink())

    with pytest.raises(OSError, match="disk full"):
        conversation.add_user("lost")

    assert conversation.messages() == []


def test_boundary_failure_prevents_memory_replace() -> None:
    class FailingSink(RecordingSink):
        def append_boundary(self, boundary: CompactBoundary) -> None:
            raise OSError("disk full")

    conversation = Conversation(sink=FailingSink())
    conversation.add_user("old")

    with pytest.raises(OSError, match="disk full"):
        conversation.apply_compaction(
            CompactBoundary("summary", [], 1),
            [Message(role="user", content="new")],
        )

    assert conversation.messages() == [Message(role="user", content="old")]


def test_boundary_succeeds_before_memory_replace() -> None:
    sink = RecordingSink()
    conversation = Conversation(sink=sink)
    conversation.add_user("old")
    boundary = CompactBoundary("summary", [], 1)

    conversation.apply_compaction(
        boundary,
        [Message(role="user", content="new")],
    )

    assert sink.boundaries == [boundary]
    assert conversation.messages() == [Message(role="user", content="new")]


def test_append_deep_copies_message_to_memory_and_sink() -> None:
    sink = RecordingSink()
    conversation = Conversation(sink=sink)

    conversation.add_user("original")

    assert conversation.messages() == [Message(role="user", content="original")]
    assert sink.messages == [Message(role="user", content="original")]


def test_from_messages_produces_no_sink_calls() -> None:
    sink = RecordingSink()
    conversation = Conversation.from_messages(
        [Message(role="user", content="restored")],
        sink=sink,
    )

    assert conversation.messages() == [Message(role="user", content="restored")]
    assert sink.messages == []
    assert sink.boundaries == []


def test_replace_history_stays_memory_only_without_sink_io() -> None:
    sink = RecordingSink()
    conversation = Conversation(sink=sink)
    conversation.add_user("old")

    conversation.replace_history([Message(role="user", content="new")])

    assert conversation.messages() == [Message(role="user", content="new")]
    assert sink.boundaries == []
    assert sink.messages == [Message(role="user", content="old")]
