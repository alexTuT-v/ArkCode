# ArkCode 结构重构设计

日期：2026-08-08

## 1. 背景与目标

ArkCode 已包含多 Provider、流式 Agent、工具调用、权限、MCP、上下文压缩、会话、记忆、命令和 Skills，但部分核心模块同时承担领域逻辑、对象装配和展示协调职责。主要热点是 `agent/agent.py` 和 `tui/app.py`。

本次重构参考 MewCode 的领域分包方式，将 ArkCode 调整为边界清晰、依赖单向的目录结构，同时保留 ArkCode 现有的 `src` 布局、Provider 抽象、严格类型检查和独立 `tui/` 展示层。

本次允许删除旧内部导入路径，不提供兼容 facade。所有用户可观察能力、配置、工具协议、命令、磁盘格式和 TUI 行为保持不变。

## 2. 非目标

本次不增加或改变以下能力：

- hooks
- file rewind
- headless 或 remote 模式
- OS 级沙箱
- Git worktree
- 多 Agent 或 team
- Provider、MCP、Memory、Context 算法
- Bash 非零退出码语义
- 配置文件格式
- TUI 视觉设计与快捷键

## 3. 架构原则

依赖方向固定为：

```text
CLI / TUI
    │
    ▼
application
    │
    ▼
agents / commands / context
    │
    ▼
llm / tools / permissions / sessions / memory / skills / mcp
```

约束如下：

1. `application` 是唯一 composition root，负责创建和连接具体实现。
2. `agents` 不依赖 Textual，不直接读取全局配置。
3. `tui` 通过 application service 操作会话，不访问领域对象私有字段。
4. `commands` 通过小型 Protocol 调用会话和展示能力，不依赖具体 Textual App。
5. `tools` 只依赖工具契约；MCP 工具通过 adapter 接入。
6. `context` 封装 token 估算、spill、摘要和 recovery。
7. `sessions` 独占会话磁盘格式和读写职责。
8. 领域包不得反向导入 `application` 或 `tui`。
9. 包级 `__init__.py` 只公开该包的新稳定 API，不保留旧路径转发。

## 4. 目标目录

```text
src/Arkcode/
├── __init__.py
├── __main__.py
├── application/
│   ├── __init__.py
│   ├── cli.py
│   ├── bootstrap.py
│   ├── lifecycle.py
│   ├── runtime.py
│   └── session.py
├── agents/
│   ├── __init__.py
│   ├── agent.py
│   ├── events.py
│   ├── execution.py
│   ├── streaming.py
│   └── runtime.py
├── commands/
│   ├── __init__.py
│   ├── models.py
│   ├── parser.py
│   ├── ports.py
│   ├── registry.py
│   └── handlers/
│       ├── __init__.py
│       ├── core.py
│       ├── conversation.py
│       ├── workflow.py
│       └── skills.py
├── config/
│   ├── __init__.py
│   ├── models.py
│   └── loader.py
├── context/
│   ├── __init__.py
│   ├── constants.py
│   ├── manager.py
│   ├── prompts.py
│   ├── recovery.py
│   ├── spill.py
│   ├── state.py
│   ├── summary.py
│   └── tokens.py
├── conversations/
│   ├── __init__.py
│   └── manager.py
├── instructions/
│   ├── __init__.py
│   └── loader.py
├── llm/
│   ├── __init__.py
│   ├── errors.py
│   ├── factory.py
│   ├── types.py
│   └── providers/
│       ├── __init__.py
│       ├── anthropic.py
│       └── openai.py
├── mcp/
│   ├── __init__.py
│   ├── config.py
│   ├── manager.py
│   └── tool_adapter.py
├── memory/
│   ├── __init__.py
│   ├── manager.py
│   ├── prompts.py
│   ├── store.py
│   └── types.py
├── permissions/
│   ├── __init__.py
│   ├── blacklist.py
│   ├── engine.py
│   ├── persist.py
│   ├── rules.py
│   ├── sandbox.py
│   ├── settings.py
│   └── types.py
├── prompts/
│   ├── __init__.py
│   ├── banner.py
│   ├── builder.py
│   ├── environment.py
│   ├── modules.py
│   └── reminders.py
├── sessions/
│   ├── __init__.py
│   ├── cleanup.py
│   ├── listing.py
│   ├── loader.py
│   └── writer.py
├── skills/
│   ├── __init__.py
│   ├── executor.py
│   ├── install.py
│   ├── loader.py
│   └── parser.py
├── tools/
│   ├── __init__.py
│   ├── base.py
│   ├── factory.py
│   ├── registry.py
│   ├── utils.py
│   ├── builtins/
│   │   ├── __init__.py
│   │   ├── bash.py
│   │   ├── edit_file.py
│   │   ├── glob.py
│   │   ├── grep.py
│   │   ├── read_file.py
│   │   └── write_file.py
│   └── skill_tools/
│       ├── __init__.py
│       ├── install_skill.py
│       └── load_skill.py
└── tui/
    ├── __init__.py
    ├── app.py
    ├── state.py
    ├── styles.tcss
    ├── adapters/
    │   ├── __init__.py
    │   └── command_ui.py
    ├── controllers/
    │   ├── __init__.py
    │   ├── approvals.py
    │   ├── chat.py
    │   ├── commands.py
    │   ├── providers.py
    │   ├── sessions.py
    │   └── skills.py
    ├── streaming/
    │   ├── __init__.py
    │   ├── controller.py
    │   └── state.py
    ├── views/
    │   ├── __init__.py
    │   ├── approvals.py
    │   ├── banner.py
    │   ├── messages.py
    │   ├── status.py
    │   └── tools.py
    └── widgets/
        ├── __init__.py
        ├── completion.py
        ├── message_input.py
        ├── provider_select.py
        └── status_bar.py
```

测试目录镜像领域目录，并将跨领域场景放入 `tests/integration/`：

```text
tests/
├── agents/
├── application/
├── commands/
├── config/
├── context/
├── conversations/
├── instructions/
├── integration/
├── llm/
├── mcp/
├── memory/
├── permissions/
├── prompts/
├── sessions/
├── skills/
├── tools/
├── tui/
└── fixtures/
```

## 5. 模块职责

### 5.1 Application

`ApplicationRuntime` 持有进程级依赖，包括配置、ToolRegistry、PermissionEngine、MCP、Memory、Skills 和 SessionService。`bootstrap.py` 创建这些依赖，`lifecycle.py` 统一管理 MCP、Writer、清理任务和后台任务的关闭。

`SessionService` 持有当前 Provider、Agent、Conversation、SessionRuntime、SessionWriter 和 SkillExecutor，并提供 `activate_provider`、`submit_message`、`force_compact`、`clear_session`、`resume_session`、`set_mode`、`cancel_turn` 和 `shutdown` 操作。

### 5.2 Agents

`agent.py` 保留公共 Agent 接口和 ReAct 主循环。`streaming.py` 负责 Provider 事件收集，`execution.py` 负责权限、审批、只读并发和工具结果，`events.py` 定义事件模型，`runtime.py` 保存单会话运行状态。

### 5.3 TUI

`tui/app.py` 只保留 Textual App、布局、bindings 和生命周期事件。Controllers 将用户动作转换为 SessionService 调用；Adapters 实现 commands 所需的 UI Protocol；Streaming 消费 AgentEvent；Views 生成 renderable；Widgets 只处理 Textual 组件和键盘行为。

TUI 外观、焦点、快捷键、Provider 选择、审批交互和流式表现保持不变。

## 6. 数据流

普通消息：

```text
ChatInput
  → tui.controllers.chat
  → SessionService.submit_message
  → Agent.run
      → ContextManager.manage
      → Provider.stream
      → ToolExecutor.execute
          → PermissionEngine.check
          → ToolRegistry.execute
  → AgentEvent
  → tui.streaming.controller
  → views/widgets
```

命令：

```text
/command
  → commands.parser
  → commands.registry
  → CommandHandler
  → commands.ports.SessionCommands Protocol
  → SessionService
  → CommandUI adapter
```

Conversation、SessionWriter 和 compact boundary 的协调统一位于 SessionService，磁盘格式不变。

## 7. 错误边界

- 配置错误由 `application.cli` 转换为现有 CLI 错误和退出码。
- MCP 单服务失败继续降级启动，并保留状态展示。
- Provider 和 Agent 错误继续转换为 AgentEvent，不使 TUI 退出。
- Tool 错误继续转换为 `ToolResult(is_error=True)`。
- Session 和 Memory 后台错误记录日志，不破坏当前对话。
- `ApplicationRuntime.shutdown` 统一关闭 Writer、MCP 和后台任务。
- 异常必须在所属边界转换，不允许 TUI 通过宽泛捕获隐藏领域状态。

## 8. 迁移顺序

1. 补齐 MCP 示例文档，建立全绿基线并冻结关键行为。
2. 迁移 `permissions`、`prompts`、`sessions` 等低耦合领域。
3. 拆分 `config`，移动 `llm/providers`。
4. 迁移 `tools` 与 MCP tool adapter。
5. 迁移 `context` 与 `conversations`。
6. 重组 `commands` 并建立 ports。
7. 拆分 `agents`。
8. 建立 application runtime 和 session service。
9. 拆分 `tui`。
10. 镜像测试目录、删除旧路径并更新文档。

每个阶段形成一个或多个独立、全绿的提交。纯目录移动与职责拆分应分别提交；任一阶段发现行为变化时，必须在进入下一阶段前修复。

## 9. 改动量与风险

预计涉及 100–140 个源码和测试文件，Git 差异约 3,500–6,000 行，其中约 1,000–1,800 行属于真实职责调整，其余为移动、import 和测试路径更新。预计形成 10–14 个提交。

风险从低到高：

| 区域 | 风险 | 主要问题 |
|---|---|---|
| 目录改名 | 低 | 动态 import 或 patch 路径遗漏 |
| Config、Provider | 中 | 启动和 Provider 选择 |
| Tools、MCP | 中 | Schema、顺序和只读属性 |
| Commands | 中 | Skill 命令和 UI Protocol |
| Context、Session | 中高 | 压缩恢复和 JSONL 格式 |
| Agent 拆分 | 高 | 取消、审批和工具并发顺序 |
| Application 生命周期 | 高 | Writer、MCP 和后台任务关闭 |
| TUI 拆分 | 高 | Textual 消息、焦点和异步渲染时序 |

## 10. 测试与验收

每个迁移阶段必须执行：

```bash
pytest
ruff check .
ruff format --check .
mypy src/Arkcode
```

需要冻结并验证：

- 内置工具、Skill 工具的名称、顺序和 JSON Schema
- Plan Mode 可见工具集合
- slash command 名称、参数和补全顺序
- Provider 请求中的 system、environment 和 reminder
- Session JSONL、compact boundary 和 `.Arkcode/` 路径
- Memory 与 Skill 加载优先级
- TUI 快捷键、审批选项、Provider 选择和流式状态
- 取消时 Provider stream、工具进程和 Skill task 的清理

增加架构依赖测试，禁止领域层反向导入 `application` 或 `tui`。增加 application runtime 装配与关闭顺序测试。

最终还需进行真实 Textual smoke test，覆盖 Provider 选择、普通对话、工具审批、Plan/Do、Compact、Resume、Skill inline/fork、取消和退出。

## 11. 完成标准

- 所有新目录落地，旧单数目录删除。
- 不保留旧导入兼容层。
- application 成为唯一 composition root。
- TUI 和 commands 不再访问 Agent、Registry、Writer 私有字段。
- `agent.py` 目标约 300–400 行，`tui/app.py` 目标约 200–300 行。
- 全部测试、Ruff、格式检查和 strict mypy 通过。
- 外部行为、工具协议、命令、配置和磁盘格式无变化。
