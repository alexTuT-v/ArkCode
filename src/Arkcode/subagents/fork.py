"""Fork 消息构造与三层嵌套阻断。"""

from __future__ import annotations

import copy
from collections.abc import Sequence

from ..agents.identity import AgentIdentity
from ..conversations import Conversation
from ..llm import ROLE_TOOL, Message, ToolResult

FORK_BOILERPLATE = (
    "<fork_boilerplate>\n"
    "你是 Arkcode 的 Fork 子 Agent。\n"
    "- 不能再启动子 Agent（嵌套启动一律拒绝）。\n"
    "- 不要对话、提问或请求确认，直接使用工具。\n"
    "- 严格限制在分配的任务范围内，不要扩大范围。\n"
    "- 最终报告以 `Scope:` 开头，500 字以内。\n"
    "</fork_boilerplate>"
)


class AgentLaunchBlocked(RuntimeError):
    """嵌套启动 Agent 被拒绝。"""


def _repair_tail(messages: list[Message]) -> None:
    """把末尾 assistant 中未完成的 tool_use 补齐为占位 ToolResult。"""

    if not messages:
        return
    last = messages[-1]
    if last.role == "assistant" and last.tool_calls:
        placeholders = [
            ToolResult(call.id, "工具调用被中断（Fork 占位结果）", is_error=True)
            for call in last.tool_calls
        ]
        messages.append(Message(role=ROLE_TOOL, tool_results=placeholders))


def build_forked_messages(
    parent: Conversation | Sequence[Message],
    task: str,
) -> list[Message]:
    """深拷贝父历史，修复消息配对，并追加 Fork Boilerplate + 任务。"""

    if isinstance(parent, Conversation):
        messages = copy.deepcopy(parent.messages())
    else:
        messages = copy.deepcopy(list(parent))
    _repair_tail(messages)
    messages.append(Message(role="user", content=f"{FORK_BOILERPLATE}\n\n{task}"))
    return messages


def contains_fork_boilerplate(messages: Sequence[Message]) -> bool:
    return any("<fork_boilerplate>" in message.content for message in messages)


def assert_can_launch_agent(
    identity: AgentIdentity,
    messages: Sequence[Message],
) -> None:
    """三道防线：来源、父链与 Boilerplate 标记扫描。"""

    if identity.source == "fork":
        raise AgentLaunchBlocked("Fork 子 Agent 不能再启动 Agent")
    if identity.parent_id:
        parent = identity.parent_id
        if parent.startswith("fork"):
            raise AgentLaunchBlocked("Fork 子 Agent 不能再启动 Agent")
    if contains_fork_boilerplate(messages):
        raise AgentLaunchBlocked("Fork 子 Agent 不能再启动 Agent")
