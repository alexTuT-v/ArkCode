# ArkCode Session JSONL Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ArkCode's snapshot-style Session JSONL with a readable append-only message journal and self-contained compact boundaries, while preserving crash-safe recovery.

**Architecture:** A `SessionRecord` codec serializes final messages and compact boundaries, `SessionJournal` performs fsync-backed append, and `SessionMetaStore` maintains atomic metadata. Tool results become final before entering history; `Conversation` persists typed mutations before changing memory; Context Manager returns compaction data instead of mutating or persisting history implicitly.

**Tech Stack:** Python 3.14, dataclasses, pathlib, JSONL, pytest/pytest-asyncio, existing ArkCode protocol-neutral LLM types.

## Global Constraints

- New sessions use `format_version: 2`; old `compact + full snapshot` sessions are neither loaded nor migrated.
- Old session directories are not deleted automatically.
- Preserve ArkCode's `user`, `assistant`, and `tool` roles.
- Ordinary messages are written exactly once; a successful real compaction appends exactly one `compact_boundary`.
- Tool results are spilled or previewed before they enter `Conversation` or JSONL.
- Journal writes remain thread-safe and use flush plus `os.fsync` for every committed record.
- Thinking text, thinking signatures, and provider-private streaming events are not persisted.
- Empty optional JSON fields and `is_error: false` are omitted.
- TUI and Context Manager must not write JSONL directly.
- Do not commit implementation or documentation unless the user explicitly requests a commit.

## Target File Map

- `src/Arkcode/sessions/record.py`: message/boundary data types, validation, JSON codec.
- `src/Arkcode/sessions/journal.py`: locked JSONL append, flush, fsync, close.
- `src/Arkcode/sessions/meta.py`: format-v2 metadata and atomic meta storage.
- `src/Arkcode/sessions/load.py`: streaming projection, valid-boundary reset, pairing repair.
- `src/Arkcode/sessions/listing.py`: format-v2 meta-based listing and deletion.
- `src/Arkcode/sessions/cleanup.py`: format-v2 meta-based expiry cleanup.
- `src/Arkcode/conversations/manager.py`: sink-backed message commit and explicit compaction commit.
- `src/Arkcode/context/spill.py`: pre-history tool-result finalization.
- `src/Arkcode/context/summary.py`: structured compaction result generation.
- `src/Arkcode/context/manager.py`: threshold orchestration without Conversation mutation.
- `src/Arkcode/agents/agent.py`: final tool-result preparation and compaction application.
- `src/Arkcode/application/session.py`: Session Journal/meta lifecycle, create/clear/resume.
- `src/Arkcode/sessions/writer.py`: delete after all call sites migrate.

---

### Task 1: Add the format-v2 Session record codec

**Files:**
- Create: `src/Arkcode/sessions/record.py`
- Create: `tests/sessions/test_record.py`

**Interfaces:**
- Produces: `CompactBoundary(summary: str, keep: list[Message], timestamp: int)`.
- Produces: `SessionRecord = Message | CompactBoundary`.
- Produces: `encode_message(message: Message, *, timestamp: int | None = None) -> bytes`.
- Produces: `encode_boundary(boundary: CompactBoundary) -> bytes`.
- Produces: `decode_record(line: str | bytes) -> SessionRecord | None`.
- Later tasks depend on JSON arguments being objects on disk and `ToolCall.input` being a JSON string in memory.

- [ ] **Step 1: Write failing codec tests**

Create tests that pin the external schema rather than dataclass implementation details:

```python
def test_message_codec_omits_empty_and_default_fields() -> None:
    encoded = encode_message(Message(role="user", content="你好"), timestamp=10)
    assert json.loads(encoded) == {"role": "user", "content": "你好", "ts": 10}


def test_tool_call_arguments_are_json_objects_on_disk() -> None:
    message = Message(
        role="assistant",
        tool_calls=[ToolCall("c1", "read_file", '{"path":"a.txt"}')],
    )
    value = json.loads(encode_message(message, timestamp=11))
    assert value["tool_calls"] == [
        {"id": "c1", "name": "read_file", "arguments": {"path": "a.txt"}}
    ]
    assert decode_record(encode_message(message, timestamp=11)) == message


def test_success_result_omits_is_error() -> None:
    message = Message(role="tool", tool_results=[ToolResult("c1", "done")])
    value = json.loads(encode_message(message, timestamp=12))
    assert "is_error" not in value["tool_results"][0]


def test_boundary_round_trip_preserves_keep_pairing() -> None:
    keep = [
        Message(role="assistant", tool_calls=[ToolCall("c1", "read_file", "{}")]),
        Message(role="tool", tool_results=[ToolResult("c1", "done")]),
    ]
    boundary = CompactBoundary("earlier summary", keep, 13)
    assert decode_record(encode_boundary(boundary)) == boundary


def test_thinking_is_not_persisted() -> None:
    message = Message(
        role="assistant",
        content="answer",
        thinking="private",
        thinking_signature="signature",
    )
    assert decode_record(encode_message(message, timestamp=14)) == Message(
        role="assistant", content="answer"
    )
```

Also cover malformed JSON, unknown roles/types, invalid boundary payloads, non-object arguments, and `is_error: true`.

- [ ] **Step 2: Run the codec tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/sessions/test_record.py
```

Expected: collection fails because `Arkcode.sessions.record` does not exist.

- [ ] **Step 3: Implement the minimal record types and encoder**

Use explicit dict construction so empty values are omitted:

```python
@dataclass(frozen=True)
class CompactBoundary:
    summary: str
    keep: list[Message]
    timestamp: int


SessionRecord: TypeAlias = Message | CompactBoundary


def _arguments(raw: str) -> dict[str, Any]:
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("工具参数必须是 JSON object")
    return value


def encode_message(message: Message, *, timestamp: int | None = None) -> bytes:
    ts = int(time.time()) if timestamp is None else timestamp
    value: dict[str, Any] = {"role": message.role, "ts": ts}
    if message.content:
        value["content"] = message.content
    # Populate tool_calls/tool_results only when non-empty.
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
```

Keep boundary message dict conversion private and shared by `encode_boundary` and decode.

- [ ] **Step 4: Implement strict, non-throwing record decode**

`decode_record` returns `None` for malformed or unknown records. It must validate the entire boundary before returning it; partial `keep` acceptance would let a corrupt boundary discard valid history.

```python
def decode_record(line: str | bytes) -> SessionRecord | None:
    try:
        value = json.loads(line)
        if value.get("type") == "compact_boundary":
            return _decode_boundary(value)
        return _decode_message(value)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError):
        return None
```

- [ ] **Step 5: Run codec tests**

Run:

```bash
.venv/bin/pytest -q tests/sessions/test_record.py
```

Expected: all tests pass.

- [ ] **Step 6: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/sessions/record.py tests/sessions/test_record.py
git diff -- src/Arkcode/sessions/record.py tests/sessions/test_record.py
```

Confirm there are no unrelated edits.

---

### Task 2: Add the crash-safe Journal and atomic metadata store

**Files:**
- Create: `src/Arkcode/sessions/journal.py`
- Create: `src/Arkcode/sessions/meta.py`
- Create: `tests/sessions/test_journal.py`
- Create: `tests/sessions/test_meta.py`

**Interfaces:**
- Consumes: `CompactBoundary`, `encode_message`, `encode_boundary` from Task 1.
- Produces: `MessageSink` protocol with `append_message(Message)` and `append_boundary(CompactBoundary)`.
- Produces: `SessionJournal(session_dir: str | Path)` implementing `MessageSink`.
- Produces: `SessionMeta` and `SessionMetaStore` with `load()`, `save(meta)`, and `update(**changes)`.

- [ ] **Step 1: Write failing Journal tests**

Pin append order, fsync, concurrency, and failure behavior:

```python
def test_journal_appends_messages_and_boundary(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.append_message(Message(role="user", content="hello"))
    journal.append_boundary(CompactBoundary("summary", [], 20))
    journal.close()

    values = [json.loads(line) for line in (tmp_path / "conversation.jsonl").read_text().splitlines()]
    assert [value.get("type", "message") for value in values] == [
        "message", "compact_boundary"
    ]


def test_closed_journal_rejects_append(tmp_path: Path) -> None:
    journal = SessionJournal(tmp_path)
    journal.close()
    journal.close()
    with pytest.raises(RuntimeError, match="已关闭"):
        journal.append_message(Message(role="user", content="late"))
```

Add a `ThreadPoolExecutor` test with 40 messages and assert 40 independently parseable lines. Monkeypatch `os.fsync` and assert one call per appended record.

Add an existing-file recovery test: write one valid line followed by a truncated JSON
fragment, open the Journal, append a new message, and assert the result contains exactly
two independently parseable lines. The truncated fragment must be removed before append.

- [ ] **Step 2: Write failing metadata tests**

```python
def test_meta_round_trip_uses_format_version_two(tmp_path: Path) -> None:
    store = SessionMetaStore(tmp_path)
    meta = SessionMeta.new("20260810-120000-abcd")
    store.save(meta)
    assert store.load() == meta
    assert json.loads((tmp_path / "meta.json").read_text())["format_version"] == 2


def test_meta_save_uses_atomic_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    replaced: list[tuple[Path, Path]] = []
    monkeypatch.setattr(os, "replace", lambda source, target: replaced.append((Path(source), Path(target))))
    SessionMetaStore(tmp_path).save(SessionMeta.new("session"))
    assert replaced and replaced[0][1] == tmp_path / "meta.json"
```

Also test corrupt/missing meta returns `None`, title truncation, and preservation of
timezone-aware timestamps.

- [ ] **Step 3: Run the tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/sessions/test_journal.py tests/sessions/test_meta.py
```

Expected: imports fail because the modules do not exist.

- [ ] **Step 4: Implement `SessionJournal`**

Use a binary append handle and a single lock:

```python
class MessageSink(Protocol):
    def append_message(self, message: Message) -> None: ...
    def append_boundary(self, boundary: CompactBoundary) -> None: ...


class SessionJournal:
    def _append(self, encoded: bytes) -> None:
        with self._lock:
            if self._file.closed:
                raise RuntimeError("Session Journal 已关闭")
            self._file.write(encoded)
            self._file.flush()
            os.fsync(self._file.fileno())
```

Encode before `_append` so validation failures never acquire the write lock or produce partial records.
When opening an existing non-empty file, inspect its final byte. If it is not `b"\n"`,
find the last newline, truncate to the byte immediately after it (or zero when none
exists), flush, and fsync before accepting new appends.

- [ ] **Step 5: Implement `SessionMeta` and `SessionMetaStore`**

Define exact fields from the spec. Use `tempfile.NamedTemporaryFile` in the Session directory, flush/fsync the temporary file, then `os.replace(temp_path, meta_path)`. Clean up an un-replaced temporary file in `finally`.

`update()` returns the updated in-memory `SessionMeta`; on failure it raises so the Session owner can mark metadata dirty without treating the Journal commit as failed.

- [ ] **Step 6: Run Journal and metadata tests**

Run:

```bash
.venv/bin/pytest -q tests/sessions/test_journal.py tests/sessions/test_meta.py
```

Expected: all tests pass.

- [ ] **Step 7: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/sessions/journal.py src/Arkcode/sessions/meta.py tests/sessions/test_journal.py tests/sessions/test_meta.py
```

---

### Task 3: Replace snapshot loading and listing with format-v2 projection

**Files:**
- Modify: `src/Arkcode/sessions/load.py`
- Modify: `src/Arkcode/sessions/listing.py`
- Modify: `src/Arkcode/sessions/cleanup.py`
- Create: `tests/sessions/test_load_v2.py`
- Modify: `tests/sessions/test_listing_delete.py`

**Interfaces:**
- Consumes: `decode_record`, `CompactBoundary`, `SessionMetaStore`.
- Produces: `load_session(session_dir: str | Path) -> list[Message]` using only format v2.
- Produces: `SessionInfo` populated from `meta.json` without scanning JSONL content.
- Produces: deterministic in-memory pairing repair.

- [ ] **Step 1: Write failing projection tests**

```python
def test_last_valid_boundary_replaces_earlier_projection(tmp_path: Path) -> None:
    write_records(
        tmp_path,
        Message(role="user", content="old"),
        CompactBoundary("summary", [Message(role="assistant", content="kept")], 30),
        Message(role="user", content="new"),
    )
    assert load_session(tmp_path) == [
        Message(role="user", content=RESUME_SUMMARY_PREFIX + "summary"),
        Message(role="assistant", content="kept"),
        Message(role="user", content="new"),
    ]


def test_corrupt_boundary_does_not_clear_valid_history(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    path.write_bytes(
        encode_message(Message(role="user", content="safe"), timestamp=1)
        + b'{"type":"compact_boundary","content":'
    )
    assert load_session(tmp_path) == [Message(role="user", content="safe")]
```

Add tests for multiple boundaries, corrupt ordinary lines, truncated tail, an incomplete tool call receiving an in-memory error result, and orphan results being omitted.

- [ ] **Step 2: Rewrite listing tests around `meta.json`**

Create one format-v2 Session with valid meta, one old Session with only JSONL, and one corrupt meta. Assert only the valid format-v2 Session is listed and that title/model/provider/time come from meta. Keep deletion tests scoped to the exact selected directory.

- [ ] **Step 3: Run loader/listing tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/sessions/test_load_v2.py tests/sessions/test_listing_delete.py
```

Expected: failures show the loader still understands old `compact` snapshots and listing still scans JSONL.

- [ ] **Step 4: Implement streaming format-v2 projection**

Validate a boundary before resetting active history:

```python
for line in source:
    record = decode_record(line)
    if isinstance(record, Message):
        active.append(record)
    elif isinstance(record, CompactBoundary):
        active = [
            Message(role="user", content=RESUME_SUMMARY_PREFIX + record.summary),
            *copy.deepcopy(record.keep),
        ]
```

After parsing, derive all issued and completed tool IDs, then rebuild the sequence in a
second pass. Drop result blocks whose IDs were never issued. Immediately after each
assistant message, insert one tool message containing interrupted error results only for
that assistant's call IDs that do not occur in the completed-ID set. Preserve real result
messages in their original positions. Do not write repairs back to disk.

- [ ] **Step 5: Implement meta-only listing and cleanup**

For each Session directory, load `meta.json`; skip missing, corrupt, or non-v2 metadata. Compute display size from `conversation.jsonl.stat().st_size` without opening its contents. Sort by `meta.last_active` descending.

Cleanup uses `meta.created_at` or `last_active` according to the existing product rule; keep the existing creation-age behavior by using `created_at`. Skip old and corrupt directories rather than deleting them.

- [ ] **Step 6: Run Session projection/listing tests**

Run:

```bash
.venv/bin/pytest -q tests/sessions/test_load_v2.py tests/sessions/test_listing_delete.py
```

Expected: all tests pass.

- [ ] **Step 7: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/sessions/load.py src/Arkcode/sessions/listing.py src/Arkcode/sessions/cleanup.py tests/sessions/test_load_v2.py tests/sessions/test_listing_delete.py
```

---

### Task 4: Make Conversation commits explicit and persistence-first

**Files:**
- Modify: `src/Arkcode/conversations/manager.py`
- Modify: `tests/conversations/test_conversation.py`

**Interfaces:**
- Consumes: `MessageSink` and `CompactBoundary` from Tasks 1-2.
- Produces: `Conversation(*, sink: MessageSink | None = None)`.
- Produces: `Conversation.from_messages(messages, *, sink=None)` without writes.
- Produces: `apply_compaction(boundary: CompactBoundary, messages: list[Message]) -> None`.
- Removes: `on_append`, `on_replace`, and persistence-bearing `replace_history` behavior.

- [ ] **Step 1: Replace callback tests with failing sink-order tests**

```python
class RecordingSink:
    def __init__(self) -> None:
        self.messages: list[Message] = []
        self.boundaries: list[CompactBoundary] = []

    def append_message(self, message: Message) -> None:
        self.messages.append(message)

    def append_boundary(self, boundary: CompactBoundary) -> None:
        self.boundaries.append(boundary)


def test_sink_commits_before_message_is_visible() -> None:
    conversation: Conversation

    class ObservingSink(RecordingSink):
        def append_message(self, message: Message) -> None:
            assert conversation.messages() == []
            super().append_message(message)

    conversation = Conversation(sink=ObservingSink())
    conversation.add_user("hello")
    assert conversation.messages() == [Message(role="user", content="hello")]


def test_sink_failure_prevents_memory_append() -> None:
    class FailingSink(RecordingSink):
        def append_message(self, message: Message) -> None:
            raise OSError("disk full")

    conversation = Conversation(sink=FailingSink())
    with pytest.raises(OSError, match="disk full"):
        conversation.add_user("lost")
    assert conversation.messages() == []
```

Add equivalent tests for boundary failure, successful boundary-before-replace ordering, deep copies, and `from_messages` producing no sink calls.

- [ ] **Step 2: Run Conversation tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/conversations/test_conversation.py
```

Expected: constructor and compaction interface failures.

- [ ] **Step 3: Implement persistence-first message append**

```python
def _append(self, message: Message) -> None:
    committed = copy.deepcopy(message)
    with self._lock:
        if self._sink is not None:
            self._sink.append_message(copy.deepcopy(committed))
        self._messages.append(committed)
```

Do not catch sink errors. Hold the Conversation commit lock across sink IO and memory
append so concurrent callers cannot observe a disk order different from memory order.
The lock is an `RLock`, allowing same-thread inspection from test sinks without deadlock.

- [ ] **Step 4: Implement explicit compaction commit**

```python
def apply_compaction(
    self,
    boundary: CompactBoundary,
    messages: list[Message],
) -> None:
    replacement = copy.deepcopy(messages)
    with self._lock:
        if self._sink is not None:
            self._sink.append_boundary(copy.deepcopy(boundary))
        self._messages = replacement
```

Retain a private/test-only memory replacement helper only if existing compaction tests need setup. It must never invoke the sink.

- [ ] **Step 5: Run Conversation tests**

Run:

```bash
.venv/bin/pytest -q tests/conversations/test_conversation.py
```

Expected: all tests pass.

- [ ] **Step 6: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/conversations/manager.py tests/conversations/test_conversation.py
```

---

### Task 5: Finalize large tool results before history insertion

**Files:**
- Modify: `src/Arkcode/context/spill.py`
- Modify: `src/Arkcode/agents/agent.py`
- Modify: `tests/context/compact/test_layer1.py`
- Modify: `tests/agents/test_agent.py`

**Interfaces:**
- Produces: `prepare_tool_results(results: list[ToolResult], calls: list[ToolCall], session: SessionContext) -> list[ToolResult]`.
- Preserves: `spill_single`, stable preview formatting, single-result and aggregate limits.
- Removes later: `offload_and_snip` and stateful history rewriting.

- [ ] **Step 1: Write failing pre-history spill tests**

```python
def test_large_result_is_final_before_conversation_append(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    calls = [ToolCall("c1", "read_file", '{"path":"large.txt"}')]
    prepared = prepare_tool_results(
        [ToolResult("c1", "x" * (SINGLE_RESULT_LIMIT + 1))],
        calls,
        session,
    )
    assert prepared[0].content.startswith("[content offloaded]")
    assert (Path(session.spill_dir) / "c1").exists()


def test_spill_failure_keeps_original_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spill_module, "spill_single", Mock(side_effect=OSError("full")))
    original = "x" * (SINGLE_RESULT_LIMIT + 1)
    prepared = prepare_tool_results(
        [ToolResult("c1", original)],
        [ToolCall("c1", "read_file", "{}")],
        new_session_context(str(tmp_path)),
    )
    assert prepared[0].content == original
```

Add aggregate-budget ordering and spill-readback exemption tests. For readback, use a `read_file` call whose resolved path is inside `session.spill_dir`.

- [ ] **Step 2: Add an Agent integration assertion**

Use a fake tool returning oversized content and a recording sink. Assert the sink and `Conversation.messages()` receive the same preview content and that raw content exists only in the spill file.

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/context/compact/test_layer1.py tests/agents/test_agent.py
```

Expected: `prepare_tool_results` is missing and Agent still appends raw results first.

- [ ] **Step 4: Implement stateless result preparation**

Build a call lookup by ID. First handle per-result spill, then compute the remaining batch total and spill the largest eligible results until within `MESSAGE_AGGREGATE_LIMIT`. Return new frozen `ToolResult` values rather than mutating inputs.

Readback detection must resolve the requested path and use `Path.is_relative_to(Path(session.spill_dir).resolve())`; invalid JSON or missing paths are not exempt.

- [ ] **Step 5: Call preparation immediately before `add_tool_results`**

In every Agent branch that commits a tool-result batch, use:

```python
results = prepare_tool_results(results, calls, self.runtime.session)
conv.add_tool_results(results)
```

Ensure cancellation-generated results take the same path.

- [ ] **Step 6: Run spill and Agent tests**

Run:

```bash
.venv/bin/pytest -q tests/context/compact/test_layer1.py tests/agents/test_agent.py
```

Expected: all tests pass.

- [ ] **Step 7: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/context/spill.py src/Arkcode/agents/agent.py tests/context/compact/test_layer1.py tests/agents/test_agent.py
```

---

### Task 6: Return structured compaction results and append one boundary

**Files:**
- Modify: `src/Arkcode/context/summary.py`
- Modify: `src/Arkcode/context/manager.py`
- Modify: `src/Arkcode/context/state.py`
- Modify: `src/Arkcode/context/__init__.py`
- Modify: `src/Arkcode/agents/agent.py`
- Modify: `tests/context/compact/test_compact.py`
- Modify: `tests/context/compact/test_layer2.py`
- Modify: `tests/context/compact/test_state.py`
- Modify: `tests/agents/test_agent.py`

**Interfaces:**
- Produces: `CompactionResult(summary: str, keep: list[Message], messages: list[Message])`.
- Changes: `ManageOutput` carries `compaction: CompactionResult | None` and exposes `compacted` from its presence.
- Consumes: `Conversation.apply_compaction` and `CompactBoundary`.
- Removes: `ContentReplacementState` and all Context Manager calls to `replace_history`.

- [ ] **Step 1: Rewrite Context Manager tests to assert no mutation**

```python
@pytest.mark.asyncio
async def test_auto_below_threshold_does_not_replace_history(tmp_path: Path) -> None:
    input_, provider = make_input(tmp_path, estimated=1000, trigger=TriggerKind.AUTO)
    before = input_.conv.messages()
    output = await manage_context(input_)
    assert output.compaction is None
    assert input_.conv.messages() == before
    assert provider.requests == []


@pytest.mark.asyncio
async def test_auto_above_threshold_returns_structured_compaction(tmp_path: Path) -> None:
    input_, _ = make_input(tmp_path, estimated=180000, trigger=TriggerKind.AUTO)
    before = input_.conv.messages()
    output = await manage_context(input_)
    assert output.compaction is not None
    assert output.compaction.summary.startswith("small")
    assert "## 最近读过的文件" in output.compaction.summary
    assert input_.conv.messages() == before
```

Update manual/emergency tests to expect the same result type. Emergency no longer performs Layer 1 history rewriting because Task 5 finalized results at insertion.

- [ ] **Step 2: Add an Agent one-boundary regression test**

Inject a recording sink and force a compact threshold. Assert exactly one boundary is appended and no old message is re-appended:

```python
assert len(sink.boundaries) == 1
assert sink.messages == messages_committed_before_compaction
assert conversation.messages() == output.compaction.messages
```

- [ ] **Step 3: Run compact tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/context/compact/test_compact.py tests/context/compact/test_layer2.py tests/context/compact/test_state.py tests/agents/test_agent.py
```

Expected: failures show `manage_context` still mutates Conversation and `ContentReplacementState` is required.

- [ ] **Step 4: Implement `CompactionResult` in summary generation**

Refactor `run_summary` to retain the formal `summary` string and `keep` list separately:

```python
@dataclass(frozen=True)
class CompactionResult:
    summary: str
    keep: list[Message]
    messages: list[Message]
```

Build one stable `resume_summary` string by joining the formal model summary and the
recovery attachment. Store that exact string in both `CompactionResult.summary` and the
summary/recovery message inside `messages`, then append a pairing-safe copy of `keep`.
This guarantees that a boundary-only Resume reconstructs the same compressed context.
`auto_compact` maintains the circuit breaker but returns `CompactionResult` and token
counts.

- [ ] **Step 5: Make `manage_context` calculation-only**

Remove Layer 1 calls and all `conv.replace_history(...)` calls. Return a `ManageOutput` containing an optional compaction. Preserve threshold calculation, prompt-too-long recovery, automatic circuit breaker behavior, and before/after token reporting.

- [ ] **Step 6: Apply compaction once in Agent**

After `manage_context` returns:

```python
if managed.compaction is not None:
    result = managed.compaction
    conv.apply_compaction(
        CompactBoundary(result.summary, result.keep, int(time.time())),
        result.messages,
    )
```

Do this for auto, manual, and emergency paths through a shared private Agent method so event reporting cannot diverge from persistence.

- [ ] **Step 7: Remove replacement state**

Delete `ContentReplacementState`, its runtime ownership, imports, construction, tests, and `replacement_count` logging. Keep `RecoveryState`, `CompactCircuitBreaker`, and Session context intact.

- [ ] **Step 8: Run compact and Agent tests**

Run:

```bash
.venv/bin/pytest -q tests/context/compact tests/agents/test_agent.py tests/agents/test_agent_runtime.py
```

Expected: all tests pass.

- [ ] **Step 9: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/context src/Arkcode/agents/agent.py tests/context tests/agents
```

---

### Task 7: Migrate SessionService lifecycle and public Session APIs

**Files:**
- Modify: `src/Arkcode/application/session.py`
- Modify: `src/Arkcode/application/lifecycle.py`
- Modify: `src/Arkcode/sessions/__init__.py`
- Modify: `tests/application/test_session_service.py`
- Modify: `tests/sessions/test_session.py`
- Modify: `tests/sessions/test_session_writer.py`

**Interfaces:**
- Consumes: `SessionJournal`, `SessionMetaStore`, meta-only `SessionInfo`, format-v2 `load_session`.
- Changes: `SessionService.writer` becomes `SessionService.journal`.
- Preserves: create, clear, resume, shutdown, provider activation, and public session listing behavior.

- [ ] **Step 1: Rewrite SessionService tests for format v2**

Replace `Writer` setup with Journal/meta setup:

```python
def create_v2_session(path: Path, message: Message) -> None:
    journal = SessionJournal(path)
    journal.append_message(message)
    journal.close()
    SessionMetaStore(path).save(
        replace(SessionMeta.new(path.name), title=message.content, model="old-model")
    )


def test_resume_restores_without_reappend(tmp_path: Path) -> None:
    target = tmp_path / ".Arkcode" / "sessions" / "20260808-120000-abcd"
    create_v2_session(target, Message(role="user", content="恢复这段对话"))
    before = (target / "conversation.jsonl").read_bytes()
    service = make_service(tmp_path)
    service.resume_session(find_info(target))
    assert (target / "conversation.jsonl").read_bytes() == before
```

Update clear tests to assert the old Journal closes only after the new Session context, Journal, meta, and Conversation are successfully constructed.

- [ ] **Step 2: Add metadata lifecycle tests**

Assert provider activation saves provider/model, first user message sets title, normal messages increment count, compact boundary does not increment count, and meta-save failure after Journal success leaves the message recoverable.

- [ ] **Step 3: Run lifecycle tests and verify failure**

Run:

```bash
.venv/bin/pytest -q tests/application/test_session_service.py tests/sessions/test_session.py tests/sessions/test_session_writer.py
```

Expected: failures show `SessionService` still owns `Writer` and creates no meta.

- [ ] **Step 4: Introduce a Session-owned sink that combines Journal and meta**

Implement a small sink in the sessions package or application boundary:

```python
class SessionSink(MessageSink):
    def append_message(self, message: Message) -> None:
        self.journal.append_message(message)
        self._update_meta_after_message(message)

    def append_boundary(self, boundary: CompactBoundary) -> None:
        self.journal.append_boundary(boundary)
        self._update_last_active()
```

Journal errors propagate. Meta errors are logged, mark the sink dirty, and are retried on the next update and `close()`.

- [ ] **Step 5: Migrate create, clear, resume, and shutdown**

- Create: construct Session context directory, initial meta, Journal, SessionSink, then Conversation.
- Clear: construct the complete replacement bundle first; swap runtime ownership; close the old sink last.
- Resume: validate v2 meta, load messages, open existing Journal, then `Conversation.from_messages(messages, sink=sink)`.
- Shutdown: retry dirty meta and close Journal exactly once.
- Provider activation: update `provider` and `model` in meta without writing a message.

- [ ] **Step 6: Update public exports and callers**

Export `SessionJournal`, `SessionMeta`, `SessionMetaStore`, the `SessionRecord` union,
codec functions, and remove `Entry`/`Writer`. Update application/runtime tests and any
type hints that refer to `writer`.

- [ ] **Step 7: Run lifecycle and Session tests**

Run:

```bash
.venv/bin/pytest -q tests/application tests/sessions
```

Expected: all tests pass.

- [ ] **Step 8: Review the task diff without committing**

Run:

```bash
git diff --check -- src/Arkcode/application src/Arkcode/sessions tests/application tests/sessions
```

---

### Task 8: Delete snapshot persistence and prove linear growth end to end

**Files:**
- Delete: `src/Arkcode/sessions/writer.py`
- Modify: `src/Arkcode/sessions/__init__.py`
- Delete or rewrite: `tests/sessions/test_session_writer.py`
- Modify: `tests/integration/test_agent_integration.py`
- Create: `tests/integration/test_session_jsonl_v2.py`
- Modify as required: imports found by repository-wide search.

**Interfaces:**
- Consumes all format-v2 interfaces from Tasks 1-7.
- Produces the final invariant: successful records equal real messages plus real boundaries.

- [ ] **Step 1: Write the linear-growth integration test**

Use a fake provider that performs several deterministic tool loops and then answers. After draining one submitted user turn:

```python
records = [decode_record(line) for line in jsonl.read_text().splitlines()]
messages = [record for record in records if isinstance(record, Message)]
boundaries = [record for record in records if isinstance(record, CompactBoundary)]

assert messages == service.conversation.messages()
assert boundaries == []
assert len(records) == len(messages)
```

Add a forced-compaction variant that records the number of messages ever committed through a recording sink and asserts:

```python
assert len(jsonl_lines) == committed_message_count + successful_compaction_count
assert successful_compaction_count == 1
```

The test must fail if any `1 + 3 + 5 + ...` full-history rewrite returns.

- [ ] **Step 2: Add clear/resume continuation coverage**

Create a Session, run tool loops, close, resume, submit another message, and assert pre-resume bytes are an exact prefix of post-resume bytes. Confirm no restored message is appended again.

- [ ] **Step 3: Run the new integration tests and verify their state**

Run:

```bash
.venv/bin/pytest -q tests/integration/test_session_jsonl_v2.py tests/integration/test_agent_integration.py
```

Expected before cleanup: tests expose any remaining old imports or snapshot writes.

- [ ] **Step 4: Remove all old Writer and snapshot references**

Search:

```bash
rg -n "\bWriter\b|\bEntry\b|on_replace|write_compact_marker|append_all|type.*compact|ContentReplacementState|offload_and_snip" src tests
```

Delete `writer.py`, remove obsolete exports, and delete or rewrite tests that assert the old snapshot protocol. Every remaining search hit must be either the new `compact_boundary`, a design document, or an intentional historical fixture outside runtime code.

- [ ] **Step 5: Run focused format-v2 suites**

Run:

```bash
.venv/bin/pytest -q tests/sessions tests/conversations tests/context tests/agents tests/application tests/integration/test_session_jsonl_v2.py
```

Expected: all tests pass.

- [ ] **Step 6: Run the complete automated verification**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

Expected: all commands exit 0. If the repository uses different configured entry points, use the matching commands from `pyproject.toml` and record the exact substitutions in the execution report.

- [ ] **Step 7: Perform the required tmux end-to-end check**

In tmux:

1. Start ArkCode in a temporary test workspace.
2. Ask it to use Context7 MCP to query Eino documentation.
3. Let it complete multiple tool loops.
4. Exit ArkCode cleanly.
5. Inspect `conversation.jsonl`: each logical message appears once and no boundary exists unless a real summary ran.
6. Resume the Session and ask a follow-up.
7. Confirm restored messages were not appended again and new records extend the existing file.
8. Trigger one manual compact and confirm exactly one `compact_boundary` is added without a full-history replay.

- [ ] **Step 8: Compare the resulting artifact to the original regression sample**

Record these counts in the execution report:

```bash
wc -l -c <new-session>/conversation.jsonl
jq -Rrc 'fromjson? | .type // "message"' <new-session>/conversation.jsonl | sort | uniq -c
```

Acceptance: a 22-message equivalent produces 22 ordinary message records, zero boundaries without real summary, and no triangular snapshot growth.

- [ ] **Step 9: Final review without committing**

Run:

```bash
git diff --check
git status --short
```

Report modified files, test results, tmux evidence, and any unrelated pre-existing workspace changes separately. Do not stage or commit.
