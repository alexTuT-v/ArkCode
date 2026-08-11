# ArkCode Memory System Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 ArkCode 长期记忆升级为“每轮自动提取、每轮选择性召回全文、周期整理去重”的轻量闭环，同时保留 JSON action 和 Store 安全边界。

**Architecture:** `Manager` 继续作为记忆门面，`Store` 负责枚举、安全读取和落盘，`MemoryActionService` 统一解析、校验并执行模型返回的 JSON action。新增 `Recall` 和 `Consolidator` 两个小组件；Agent 只负责在明确的 turn 生命周期节点调用门面，不直接操作记忆文件。

**Tech Stack:** Python 3.11+、`asyncio`、dataclasses、PyYAML、pytest、pytest-asyncio；不新增第三方依赖。

## Global Constraints

- 不兼容旧版自动记忆输出格式。
- JSON action 不写入 `conversation.jsonl`，也不追加到记忆 Markdown 正文。
- 不引入向量数据库、Embedding、指纹、相似度算法或持久任务队列。
- 所有模型驱动的写操作必须经过严格 action 校验和 `Store`。
- 召回最多 5 条、最多 25 KiB、等待最多 5 秒。
- 正常退出等待自动提取最多 3 秒。
- 周期整理同时满足 24 小时和新增 5 个 session 才触发。
- 保留工作区现存改动；本计划不执行 Git commit。
- 每项开发完成后先运行聚焦测试，最终运行完整测试和 tmux 端到端验收。

---

## File Map

- Modify: `src/Arkcode/memory/types.py` — 增加 scope、记忆清单项和不可变 turn 输入类型。
- Modify: `src/Arkcode/memory/store.py` — 提供结构化清单、安全读取、公开索引重建及幂等文件操作。
- Create: `src/Arkcode/memory/actions.py` — JSON action 有限容错解析、整批校验、统一执行和模型文本收集。
- Modify: `src/Arkcode/memory/manager.py` — 记忆门面、提取队列、共享写入串行化及子组件装配。
- Create: `src/Arkcode/memory/recall.py` — 候选选择、键校验、安全全文读取和 25 KiB 限制。
- Create: `src/Arkcode/memory/consolidation.py` — 周期条件、状态文件、单任务调度和整理请求。
- Modify: `src/Arkcode/memory/prompts.py` — 提取、召回、整理三类提示词。
- Modify: `src/Arkcode/memory/__init__.py` — 导出新增公共类型。
- Modify: `src/Arkcode/agents/agent.py` — 正常 turn 触发提取，并在主请求前获取召回内容。
- Modify: `src/Arkcode/agents/runtime.py` — 删除仅服务于旧“每 5 轮”策略的 `turn_count`。
- Modify: `src/Arkcode/application/bootstrap.py` — 将 sessions 目录传给记忆 Manager。
- Modify: `src/Arkcode/application/lifecycle.py` — 增加记忆后台任务关闭步骤。
- Modify: `src/Arkcode/application/runtime.py` — 将 memory shutdown 纳入进程关闭顺序。
- Modify: `tests/memory/test_memory.py` — Store 行为与清单测试。
- Create: `tests/memory/test_actions.py` — action 解析、校验和批处理测试。
- Modify: `tests/memory/test_memory_manager.py` — 提取队列、过滤、重试与 flush 测试。
- Create: `tests/memory/test_recall.py` — 召回选择、安全读取、容量与降级测试。
- Create: `tests/memory/test_consolidation.py` — 周期门槛、状态和单任务测试。
- Modify: `tests/agents/test_agent.py` — 正常/异常 turn 触发和召回注入测试。
- Modify: `tests/application/test_runtime.py` — 进程关闭顺序与 3 秒收尾测试。
- Create: `tests/integration/test_memory_lifecycle.py` — 三层记忆链路与 JSONL 不变性集成测试。

---

### Task 1: 结构化记忆清单与安全 Store API

**Files:**
- Modify: `src/Arkcode/memory/types.py`
- Modify: `src/Arkcode/memory/store.py`
- Modify: `src/Arkcode/memory/__init__.py`
- Modify: `tests/memory/test_memory.py`

**Interfaces:**
- Produces: `MemoryScope`, `MemoryEntry`, `MemoryTurn`。
- Produces: `Store.list_entries(scope) -> list[MemoryEntry]`。
- Produces: `Store.read(filename) -> str`。
- Produces: `Store.rebuild_index() -> None`。
- Produces: `Store.validate_filename(filename) -> None` 和 `Store.validate_slug(slug) -> None`。
- Consumes: 现有 Markdown frontmatter 和 `_FILENAME_RE` / `_SLUG_RE` 规则。

- [ ] **Step 1: 为清单、安全读取和同名 create 写失败测试**

在 `tests/memory/test_memory.py` 增加：

```python
from Arkcode.memory import MemoryScope


def test_store_lists_structured_entries_and_reads_by_valid_filename(
    tmp_path: Path,
) -> None:
    store = Store(str(tmp_path / "memory"))
    store.apply([
        UpdateAction(
            action="create",
            level="user",
            type="user_preference",
            title="回答语言",
            slug="response_language",
            content="用户偏好中文回答。",
        )
    ])

    entries = store.list_entries(MemoryScope.USER)

    assert len(entries) == 1
    assert entries[0].key == "user:user_preference_response_language.md"
    assert entries[0].preview == "用户偏好中文回答。"
    assert "用户偏好中文回答" in store.read(entries[0].filename)


def test_store_read_rejects_path_escape(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))

    with pytest.raises(ValueError, match="非法记忆文件名"):
        store.read("../secret.md")


def test_same_name_create_updates_and_preserves_created(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "memory"))
    first = UpdateAction(
        action="create",
        level="user",
        type="user_preference",
        title="语言",
        slug="language",
        content="中文。",
    )
    store.apply([first])
    path = tmp_path / "memory" / "user_preference_language.md"
    created = Store._parse_note(path)[0]["created"]

    store.apply([UpdateAction(**{**first.__dict__, "content": "简体中文。"})])

    metadata, content = Store._parse_note(path)
    assert metadata["created"] == created
    assert content == "简体中文。"
```

- [ ] **Step 2: 运行聚焦测试并确认失败原因**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_memory.py -q
```

Expected: 新测试因 `MemoryScope`、`list_entries`、`read` 尚不存在以及同名 create 重置 `created` 而失败。

- [ ] **Step 3: 增加公共数据类型**

在 `src/Arkcode/memory/types.py` 增加：

```python
from enum import StrEnum


class MemoryScope(StrEnum):
    PROJECT = "project"
    USER = "user"


@dataclass(frozen=True)
class MemoryEntry:
    scope: MemoryScope
    type: NoteType
    filename: str
    title: str
    preview: str
    updated_at: str

    @property
    def key(self) -> str:
        return f"{self.scope.value}:{self.filename}"


@dataclass(frozen=True)
class MemoryTurn:
    session_id: str
    turn_id: str
    user_text: str
    assistant_text: str
```

将这些类型加入 `memory.__all__`。

- [ ] **Step 4: 实现 Store 的清单、安全读取和幂等 create**

在 `Store` 中把原私有校验改为公共静态方法，并作为所有读写入口的前置条件：

```python
@staticmethod
def validate_filename(filename: str) -> None:
    if not _FILENAME_RE.fullmatch(filename):
        raise ValueError(f"非法记忆文件名: {filename}")

@staticmethod
def validate_slug(slug: str) -> None:
    if not _SLUG_RE.fullmatch(slug):
        raise ValueError(f"非法记忆 slug: {slug}")

def read(self, filename: str) -> str:
    self.validate_filename(filename)
    return (self._dir / filename).read_text(encoding="utf-8")

def list_entries(self, scope: MemoryScope) -> list[MemoryEntry]:
    entries: list[MemoryEntry] = []
    for path in sorted(self._dir.glob("*.md")):
        if path.name == "MEMORY.md" or not _FILENAME_RE.fullmatch(path.name):
            continue
        metadata, content = self._parse_note(path)
        entries.append(MemoryEntry(
            scope=scope,
            type=NoteType(str(metadata["type"])),
            filename=path.name,
            title=str(metadata.get("title", path.stem)),
            preview=" ".join(content.split())[:100],
            updated_at=str(metadata.get("updated", "")),
        ))
    return entries[:200]

def rebuild_index(self) -> None:
    with self._lock:
        self.ensure_dir()
        self._rebuild_index()
```

调整 `create` 分支：如果目标文件存在，读取原 metadata、保留 `created`、更新 `title`、`updated` 和完整正文；不存在时才创建 metadata。

- [ ] **Step 5: 运行 Store 测试**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_memory.py tests/memory/test_store_clear.py -q
```

Expected: PASS。

- [ ] **Step 6: Review checkpoint**

确认新 API 不暴露绝对路径、`MEMORY.md` 不出现在清单中，并确认本任务没有修改 conversation/session 文件。

---

### Task 2: JSON action 有限容错、整批校验与统一执行

**Files:**
- Create: `src/Arkcode/memory/actions.py`
- Modify: `src/Arkcode/memory/manager.py`
- Create: `tests/memory/test_actions.py`
- Modify: `tests/memory/test_memory_manager.py`

**Interfaces:**
- Consumes: `Store.apply(actions)`、`Store.rebuild_index()`。
- Produces: `parse_actions(raw: str) -> list[UpdateAction]`。
- Produces: `validate_actions(actions: list[UpdateAction]) -> None`。
- Produces: `collect_text(provider: Provider, request: Request) -> str`。
- Produces: `MemoryActionService.execute(system_prompt: str, payload: dict[str, object]) -> bool`。

- [ ] **Step 1: 写 action 解析与整批拒绝测试**

创建 `tests/memory/test_actions.py`，至少包含：

```python
def test_parse_accepts_plain_array_and_single_json_fence() -> None:
    raw = '[{"action":"delete","level":"user",' \
        '"type":"user_preference","filename":"user_preference_old.md"}]'
    assert parse_actions(raw)[0].action == "delete"
    assert parse_actions(f"```json\n{raw}\n```") == parse_actions(raw)


@pytest.mark.parametrize("raw", [
    "{}",
    "[1]",
    "[] []",
    '[{"action":"erase","level":"user","type":"user_preference"}]',
    '[{"action":"delete","level":"users",' \
    '"type":"user_preference","filename":"user_preference_old.md"}]',
])
def test_parse_rejects_invalid_batch(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_actions(raw)


@pytest.mark.asyncio
async def test_validation_happens_before_any_store_write(tmp_path: Path) -> None:
    service = action_service(tmp_path,
        '[{"action":"create","level":"user",' \
        '"type":"user_preference","title":"语言","slug":"language",' \
        '"content":"中文"},{"action":"delete","level":"user",' \
        '"type":"user_preference","filename":"../bad.md"}]'
    )

    assert await service.execute("prompt", {}) is False
    assert not list((tmp_path / "user").glob("*.md"))
```

测试模块内定义以下最小替身，避免依赖真实 Provider：

```python
class TextProvider:
    name = "fake"
    model = "memory-model"

    def __init__(self, text: str) -> None:
        self.text = text

    async def stream(self, request: Request) -> AsyncIterator[object]:
        yield TextDelta(self.text)
        yield StreamEnd("end")


def action_service(tmp_path: Path, text: str) -> MemoryActionService:
    return MemoryActionService(
        Store(str(tmp_path / "project")),
        Store(str(tmp_path / "user")),
        TextProvider(text),
        "memory-model",
    )
```

- [ ] **Step 2: 运行 action 测试确认失败**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_actions.py -q
```

Expected: FAIL，因为 `actions.py` 尚不存在。

- [ ] **Step 3: 实现严格解析和字段校验**

`src/Arkcode/memory/actions.py` 使用 `json.JSONDecoder.raw_decode`，规则固定为：去除包裹整个输出的单层 `json` fence；从第一个 `[` 开始解析一个数组；若剩余文本还能找到第二个 `[` 则拒绝；随后校验每个对象。

核心接口：

```python
_ACTIONS = {"create", "update", "delete"}


def parse_actions(raw: str) -> list[UpdateAction]:
    text = _strip_json_fence(raw.strip())
    start = text.find("[")
    if start < 0:
        raise ValueError("记忆更新响应必须包含 JSON 数组")
    value, consumed = json.JSONDecoder().raw_decode(text[start:])
    if "[" in text[start + consumed:]:
        raise ValueError("记忆更新响应包含多个 JSON 数组")
    if not isinstance(value, list):
        raise ValueError("记忆更新响应必须是 JSON 数组")
    actions = [_parse_action(item) for item in value]
    validate_actions(actions)
    return actions
```

校验要求：所有 action 必须有合法 `level` 和 `type`；`create` 必须有非空 `title`、`slug`、`content`；`update` 必须有合法 `filename` 和非空 `content`；`delete` 必须有合法 `filename`；`update/delete` 的文件名前缀必须与 `type` 相同。文件名和 slug 校验复用 `Store.validate_filename` / `Store.validate_slug`，不在 action 层复制正则。

- [ ] **Step 4: 实现统一模型调用和执行服务**

`MemoryActionService` 持有两个 Store、Provider/model 和一个共享 `asyncio.Lock`：

```python
class MemoryActionService:
    def set_provider(self, provider: Provider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def execute(
        self,
        system_prompt: str,
        payload: dict[str, object],
    ) -> bool:
        async with self._lock:
            if self._provider is None:
                return False
            raw = await collect_text(self._provider, Request(
                messages=[Message(role="user", content=json.dumps(
                    {"model": self._model, **payload}, ensure_ascii=False
                ))],
                tools=None,
                system=System(stable=system_prompt),
            ))
            actions = parse_actions(raw)
            try:
                self._project.apply([
                    item for item in actions if item.level == "project"
                ])
                self._user.apply([
                    item for item in actions if item.level == "user"
                ])
            finally:
                try:
                    self._project.rebuild_index()
                finally:
                    self._user.rebuild_index()
            return True
```

公共 `collect_text` 只收集 `TextDelta`，遇到 `StreamError` 抛出其 error，供 action、recall 共用。`execute` 在边界捕获异常、记录日志并返回 `False`；合法 `[]` 返回 `True`。

- [ ] **Step 5: 让 Manager 使用 ActionService**

`Manager` 构造时创建一个 `MemoryActionService`；`set_provider` 同步更新 service；保留 `load_index`、`list_files`、`clear` 和 `dirs` 的公共行为。先将现有 `update_async` 改为调用 service，保证既有调用在 Task 3 替换前仍可测试。

- [ ] **Step 6: 运行 action 和现有记忆测试**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_actions.py tests/memory/test_memory.py tests/memory/test_memory_manager.py -q
```

Expected: PASS；非法批次没有产生任何记忆文件。

- [ ] **Step 7: Review checkpoint**

检查代码不存在向 session journal 写 action 的调用；检查未知 level 不会再被静默过滤；检查所有业务字段在文件操作前已经验证。

---

### Task 3: 每个自然 turn 的单活跃自动提取

**Files:**
- Modify: `src/Arkcode/memory/manager.py`
- Modify: `src/Arkcode/memory/prompts.py`
- Modify: `src/Arkcode/agents/agent.py`
- Modify: `src/Arkcode/agents/runtime.py`
- Modify: `tests/memory/test_memory_manager.py`
- Modify: `tests/agents/test_agent.py`
- Modify: `tests/agents/test_agent_runtime.py`

**Interfaces:**
- Consumes: `MemoryActionService.execute(...)`。
- Produces: `Manager.schedule_extract(turn: MemoryTurn) -> None`。
- Produces: `Manager.flush_extraction(timeout: float = 3.0) -> None`。
- Produces: `Manager.has_pending_extraction() -> bool`，仅用于生命周期测试和诊断。

- [ ] **Step 1: 写语义输入、串行 pending 和一次重试测试**

在 `tests/memory/test_memory_manager.py` 使用可阻塞 Provider，验证：

```python
@pytest.mark.asyncio
async def test_extract_coalesces_turns_arriving_while_active(tmp_path: Path) -> None:
    provider = BlockingSequenceProvider([valid_empty(), valid_empty()])
    manager = make_manager(tmp_path, provider)
    manager.schedule_extract(turn("s1", "t1", "用户一", "回答一"))
    await provider.first_started.wait()
    manager.schedule_extract(turn("s1", "t2", "用户二", "回答二"))
    manager.schedule_extract(turn("s1", "t3", "用户三", "回答三"))
    provider.release_first.set()
    await manager.flush_extraction()

    assert provider.peak_active == 1
    assert "用户一" in provider.payloads[0]
    assert "用户二" in provider.payloads[1]
    assert "用户三" in provider.payloads[1]


@pytest.mark.asyncio
async def test_extract_retries_failed_batch_once_on_next_trigger(
    tmp_path: Path,
) -> None:
    provider = SequenceProvider([
        RuntimeError("down"),
        valid_empty(),
        valid_empty(),
    ])
    manager = make_manager(tmp_path, provider)
    batch = turn("s1", "t1", "用户", "回答")
    manager.schedule_extract(batch)
    first_task = manager._extract_task
    assert first_task is not None
    await first_task
    assert manager.has_pending_extraction()

    manager.schedule_extract(turn("s1", "t2", "继续", "好的"))
    await manager.flush_extraction()

    assert provider.call_count == 3
    assert not manager.has_pending_extraction()


@pytest.mark.asyncio
async def test_twice_failed_batch_does_not_block_new_turn(tmp_path: Path) -> None:
    provider = SequenceProvider([
        RuntimeError("down-1"),
        RuntimeError("down-2"),
        valid_empty(),
    ])
    manager = make_manager(tmp_path, provider)
    manager.schedule_extract(turn("s1", "old", "旧问题", "旧回答"))
    first_task = manager._extract_task
    assert first_task is not None
    await first_task

    manager.schedule_extract(turn("s1", "new", "新问题", "新回答"))
    await manager.flush_extraction()

    assert provider.call_count == 3
    assert "新问题" in provider.payloads[2]
    assert not manager.has_pending_extraction()
```

另加断言，提取 payload 只有 `session_id`、`turn_id`、`user_text`、`assistant_text` 和结构化 memory manifest，不含 tool calls、thinking 或完整 conversation。

测试模块提供：`valid_empty()` 返回 `[]`；`turn(...)` 构造 `MemoryTurn`；`make_manager(tmp_path, provider)` 用临时 project/user 目录构造并注入 Provider；`SequenceProvider` 按列表顺序返回字符串或抛出异常；`BlockingSequenceProvider` 在第一次调用中设置 `first_started`、等待 `release_first`，并记录 `peak_active` 与请求 payload。它们均沿用现有测试中的 `MemoryProvider` 流式协议。

- [ ] **Step 2: 写 Agent 正常与异常触发测试**

更新 `MemorySpy` 为同步调度接口：

```python
class MemorySpy:
    def __init__(self) -> None:
        self.turns: list[MemoryTurn] = []
        self.recall_queries: list[str] = []

    async def recall(self, query: str) -> str:
        self.recall_queries.append(query)
        return ""

    def schedule_extract(self, turn: MemoryTurn) -> None:
        self.turns.append(turn)

    def schedule_consolidation(self) -> None:
        pass
```

新增参数化测试，普通最终文本恰好调度一次；cancel、Provider error、空 `stream_state.text`、max iteration 和未知工具终止均为零次。普通消息不再依赖关键词或第 5 轮。

- [ ] **Step 3: 运行测试确认旧行为失败**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_memory_manager.py tests/agents/test_agent.py -q
```

Expected: FAIL，旧 Agent 仍按关键词/第 5 轮调用 `update_async`，Manager 也没有 pending 协调器。

- [ ] **Step 4: 实现 Manager 的 active + pending 协调器**

Manager 保存：

```python
self._pending_turns: list[MemoryTurn] = []
self._retry_batch: tuple[list[MemoryTurn], int] | None = None
self._extract_task: asyncio.Task[None] | None = None
```

`schedule_extract` 只把不可变 turn 加入 pending，并确保最多存在一个 `_drain_extraction()` task。drain 先处理 retry batch，再原子取走当前 pending；失败一次保存为 `(batch, 1)` 后退出；下一次触发失败则丢弃该 retry batch并继续后续 pending。成功的 `[]` 和成功 actions 都清除当前 batch。

提取系统提示常量命名为 `MEMORY_EXTRACTION_SYSTEM_PROMPT`。提取 payload 固定为：

```python
{
    "existing_memories": [asdict(entry) for entry in self.list_entries()],
    "turns": [asdict(turn) for turn in batch],
}
```

`flush_extraction(3.0)` 在有 pending 但没有 task 时启动 drain，再使用 `asyncio.wait_for` 等待；超时记录日志并取消等待，不向上抛异常。

- [ ] **Step 5: 替换 Agent 的旧触发器**

删除 `_recent_turn`、`_has_memory_signal` 和 `% 5` 判断。`_run_unlocked` 开始时捕获本轮真实用户文本；只有 `stream_state.text` 非空且没有 tool calls 的自然完成分支才创建：

```python
MemoryTurn(
    session_id=self.runtime.session.session_id,
    turn_id=uuid.uuid4().hex,
    user_text=current_user_text,
    assistant_text=stream_state.text,
)
```

然后调用 `manager.schedule_extract(turn)`。删除 `SessionRuntime.turn_count` 及其 reset 逻辑，避免 resume session 继承错误计数。

删除过渡期的 `Manager.update_async`，所有调用点和测试统一改用 `schedule_extract` / `flush_extraction`。

- [ ] **Step 6: 运行提取与 Agent 测试**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_memory_manager.py tests/agents/test_agent.py tests/agents/test_agent_runtime.py -q
```

Expected: PASS；普通每轮触发，异常结束均不触发，最大并发为 1。

- [ ] **Step 7: Review checkpoint**

检查没有裸 `asyncio.create_task(manager.update_async(...))`；所有提取 task 均由 Manager 强引用；提取 payload 不再使用 `asdict(Message)`。

---

### Task 4: 最多 5 条的选择性全文召回

**Files:**
- Create: `src/Arkcode/memory/recall.py`
- Modify: `src/Arkcode/memory/prompts.py`
- Modify: `src/Arkcode/memory/manager.py`
- Modify: `src/Arkcode/agents/agent.py`
- Create: `tests/memory/test_recall.py`
- Modify: `tests/agents/test_agent.py`

**Interfaces:**
- Consumes: `Store.list_entries(scope)`、`Store.read(filename)`、Provider。
- Consumes: `collect_text(provider, request)`。
- Produces: `Recall.select(query: str) -> str`。
- Produces: `Manager.recall(query: str) -> str`。

- [ ] **Step 1: 写候选键、数量、容量和降级测试**

创建 `tests/memory/test_recall.py`：

```python
@pytest.mark.asyncio
async def test_recall_reads_only_unique_known_keys(tmp_path: Path) -> None:
    recall = make_recall(
        tmp_path,
        response='["user:user_preference_language.md", '
                 '"user:user_preference_language.md", "user:../../secret.md"]',
    )

    text = await recall.select("应该用什么语言回答？")

    assert text.count("用户偏好中文") == 1
    assert "secret" not in text


@pytest.mark.asyncio
async def test_recall_limits_selection_to_five_and_25_kib(tmp_path: Path) -> None:
    recall = make_six_large_memories(tmp_path)
    text = await recall.select("相关内容")

    assert text.count("<memory key=") == 5
    assert len(text.encode("utf-8")) <= 25 * 1024


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid-json", "stream-error", "timeout"])
async def test_recall_failure_returns_empty_text(
    tmp_path: Path,
    failure: str,
) -> None:
    assert await make_failing_recall(tmp_path, failure).select("query") == ""
```

测试模块定义与 `test_actions.py` 相同流式协议的本地 `TextProvider`。`make_recall` 创建一条合法 user 记忆并注入返回指定字符串的 Provider；`make_six_large_memories` 创建 6 条不同 filename、每条正文超过 6 KiB 的记忆并让 Provider 返回全部 6 个 key；`make_failing_recall` 分别返回非法 JSON、产生 `StreamError`、或阻塞超过通过构造参数注入的 0.01 秒测试 timeout。生产默认 timeout 仍为 5 秒。

- [ ] **Step 2: 运行召回测试确认失败**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_recall.py -q
```

Expected: FAIL，因为 `Recall` 尚不存在。

- [ ] **Step 3: 实现 Recall**

`Recall` 构造参数为两个 Store、可空 Provider、model 和 `timeout_seconds: float = 5.0`；`set_provider` 与 Manager 同步。`select` 将 query 和 manifest 传给 `MEMORY_RECALL_SYSTEM_PROMPT` 指定的无工具模型请求，使用 `asyncio.timeout(self._timeout_seconds)` 包裹完整响应。

模型响应只接受 JSON 字符串数组。处理规则：按返回顺序、只接受当前 manifest 的精确 key、去重、截取前 5 个；用 scope 找 Store，再调用 `Store.read(filename)`；组合后的 reminder 使用：

```text
<system-reminder>
Relevant long-term memories (read-only):
<memory key="user:user_preference_language.md">
完整 Markdown
</memory>
</system-reminder>
```

按 UTF-8 字节计算 25 KiB；超过时仅截断最后一个 memory block，并附加 `(memory truncated)`。

- [ ] **Step 4: 将 Recall 装配到 Manager**

Manager 增加：

```python
async def recall(self, query: str) -> str:
    return await self._recall.select(query)
```

`set_provider` 同时更新 action service 和 Recall。无 Provider、空 manifest 或空 query 时直接返回空字符串，不发请求。

- [ ] **Step 5: 在 Agent 主请求前完成一次召回**

在 `_run_unlocked` 捕获当前用户文本后调用 `await manager.recall(current_user_text)`。召回返回的 reminder 只计算一次，并在当前 ReAct turn 的每次 Provider Request 中通过：

```python
reminder = combine_reminders(recall_text, plan, deferred)
```

复用同一字符串，不把它加入 `Conversation`，因此不会写入 `conversation.jsonl`，也不会进入自动提取 batch。

- [ ] **Step 6: 增加 Agent 注入测试**

在 `tests/agents/test_agent.py` 令 MemorySpy 返回唯一 recall marker，并断言：

```python
assert memory.recall_queries == ["当前问题"]
assert "unique recalled memory" in provider.requests[0].reminder
assert all(
    "unique recalled memory" not in message.content
    for message in conversation.messages()
)
```

另测 MemorySpy 返回空字符串时原有 `load_index()` 仍出现在 stable system。

- [ ] **Step 7: 运行召回与 Agent 测试**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_recall.py tests/agents/test_agent.py -q
```

Expected: PASS。

- [ ] **Step 8: Review checkpoint**

检查 manifest 和允许键都使用完全相同的 `scope:filename`；不存在绝对路径；Recall 没有文件写入能力。

---

### Task 5: 24 小时且新增 5 个 session 的周期整理

**Files:**
- Create: `src/Arkcode/memory/consolidation.py`
- Modify: `src/Arkcode/memory/prompts.py`
- Modify: `src/Arkcode/memory/manager.py`
- Modify: `src/Arkcode/agents/agent.py`
- Modify: `src/Arkcode/application/bootstrap.py`
- Create: `tests/memory/test_consolidation.py`
- Modify: `tests/agents/test_agent.py`

**Interfaces:**
- Consumes: `MemoryActionService.execute(...)`、`Store.list_entries/read`、`list_sessions(...)`。
- Produces: `Consolidator.schedule() -> None`。
- Produces: `Consolidator.shutdown() -> None`。
- Produces: `Manager.schedule_consolidation() -> None`。

- [ ] **Step 1: 写门槛、单任务和状态推进测试**

创建 `tests/memory/test_consolidation.py`，使用注入的 `now` 和 action service spy：

```python
def test_due_requires_both_24_hours_and_five_new_sessions(tmp_path: Path) -> None:
    state = ConsolidationState(
        last_success="2026-08-09T10:00:00+08:00",
        session_count=10,
    )
    assert not is_due(state, now("2026-08-10T09:59:59+08:00"), 15)
    assert not is_due(state, now("2026-08-10T10:00:00+08:00"), 14)
    assert is_due(state, now("2026-08-10T10:00:00+08:00"), 15)


@pytest.mark.asyncio
async def test_schedule_runs_only_one_consolidation(tmp_path: Path) -> None:
    service = BlockingActionService()
    consolidator = make_due_consolidator(tmp_path, service)
    consolidator.schedule()
    consolidator.schedule()
    await service.started.wait()
    assert service.calls == 1
    service.release.set()
    await consolidator.shutdown()


@pytest.mark.asyncio
async def test_failed_run_does_not_advance_state(tmp_path: Path) -> None:
    consolidator = make_due_consolidator(tmp_path, FailingActionService())
    before = consolidator.load_state()
    consolidator.schedule()
    await consolidator.shutdown()
    assert consolidator.load_state() == before
```

另测成功时 `.consolidation-state.json` 写入当前成功时间和 session 文件总数；损坏或缺失状态按 `last_success=epoch, session_count=0` 处理。

测试模块中的 `now(value)` 使用 `datetime.fromisoformat(value)`；`BlockingActionService.execute` 设置 `started` 后等待 `release` 并返回 `True`；`FailingActionService.execute` 直接返回 `False`；`make_due_consolidator` 创建 5 个合法 format v2 session 目录并注入 epoch state，使 due 条件确定成立。

- [ ] **Step 2: 运行整理测试确认失败**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_consolidation.py -q
```

Expected: FAIL，因为 consolidation 模块尚不存在。

- [ ] **Step 3: 实现状态和 due 判断**

使用明确类型：

```python
@dataclass(frozen=True)
class ConsolidationState:
    last_success: str
    session_count: int


def is_due(
    state: ConsolidationState,
    now: datetime,
    current_session_count: int,
) -> bool:
    last = datetime.fromisoformat(state.last_success)
    return (
        now - last >= timedelta(hours=24)
        and current_session_count - state.session_count >= 5
    )
```

状态文件固定为项目记忆目录下 `.consolidation-state.json`。读取失败返回 epoch state；保存先写同目录临时文件，再 `os.replace`，不生成 action 日志。

- [ ] **Step 4: 实现 Consolidator 单任务调度**

`Consolidator` 保存 stores、sessions_dir、action service、state path 和 `_task`。`schedule()` 在无活跃 task 时计算 `len(list_sessions(sessions_dir))`；未到期直接返回，到期则创建并强引用 `_run()` task。

`_run()` 读取最多 200 个 manifest 项及对应全文，调用：

```python
success = await self._actions.execute(
    MEMORY_CONSOLIDATION_SYSTEM_PROMPT,
    {
        "existing_memories": manifest,
        "memory_documents": documents,
    },
)
```

仅在 `success is True` 时写新 state。`shutdown()` 对仍在运行的整理 task 调用 `cancel()`，随后使用 `asyncio.gather(task, return_exceptions=True)` 回收；周期整理不占用自动提取的 3 秒退出预算。

- [ ] **Step 5: 装配 Manager、Agent 和 bootstrap**

`Manager.__init__` 增加可选 `sessions_dir: str | None = None`，有目录时构造 Consolidator；`schedule_consolidation()` 在组件不存在时为空操作。

`build_runtime` 先计算：

```python
sessions_dir = str(root / ".Arkcode" / "sessions")
```

并同时传给 MemoryManager 和 SessionService。

Agent 在成功 `schedule_extract` 后调用一次 `manager.schedule_consolidation()`；异常结束路径不调用。

- [ ] **Step 6: 运行周期整理相关测试**

Run:

```bash
.venv/bin/python -m pytest tests/memory/test_consolidation.py tests/agents/test_agent.py tests/application/test_runtime.py -q
```

Expected: PASS；未同时满足两个门槛时 action service 调用次数为 0。

- [ ] **Step 7: Review checkpoint**

检查 Consolidator 没有 Bash、工具注册表、Conversation 或 SessionJournal 写入权限；整理 action 与自动提取共用 `MemoryActionService` 的写锁。

---

### Task 6: 退出时 3 秒提取收尾与后台任务所有权

**Files:**
- Modify: `src/Arkcode/memory/manager.py`
- Modify: `src/Arkcode/application/lifecycle.py`
- Modify: `src/Arkcode/application/runtime.py`
- Modify: `tests/memory/test_memory_manager.py`
- Modify: `tests/application/test_runtime.py`

**Interfaces:**
- Consumes: `Manager.flush_extraction(3.0)`、`Consolidator.shutdown()`。
- Produces: `Manager.shutdown() -> None`。
- Produces: `close_memory(memory: MemoryManager) -> None`。

- [ ] **Step 1: 写关闭顺序和超时测试**

扩展 `tests/application/test_runtime.py`：

```python
class FakeMemory:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def shutdown(self) -> None:
        self.calls.append("memory")


@pytest.mark.asyncio
async def test_shutdown_closes_session_then_memory_then_tasks_then_mcp() -> None:
    calls: list[str] = []
    runtime = make_runtime(calls, asyncio.create_task(_record_cleanup(calls)))
    await runtime.shutdown()
    assert calls == ["writer", "memory", "tasks", "mcp"]
```

在 manager 测试中使用永不返回的 Provider，记录 `loop.time()` 前后差值，调用 `await manager.shutdown()` 后断言耗时小于 3.5 秒且提取 task 已取消或完成。

- [ ] **Step 2: 运行生命周期测试确认失败**

Run:

```bash
.venv/bin/python -m pytest tests/application/test_runtime.py tests/memory/test_memory_manager.py -q
```

Expected: FAIL，runtime 尚未关闭 memory。

- [ ] **Step 3: 实现 Manager.shutdown**

固定顺序：

```python
async def shutdown(self) -> None:
    await self.flush_extraction(timeout=3.0)
    if self._consolidator is not None:
        await self._consolidator.shutdown()
```

`flush_extraction` 超时时取消 `_extract_task` 并 `gather(..., return_exceptions=True)`；清理 task 引用。Consolidator shutdown 不允许留下未持有的 task。

- [ ] **Step 4: 将 memory 纳入 ApplicationRuntime 关闭链**

在 lifecycle 增加：

```python
async def close_memory(memory: MemoryManager) -> None:
    await memory.shutdown()
```

`ApplicationRuntime.shutdown` 顺序改为：session → memory → cleanup task → MCP。Session 先关闭 journal，memory action 不触碰 session JSONL。

- [ ] **Step 5: 运行生命周期与记忆测试**

Run:

```bash
.venv/bin/python -m pytest tests/application/test_runtime.py tests/memory -q
```

Expected: PASS；关闭顺序与超时断言稳定。

- [ ] **Step 6: Review checkpoint**

使用 `rg -n "create_task" src/Arkcode/memory src/Arkcode/agents/agent.py` 检查每一个记忆 task 都保存在 `_extract_task` 或 Consolidator `_task` 中。

---

### Task 7: 回归、JSONL 不变性与 tmux 端到端验收

**Files:**
- Create: `tests/integration/test_memory_lifecycle.py`
- Modify: `checklist.md`

**Interfaces:**
- Consumes: 前六个任务的全部公共接口。
- Produces: 一条覆盖提取、召回、整理和 session JSONL 不变性的集成测试。

- [ ] **Step 1: 写完整记忆生命周期集成测试**

在 `tests/integration/test_memory_lifecycle.py` 使用脚本化 Provider 和临时 workspace，完成两个自然 turn：第一轮返回 create action，第二轮 recall selector 返回第一轮文件键。核心断言：

```python
async def drain_turn(service: SessionService, text: str) -> None:
    async for _ in service.submit_message(text):
        pass


before_lines = conversation_jsonl.read_text(encoding="utf-8").splitlines()
await drain_turn(service, "以后都用中文回答")
await memory.flush_extraction()
await drain_turn(service, "我偏好什么语言？")
after_lines = conversation_jsonl.read_text(encoding="utf-8").splitlines()

assert memory_file.exists()
assert "用户偏好中文" in main_provider.requests[-1].reminder
assert len(after_lines) == len(before_lines) + 4  # 两个 user/assistant turn
assert all("\"action\"" not in line for line in after_lines)
assert all("Relevant long-term memories" not in line for line in after_lines)
```

测试 Provider 根据 `request.system.stable` 区分 main、extraction、recall、consolidation 请求，避免依赖请求顺序。

- [ ] **Step 2: 运行集成测试确认行为**

Run:

```bash
.venv/bin/python -m pytest tests/integration/test_memory_lifecycle.py -q
```

Expected: PASS；JSONL 只增加四条真实对话消息。

- [ ] **Step 3: 运行完整自动化测试**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: 全部测试 PASS；不得通过删除或放宽既有测试获得通过。

- [ ] **Step 4: 运行静态检查**

Run:

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m ruff format --check src tests
.venv/bin/python -m mypy src/Arkcode
```

Expected: 三条命令均退出码 0。

- [ ] **Step 5: 使用 tmux 做真实端到端验证**

在独立 tmux session 启动项目：

```bash
tmux new-session -d -s arkcode-memory-e2e '.venv/bin/python -m Arkcode'
tmux send-keys -t arkcode-memory-e2e '请记住：以后优先用中文简洁回答' Enter
```

等待真实回复后，再输入：

```bash
tmux send-keys -t arkcode-memory-e2e '我刚才要求的回答偏好是什么？' Enter
tmux capture-pane -pt arkcode-memory-e2e -S -200
```

确认第二轮回答使用了第一轮提取的记忆；退出 ArkCode 后检查项目记忆目录存在对应 Markdown，且当前 session 的 `conversation.jsonl` 中没有 JSON action、memory reminder 或重复消息。

- [ ] **Step 6: 更新验收清单**

在 `checklist.md` 增加并逐项勾选：

```markdown
- [ ] 正常 turn 每轮自动提取，异常结束不提取
- [ ] 同名 create 覆盖更新且保留 created
- [ ] 每轮最多召回 5 条、25 KiB 的已知记忆全文
- [ ] 24 小时且新增 5 个 session 才触发整理
- [ ] 退出最多等待提取 3 秒
- [ ] conversation.jsonl 不包含记忆 action、全文 reminder 或记忆快照
```

- [ ] **Step 7: 最终 Review checkpoint**

执行 `git status --short` 和针对本计划文件集合的 `git diff`，确认没有覆盖用户无关改动、没有生成提交、没有加入旧格式兼容分支，并记录自动化测试与 tmux 验收结果。

---

## Completion Criteria

- Task 1–7 的 checkbox 全部完成。
- 聚焦测试、完整 pytest、项目实际静态检查命令全部通过。
- tmux 中完成两轮真实对话并验证第二轮可召回第一轮记忆。
- `conversation.jsonl` 仍只持久化真实消息和既有 compact boundary，不含记忆维护内部数据。
- 所有后台提取和整理任务都有显式所有者，退出后没有悬空 task。
- 工作区没有创建 Git commit。
