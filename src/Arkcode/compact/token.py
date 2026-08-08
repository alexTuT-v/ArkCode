"""无需精确 tokenizer 的保守 token 估算。"""

import math

from ..llm import Message, StreamEnd
from .const import ESTIMATE_CHARS_PER_TOKEN


def message_chars(msgs: list[Message]) -> int:
    """统计消息正文、工具参数和工具结果的 UTF-8 字节数。"""

    total = 0
    for message in msgs:
        total += len((message.content or "").encode("utf-8"))
        total += sum(
            len((call.input or "").encode("utf-8")) for call in message.tool_calls
        )
        total += sum(
            len((result.content or "").encode("utf-8"))
            for result in message.tool_results
        )
    return total


def estimate_tokens(
    anchor: int,
    all_msgs: list[Message],
    anchor_msg_len: int,
) -> int:
    """以真实 usage 为锚，只估算锚点之后新增的消息。"""

    start = min(len(all_msgs), max(0, anchor_msg_len))
    return int(anchor) + math.ceil(
        message_chars(all_msgs[start:]) / ESTIMATE_CHARS_PER_TOKEN
    )


def usage_anchor(usage: StreamEnd) -> int:
    """合并主对话流尾事件中的 token 用量。"""

    return int(
        usage.input_tokens + usage.output_tokens + usage.cache_read + usage.cache_write
    )
