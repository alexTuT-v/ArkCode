# ArkCode

ArkCode 是一个运行在终端中的多协议 LLM 对话客户端，支持 Anthropic 和 OpenAI
协议及其兼容端点，提供流式回复、多轮上下文、Markdown 渲染和多 Provider 启动选择。

## 环境要求

- Python 3.12 或更高版本
- 可用的 LLM API Key
- 推荐安装 [uv](https://docs.astral.sh/uv/)

## 安装依赖

在项目根目录执行：

```bash
uv sync
```

如果不使用 uv，也可以创建虚拟环境并通过 pip 安装：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 配置

复制配置模板：

```bash
cp .env.example .env
```

编辑 `.env`，填入真实的模型、端点和 API Key。`.env` 已被 Git 忽略，请勿提交真实密钥。

```dotenv
ARKCODE_PROVIDERS=anthropic,openai

ARKCODE_ANTHROPIC_PROTOCOL=anthropic
ARKCODE_ANTHROPIC_MODEL=claude-sonnet-4-5
ARKCODE_ANTHROPIC_BASE_URL=
ARKCODE_ANTHROPIC_API_KEY=your-anthropic-api-key
ARKCODE_ANTHROPIC_THINKING=true

ARKCODE_OPENAI_PROTOCOL=openai
ARKCODE_OPENAI_MODEL=gpt-5
ARKCODE_OPENAI_BASE_URL=
ARKCODE_OPENAI_API_KEY=your-openai-api-key
ARKCODE_OPENAI_THINKING=false
```

配置规则：

- `ARKCODE_PROVIDERS` 是逗号分隔的 Provider 名称列表，其顺序也是启动选择界面的展示顺序。
- Provider 名称仅允许字母、数字和下划线。
- 每个 Provider 使用 `ARKCODE_<大写名称>_` 前缀。
- `PROTOCOL` 仅支持 `anthropic` 或 `openai`。
- `PROTOCOL`、`MODEL` 和 `API_KEY` 必填。
- `BASE_URL` 可留空；兼容服务需填写其 API 地址。
- `THINKING` 可省略，默认为 `false`，仅接受 `true` 或 `false`。
- `.env` 中的值会覆盖同名系统环境变量。

如果只使用一个 Provider，只需在 `ARKCODE_PROVIDERS` 中保留一个名称，并删除其他配置。

## 启动

必须在包含 `.env` 的项目根目录运行：

```bash
uv run Arkcode
```

也可以通过 Python 模块启动：

```bash
uv run python -m Arkcode
```

如果使用 pip 安装并已激活虚拟环境：

```bash
Arkcode
```

配置多个 Provider 时，启动后使用方向键选择，按 Enter 确认。对话界面中：

- Enter：发送消息
- Alt+Enter：插入换行
- `/exit` 或 Ctrl+C：退出

### Slash 命令

- `/help [命令名]`：列出命令，或查看单个命令的别名、描述与用法详情
- `/session [list | resume <id> | new | delete <id>]`：会话管理
- `/memory [list | clear | edit]`：记忆管理
- `/mcp`：查看 MCP 服务器连接状态与工具数量
- `/sandbox [1|on-auto | 2|on | 3|off]`：OS 级沙箱三态切换（macOS Seatbelt /
  Linux bubblewrap）
- 自定义命令：`.Arkcode/commands/*.md` 会被自动注册为可用的 Slash 命令

### MCP 与工具延迟加载

- MCP server 的 `instructions` 会随启动注入 Agent 系统指令；连接失败时保留状态
  供 `/mcp` 查询，运行中断开会自动重连一次。
- 远端 MCP 工具采用延迟加载：默认不进模型上下文，模型可用 `ToolSearch` 工具
  按关键词或 `select:<name>` 精确加载后使用，避免大量 schema 占用上下文。
- 工具参数基于远端 `input_schema` 动态生成 pydantic 模型做类型校验；结果中的
  图片与内嵌资源会以占位文本形式回流。

## 常见启动错误

- `配置文件不存在: .env`：确认当前目录是项目根目录，并已复制 `.env.example`。
- `ARKCODE_PROVIDERS 不能为空`：至少配置一个 Provider。
- `ARKCODE_<NAME>_API_KEY 不能为空`：为对应 Provider 填写 API Key。
- 协议错误：确认 `PROTOCOL` 为 `anthropic` 或 `openai`。
- 兼容端点无法连接：检查 `BASE_URL` 是否符合服务商要求。

## 代码架构

ArkCode 采用单向依赖的领域分包结构，`application` 是唯一 composition root：

```text
CLI / TUI
    │
    ▼
application（ApplicationRuntime / SessionService / build_runtime）
    │
    ▼
agents / commands / context
    │
    ▼
llm / tools / permissions / sessions / memory / skills / mcp
```

主要边界约定：

- `src/Arkcode/application/`：唯一的对象装配点。`build_runtime` 构造进程级依赖，
  `SessionService` 显式持有当前 Provider、Agent、Conversation、Writer 与权限模式，
  `ApplicationRuntime.shutdown` 按 Writer → 后台任务 → MCP 的顺序关闭资源。
- `src/Arkcode/agents/`：`agent.py` 只保留公共 Agent API 与 ReAct 编排；流事件转换在
  `streaming.py`，工具批执行、审批与只读并发在 `execution.py`，事件模型在 `events.py`。
- `src/Arkcode/commands/`：每条内置 Slash 命令一个 `handlers/<name>.py` 模块；
  `ports.py` 定义强类型 Protocol，`dispatcher.py` 统一处理 busy 策略与异常边界。
- `src/Arkcode/tui/`：`app.py` 只保留 Textual 组合、绑定与生命周期；controllers 把
  用户动作转换为 `SessionService` 调用；views 只生成 renderable；widgets 只处理
  Textual 组件与键盘行为；streaming 消费 AgentEvent 并维护展示状态。
- 领域包不得反向导入 `application` 或 `tui`；除 `application` 外任何模块不得构造
  具体的 MCP manager、Memory manager、权限引擎或默认工具注册表（由
  `tests/architecture/test_dependencies.py` 强制）。

## 开发与验证

安装开发依赖后执行：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/Arkcode
```
