# ArkCode 交互式 AI 对话基础 Plan

## 架构概览

ArkCode 采用单进程异步架构。Textual TUI 运行在主事件循环中，模型流式请求作为可中断的后台 Worker 执行；日志记录先完成递归脱敏，再进入 FIFO 队列，由独立线程按顺序持久化，避免逐条 SSE 日志阻塞界面和网络事件消费。

```text
CLI / 启动编排
    │
    ├── 加载并校验 .env 配置
    ├── 生成 session_id，初始化 SessionLogger
    ├── 根据 protocol 创建 ChatProvider
    └── 启动 Textual TUI
              │
              ▼
       ConversationManager
         │       │        │
         │       │        └── SessionLogger
         │       │
         │       └── Conversation
         │
         ▼
      ChatProvider
       ├── AnthropicProvider ── Anthropic Messages SSE
       └── OpenAIProvider ───── OpenAI Responses SSE
```

### 启动编排层

负责 `session_id` 生成、日志文件初始化、`.env` 加载与校验、Provider 创建和 TUI 启动。任何启动阶段错误在进入全屏界面前以普通终端错误显示。日志文件无法创建时终止启动；日志成功初始化后发生的配置或 Provider 创建错误同时写入当前 session 日志。

### 配置层

将环境变量转换为经过校验且不可变的运行配置。它只暴露业务所需字段，不负责创建 SDK 客户端。配置对象的字符串表示和日志表示必须隐藏 API Key。

### 日志层

将结构化事件递归脱敏后写入 `logs/<session_id>.log`。所有调用方只向有序队列提交记录，独立线程负责 JSON 序列化、落盘和刷新。启动时同步验证日志文件可写；运行中写入失败通过线程安全回调通知 TUI，并同时写入标准错误。

### 领域模型层

定义与供应商无关的 Message、ConversationTurn、流事件、完成结果、运行状态和错误类型。TUI、ConversationManager 和 Provider 只通过这些统一模型协作。

### Provider 层

提供统一异步流接口。Anthropic 和 OpenAI 适配器分别使用官方异步 SDK 发起 SSE 请求，将 SDK 解码后的供应商事件转换为统一事件，同时记录原始事件、转换结果和顺序。

### 会话管理层

用户消息提交后立即创建 `IN_PROGRESS` ConversationTurn 并进入内存历史。ConversationManager 消费 Provider 流、累积 thinking 与正文、更新 TUI，并将 Turn 确定为 `COMPLETED`、`INTERRUPTED` 或 `FAILED`。三种终态都保留用户消息和已有助手正文；ArkCode 自身错误提示不进入模型上下文。

### TUI 层

使用 Textual 构建顶部状态栏、可滚动 Turn 列表、流式 Markdown、Thinking 区块、底部输入框和运行状态。TUI 只消费统一流事件，不解析供应商协议，也不直接操作 SDK。

依赖方向保持单向：

```text
TUI → ConversationManager → ChatProvider → 供应商 SDK
              ↓                  ↓
        领域模型 ←───────────────┘
              ↓
          SessionLogger
```

Provider 实现之间互不依赖；日志层不依赖 TUI；领域模型不依赖 SDK 或 Textual。

## 核心数据结构

### Protocol 与 AppConfig

```python
class Protocol(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass(frozen=True, slots=True)
class AppConfig:
    name: str
    protocol: Protocol
    model: str
    base_url: str
    api_key: str
    thinking: bool = False
```

```python
def load_config(env_file: Path = Path(".env")) -> AppConfig
```

约束：

- `.env` 使用 `name`、`protocol`、`model`、`base_url`、`api_key`、`thinking` 六个小写变量名。
- 前五项必填，`thinking` 省略时为 `false`。
- `thinking` 只接受明确布尔值。
- `protocol=openai` 时不把 `thinking` 传给 OpenAI。
- `AppConfig.__repr__` 和日志序列化不得暴露 `api_key`。

### Message

```python
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole
    content: str
    thinking: str | None = None
    provider_data: Mapping[str, Any] = field(default_factory=dict)
```

- `content` 保存用户输入、完整助手正文或被中断的部分正文。
- `thinking` 用于 TUI 和日志展示，可以是不完整内容。
- `provider_data` 只保存 Provider 验证过、允许在下一次请求中安全回传的供应商状态。
- Provider 不会仅因为 `thinking` 有值就将其发回供应商。

### TurnStatus 与 ConversationTurn

```python
class TurnStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


@dataclass(slots=True)
class ConversationTurn:
    turn_id: str
    user: Message
    status: TurnStatus = TurnStatus.IN_PROGRESS
    thinking: str = ""
    assistant_content: str = ""
    provider_data: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    sse_event_count: int = 0
```

- 用户提交后立即创建并加入 Conversation。
- thinking、正文和事件数量在流式处理期间增量累积。
- `error_message` 只用于 TUI 和日志，不转换成模型消息。
- ConversationTurn 同时表示进行中和历史终态，不再使用单独的 ActiveTurn。

### Conversation

```python
@dataclass(slots=True)
class Conversation:
    _turns: list[ConversationTurn] = field(default_factory=list)

    @property
    def turns(self) -> tuple[ConversationTurn, ...]: ...

    def start_turn(
        self,
        turn_id: str,
        user: Message,
    ) -> ConversationTurn: ...

    def apply_stream_event(
        self,
        turn_id: str,
        event: StreamEvent,
    ) -> None: ...

    def finish_turn(
        self,
        turn_id: str,
        status: TurnStatus,
        error_message: str | None = None,
    ) -> ConversationTurn: ...

    def context_messages(self) -> tuple[Message, ...]: ...

    def clear(self) -> None: ...
```

`context_messages()` 按顺序投影模型上下文：

- 每个 Turn 的用户 Message 始终包含。
- `assistant_content` 非空时增加 assistant Message，适用于完成、中断和失败 Turn。
- `thinking` 可进入 Message 的展示字段。
- 只有 `provider_data` 中经过 Provider 验证的完整状态才允许按供应商协议回传。
- `error_message` 永远排除。

返回值是新的元组，Provider 无法增删 Conversation 内部历史。

### StreamEventKind 与 StreamEvent

```python
class StreamEventKind(str, Enum):
    THINKING_STARTED = "thinking_started"
    THINKING_DELTA = "thinking_delta"
    TEXT_STARTED = "text_started"
    TEXT_DELTA = "text_delta"
    PROVIDER_STATE = "provider_state"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    kind: StreamEventKind
    sequence: int
    delta: str = ""
    raw_event: Any = None
    provider_data: Mapping[str, Any] = field(default_factory=dict)
    response: ProviderResponse | None = None
```

- 每个供应商事件获得单调递增的 `sequence`。
- thinking 和最终回答使用不同事件类型。
- `PROVIDER_STATE` 只在收到完整、可安全回传的供应商状态后产生。
- 正常流最后必须产生一次 `COMPLETED`。
- API 错误通过异常传播，不伪装成完成事件。

### TokenUsage 与 ProviderResponse

```python
@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    thinking: str
    content: str
    stop_reason: str | None
    usage: TokenUsage
    provider_data: Mapping[str, Any]
    request_id: str | None
    response_id: str | None
    sse_event_count: int
```

### ChatProvider

```python
class ChatProvider(Protocol):
    async def stream(
        self,
        messages: Sequence[Message],
        *,
        turn_id: str,
    ) -> AsyncIterator[StreamEvent]: ...

    async def close(self) -> None: ...
```

```python
def create_provider(
    config: AppConfig,
    logger: SessionLogger,
) -> ChatProvider
```

Provider 负责消息协议转换、SDK SSE 调用、事件标准化、逐事件日志、完成聚合和 SDK 异常转换。

### ProviderErrorKind 与 ProviderError

```python
class ProviderErrorKind(str, Enum):
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    SERVER = "server"
    CONTEXT_LENGTH = "context_length"
    PROTOCOL = "protocol"
    UNSUPPORTED_THINKING = "unsupported_thinking"
    UNKNOWN = "unknown"


class ProviderError(Exception):
    kind: ProviderErrorKind
    safe_message: str
    retryable: bool
    provider_code: str | None
```

原始 SDK 异常在 Provider 边界转换成 ProviderError。脱敏原始异常进入日志，TUI 只显示 `safe_message`。

### TurnResult

```python
@dataclass(frozen=True, slots=True)
class TurnResult:
    turn_id: str
    status: TurnStatus
    error: ProviderError | None = None
```

正文和 thinking 已保存在 ConversationTurn 并通过流事件交给 TUI，TurnResult 只表示最终状态。

### ConversationManager

```python
ConversationEventSink = Callable[
    [StreamEvent],
    Awaitable[None],
]


class ConversationManager:
    async def run_turn(
        self,
        user_text: str,
        emit: ConversationEventSink,
    ) -> TurnResult: ...

    async def interrupt_current(self) -> None: ...

    def clear(self) -> None: ...

    @property
    def is_generating(self) -> bool: ...
```

行为：

1. 生成 `turn_id` 并创建用户 Message。
2. 立即调用 `Conversation.start_turn()`。
3. 使用包含当前用户消息的 `context_messages()` 调用 Provider。
4. 将每个流事件应用到 ConversationTurn，再交给 TUI。
5. 正常结束时标记 `COMPLETED`。
6. 捕获取消时保留部分内容并标记 `INTERRUPTED`。
7. 捕获 Provider 错误时保留部分内容并标记 `FAILED`。
8. 不将 ArkCode 错误说明放入模型上下文。

### 日志模型与接口

```python
@dataclass(frozen=True, slots=True)
class LogRecord:
    timestamp: str
    level: str
    session_id: str
    component: str
    event: str
    status: str
    message: str
    fields: Mapping[str, Any] = field(default_factory=dict)
```

`fields` 在序列化时展开到 JSON 顶层。

```python
@dataclass(frozen=True, slots=True)
class RedactionResult:
    value: Any
    redacted_fields: tuple[str, ...]


def redact(value: Any) -> RedactionResult
```

```python
class SessionLogger:
    @classmethod
    def create(
        cls,
        project_root: Path,
        session_id: str,
    ) -> SessionLogger: ...

    def log(
        self,
        *,
        level: str,
        component: str,
        event: str,
        status: str,
        message: str,
        **fields: Any,
    ) -> None: ...

    def set_failure_handler(
        self,
        handler: Callable[[Exception], None],
    ) -> None: ...

    def flush(self) -> None: ...
    def close(self) -> None: ...
```

`log()` 在调用线程完成脱敏后放入 FIFO 队列，不执行磁盘写入。`close()` 排空队列并结束写入线程。

### TUI 主接口

```python
class ArkCodeApp(App[None]):
    def __init__(
        self,
        config: AppConfig,
        manager: ConversationManager,
        logger: SessionLogger,
    ) -> None: ...
```

TUI 持有 ConversationManager，但不访问具体 Provider。模型调用作为 Textual Worker 运行；`Ctrl+C` 根据 `manager.is_generating` 决定中断当前 Turn 或退出。

## 模块设计

### 启动模块

**职责：**

- 解析命令行启动。
- 定位当前工作目录中的 `.env`。
- 生成 UUID v4 `session_id`。
- 创建 `logs/<session_id>.log`。
- 加载并校验配置，记录成功或失败结果。
- 初始化 Provider、Conversation、ConversationManager 和 TUI。
- 退出时关闭 Provider、排空日志队列并恢复终端。

**错误边界：**

- 配置错误和日志初始化错误发生在进入全屏 TUI 之前。
- 日志初始化失败只能写入标准错误；日志初始化成功后的启动错误同时写入日志和标准错误。
- Provider 客户端只完成本地构造，不在启动阶段主动请求 API。
- 启动失败时使用标准错误输出，并返回非零退出码。

### 配置模块

**职责：**

- 从 `.env` 读取六个小写配置项。
- 去除非秘密字段首尾空白。
- 校验必填字段、协议、URL 和布尔值。
- 构造不可变 AppConfig。
- 提供隐藏 API Key 的安全字符串表示。

**依赖：**

- 依赖 python-dotenv。
- 不依赖 Provider SDK、TUI 或日志具体实现。

### 结构化日志模块

内部包含三个职责：

1. **脱敏器：**递归遍历字典、序列、数据类和 SDK 模型，识别大小写不同的 `api_key`、`authorization`、`x-api-key`、`token` 等秘密字段。
2. **记录构造器：**添加公共字段，阻止调用方覆盖保留字段，将可选字段展开到 JSON 顶层。
3. **后台写入器：**通过 FIFO 队列写入独立线程；边界事件立即刷新，正常关闭时排空队列。

初始化时同步创建目录和文件并验证可写性。后台线程首次写入失败后保存故障状态，通过线程安全回调通知主事件循环；TUI 和标准错误同时告警。日志故障不得再次调用 SessionLogger。

### 领域模型模块

定义 AppConfig 之外的统一类型。Conversation 保存全部进行中和终态 Turn，并负责投影模型上下文，但不负责调用 Provider。

### Provider 基础模块

**职责：**

- 声明 ChatProvider。
- 定义统一错误类型与分类。
- 提供 Provider 工厂。
- 提供相邻同角色消息归并等共用转换辅助。
- 提供请求、流事件和完成结果的日志辅助。

ConversationManager 只依赖 ChatProvider。

### AnthropicProvider

**职责：**

- 将 Message 转换为 Anthropic Messages 输入。
- 合并协议需要合并的相邻同角色消息。
- `thinking=true` 时设置 adaptive thinking 和可展示摘要。
- 使用异步 Messages SSE。
- 处理 thinking、text、usage、stop reason、request ID 和 signature。
- 只有完整 thinking block/signature 才产生 `PROVIDER_STATE`。
- 中断或失败时不把不完整 thinking 写入安全 `provider_data`。
- 将 SDK 异常转换为 ProviderError。

下一次请求中，部分助手正文作为普通 assistant 文本保留；完整签名 thinking 根据 `provider_data` 回传；不完整 thinking 不回传。

### OpenAIProvider

**职责：**

- 将 Message 转换为 Responses API input Item。
- 使用本地完整历史，不依赖 `previous_response_id` 作为主要记忆。
- 不把 `.env` 的 `thinking` 映射成 OpenAI reasoning。
- 使用异步 Responses SSE。
- 处理文本增量、拒绝、usage、response ID、完成和错误事件。
- 只保存可在下一轮安全复用的完整输出 Item。
- 中断正文按普通 assistant 文本保留。
- 将 SDK 异常转换为 ProviderError。

### ConversationManager

**职责：**

- 保证同一时间最多一个活动请求。
- 用户提交后立即创建 IN_PROGRESS Turn。
- 消费 Provider 流并更新当前 Turn。
- 把 thinking/text 增量传给 TUI。
- 处理 PROVIDER_STATE，只保存完整安全状态。
- 正常完成时标记 COMPLETED。
- `Ctrl+C` 中断时关闭流并标记 INTERRUPTED。
- Provider 失败时标记 FAILED。
- 保留用户消息和已有部分助手正文。
- 确保错误提示不进入模型上下文。
- `/clear` 清空所有 Turn，但不改变 `session_id`。
- 记录 Turn 从创建到终态的全部状态变化。

### TUI 模块

由以下组件组成：

1. **状态栏：**显示 ArkCode、配置名称、协议、模型和当前状态；不显示 `base_url` 或 API Key。
2. **Turn 列表：**使用可滚动容器保存进行中和历史 Turn。
3. **Thinking 组件：**使用弱化样式，仅在收到 thinking 事件后创建。
4. **流式 Markdown 组件：**使用 Textual Markdown Stream 合并高频增量。
5. **输入区：**空闲时接受文本和命令；生成期间禁用提交，但保留滚动和 `Ctrl+C`。
6. **状态与错误提示：**展示空闲、请求中、thinking、回答、已中断和错误。

每个 Turn 显示终态；错误提示属于界面元数据，不拼接到 assistant 正文。

### CLI 模块

保留 `arkcode` 和 `python -m arkcode` 两个入口。`main()` 调用启动模块并把结果映射为进程退出码，不包含业务逻辑。

## 模块交互

### 启动流程

```text
CLI
 → 以当前工作目录为 project_root
 → 生成 session_id
 → SessionLogger.create(project_root, session_id)
 → load_config(project_root / ".env")
 → create_provider(config, logger)
 → 创建 Conversation
 → 创建 ConversationManager
 → ArkCodeApp.run()
```

配置或日志初始化失败时，在进入全屏 TUI 前停止。日志初始化成功后记录配置加载、Provider 创建及后续启动节点；日志初始化自身失败时只能向标准错误报告。

### 正常对话

```text
TUI 提交用户文本
 → ConversationManager 生成 turn_id
 → Conversation.start_turn() 立即新增 IN_PROGRESS Turn
 → Conversation.context_messages()
 → ChatProvider.stream()
 → 每个 SSE 事件：
      Provider 记录 raw_event + normalized_event + sequence
      Conversation.apply_stream_event()
      TUI 更新 Thinking 或 Markdown
 → COMPLETED
 → Conversation.finish_turn(COMPLETED)
 → 记录完整聚合结果、上下文状态和耗时
 → TUI 恢复输入
```

### Ctrl+C 中断

```text
TUI 捕获 Ctrl+C
 → ConversationManager.interrupt_current()
 → 关闭当前 Provider SSE 流
 → 保留用户 Message
 → 保留 partial assistant text
 → 保留 TUI 和日志中的 partial thinking
 → 只保存已验证 provider_data
 → Conversation.finish_turn(INTERRUPTED)
 → 下一轮 context_messages() 仍包含用户和部分助手正文
 → TUI 标记“已中断”并恢复输入
```

### Provider 失败

```text
SDK 异常或协议错误
 → ProviderError
 → 记录脱敏原始异常
 → 保留用户 Message
 → 有正文时保留 partial assistant text
 → Conversation.finish_turn(FAILED, safe_message)
 → error_message 只进入 TUI 和日志
 → 下一轮上下文不包含错误提示
 → TUI 恢复输入
```

### Thinking 安全分流

```text
不完整 thinking
 ├── TUI 保留
 ├── JSONL 保留
 ├── 不放入 provider_data
 └── 下一轮不回传

完整可验证 thinking 状态
 ├── TUI 保留
 ├── JSONL 保留
 ├── 通过 PROVIDER_STATE 写入 provider_data
 └── 下一轮按供应商协议回传
```

### `/clear`

```text
TUI 识别完整命令
 → 确认当前没有活动请求
 → Conversation.clear()
 → 清空 Turn 列表
 → 记录 conversation.cleared
 → session_id 和日志文件保持不变
```

### `/quit` 与空闲 Ctrl+C

```text
请求 TUI 退出
 → 停止接收新输入
 → 关闭 Provider
 → 记录 session.ended
 → SessionLogger.close() 排空队列
 → Textual 恢复终端
```

### 运行中日志写入故障

```text
写入线程捕获异常
 → 标记 SessionLogger 故障
 → 线程安全通知主事件循环
 → TUI + stderr 告警
 → 当前模型流继续
 → 禁止递归记录该日志错误
```

## 文件组织

```text
ArkCode/
├── .env.example
├── .gitignore
├── README.md
├── pyproject.toml
├── spec.md
├── plan.md
│
├── src/
│   └── arkcode/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── bootstrap.py
│       ├── config.py
│       │
│       ├── domain/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   └── conversation.py
│       │
│       ├── logging/
│       │   ├── __init__.py
│       │   ├── redaction.py
│       │   └── session_logger.py
│       │
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── factory.py
│       │   ├── anthropic.py
│       │   └── openai.py
│       │
│       ├── conversation/
│       │   ├── __init__.py
│       │   └── manager.py
│       │
│       └── tui/
│           ├── __init__.py
│           ├── app.py
│           ├── prompt.py
│           ├── status_bar.py
│           ├── turn_view.py
│           └── styles.tcss
│
└── tests/
    ├── conftest.py
    ├── test_cli.py
    ├── test_bootstrap.py
    ├── test_config.py
    │
    ├── domain/
    │   └── test_conversation.py
    │
    ├── logging/
    │   ├── test_redaction.py
    │   └── test_session_logger.py
    │
    ├── providers/
    │   ├── test_factory.py
    │   ├── test_anthropic.py
    │   └── test_openai.py
    │
    ├── conversation/
    │   └── test_manager.py
    │
    ├── tui/
    │   └── test_app.py
    │
    ├── fixtures/
    │   ├── anthropic_stream.jsonl
    │   └── openai_stream.jsonl
    │
    └── e2e/
        └── test_real_providers.py
```

运行时生成的 `logs/` 不受版本控制，由启动模块自动创建。

### 文件职责

| 文件 | 职责 |
|---|---|
| `cli.py` | 同步入口和退出码 |
| `bootstrap.py` | 配置、日志、Provider、ConversationManager 和 TUI 生命周期 |
| `config.py` | `.env` 读取、校验和安全表示 |
| `domain/models.py` | Message、ConversationTurn、流事件、响应、错误和枚举 |
| `domain/conversation.py` | Turn 存储、状态变更、上下文投影和 clear |
| `logging/redaction.py` | 递归秘密识别、替换和字段路径 |
| `logging/session_logger.py` | JSONL、队列、线程、flush/close 和故障通知 |
| `providers/base.py` | ChatProvider、统一错误和共用转换辅助 |
| `providers/factory.py` | 按 protocol 创建 Provider |
| `providers/anthropic.py` | Anthropic Messages、adaptive thinking 和 SSE 转换 |
| `providers/openai.py` | OpenAI Responses 和 SSE 转换 |
| `conversation/manager.py` | 生成编排、中断、失败历史保留和状态日志 |
| `tui/app.py` | Textual 生命周期、按键绑定和 Worker |
| `tui/prompt.py` | 输入、提交和最小命令识别 |
| `tui/status_bar.py` | 配置身份和运行状态 |
| `tui/turn_view.py` | 用户、Thinking、Markdown 和 Turn 终态 |
| `tui/styles.tcss` | 专注单栏布局和样式 |
| `.env.example` | 无真实凭据的配置示例 |
| `.gitignore` | 忽略 `.env`、`logs/` 和缓存 |
| `README.md` | 安装、配置、启动、命令、日志和安全说明 |
| `pyproject.toml` | 依赖及测试/lint 配置 |

## 技术决策

### 依赖版本

| 依赖 | 版本范围 | 用途 |
|---|---|---|
| Python | `>=3.10` | 现有项目约束 |
| Textual | `>=8.2.8,<9` | 全屏 TUI、Worker、Markdown 和无头测试 |
| anthropic | `>=0.117.0,<0.118` | Anthropic 官方异步 SDK |
| openai | `>=2.46.0,<3` | OpenAI 官方异步 SDK |
| python-dotenv | `>=1.2.2,<2` | `.env` 读取 |
| pytest | `>=9.1.1,<10` | 测试 |
| pytest-asyncio | `>=1.4,<2` | 异步测试 |
| ruff | `>=0.15.22,<0.16` | lint 和格式化 |

### 项目根目录

启动时的当前工作目录是 project root：

```text
<cwd>/.env
<cwd>/logs/<session_id>.log
```

不向上搜索 `.env`。

### ID

- `session_id` 和 `turn_id` 均使用 UUID v4。
- 日志文件名为 `<session_id>.log`。
- 日志内记录完整 UUID。

### 并发

- Textual 主事件循环负责界面。
- 模型流在 Textual Worker 中运行。
- 同时只允许一个模型请求。
- 日志使用无界 FIFO 队列和单独写入线程。
- 正常关闭时等待日志队列排空。

首版使用无界队列，以同时满足逐事件完整记录和不阻塞流式渲染；日志轮转与背压留待后续。

### 原始 SSE 事件

“原始 SSE 事件”是官方 SDK 解码后、进入 ArkCode 标准化转换前的完整供应商事件对象及其 JSON 等价内容。不记录底层 HTTP 字节、SSE 分隔符或 TCP 数据包。

每个供应商事件只写一条包含 `sequence`、`raw_event` 和 `normalized_event` 的日志。

### 会话事实来源

- 本地 Conversation 是当前进程的会话事实来源。
- OpenAI 不依赖 `previous_response_id` 保存主要历史。
- 正常、中断和失败 Turn 都保留。
- `/clear` 清空全部 Turn。
- 日志不参与会话恢复。

### Provider 状态

`provider_data` 只能由具体 Provider 写入。

- Anthropic 只保存完整 thinking block/signature。
- OpenAI 只保存完整可复用输出 Item。
- 中断正文作为普通 assistant 文本进入下一轮。
- 不完整 thinking 不进入下一轮供应商输入。

### 相邻同角色消息

Conversation 投影可能产生相邻 user Message。Provider 按目标协议归并相邻同角色消息，保持顺序和内容边界，不修改 Conversation。

### 重试与超时

- 两个 SDK 设置 `max_retries=0`。
- 首版不自动重试请求。
- 使用 SDK 的流式连接和读取超时。
- 超时映射为可恢复的 NETWORK ProviderError。

### 输入

- 首版使用单行输入框。
- `Enter` 提交。
- 生成期间禁止再次提交。
- 生成时 `Ctrl+C` 中断，空闲时退出。
- `/clear` 和 `/quit` 只在完整输入匹配时执行。
- 多行编辑和其他命令不在本阶段。

### Markdown

- 每个助手 Turn 使用独立 Markdown 组件。
- 使用 Textual Markdown Stream 合并高频增量。
- Thinking 与正式回答分开。
- 中断和失败状态显示在正文之外。

### 日志刷新

以下边界事件后立即 flush：

- `session.started`
- `request.completed`
- `request.interrupted`
- `request.failed`
- `conversation.cleared`
- `session.ended`

普通 SSE delta 由后台线程顺序写入；退出时强制排空。

### 错误与秘密

- SDK 异常按类型和 HTTP 状态转换，不依赖错误字符串。
- 原始异常脱敏后进入日志。
- TUI 只展示安全错误。
- 日志数据在进入队列前递归脱敏。
- 日志线程故障不得递归写日志。

### 测试

- 领域模型、配置和脱敏器使用单元测试。
- Provider 使用脱敏 JSONL fixture 和假异步 SDK 流。
- ConversationManager 覆盖完成、中断、失败和 thinking 安全状态。
- 日志测试覆盖顺序、flush、并发提交、写入故障和秘密脱敏。
- TUI 使用 Textual Pilot 无头测试。
- 真实 API 测试默认跳过，仅在明确提供凭据时运行。
- 最终在 tmux 中分别使用 Anthropic 与 OpenAI 验收。

## Spec 覆盖

### 功能需求

| Spec | 设计归属 |
|---|---|
| F1 | 配置模块、启动模块 |
| F2–F3 | TUI、CLI |
| F4–F5 | ChatProvider、两个 Provider 实现 |
| F6 | Conversation、ConversationTurn、ConversationManager |
| F7 | AnthropicProvider、Thinking 组件 |
| F8 | ConversationManager、TUI 中断流程 |
| F9 | TurnView、Textual Markdown Stream |
| F10 | ProviderError、失败流程、TUI |
| F11 | `PROVIDER_STATE` 流事件、`provider_data`、thinking 安全分流 |
| F12–F15 | SessionLogger、redaction、bootstrap |

### 非功能需求

| Spec | 设计归属 |
|---|---|
| N1–N2 | Textual 主事件循环、Worker、异步 Provider 流 |
| N3 | ChatProvider 抽象、Provider 工厂 |
| N4 | AppConfig 安全表示、递归脱敏 |
| N5 | 启动编排、Provider/TUI 关闭、日志排空 |
| N6 | macOS/Linux、Python 3.10+ 与 Textual |
| N7 | 分层单元测试、fixture、双 Provider E2E |
| N8 | Conversation 仅内存保存、日志不参与恢复 |
| N9 | `Message`、`ConversationTurn`、`ConversationManager` 命名与职责 |
| N10 | TUI 状态栏与 Turn 终态 |
| N11 | `.gitignore`、SessionLogger |
| N12 | 日志同步初始化、运行时故障通知 |
| N13 | 有序队列、单写入线程、事件 `sequence` |

### 验收标准

| Spec | 验证归属 |
|---|---|
| AC1–AC2 | 配置、启动和 Provider 工厂测试 |
| AC3–AC4 | TUI Pilot、CLI 测试 |
| AC5–AC6 | Anthropic/OpenAI Provider fixture 与真实 E2E |
| AC7 | Anthropic adaptive thinking fixture、TUI Pilot 与真实 E2E |
| AC8 | ConversationManager 中断测试、TUI Pilot |
| AC9 | Markdown Stream 的 TUI Pilot |
| AC10 | Provider 错误分类与失败历史测试 |
| AC11–AC14 | Conversation 上下文投影及完整/不完整 provider state 测试 |
| AC15–AC19 | SessionLogger、脱敏、启动故障和运行时写入故障测试 |

所有功能需求、非功能需求和验收标准均有明确设计或验证归属，依赖方向无环。
