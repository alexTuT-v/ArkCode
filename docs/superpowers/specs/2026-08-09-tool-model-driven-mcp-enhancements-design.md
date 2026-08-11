# 工具层模型驱动与 MCP 增强设计

日期：2026-08-09
状态：待用户评审

## 1. 背景与目标

对照 `mewcode-gap-analysis.md`，ArkCode 缺失的能力集中在两块：

- **工具层模型驱动**：mewcode 用 pydantic `params_model` 作为工具 schema 与校验的
  唯一真相源；ArkCode 是手写 `parameters()` + `execute(args: str)` 内部
  `json.loads`。
- **MCP 增强**：富内容结果、instructions 注入、懒重连/按需连接、工具懒加载
  （`should_defer` + ToolSearch）、类型化参数校验。

目标：将工具层与配置层改为 pydantic 模型驱动（配置层超越 mewcode），补齐 MCP
增强五件套，同时保持全部用户可见契约（工具名称/顺序/只读、`.env` 错误消息、
权限语义、会话 JSONL 磁盘格式）不变。

## 2. 范围

### 2.1 包含

- Phase 1 工具层模型驱动：`Tool.params_model` + `execute(params: BaseModel)` +
  schema 从模型生成；现存 9 个工具类（6 内置 + load/install skill）与 McpTool
  动态模型改造；`registry.execute` 统一解析与校验错误分类。新增工具（ToolSearch）
  在 Phase 4 直接使用该契约。
- Phase 2 配置层模型驱动：`config/models.py`、`mcp/config.py`、
  `permissions/settings.py` 改为 pydantic；错误消息/默认值/宽容行为保持。
- Phase 3 MCP 增强：富内容结果提取、instructions 注入、懒重连/按需连接。
- Phase 4 工具懒加载：`should_defer` / `mark_discovered` / `search_deferred` +
  `ToolSearch` 内置工具 + `definitions()` 过滤。
- 新增依赖 `pydantic>=2`。

### 2.2 排除

- 会话 JSONL 持久化模型化（磁盘格式冻结，不碰）。
- 内部事件/状态模型（`llm/types.py`、`agents/events.py`、`context/state.py`、
  `tui/streaming/state.py`）pydantic 化（纯内部，零收益）。
- `/rewind`、`/worktree`、`/tasks`、`/trace`、hooks、sandbox（均已排除或已完成）。

## 3. 非目标

- 不改变 6 个内置工具的名称、注册顺序与只读分类；契约测试保持通过。
- 不改变 `.env` 字段名、provider 选择行为与 `ConfigError` 错误消息。
- 不改变权限 yaml 语义与"忽略非字符串项"的宽容行为。
- 不改变 `McpTool` 的 `call_timeout=30`、工具命名 `mcp__server__tool` 与
  read-only hint 分类。
- 不自动 git commit（用户手动提交）。

## 4. 总体架构与依赖方向

```text
src/Arkcode/
├── pyproject.toml                      # dependencies 增加 pydantic>=2（修改）
├── tools/
│   ├── base.py                         # params_model / get_schema / execute(params)（修改）
│   ├── registry.py                     # model_validate 收口、defer/discover、definitions 过滤（修改）
│   ├── builtins/{read_file,write_file,edit_file,bash,glob,grep}.py（修改）
│   ├── builtins/tool_search.py         # 新增 ToolSearch 内置工具
│   └── skill_tools/{load_skill,install_skill}.py（修改）
├── mcp/
│   ├── tool_adapter.py                 # 动态参数模型、富内容提取、manager 委托（修改）
│   └── manager.py                      # instructions 提取、get_client、懒重连（修改）
├── config/
│   ├── models.py                       # dataclass → BaseModel（修改）
│   └── loader.py                       # 业务校验/错误消息保留，构造方式换模型（修改）
├── permissions/
│   └── settings.py                     # Settings/PermissionsBlock → BaseModel（修改）
├── application/
│   ├── bootstrap.py                    # 生成 MCP instructions 段落（修改）
│   └── session.py                      # mcp_instructions 参数 + 注入 Agent（修改）
└── tui/
    └── app.py                          # 注册 ToolSearchTool（修改）
```

依赖顺序：Phase 1 → Phase 2 → Phase 3 → Phase 4。Phase 3 的类型化参数由 Phase 1
覆盖；Phase 4 的 ToolSearch 依赖 Phase 1 的工具契约。

## 5. Phase 1：工具层模型驱动

### 5.1 工具契约（`tools/base.py`）

```python
class Tool(ABC):
    params_model: type[BaseModel]          # 新增抽象：每个工具声明参数模型
    should_defer: bool = False             # Phase 4 预置，默认不延迟

    def get_schema(self) -> dict[str, Any]:
        schema = self.params_model.model_json_schema()
        schema.pop("title", None)
        return {"name": self.name(), "description": self.description(), "input_schema": schema}

    async def execute(self, params: BaseModel) -> Result: ...   # args: str → params: BaseModel
```

保留 `read_only` property 与 `name()`/`description()`；移除 `parameters()`。

### 5.2 12 个工具类

Phase 1 改造现存 9 个工具类（`read_file`、`write_file`、`edit_file`、`bash`
（退出码/超时/进程树逻辑保持）、`glob`、`grep`、`load_skill`、`install_skill`）
与 `McpTool`（动态模型，见 5.4）。每个工具新增 `class Params(BaseModel)`，字段与
`Field(description=...)` 逐字对应现有 `parameters()` 的 schema 描述（模型看到的
工具描述文本不变）；execute 内部 `json.loads(args)` 改为直接访问 `params.xxx`。
Phase 4 新增的 `ToolSearch` 直接使用该契约。

### 5.3 registry 收口（`tools/registry.py`）

```python
async def execute(self, name, args, timeout=DEFAULT_TIMEOUT) -> Result:
    tool = self.get(name)
    if tool is None:
        return Result(f"未知工具: {name}", is_error=True)
    try:
        params = tool.params_model.model_validate_json(args)
    except ValidationError as exc:
        return Result(f"参数校验失败: {exc}", is_error=True)
    try:
        return await asyncio.wait_for(tool.execute(params), timeout=timeout)
    except TimeoutError:
        return Result(f"工具 {name} 执行超时（{timeout}s）", is_error=True)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return Result(f"工具 {name} 异常: {exc}", is_error=True)
```

`definitions()` / `read_only_definitions()` 用 `tool.get_schema()` 组装
`ToolDefinition`。Agent、ToolExecutor、providers 零改动（只经 registry）。

### 5.4 McpTool 动态模型（`mcp/tool_adapter.py`）

- `_build_params_model(tool_name, input_schema) -> type[BaseModel]`：properties 的
  type 映射（string→str、integer→int、number→float、boolean→bool、object→dict、
  array→list）；required 字段必填；`pydantic.create_model` 动态生成。
- `McpTool.params_model`（`field(init=False, repr=False)`）在 `__post_init__`
  构建；execute 用 `model_validate_json` 校验、`model_dump(exclude_none=True)`
  传参。

### 5.5 调用点与测试

- src 侧无直接 `tool.execute(args_str)` 调用（唯一入口是 registry）。
- 测试适配：`tests/tools/`、`tests/tui/test_tui_skills.py`、
  `tests/mcp/test_mcp_tool.py` 中约 10+ 处直接 `tool.execute('{...}')` 改为传
  `Params(...)` 或走 registry。
- 新增校验测试：必填缺失、类型错误、额外字段忽略、默认值生效。
- 行为契约：6 内置工具名称/顺序/只读不变；工具 description 文本不变。

## 6. Phase 2：配置层模型驱动

### 6.1 config/models.py

- `ProtocolName = Literal["anthropic", "openai"]` 与 `ConfigError` 不变。
- `ProviderConfig(BaseModel)` / `Config(BaseModel)`：
  `model_config = ConfigDict(frozen=True, extra="ignore")`。
- 字段与默认值逐字照抄：`api_key: str = Field(repr=False)`、`base_url=None`、
  `thinking=False`、`context_window=0`。
- `effective_context_window` 等函数保留原位置与签名。

### 6.2 config/loader.py

所有 `ConfigError` 消息与跨字段校验（provider 去重、必填组合）逐字保留；手动构造
`ProviderConfig(...)` 改为 pydantic 构造；`${VAR}`（如有）展开时机不变。

### 6.3 mcp/config.py

`ServerConfig` / `Config` → BaseModel（frozen + extra="ignore"），默认值照抄；
`_RawServer` 手写校验与全部 `_warn(...)` 跳过消息保留在加载层；`${VAR}` 展开
保留在加载层。

### 6.4 permissions/settings.py

`PermissionsBlock` / `Settings` → BaseModel（extra="ignore"）；`SettingsError` 与
消息保留；**`_strings` 的"忽略列表中的非字符串项"宽容语义必须用
`field_validator` 保留**（pydantic `list[str]` 默认会报错，行为不能变）。

### 6.5 测试

现有 `tests/config/`、`tests/mcp/test_mcp_config.py`、`tests/permissions/` 全部
不改（错误消息/默认值/宽容行为冻结）；新增结构测试：`repr=False` 生效、frozen
不可变、extra="ignore"、permissions 非字符串项被忽略。

## 7. Phase 3：MCP 增强

### 7.1 富内容结果（`mcp/tool_adapter.py`）

`_extract_text(content) -> str`：`TextContent` → 文本；`ImageContent` →
`[image: <mimeType>]`；`EmbeddedResource` → 文本资源取 `resource.text`、二进制取
`[binary resource: <uri>]`。`McpTool.execute` 用它替换"只取文本 + 非文本警告"。

### 7.2 instructions 注入

- `mcp/manager.py`：`_do_connect` 保存 `init_result.instructions`；
  `instructions_text() -> str` 按 server 名排序生成 mewcode 同款段落（有
  instructions 用之，无则列该 server 工具名）。
- `application/bootstrap.py`：连接后生成 `mcp_instructions` 传给 `SessionService`。
- `application/session.py`：新增 `mcp_instructions: str = ""` 构造参数；
  `activate_provider` 创建 Agent 时 `instruction_text` 传
  `基础指令 + MCP 指令段落`（Agent 零改动）。

### 7.3 懒重连 / 按需连接

- `McpTool` 增加 `manager` 引用与 `server_name`（`adapt_tool` 注入），`caller`
  改为运行时从 manager 获取。
- `Manager` 新增 `get_client(name)`（有则返回、无则按需连接）与
  `call_server_tool(name, tool_name, arguments)`（调用抛异常时关闭旧会话、重连、
  重试一次；失败返回错误并更新 `_failures`）。
- 重连实现：cancel 旧连接 task、移除该 server 的 `_sessions`/`_tools` 条目、
  重新 `_connect_one`。
- `McpTool.execute` 委托 `manager.call_server_tool`；超时与参数模型逻辑保持。

## 8. Phase 4：工具懒加载

### 8.1 registry 扩展（`tools/registry.py`）

- `_discovered: set[str]`、`mark_discovered(name)`、`is_discovered(name)`。
- `get_deferred_tool_names() -> list[str]`：`should_defer` 且未 discovered。
- `search_deferred(query, max_results) -> list[dict]`：名称/描述关键词打分排序，
  返回 `{name, description, input_schema}`。
- `find_deferred_by_names(names) -> list[dict]`。
- `definitions()` / `read_only_definitions()` 过滤未发现的延迟工具。

### 8.2 ToolSearch（`tools/builtins/tool_search.py`）

- `params_model`：`query: str`、`max_results: int = 5`；`should_defer = False`。
- execute：`select:<name>[,<name>...]` 精确加载；否则关键词搜索；命中即
  `mark_discovered` 并返回 schema 文本；无匹配时列出可用延迟工具名。

### 8.3 装配与默认

- `McpTool` 覆盖 `should_defer = True`。
- `ArkCodeApp.__init__` 注册 `ToolSearchTool(registry)`（bootstrap 路径自动获得）。
- `new_default_registry()` 不含 ToolSearch 与延迟工具 → 契约测试 6 工具列表不变。
- Agent/ToolExecutor 零改动。

## 9. 错误处理

- 工具参数校验失败：`registry.execute` 返回 `参数校验失败: <错误>`
  （`is_error=True`），不执行工具。
- 配置错误：`ConfigError` / `SettingsError` 消息逐字保留，CLI 行为不变。
- MCP 调用失败：懒重连一次，仍失败则返回错误并更新 `_failures`；超时保持 30s。
- ToolSearch 无匹配：返回可用延迟工具名提示，不报错。

## 10. 测试与验收

- 每 Phase 结束：`pytest -q`、`ruff check .`、`ruff format --check .`、
  `mypy src/Arkcode` 全绿。
- 契约冻结：6 内置工具名称/顺序/只读不变；`.env` 错误消息与 provider 选择不变；
  权限 yaml 语义与宽容行为不变；会话 JSONL 磁盘格式不碰。
- Phase 1 新增：参数校验测试（必填/类型/额外字段/默认值）。
- Phase 2 新增：结构测试（repr/frozen/extra/宽容行为）。
- Phase 3 新增：富内容提取、instructions 段落（含/不含两分支）、懒重连（重试
  一次、失败更新 failures）。
- Phase 4 新增：registry defer/discover、ToolSearch select/搜索/无匹配、McpTool
  should_defer、集成（deferred 工具 select 后进入 definitions）。
- 最终：`python -m Arkcode --version` 输出 `0.1.0`；README 依赖段增加 pydantic。

## 11. 参考实现

- mewcode 工具模型驱动：`mewcode/tools/base.py`（params_model / get_schema /
  execute(params)）、`mewcode/tools/read_file.py`（Params 示例）、
  `mewcode/agent.py`（model_validate 调用点）、`mewcode/mcp/tool_wrapper.py`
  （create_model 动态模型）。
- mewcode 懒加载：`mewcode/tools/__init__.py`（should_defer / mark_discovered /
  search_deferred / find_deferred_by_names）、`mewcode/tools/impl/tool_search.py`。
- mewcode instructions 注入：`mewcode/mcp/client.py`（instructions 属性）、
  `mewcode/remote.py`（段落拼接与注入）。
