"""SubAgent 领域的数据模型：定义、运行结果与 Job 生命周期。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from ..agents import Agent, SessionRuntime
from ..agents.events import RunResult, RunStatus, Usage
from ..agents.identity import AgentIdentity
from ..conversations import Conversation
from ..permissions import Mode
from ..tools.workspace import ExecutionPathContext


class Source(Enum):
    """Agent 定义的来源，数字顺序即加载优先级（后者覆盖前者）。"""

    BUILTIN = 0
    USER = 1
    PROJECT = 2
    PLUGIN = 3


@dataclass(frozen=True, slots=True)
class Definition:
    """解析成功后不可变的 Agent 角色定义。"""

    name: str
    description: str
    instructions_content: str
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    model: str = "inherit"
    max_turns: int = 25
    permission_mode: str = "default"
    background: bool = False
    isolation: str = ""
    plan_mode_required: bool = False
    source: Source = Source.BUILTIN


class JobStatus(Enum):
    """对模型与用户统一的 Job 状态枚举。"""

    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            JobStatus.COMPLETED,
            JobStatus.LIMIT_REACHED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }


def status_from_run(status: RunStatus) -> JobStatus:
    return {
        RunStatus.COMPLETED: JobStatus.COMPLETED,
        RunStatus.LIMIT_REACHED: JobStatus.LIMIT_REACHED,
        RunStatus.FAILED: JobStatus.FAILED,
        RunStatus.CANCELLED: JobStatus.CANCELLED,
    }[status]


__all__ = [
    "Definition",
    "Source",
    "RunStatus",
    "RunResult",
    "JobStatus",
    "BackgroundTask",
    "LaunchRequest",
    "LaunchOutcome",
    "EnvironmentPreparer",
    "PreparedEnvironment",
    "CleanupReport",
]


@dataclass(slots=True)
class BackgroundTask:
    """一个正在执行或已结束的 Job 记录（内部名保留 mewCode 风格）。"""

    id: str  # 对外 job_id
    agent_id: str
    name: str
    agent_type: str
    agent: Agent
    conversation: Conversation
    task_text: str
    status: JobStatus = JobStatus.PREPARING
    result: str = ""
    error: Exception | None = None
    usage: Usage = field(default_factory=Usage)
    tool_count: int = 0
    last_activity: str = ""
    start_time: float = 0.0
    end_time: float | None = None
    run_in_background: bool = False
    worktree_name: str = ""
    worktree_path: str = ""
    worktree_branch: str = ""
    worktree_base_commit: str = ""
    # ---- 运行期内部状态 ----
    task: asyncio.Task[Any] | None = field(default=None, repr=False)
    foreground: bool = field(default=False, repr=False)
    backgrounded_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        repr=False,
    )
    cancel_event: asyncio.Event = field(
        default_factory=asyncio.Event,
        repr=False,
    )
    mode: Mode = field(default=Mode.DEFAULT, repr=False)
    identity: AgentIdentity | None = field(default=None, repr=False)
    runtime: SessionRuntime | None = field(default=None, repr=False)
    preparer: EnvironmentPreparer | None = field(default=None, repr=False)
    final_result: RunResult | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class LaunchRequest:
    """Agent 工具的标准化启动参数。"""

    prompt: str
    description: str
    subagent_type: str | None
    model: str | None
    run_in_background: bool
    name: str | None
    team_name: str | None = None
    plan_mode_required: bool = False
    fork_history_limit: int | None = None


@dataclass(slots=True)
class LaunchOutcome:
    """Agent 工具返回给主 Agent 的结果摘要。"""

    job_id: str
    status: str
    final_text: str = ""


class EnvironmentPreparer(Protocol):
    """后台 Job 的可选异步环境准备器（如 Worktree）。"""

    async def prepare(self, job: BackgroundTask) -> PreparedEnvironment: ...

    async def cleanup(
        self,
        job: BackgroundTask,
        outcome: RunResult | None,
    ) -> CleanupReport: ...


@dataclass(frozen=True, slots=True)
class PreparedEnvironment:
    workspace: ExecutionPathContext
    reminder: str


@dataclass(frozen=True, slots=True)
class CleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""
    base_commit: str = ""
