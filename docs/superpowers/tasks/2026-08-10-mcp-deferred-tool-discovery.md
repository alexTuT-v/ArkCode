# MCP 延迟工具发现增强 Tasks

## 文件清单

| 操作 | 文件 | 职责 |
|---|---|---|
| 修改 | `src/Arkcode/mcp/tool_adapter.py` | 让 MCP 工具暴露原始输入 Schema |
| 修改 | `src/Arkcode/tools/registry.py` | 在现有搜索方法中增加分词评分与空白保护 |
| 修改 | `src/Arkcode/prompts/reminders.py` | 生成延迟工具提醒并合并请求提醒 |
| 修改 | `src/Arkcode/prompts/__init__.py` | 导出新增提醒函数 |
| 修改 | `src/Arkcode/agents/agent.py` | 每轮构造请求级延迟工具提醒 |
| 修改 | `tests/mcp/test_mcp_tool.py` | 验证复杂 MCP Schema 保真 |
| 修改 | `tests/tools/test_deferred.py` | 验证分词评分、排序与过滤 |
| 修改 | `tests/tools/test_tool_search.py` | 验证空白搜索和精确选择回归 |
| 修改 | `tests/prompts/test_prompt.py` | 验证提醒纯函数 |
| 修改 | `tests/agents/test_agent.py` | 验证提醒刷新、Plan 共存和历史隔离 |

## T1：建立 MCP Schema 保真失败测试

**文件：** `tests/mcp/test_mcp_tool.py`  
**依赖：** 无

**步骤：**
1. 新增包含 `enum`、字段描述、嵌套对象、数组 `items`、`oneOf` 和
   `additionalProperties` 的 MCP Schema fixture。
2. 使用现有 `_remote_tool()`、`StubSession` 和 `adapt_tool()` 构造工具。
3. 断言 `get_schema()` 的名称和描述使用适配值，`input_schema` 与 fixture 深度相等。
4. 断言工具实例保存的 `input_schema` 未被修改。

**验证：**

```bash
.venv/bin/pytest tests/mcp/test_mcp_tool.py::test_adapt_tool_preserves_original_complex_input_schema -q
```

期望：FAIL，输出显示当前生成 Schema 丢失复杂约束。

## T2：让 McpTool 暴露原始 Schema

**文件：** `src/Arkcode/mcp/tool_adapter.py`  
**依赖：** T1

**步骤：**
1. 在 `McpTool` 中覆盖 `get_schema() -> dict[str, Any]`。
2. 返回适配后的 `full_name`、`tool_description` 和实例原始 `input_schema`。
3. 不修改 `_build_params_model()`、`params_model` 或 `execute()`。
4. 运行 MCP 工具及模型驱动工具回归测试。

**验证：**

```bash
.venv/bin/pytest tests/mcp/test_mcp_tool.py tests/tools/test_model_driven.py -q
```

期望：全部 PASS，空 Schema 回退和运行时 Pydantic 参数解析保持原行为。

## T3：建立延迟搜索分词评分失败测试

**文件：** `tests/tools/test_deferred.py`  
**依赖：** 无

**步骤：**
1. 新增可自定义工具名和描述的 `RankedDeferredTool` 测试类。
2. 新增 `github issue search` 多词查询测试，期望分别命中名称和描述中的关键词。
3. 新增同分工具保持注册顺序且遵守 `max_results` 的测试。
4. 新增纯空白 query 返回空列表的测试。
5. 保留并继续运行已发现工具过滤测试。

**验证：**

```bash
.venv/bin/pytest tests/tools/test_deferred.py -q
```

期望：多词召回和空白 query 测试 FAIL；现有完整 query 测试仍 PASS。

## T4：在现有 search_deferred 中内联分词评分

**文件：** `src/Arkcode/tools/registry.py`  
**依赖：** T3

**步骤：**
1. 对 query 执行 `strip().lower()`；结果为空时立即返回空列表。
2. 使用 `split()` 生成关键词，不创建新的评分函数、类或模块。
3. 保留完整 query 命中名称 `+10`、描述 `+5` 的现有逻辑。
4. 在同一评分循环中增加每词命中名称 `+3`、描述 `+1`。
5. 保留非延迟过滤、已发现过滤、正分过滤、稳定降序排序和结果切片。

**验证：**

```bash
.venv/bin/pytest tests/tools/test_deferred.py -q
```

期望：全部 PASS。

## T5：验证 ToolSearch 空白查询与精确选择

**文件：** `tests/tools/test_tool_search.py`  
**依赖：** T4

**步骤：**
1. 新增空白 query 调用 ToolSearch 的异步测试。
2. 断言结果包含 `No matching deferred tools` 和可用工具名。
3. 断言空白 query 不把工具标记为 discovered。
4. 运行现有 `select:deferred_demo` 测试，确认精确选择不经过评分且仍能加载工具。

**验证：**

```bash
.venv/bin/pytest tests/tools/test_deferred.py tests/tools/test_tool_search.py -q
```

期望：全部 PASS。

## T6：建立请求提醒纯函数失败测试

**文件：** `tests/prompts/test_prompt.py`  
**依赖：** 无

**步骤：**
1. 为 `deferred_tools_reminder()` 新增多工具名测试，断言存在 ToolSearch 和
   `select:<name>[,<name>...]` 指引。
2. 断言提醒按输入顺序逐行列出名称，并且不包含 `input_schema`。
3. 断言空列表返回空字符串且不修改输入列表。
4. 为 `combine_reminders()` 新增过滤空字符串、保持顺序、两个提醒不嵌套的测试。

**验证：**

```bash
.venv/bin/pytest tests/prompts/test_prompt.py -q
```

期望：测试收集阶段因新增函数尚不存在而 FAIL。

## T7：实现延迟工具提醒与提醒合并

**文件：** `src/Arkcode/prompts/reminders.py`、`src/Arkcode/prompts/__init__.py`  
**依赖：** T6

**步骤：**
1. 实现 `deferred_tools_reminder(names: list[str]) -> str`；空列表返回空字符串。
2. 非空列表使用现有 `system_reminder()` 包装固定指引和逐行工具名。
3. 实现 `combine_reminders(*items: str) -> str`，过滤空值后用两个换行连接。
4. 从 Prompt 包公共入口导出两个函数并加入 `__all__`。
5. 不把工具描述、Schema、Provider 格式或模式权限逻辑加入 Prompt 模块。

**验证：**

```bash
.venv/bin/pytest tests/prompts/test_prompt.py -q
.venv/bin/ruff check src/Arkcode/prompts tests/prompts
.venv/bin/mypy src/Arkcode/prompts
```

期望：全部 PASS。

## T8：建立 Agent 延迟提醒刷新失败测试

**文件：** `tests/agents/test_agent.py`  
**依赖：** T2、T5、T7

**步骤：**
1. 注册 `ToolSearchTool` 和一个 `should_defer=True` 的只读测试工具。
2. 使用真实 `Writer` 回调构造 Conversation，并将 JSONL 写入 `tmp_path`。
3. 配置 Fake Provider：第一轮调用 ToolSearch 精确发现工具，第二轮返回最终文本。
4. 断言第一轮 reminder 包含工具名且 definitions 只有 ToolSearch。
5. 断言第二轮 reminder 移除工具名且 definitions 出现已发现工具。
6. 断言 Conversation 所有消息和 `conversation.jsonl` 均不包含延迟工具提醒正文。

**验证：**

```bash
.venv/bin/pytest tests/agents/test_agent.py::test_deferred_tool_reminder_refreshes_without_entering_history -q
```

期望：FAIL，因为 Agent 当前只构造 Plan Mode reminder。

## T9：建立 Plan 与延迟提醒共存失败测试

**文件：** `tests/agents/test_agent.py`  
**依赖：** T7

**步骤：**
1. 在 Plan Mode 测试中注册 ToolSearch 和一个未发现的只读延迟工具。
2. 断言 definitions 只包含当前可见的 ToolSearch。
3. 断言 `Request.reminder` 等于完整 Plan reminder 与 deferred reminder 的合并结果。
4. 断言合并结果包含两个非嵌套 `<system-reminder>` 块。
5. 断言 Conversation 未持久化延迟提醒正文。
6. 新增紧急压缩重试测试：注册一个未发现延迟工具，让 Fake Provider 首次返回
   `PromptTooLongError`、第二次完成摘要、第三次完成主请求。
7. 过滤出两次 `tools is not None` 的主请求，断言 reminder 完全相等且包含延迟工具名。

**验证：**

```bash
.venv/bin/pytest tests/agents/test_agent.py::test_plan_and_deferred_reminders_coexist tests/agents/test_agent.py::test_deferred_reminder_is_reused_for_emergency_retry -q
```

期望：FAIL，因为 Agent 尚未附加 deferred reminder。

## T10：在 Agent 每轮合并请求级提醒

**文件：** `src/Arkcode/agents/agent.py`  
**依赖：** T8、T9

**步骤：**
1. 从 Prompt 公共入口导入 `deferred_tools_reminder` 和 `combine_reminders`。
2. 保留现有 Plan reminder 的完整/精简频率计算。
3. 每次 ReAct 迭代调用 `Registry.get_deferred_tool_names()` 并生成 deferred reminder。
4. 使用 `combine_reminders(plan, deferred)` 构造本轮 `Request.reminder`。
5. 正常请求和同一迭代的紧急压缩重试使用同一份 reminder。
6. 不调用任何 Conversation append 方法，不修改 Provider、Session 或 Context 模块。

**验证：**

```bash
.venv/bin/pytest tests/agents/test_agent.py::test_deferred_tool_reminder_refreshes_without_entering_history tests/agents/test_agent.py::test_plan_and_deferred_reminders_coexist tests/agents/test_agent.py::test_deferred_reminder_is_reused_for_emergency_retry tests/agents/test_agent.py::test_plan_reminder_frequency_and_history_isolation -q
```

期望：全部 PASS。

## T11：运行跨模块功能回归

**文件：** Tasks 中列出的全部实现与测试文件  
**依赖：** T2、T5、T7、T10

**步骤：**
1. 运行 MCP Schema、工具搜索、Prompt、Agent 和 Provider 相关测试。
2. 如果出现失败，只修改本功能文件范围内的直接原因。
3. 确认 Provider 无需实现改动即可发送合并后的 `Request.reminder`。
4. 确认无 MCP 或没有延迟工具时现有 reminder 行为不变。

**验证：**

```bash
.venv/bin/pytest tests/mcp/test_mcp_tool.py tests/tools/test_deferred.py tests/tools/test_tool_search.py tests/prompts/test_prompt.py tests/agents/test_agent.py tests/llm/test_anthropic_system.py tests/llm/test_providers.py -q
```

期望：全部 PASS。

## T12：执行项目质量门禁

**文件：** 全项目  
**依赖：** T11

**步骤：**
1. 运行全部测试。
2. 运行 Ruff 检查。
3. 运行 mypy strict 检查。
4. 运行 `git diff --check` 检查空白错误。
5. 审阅最终 diff，确认没有 Provider、Conversation、Session、Context、MCP 连接时机或
   完整 JSON Schema 运行时校验的范围外改动。

**验证：**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
git diff --check
```

期望：全部命令 PASS。

## 执行顺序

```text
T1 → T2 ───────────────┐
                       │
T3 → T4 → T5 ─────────┼→ T8 → T10 ─┐
                       │             │
T6 → T7 ───────────────┴→ T9 ───────┼→ T11 → T12
```

T1/T2、T3/T4/T5、T6/T7 是三个独立的测试驱动单元；T8 和 T9 汇合这些接口，T10
完成 Agent 集成，最后统一回归和验收。
