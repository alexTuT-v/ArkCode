# 多协议 LLM 终端对话客户端 Checklist

> 每一项通过运行代码或观察行为来验证，聚焦系统行为；括号内为验证方式。

## 实现完整性
- [x] 配置加载：合法根目录 `.env` 能解析出按 `ARKCODE_PROVIDERS` 声明顺序排列的 providers 列表（验证：单测 + 启动进入对话）。(AC1/AC14/F1)
- [x] 配置校验：缺文件/列表/必填字段、非法或重复名称、非法 protocol/thinking 时给出不含密钥的可读错误并非零退出，无未捕获堆栈（验证：单测 + 分别运行 `python -m Arkcode`）。(AC1/AC14/N4)
- [x] `.env` 优先级：`.env` 覆盖同名系统环境变量（验证：预设不同系统变量后加载，断言 `.env` 值生效）。(AC15/F1)
- [x] 配置转换：空 `BASE_URL` 得到 `None`，缺省 `THINKING` 得到 `false`（验证：单测）。(AC15/F1)
- [x] 密钥安全：`ProviderConfig` 的 `repr`、配置错误、CLI/TUI 输出均不出现 API key（验证：单测 + 检索输出）。(AC16/N5)
- [x] 配置文件安全：`.env` 被 git 忽略，`.env.example` 含双 provider 占位示例且无真实密钥（验证：`git check-ignore .env` + 人工检查）。(AC16/N5)
- [x] 单 provider 直进：`.env` 仅声明一条配置时启动直接进入对话（验证：单条配置运行）。(AC2/F2)
- [x] 多 provider 选择：`.env` 声明多条配置时按顺序出现方向键 `OptionList`，选定后进入对话（验证：两条配置运行、上下选择 + Enter）。(AC2/AC14/F2)
- [x] 内置 system prompt 与历史随请求发送（验证：问"你的角色/规则"，回答体现内置 prompt；多轮见 AC6）。(AC4/F4)
- [x] thinking：anthropic 配 `thinking: true` 时启用，且界面不出现任何思考文本（验证：开启后观察仅最终回复）。(AC5/F5)
- [x] 流式逐字：回复以纯文本逐字出现（验证：长回复肉眼可见逐步输出）。(AC5/F8)
- [x] markdown 定型：回复结束后整段以 markdown 渲染（代码块/列表/强调正确）（验证：让模型输出含代码块与列表的内容）。(AC8/F8)
- [x] 多行输入：Alt+Enter 换行、Enter 提交、提交后输入框清空（验证：输入两行后提交）。(AC9/F9)
- [x] 响应计时：自提交即显示 `Imagining… (Ns)` 且秒数递增，结束后显示总耗时（验证：发一条慢回复观察）。(AC12/F12)
- [x] 错误反馈：错误 key/不存在模型时，错误在对话区可区分样式（红色）显示且不退出（验证：改坏 key 运行后再正常发一条）。(AC11/F11)
- [x] 退出：`/exit` 与 Ctrl+C 均能安全退出，终端恢复正常（验证：两种方式各试一次，观察无残留/错乱）。(AC10/F10/N7)
- [ ] 全屏界面布局：启动进入独立全屏 TUI，含猫 banner + 名称版本 + cwd + 就绪提示行 + 输入框（含 `❯` 与占位符）+ 状态栏（左 name 右 model），不与启动前 shell 内容重叠（验证：80×24 启动截图比对）。(AC7/F7)

## 集成
- [ ] TUI 通过统一 `Provider` Protocol 驱动两种协议，切换协议不改变上层交互（验证：分别用 anthropic / openai 配置跑同一组对话，行为一致）。(AC3/N3)
- [x] 多轮上下文携带：先告知信息、后追问，模型能正确引用前文；退出再启动后历史为空（验证：两轮对话 + 重启验证）。(AC6/F6)
- [x] 流式不阻塞：等待/流式期间界面仍响应、不冻结（验证：长回复期间界面持续刷新；asyncio event loop 不阻塞）。(AC13/N1)
- [ ] 应用内会话滚动：banner、用户消息、助手回复和错误均追加到全屏 TUI 的 `RichLog`，
  运行期间可滚动回看；退出后恢复原 shell，不要求把会话保留在 shell 历史中。
- [ ] 80×24 布局：banner 与会话内容可见；`❯` 与输入文字同一行；输入区和状态栏不相交
  （验证：自动化区域断言 + 真实终端截图）。(AC17/F7/N6)
- [x] base_url 覆盖：为某 provider 配自定义 `base_url`（兼容端点）可正常收发（验证：配一个兼容端点跑通一轮）。(F3)
- [ ] 窗口自适应：缩放终端宽度后输入框/对话区/markdown 不错版（验证：运行中调整终端宽度）。(N6)

## 编译与测试
- [x] `python -m Arkcode` 能正常启动（在合法配置下进入 TUI）。
- [x] CLI 从根目录 `.env` 启动，不再读取或回退到 YAML（验证：仅保留 `.env` 时可启动；仅保留旧 YAML 时给出 `.env` 缺失错误）。
- [x] 项目直接依赖包含 `python-dotenv`，不再包含 `pyyaml` / `types-pyyaml`。
- [x] `ruff check .` 无告警。
- [x] `ruff format --check .` 通过（或本地 `ruff format .` 已统一格式）。
- [x] `pytest` 通过（`tests/test_config.py`、`tests/test_conversation.py`）。
- [x] （可选）`mypy src/Arkcode` 通过（启用 strict 子集亦可）。
- [x] 密钥不回显/不打印：对话区与任何输出均不出现 `api_key` 的值（验证：自动化测试 + 通读运行输出）。(AC16/N5)

## 端到端场景
- [ ] 场景 1（anthropic 多轮）：单条 anthropic 配置启动 → 连续两轮、第二轮引用第一轮 → 流式 + 计时 + markdown 定型 → `/exit` 退出。
- [ ] 场景 2（openai 流式）：openai 协议配置 → 发一条含代码块的请求 → 流式逐字后 markdown 渲染正确。
- [ ] 场景 3（多 provider 选择）：`.env` 中声明两条配置 → 启动按声明顺序出现列表 → 选第二条 → 状态栏显示其 name/model → 正常对话。
- [ ] 场景 4（错误恢复）：错误 key 触发失败 → 对话区红色错误、程序不退出 → 修正后（重启）继续正常对话。
