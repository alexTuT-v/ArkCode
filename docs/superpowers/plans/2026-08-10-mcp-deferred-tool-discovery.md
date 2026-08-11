# MCP Deferred Tool Discovery Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve original MCP input schemas, improve deferred-tool keyword recall, and expose undiscovered tool names through request-scoped system reminders.

**Architecture:** Keep the existing `McpTool → Registry → Prompt → Agent → Provider` boundaries. `McpTool` owns model-facing schema fidelity, `Registry.search_deferred()` keeps its current scoring loop and adds word-level points inline, prompt helpers build request-only reminders, and `Agent` recomputes the deferred catalog on every ReAct iteration without mutating conversation history.

**Tech Stack:** Python 3.12, Pydantic 2, MCP Python SDK, pytest/pytest-asyncio, Ruff, mypy.

## Global Constraints

- Model-facing MCP schemas must preserve the server-provided `input_schema` without normalization or regeneration.
- Runtime MCP argument parsing remains on the current dynamically generated Pydantic model; full JSON Schema validation is out of scope.
- Full-query scoring remains `name +10` and `description +5`; each whitespace-delimited word adds `name +3` and `description +1`.
- Search continues to exclude non-deferred and already discovered tools, with stable registration-order tie breaking.
- Deferred-tool reminders list names only, are request-scoped, and never enter Conversation or Session JSONL.
- OpenAI and Anthropic protocol serialization remains inside the provider adapters.
- No new dependency, persistence format, tool-unload policy, semantic search, or MCP connection behavior is introduced.

---

## File Map

| File | Responsibility in this change |
|---|---|
| `src/Arkcode/mcp/tool_adapter.py` | Return the original MCP input schema from `McpTool.get_schema()` while retaining the Pydantic model for execution parsing. |
| `src/Arkcode/tools/registry.py` | Add whitespace-query protection and word-level scoring inside the existing deferred search loop. |
| `src/Arkcode/prompts/reminders.py` | Build deferred-tool system reminders and combine multiple request reminders. |
| `src/Arkcode/prompts/__init__.py` | Export the two new reminder helpers. |
| `src/Arkcode/agents/agent.py` | Recompute and attach deferred-tool reminders on every ReAct iteration. |
| `tests/mcp/test_mcp_tool.py` | Prove complex MCP schema fidelity. |
| `tests/tools/test_deferred.py` | Prove word scoring, filtering, limits, and stable ordering. |
| `tests/tools/test_tool_search.py` | Prove blank-query behavior and exact-select regression behavior. |
| `tests/prompts/test_prompt.py` | Prove reminder rendering and combination as pure functions. |
| `tests/agents/test_agent.py` | Prove iteration refresh, Plan reminder coexistence, and history isolation. |

---

### Task 1: Preserve the Original MCP Input Schema

**Files:**
- Modify: `src/Arkcode/mcp/tool_adapter.py`
- Test: `tests/mcp/test_mcp_tool.py`

**Interfaces:**
- Consumes: `McpTool.input_schema: dict[str, Any]`, already populated by `adapt_tool()`.
- Produces: `McpTool.get_schema() -> dict[str, Any]`, with keys `name`, `description`, and `input_schema`.
- Preserves: `McpTool.params_model` and `_build_params_model()` for runtime argument parsing.

- [ ] **Step 1: Add a failing complex-schema fidelity test**

Add this test beside the existing adapter-definition test:

```python
def test_adapt_tool_preserves_original_complex_input_schema() -> None:
    original = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["fast", "safe"],
                "description": "Execution mode",
            },
            "filters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                    "required": ["key"],
                },
            },
            "target": {
                "oneOf": [
                    {"type": "string"},
                    {"type": "integer"},
                ]
            },
        },
        "required": ["mode"],
        "additionalProperties": False,
    }
    tool = adapt_tool("demo", _remote_tool(schema=original), StubSession())

    assert tool is not None
    assert tool.get_schema() == {
        "name": "mcp__demo__echo",
        "description": "Echo input",
        "input_schema": original,
    }
    assert tool.input_schema == original
```

- [ ] **Step 2: Run the test and verify the lossy behavior**

Run:

```bash
.venv/bin/pytest tests/mcp/test_mcp_tool.py::test_adapt_tool_preserves_original_complex_input_schema -q
```

Expected: FAIL because the inherited base implementation regenerates the schema from the simplified Pydantic model and drops `enum`, descriptions, nested properties, `items`, and `oneOf`.

- [ ] **Step 3: Override `McpTool.get_schema()` with the minimal implementation**

Add the method after `description()`:

```python
def get_schema(self) -> dict[str, Any]:
    """Return the server-provided schema without Pydantic regeneration."""

    return {
        "name": self.full_name,
        "description": self.tool_description,
        "input_schema": self.input_schema,
    }
```

Do not alter `_build_params_model()`, `params_model`, or `execute()`.

- [ ] **Step 4: Run MCP adapter and model-driven regression tests**

Run:

```bash
.venv/bin/pytest tests/mcp/test_mcp_tool.py tests/tools/test_model_driven.py -q
```

Expected: PASS. Existing empty-schema fallback still returns `{"type": "object"}` and runtime Pydantic parsing tests remain unchanged.

- [ ] **Step 5: Commit the schema-fidelity unit**

```bash
git add src/Arkcode/mcp/tool_adapter.py tests/mcp/test_mcp_tool.py
git commit -m "fix(mcp): preserve original tool input schemas"
```

---

### Task 2: Add Word-Level Deferred Search Scoring Inline

**Files:**
- Modify: `src/Arkcode/tools/registry.py`
- Test: `tests/tools/test_deferred.py`
- Test: `tests/tools/test_tool_search.py`

**Interfaces:**
- Consumes: existing `Registry.search_deferred(query: str, max_results: int) -> list[dict[str, Any]]`.
- Produces: the same signature and return type; no new scorer, helper class, or module.
- Preserves: `find_deferred_by_names()`, `mark_discovered()`, and exact `select:` handling in `ToolSearchTool`.

- [ ] **Step 1: Add a reusable ranked deferred test tool**

Append this test-only class to `tests/tools/test_deferred.py`:

```python
class RankedDeferredTool(DeferredTool):
    def __init__(self, tool_name: str, tool_description: str) -> None:
        self._tool_name = tool_name
        self._tool_description = tool_description

    def name(self) -> str:
        return self._tool_name

    def description(self) -> str:
        return self._tool_description
```

- [ ] **Step 2: Add failing tests for word recall and stable ranking**

```python
def test_search_deferred_adds_word_level_scores() -> None:
    registry = Registry()
    registry.register(RankedDeferredTool("github_issue_search", "remote tool"))
    registry.register(RankedDeferredTool("github_client", "search repository issues"))
    registry.register(RankedDeferredTool("unrelated", "calendar events"))

    found = registry.search_deferred("github issue search", 5)

    assert [item["name"] for item in found] == [
        "github_issue_search",
        "github_client",
    ]


def test_search_deferred_keeps_registration_order_for_ties_and_applies_limit() -> None:
    registry = Registry()
    registry.register(RankedDeferredTool("first_alpha", "shared"))
    registry.register(RankedDeferredTool("second_alpha", "shared"))

    found = registry.search_deferred("alpha", 1)

    assert [item["name"] for item in found] == ["first_alpha"]


def test_search_deferred_rejects_blank_query() -> None:
    registry = Registry()
    registry.register(RankedDeferredTool("anything", "anything"))

    assert registry.search_deferred("   ", 5) == []
```

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/tools/test_deferred.py -q
```

Expected: the multi-word query test and blank-query test FAIL under the current full-query-only implementation.

- [ ] **Step 4: Extend the existing scoring loop without extracting a scorer**

Inside `Registry.search_deferred()`:

```python
query_lower = query.strip().lower()
if not query_lower:
    return []
query_words = query_lower.split()
```

Compute lowercased fields once per tool and retain the existing full-query points:

```python
name_lower = name.lower()
description_lower = (tool.description() or "").lower()
score = 0
if query_lower in name_lower:
    score += 10
if query_lower in description_lower:
    score += 5
for word in query_words:
    if word in name_lower:
        score += 3
    if word in description_lower:
        score += 1
```

Keep the current deferred/discovered filtering, positive-score check, stable descending sort, and `[:max_results]` slice unchanged.

- [ ] **Step 5: Add a ToolSearch-level blank-query regression test**

Append to `tests/tools/test_tool_search.py`:

```python
@pytest.mark.asyncio
async def test_tool_search_blank_query_discovers_nothing() -> None:
    registry = make_registry_with_deferred()
    tool = ToolSearchTool(registry)

    result = await tool.execute(Params(query="   "))

    assert "No matching deferred tools" in result.content
    assert "deferred_demo" in result.content
    assert registry.is_discovered("deferred_demo") is False
```

- [ ] **Step 6: Run the deferred-search suite**

Run:

```bash
.venv/bin/pytest tests/tools/test_deferred.py tests/tools/test_tool_search.py -q
```

Expected: PASS, including the existing exact-select test.

- [ ] **Step 7: Commit the search-scoring unit**

```bash
git add src/Arkcode/tools/registry.py tests/tools/test_deferred.py tests/tools/test_tool_search.py
git commit -m "feat(tools): improve deferred tool keyword scoring"
```

---

### Task 3: Build Request-Scoped Deferred Tool Reminders

**Files:**
- Modify: `src/Arkcode/prompts/reminders.py`
- Modify: `src/Arkcode/prompts/__init__.py`
- Test: `tests/prompts/test_prompt.py`

**Interfaces:**
- Consumes: `system_reminder(body: str) -> str`.
- Produces: `deferred_tools_reminder(names: list[str]) -> str`.
- Produces: `combine_reminders(*items: str) -> str`.
- Contract: both helpers are pure and do not mutate the names list or conversation state.

- [ ] **Step 1: Add failing pure-function tests**

Extend the prompt imports with `combine_reminders` and `deferred_tools_reminder`, then add:

```python
def test_deferred_tools_reminder_lists_names_only() -> None:
    names = ["mcp__demo__search", "mcp__demo__fetch"]

    reminder = deferred_tools_reminder(names)

    assert reminder.startswith("<system-reminder>")
    assert reminder.endswith("</system-reminder>")
    assert "ToolSearch" in reminder
    assert 'select:<name>[,<name>...]' in reminder
    assert "\n".join(names) in reminder
    assert "input_schema" not in reminder
    assert names == ["mcp__demo__search", "mcp__demo__fetch"]


def test_deferred_tools_reminder_omits_empty_catalog() -> None:
    assert deferred_tools_reminder([]) == ""


def test_combine_reminders_filters_empty_values_without_nesting() -> None:
    plan = plan_reminder(full=True)
    deferred = deferred_tools_reminder(["mcp__demo__search"])

    combined = combine_reminders("", plan, deferred)

    assert combined == f"{plan}\n\n{deferred}"
    assert combined.count("<system-reminder>") == 2
```

- [ ] **Step 2: Run the tests and verify missing exports**

Run:

```bash
.venv/bin/pytest tests/prompts/test_prompt.py -q
```

Expected: FAIL during import because the two helpers do not exist.

- [ ] **Step 3: Implement the two prompt helpers**

In `src/Arkcode/prompts/reminders.py`:

```python
def deferred_tools_reminder(names: list[str]) -> str:
    """Render undiscovered tool names as a request-scoped system reminder."""

    if not names:
        return ""
    body = (
        "The following deferred tools are available via ToolSearch. "
        "Their schemas are not loaded. Use ToolSearch with query "
        '"select:<name>[,<name>...]" before calling them:\n\n'
        + "\n".join(names)
    )
    return system_reminder(body)


def combine_reminders(*items: str) -> str:
    """Join non-empty, already wrapped request reminders."""

    return "\n\n".join(item for item in items if item)
```

Export both names from `src/Arkcode/prompts/__init__.py` and include them in `__all__`.

- [ ] **Step 4: Run prompt tests and static checks for the prompt package**

Run:

```bash
.venv/bin/pytest tests/prompts/test_prompt.py -q
.venv/bin/ruff check src/Arkcode/prompts tests/prompts
.venv/bin/mypy src/Arkcode/prompts
```

Expected: all commands PASS.

- [ ] **Step 5: Commit the reminder-helper unit**

```bash
git add src/Arkcode/prompts/reminders.py src/Arkcode/prompts/__init__.py tests/prompts/test_prompt.py
git commit -m "feat(prompts): add deferred tool reminders"
```

---

### Task 4: Attach and Refresh Deferred Reminders in the Agent Loop

**Files:**
- Modify: `src/Arkcode/agents/agent.py`
- Test: `tests/agents/test_agent.py`

**Interfaces:**
- Consumes: `Registry.get_deferred_tool_names() -> list[str]`.
- Consumes: `deferred_tools_reminder(names: list[str]) -> str`.
- Consumes: `combine_reminders(*items: str) -> str`.
- Produces: `Request.reminder` containing Plan and/or deferred-tool reminder blocks for the current iteration only.

- [ ] **Step 1: Add imports and a failing two-iteration discovery test**

Import `Writer`, `ToolSearchTool`, `combine_reminders`, and
`deferred_tools_reminder`. Add:

```python
@pytest.mark.asyncio
async def test_deferred_tool_reminder_refreshes_without_entering_history(
    tmp_path: Path,
) -> None:
    deferred = InstrumentedTool("mcp__demo__search", True)
    deferred.should_defer = True
    registry = Registry()
    registry.register(ToolSearchTool(registry))
    registry.register(deferred)
    provider = FakeProvider(
        [
            [
                ToolCallComplete(
                    "discover-1",
                    "ToolSearch",
                    {"query": "select:mcp__demo__search"},
                ),
                end(),
            ],
            [TextDelta("完成"), end()],
        ]
    )
    session_dir = tmp_path / "session"
    with Writer(str(session_dir)) as writer:
        conversation = Conversation(
            on_append=writer.on_append,
            on_replace=writer.on_replace,
        )
        conversation.add_user("搜索远程数据")
        await collect(Agent(provider, registry), conversation)

    first, second = provider.requests
    assert "mcp__demo__search" in first.reminder
    assert "mcp__demo__search" not in second.reminder
    assert [tool.name for tool in first.tools] == ["ToolSearch"]
    assert [tool.name for tool in second.tools] == [
        "ToolSearch",
        "mcp__demo__search",
    ]
    assert all(
        "The following deferred tools" not in message.content
        for message in conversation.messages()
    )
    transcript = (session_dir / "conversation.jsonl").read_text()
    assert "The following deferred tools" not in transcript
```

- [ ] **Step 2: Add a failing Plan/deferred coexistence test**

```python
@pytest.mark.asyncio
async def test_plan_and_deferred_reminders_coexist() -> None:
    provider = FakeProvider([[TextDelta("计划完成"), end()]])
    deferred = InstrumentedTool("mcp__demo__read", True)
    deferred.should_defer = True
    registry = Registry()
    registry.register(ToolSearchTool(registry))
    registry.register(deferred)
    conversation = Conversation()
    conversation.add_user("先查远程资料再计划")

    await collect(Agent(provider, registry), conversation, mode=Mode.PLAN)

    _, tools, suffix = provider.received[0]
    expected_deferred = deferred_tools_reminder(["mcp__demo__read"])
    assert [tool.name for tool in tools] == ["ToolSearch"]
    assert suffix == combine_reminders(plan_reminder(full=True), expected_deferred)
    assert suffix.count("<system-reminder>") == 2
    assert provider.requests[0].system.stable
    assert all(
        "The following deferred tools" not in message.content
        for message in conversation.messages()
    )
```

- [ ] **Step 3: Add a failing emergency-retry reminder test**

Add a second failing test proving an emergency retry receives the same current-iteration reminder:

```python
@pytest.mark.asyncio
async def test_deferred_reminder_is_reused_for_emergency_retry(
    tmp_path: Path,
) -> None:
    deferred = InstrumentedTool("mcp__demo__search", True)
    deferred.should_defer = True
    registry = registry_with(deferred)
    provider = FakeProvider(
        [
            [StreamError(PromptTooLongError("too long"))],
            [TextDelta("<summary>recovered</summary>"), end()],
            [TextDelta("done"), end()],
        ]
    )
    conversation = Conversation()
    conversation.add_user("hello")

    await collect(Agent(provider, registry, runtime=runtime(tmp_path)), conversation)

    main_requests = [request for request in provider.requests if request.tools is not None]
    assert len(main_requests) == 2
    assert main_requests[0].reminder == main_requests[1].reminder
    assert "mcp__demo__search" in main_requests[0].reminder
```

- [ ] **Step 4: Run the focused Agent reminder tests and verify failure**

Run:

```bash
.venv/bin/pytest tests/agents/test_agent.py::test_deferred_tool_reminder_refreshes_without_entering_history tests/agents/test_agent.py::test_plan_and_deferred_reminders_coexist tests/agents/test_agent.py::test_deferred_reminder_is_reused_for_emergency_retry tests/agents/test_agent.py::test_plan_reminder_frequency_and_history_isolation -q
```

Expected: FAIL because Agent currently builds only the Plan reminder.

- [ ] **Step 5: Compose reminders inside every ReAct iteration**

Extend the prompt imports in `src/Arkcode/agents/agent.py`:

```python
from ..prompts import (
    build_system_prompt,
    combine_reminders,
    deferred_tools_reminder,
    gather_environment,
    plan_reminder,
    render_active_skills,
)
```

Replace the single mutable `reminder` branch with request-local composition:

```python
plan = ""
if mode is Mode.PLAN:
    full = iteration == 1 or (iteration - 1) % PLAN_REMINDER_INTERVAL == 0
    plan = plan_reminder(full)
deferred = deferred_tools_reminder(
    self._registry.get_deferred_tool_names()
)
reminder = combine_reminders(plan, deferred)
```

Keep `reminder=reminder` in both the normal `Request` and the emergency-retry `Request`. Do not call `conv.add_user()` or add any new Conversation method.

- [ ] **Step 6: Confirm the existing Plan reminder frequency test remains unchanged**

The existing registry in that test has no deferred tools, so its expected list remains exactly:

```python
[
    plan_reminder(full=True),
    plan_reminder(full=False),
    plan_reminder(full=False),
    plan_reminder(full=False),
    plan_reminder(full=True),
]
```

Retain the assertion that no `<system-reminder>` appears in `conversation.messages()`.

- [ ] **Step 7: Run Agent, prompt, and provider reminder tests**

Run:

```bash
.venv/bin/pytest tests/agents/test_agent.py tests/prompts/test_prompt.py tests/llm/test_anthropic_system.py tests/llm/test_providers.py -q
```

Expected: PASS. Provider adapters need no implementation changes because both already serialize `Request.reminder` without persisting it.

- [ ] **Step 8: Commit the Agent integration unit**

```bash
git add src/Arkcode/agents/agent.py tests/agents/test_agent.py
git commit -m "feat(agent): advertise deferred tools per request"
```

---

### Task 5: Verify End-to-End Behavior and Project Quality Gates

**Files:**
- Verify: `src/Arkcode/mcp/tool_adapter.py`
- Verify: `src/Arkcode/tools/registry.py`
- Verify: `src/Arkcode/prompts/reminders.py`
- Verify: `src/Arkcode/agents/agent.py`
- Verify: all tests changed by Tasks 1–4

**Interfaces:**
- Consumes: all interfaces produced by Tasks 1–4.
- Produces: evidence that AC1–AC10 pass together without Provider, persistence, or context regressions.

- [ ] **Step 1: Run the focused feature suite**

```bash
.venv/bin/pytest tests/mcp/test_mcp_tool.py tests/tools/test_deferred.py tests/tools/test_tool_search.py tests/prompts/test_prompt.py tests/agents/test_agent.py tests/llm/test_anthropic_system.py tests/llm/test_providers.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the entire test suite**

```bash
.venv/bin/pytest -q
```

Expected: PASS with no newly failing tests.

- [ ] **Step 3: Run lint and strict type checking**

```bash
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

Expected: both commands PASS.

- [ ] **Step 4: Review the final diff against the approved spec**

```bash
git diff --check
git diff -- src/Arkcode/mcp/tool_adapter.py src/Arkcode/tools/registry.py src/Arkcode/prompts/reminders.py src/Arkcode/prompts/__init__.py src/Arkcode/agents/agent.py tests/mcp/test_mcp_tool.py tests/tools/test_deferred.py tests/tools/test_tool_search.py tests/prompts/test_prompt.py tests/agents/test_agent.py
```

Expected: no whitespace errors; no changes to Provider, Conversation, Session, Context, MCP connection timing, or runtime JSON Schema validation.

- [ ] **Step 5: Commit any verification-only corrections**

If Steps 1–4 required corrections, stage only the files listed in this plan and commit them:

```bash
git add src/Arkcode/mcp/tool_adapter.py src/Arkcode/tools/registry.py src/Arkcode/prompts/reminders.py src/Arkcode/prompts/__init__.py src/Arkcode/agents/agent.py tests/mcp/test_mcp_tool.py tests/tools/test_deferred.py tests/tools/test_tool_search.py tests/prompts/test_prompt.py tests/agents/test_agent.py
git commit -m "test: verify deferred tool discovery flow"
```

If no correction was necessary, do not create an empty commit.

---

## Requirement Coverage

| Requirement | Implemented and verified by |
|---|---|
| F1, N1, AC1, AC9 | Task 1; Task 5 Provider regressions |
| F2, F3, N2, AC2–AC4 | Task 2 |
| F4, F5, N3, N4 | Task 3 and Task 4 |
| F6, N6, AC5–AC8 | Task 4 |
| F7, N5, N7, AC9–AC10 | Task 5 full regression, lint, and mypy gates |

## Execution Order

```text
Task 1 ─┐
Task 2 ─┼─→ Task 4 → Task 5
Task 3 ─┘
```

Tasks 1–3 affect independent implementation units and may be developed independently, but Task 4 consumes Task 3's reminder helpers and the Registry/MCP behavior verified by Tasks 1–2. Task 5 runs only after all preceding tasks pass their focused tests.
