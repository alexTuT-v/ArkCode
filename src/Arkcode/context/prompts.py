"""全量会话摘要的固定提示词与解析逻辑。"""

import logging
import re

from ..llm import Message

logger = logging.getLogger(__name__)

SUMMARY_INSTRUCTION = """\
你正在压缩一个编程 Agent 的完整会话。请分两个阶段输出：
<analysis>
先分析请求、进展、关键事实和未完成事项；这段草稿会被丢弃。
</analysis>
<summary>
## 1 主要请求和意图
## 2 关键技术概念
## 3 文件和代码段
## 4 错误和修复
## 5 问题解决过程
## 6 所有用户消息原文
按时间顺序逐条完整保留用户消息原文。
## 7 待办任务
## 8 当前工作（最详细）
## 9 可能的下一步
</summary>
不要调用任何工具，输出纯文本。"""


def serialize_conversation(msgs: list[Message]) -> str:
    """把协议无关消息稳定序列化为供摘要模型阅读的文本。"""

    lines: list[str] = []
    for message in msgs:
        if message.role != "tool":
            lines.append(f"{message.role}: {message.content}")
        for call in message.tool_calls:
            lines.append(f"[call {call.name} id={call.id} args={call.input or '{}'}]")
        for result in message.tool_results:
            lines.append(
                f"[result id={result.tool_call_id} is_error={result.is_error}] "
                f"{result.content}"
            )
    return "\n".join(lines)


def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    """构造不包含工具定义的单条用户摘要请求。"""

    content = f"{SUMMARY_INSTRUCTION}\n\n[conversation]\n{serialize_conversation(msgs)}"
    return [Message(role="user", content=content)]


def extract_summary(raw: str) -> str:
    """取最后一个完整 summary 标签；缺失标签时保留模型原文。"""

    matches: list[str] = re.findall(
        r"<summary>(.*?)</summary>",
        raw,
        re.DOTALL,
    )
    if not matches:
        logger.warning("summary tags not found")
        return raw
    return matches[-1].strip()
