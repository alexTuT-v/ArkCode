# Slash Command 增强设计

日期：2026-08-09
状态：待用户评审

## 1. 背景与目标

对照 `mewcode-gap-analysis.md` 中 Slash Command 模块的功能差距，补齐 ArkCode
的命令基础设施与两个依赖命令：`/mcp` 状态命令与 `/sandbox` OS 级沙箱。

目标：

- 命令元数据：`Command` 增加 `usage` / `arg_prompt`，`/help <命令名>` 显示详情。
- 子命令型命令：`/session` 支持 `list | resume <id> | new | delete <id>`；
  `/memory` 支持 `list | clear | edit`。
- 自定义命令：`.Arkcode/commands/*.md` 自动注册为 prompt 命令。
- `/mcp`：实时查看 MCP server 连接状态与工具列表。
- `/sandbox`：OS 级隔离（macOS Seatbelt / Linux bubblewrap），三态切换与自动放行。

## 2. 范围

### 2.1 包含

- Phase 1 命令基础设施：usage / arg_prompt 元数据、`/help <命令名>` 详情、
  `/session` 与 `/memory` 子命令、自定义 Markdown 命令加载器。
- Phase 2 `/mcp` 状态命令（含 MCP manager 状态查询扩展）。
- Phase 3 sandbox 子系统（`sandbox/` 包、Bash 沙箱挂载、`/sandbox` 命令、
  权限引擎自动放行联动）。

### 2.2 排除

本期不实现：`/rewind`、`/worktree`、`/tasks`、`/trace`、hooks、ToolSearch /
延迟工具加载、子命令级补全（与 mewcode 对齐，mewcode 亦无子命令补全）。

## 3. 非目标（沿用 ArkCode 重构设计）

- 不改变现有 12 个内置命令的 name / kind / 无参数输出。
- 不改变 Bash 非零退出码语义、超时与进程树处理。
- 不引入 hooks / rewind / headless / worktree / 多 Agent 能力。
- 不新增第三方运行时依赖（sandbox 仅包装系统自带工具）。

## 4. 总体架构与依赖方向

```text
src/Arkcode/
├── commands/
│   ├── models.py          # Command 增加 usage / arg_prompt（修改）
│   ├── loader.py          # 新增：.Arkcode/commands/*.md 加载器
│   ├── ports.py           # 新增 SandboxCommands；扩展 SessionCommands / StatusQueries（修改）
│   └── handlers/
│       ├── help.py        # /help <命令名> 详情（修改）
│       ├── session.py     # 子命令（修改）
│       ├── memory.py      # 子命令（修改）
│       ├── mcp.py         # 新增
│       └── sandbox.py     # 新增
├── mcp/
│   └── manager.py         # server_summary() 与失败记录（修改）
├── sandbox/               # 新增包
│   ├── __init__.py        # SandboxConfig / Sandbox / create_sandbox
│   ├── bwrap.py
│   └── seatbelt.py
├── permissions/
│   └── engine.py          # sandbox_enabled 自动放行（修改）
├── memory/
│   └── manager.py         # clear()（修改）
├── sessions/
│   └── listing.py         # delete_session()（修改）
├── tools/
│   └── builtins/bash.py   # 可注入 sandbox / sandbox_config（修改）
└── tui/
    ├── app.py             # mcp_manager 引用与命令表重建接入 loader（修改）
    ├── adapters/command_ui.py  # 新端口实现（修改）
    └── controllers/sessions.py # resume 公共入口（修改）
```

依赖顺序：Phase 1 → Phase 2 → Phase 3。Phase 3 的 `/sandbox` 用法展示依赖
Phase 1 的 usage 字段。命令层仍通过强类型端口访问能力，不反向依赖 TUI 内部。

## 5. Phase 1：命令基础设施

### 5.1 Command 元数据

`commands/models.py` 的 `Command` 增加两个字段（位于 `aliases` 之后）：

```python
usage: str = ""
arg_prompt: str = ""
```

每个内置 handler 模块补充 `usage` 值，至少覆盖：`session`、`memory`、
`sandbox`（Phase 3）、`help`。

### 5.2 /help <命令名> 详情

`handlers/help.py`：

- 无参数：保持现有"渲染全部命令"输出。
- 有参数：`registry.lookup(name)`，命中时输出：
  - `/<name>` 与别名（`(别名: /a, /b)`）
  - 描述
  - `用法: <usage>`（非空时）
  - `参数: <arg_prompt>`（非空时）
- 未知命令：`未知命令：<name>，输入 /help 查看可用命令`。

### 5.3 /session 子命令

`handlers/session.py` 按 args 分派：

- 无参数：保持现有输出（`Session: ...` / `Path: ...`）。
- `list`：用 `list_sessions` 列出会话（id、标题、消息数、最后活跃）。
- `resume <id>`：参数式恢复。`SessionCommands` 端口新增
  `resume_by_id(session_id: str) -> bool`，`CommandUIAdapter` 委托给 TUI session
  controller 复用完整恢复流程（压缩检查、过期提醒、UI 刷新）；现有 `/resume`
  交互式命令保持不变。id 不存在返回 False 且状态不变。
- `new`：复用 `clear_session` 语义并打印确认。
- `delete <id>`：`sessions` 包新增 `delete_session(sessions_dir, id) -> bool`；
  禁止删除当前活跃会话，失败返回 False。
- 未知子命令：输出用法提示。

### 5.4 /memory 子命令

`handlers/memory.py`：

- 无参数 / `list`：保持现有"列文件"输出。
- `clear`：清空记忆。`memory/manager.py` 新增 `clear()`：删除项目级与用户级
  store 中的全部记忆笔记并重建 `MEMORY.md` 索引。ArkCode 当前所有记忆均由
  `update_async` 自动生成（四种 `NoteType`），无手动编辑入口，因此该语义与
  mewcode 的"清空自动记忆"等价。`SessionService` 新增 `clear_memory()`，
  `SessionCommands` 端口新增 `clear_memory() -> None`。
- `edit`：显示用户级 / 项目级记忆目录路径（不打开编辑器）。
- 未知子命令：输出用法提示。

### 5.5 自定义 Markdown 命令加载器

新增 `commands/loader.py`：

- 扫描 `.Arkcode/commands/*.md`，子目录映射为冒号命名空间
  （`git/log.md` → `git:log`）。
- YAML frontmatter 支持 `description`、`aliases`、`argument-hint`。
- 正文 `$ARGUMENTS` 占位符替换；无占位符且带参数时追加 `## User Request` 段。
- 注册为 `CommandKind.PROMPT`，handler 调用 `session.submit_prompt(label, rendered)`。
- 冲突策略：与内置命令重名时警告并跳过，不允许覆盖内置命令。
- frontmatter 解析失败：跳过并警告，不阻塞启动。
- 注册时机：启动时加载，并在 TUI 命令表重建流程中重扫（获得与 `/skill reload`
  一致的热重载）。

## 6. Phase 2：/mcp 状态命令

### 6.1 MCP manager 扩展

`mcp/manager.py`：

- 新增 `McpServerStatus`（name、tool_count、connected、error）与
  `server_summary() -> list[McpServerStatus]`。
- `new_manager` 连接流程中把失败错误记录到 `_failures: dict[str, str]`。

### 6.2 命令与端口

- `commands/handlers/mcp.py`：无参数显示已连接 x/y、工具总数，逐 server 列出
  名称、工具数、状态与失败原因。
- `StatusQueries` 端口新增
  `mcp_server_status() -> list[McpServerInfo]`，`McpServerInfo` 为 commands 层
  dataclass（name / tool_count / connected / error）。
- `ArkCodeApp` 增加可选 `mcp_manager` 引用（生产路径来自
  `ApplicationRuntime.mcp`）；未配置或未注入时显示 `未配置 MCP`。

## 7. Phase 3：sandbox 子系统

### 7.1 sandbox 包

新增 `sandbox/`，对齐 mewcode 的接口与策略，代码按 ArkCode 风格实现，无新依赖：

- `SandboxConfig`：`allow_write: list[str]`、`deny_write: list[str]`
  （优先级高于 allow_write）、`network_enabled: bool`。
- `Sandbox` ABC：`wrap(command, config) -> str`、`available() -> bool`。
- `create_sandbox() -> Sandbox | None`：Darwin → SeatbeltSandbox，
  Linux → BwrapSandbox，其他平台 → None。
- `bwrap.py`：`bwrap --unshare-user --unshare-pid --ro-bind / / --bind <allow>
  ... --ro-bind <deny> ... [--unshare-net] --proc /proc --dev /dev --
  bash -c <command>`。
- `seatbelt.py`：`/usr/bin/sandbox-exec -p '<SBPL profile>' bash -c <command>`；
  profile 为 `(deny default)` + process-exec/fork、sysctl-read、全局 file-read、
  白名单 file-write、黑名单 deny（后声明优先）、网络开关。

### 7.2 Bash 集成

`tools/builtins/bash.py` 增加可注入属性 `sandbox` / `sandbox_config`
（默认 None）。execute 时若两者存在且 `available()` 为真，则
`actual_command = sandbox.wrap(command, sandbox_config)`；其余执行逻辑
（超时、退出码语义、进程树处理）不变。

### 7.3 权限联动

`permissions/engine.py` 的 `Engine` 增加 `sandbox_enabled: bool = False`。
`check()` 中：当 `sandbox_enabled` 为真时，`ASK` 决策直接返回 `ALLOW`
（OS 层兜底）；`DENY` 决策（如 Plan 模式写操作）保持不变。

### 7.4 /sandbox 命令

`commands/handlers/sandbox.py`：

- 无参数：显示状态（是否启用、自动放行、后端类型、后端可用性）。
- `1|on-auto`：启用沙箱 + 自动放行（推荐）。
- `2|on`：启用沙箱 + 常规审批。
- `3|off`：关闭沙箱。
- 启用时构建
  `SandboxConfig(allow_write=[workspace, 临时目录], deny_write=[.Arkcode/config.yaml,
  .Arkcode/permissions.local.yaml, .Arkcode/skills/], network_enabled=False)`，
  挂到 Bash 工具并设置 `engine.sandbox_enabled`。
- 平台不支持 / 后端不可用 / 找不到 Bash 工具：明确报错，不静默降级。

### 7.5 端口

新增 `SandboxCommands` Protocol：

```python
class SandboxCommands(Protocol):
    def status(self) -> SandboxStatus: ...
    def enable(self, auto_allow: bool) -> str | None: ...
    def disable(self) -> None: ...
```

`SandboxStatus` 为 commands 层 dataclass（enabled / auto_allow / backend /
available）。`CommandContext` 增加 `sandbox: SandboxCommands` 字段，所有构造点
同步更新（`CommandController`、`tests/commands/fakes.py` 的 `make_context` 与
相关手工构造 `CommandContext` 的测试）。`CommandUIAdapter` 实现该端口，操作
`app.tool_registry` 的 Bash 工具、`session` 的 engine 与 `workspace`。

ArkCode 现有的 `permissions/sandbox.py`（路径级写检查）与 OS 沙箱是两层独立
机制：前者保留，后者新增。

## 8. 错误处理

- `/session`：`resume <id>` 不存在 → `会话未找到: <id>`；`delete` 当前活跃会话 →
  拒绝；删除失败 → 提示失败。
- `/memory clear`：底层异常由 dispatcher 统一转 `ui.error`。
- `/mcp`：未配置 → `未配置 MCP`；单 server 失败 → 显示失败原因，不中断输出。
- `/sandbox`：平台不支持、后端缺失、Bash 工具缺失 → 明确报错；沙箱内命令失败 →
  走 Bash 现有退出码语义。
- 自定义命令：解析失败 / 与内置重名 → 警告跳过。
- handler 异常统一由 `commands/dispatcher.py` 捕获转 `ui.error`。

## 9. 测试

- Phase 1：`tests/commands/`——usage 字段、`/help <name>` 详情、`/session`
  四子命令（含 delete 保护当前会话）、`/memory` 子命令、loader 解析
  （frontmatter / `$ARGUMENTS` / 命名空间 / aliases / 冲突跳过）；扩展
  `tests/commands/fakes.py` 覆盖新端口方法。
- Phase 2：`tests/mcp/`——server_summary 与失败记录；`tests/commands/`——`/mcp`
  handler 用 fake 状态渲染。
- Phase 3：`tests/sandbox/`——wrap 构建（bwrap/seatbelt）、available、
  create_sandbox 平台选择；`tests/commands/`——`/sandbox` 三态与不可用报错；
  `tests/permissions/`——engine 自动放行；`tests/tools/`——Bash 注入 fake sandbox。
- 行为契约：`tests/integration/test_behavior_contracts.py` 的 12 命令列表保持；
  `/session`、`/memory`、`/help` 无参数输出保持。

## 10. 验收标准

- 每个 Phase 结束：`pytest`、`ruff check .`、`ruff format --check .`、
  `mypy src/Arkcode` 全绿。
- 12 个内置命令的 name / kind 与无参数输出不变；Bash 非零退出码语义不变。
- `/sandbox on-auto` 后写工具不再弹审批（自动放行生效）；Plan 模式写操作仍被
  拒绝。
- `/help /session` 等详情输出包含用法；`/session list`、`/memory clear` 等
  子命令可用；自定义 `.md` 命令可注册、覆盖保护生效。

## 11. 参考实现

- MewCode sandbox：`mewcode/sandbox/__init__.py`、`bwrap.py`、`seatbelt.py`、
  `tools/bash.py`、`commands/handlers/sandbox.py`、`permissions/sandbox.py`。
- MewCode 命令：`mewcode/commands/registry.py`（usage / arg_prompt）、
  `handlers/{session,memory,help,mcp}.py`、`commands/loader.py`。
