"""SubAgent 审批的队列/Future 桥接。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

from ..agents.events import ApprovalRequest
from ..permissions import Outcome


@dataclass(slots=True)
class ApprovalRequestRecord:
    """TUI 展示的完整审批请求（带 request_id 与来源信息）。"""

    request_id: str
    agent_id: str
    agent_name: str
    agent_type: str
    job_id: str
    foreground: bool
    tool_name: str
    args_preview: str
    reason: str
    respond: asyncio.Future[Outcome]


class ApprovalBroker:
    """把子 Agent 的审批挂起到队列，由主 TUI 消费并回传 Outcome。"""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ApprovalRequestRecord] = asyncio.Queue()
        self._pending: dict[str, ApprovalRequestRecord] = {}

    async def submit(self, request: ApprovalRequest) -> Outcome:
        record = ApprovalRequestRecord(
            request_id=uuid.uuid4().hex[:12],
            agent_id=request.agent_id,
            agent_name=request.agent_name,
            agent_type=request.agent_type,
            job_id=request.job_id,
            foreground=request.foreground,
            tool_name=request.name,
            args_preview=request.args,
            reason=request.reason,
            respond=request.respond,
        )
        self._pending[record.request_id] = record
        self._queue.put_nowait(record)
        try:
            return await record.respond
        finally:
            self._pending.pop(record.request_id, None)

    async def next(self) -> ApprovalRequestRecord:
        return await self._queue.get()

    def respond(self, request_id: str, outcome: Outcome) -> bool:
        record = self._pending.get(request_id)
        if record is None or record.respond.done():
            return False
        record.respond.set_result(outcome)
        return True

    def cancel_agent(self, agent_id: str) -> None:
        """取消某 Agent 的所有 pending 审批，统一按拒绝处理。"""

        for record in list(self._pending.values()):
            if record.agent_id == agent_id and not record.respond.done():
                record.respond.set_result(Outcome.DENY_ONCE)

    def cancel_all(self) -> None:
        for record in list(self._pending.values()):
            if not record.respond.done():
                record.respond.set_result(Outcome.DENY_ONCE)

    @property
    def pending_count(self) -> int:
        return len(self._pending)
