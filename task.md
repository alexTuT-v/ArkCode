# SubAgent、Worktree 与 Agent Team Unified Tasks

> 输入：已批准的 `spec_sub_agent.md`、`spec_worktree.md`、`spec_agent_team.md` 与 `plan.md`。在本文件和后续 `checklist.md` 获得批准前，禁止编写实现代码。

## 全局执行规则

- 实现顺序固定为阶段 A SubAgent → 阶段 B Worktree → 阶段 C Agent Team。
- 每个任务的每个 checkbox 是一个 2-5 分钟动作；红测必须先失败，最小实现后再通过。
- 每个任务只修改列出的文件；发现接口不够时先修订 `plan.md` 和本文件并重新审批。
- 使用 `python3.12`/项目虚拟环境；统一验证入口为 `pytest`、`ruff check src tests`、`mypy src/Arkcode`。
- 不实现 Git hooks 设置；不读取或修改 `core.hooksPath`。
- 主进程和 in-process Agent 禁止 `os.chdir`；Pane worker 仅启动时允许一次。
- 文档生成阶段不提交。进入开发阶段后，每个任务验证通过可形成一个提交；若用户明确要求不提交则保留工作区改动。

## 文件清单

### 阶段 A：SubAgent

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/Arkcode/agents/identity.py` | `AgentIdentity` 与调用身份 ContextVar |
| 修改 | `src/Arkcode/agents/agent.py` | 可配置轮数、追加式 instructions、`run_to_completion` |
| 修改 | `src/Arkcode/agents/events.py` | 运行终态与结果事件 |
| 修改 | `src/Arkcode/agents/runtime.py` | `ReminderInbox` 与每 Agent 状态 |
| 修改 | `src/Arkcode/agents/execution.py` | Registry/权限/审批上下文接入 |
| 修改 | `src/Arkcode/tools/registry.py` | RegistryView、过滤、长运行超时策略 |
| 新建 | `src/Arkcode/subagents/__init__.py` | SubAgent 公共导出 |
| 新建 | `src/Arkcode/subagents/models.py` | Definition、Job、Launch、Run 模型 |
| 新建 | `src/Arkcode/subagents/parser.py` | Agent Markdown/frontmatter 解析 |
| 新建 | `src/Arkcode/subagents/catalog.py` | project/user/builtin 加载与覆盖 |
| 新建 | `src/Arkcode/subagents/filter.py` | RegistryPolicy 与按身份过滤 |
| 新建 | `src/Arkcode/subagents/fork.py` | Fork 消息与嵌套拦截 |
| 新建 | `src/Arkcode/subagents/approvals.py` | ApprovalBroker |
| 新建 | `src/Arkcode/subagents/manager.py` | TaskManager/BackgroundTask 生命周期 |
| 新建 | `src/Arkcode/subagents/launcher.py` | 定义式/Fork/Skill fork 统一构造 |
| 新建 | `src/Arkcode/subagents/notification.py` | `<task-notification>` 格式化 |
| 新建 | `src/Arkcode/subagents/tools.py` | Agent 与 Job 工具 |
| 新建 | `src/Arkcode/subagents/builtins/general-purpose.md` | 通用内置角色 |
| 新建 | `src/Arkcode/subagents/builtins/explore.md` | 只读探索角色 |
| 新建 | `src/Arkcode/subagents/builtins/plan.md` | 只读规划角色 |
| 修改 | `src/Arkcode/permissions/engine.py` | 子权限引擎与裁决顺序 |
| 新建 | `src/Arkcode/permissions/scope.py` | PermissionScope、Ledger、ScopedRuleStore |
| 修改 | `src/Arkcode/permissions/settings.py` | 作用域规则兼容存储 |
| 修改 | `src/Arkcode/permissions/types.py` | dontAsk 与审批 Outcome |
| 修改 | `src/Arkcode/skills/executor.py` | Skill fork 复用 Launcher |
| 修改 | `src/Arkcode/application/bootstrap.py` | Catalog/TaskManager/工具装配 |
| 修改 | `src/Arkcode/application/runtime.py` | 后台任务所有权与 shutdown |
| 修改 | `src/Arkcode/application/session.py` | ParentContext 与提醒接入 |
| 修改 | `src/Arkcode/tui/app.py` | ESC 转后台与消费者生命周期 |
| 修改 | `src/Arkcode/tui/controllers/approvals.py` | SubAgent 审批转发 |
| 新建 | `src/Arkcode/tui/tasks.py` | Job 完成通知消费 |
| 新建 | `tests/subagents/test_models.py` | 模型与 parser 测试 |
| 新建 | `tests/subagents/test_catalog.py` | Catalog 优先级测试 |
| 新建 | `tests/subagents/test_filter.py` | 工具过滤测试 |
| 新建 | `tests/subagents/test_manager.py` | Job 状态机测试 |
| 新建 | `tests/subagents/test_launcher.py` | 启动/Fork/权限测试 |
| 新建 | `tests/subagents/test_tools.py` | Agent/Job 工具测试 |

### 阶段 B：Worktree

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/Arkcode/tools/workspace.py` | ExecutionPathContext 与路径解析 |
| 修改 | `src/Arkcode/tools/builtins/bash.py` | 显式 cwd 与 sandbox root |
| 修改 | `src/Arkcode/tools/builtins/read_file.py` | containment 读路径 |
| 修改 | `src/Arkcode/tools/builtins/write_file.py` | containment 写路径 |
| 修改 | `src/Arkcode/tools/builtins/edit_file.py` | containment 编辑路径 |
| 修改 | `src/Arkcode/tools/builtins/glob.py` | workspace 内 glob |
| 修改 | `src/Arkcode/tools/builtins/grep.py` | workspace 内 grep |
| 新建 | `src/Arkcode/worktrees/__init__.py` | Worktree 公共导出 |
| 新建 | `src/Arkcode/worktrees/models.py` | Worktree/Manifest/Session/Report |
| 新建 | `src/Arkcode/worktrees/slug.py` | slug 验证与 flatten |
| 新建 | `src/Arkcode/worktrees/git.py` | 可取消 GitRunner |
| 新建 | `src/Arkcode/worktrees/manifest.py` | manifest 原子存储/身份校验 |
| 新建 | `src/Arkcode/worktrees/changes.py` | 变更与新增 commit 检测 |
| 新建 | `src/Arkcode/worktrees/setup.py` | 三步 best-effort 创建后设置 |
| 新建 | `src/Arkcode/worktrees/session.py` | worktree session 存储 |
| 新建 | `src/Arkcode/worktrees/manager.py` | 生命周期与 stale sweep |
| 新建 | `src/Arkcode/worktrees/integration.py` | SubAgent Worktree preparer |
| 修改 | `src/Arkcode/subagents/models.py` | Definition isolation 字段接入 |
| 修改 | `src/Arkcode/subagents/manager.py` | preparing/cleanup 所有权 |
| 修改 | `src/Arkcode/commands/ports.py` | WorktreeCommands 协议 |
| 新建 | `src/Arkcode/commands/handlers/worktree.py` | `/worktree` 命令 |
| 修改 | `src/Arkcode/commands/builtins.py` | 注册 worktree 命令 |
| 修改 | `src/Arkcode/tui/adapters/command_ui.py` | Worktree 命令适配 |
| 新建 | `tests/tools/test_workspace_context.py` | cwd/containment/symlink 测试 |
| 新建 | `tests/worktrees/test_slug.py` | slug 测试 |
| 新建 | `tests/worktrees/test_manifest.py` | manifest 恢复测试 |
| 新建 | `tests/worktrees/test_manager.py` | 生命周期测试 |
| 新建 | `tests/worktrees/test_setup.py` | 三步设置和 hooks 跳过测试 |
| 新建 | `tests/integration/test_subagent_worktree.py` | SubAgent+Worktree 集成 |

### 阶段 C：Agent Team

| 操作 | 文件 | 职责 |
|---|---|---|
| 新建 | `src/Arkcode/teams/__init__.py` | Team 公共导出 |
| 新建 | `src/Arkcode/teams/models.py` | Team/Teammate/Backend/Message/Task 模型 |
| 新建 | `src/Arkcode/teams/storage.py` | O_EXCL FileLock 与原子 JSON 更新 |
| 新建 | `src/Arkcode/teams/manager.py` | Team 生命周期/恢复/删除 |
| 新建 | `src/Arkcode/teams/registry.py` | AgentNameRegistry |
| 新建 | `src/Arkcode/teams/mailbox.py` | mailbox 读写/广播 |
| 新建 | `src/Arkcode/teams/protocol.py` | 结构化消息协议 |
| 新建 | `src/Arkcode/teams/shared_tasks.py` | 共享任务板 |
| 新建 | `src/Arkcode/teams/coordinator.py` | 开关、四工具白名单、prompt |
| 新建 | `src/Arkcode/teams/spawner.py` | Team spawn 顺序/回滚 |
| 新建 | `src/Arkcode/teams/worker.py` | Pane worker 自治循环 |
| 新建 | `src/Arkcode/teams/tools.py` | Team/Task/SendMessage 工具 |
| 新建 | `src/Arkcode/teams/backends/base.py` | Backend Protocol |
| 新建 | `src/Arkcode/teams/backends/detect.py` | 后端检测 |
| 新建 | `src/Arkcode/teams/backends/inprocess.py` | in-process 后端 |
| 新建 | `src/Arkcode/teams/backends/tmux.py` | tmux 后端 |
| 新建 | `src/Arkcode/teams/backends/iterm2.py` | iTerm2 后端 |
| 修改 | `src/Arkcode/application/cli.py` | `--team-member` 路由 |
| 修改 | `src/Arkcode/application/bootstrap.py` | Team composition |
| 修改 | `src/Arkcode/application/runtime.py` | Team 生命周期 shutdown |
| 修改 | `src/Arkcode/config/models.py` | Coordinator feature 配置 |
| 修改 | `src/Arkcode/commands/ports.py` | TeamCommands 协议 |
| 新建 | `src/Arkcode/commands/handlers/team.py` | `/team` 命令 |
| 修改 | `src/Arkcode/tui/tasks.py` | Lead mailbox 消费/唤醒 |
| 修改 | `src/Arkcode/tui/widgets/status_bar.py` | Coordinator 状态 |
| 新建 | `tests/teams/test_storage.py` | 文件锁/原子存储测试 |
| 新建 | `tests/teams/test_manager.py` | Team/Lead/members 测试 |
| 新建 | `tests/teams/test_mailbox.py` | mailbox/广播测试 |
| 新建 | `tests/teams/test_shared_tasks.py` | 任务板测试 |
| 新建 | `tests/teams/test_backends.py` | 检测/Backend 测试 |
| 新建 | `tests/teams/test_spawner.py` | spawn 顺序/失败回滚测试 |
| 新建 | `tests/teams/test_worker.py` | Pane 单次 chdir/自治循环测试 |
| 新建 | `tests/teams/test_coordinator.py` | Coordinator 精确白名单测试 |
| 新建 | `tests/integration/test_team_inprocess.py` | in-process Team 集成 |
| 新建 | `tests/integration/test_team_tmux.py` | tmux Team 集成（条件执行） |

## 阶段 A：SubAgent

### T1：AgentIdentity 与身份上下文

**文件：** `src/Arkcode/agents/identity.py`、`tests/subagents/test_models.py`
**依赖：** 无
**接口：** 产出 `AgentIdentity`、`current_identity()`、`identity_scope(identity)`。

- [ ] 写测试断言 main/defined/fork/skill/teammate 五类 source 可构造且 ContextVar 嵌套后恢复。
- [ ] 运行 `pytest tests/subagents/test_models.py -k identity -v`，确认因模块缺失失败。
- [ ] 实现 frozen/slots `AgentIdentity` 与 ContextVar scope。
- [ ] 重跑同一命令，期望通过。

**验证：** `pytest tests/subagents/test_models.py -k identity -v`。

### T2：ReminderInbox 与独立 Runtime

**文件：** `src/Arkcode/agents/runtime.py`、`tests/agents/test_agent_runtime.py`
**依赖：** T1
**接口：** 产出 `ReminderInbox.append/drain`，`SessionRuntime` 持有独立 inbox。

- [ ] 写两个 Runtime 的隔离测试和 drain 清空测试。
- [ ] 运行目标测试确认失败。
- [ ] 实现 FIFO inbox 并接入 SessionRuntime default factory。
- [ ] 重跑测试确认两个 Agent 不共享提醒。

**验证：** `pytest tests/agents/test_agent_runtime.py -k reminder -v`。

### T3：RunStatus、RunResult 与可配置 Agent

**文件：** `src/Arkcode/subagents/models.py`、`src/Arkcode/agents/events.py`、`src/Arkcode/agents/agent.py`、`tests/agents/test_agent.py`
**依赖：** T1、T2
**接口：** 产出 `RunStatus`、`RunResult`、`Agent.run_to_completion()`；Agent 构造接收 `instructions_content/max_turns/identity`。

- [ ] 写测试覆盖基础 system prompt 保留、instructions 追加、max_turns 返回 `limit_reached`。
- [ ] 运行测试确认当前 Agent 不支持这些参数。
- [ ] 把现有 loop 上限改为实例字段，并实现消费同一事件流的 `run_to_completion`。
- [ ] 重跑测试，确认 completed 与 limit_reached 互斥。

**验证：** `pytest tests/agents/test_agent.py -k 'instructions or completion or max_turns' -v`。

### T4：RegistryPolicy 与 RegistryView

**文件：** `src/Arkcode/subagents/filter.py`、`src/Arkcode/tools/registry.py`、`tests/subagents/test_filter.py`
**依赖：** T1
**接口：** 产出 `RegistryPolicy`、`RegistryView.from_parent()`。

- [ ] 写测试覆盖 allowed/denied/global deny、独立 discovered、Fork 保留 Agent schema。
- [ ] 运行目标测试确认失败。
- [ ] 实现 RegistryView，并让 search/find/definitions/execute 都再次应用 policy。
- [ ] 重跑测试，确认延迟工具不能绕过过滤。

**验证：** `pytest tests/subagents/test_filter.py -v`。

### T5：Definition parser 与名称约束

**文件：** `src/Arkcode/subagents/models.py`、`src/Arkcode/subagents/parser.py`、`tests/subagents/test_models.py`
**依赖：** T3
**接口：** 产出 `Definition`、`Source`、`parse_definition(path)`。

- [ ] 写合法 `explore-v2` 与非法 `Explore/foo_bar/foo bar` 测试。
- [ ] 写 frontmatter 字段、正文 `instructions_content`、isolation/plan_mode_required 测试。
- [ ] 实现严格 YAML/Pydantic 解析和 `^[a-z0-9-]+$` 校验。
- [ ] 运行 parser 测试，期望全部通过。

**验证：** `pytest tests/subagents/test_models.py -k definition -v`。

### T6：Catalog 与三个内置角色

**文件：** `src/Arkcode/subagents/catalog.py`、`src/Arkcode/subagents/builtins/general-purpose.md`、`src/Arkcode/subagents/builtins/explore.md`、`src/Arkcode/subagents/builtins/plan.md`、`tests/subagents/test_catalog.py`
**依赖：** T5
**接口：** 产出 `Catalog.load/reload/resolve/list`。

- [ ] 写 builtin → user → project 覆盖、用户坏文件 warning、builtin 坏文件 fail-fast 测试。
- [ ] 运行测试确认 Catalog 缺失。
- [ ] 实现 `importlib.resources` 内置加载和三层覆盖；plugin 层返回空。
- [ ] 重跑测试并断言三个内置名均为小写。

**验证：** `pytest tests/subagents/test_catalog.py -v`。

### T7：权限作用域与临时 Ledger

**文件：** `src/Arkcode/permissions/scope.py`、`src/Arkcode/permissions/engine.py`、`src/Arkcode/permissions/settings.py`、`src/Arkcode/permissions/types.py`、`tests/permissions/test_permission_core.py`
**依赖：** T1
**接口：** 产出 `PermissionScope`、`PermissionLedger`、`ScopedRuleStore`、`Engine.child()`。

- [ ] 写系统 deny 优先、global/main/type/instance 匹配和 Ledger 隔离测试。
- [ ] 写 dontAsk 不绕过系统 deny、ALLOW_AGENT 只写当前 Ledger 测试。
- [ ] 实现作用域匹配、旧 YAML 兼容读取和新对象规则保存。
- [ ] 运行权限测试确认通过。

**验证：** `pytest tests/permissions/test_permission_core.py -k 'scope or ledger or dont' -v`。

### T8：ApprovalBroker

**文件：** `src/Arkcode/subagents/approvals.py`、`src/Arkcode/agents/execution.py`、`src/Arkcode/tui/controllers/approvals.py`、`tests/subagents/test_launcher.py`
**依赖：** T7
**接口：** 产出 `ApprovalRequest`、`ApprovalBroker.submit/next/cancel_agent`。

- [ ] 写并发两个 Agent 审批只恢复对应 Future 的测试。
- [ ] 运行测试确认失败。
- [ ] 实现 Queue/Future broker，并在 ToolExecutor Ask 分支按身份路由。
- [ ] 重跑测试，覆盖取消 Agent 时 pending Future 被拒绝。

**验证：** `pytest tests/subagents/test_launcher.py -k approval -v`。

### T9：TaskManager 基础状态机

**文件：** `src/Arkcode/subagents/manager.py`、`tests/subagents/test_manager.py`
**依赖：** T3
**接口：** 产出 `TaskManager.launch/get/list/stop/subscribe_done/shutdown`。

- [ ] 写 preparing/running/completed/failed/cancelled/limit_reached 状态测试。
- [ ] 写普通 Exception 转 failed、CancelledError 转 cancelled、done 仅一次测试。
- [ ] 实现 BackgroundTask 字典、runner、CAS 终态和 done queue。
- [ ] 运行 manager 状态测试。

**验证：** `pytest tests/subagents/test_manager.py -k 'status or done or stop' -v`。

### T10：前台转后台与 adopt

**文件：** `src/Arkcode/subagents/manager.py`、`src/Arkcode/tools/registry.py`、`src/Arkcode/tui/app.py`、`tests/subagents/test_manager.py`
**依赖：** T9
**接口：** 产出 `wait_foreground/move_to_background/adopt_running`，保持同一 asyncio task。

- [ ] 写模拟 120 秒超时和 ESC 切换时 task identity/Conversation 不变测试。
- [ ] 运行测试确认失败。
- [ ] 使用 `asyncio.shield` 和所有权标志实现切换；AgentTool 禁用 Registry 默认 30 秒超时。
- [ ] 重跑测试，确认切换不取消底层执行。

**验证：** `pytest tests/subagents/test_manager.py -k 'foreground or background or adopt' -v`。

### T11：Fork 消息与三层嵌套阻断

**文件：** `src/Arkcode/subagents/fork.py`、`src/Arkcode/subagents/filter.py`、`tests/subagents/test_launcher.py`
**依赖：** T4
**接口：** 产出 `build_forked_messages()` 与 `assert_can_launch_agent()`。

- [ ] 写父历史前缀不变、未完成 tool call 补 result、boilerplate 追加测试。
- [ ] 写 Identity/Fork ancestry/boilerplate 三种拒绝嵌套测试。
- [ ] 实现深拷贝和防线，Fork RegistryView 仅保留 Agent schema。
- [ ] 运行 Fork 测试确认通过。

**验证：** `pytest tests/subagents/test_launcher.py -k fork -v`。

### T12：SubAgentLauncher

**文件：** `src/Arkcode/subagents/launcher.py`、`src/Arkcode/subagents/models.py`、`tests/subagents/test_launcher.py`
**依赖：** T3、T4、T6、T7、T8、T9、T11
**接口：** 产出 `LaunchRequest`、`LaunchOutcome`、`SubAgentLauncher.launch/launch_fork`。

- [ ] 写定义式从空 Conversation 启动、Fork 继承历史、Provider 失败不回退测试。
- [ ] 运行测试确认失败。
- [ ] 装配 Provider/RegistryView/Engine.child/Runtime/Conversation/Identity/TaskManager。
- [ ] 重跑测试，断言基础 prompt 保留且角色 instructions 追加。

**验证：** `pytest tests/subagents/test_launcher.py -v`。

### T13：Agent 与 Job 工具

**文件：** `src/Arkcode/subagents/tools.py`、`tests/subagents/test_tools.py`
**依赖：** T10、T12
**接口：** 产出 `AgentTool`、`JobListTool`、`JobGetTool`、`JobStopTool`、`JobSendTool`。

- [ ] 写稳定 Agent schema、未知类型、显式后台、Fork 强制后台测试。
- [ ] 写 JobList/Get/Stop 与运行中 JobSend 拒绝测试。
- [ ] 实现五个 Tool 与 `job_id` 对外字段。
- [ ] 运行工具测试，确认没有模型可见 `TaskList/TaskGet/TaskStop`。

**验证：** `pytest tests/subagents/test_tools.py -v`。

### T14：JobSend resume 与上下文复用

**文件：** `src/Arkcode/subagents/manager.py`、`src/Arkcode/subagents/tools.py`、`tests/subagents/test_manager.py`
**依赖：** T13
**接口：** 产出 `TaskManager.resume(agent_ref, message)`。

- [ ] 写完成实例按 name 续派、复用 Agent/Conversation、生成新 job_id 测试。
- [ ] 运行测试确认失败。
- [ ] 实现弱 name registry 解析与非重入校验。
- [ ] 重跑测试确认旧 job 保留、新 job 独立终态。

**验证：** `pytest tests/subagents/test_manager.py -k resume -v`。

### T15：`<task-notification>` 消费

**文件：** `src/Arkcode/subagents/notification.py`、`src/Arkcode/tui/tasks.py`、`src/Arkcode/application/runtime.py`、`tests/subagents/test_tools.py`
**依赖：** T2、T9
**接口：** 产出 `format_task_notification()` 与 `consume_job_notifications()`。

- [ ] 写 completed/failed/cancelled/limit_reached 格式测试。
- [ ] 实现 done queue 消费并写主 ReminderInbox。
- [ ] 断言标签只允许 `<task-notification>`，内容使用 Job/job_id 术语。
- [ ] 运行通知测试。

**验证：** `pytest tests/subagents/test_tools.py -k notification -v`。

### T16：Skill fork 收敛与应用装配

**文件：** `src/Arkcode/skills/executor.py`、`src/Arkcode/application/bootstrap.py`、`src/Arkcode/application/runtime.py`、`src/Arkcode/application/session.py`、`tests/skills/test_skills_executor.py`
**依赖：** T12、T15
**接口：** Skill fork 调用 `SubAgentLauncher.launch_fork`；Runtime 持有 Catalog/TaskManager/ApprovalBroker。

- [ ] 写 Skill fork 不再自行构造 Agent 的集成测试。
- [ ] 修改 composition root 注册 Agent/Job 工具和后台消费者。
- [ ] 实现 shutdown 取消任务、Broker Future 和消费者。
- [ ] 运行 Skills、Application 和 SubAgent 全部测试。

**验证：** `pytest tests/skills tests/application tests/subagents -q`。

### T17：阶段 A 回归门

**文件：** 阶段 A 全部文件
**依赖：** T1-T16

- [ ] 运行 `python3 -m compileall src/Arkcode`。
- [ ] 运行 `ruff check src tests`。
- [ ] 运行 `mypy src/Arkcode`。
- [ ] 运行 `pytest tests/agents tests/subagents tests/skills tests/application tests/tools -q`。

**验证：** 四条命令均退出 0；失败时停在阶段 A 修复，不进入 Worktree。

## 阶段 B：Worktree

### T18：ExecutionPathContext

**文件：** `src/Arkcode/tools/workspace.py`、`tests/tools/test_workspace_context.py`
**依赖：** T17
**接口：** 产出 `ExecutionPathContext/current_workspace/workspace_scope/resolve_path`。

- [ ] 写默认 workspace、ContextVar 并发隔离和嵌套恢复测试。
- [ ] 写绝对路径、`..`、symlink escape、readonly target 的 read/write 测试。
- [ ] 实现 realpath containment 和 Access.READ/WRITE。
- [ ] 运行 workspace 测试。

**验证：** `pytest tests/tools/test_workspace_context.py -v`。

### T19：六个核心工具显式 cwd

**文件：** `src/Arkcode/tools/builtins/bash.py`、`src/Arkcode/tools/builtins/read_file.py`、`src/Arkcode/tools/builtins/write_file.py`、`src/Arkcode/tools/builtins/edit_file.py`、`src/Arkcode/tools/builtins/glob.py`、`src/Arkcode/tools/builtins/grep.py`、`tests/tools/test_workspace_context.py`
**依赖：** T18

- [ ] 为每个工具写在两个并发 workspace 中访问同名文件的测试。
- [ ] 把文件工具路径统一改用 `resolve_path`，Bash 显式传 `cwd` 和 workspace sandbox root。
- [ ] 加 monkeypatch 测试断言主进程从未调用 `os.chdir`。
- [ ] 运行 workspace 与既有 tools 测试。

**验证：** `pytest tests/tools/test_workspace_context.py tests/tools -q`。

### T20：Worktree 模型与 slug

**文件：** `src/Arkcode/worktrees/models.py`、`src/Arkcode/worktrees/slug.py`、`tests/worktrees/test_slug.py`
**依赖：** T17
**接口：** 产出 `Worktree/WorktreeManifest/WorktreeSession` 与 `validate_slug/flatten_slug`。

- [ ] 写 `feature/a` 通过及 traversal/空段/超长拒绝测试。
- [ ] 实现 `[a-zA-Z0-9._-]` 分段规则和 `/ → +` flatten。
- [ ] 写 manifest 字段序列化测试。
- [ ] 运行 slug 测试。

**验证：** `pytest tests/worktrees/test_slug.py -v`。

### T21：GitRunner 与变更检测

**文件：** `src/Arkcode/worktrees/git.py`、`src/Arkcode/worktrees/changes.py`、`tests/worktrees/test_manager.py`
**依赖：** T19、T20
**接口：** 产出 `GitRunner.run()`、`has_worktree_changes()`。

- [ ] 写显式 cwd/env、命令失败、取消终止子进程测试。
- [ ] 写 status 非空、base..HEAD 新 commit、git 失败 fail-closed 测试。
- [ ] 实现异步 subprocess 与两段变更检查。
- [ ] 运行目标测试。

**验证：** `pytest tests/worktrees/test_manager.py -k 'git or changes' -v`。

### T22：Manifest 原子存储与身份校验

**文件：** `src/Arkcode/worktrees/manifest.py`、`tests/worktrees/test_manifest.py`
**依赖：** T20、T21
**接口：** 产出 `ManifestStore.save/load/validate/remove`。

- [ ] 写 schema/repo_id/path/branch/base_commit/owner 不匹配拒绝测试。
- [ ] 写唯一 tmp、fsync、os.replace 行为测试。
- [ ] 实现 fail-closed load/validate。
- [ ] 运行 manifest 测试。

**验证：** `pytest tests/worktrees/test_manifest.py -v`。

### T23：WorktreeManager 创建与快速恢复

**文件：** `src/Arkcode/worktrees/manager.py`、`tests/worktrees/test_manager.py`
**依赖：** T21、T22
**接口：** 产出 `WorktreeManager.open/create/list`。

- [ ] 写 reservation 阻止同名并发创建测试。
- [ ] 写新建调用 git worktree add、合法 manifest 快速恢复不调用 git 测试。
- [ ] 实现短 asyncio.Lock reservation 与失败身份化清理。
- [ ] 运行 create/recovery 测试。

**验证：** `pytest tests/worktrees/test_manager.py -k 'create or recover or reservation' -v`。

### T24：创建后三步设置并跳过 hooks

**文件：** `src/Arkcode/worktrees/setup.py`、`tests/worktrees/test_setup.py`
**依赖：** T23
**接口：** 产出 `perform_post_creation_setup()`。

- [ ] 写配置复制、readonly shared dirs、`.worktreeinclude` ignored file 测试。
- [ ] 写 `shared_writable_dirs` 非空失败与无只读保障跳过测试。
- [ ] 实现三个独立 best-effort 步骤。
- [ ] monkeypatch git runner，断言从不调用 `.husky` 探测或 `core.hooksPath`。

**验证：** `pytest tests/worktrees/test_setup.py -v`。

### T25：enter/exit/remove/auto_cleanup

**文件：** `src/Arkcode/worktrees/manager.py`、`src/Arkcode/worktrees/session.py`、`tests/worktrees/test_manager.py`
**依赖：** T23、T24

- [ ] 写 session 原子保存/损坏清空测试。
- [ ] 写有变更拒绝 remove、discard 删除、auto_cleanup 保留报告测试。
- [ ] 实现 enter/exit/remove/auto_cleanup，所有 git 命令显式 cwd。
- [ ] 断言每个入口前后 `Path.cwd()` 不变。

**验证：** `pytest tests/worktrees/test_manager.py -k 'enter or exit or remove or cleanup or session' -v`。

### T26：SubAgent WorktreeEnvironmentPreparer

**文件：** `src/Arkcode/worktrees/integration.py`、`src/Arkcode/subagents/manager.py`、`src/Arkcode/subagents/models.py`、`tests/integration/test_subagent_worktree.py`
**依赖：** T15、T25

- [ ] 写 `isolation:worktree + background` 的 preparing→running→终态测试。
- [ ] 写取消/prepare 失败/有变更保留均只通知一次测试。
- [ ] 实现 create→workspace_scope→run→auto_cleanup finally 所有权链。
- [ ] 运行集成测试并断言主目录未被修改。

**验证：** `pytest tests/integration/test_subagent_worktree.py -v`。

### T27：Worktree slash commands

**文件：** `src/Arkcode/commands/ports.py`、`src/Arkcode/commands/handlers/worktree.py`、`src/Arkcode/commands/builtins.py`、`src/Arkcode/tui/adapters/command_ui.py`、`tests/commands/test_builtins.py`
**依赖：** T25

- [ ] 写 create/list/enter/exit/remove 参数与 `--discard` 测试。
- [ ] 实现 WorktreeCommands 协议和 handler。
- [ ] 接入 CommandUIAdapter，确保命令不写对话历史。
- [ ] 运行命令测试。

**验证：** `pytest tests/commands/test_builtins.py -k worktree -v`。

### T28：stale sweep 与应用装配

**文件：** `src/Arkcode/worktrees/manager.py`、`src/Arkcode/application/bootstrap.py`、`src/Arkcode/application/runtime.py`、`tests/worktrees/test_manager.py`
**依赖：** T26、T27

- [ ] 写只匹配 `agent-a[0-9a-f]{7}`、时间 cutoff、变更 fail-closed 测试。
- [ ] 实现 bootstrap 打开 Manager、恢复 session、后台 sweep 和 shutdown。
- [ ] `.gitignore` 缺目标条目时只 warning，不自动修改。
- [ ] 运行 Worktree/Application 测试。

**验证：** `pytest tests/worktrees tests/application -q`。

### T29：阶段 B 回归门

**文件：** 阶段 A+B 全部文件
**依赖：** T18-T28

- [ ] 运行 `python3 -m compileall src/Arkcode`。
- [ ] 运行 `ruff check src tests` 和 `mypy src/Arkcode`。
- [ ] 运行 `pytest tests/subagents tests/worktrees tests/tools tests/commands tests/integration/test_subagent_worktree.py -q`。
- [ ] 运行 `pytest -q` 确认既有功能无回归。

**验证：** 四组命令退出 0 后才进入 Agent Team。

## 阶段 C：Agent Team

### T30：统一 FileLock 与原子 JSON 更新

**文件：** `src/Arkcode/teams/storage.py`、`tests/teams/test_storage.py`
**依赖：** T29
**接口：** 产出 `FileLock`、`atomic_update_json`。

- [ ] 写 O_EXCL 获取、5ms→80ms 退避、5 秒 timeout、10 秒 stale 测试。
- [ ] 写两个独立进程 read-modify-write 无丢失测试。
- [ ] 实现唯一 tmp + flush/fsync/os.replace + finally unlink。
- [ ] 运行 storage 测试。

**验证：** `pytest tests/teams/test_storage.py -v`。

### T31：Team/Teammate 模型与 Lead 分离

**文件：** `src/Arkcode/teams/models.py`、`tests/teams/test_manager.py`
**依赖：** T30

- [ ] 写 Team JSON 包含独立 lead_agent_id 且初始 members=[] 测试。
- [ ] 写 members 只接受 teammate、Lead 不参与计数/遍历测试。
- [ ] 实现 Team/TeammateInfo/BackendType 模型和序列化。
- [ ] 运行模型测试。

**验证：** `pytest tests/teams/test_manager.py -k models -v`。

### T32：TeamManager create/reload/member 更新

**文件：** `src/Arkcode/teams/manager.py`、`tests/teams/test_manager.py`
**依赖：** T31、T37

- [ ] 写 sanitize/同名后缀/backend 持久化/坏目录跳过测试。
- [ ] 写 `Team._lock → config.lock → reload → mutate → save` 并发测试。
- [ ] 实现 create/get/list/add/set_active/remove 和启动恢复。
- [ ] 运行 manager 测试。

**验证：** `pytest tests/teams/test_manager.py -k 'create or reload or member' -v`。

### T33：AgentNameRegistry 与消息协议

**文件：** `src/Arkcode/teams/registry.py`、`src/Arkcode/teams/protocol.py`、`tests/teams/test_mailbox.py`
**依赖：** T31

- [ ] 写 name↔id、后注册覆盖、unregister 测试。
- [ ] 写 Message text/结构化顶层字段、request_id/approve 校验测试。
- [ ] 实现线程安全 registry 和协议模型。
- [ ] 运行目标测试。

**验证：** `pytest tests/teams/test_mailbox.py -k 'registry or protocol' -v`。

### T34：Mailbox 与广播

**文件：** `src/Arkcode/teams/mailbox.py`、`tests/teams/test_mailbox.py`
**依赖：** T30、T31、T33

- [ ] 写 `<agent_id>.json.lock` 并发 10 写、mark_read、stale 恢复测试。
- [ ] 写 Lead 广播所有 members、teammate 广播其他 members+lead 测试。
- [ ] 实现 Box.write/read/mark_read/broadcast。
- [ ] 运行 mailbox 测试。

**验证：** `pytest tests/teams/test_mailbox.py -v`。

### T35：SharedTaskStore

**文件：** `src/Arkcode/teams/shared_tasks.py`、`tests/teams/test_shared_tasks.py`
**依赖：** T30、T31

- [ ] 写 create/get/list/update/status/is_ready 测试。
- [ ] 写 blocked_by/blocks 双向更新和并发无丢失测试。
- [ ] 实现 tasks.lock 临界区内完整 read-modify-write。
- [ ] 运行任务板测试。

**验证：** `pytest tests/teams/test_shared_tasks.py -v`。

### T36：Team/Task/SendMessage 工具

**文件：** `src/Arkcode/teams/tools.py`、`tests/teams/test_manager.py`、`tests/teams/test_mailbox.py`、`tests/teams/test_shared_tasks.py`
**依赖：** T32、T34、T35

- [ ] 写 TeamCreate/Delete、TaskCreate/Get/List/Update、SendMessage schema 测试。
- [ ] 写调用身份过滤和 plan/shutdown 消息方向约束测试。
- [ ] 实现工具并确保 Task* 仅 teammate、SendMessage 仅 Lead/teammate 可见。
- [ ] 运行三组工具测试。

**验证：** `pytest tests/teams/test_manager.py tests/teams/test_mailbox.py tests/teams/test_shared_tasks.py -q`。

### T37：Backend Protocol 与检测

**文件：** `src/Arkcode/teams/backends/base.py`、`src/Arkcode/teams/backends/detect.py`、`tests/teams/test_backends.py`
**依赖：** T31

- [ ] 写 TMUX→iTerm2+it2→PATH tmux→in-process 优先级测试。
- [ ] 定义 SpawnRequest/SpawnResult/Backend Protocol。
- [ ] 实现一次性缓存检测且 spawn 失败不静默回退。
- [ ] 运行 backend 检测测试。

**验证：** `pytest tests/teams/test_backends.py -k detect -v`。

### T38：InProcessBackend

**文件：** `src/Arkcode/teams/backends/inprocess.py`、`tests/teams/test_backends.py`
**依赖：** T17、T37

- [ ] 写 launch/wake no-op/kill 测试。
- [ ] 写 teammate 二次 team spawn 与 background SubAgent 被拒绝测试。
- [ ] 实现复用 SubAgentLauncher/TaskManager，使用 ExecutionPathContext。
- [ ] monkeypatch `os.chdir`，断言调用次数为 0。

**验证：** `pytest tests/teams/test_backends.py -k inprocess -v`。

### T39：TmuxBackend 与 Iterm2Backend

**文件：** `src/Arkcode/teams/backends/tmux.py`、`src/Arkcode/teams/backends/iterm2.py`、`tests/teams/test_backends.py`
**依赖：** T37

- [ ] 写命令 argv、pane_id 解析、wake/kill 和失败返回测试。
- [ ] 实现 tmux split/detached session 与 it2 split/send/close。
- [ ] 确认所有参数使用 exec argv，不把 initial prompt 放命令行。
- [ ] 运行 mock backend 测试。

**验证：** `pytest tests/teams/test_backends.py -k 'tmux or iterm' -v`。

### T40：Pane worker CLI 与单次 chdir

**文件：** `src/Arkcode/teams/worker.py`、`src/Arkcode/application/cli.py`、`tests/teams/test_worker.py`
**依赖：** T32、T34、T39

- [ ] 写参数缺失失败、无 TUI 构造、stdout 事件渲染测试。
- [ ] 写在任何 task/Agent 前执行一次 chdir，续派多轮仍只调用一次测试。
- [ ] 实现 mailbox/wake_event/2 秒轮询/run_to_completion/idle/shutdown 循环。
- [ ] 运行 worker 测试。

**验证：** `pytest tests/teams/test_worker.py -v`。

### T41：TeamSpawner spawn 前注册

**文件：** `src/Arkcode/teams/spawner.py`、`tests/teams/test_spawner.py`
**依赖：** T32、T33、T34、T37-T40

- [ ] 写 mock backend 在 spawn 入口读取 config 已看到 member/final agent_id 测试。
- [ ] 写 Pane prompt 预写 mailbox、spawn 后 pane_id 回写测试。
- [ ] 按 plan 固定顺序实现预生成→Worktree/session→预注册→spawn→回写。
- [ ] 写 spawn 失败移除 member/name 并清理本次资源测试。

**验证：** `pytest tests/teams/test_spawner.py -v`。

### T42：Teammate context、idle 与 resume

**文件：** `src/Arkcode/teams/spawner.py`、`src/Arkcode/agents/agent.py`、`src/Arkcode/teams/manager.py`、`tests/integration/test_team_inprocess.py`
**依赖：** T38、T41

- [ ] 写 teammate instructions 追加和 `<team-context>` 注入测试。
- [ ] 写 run 完成 set_active(False)+Lead idle mailbox 测试。
- [ ] 写 SendMessage 恢复 session Conversation、set_active(True) 测试。
- [ ] 实现 in-process Team 完整续派链并运行集成测试。

**验证：** `pytest tests/integration/test_team_inprocess.py -v`。

### T43：Plan 审批循环

**文件：** `src/Arkcode/teams/protocol.py`、`src/Arkcode/teams/worker.py`、`src/Arkcode/teams/tools.py`、`tests/teams/test_worker.py`
**依赖：** T36、T40、T42

- [ ] 写 plan teammate 初始 Mode.PLAN 和 request_id 非空测试。
- [ ] 写不匹配 response 保留、approve 切 DEFAULT、reject 保持 PLAN 测试。
- [ ] 实现 awaiting_plan_approval 无超时循环。
- [ ] 运行 plan approval 测试。

**验证：** `pytest tests/teams/test_worker.py -k plan -v`。

### T44：Coordinator 精确白名单

**文件：** `src/Arkcode/teams/coordinator.py`、`src/Arkcode/config/models.py`、`src/Arkcode/application/session.py`、`tests/teams/test_coordinator.py`
**依赖：** T4、T36

- [ ] 写 feature+env 双锁和状态标签测试。
- [ ] 写 allowed tools 精确等于 Agent/SendMessage/JobStop/TeamDelete 测试。
- [ ] 实现 RegistryView 过滤和纯调度 prompt。
- [ ] 写 read/write/Bash/TeamCreate/Task* 全部拒绝测试。

**验证：** `pytest tests/teams/test_coordinator.py -v`。

### T45：Lead mail pump 与自主唤醒

**文件：** `src/Arkcode/tui/tasks.py`、`src/Arkcode/tui/app.py`、`src/Arkcode/application/runtime.py`、`tests/tui/test_tui.py`
**依赖：** T34、T42、T44

- [ ] 写 mailbox→`<team-update>`→ReminderInbox 与 8000 字符边界测试。
- [ ] 写 idle 时 autonomous turn、streaming 时只追加 reminder 测试。
- [ ] 实现 lead_mail_event 的 set/clear 和消费者 shutdown。
- [ ] 运行 TUI Team 测试。

**验证：** `pytest tests/tui/test_tui.py -k team -v`。

### T46：Team slash commands 与状态栏

**文件：** `src/Arkcode/commands/ports.py`、`src/Arkcode/commands/handlers/team.py`、`src/Arkcode/commands/builtins.py`、`src/Arkcode/tui/adapters/command_ui.py`、`src/Arkcode/tui/widgets/status_bar.py`、`tests/commands/test_builtins.py`
**依赖：** T32、T36、T44

- [ ] 写 `/team list/info/delete/kill` 参数与输出测试。
- [ ] 实现 TeamCommands 协议和 handler/adapter。
- [ ] 实现 Team/Coordinator 状态栏标识。
- [ ] 运行命令和状态栏测试。

**验证：** `pytest tests/commands/test_builtins.py tests/tui/test_views.py -k 'team or coordinator' -v`。

### T47：Team delete、恢复与普通模式收敛

**文件：** `src/Arkcode/teams/manager.py`、`src/Arkcode/teams/coordinator.py`、`tests/teams/test_manager.py`、`tests/teams/test_coordinator.py`
**依赖：** T39-T46

- [ ] 写非 force 活跃拒绝、force kill→session/worktree→config dir 顺序测试。
- [ ] 写重启恢复 Pane 判活、in-process 标 idle 测试。
- [ ] 写 Coordinator 中 Bash merge 拒绝、普通模式允许且 merge 前 Team 保留测试。
- [ ] 实现删除/恢复边界；不增加 MergeTool。

**验证：** `pytest tests/teams/test_manager.py tests/teams/test_coordinator.py -k 'delete or restore or merge' -v`。

### T48：Team 应用装配

**文件：** `src/Arkcode/application/bootstrap.py`、`src/Arkcode/application/runtime.py`、`src/Arkcode/application/cli.py`、`tests/application/test_runtime.py`
**依赖：** T41-T47

- [ ] 在 composition root 构造 TeamManager/Backend/Tools/consumers。
- [ ] 写普通 CLI 与 team-member CLI 分流测试。
- [ ] 写 shutdown 按消费者→队员→Manager→既有资源顺序测试。
- [ ] 运行 Application 与 Team 集成测试。

**验证：** `pytest tests/application tests/integration/test_team_inprocess.py -q`。

### T49：tmux 条件端到端

**文件：** `tests/integration/test_team_tmux.py`
**依赖：** T48

- [ ] 用 `shutil.which("tmux")` 条件标记真实集成测试。
- [ ] 覆盖 TeamCreate→spawn pane→initial mailbox→idle→SendMessage wake→force delete。
- [ ] 断言 worktree/config/session 生命周期与 pane 状态。
- [ ] 在有 tmux 环境运行测试；无 tmux 时明确 SKIP 而非 PASS。

**验证：** `pytest tests/integration/test_team_tmux.py -v`。

### T50：最终回归门

**文件：** 全部实现与测试文件
**依赖：** T1-T49

- [ ] 运行 `python3 -m compileall src/Arkcode`。
- [ ] 运行 `ruff check src tests`。
- [ ] 运行 `mypy src/Arkcode`。
- [ ] 运行 `pytest -q`，记录通过/失败/跳过数量。
- [ ] 手动确认 `rg -n 'os\.chdir' src/Arkcode` 只命中 Pane worker 的一次启动调用。
- [ ] 手动确认 `rg -n 'core\.hooksPath|<job-notification>' src/Arkcode` 无实际实现残留；测试文件允许包含用于拒绝断言的字符串。

**验证：** 所有静态检查和可运行测试退出 0；tmux 缺失只允许对应条件测试 skip。

## 执行顺序

```text
阶段 A
T1 → T2 → T3 ─┬→ T5 → T6 ───────────────┐
               ├→ T9 → T10 ──────────────┤
T1 → T4 → T11 ┘                           ├→ T12 → T13 → T14 → T15 → T16 → T17
T1 → T7 → T8 ─────────────────────────────┘

阶段 B
T17 → T18 → T19 ───────────────┐
T17 → T20 → T21 → T22 → T23 → T24 → T25 → T26 ─┐
                                      └→ T27 ────┴→ T28 → T29

阶段 C
T29 → T30 → T31 → T37 → T32 ─────────┐
             ├→ T33 → T34 ────────────┤
             └→ T35 → T36 ────────────┤
T37 → T38 ────────────────────────────┤
          └→ T39 → T40 ───────────────┤
T32+T34+T37-T40 → T41 → T42 → T43 ───┤
T4+T36 → T44 → T45/T46 ───────────────┤
T39-T46 → T47 → T48 → T49 → T50 ─────┘
```

## Plan 覆盖映射

| Plan 组件 | Tasks |
|---|---|
| AgentIdentity/RunResult/ReminderInbox | T1-T3 |
| RegistryPolicy/Definition/Catalog | T4-T6 |
| PermissionScope/ApprovalBroker | T7-T8 |
| TaskManager/Fork/Launcher/Job tools | T9-T16 |
| ExecutionPathContext/六工具 | T18-T19 |
| Worktree models/Git/manifest/manager/setup | T20-T25 |
| Worktree SubAgent/commands/stale sweep | T26-T29 |
| Team FileLock/models/manager | T30-T32 |
| Registry/Mailbox/TaskStore/Tools | T33-T36 |
| Backend/worker/spawner | T37-T41 |
| Team context/resume/Plan approval | T42-T43 |
| Coordinator/Lead pump/commands | T44-T46 |
| Team delete/recovery/app/E2E | T47-T50 |
