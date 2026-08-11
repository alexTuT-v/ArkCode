# ArkCode × MewCode（Python）能力差距分析

> 生成日期：2026-08-09
> 对照对象：`/Users/inception/learning/mewcode-python`（下称 MewCode）
> 范围：tools、slash command、MCP、agent 模块，以及直接支撑这些模块的子系统。
> 目的：找出当前 ArkCode 没有、但 MewCode 已实现的能力，作为后续功能提案的输入。

## 1. 总体结论

MewCode 在四个重点模块上都是 ArkCode 的超集方向，并额外拥有 7 个 ArkCode 完全没有的
子系统（sandbox、hooks、worktree、filehistory/rewind、remote、teams、自定义 Agent 定义）。

ArkCode 缺失的能力可归纳为五类：

- **子代理与多代理**：Agent 工具、Team 协作、TaskManager、Trace
- **工作区隔离**：worktree、OS sandbox、filehistory/rewind
- **可扩展性**：自定义 Markdown 命令、自定义 Agent 定义、延迟工具加载（ToolSearch）
- **MCP 增强**：instructions 注入、富内容结果提取、`/mcp` 状态命令
- **事件钩子**：hooks（条件匹配、工具调用拦截）

注意：ArkCode 结构重构设计文档明确将 hooks、rewind、headless/remote、OS 级沙箱、
git worktree、多 Agent/team 列为**非目标**，因此其中一部分缺失属于设计上有意排除；
另一部分（ToolSearch、AskUser、自定义命令/Agent 定义、MCP instructions 注入等）
则属于"未实现但与现有架构不冲突"的可选增强。

## 2. Tools

### 2.1 共同基础

两边内置工具一致：`ReadFile / WriteFile / EditFile / Bash / Glob / Grep`。

### 2.2 ArkCode 缺失的工具

| 工具 | MewCode 源码 | 作用 |
|---|---|---|
| `Agent` | `mewcode/tools/agent_tool.py` | 主 Agent 生成子代理执行任务，支持一次性阻塞、后台运行、指定 subagent_type / model / isolation、team 成员模式 |
| `ToolSearch` | `mewcode/tools/impl/tool_search.py` | 延迟工具加载：`should_defer` 工具不进主上下文，按需搜索发现（ArkCode 所有工具常驻） |
| `AskUser` | `mewcode/tools/ask_user.py` | 向用户提结构化问题（text / radio / select / checkbox），配对话框（`askuser_dialog.py`） |
| `EnterWorktree` / `ExitWorktree` | `mewcode/tools/enter_worktree.py` / `exit_worktree.py` | 通过 git 创建隔离 worktree 并切换会话 |
| `TaskCreate / TaskGet / TaskList / TaskUpdate / TaskStop` | `mewcode/tools/task_*.py` | 团队任务看板，支持 blocks / blocked_by 依赖 |
| `TeamCreate / TeamDelete` | `mewcode/tools/team_create.py` / `team_delete.py` | 创建/删除多代理团队 |
| `SendMessage` | `mewcode/tools/send_message.py` | 团队内成员消息通信（含 plan_approval_response 审批消息） |
| `SyntheticOutput` | `mewcode/tools/synthetic_output.py` | 合成输出，测试/演示场景 |
| `ExitPlanMode` | `mewcode/tools/exit_plan_mode.py` | Plan 模式完成后提交计划等待用户审批（ArkCode 用 `/plan` + `/do` 指令流代替） |
| `diff`（模块） | `mewcode/tools/diff.py` | 编辑前后生成带行号的 diff（前缀/后缀匹配，非通用 LCS），上限 200 行 |
| `file_state_cache`（模块） | `mewcode/tools/file_state_cache.py` | 文件状态缓存，检测编辑冲突 |

### 2.3 现有工具的隐性差异

- `WriteFile` / `EditFile` 接入 `FileHistory.track_edit`，写前自动备份旧文件（ArkCode 无快照）。
- `Bash` 可配合 sandbox 在 OS 隔离内执行（`mewcode/tools/bash.py` + `mewcode/sandbox/`）。
- 工具注册表支持 `enable / disable / mark_discovered / search_deferred`（`mewcode/tools/__init__.py`）。

## 3. Slash Command

### 3.1 共同基础

核心命令重叠：`help / status / session / memory / compact / clear / plan / skill`。

### 3.2 ArkCode 缺失的命令

| 命令 | MewCode 源码 | 作用 |
|---|---|---|
| `/sandbox` | `mewcode/commands/handlers/sandbox.py` | 三态切换：沙箱+自动放行、沙箱+常规审批、关闭沙箱 |
| `/rewind` | `mewcode/commands/handlers/rewind.py` | 选择文件历史快照回退，支持"代码+对话 / 仅对话 / 仅代码"三种恢复 |
| `/worktree` | `mewcode/commands/handlers/worktree.py` | worktree 管理（create / list / enter 等） |
| `/tasks` | `mewcode/commands/handlers/tasks.py` | 后台任务与团队任务状态（状态图标、耗时） |
| `/trace` | `mewcode/commands/handlers/trace.py` | Agent 调用树追踪 |
| `/mcp` | `mewcode/commands/handlers/mcp.py` | 实时查看 MCP 连接、各 server 工具列表与状态 |
| 自定义 Markdown 命令 | `mewcode/commands/loader.py` | `.mewcode/commands/*.md` 自动注册为 prompt 命令：YAML frontmatter（description / argument-hint / aliases）、`$ARGUMENTS` 替换、子目录冒号命名空间（`git/log.md` → `git:log`） |

### 3.3 子命令（subcommand）能力

MewCode 的"子命令"不是注册表级子命令树，而是 handler 内部按 `args` 分派 +
`usage` 元数据文档化的惯例；多个命令采用此模式：

- `/session list | resume <id> | new | delete <id>`（`handlers/session.py`）
- `/memory list | clear | edit`（`handlers/memory.py`）
- `/worktree create | list | enter | exit | status`（`handlers/worktree.py`）
- `/rewind <checkpoint> [option]`、`/skill list | info | reload`

ArkCode 的缺口：

- **子命令型命令**：只有 `/skill` 一个命令实现了 args 分派；`/session` 仅显示当前
  会话 ID 与路径（无 list/resume/new/delete），`/memory` 仅列文件（无 list/clear/edit）。
- **`usage` / `arg_prompt` 元数据**：MewCode 的 `Command` 带 `usage` 与 `arg_prompt`
  字段（`mewcode/commands/registry.py`），每个命令声明子命令用法；ArkCode 的
  `Command`（`src/Arkcode/commands/models.py`）只有 name/description/kind/handler/
  aliases/hidden，没有用法元数据。
- **`/help <命令名>` 详细查询**：MewCode 的 help 支持按命令名显示别名、描述、
  `用法:` 与 `参数:`（`handlers/help.py`）；ArkCode 的 `/help` 只渲染全部命令名+描述，
  不支持参数查询。
- **子命令级补全（两边都没有）**：MewCode 的 `completion.py` 与 ArkCode 的
  `CompletionMenu` 都只补顶层命令名与 alias，不补子命令——这是共同缺口，不算
  ArkCode 相对 MewCode 的独缺项。

### 3.4 ArkCode 独有、MewCode 核心没有的命令

`/do`、`/exit`、`/permission`、`/resume`、`/review`。MewCode 的 Plan 流程由
`ExitPlanMode` 工具承担，而非命令。

## 4. MCP

### 4.1 共同基础

两边都支持 stdio 与 streamable HTTP 传输、启动降级与状态展示
（ArkCode：`src/Arkcode/mcp/`；MewCode：`mewcode/mcp/`）。

### 4.2 状态与 `/mcp` 命令（2026-08-09 已对齐）

ArkCode 已实现 `Manager.server_summary()`（`McpServerStatus`：name / tool_count /
connected / error）、连接失败记录（`_failures`）与 `/mcp` 状态命令
（`src/Arkcode/commands/handlers/mcp.py`）。此前的 `/mcp` 缺失项已解决。

### 4.3 传输与生命周期差异

| 维度 | ArkCode | MewCode |
|---|---|---|
| 连接方式 | 并发连接全部 server（`create_task` + `gather`，每 server 30s 超时） | 顺序连接（`connect_all` 循环） |
| 失败降级 | 打印 warn + `_failures` 记录（`server_summary` 可查） | `ConnectResult.errors` 收集 |
| 按需连接单个 server | 无 | `MCPManager.get_client` 支持 |
| 调用时懒重连 | 无（会话断开后调用直接失败） | `MCPToolWrapper.execute` 检测 `is_alive` 自动重连 |

### 4.4 工具适配差异

| 维度 | ArkCode | MewCode |
|---|---|---|
| 工具命名 | `mcp__server__tool`（双下划线） | `mcp_<server>_<tool>`（单下划线） |
| read-only 分类 | 读取 `annotations.read_only_hint`，支持只读并发（更强） | 不读取 hint，`category="command"`、`is_concurrency_safe=False` |
| 参数模型 | JSON 字符串 + `input_schema` 原样透传，无类型校验 | pydantic 动态生成 `params_model`，JSON Schema → Python 类型转换与必填校验 |
| 结果内容 | 只提取 `TextContent`，非文本警告一次并丢弃 | `_extract_text` 提取 Text / Image / EmbeddedResource |
| 调用超时 | 30s `wait_for` + 超时/异常分类 | 无显式超时 |
| 延迟加载 | 无（全部常驻模型上下文） | `should_defer = True` + `ToolSearch` 按需发现 |

### 4.5 元数据与指令

- **instructions 注入**：MewCode 从 `InitializeResult` 提取 server instructions
  （`mewcode/mcp/client.py` 的 `instructions` 属性）并可注入系统提示；ArkCode 不读取。
- **env 展开**：两边都支持 `${VAR}` 展开（ArkCode 在配置加载时完成，
  MewCode 在连接时 `build_child_env` 处理），基本对等。

### 4.6 待办差距（ArkCode 尚未实现）

- instructions 注入（4.5）
- 富内容结果提取（4.4 结果内容）
- 调用时懒重连与按需连接（4.3）
- MCP 工具懒加载（`should_defer` + ToolSearch，4.4 延迟加载）
- 类型化参数校验（4.4 参数模型）

## 5. Agent

这是差距最大的模块。ArkCode 是单 Agent + ReAct 循环
（`src/Arkcode/agents/`：agent / streaming / execution / events）；MewCode 在此基础上
增加了一整套能力：

| 能力 | MewCode 源码 | 说明 |
|---|---|---|
| Agent 定义系统 | `mewcode/agents/loader.py`、`parser.py`、`agents/builtins/*.md` | `.mewcode/agents/*.md` 定义 agent：system_prompt、tools 白名单、disallowed_tools、model、max_turns、permission_mode、background、isolation（可选 worktree）；内置 explore / general-purpose / plan / verification 四个 |
| ToolFilter | `mewcode/agents/tool_filter.py` | 按 agent 类型过滤工具：全 Agent 禁用集、自定义 Agent 禁用集、异步 Agent 白名单、团队协作工具集 |
| 子代理工具 | `mewcode/tools/agent_tool.py` | 一次性子代理或常驻 teammate；支持 `plan_mode_required` 审批流 |
| TaskManager | `mewcode/agents/task_manager.py` | 后台任务注册表：进度、工具调用数、token 统计、结果回收 |
| TraceManager | `mewcode/agents/trace.py` | 跨代理调用树：agent_id / parent_id / trace_id / token / 状态 |
| Notification | `mewcode/agents/notification.py` | 任务结果格式化（截断 5000 字符）并注入会话 |
| Fork 子代理 | `mewcode/agents/fork.py` | 通用子代理消息构造（fork boilerplate、范围约束、500 字报告上限） |
| Teams | `mewcode/teams/` | 多代理团队：coordinator、mailbox、spawn（tmux / iTerm2 / in-process）、progress、transcript、backend_detect |

ArkCode 目前只有 `SkillExecutor.execute_fork` 这类 skill 级 fork，没有通用的子代理、
任务、追踪或多代理机制。

## 6. FileHistory / Rewind

> 单独成节：这是"工作区隔离/可恢复性"里与 Tools、Agent 都直接耦合的一项，
> 也是 MewCode 中实现最完整的能力之一。

### 6.1 数据模型（`mewcode/filehistory/history.py`）

- `FileHistory` 以会话为单位存储：目录 `.<项目>/.mewcode/file-history/<session_id>`。
- 备份文件命名：`sha256(绝对路径)[:16]@v<版本号>`。
- 快照 `Snapshot`：绑定 `message_index`（对话位置）与 `user_text`（该轮用户输入），
  内含该时刻所有已跟踪文件的 `Backup`（备份路径 + 版本 + 时间戳）。
- 上限 `MAX_SNAPSHOTS = 100`，超出后丢弃最旧的。

### 6.2 写入链路

- `WriteFile` / `EditFile` 在执行写操作前调用 `track_edit(path)`：把当前文件内容备份到
  会话目录，并递增版本号（`mewcode/tools/write_file.py`、`edit_file.py`）。
- Agent 在每轮用户消息处理时调用 `make_snapshot(len(conversation.history), summary)`
  （`mewcode/agent.py`），把当前文件版本与对话位置绑定成检查点。

### 6.3 恢复链路（`/rewind`）

`/rewind [checkpoint] [option]` 支持三种恢复模式：

1. 恢复代码 + 对话（默认）：`FileHistory.rewind(idx)` 还原文件，对话截断到快照位置。
2. 仅恢复对话：只替换会话历史，文件不动。
3. 仅恢复代码：只还原文件，对话保留。

还原时只重写与备份内容不一致的文件；快照列表在还原点之后的部分被丢弃，已跟踪版本号
回退到还原点。

### 6.4 与 ArkCode 的差距

ArkCode 没有任何文件快照机制：`WriteFile` / `EditFile` 直接落盘，不存在"回退到上一步"
的入口。ArkCode 的会话持久化（`sessions/writer.py`）只有 JSONL 追加式记录，没有
与文件快照绑定的检查点。该项在 ArkCode 重构设计文档中被列为非目标。

## 7. 其他 ArkCode 完全没有的子系统

| 子系统 | MewCode 源码 | 说明 |
|---|---|---|
| sandbox | `mewcode/sandbox/bwrap.py`、`seatbelt.py` | OS 级隔离：Linux bubblewrap、macOS seatbelt |
| hooks | `mewcode/hooks/`（engine / conditions / executors / models / loader） | 事件钩子：条件匹配、事件驱动、`ToolRejectedError` 拦截工具调用 |
| worktree | `mewcode/worktree/`（manager / session / changes / cleanup / setup / slug） | git worktree 全流程：创建、进入、变更检测、清理 |
| remote | `mewcode/remote.py` + `web_content.py` | WebSocket 桥接 Agent 事件 + 浏览器 Web UI（headless 远程控制） |
| 自定义 Agent 定义 | 见第 5 节 | 项目/用户级 `.md` 定义可执行代理 |

## 8. 落地优先级建议

按"与现有架构兼容度 × 收益"排序的建议（仅作参考，需另行立项评估）：

1. **MCP 增强（部分完成）**：`/mcp` 状态命令与 `server_summary` 已实现
   （2026-08-09）；剩余：instructions 注入、富内容结果提取、调用时懒重连、
   工具懒加载（`should_defer` + ToolSearch）、类型化参数校验。
2. **自定义 Markdown 命令**：已实现（2026-08-09，`commands/loader.py`）。
3. **AskUser 工具 + 审批对话框**：属于交互层增强，Agent 事件模型已支持
   `ApprovalRequest`，可类比扩展。
4. **ToolSearch / 延迟工具加载**：需要改工具注册表与 Agent 请求装配，属中风险。
5. **FileHistory / Rewind**：需要新包 + WriteFile/EditFile 挂钩 + 会话恢复命令，
   改动面中等；ArkCode 已明确列为非目标，如需落地需先修改范围决策。
6. **子代理 / TaskManager / Trace**：可先做单 Agent 后台任务与追踪，再做通用 Agent
   工具；团队协作（teams）与 worktree/sandbox 依赖 OS 级与进程级能力，投入最大。
7. **hooks / worktree / sandbox / remote / teams**：均属 ArkCode 重构设计文档的明确
   非目标，落地前必须先变更产品范围决策。

## 9. 参考资料（MewCode 源码索引）

- Tools：`mewcode/tools/`（ask_user、diff、enter_worktree、exit_plan_mode、
  exit_worktree、file_state_cache、send_message、synthetic_output、task_*、team_*、
  impl/tool_search、agent_tool）
- Commands：`mewcode/commands/`（loader、parser、registry、completion、
  handlers/{mcp,rewind,sandbox,worktree,tasks,trace,skill_register}）
- MCP：`mewcode/mcp/`（client、manager、tool_wrapper）
- Agent：`mewcode/agents/`（loader、parser、fork、notification、task_manager、
  tool_filter、trace、builtins/）
- FileHistory：`mewcode/filehistory/history.py`、`mewcode/commands/handlers/rewind.py`
- 子系统：`mewcode/{hooks,sandbox,teams,worktree}/`、`mewcode/remote.py`
