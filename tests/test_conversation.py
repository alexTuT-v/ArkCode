from Arkcode.conversation import Conversation
from Arkcode.llm import Message


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
