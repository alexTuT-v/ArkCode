"""结构化消息协议与收件约束。"""

from __future__ import annotations

import uuid
from datetime import datetime

from .models import Message, MessageType


def new_message(
    from_agent: str,
    text: str,
    *,
    message_type: MessageType = MessageType.TEXT,
    request_id: str = "",
    approve: bool | None = None,
) -> Message:
    return Message(
        from_agent=from_agent,
        text=text,
        timestamp=datetime.now().astimezone().isoformat(),
        read=False,
        type=message_type,
        request_id=request_id,
        approve=approve,
    )


def ensure_request_id(message: Message) -> Message:
    if message.type is MessageType.TEXT or message.request_id:
        return message
    return Message(
        from_agent=message.from_agent,
        text=message.text,
        timestamp=message.timestamp,
        read=message.read,
        type=message.type,
        request_id=uuid.uuid4().hex[:12],
        approve=message.approve,
    )
