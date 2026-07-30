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

## 常见启动错误

- `配置文件不存在: .env`：确认当前目录是项目根目录，并已复制 `.env.example`。
- `ARKCODE_PROVIDERS 不能为空`：至少配置一个 Provider。
- `ARKCODE_<NAME>_API_KEY 不能为空`：为对应 Provider 填写 API Key。
- 协议错误：确认 `PROTOCOL` 为 `anthropic` 或 `openai`。
- 兼容端点无法连接：检查 `BASE_URL` 是否符合服务商要求。

## 开发与验证

安装开发依赖后执行：

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src/Arkcode
```
