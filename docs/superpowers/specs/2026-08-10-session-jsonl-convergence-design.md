# ArkCode Session JSONL 收敛设计

## 状态

- 日期：2026-08-10
- 状态：设计已确认
- 方案：采用 MewCode 的追加式消息日志与结构化压缩边界，适配 ArkCode 的消息类型和目录结构

## 背景

ArkCode 旧版把 `Conversation.replace_history()` 直接绑定到 Session Writer 的
`on_replace()`。上下文 Layer 1 即使没有改变消息，也可能调用
`replace_history()`；Writer 随后写入一条 `compact` 标记，并把当前完整历史重新追加到
JSONL。

样本 `.Arkcode/sessions/20260809-234535-79bd/conversation.jsonl` 中有 154 行，
但最后一个压缩标记后的有效历史只有 22 条消息。文件包含 11 个压缩标记和 121 条重复
消息副本，记录块呈 `1、3、5、7……` 增长。

MewCode 使用不同语义：普通消息只追加一次；真正发生摘要时只追加一条自包含的
`compact_boundary`，恢复时从最后一个有效边界重建历史。本设计让 ArkCode 收敛到这一
模式。

## 目标

1. `conversation.jsonl` 成为按发生顺序追加的事件日志，而不是历史快照集合。
2. 每条普通消息只写入一次，文件大小随真实消息数量线性增长。
3. 真正的上下文摘要只写入一条结构化 `compact_boundary`。
4. 工具结果在进入 Conversation 前完成溢写或预览替换，消息进入历史后不再修改。
5. 任意安全中断后，可以恢复到最后一次成功 `fsync` 的一致状态。
6. JSONL 便于人工阅读，省略空值与无意义的默认字段。
7. Session 列表无需扫描完整 JSONL。

## 非目标

1. 不兼容、不迁移旧版 `compact + 全量快照` Session。
2. 不自动删除旧 Session 文件。
3. 不持久化 thinking、thinking signature 或供应商私有流事件。
4. 不引入通用事件溯源框架；只定义消息与压缩边界两类持久化记录。
5. 不改变 ArkCode 当前 `user`、`assistant`、`tool` 的内部角色模型。

## 总体架构

```text
工具执行
  -> 大结果在进入 Conversation 前完成 spill/preview
  -> 最终 Message 提交给 SessionJournal
  -> Journal append + flush + fsync
  -> Conversation 更新内存历史
  -> SessionMetaStore 更新 meta.json

真正摘要
  -> Context Manager 计算 CompactionResult
  -> Journal 追加一个 CompactBoundary 并 fsync
  -> Conversation 替换为摘要后的内存历史

Resume
  -> SessionLoader 流式读取 JSONL
  -> 从最后一个有效 CompactBoundary 投影
  -> 修复中断的工具调用配对
  -> Conversation.from_messages() 装载但不重新写盘
```

核心约束：

- JSONL 记录已经发生的持久化事件，不记录每次内存检查产生的快照。
- 普通消息一旦进入历史，其内容保持不变。
- `replace_history()` 不具备任何隐式持久化语义。
- 只有成功产出摘要的压缩操作才能写 `compact_boundary`。

## 文件布局

继续使用 ArkCode 的每会话目录：

```text
.Arkcode/sessions/<session-id>/
├── conversation.jsonl
├── meta.json
└── tool-results/
    └── <tool-call-id>.txt
```

旧会话目录没有 `format_version: 2` 的 `meta.json`，不会出现在新版 Session 列表中，
但文件保持原样。

## JSONL 协议

### 普通消息

用户消息：

```json
{"role":"user","content":"查看最新的 Eino 文档","ts":1786290409}
```

助手工具调用：

```json
{"role":"assistant","content":"我先查询文档库 ID。","tool_calls":[{"id":"call_001","name":"mcp__context7__resolve-library-id","arguments":{"libraryName":"eino"}}],"ts":1786290411}
```

工具结果：

```json
{"role":"tool","tool_results":[{"tool_call_id":"call_001","content":"找到 /cloudwego/eino"}],"ts":1786290412}
```

序列化规则：

- `role` 和 `ts` 必填。
- 普通文本消息写 `content`；空 `content` 可以省略。
- 空的 `tool_calls`、`tool_results`、`model` 等字段不写入。
- 成功的工具结果省略 `is_error`；只有错误时写 `"is_error": true`。
- 工具参数以 JSON 对象写入 `arguments`，不保存二次转义的 JSON 字符串。
- 解码为 ArkCode `ToolCall` 时，再将 `arguments` 转为内部需要的 JSON 字符串。
- thinking 和 thinking signature 不落盘。
- 每条记录使用紧凑单行 JSON，保留非 ASCII 字符。

### 压缩边界

```json
{"type":"compact_boundary","role":"system","content":{"summary":"用户查询 Eino 文档，已完成库解析和核心资料读取。","keep":[{"role":"assistant","content":"继续读取快速开始。","tool_calls":[]},{"role":"tool","tool_results":[]}]},"ts":1786290430}
```

`content.summary` 是可直接用于 Resume 的稳定摘要文本：由被压缩前缀的正式摘要与当次
recovery attachment 拼接而成。这样 boundary 写入后即使进程立刻退出，Resume 也能重建
与压缩后内存历史相同的摘要消息。`content.keep` 是摘要后必须原样保留的近期尾部。
`keep` 必须：

- 保持原始消息顺序；
- 保留完整的 `tool_call` 与 `tool_result` 配对；
- 不包含已经完全被摘要替代的旧前缀；
- 使用与普通消息相同的字段格式，但不需要逐条 `ts`。

一次真正压缩只追加一条 boundary。boundary 之后只追加未来新产生的消息，不重写
`keep` 或其他历史。

## Session 元数据

`meta.json` 示例：

```json
{
  "format_version": 2,
  "id": "20260809-234535-79bd",
  "title": "查看最新的 Eino 文档",
  "provider": "anthropic",
  "model": "claude-sonnet-4-5",
  "message_count": 22,
  "total_tokens": 18432,
  "created_at": "2026-08-09T23:45:35+08:00",
  "last_active": "2026-08-09T23:47:31+08:00"
}
```

规则：

- title 来自第一条非空用户消息，按现有展示长度截断。
- `message_count` 统计真实普通消息，不统计 boundary。
- `last_active` 在消息或 boundary 成功写入后更新。
- MetaStore 使用同目录临时文件写入、flush，并通过 `os.replace` 原子替换。
- Session 列表只读取有效且 `format_version == 2` 的 meta。
- meta 损坏的 Session 不进入列表，并记录 warning；正文数据不删除。

## 组件职责

### SessionRecord

负责：

- ArkCode `Message` 与普通 JSONL 记录互转；
- `CompactBoundary` 与 JSONL 记录互转；
- 字段校验和空字段省略。

不负责文件 IO、Session 列表或 Conversation 修改。

### SessionJournal

接口：

```python
class SessionJournal:
    def append_message(self, message: Message) -> None: ...
    def append_boundary(self, boundary: CompactBoundary) -> None: ...
    def close(self) -> None: ...
```

负责线程安全的单行追加、flush、`fsync` 和关闭。编码必须在取得写锁前完成；一次记录通过
一次底层 write 追加，避免同进程并发写产生交叉行。关闭操作幂等，关闭后拒绝新写入。
打开既有 Journal 时如果文件末尾不是换行符，必须先截断到最后一个完整换行边界并
`fsync`，再允许继续追加，避免新记录与崩溃留下的半行粘连。

### SessionMetaStore

负责 `meta.json` 的原子读取与更新。Meta 更新失败不撤销已经成功提交到 Journal 的消息，
而是记录 warning、标记 dirty，并在下一次提交或关闭 Session 时重试。

### SessionLoader

负责流式解析 JSONL、应用最后一个有效 boundary、跳过损坏记录并修复工具调用配对。

### MessageSink 与 Conversation

使用明确协议替代 `on_append/on_replace`：

```python
class MessageSink(Protocol):
    def append_message(self, message: Message) -> None: ...
    def append_boundary(self, boundary: CompactBoundary) -> None: ...
```

Conversation 提供：

```python
conversation.append_message(message)
conversation.apply_compaction(compaction_result)
```

普通消息先由 sink 持久化，成功后才加入内存历史。压缩边界先由 sink 持久化，成功后才替换
内存历史。`Conversation.from_messages(messages, sink=journal)` 初始化时直接装载，不调用
sink。

Conversation 使用同一把提交锁串行化“sink 写入 + 内存更新”，保证并发调用时磁盘记录顺序
与内存消息顺序一致。

## 工具结果生命周期

工具结果采用“消息出生即终态”：

```text
工具返回原始结果
  -> 检查单条结果大小
  -> 检查本批工具结果聚合大小
  -> 必要时幂等写入 tool-results/<tool-call-id>.txt
  -> 用稳定 preview 替换结果正文
  -> 组成最终 tool Message
  -> Journal 持久化
  -> Conversation 追加
```

从 spill 目录回读的结果需要豁免再次溢写，避免模型陷入“回读后再次变成预览”的循环。

如果 spill 文件写入失败，保留原始结果，不生成虚假的“已经保存”提示，并记录 warning。
正确性优先于 JSONL 大小；可能产生的上下文压力交给正常 compact 或 emergency 路径处理。

这一改造后删除每轮对完整历史执行的 `offload_and_snip` 和
`ContentReplacementState`。Prompt Cache 前缀也不会再因为下一轮修改旧消息而失效。

## 上下文压缩生命周期

Context Manager 只计算结果，不直接修改 Conversation：

```python
@dataclass(frozen=True)
class CompactionResult:
    summary: str
    keep: list[Message]
    messages: list[Message]
```

手动、自动和紧急压缩都返回同一种 `CompactionResult`。Agent 收到结果后调用
`conversation.apply_compaction(result)`：

1. 校验 summary、keep 和 messages。
2. 编码完整 boundary。
3. Journal 追加 boundary、flush、fsync。
4. Journal 成功后用 `messages` 替换内存历史。
5. 更新 meta，但 meta 失败不撤销 boundary。

摘要生成失败或 boundary 写入失败时，不修改内存历史。boundary 已成功 `fsync` 后即成为恢复
边界；即使替换内存前进程退出，Resume 也能从其自包含的 summary 和 keep 恢复。

## Resume 算法

加载器维护一个活动投影：

```text
active_messages = []

for record in conversation.jsonl:
  if record is valid normal message:
    active_messages.append(message)
  elif record is valid compact_boundary:
    active_messages = [summary_message, *boundary.keep]
  else:
    warn and skip
```

只有结构完整的 boundary 才能替换活动投影。损坏 boundary 被忽略，因此不会意外清空此前
有效历史。多个有效 boundary 存在时，最后一个自然成为当前投影起点。

摘要恢复为带固定说明前缀的 user 消息，随后接原样 keep 和 boundary 后的新消息。

读取完成后执行工具配对修复：

- 未完成的 assistant tool call：在内存中补一条 `is_error=true` 的 interrupted 结果；
- 孤立 tool result：跳过并 warning；
- 修复结果不自动写回 JSONL，而是在每次 Resume 时确定性生成。

最后一行被截断、单条 JSON 损坏或未知记录均跳过，不修改原文件。

## 错误与一致性策略

### 普通消息

```text
Journal append + fsync
  -> Conversation 更新内存
  -> MetaStore 更新
```

- Journal 失败：消息不进入内存，当前回合停止并向 UI 报告错误。
- Journal 成功、meta 失败：消息保持已提交，回合继续，meta 标记待重试。
- 不允许吞掉 Journal 异常后继续运行。

### 压缩

- 摘要失败：无 boundary、无历史替换。
- boundary 校验或写入失败：无历史替换。
- boundary 成功后崩溃：Resume 从 boundary 恢复。

### 损坏数据

- 损坏普通记录：跳过并 warning。
- 损坏 boundary：忽略并保留此前有效投影。
- 损坏 meta：不展示 Session，但不删除正文。

## 代码改造范围

目标结构：

```text
src/Arkcode/sessions/
├── record.py
├── journal.py
├── meta.py
├── load.py
├── listing.py
├── cleanup.py
└── __init__.py
```

主要调用方调整：

- `conversations/manager.py`：使用 MessageSink，删除 `on_replace`。
- `context/spill.py`：变为工具结果进入历史前的准备步骤。
- `context/manager.py`、`context/summary.py`：返回结构化 CompactionResult。
- `agents/agent.py`：提交最终工具消息并应用压缩结果。
- `application/session.py`：创建、clear、resume、关闭 Journal 和 MetaStore。
- `sessions/listing.py`：只读取新版 meta。
- TUI：只消费应用事件，不直接读写 JSONL，也不维护持久化 history cursor。

删除以下旧机制：

- `Writer.Entry`；
- `Writer.on_replace`；
- `write_compact_marker`；
- `append_all`；
- `"type":"compact"` 旧标记；
- marker 后全量重写历史；
- Loader 遇到旧 compact 清空并等待后续快照的协议；
- `ContentReplacementState`；
- 每轮扫描并修改完整历史的 `offload_and_snip`；
- Conversation 的 `on_replace` 回调；
- Journal 失败只记录 warning 后继续的行为。

## 测试设计

### Codec

- user、assistant、tool 消息往返一致；
- 空字段不写入；
- arguments 以 JSON 对象保存；
- `is_error=false` 省略；
- boundary 的 summary、keep 和工具配对完整往返；
- thinking 与 signature 不落盘。

### Journal

- 并发追加不产生交叉或半行；
- 每条关键记录执行 flush/fsync；
- append 失败后 Conversation 不改变；
- boundary 写入失败后历史不替换；
- close 幂等；
- 关闭后拒绝新写入。

### Resume

- 只有普通消息；
- 一个 boundary 后继续追加；
- 多个 boundary；
- 损坏普通行；
- 损坏 boundary；
- 最后一行截断；
- 未完成 tool call；
- 孤立 tool result；
- keep 边界处的完整工具配对；
- Resume 初始化不重新追加历史。

### Spill

- 单条结果超限时，进入历史前变为 preview；
- 批量结果聚合超限时优先溢写最大项；
- spill 文件回读结果不再次溢写；
- spill 失败保留原始结果；
- JSONL 与 Conversation 保存同一个最终版本。

### Meta 与列表

- 新 Session 写入 `format_version: 2`；
- title、provider、model、时间和计数正确；
- 原子替换不会暴露半截 meta；
- meta 失败不破坏已提交消息；
- 旧格式 Session 不展示；
- 列表按 `last_active` 排序。

### 集成与端到端

- 执行 N 次工具循环后，普通 JSONL 记录数等于真实逻辑消息数；
- 没有摘要时不产生 boundary；
- K 次真实压缩只增加 K 条 boundary；
- Clear 后新旧 Journal 隔离；
- 手动、自动、紧急压缩使用同一协议；
- compact 后继续工具循环仍保持线性增长；
- 使用 Context7/MCP 完成一次多轮真实工具调用；
- 按项目约定用 tmux 完成创建、对话、退出、Resume、继续对话验证。

## 验收标准

1. 与问题样本等价的 22 条逻辑消息只产生 22 条普通记录；没有真正摘要时产生 0 条
   boundary，不再产生 154 行。
2. 任意会话满足：

   ```text
   JSONL 总记录数 = 历史上真实提交的普通消息数 + 成功提交的 boundary 数
   ```

3. 不再出现 `1 + 3 + 5 + ...` 的快照式增长。
4. JSONL 按时间顺序可读，普通消息不重复，空字段不产生噪音。
5. 大工具结果不会先写原文、后通过历史快照写 preview。
6. 任意安全中断后可恢复到最后一次成功 fsync 的状态。
7. TUI 和 Context Manager 不直接操作 JSONL。
8. Session 写入、压缩和恢复拥有独立且完整的自动化测试覆盖。
