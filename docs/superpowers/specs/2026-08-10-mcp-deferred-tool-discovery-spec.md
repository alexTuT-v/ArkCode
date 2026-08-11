# MCP 延迟工具发现增强 Spec

## 背景

ArkCode 已实现 MCP 工具的延迟暴露：MCP 工具启动时注册到工具注册表，但在被
ToolSearch 发现前不把完整参数 Schema 发送给模型。当前流程存在三个问题：

1. MCP Server 返回的原始 `input_schema` 会先转换为简化的 Pydantic 参数模型，再从
   参数模型重新生成 Schema。这个往返过程可能丢失枚举、字段描述、嵌套约束等信息。
2. ToolSearch 只匹配完整查询文本，包含多个关键词的查询容易漏掉相关工具。
3. 模型只收到通用的延迟工具说明，不一定知道当前具体有哪些工具可供加载。

## 目标

- 模型发现 MCP 工具后，获得 MCP Server 提供的原始输入 Schema。
- ToolSearch 同时支持完整查询和空格分词匹配，并按相关性稳定排序。
- 每轮模型请求通过 `<system-reminder>` 告知模型尚未发现的工具名。
- 延迟工具提醒只存在于当前模型请求，不写入或累积到 Conversation。
- 保持现有 `should_defer → ToolSearch → mark_discovered → 下一轮暴露 Schema`
  主流程不变。

## 功能需求

- F1：MCP 工具对模型暴露 Schema 时，必须使用 MCP Server 返回的原始
  `input_schema`；工具名称和描述仍使用 ArkCode 适配后的名称与描述。工具定义导出和
  ToolSearch 返回结果必须获得同一份原始 Schema。
- F2：延迟工具关键词搜索必须同时执行完整查询匹配和空格分词匹配。完整查询命中名称
  加 10 分、命中描述加 5 分；每个关键词命中名称加 3 分、命中描述加 1 分。只返回
  分数大于 0 的未发现延迟工具，按分数降序排列；同分时保持注册顺序。
- F3：`select:<name>[,<name>...]` 精确选择行为保持不变，不经过关键词评分。空字符串
  或纯空白查询不得发现任何工具，而是返回无匹配结果和当前可用的延迟工具名。
- F4：每次 Agent ReAct 迭代都获取当前尚未发现的延迟工具名。列表非空时生成请求级
  `<system-reminder>`，其中只包含 ToolSearch 使用说明和工具名列表；列表为空时不生成
  该提醒。
- F5：延迟工具提醒必须与现有 Plan Mode 提醒合并。两者同时存在时不能互相覆盖；
  Default Mode 和 Plan Mode 使用同一条请求级提醒通道。
- F6：延迟工具提醒只加入当前模型请求，不得写入 Conversation、Session JSONL 或作为
  对话历史参与上下文压缩。工具被发现后，下一轮提醒不再包含该名称，同时其 Schema
  进入符合当前模式权限的工具定义。
- F7：现有 MCP instructions、工具权限审批、延迟发现状态和工具执行流程保持不变。

## 非功能需求

- N1：原始 MCP `input_schema` 在暴露过程中不得被修改；枚举、描述、嵌套结构、组合
  规则和扩展字段必须完整保留。
- N2：搜索结果必须确定性排序。相同工具注册表、发现状态和查询必须产生相同结果。
- N3：延迟工具提醒只包含工具名，不包含描述或完整 Schema，以控制每轮新增 token。
- N4：动态提醒不得改变稳定 system prompt，避免破坏现有 Anthropic 缓存分块策略。
- N5：功能必须同时适用于 OpenAI 和 Anthropic Provider；协议格式转换仍由各 Provider
  负责，工具注册表不感知 Provider 协议。
- N6：未配置 MCP Server、没有延迟工具或延迟工具已全部发现时，不产生额外提醒，也不
  改变现有请求行为。
- N7：现有内置工具 Schema、工具注册顺序以及非延迟工具搜索行为不得发生变化。

## 不做的事

- 不实现完整的 JSON Schema 运行时校验；MCP 工具执行参数仍暂时使用现有动态
  Pydantic 参数模型校验。
- 不改变 MCP Server 的连接与 `tools/list` 时机；本次仍是 Schema 延迟暴露，不是连接级
  懒加载。
- 不实现向量搜索、模糊搜索、拼写纠错或中文分词，只增加基于空格的关键词评分。
- 不把工具描述、参数摘要或完整 Schema 加入延迟工具提醒。
- 不实现已发现工具的自动卸载、过期或会话级隔离。
- 不改变 MCP Server instructions 的生成和注入逻辑。
- 不禁止模型直接调用尚未发现但名称已知的工具。
- 不重构 Provider 请求协议或改变现有 Plan Mode 提醒的语义。

## 验收标准

- AC1：给定包含 `enum`、字段描述、嵌套对象、数组约束和组合规则的 MCP Schema，模型
  工具定义与 ToolSearch 返回结果完整保留这些字段。
- AC2：搜索 `github issue search` 时，名称或描述分别包含 `github`、`issue`、`search`
  的未发现工具能够被召回，并按约定分数排序。
- AC3：已发现、非延迟或零分工具不进入关键词搜索结果；同分结果保持注册顺序。
- AC4：`select:tool_a,tool_b` 仍能精确发现多个工具，不受分词评分影响；空白查询不发现
  任何工具。
- AC5：首次模型请求的提醒包含当前全部未发现延迟工具名；ToolSearch 发现其中一个后，
  下一轮提醒移除该名称，并且下一轮工具定义包含其原始 Schema。
- AC6：延迟工具提醒不出现在 Conversation 消息和 Session JSONL 中，多次 ReAct 迭代
  不会在历史里累积提醒。
- AC7：Plan Mode 下 Plan 提醒和延迟工具提醒同时传给模型；Default Mode 下只出现需要
  的延迟工具提醒。
- AC8：没有未发现延迟工具时不生成额外提醒，现有无 MCP 场景行为不变。
- AC9：OpenAI 和 Anthropic 请求都能收到相同语义的工具目录与原始工具 Schema，协议
  封装格式符合各自 Provider。
- AC10：工具、MCP、Agent、Prompt 和 Provider 相关测试全部通过。
