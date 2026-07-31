from Arkcode.conversation import Conversation
from Arkcode.llm import ROLE_ASSISTANT, ROLE_TOOL, Message, ToolCall, ToolResult


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
