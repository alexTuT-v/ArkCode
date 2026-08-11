# MCP 延迟工具发现增强 Checklist

> 每项都通过运行命令或观察真实行为验证；不以阅读实现代码代替验收。

## MCP Schema 保真

- [ ] 复杂 MCP Schema 中的 `enum` 和字段 `description` 完整保留。（验证：运行
  `.venv/bin/pytest tests/mcp/test_mcp_tool.py::test_adapt_tool_preserves_original_complex_input_schema -q`，期望 PASS）
- [ ] 嵌套对象、数组 `items`、`oneOf`、`required` 和 `additionalProperties` 完整保留。
  （验证：同一复杂 Schema 测试对模型可见 `input_schema` 做深度相等断言并 PASS）
- [ ] 空 MCP Schema 仍回退为 `{"type": "object"}`。（验证：运行
  `.venv/bin/pytest tests/mcp/test_mcp_tool.py::test_adapt_tool_rejects_illegal_full_name_and_defaults_empty_schema -q`，期望 PASS）
- [ ] 运行时动态 Pydantic 参数解析保持原行为。（验证：运行
  `.venv/bin/pytest tests/mcp/test_mcp_tool.py::test_build_params_model_maps_types_and_required -q`，期望 PASS）

## 延迟工具搜索

- [ ] 完整 query 命中名称仍加 10 分、命中描述仍加 5 分。（验证：运行
  `tests/tools/test_deferred.py` 中完整 query 排序测试，期望 PASS）
- [ ] 多词 query 能分别命中工具名和描述中的关键词。（验证：搜索
  `github issue search`，期望 `github_issue_search` 和 `github_client` 按约定顺序返回）
- [ ] 每词名称命中加 3 分、描述命中加 1 分，完整 query 与逐词分数可以叠加。（验证：
  运行评分断言测试，实际排序与手算分数一致）
- [ ] 同分结果保持工具注册顺序，`max_results` 正确截断。（验证：运行同分限制测试，
  期望只返回第一个注册工具）
- [ ] 非延迟、已 discovered 和零分工具不进入结果。（验证：运行
  `.venv/bin/pytest tests/tools/test_deferred.py -q`，期望相关过滤测试全部 PASS）
- [ ] 空字符串或纯空白 query 不发现工具，并返回当前可用延迟工具名。（验证：运行
  `.venv/bin/pytest tests/tools/test_tool_search.py::test_tool_search_blank_query_discovers_nothing -q`，期望 PASS）
- [ ] `select:<name>[,<name>...]` 精确发现行为不受评分改动影响。（验证：运行
  `.venv/bin/pytest tests/tools/test_tool_search.py::test_tool_search_select_loads_deferred_tool -q`，期望 PASS）

## 请求级 System Reminder

- [ ] 非空延迟工具目录生成带 `<system-reminder>` 标签的提醒。（验证：运行
  `tests/prompts/test_prompt.py` 的 deferred reminder 测试，期望首尾标签断言 PASS）
- [ ] reminder 只包含固定 ToolSearch 指引和工具名，不包含工具描述或 `input_schema`。
  （验证：纯函数测试检查两个工具名存在且 `input_schema` 不存在）
- [ ] 工具名顺序与 Registry 注册顺序一致。（验证：给定两个有序名称，输出中的索引顺序
  与输入一致）
- [ ] 没有未发现延迟工具时不生成额外 reminder。（验证：
  `deferred_tools_reminder([]) == ""` 测试 PASS）
- [ ] Plan reminder 与 deferred reminder 同时存在时不相互覆盖或嵌套。（验证：运行
  `.venv/bin/pytest tests/agents/test_agent.py::test_plan_and_deferred_reminders_coexist -q`，期望存在两个独立 `<system-reminder>` 块）
- [ ] 没有延迟工具时，现有 Plan reminder 频率和文本逐字保持不变。（验证：运行
  `.venv/bin/pytest tests/agents/test_agent.py::test_plan_reminder_frequency_and_history_isolation -q`，期望 PASS）

## Agent 迭代与状态变化

- [ ] 第一轮请求包含全部未发现延迟工具名，但工具 definitions 不包含其 Schema。（验证：
  Fake Provider 首次捕获的 reminder 包含名称，tools 只包含 ToolSearch）
- [ ] ToolSearch 发现工具后，下一轮 reminder 移除该名称。（验证：运行
  `.venv/bin/pytest tests/agents/test_agent.py::test_deferred_tool_reminder_refreshes_without_entering_history -q`，期望 PASS）
- [ ] 同一下一轮请求的 definitions 包含已发现工具及其原始 Schema。（验证：Agent 测试
  检查第二个 `Request.tools`，并由 MCP Schema 保真测试覆盖具体字段）
- [ ] reminder 不进入 `Conversation.messages()`。（验证：Agent 多轮测试检查所有消息均不
  含 `The following deferred tools`）
- [ ] reminder 不进入 Session JSONL。（验证：运行 Agent/Writer 集成测试后搜索生成的
  `conversation.jsonl`，期望没有延迟工具提醒正文）
- [ ] reminder 不作为历史消息参与上下文压缩。（验证：触发 Agent 自动压缩的测试中，
  compact 输入来自 Conversation，且压缩后历史不含延迟工具提醒正文）
- [ ] 紧急压缩重试复用当前迭代的 reminder。（验证：Fake Provider 首次抛出
  `PromptTooLongError` 后捕获重试 Request，期望 reminder 与首次请求相等）

## Provider 与协议集成

- [ ] Anthropic 请求收到原始 MCP Schema 和请求级 reminder。（验证：运行
  `.venv/bin/pytest tests/llm/test_anthropic_system.py tests/llm/test_providers.py -q`，期望 Anthropic 序列化测试 PASS）
- [ ] OpenAI 请求收到原始 MCP Schema 和请求级 reminder。（验证：运行
  `.venv/bin/pytest tests/llm/test_providers.py -q`，期望 OpenAI function schema 与 reminder 序列化测试 PASS）
- [ ] Registry 未引入 Provider 协议分支。（验证：mypy 和全部 Provider 测试 PASS，且
  OpenAI/Anthropic 使用同一 `ToolDefinition` 输入）
- [ ] MCP instructions 的生成和注入行为保持不变。（验证：运行
  `.venv/bin/pytest tests/mcp/test_instructions.py -q`，期望全部 PASS）
- [ ] MCP 权限审批和工具执行行为保持不变。（验证：运行
  `.venv/bin/pytest tests/mcp/test_mcp_tool.py tests/permissions tests/agents/test_agent.py -q`，期望全部 PASS）

## 代码范围与质量门禁

- [ ] 未增加新的运行时或开发依赖。（验证：`git diff -- pyproject.toml uv.lock` 无本功能
  产生的差异）
- [ ] 未修改 Provider、Conversation、Session、Context 或 MCP Manager 实现。（验证：
  本功能最终 diff 只包含 task 文件清单中的实现与测试文件）
- [ ] 未增加独立评分器、评分类或评分模块。（验证：分词加分只存在于现有
  `Registry.search_deferred()` 方法）
- [ ] 未实现或声称实现完整 JSON Schema 运行时校验。（验证：运行时仍通过
  `params_model.model_validate_json()` 解析工具参数）
- [ ] 聚焦功能测试全部通过。（验证：运行以下命令，期望全部 PASS）

  ```bash
  .venv/bin/pytest tests/mcp/test_mcp_tool.py tests/tools/test_deferred.py tests/tools/test_tool_search.py tests/prompts/test_prompt.py tests/agents/test_agent.py tests/llm/test_anthropic_system.py tests/llm/test_providers.py -q
  ```

- [ ] 全部测试通过。（验证：`.venv/bin/pytest -q` 返回 0）
- [ ] Ruff 检查通过。（验证：`.venv/bin/ruff check src tests` 返回 0）
- [ ] mypy strict 检查通过。（验证：`.venv/bin/mypy src` 返回 0）
- [ ] 没有空白或补丁格式错误。（验证：`git diff --check` 无输出并返回 0）

## 端到端场景

- [ ] 场景 1：Default Mode 发现并调用真实 MCP 工具。验证方式：在 tmux 中启动 ArkCode，
  输入一个需要当前 `context7` MCP Server 的真实文档查询；观察模型首次请求先调用
  ToolSearch，随后使用发现的 `mcp__context7__...` 工具并给出最终答案。
- [ ] 场景 1 的工具参数 Schema 保真。验证方式：在调试输出或 Fake Provider 集成记录中
  检查发现后的工具定义，确认远端 Schema 的描述和约束仍存在。
- [ ] 场景 1 的历史隔离。验证方式：对话完成后检查本次 Session JSONL，确认记录了用户、
  Assistant 和工具调用结果，但没有 `The following deferred tools are available` 文本。
- [ ] 场景 2：Plan Mode 同时提醒。验证方式：在 tmux 中进入 `/plan` 后提出需要 MCP 调研
  的请求；观察模型同时遵守 Plan Mode 只读约束并能通过 ToolSearch 发现只读 MCP 工具，
  不执行写操作。
- [ ] 场景 3：无匹配搜索。验证方式：让 Fake Provider 调用 ToolSearch 并传入不存在的
  关键词；观察结果列出可用未发现工具名，Registry discovered 状态不改变，下一轮 reminder
  仍包含原目录。

## 验收映射

| Spec 验收标准 | Checklist 覆盖 |
|---|---|
| AC1 | MCP Schema 保真 |
| AC2–AC4 | 延迟工具搜索 |
| AC5–AC8 | 请求级 System Reminder、Agent 迭代与状态变化 |
| AC9 | Provider 与协议集成 |
| AC10 | 代码范围与质量门禁、端到端场景 |
