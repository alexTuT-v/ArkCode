# SubAgent、Worktree 与 Agent Team Unified Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement the later approved `task.md` task-by-task. This document defines architecture; implementation is forbidden until `task.md` and `checklist.md` are approved.

**Goal:** 在 Arkcode 中以一套共享 Agent 运行时实现 SubAgent、Worktree 隔离和持久化 Agent Team 的最低可用闭环，并与 mewCode 当前行为保持一致。

**Architecture:** 先扩展现有 Agent loop 和按 Agent 隔离的 Registry/权限/Runtime，再在其上实现 SubAgent Job 生命周期；Worktree 作为可插拔执行环境接入；Agent Team 最后组合前两层并增加文件锁、Mailbox、Pane/in-process Backend 与 Coordinator。所有跨层能力通过显式接口组合，不复制 Agent loop 或修改全局 cwd。

**Tech Stack:** Python 3.12、asyncio、Pydantic 2、Textual、JSON 原子文件存储、Git Worktree、tmux/iTerm2、pytest、pytest-asyncio、Ruff、mypy。

## Global Constraints

- 权威输入仅为 `spec_sub_agent.md`、`spec_worktree.md`、`spec_agent_team.md`。
- Agent 角色名长度 1-32 且只允许小写字母、数字、连字符,即 `^[a-z0-9-]+$`。
- 角色 instructions 只能追加到 Arkcode 基础 system prompt,不得覆盖基础协议、安全、工具或环境内容。
- 对模型暴露 `JobList / JobGet / JobStop / JobSend` 与 `job_id`;完成提醒标签固定为 `<task-notification>`。
- 主进程和 in-process Agent 禁止 `os.chdir`;独立 Pane 子进程仅允许启动时调用一次。
- Worktree 本期不读取或设置 Git hooks,不修改 `core.hooksPath`。
- Team Lead 只存于 `lead_agent_id`,不得放入 `members`。
- Team 配置、任务板和 mailbox 的跨进程 read-modify-write 都必须使用 mewCode 风格 O_EXCL 文件锁与原子替换。
- Coordinator 工具白名单精确为 `Agent / SendMessage / JobStop / TeamDelete`;Coordinator 内禁止 Bash merge。
- 本期只实现规格明确要求的最低能力,不增加 SQLite、分布式 Team、专用 MergeTool、运行时 Coordinator 解锁或 Git hooks 管理。

---

## 设计输入与约束

本计划基于已经批准的以下规格：

- `spec_sub_agent.md`：SubAgent、Job 管理、Fork、Agent 定义与 Skill fork；
- `spec_worktree.md`：Worktree 生命周期、显式 cwd、后台隔离与命令；
- `spec_agent_team.md`：Team、三种后端、任务板、邮箱、Plan 审批与 Coordinator。

实现顺序固定为：

```text
统一 Agent 运行时
    ↓
SubAgent + JobManager + 权限作用域
    ↓
Worktree + ExecutionPathContext
    ↓
Agent Team + Mailbox + Backend
```

三层共享同一个 Agent 循环、权限引擎、工具注册抽象和会话持久化能力。后续层只能组合前一层公开接口，不复制 Agent Loop、Job runner 或 Worktree 生命周期代码。

本期遵循最低可用原则：Team 的文件存储、锁、Plan 审批和 Git 收敛方式与 mewCode 当前实现保持同一复杂度，不引入 SQLite、分布式锁、跨机器通信或专用 merge 工具。

## 架构概览

### 1. 核心运行层

现有 `Arkcode.agents.Agent` 继续作为唯一 ReAct 循环。它增加实例级最大轮数、追加式 `instructions_content`、运行身份、提醒收件箱和 `run_to_completion()` 适配器。基础 Arkcode system prompt 仍由现有 builder 生成,角色 instructions 只能追加在其后。交互式主 Agent 与所有子 Agent 都消费同一组 `AgentEvent`；RunToCompletion 只负责汇总事件，不实现第二套循环。

### 2. SubAgent 编排层

新增 `Arkcode.subagents` 领域包，负责 Agent 定义加载、Fork 消息构造、工具过滤、权限子作用域、Job 生命周期、通知与统一启动。`AgentTool`、`JobList`、`JobGet`、`JobStop`、`JobSend` 作为该领域自己的 Tool 实现，通过组合根注册到主 Registry。

### 3. Worktree 隔离层

新增 `Arkcode.worktrees` 领域包，封装 Git Worktree、manifest、session、变更检测、创建后初始化与过期清理。新增与领域无关的 `ExecutionPathContext`，六个核心工具从该上下文读取 cwd 和 workspace_root，使主进程与 in-process Agent 不调用 `os.chdir()`；独立 Pane worker 在进程启动且创建异步任务前允许一次 `os.chdir(worktree_path)`。

### 4. Agent Team 协作层

新增 `Arkcode.teams` 领域包，管理 Team、成员、共享任务、Mailbox、Agent 名称、三种 Backend、Plan 审批和 Coordinator。in-process 队员复用 SubAgent JobManager；tmux/iTerm2 队员通过 `--team-member` 启动独立 worker 进程。所有队员都复用 WorktreeManager 创建的隔离目录。

### 5. 应用与 TUI 集成层

`ApplicationRuntime` 负责创建并关闭 Catalog、JobManager、WorktreeManager、TeamManager 和后台消费者。`SessionService` 继续拥有当前主 Agent/Conversation，并向编排工具提供“当前父会话”绑定。TUI 只处理展示、ESC 所有权切换、审批队列、完成通知和 Team 邮件唤醒，不直接实现领域逻辑。

## 依赖方向

```text
llm / conversations / permissions / tools / sessions
                    ↑
                  agents
                    ↑
                subagents
                    ↑
          worktrees integration adapter
                    ↑
                   teams
                    ↑
             application / tui
```

约束：

- `agents` 不导入 `subagents`、`worktrees` 或 `teams`；
- `tools` 核心包不导入高层领域，领域 Tool 放在各自包内；
- `worktrees` 的 Git 核心不依赖 SubAgent，只由 integration adapter 实现 SubAgent 环境准备协议；
- `teams` 可以依赖 SubAgent 与 Worktree 的公开接口；
- 具体 Manager、Backend、Tool 的构造只发生在 `application/bootstrap.py` 和 team-member CLI composition root。

## 公共运行模型

### AgentIdentity

```python
@dataclass(frozen=True, slots=True)
class AgentIdentity:
    agent_id: str
    parent_id: str
    trace_id: str
    agent_type: str
    name: str
    source: Literal["main", "defined", "fork", "skill", "teammate"]
    team_name: str = ""
```

AgentIdentity 通过 Agent 构造参数与 ContextVar 同时提供：Agent 本身用于事件和 trace；Tool 调用使用 ContextVar 判断调用来源、权限作用域和 Team 上下文。Fork 嵌套拦截不得依赖模型可伪造的普通参数。

### RunStatus 与 RunResult

```python
class RunStatus(StrEnum):
    COMPLETED = "completed"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass(slots=True)
class RunResult:
    status: RunStatus
    final_text: str
    error: Exception | None
    usage: Usage
    tool_count: int
    last_activity: str
```

`Agent.run()` 仍返回事件流；最后一个完成事件带明确 stop reason。`Agent.run_to_completion()` 消费同一事件流并构造 RunResult。达到最大轮数时返回 `LIMIT_REACHED`，不同时返回成功并抛异常。

### ReminderInbox

```python
class ReminderInbox:
    def append(self, text: str) -> None: ...
    def drain(self) -> list[str]: ...
```

主 Agent、SubAgent 和 teammate 各自持有 ReminderInbox。Agent 每次请求模型前 drain，并与现有 recall、plan、deferred-tool reminder 合并。Job 通知、Team 邮件和 worktree/team context 都走这个入口，避免直接伪装成真实用户消息。

### RegistryPolicy 与 RegistryView

```python
@dataclass(frozen=True, slots=True)
class RegistryPolicy:
    globally_denied: frozenset[str]
    allowed: frozenset[str] | None
    denied: frozenset[str]
    background_allowed: frozenset[str] | None
    keep_agent_schema: bool = False

class RegistryView(Registry):
    @classmethod
    def from_parent(
        cls,
        parent: Registry,
        policy: RegistryPolicy,
        *,
        copy_discovery: bool,
    ) -> "RegistryView": ...
```

每个 Agent 获得独立 discovered 集合和过滤策略，但共享不可变 Tool 实现或安全克隆。ToolSearch 必须绑定当前 RegistryView，搜索和精确加载都再次应用 policy，MCP、Skill 与延迟工具不能绕过过滤。

## SubAgent 设计

### Definition

```python
@dataclass(frozen=True, slots=True)
class Definition:
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
```

`Source` 使用有序枚举表达 project、user、builtin、plugin。parser 强制 `name` 匹配 `^[a-z0-9-]+$`；Definition 在解析成功后不可变，避免运行中被 reload 修改。Launcher 将 `instructions_content` 追加到不可替换的基础 system prompt,不允许 Definition 替换基础提示。

### Catalog

```python
class Catalog:
    def load(self) -> None: ...
    def reload(self) -> None: ...
    def resolve(self, name: str) -> Definition | None: ...
    def list(self) -> list[tuple[str, str]]: ...
```

加载顺序为 builtin → user → project，后加载覆盖前者；plugin source 仅保留入口。内置定义错误直接抛出；用户和项目定义错误 warning 后跳过。项目/用户文件记录最后一次成功解析结果，为未来热重载保留稳定缓存。

### ProviderResolver

```python
class ProviderResolver(Protocol):
    def resolve(self, model: str, parent: Provider) -> Provider: ...
```

`inherit` 返回父 Provider；其他字符串先按已配置 provider 名称匹配，未匹配时复制当前 ProviderConfig 并覆盖 model。Provider 创建失败直接结束本次 Agent 调用，不静默回退。

### 权限作用域

```python
@dataclass(frozen=True, slots=True)
class PermissionScope:
    value: str

@dataclass(slots=True)
class PermissionLedger:
    allow: list[Rule]
    deny: list[Rule]

class ScopedRuleStore:
    def match(self, scope: PermissionScope, call: ToolCall) -> MatchResult: ...
    def persist_project(self, scope: PermissionScope, call: ToolCall) -> None: ...

class Engine:
    def child(
        self,
        scope: PermissionScope,
        ledger: PermissionLedger,
        mode: Mode,
    ) -> "Engine": ...
```

Engine 的系统黑名单与 PathSandbox 始终最先执行。持久规则按 global、main-agent、subagent-type、subagent-instance 匹配；临时 Ledger 每个 Agent 独立。现有 YAML 字符串规则作为 `main-agent` 兼容读取，新写入的带作用域规则使用对象形式，不改变旧配置的可读性。

`Outcome` 扩展为：

- DENY_ONCE；
- ALLOW_ONCE；
- ALLOW_AGENT；
- SAVE_PROJECT_RULE。

保存项目规则由 TUI 二次确认；其他结果只写当前 Ledger。普通 SubAgent 审批通过 ApprovalBroker 排队，不打断父模型流。

### ApprovalBroker

```python
@dataclass(slots=True)
class ApprovalRequest:
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
    async def submit(self, request: ApprovalRequest) -> Outcome: ...
    async def next(self) -> ApprovalRequest: ...
    def cancel_agent(self, agent_id: str) -> None: ...
```

ToolExecutor 接受可选 ApprovalBroker。主 Agent 继续直接把 approval 作为 AgentEvent 交给 TUI；SubAgent 将请求送入 Broker。TUI 在父流安全边界展示队列中的审批，响应 Future 后只恢复对应 job。

### Job 数据结构

内部类名保留 mewCode 风格的 `TaskManager` / `BackgroundTask`，对模型和用户统一暴露 Job 术语。

```python
class JobStatus(StrEnum):
    PREPARING = "preparing"
    RUNNING = "running"
    COMPLETED = "completed"
    LIMIT_REACHED = "limit_reached"
    FAILED = "failed"
    CANCELLED = "cancelled"

@dataclass(slots=True)
class BackgroundTask:
    id: str                         # 对外 job_id
    agent_id: str
    name: str
    agent_type: str
    agent: Agent
    conversation: Conversation
    task_text: str
    status: JobStatus
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
```

### TaskManager

```python
class TaskManager:
    def launch(self, request: LaunchRequest) -> BackgroundTask: ...
    async def wait_foreground(self, job_id: str, timeout: float) -> RunResult | None: ...
    def move_to_background(self, job_id: str) -> bool: ...
    def adopt_running(self, handle: ExecutionHandle) -> BackgroundTask: ...
    def get(self, job_id: str) -> BackgroundTask | None: ...
    def list(self) -> list[BackgroundTask]: ...
    async def stop(self, job_id: str) -> bool: ...
    def resume(self, agent_ref: str, message: str) -> BackgroundTask: ...
    def subscribe_done(self) -> asyncio.Queue[str]: ...
    async def shutdown(self) -> None: ...
```

前台 Agent 调用也先登记为同一个 BackgroundTask。120 秒超时用 `asyncio.shield()` 等待，不取消底层运行；超时或 ESC 只把 `run_in_background` 设为 true 并切换事件所有者,对外 status 仍为 `running`。审批等待是运行中的子状态,不扩张对外状态枚举。Registry 为 AgentTool 提供禁用默认 30 秒超时的能力，否则工具层会先于 120 秒终止。

runner 分别捕获 `asyncio.CancelledError` 和普通 `Exception`，终态使用 compare-and-set 只写一次。所有终态把 job_id 放入 done queue。

### SubAgentLauncher

```python
@dataclass(frozen=True, slots=True)
class LaunchRequest:
    prompt: str
    description: str
    subagent_type: str | None
    model: str | None
    run_in_background: bool
    name: str | None
    team_name: str | None = None
    plan_mode_required: bool = False

class EnvironmentPreparer(Protocol):
    async def prepare(self, job: BackgroundTask) -> PreparedEnvironment: ...
    async def cleanup(self, job: BackgroundTask, outcome: RunResult) -> CleanupReport: ...

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

@dataclass(slots=True)
class LaunchOutcome:
    job_id: str
    status: str
    final_text: str = ""

class SubAgentLauncher:
    async def launch(self, request: LaunchRequest, parent: ParentContext) -> LaunchOutcome: ...
    async def launch_fork(self, ...) -> LaunchOutcome: ...
```

Launcher 是定义式、Fork、Skill fork 和 in-process teammate 的唯一 Agent 构造入口。它负责 Definition、Provider、RegistryView、Engine.child、SessionRuntime、Conversation、Identity 和可选 EnvironmentPreparer 的装配。

### Fork 消息

`build_forked_messages(parent, task)` 深拷贝父历史，补齐末尾未完成 tool call 的 placeholder result，再追加 `<fork_boilerplate>` 与任务。Fork RegistryView 保留 Agent schema，但 AgentTool 通过 Identity.source、父链和 boilerplate 扫描拒绝嵌套。

### SubAgent 工具

- `AgentTool`：Pydantic 参数模型，调用 Launcher；`team_name` 非空时委托 TeamSpawner；
- `JobListTool`：输出 Job 摘要；
- `JobGetTool`：输出完整结果、错误、usage 与 worktree 信息；
- `JobStopTool`：调用 TaskManager.stop；
- `JobSendTool`：调用 TaskManager.resume，运行中 Agent 返回错误。

AgentTool 的 schema 在启动时固定注册，不根据 Catalog 内容动态改变；可用类型通过 system prompt catalog 提示。

### Skill fork 收敛

`SkillExecutor.execute_fork()` 不再自行构造 Agent。它把 SkillMeta 转成临时 Definition/LaunchRequest，并调用 `SubAgentLauncher.launch_fork()`；上下文 recent/full 的现有语义在 Fork adapter 中保留，最终结果仍由 SkillsController 写入 system reminder。

## Worktree 设计

### ExecutionPathContext

```python
class Access(StrEnum):
    READ = "read"
    WRITE = "write"

@dataclass(frozen=True, slots=True)
class ExecutionPathContext:
    cwd: Path
    workspace_root: Path
    readonly_shared_targets: tuple[Path, ...] = ()

def current_workspace() -> ExecutionPathContext: ...
def workspace_scope(context: ExecutionPathContext) -> ContextManager[None]: ...
def resolve_path(value: str, access: Access) -> Path: ...
```

该上下文放在 `Arkcode.tools.workspace`，因为主 Agent、SubAgent 和 teammate 的所有工具都需要使用，而不是 Worktree 专属实现。默认上下文由 SessionService 的 workspace 构造，不允许退化为无限制进程 cwd。

Read/Write/Edit/Glob/Grep 使用 `resolve_path()`；Bash 使用 `cwd=context.cwd`，并按当前 workspace_root 动态构造 OS SandboxConfig。ToolExecutor 的文件恢复缓存也使用相同 resolved path。

### Worktree 与 Manifest

```python
@dataclass(frozen=True, slots=True)
class Worktree:
    name: str
    path: Path
    branch: str
    based_on: str
    base_commit: str
    created: datetime
    manual: bool
    owner_job_id: str

@dataclass(frozen=True, slots=True)
class WorktreeManifest:
    schema_version: int
    repo_id: str
    repo_common_dir: str
    name: str
    path: str
    branch: str
    base_ref: str
    base_commit: str
    created_at: str
    manual: bool
    owner_job_id: str
```

Manifest 使用 Pydantic 校验和 `atomic_write_json()` 写入。恢复同时校验 repo_id、路径、branch、HEAD、base_commit 和 owner；任何不一致都 fail-closed。

### GitRunner

```python
class GitRunner:
    async def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
        timeout: float = 60.0,
    ) -> CompletedGitCommand: ...
```

使用 `asyncio.create_subprocess_exec`，固定 `GIT_TERMINAL_PROMPT=0` 与空 `GIT_ASKPASS`。取消时终止并等待进程，不遗留 git 子进程。所有命令显式 cwd，不使用 `os.chdir()`。

### WorktreeManager

```python
class WorktreeManager:
    @classmethod
    async def open(cls, repo_root: Path, config: WorktreeConfig) -> "WorktreeManager": ...
    async def create(
        self,
        name: str,
        base_ref: str = "HEAD",
        *,
        manual: bool,
        owner_job_id: str = "",
    ) -> Worktree: ...
    async def enter(self, name: str) -> WorktreeSession: ...
    async def exit(self, name: str, action: ExitAction, options: ExitOptions) -> ExitReport: ...
    async def remove(self, name: str, options: ExitOptions) -> ExitReport: ...
    async def auto_cleanup(self, name: str) -> AutoCleanupReport: ...
    async def sweep_stale(self, cutoff: datetime) -> list[str]: ...
    def list(self) -> list[Worktree]: ...
```

Manager 用 reservation + asyncio.Lock 保护同进程并发，耗时 Git 命令不持锁。创建失败只清理 manifest 已确认属于当前 reservation 的资源。删除失败保留 manifest 和 active 记录。

### 创建后设置

`setup.py` 分三个独立 best-effort 步骤：

1. 复制 `.Arkcode/config.yaml` 和 `.Arkcode/settings.local.yaml`；
2. 在 OS/path sandbox 能保证只读时建立共享依赖 symlink；
3. 按 `.worktreeinclude` 复制匹配的 ignored file。

每步独立捕获错误并 warning，不能使已经创建成功的 Worktree 失败。`shared_writable_dirs` 非空时配置加载失败。本期 setup 不探测 `.husky/`,不读取或写入 `core.hooksPath`,也不运行任何 hooks 配置命令。

### WorktreeEnvironmentPreparer

```python
class WorktreeEnvironmentPreparer(EnvironmentPreparer):
    async def prepare(self, job: BackgroundTask) -> PreparedEnvironment: ...
    async def cleanup(self, job: BackgroundTask, outcome: RunResult) -> CleanupReport: ...
```

prepare 生成 `agent-a<7hex>`，创建 Worktree，写回 job 的 worktree 字段，返回 ExecutionPathContext 和 notice。cleanup 调 auto_cleanup；有变更时保留并把 path/branch/base_commit 追加到 Job 结果。

### Worktree Session 与命令

`WorktreeSessionStore` 原子保存 `.Arkcode/worktree_session.json`。SessionService 新增 active workspace 字段；`/worktree enter` 只替换后续 run 的 ExecutionPathContext，不改变进程 cwd。

命令层增加 `WorktreeCommands` Protocol 与 `commands/handlers/worktree.py`，由 CommandUIAdapter 调用 WorktreeManager。`/worktree create/list/enter/exit/remove` 均不写入对话历史。

## Agent Team 设计

### Team 核心模型

```python
class BackendType(StrEnum):
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"

@dataclass(slots=True)
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str
    model: str
    worktree_path: str
    branch: str
    backend_type: BackendType
    pane_id: str
    is_active: bool | None
    plan_mode_required: bool
    session_dir: str

@dataclass(slots=True)
class Team:
    name: str
    sanitized_name: str
    description: str
    lead_agent_id: str
    members: list[TeammateInfo]
    config_dir: Path
    config_path: Path
    created_at: datetime
    backend: BackendType
```

Team 自带 `asyncio.Lock`,但它只保护同进程协程。跨进程修改 `config.json` 时固定按 `Team._lock → config.lock` 顺序获取锁,在文件锁内 reload 最新 members、修改并以唯一临时文件 + `flush/fsync/os.replace` 原子替换；后端 spawn/kill 不持任一锁。与 mewCode 同级复杂度,本期使用 JSON 文件,不增加数据库。

`lead_agent_id` 独立保存 Lead；`members` 只保存 teammate,Team 创建时必须是空列表。所有成员遍历、删除和活跃计数都不得把 Lead 当成 `TeammateInfo`。

`teams/storage.py` 提供所有 Team JSON 状态共用的同步文件锁原语,由 async 调用方通过线程桥接避免阻塞事件循环：

```python
class FileLock:
    def __init__(
        self,
        path: Path,
        *,
        acquire_timeout: float = 5.0,
        stale_age: float = 10.0,
        initial_backoff: float = 0.005,
        max_backoff: float = 0.08,
    ) -> None: ...

    def __enter__(self) -> "FileLock": ...
    def __exit__(self, *exc: object) -> None: ...

def atomic_update_json(path: Path, lock: FileLock, mutate: Callable[[Any], Any]) -> Any: ...
```

锁通过 `os.open(O_CREAT | O_EXCL | O_WRONLY)` 获取,失败时使用指数退避加随机抖动；超过 10 秒的 lock file 可按 mtime 清理,总等待 5 秒后抛 `TimeoutError`。`config.json/config.lock`、`tasks.json/tasks.lock`、`mailbox/<agent_id>.json/<agent_id>.json.lock` 都必须让完整 read-modify-write 位于该临界区内。

### TeamManager

```python
class TeamManager:
    async def create(self, name: str, agent_type: str = "") -> Team: ...
    def get(self, name: str) -> Team | None: ...
    def list(self) -> list[Team]: ...
    async def delete(self, name: str, force: bool) -> None: ...
    async def add_member(self, team: str, member: TeammateInfo) -> None: ...
    async def set_member_active(self, team: str, member: str, active: bool) -> None: ...
    async def remove_member(self, team: str, member: str) -> None: ...
    async def stop_member(self, member: str) -> bool: ...
```

启动时扫描 `~/.Arkcode/teams/*/config.json`。in-process 成员重启后标 idle；Pane 成员通过 backend probe 判活。delete 严格按 kill → session/worktree cleanup → team dir → memory map 的顺序执行。

### Backend Protocol

```python
@dataclass(frozen=True, slots=True)
class SpawnRequest:
    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str
    model: str
    initial_prompt: str
    plan_mode_required: bool
    agent: Agent | None = None
    conversation: Conversation | None = None

@dataclass(frozen=True, slots=True)
class SpawnResult:
    pane_id: str
    agent_id: str
    backend: BackendType

class Backend(Protocol):
    async def spawn(self, request: SpawnRequest) -> SpawnResult: ...
    async def wake(self, pane_id: str, agent_id: str) -> None: ...
    async def kill(self, pane_id: str, agent_id: str) -> None: ...
    async def is_alive(self, pane_id: str, agent_id: str) -> bool: ...
```

BackendDetector 按 `$TMUX`、iTerm2+it2、PATH 中 tmux、in-process 的顺序选择一次，不静默回退。

- TmuxBackend：split-window 或 detached new-session；
- Iterm2Backend：通过 `it2 split-pane`；
- InProcessBackend：调用 SubAgentLauncher 构造 teammate，再交给 TaskManager；禁止 in-process teammate 带 team_name 再 spawn 队员，后台 SubAgent 参数返回错误。

### team-member CLI

`application/cli.py` 增加 argparse 路由。普通模式仍启动 TUI；`--team-member` 调 `teams/worker.py::run_team_member()`：

1. 校验 team/member/agent-id/session-dir/worktree 参数；
2. 在创建任何 asyncio task、Agent 或 runtime 前执行唯一一次 `os.chdir(worktree_path)`,并立即验证 `Path.cwd()`；此后禁止再次改变 cwd；
3. 构造 provider、registry、permissions、hooks、session 和 TeamContext；
4. 消费初始 mailbox，执行 run_to_completion；
5. stdout 仅输出 text/tool/done/error 日志；
6. idle 后轮询 mailbox，stdin 换行只触发 wake_event；
7. mailbox 被删除或收到 shutdown 后退出。

Pane worker 是独立进程,不共享主进程 cwd；一次启动 chdir 与该进程的 ExecutionPathContext 同时固定到 worktree。主进程和 in-process teammate 始终只使用 ExecutionPathContext,绝不调用 `os.chdir()`。

### SharedTaskStore

```python
class SharedTaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"

@dataclass(slots=True)
class SharedTask:
    id: str
    title: str
    description: str
    status: SharedTaskStatus
    assignee: str
    blocked_by: list[str]
    blocks: list[str]
    created_at: int
    updated_at: int
```

SharedTaskStore 使用统一 `FileLock(tasks.lock)` 包围完整 read-modify-write，并用唯一临时文件 + `flush/fsync/os.replace` 保存。TaskUpdate 在同一锁内维护 blocked_by/blocks 双向关系。TaskCreate/Get/List/Update Tool 只注入 teammate RegistryView。

### Mailbox 与消息协议

```python
@dataclass(slots=True)
class Message:
    from_agent: str
    text: str
    timestamp: str
    read: bool
    type: MessageType = MessageType.TEXT
    request_id: str = ""
    approve: bool | None = None

class Box:
    async def write(self, agent_id: str, message: Message) -> None: ...
    async def read(self, agent_id: str) -> list[Message]: ...
    async def mark_read(self, agent_id: str, indexes: list[int]) -> None: ...
```

Box 直接复用统一 `FileLock`：每个收件人使用 `<agent_id>.json` 与 `<agent_id>.json.lock`,初始退避 5ms、单次封顶 80ms、获取期限 5 秒、stale 阈值 10 秒；写入使用唯一临时文件 + `flush/fsync/os.replace`。广播从 Lead 发出时覆盖所有 members；从 teammate 发出时覆盖其他 members 并额外投递 `lead_agent_id`。

MessageType 包含 text、shutdown_request/response、plan_approval_request/response。非 text 请求生成随机 request_id；response 原样携带 request_id。SendMessage 对 Lead 和 teammate 可见，普通 SubAgent 不可见。

### Plan 审批

plan_mode_required teammate 以 Mode.PLAN 启动。一轮结束后读取计划文本，创建 `plan_approval_request` 并进入 awaiting_plan_approval。worker 只接受 request_id 匹配的 response：

- approve=True：切换 Mode.DEFAULT，下一轮按计划执行；
- approve=False：反馈作为下一轮用户文本，保持 PLAN 并重新提交新 request。

本期不设置超时，不持久化独立审批表。

### TeamSpawner 与 AgentTool 分流

```python
class TeamSpawner:
    async def spawn(self, request: LaunchRequest, parent: ParentContext) -> SpawnResult: ...
```

AgentTool 只判断 team_name 是否非空；非空委托 TeamSpawner。TeamSpawner 校验调用身份和 Team，预生成最终 agent_id,创建 team worktree 与 session，构造 teammate registry/context,在 Backend 启动前注册 name 与 member。Pane 初始 prompt 在 spawn 前写 mailbox；in-process 直接传给 TaskManager。

统一 spawn 顺序固定为：

1. 加载 Definition,生成 Team 内唯一 member_name 和最终 agent_id；
2. 创建 Worktree、session、RegistryView、Conversation 与 SpawnRequest；
3. 在 `backend.spawn()` 前注册 `AgentNameRegistry`,并在 `config.lock` 临界区把 `TeammateInfo(pane_id="", is_active=True)` 写入 members；
4. Pane 后端把 initial prompt 预写到该 agent_id mailbox,in-process 后端把 prompt 放入 TaskManager request；
5. 调 `backend.spawn()`,要求后端沿用预生成 agent_id；
6. 在短 `config.lock` 临界区回写 pane_id/backend/is_active；
7. spawn 失败则移除预注册 member、注销 name、清理由本次创建且身份可确认的 session/Worktree,并返回原错误。

### Coordinator Mode

配置模型增加 feature 集合与 coordinator 环境开关。只有 feature 与环境变量同时开启时，SessionService 在构造主 Agent RegistryView 时应用 `COORDINATOR_ALLOWED_TOOLS`，追加 coordinator prompt，并让状态栏显示标签。过滤后的 RegistryView 在本次进程内不可恢复，关闭只能重启。

```python
COORDINATOR_ALLOWED_TOOLS: frozenset[str] = frozenset({
    "Agent",
    "SendMessage",
    "JobStop",
    "TeamDelete",
})
```

该白名单映射 mewCode 的 `TaskStop → JobStop`,并因 Arkcode 本期没有 SyntheticOutput 而不新增该工具。`TeamCreate`、Team Task 工具、read/glob/grep、write/edit 和 Bash 都必须被 RegistryView 排除。Coordinator 只能委派、接收 `<task-notification>`/`<team-update>` 并综合消息；不得自行探索、实现或 merge。

收敛阶段不实现 MergeTool。Coordinator 必须保留 Team 与 teammate Worktree,退出 Arkcode 并以普通模式恢复后,普通 Lead 才能使用 Bash 执行规格中的 `git merge --no-ff`；冲突时自行编辑或 `git merge --abort`,失败保留 teammate Worktree。完成 merge 后才允许 `TeamDelete`。

### Team TUI 集成

`tui/tasks.py` 管理两个长生命周期协程：

- `consume_job_notifications()`：消费 TaskManager done queue，向主 ReminderInbox 注入 `<task-notification>`；
- `consume_lead_mail()`：轮询 Team Lead mailbox，注入 `<team-update>` 并 set lead_mail_event。

Lead idle 时收到 team mail，ChatController 启动内部 autonomous turn；主 Agent 正在运行时只追加 reminder，由下一次模型请求自然读取。

命令层增加 `TeamCommands` Protocol 与 `/team list/info/delete/kill` handler。

## 模块交互

### 定义式前台 SubAgent

```text
主 Agent → AgentTool → SubAgentLauncher
  → Catalog.resolve
  → ProviderResolver + RegistryView + Engine.child
  → TaskManager 登记 running_foreground
  → Agent.run_to_completion
  → RunResult → AgentTool Result → 主 Agent
```

### 前台转后台

```text
TaskManager 中同一个 job 正在运行
  ├─ 120 秒到期 → move_to_background
  └─ 用户 ESC → TUI 调 move_to_background
       ↓
AgentTool 返回 job_id，底层 asyncio.Task/Conversation/usage 不变
       ↓
完成 → done queue → ReminderInbox → <task-notification>
```

### Worktree 后台 SubAgent

```text
AgentTool → TaskManager(status=preparing, owner_job_id)
  → WorktreeEnvironmentPreparer.prepare
  → workspace_scope(worktree)
  → Agent.run_to_completion
  → cleanup(auto remove or preserve)
  → one terminal notification
```

### Team teammate

```text
Lead → TeamCreate → TeamManager
Lead → Agent(team_name=...) → TeamSpawner
  → 预生成 agent_id → WorktreeManager.create
  → teammate Session/Registry/Context
  → AgentNameRegistry.register + Team.add_member(config.lock)
  → Backend.spawn → Team member backend 信息回写
  → teammate 执行并写 Lead mailbox
  → TUI mail pump 唤醒 Lead
```

## 文件组织

```text
src/Arkcode/
├── agents/
│   ├── agent.py                 — 可配置 Agent Loop、run_to_completion
│   ├── events.py                — stop reason、丰富审批事件
│   ├── execution.py             — Broker、作用域权限与 workspace 路径接入
│   ├── identity.py              — AgentIdentity 与调用 ContextVar
│   └── runtime.py               — ReminderInbox、每 Agent 运行状态
├── subagents/
│   ├── __init__.py
│   ├── models.py                — Definition、Run/Job/Launch 数据结构
│   ├── parser.py                — Markdown frontmatter 解析
│   ├── catalog.py               — 三层定义加载与覆盖
│   ├── builtins/
│   │   ├── general-purpose.md
│   │   ├── explore.md
│   │   └── plan.md
│   ├── filter.py                — RegistryPolicy / RegistryView 构造
│   ├── fork.py                  — Fork 消息与嵌套检测
│   ├── approvals.py             — ApprovalBroker
│   ├── manager.py               — TaskManager / BackgroundTask
│   ├── launcher.py              — 统一启动入口
│   ├── notification.py          — `<task-notification>` 格式化
│   └── tools.py                 — Agent、JobList/Get/Stop/Send
├── worktrees/
│   ├── __init__.py
│   ├── models.py                — Worktree、Session、Manifest、Report
│   ├── slug.py                  — slug 验证与 flatten
│   ├── git.py                   — 可取消异步 GitRunner
│   ├── manifest.py              — 原子存储与身份校验
│   ├── changes.py               — 未提交/新增/未推送检查
│   ├── setup.py                 — 创建后三步设置,明确跳过 hooks
│   ├── session.py               — worktree session 持久化
│   ├── manager.py               — 生命周期与 stale sweep
│   └── integration.py           — SubAgent EnvironmentPreparer
├── teams/
│   ├── __init__.py
│   ├── models.py                — Team、Member、Backend、Message、Task
│   ├── manager.py               — Team 生命周期
│   ├── storage.py               — O_EXCL FileLock 与原子 JSON 更新
│   ├── registry.py              — AgentNameRegistry
│   ├── mailbox.py               — Box
│   ├── protocol.py              — 结构化消息协议
│   ├── shared_tasks.py          — SharedTaskStore
│   ├── coordinator.py           — 开关、白名单与 prompt
│   ├── spawner.py               — AgentTool Team 分支
│   ├── worker.py                — --team-member 自治循环
│   ├── tools.py                 — Team/Task/SendMessage 工具
│   └── backends/
│       ├── base.py
│       ├── detect.py
│       ├── inprocess.py
│       ├── tmux.py
│       └── iterm2.py
├── tools/
│   ├── registry.py              — RegistryView、per-tool timeout
│   ├── workspace.py             — ExecutionPathContext / resolve_path
│   └── builtins/                — 六个工具显式 cwd 改造
├── permissions/
│   ├── engine.py                — child Engine 与裁决顺序
│   ├── scope.py                 — Scope、Ledger、ScopedRuleStore
│   ├── settings.py              — 带作用域规则兼容解析
│   └── types.py                 — dontAsk 与新 Outcome
├── commands/
│   ├── ports.py                 — WorktreeCommands、TeamCommands
│   └── handlers/
│       ├── worktree.py
│       └── team.py
├── application/
│   ├── bootstrap.py             — 新 Manager/Tool composition
│   ├── runtime.py               — 生命周期所有权
│   ├── session.py               — ParentContext、active workspace、提醒
│   └── cli.py                   — 普通 TUI / team-member 路由
└── tui/
    ├── app.py                   — ESC 转后台、后台消费者启停
    ├── tasks.py                 — Job/Team 通知消费
    ├── controllers/approvals.py — SubAgent 审批队列与二次确认
    └── widgets/status_bar.py    — Coordinator 标识

tests/
├── subagents/
├── worktrees/
├── teams/
├── tools/test_workspace_context.py
├── integration/test_subagent_worktree.py
├── integration/test_team_inprocess.py
└── architecture/test_dependencies.py
```

## 技术决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| Agent Loop | 扩展现有 Agent，RunToCompletion 消费同一事件流 | 避免主/子两套循环行为漂移 |
| 后台内部命名 | 保留 TaskManager/BackgroundTask | 与 mewCode 实现接近，降低迁移成本 |
| 模型可见命名 | JobList/Get/Stop/Send + job_id | 与 Team 的 Task* / SendMessage 分域 |
| Registry 隔离 | 每 Agent RegistryView + 独立 discovered | 防止 ToolSearch 和过滤状态跨 Agent 污染 |
| 权限 | 共享带作用域持久规则，临时 Ledger 独立 | 满足新版 spec，避免继承主 Agent 临时放行 |
| 审批 | ApprovalBroker + Future | 允许后台 Agent 暂停而不抢断父模型流 |
| 前台转后台 | 同一 asyncio.Task 切换所有权 | 保留 Conversation、工具结果和 usage |
| 路径上下文 | ContextVar + 显式 subprocess cwd；Pane 启动时一次 chdir | 主/in-process 并发安全,同时让独立 Pane 进程 cwd 与 Worktree 对齐 |
| Worktree 恢复 | manifest + repo identity fail-closed | 不复用无法证明归属的目录/分支 |
| Team 存储 | config/tasks/mailbox 统一 JSON + O_EXCL 文件锁 + fsync/atomic replace | 将 mewCode mailbox 锁原语扩展到所有跨进程 read-modify-write |
| Plan 审批 | request/response + request_id | 按 mewCode 实际实现，避免自然语言猜关联 |
| Team 权限 | 普通队员 dontAsk，plan_required 先 PLAN | 没有子 TUI 时避免永久阻塞 |
| Coordinator | 精确白名单 `Agent/SendMessage/JobStop/TeamDelete` | 对齐 mewCode 实际纯调度模型,不让 Lead 自行探索或实现 |
| Team 收敛 | 退出 Coordinator 后由普通 Lead Bash git merge | 不增加 MergeTool,同时保持 Coordinator 无 Bash 的工具边界 |
| Pane 后端失败 | 返回错误，不静默回退 in-process | 保持执行模型可预测 |
| 生命周期 | Runtime 显式 shutdown 所有 task/backend | 避免退出时遗留子进程、Future 或文件锁 |

## Spec 覆盖矩阵

### SubAgent

| Spec | 设计归属 |
|------|----------|
| F1-F3 | AgentTool、LaunchRequest、Fork/定义式过滤 |
| F4-F8 | Definition、parser、Catalog |
| F9-F11 | Agent RunResult、run_to_completion、独立 Runtime/Registry/Ledger |
| F12-F13 | PermissionScope、ScopedRuleStore、ApprovalBroker |
| F14-F19 | TaskManager、BackgroundTask、所有权切换、通知泵 |
| F20-F21 | Job 工具命名与 Team 工具边界 |
| F22-F25 | fork.py、Identity 与三层嵌套拦截 |
| F26-F31 | RegistryPolicy、RegistryView、延迟工具过滤 |
| F32-F33 | 内置 Definition 与 SkillExecutor 收敛 |

### Worktree

| Spec | 设计归属 |
|------|----------|
| F1 | slug.py |
| F2-F6a | models、manifest、GitRunner、WorktreeManager |
| F7-F10 | setup.py 三步设置；F8 明确跳过 Git hooks |
| F11-F15 | Manager enter/exit/remove/cleanup、changes.py |
| F16-F19 | tools.workspace、六个核心工具、ToolExecutor |
| F20-F23 | Definition.isolation、WorktreeEnvironmentPreparer、Job runner |
| F24-F29 | WorktreeCommands、handler、CommandUIAdapter |
| F30-F32 | WorktreeSessionStore、SessionService active workspace |
| F33-F35 | stale sweep、bootstrap task、gitignore warning |

### Agent Team

| Spec | 设计归属 |
|------|----------|
| F1-F10 | 独立 lead_agent_id、纯 teammate members、TeamManager、config.lock 原子更新 |
| F11-F19c | Backend Protocol、检测器、三种 Backend、worker CLI |
| F20-F25 | TeamCreate/Delete、AgentTool TeamSpawner 分流、spawn 前预注册 |
| F26-F30 | SharedTaskStore 与四个 Task Tool |
| F31-F34 | SendMessage、Box、Message protocol |
| F35-F38 | AgentNameRegistry |
| F39-F40 | teammate system prompt、TeamContext |
| F41-F44 | mailbox 注入、Lead mail pump、shutdown/plan 响应 |
| F45-F47 | idle、in-process resume、Pane wake |
| F48-F51 | 结构化 Plan 审批循环 |
| F52-F55 | Coordinator 开关、精确四工具 RegistryPolicy、prompt/status |
| F56-F58 | 退出 Coordinator 后普通 Lead Bash merge 与 abort 流程 |
| F59-F62 | TeamCommands 与 `/team` handler |
| F63-F66 | Team 恢复、session 持久化、删除顺序 |

覆盖结论：已批准 Spec 的所有功能需求都有明确组件与接口归属，没有留给 task.md 才决定的架构缺口。

## 测试设计

### 单元测试

- parser/catalog 优先级、错误降级与 Provider 失败；
- RegistryView 过滤、Fork schema 保留与 ToolSearch 二次过滤；
- PermissionScope/临时 Ledger 隔离、四种审批结果；
- Job 状态机、超时转后台、取消、resume 与一次通知；
- slug、manifest 身份、Git 命令失败、变更检测；
- ExecutionPathContext 的相对/绝对/`..`/symlink/readonly target；
- Team sanitize、成员状态、Backend 检测、Task 双向依赖；
- config/tasks/mailbox 跨进程并发写、5 秒 timeout、10 秒 stale lock、广播与 request_id；
- Plan approve/reject 和 Coordinator 工具过滤。

### 集成测试

- 定义式 SubAgent 前台完成与后台通知；
- Fork 命中 prompt prefix 且无法嵌套；
- Skill fork 走 Launcher；
- Worktree SubAgent 修改不污染主目录，取消后清理或保留；
- in-process Team 创建、任务、消息、idle、续派；
- session 恢复与 Worktree session 恢复；
- ApplicationRuntime shutdown 取消所有后台执行。

### 端到端测试

- tmux 启动 ArkCode，真实触发 SubAgent + Worktree；
- tmux Team 创建并 spawn pane teammate，观察 mailbox/wake/idle；
- in-process fallback 完整协作；
- Coordinator Mode 下验证工具精确等于 Agent/SendMessage/JobStop/TeamDelete,Bash merge 被拒绝；重启普通模式后 merge 可用。

所有阶段完成后统一运行：

```bash
python -m compileall src/Arkcode
ruff check src tests
mypy src/Arkcode
pytest
```

## 实施阶段边界

### 阶段 A：SubAgent

完成统一运行时、定义系统、权限作用域、JobManager、编排工具、通知与 Skill fork。阶段结束时不依赖 Worktree 或 Team，也必须保持全部既有测试通过。

### 阶段 B：Worktree

完成显式 cwd、WorktreeManager、SubAgent isolation、后台清理与 `/worktree`。阶段结束时 Team 尚未出现，但 WorktreeEnvironmentPreparer 已是可复用接口。

### 阶段 C：Agent Team

完成 Team 数据、Mailbox、任务板、Backend、worker、Plan 审批、Coordinator、命令与端到端收敛。仅这一阶段引入 Pane 子进程和长期 teammate。

task.md 将严格按 A → B → C 拆解；任何跨阶段并行只允许测试或互不依赖的叶子模块，不能在 SubAgent/Worktree 公共接口未稳定前实现 Team。
