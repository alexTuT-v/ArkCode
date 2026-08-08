# ArkCode Structure Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize ArkCode into explicit application, domain, and TUI boundaries without changing any user-visible capability, protocol, command, configuration, persistence format, or interaction.

**Architecture:** Migrate leaf packages first, then split Agent and command responsibilities, introduce `ApplicationRuntime` and `SessionService` as the sole composition boundary, and finally decompose the Textual UI. Every task leaves the repository runnable and fully verified; old import paths are removed rather than retained through compatibility facades.

**Tech Stack:** Python 3.12+, asyncio, Textual, Rich, Anthropic SDK, OpenAI SDK, MCP, PyYAML, httpx, pytest, pytest-asyncio, Ruff, strict mypy.

## Global Constraints

- Preserve `Arkcode` and `python -m Arkcode` startup behavior.
- Preserve all `.env` field names and provider-selection behavior.
- Preserve tool names, order, JSON Schema, read-only classification, argument names, and result text.
- Preserve permission modes, approval options, slash commands, aliases, completion ordering, Plan/Do behavior, Skills behavior, and session resume behavior.
- Preserve every path and format under `.Arkcode/`, including session JSONL, compact boundaries, memory, settings, and Skills.
- Preserve TUI layout, bindings, focus behavior, streaming display, approval interaction, and status display.
- Do not add hooks, rewind, headless/remote mode, OS sandboxing, worktrees, or multi-agent features.
- Do not retain compatibility modules for `Arkcode.agent`, `Arkcode.command`, `Arkcode.compact`, `Arkcode.permission`, `Arkcode.prompt`, `Arkcode.session`, or `Arkcode.tool`.
- Do not touch the unrelated untracked `.learnings/`, `hello.txt`, or `helloWorld.txt` files.
- Each task must end with `pytest`, `ruff check .`, `ruff format --check .`, and `mypy src/Arkcode` passing before commit.

---

## Locked File Responsibilities

- `application/bootstrap.py`: construct process-level concrete dependencies.
- `application/runtime.py`: own process-level runtime state.
- `application/lifecycle.py`: start and close MCP, Writer, cleanup jobs, and tracked background tasks.
- `application/session.py`: own active Provider, Agent, Conversation, Writer, compact runtime, and Skill execution.
- `agents/agent.py`: public Agent API and ReAct loop only.
- `agents/streaming.py`: translate Provider stream events into Agent events and stream state.
- `agents/execution.py`: permission checks, approval waits, tool batching, execution, and result events.
- `commands/dispatcher.py`: slash-command lookup, busy policy, command-kind policy, and exception boundary.
- `commands/ports.py`: strongly typed handler dependencies.
- `commands/handlers/<name>.py`: exactly one built-in command per module.
- `context/manager.py`: automatic and manual context-management entry points.
- `tui/app.py`: Textual composition, bindings, and Textual lifecycle callbacks only.
- `tui/controllers/`: translate UI actions to application service calls.
- `tui/streaming/`: consume Agent events and track presentation state.
- `tui/views/`: create Rich/Textual renderables without mutating application state.
- `tui/widgets/`: Textual widgets and keyboard behavior only.
- `tests/<domain>/`: unit tests mirroring the source domain.
- `tests/integration/`: cross-domain startup, session, Agent, Skills, and TUI flows.

---

### Task 1: Restore a Green Baseline and Freeze External Contracts

**Files:**
- Create: `docs/mcp/mcp-servers.example.yaml`
- Create: `tests/integration/test_behavior_contracts.py`
- Modify: `tests/test_package_facades.py`

**Interfaces:**
- Consumes: current `new_default_registry`, command registry, MCP config loader, and persisted path constants.
- Produces: executable contract tests that every later namespace move must update without changing expected values.

- [ ] **Step 1: Reproduce the existing documentation failure**

Run:

```bash
.venv/bin/pytest tests/test_mcp_config.py::test_documented_example_is_a_valid_three_server_config -v
```

Expected: FAIL with `FileNotFoundError` for `docs/mcp/mcp-servers.example.yaml`.

- [ ] **Step 2: Add the valid three-server MCP example**

Create `docs/mcp/mcp-servers.example.yaml` with exactly:

```yaml
mcp_servers:
  github:
    type: stdio
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
  local-sqlite:
    type: stdio
    command: uvx
    args:
      - mcp-server-sqlite
      - --db-path
      - ./example.db
  example-http:
    type: http
    url: https://example.com/mcp
    headers:
      Authorization: "Bearer ${EXAMPLE_TOKEN}"
```

- [ ] **Step 3: Write behavior-contract tests before moving packages**

Create `tests/integration/test_behavior_contracts.py`:

```python
from pathlib import Path

from Arkcode.command import Registry as CommandRegistry
from Arkcode.command import register_builtins
from Arkcode.tool import new_default_registry


def test_builtin_tool_contract_is_stable() -> None:
    registry = new_default_registry()
    definitions = registry.definitions()
    assert [item.name for item in definitions] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert [
        item.name for item in definitions if registry.is_read_only(item.name)
    ] == ["read_file", "glob", "grep"]


def test_builtin_slash_command_contract_is_stable() -> None:
    registry = CommandRegistry()
    register_builtins(registry)
    assert [item.name for item in registry.visible()] == [
        "clear",
        "compact",
        "do",
        "exit",
        "help",
        "memory",
        "permission",
        "plan",
        "resume",
        "review",
        "session",
        "status",
    ]


def test_persisted_project_paths_are_stable() -> None:
    root = Path("/workspace")
    assert root / ".Arkcode" / "sessions" == Path(
        "/workspace/.Arkcode/sessions"
    )
    assert root / ".Arkcode" / "memory" == Path(
        "/workspace/.Arkcode/memory"
    )
    assert root / ".Arkcode" / "skills" == Path(
        "/workspace/.Arkcode/skills"
    )
```

- [ ] **Step 4: Remove old-facade assertions from the future contract**

Delete `tests/test_package_facades.py`. Old import compatibility is explicitly outside the design; later tasks replace it with new package API and architecture tests.

- [ ] **Step 5: Verify the baseline**

Run:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

Expected: 0 failures and all static checks exit 0.

- [ ] **Step 6: Commit the green contract baseline**

```bash
git add docs/mcp/mcp-servers.example.yaml tests/integration/test_behavior_contracts.py tests/test_package_facades.py
git commit -m "test: freeze refactor behavior contracts"
```

---

### Task 2: Rename Low-Coupling Domain Packages

**Files:**
- Move: `src/Arkcode/permission/` → `src/Arkcode/permissions/`
- Move: `src/Arkcode/prompt/` → `src/Arkcode/prompts/`
- Move: `src/Arkcode/session/` → `src/Arkcode/sessions/`
- Rename: `src/Arkcode/permissions/rule.py` → `src/Arkcode/permissions/rules.py`
- Rename: `src/Arkcode/prompts/reminder.py` → `src/Arkcode/prompts/reminders.py`
- Rename: `src/Arkcode/sessions/list.py` → `src/Arkcode/sessions/listing.py`
- Modify: every source and test import reported by the verification command below.

**Interfaces:**
- Consumes: existing `Mode`, `Outcome`, `Engine`, prompt builders, session Writer/list/load functions.
- Produces: the same APIs under `Arkcode.permissions`, `Arkcode.prompts`, and `Arkcode.sessions` only.

- [ ] **Step 1: Record current import consumers**

```bash
rg -n 'Arkcode\.(permission|prompt|session)|\.\.(permission|prompt|session)' src tests
```

Expected: matches in Agent, CLI, commands, compact/context, TUI, and tests.

- [ ] **Step 2: Move the packages and renamed modules**

```bash
git mv src/Arkcode/permission src/Arkcode/permissions
git mv src/Arkcode/prompt src/Arkcode/prompts
git mv src/Arkcode/session src/Arkcode/sessions
git mv src/Arkcode/permissions/rule.py src/Arkcode/permissions/rules.py
git mv src/Arkcode/prompts/reminder.py src/Arkcode/prompts/reminders.py
git mv src/Arkcode/sessions/list.py src/Arkcode/sessions/listing.py
```

- [ ] **Step 3: Update imports without adding compatibility files**

Apply this exact mapping throughout `src/` and `tests/`:

```text
Arkcode.permission        → Arkcode.permissions
Arkcode.prompt            → Arkcode.prompts
Arkcode.session           → Arkcode.sessions
.permission               → .permissions
.prompt                   → .prompts
.session                  → .sessions
permissions.rule          → permissions.rules
prompts.reminder          → prompts.reminders
sessions.list             → sessions.listing
```

Update relative imports inside all three moved packages to reflect their unchanged parent depth.

- [ ] **Step 4: Prove old paths are gone and targeted tests pass**

```bash
! rg -n 'Arkcode\.(permission|prompt|session)(\.| import)|\.\.(permission|prompt|session)(\.| import)' src tests
.venv/bin/pytest tests/test_permission_core.py tests/test_prompt.py tests/test_session.py tests/test_session_writer.py -q
```

Expected: no old-path matches and all targeted tests pass.

- [ ] **Step 5: Run full verification and commit**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
git add src tests
git commit -m "refactor: rename core domain packages"
```

---

### Task 3: Split Configuration and Provider Implementations

**Files:**
- Move: `src/Arkcode/config.py` → `src/Arkcode/config/loader.py`
- Create: `src/Arkcode/config/__init__.py`
- Create: `src/Arkcode/config/models.py`
- Move: `src/Arkcode/llm/anthropic_provider.py` → `src/Arkcode/llm/providers/anthropic.py`
- Move: `src/Arkcode/llm/openai_provider.py` → `src/Arkcode/llm/providers/openai.py`
- Create: `src/Arkcode/llm/providers/__init__.py`
- Modify: `src/Arkcode/llm/factory.py`
- Modify: configuration and provider tests and import consumers.

**Interfaces:**
- Consumes: environment variables and the existing Provider Protocol.
- Produces: `Config`, `ConfigError`, `ProviderConfig`, `ProtocolName`, `effective_context_window`, and `load` from `Arkcode.config`; concrete providers from `Arkcode.llm.providers`.

- [ ] **Step 1: Update tests to the target provider paths**

Change provider imports to:

```python
from Arkcode.config import ConfigError, ProviderConfig, effective_context_window, load
from Arkcode.llm.providers.anthropic import AnthropicProvider
from Arkcode.llm.providers.openai import OpenAIProvider
```

Run:

```bash
.venv/bin/pytest tests/test_config.py tests/test_providers.py tests/test_anthropic_system.py -q
```

Expected: collection fails because `Arkcode.config` is not yet a package and `llm.providers` does not exist.

- [ ] **Step 2: Move config and provider files**

```bash
mkdir -p src/Arkcode/config src/Arkcode/llm/providers
git mv src/Arkcode/config.py src/Arkcode/config/loader.py
git mv src/Arkcode/llm/anthropic_provider.py src/Arkcode/llm/providers/anthropic.py
git mv src/Arkcode/llm/openai_provider.py src/Arkcode/llm/providers/openai.py
```

- [ ] **Step 3: Extract immutable configuration models**

Move `ProtocolName`, `ConfigError`, `ProviderConfig`, and `Config` into `config/models.py`. In `config/loader.py`, import them with:

```python
from .models import Config, ConfigError, ProtocolName, ProviderConfig
```

Create `config/__init__.py`:

```python
from .loader import effective_context_window, load
from .models import Config, ConfigError, ProtocolName, ProviderConfig

__all__ = [
    "Config",
    "ConfigError",
    "ProtocolName",
    "ProviderConfig",
    "effective_context_window",
    "load",
]
```

- [ ] **Step 4: Repair provider-relative imports and factory imports**

Provider implementations are now one level deeper. Import ProviderConfig from the package-level `Arkcode.config` API and use `..types`/`..errors` for LLM contracts. Update `llm/factory.py` to import:

```python
from .providers.anthropic import AnthropicProvider
from .providers.openai import OpenAIProvider
```

Create `llm/providers/__init__.py` exporting only `AnthropicProvider` and `OpenAIProvider`.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest tests/test_config.py tests/test_providers.py tests/test_anthropic_system.py tests/test_cli.py -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
git add src tests
git commit -m "refactor: split config and llm providers"
```

---

### Task 4: Reorganize Tools and the MCP Adapter

**Files:**
- Move: `src/Arkcode/tool/` → `src/Arkcode/tools/`
- Create: `src/Arkcode/tools/builtins/__init__.py`
- Move: six built-in tool modules into `src/Arkcode/tools/builtins/`
- Create: `src/Arkcode/tools/skill_tools/__init__.py`
- Move: Skill tool modules into `src/Arkcode/tools/skill_tools/`
- Rename: `src/Arkcode/tools/defaults.py` → `src/Arkcode/tools/factory.py`
- Rename: `src/Arkcode/tools/builtins/glob_tool.py` → `glob.py`
- Rename: `src/Arkcode/tools/builtins/grep_tool.py` → `grep.py`
- Move: `src/Arkcode/mcp/tool.py` → `src/Arkcode/mcp/tool_adapter.py`
- Modify: `src/Arkcode/llm/types.py`, registries, CLI/TUI wiring, Skills executor, and tool/MCP tests.

**Interfaces:**
- Consumes: existing `Tool`, `ToolDefinition`, `Result`, and Registry behavior.
- Produces: `Arkcode.tools` public API and `Arkcode.mcp.tool_adapter` with byte-for-byte equivalent schemas and results.

- [ ] **Step 1: Point contract and tool tests at target imports**

Use these target paths:

```python
from Arkcode.tools import Registry, Result, new_default_registry
from Arkcode.tools.base import Tool, ToolDefinition
from Arkcode.tools.builtins.bash import BashTool
from Arkcode.tools.builtins.grep import GrepTool
from Arkcode.tools.skill_tools.load_skill import LoadSkillTool
from Arkcode.mcp.tool_adapter import McpTool, adapt_tool
```

Run the tests and confirm collection failure:

```bash
.venv/bin/pytest tests/test_tool.py tests/test_skill_tools.py tests/test_mcp_tool.py tests/integration/test_behavior_contracts.py -q
```

- [ ] **Step 2: Move tool packages and modules**

```bash
git mv src/Arkcode/tool src/Arkcode/tools
mkdir -p src/Arkcode/tools/builtins src/Arkcode/tools/skill_tools
git mv src/Arkcode/tools/bash.py src/Arkcode/tools/builtins/bash.py
git mv src/Arkcode/tools/edit_file.py src/Arkcode/tools/builtins/edit_file.py
git mv src/Arkcode/tools/glob_tool.py src/Arkcode/tools/builtins/glob.py
git mv src/Arkcode/tools/grep_tool.py src/Arkcode/tools/builtins/grep.py
git mv src/Arkcode/tools/read_file.py src/Arkcode/tools/builtins/read_file.py
git mv src/Arkcode/tools/write_file.py src/Arkcode/tools/builtins/write_file.py
git mv src/Arkcode/tools/install_skill.py src/Arkcode/tools/skill_tools/install_skill.py
git mv src/Arkcode/tools/load_skill.py src/Arkcode/tools/skill_tools/load_skill.py
git mv src/Arkcode/tools/defaults.py src/Arkcode/tools/factory.py
git mv src/Arkcode/mcp/tool.py src/Arkcode/mcp/tool_adapter.py
```

- [ ] **Step 3: Repair imports and package exports**

Apply this exact public mapping:

```text
Arkcode.tool                         → Arkcode.tools
Arkcode.tool.bash                    → Arkcode.tools.builtins.bash
Arkcode.tool.edit_file               → Arkcode.tools.builtins.edit_file
Arkcode.tool.glob_tool               → Arkcode.tools.builtins.glob
Arkcode.tool.grep_tool               → Arkcode.tools.builtins.grep
Arkcode.tool.read_file               → Arkcode.tools.builtins.read_file
Arkcode.tool.write_file              → Arkcode.tools.builtins.write_file
Arkcode.tool.install_skill           → Arkcode.tools.skill_tools.install_skill
Arkcode.tool.load_skill              → Arkcode.tools.skill_tools.load_skill
Arkcode.mcp.tool                     → Arkcode.mcp.tool_adapter
```

Update built-in modules to import `Result`, `Tool`, and `truncate` from their parent package with `..base` and `..utils`. Update `llm/types.py` to import `ToolDefinition` from `..tools.base`.

Create explicit exports in `tools/__init__.py`, `tools/builtins/__init__.py`, `tools/skill_tools/__init__.py`, and `mcp/__init__.py`. Do not create `Arkcode/tool`.

- [ ] **Step 4: Verify schemas, plan visibility, MCP, and full suite**

```bash
! test -e src/Arkcode/tool
.venv/bin/pytest tests/test_tool.py tests/test_skill_tools.py tests/test_mcp_tool.py tests/test_agent.py tests/integration/test_behavior_contracts.py -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "refactor: reorganize tools and mcp adapter"
```

---

### Task 5: Replace Compact and Conversation with Context Domains

**Files:**
- Move: `src/Arkcode/compact/` → `src/Arkcode/context/`
- Rename: `compact.py` → `manager.py`
- Rename: `const.py` → `constants.py`
- Rename: `layer1.py` → `spill.py`
- Rename: `layer2.py` → `summary.py`
- Rename: `summary_prompt.py` → `prompts.py`
- Rename: `token.py` → `tokens.py`
- Move: `src/Arkcode/conversation.py` → `src/Arkcode/conversations/manager.py`
- Create: `src/Arkcode/conversations/__init__.py`
- Modify: Agent runtime, Skills executor, sessions, and all compact/conversation tests.

**Interfaces:**
- Consumes: existing `ManageInput`, `ManageOutput`, `TriggerKind`, `manage_context`, compact state, and `Conversation` behavior.
- Produces: identical behavior from `Arkcode.context` and `Arkcode.conversations`.

- [ ] **Step 1: Move tests to target import paths and confirm failure**

Use:

```python
from Arkcode.context import ManageInput, TriggerKind, manage_context
from Arkcode.context.spill import offload_and_snip
from Arkcode.context.summary import auto_compact
from Arkcode.context.tokens import estimate_tokens
from Arkcode.conversations import Conversation
```

Run:

```bash
.venv/bin/pytest tests/compact tests/test_conversation.py tests/test_session.py -q
```

Expected: collection fails on missing target packages.

- [ ] **Step 2: Move and rename the modules**

```bash
git mv src/Arkcode/compact src/Arkcode/context
git mv src/Arkcode/context/compact.py src/Arkcode/context/manager.py
git mv src/Arkcode/context/const.py src/Arkcode/context/constants.py
git mv src/Arkcode/context/layer1.py src/Arkcode/context/spill.py
git mv src/Arkcode/context/layer2.py src/Arkcode/context/summary.py
git mv src/Arkcode/context/summary_prompt.py src/Arkcode/context/prompts.py
git mv src/Arkcode/context/token.py src/Arkcode/context/tokens.py
mkdir -p src/Arkcode/conversations
git mv src/Arkcode/conversation.py src/Arkcode/conversations/manager.py
```

- [ ] **Step 3: Repair internal imports and expose the new APIs**

Inside `context`, apply:

```text
.compact        → .manager
.const          → .constants
.layer1         → .spill
.layer2         → .summary
.summary_prompt → .prompts
.token          → .tokens
```

Create `conversations/__init__.py`:

```python
from .manager import Conversation

__all__ = ["Conversation"]
```

Update Agent, Skills, sessions, tests, and any type-check-only imports. Keep all compact path calculations and JSONL records unchanged.

- [ ] **Step 4: Verify compact recovery and persistence before full suite**

```bash
.venv/bin/pytest tests/compact tests/test_conversation.py tests/test_session.py tests/test_session_writer.py tests/test_agent.py -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "refactor: establish context and conversation domains"
```

---

### Task 6: Build One-Command-Per-Handler Command Architecture

**Files:**
- Move: `src/Arkcode/command/` → `src/Arkcode/commands/`
- Create: `src/Arkcode/commands/models.py`
- Create: `src/Arkcode/commands/parser.py`
- Create: `src/Arkcode/commands/ports.py`
- Create: `src/Arkcode/commands/dispatcher.py`
- Create: `src/Arkcode/commands/builtins.py`
- Create: 13 modules under `src/Arkcode/commands/handlers/`
- Create: `tests/commands/fakes.py`
- Create: `tests/commands/test_dispatcher.py`
- Modify: `src/Arkcode/commands/skills.py` by distributing management and factory logic into `handlers/skill.py`.
- Modify: command tests, TUI command adapter tests, and Skills command tests.

**Interfaces:**
- Consumes: existing command names, Kind values, handler behavior, Registry replacement semantics, and dynamic Skill precedence.
- Produces: `CommandContext`, `Command`, `CommandKind`, `CommandRegistry`, `dispatch`, and one module per built-in handler.

- [ ] **Step 1: Write dispatcher and port tests against target APIs**

Create `tests/commands/test_dispatcher.py` with fakes implementing these ports:

```python
from dataclasses import dataclass, field

from Arkcode.commands import Command, CommandContext, CommandKind, CommandRegistry
from Arkcode.commands.dispatcher import dispatch
from Arkcode.permissions import Mode


@dataclass
class FakeUI:
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def println(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def request_exit(self) -> None:
        self.lines.append("exit")


class FakeSession:
    current_mode = Mode.DEFAULT

    def mode(self) -> Mode:
        return self.current_mode

    def set_mode(self, mode: Mode) -> None:
        self.current_mode = mode

    def idle(self) -> bool:
        return True

    def submit_prompt(self, label: str, prompt: str) -> None:
        return None

    def force_compact(self) -> None:
        return None

    def open_resume(self) -> None:
        return None

    def clear_session(self) -> None:
        return None


class FakeSkills:
    def list_skills(self) -> list[tuple[str, str, str]]:
        return []

    def skill_info(self, name: str) -> str | None:
        return None

    def reload_skills(self) -> None:
        return None

    async def invoke_skill(self, name: str, args: str) -> None:
        return None


class FakeStatus:
    def usage(self) -> tuple[int, int]:
        return (0, 0)

    def model_name(self) -> str:
        return "model"

    def cwd(self) -> str:
        return "/workspace"

    def tool_count(self) -> int:
        return 0

    def memory_files(self) -> list[str]:
        return []

    def session_path(self) -> str:
        return "/workspace/.Arkcode/sessions/id"

    def session_id(self) -> str:
        return "id"


async def test_dispatch_passes_parsed_arguments_to_handler() -> None:
    received: list[str] = []

    async def handler(ctx: CommandContext) -> None:
        received.append(ctx.args)

    registry = CommandRegistry()
    registry.register(Command("sample", "sample", CommandKind.LOCAL, handler))
    context = CommandContext(
        args="value",
        session=FakeSession(),
        skills=FakeSkills(),
        status=FakeStatus(),
        ui=FakeUI(),
    )

    handled = await dispatch(registry, "sample", context)

    assert handled is True
    assert received == ["value"]
```

Move the reusable fake classes to `tests/commands/fakes.py`; import them into dispatcher and handler tests so strict mypy verifies every Protocol implementation.

Run:

```bash
.venv/bin/pytest tests/commands/test_dispatcher.py -q
```

Expected: collection fails because `Arkcode.commands` does not exist.

- [ ] **Step 2: Move the package and create the target skeleton**

```bash
git mv src/Arkcode/command src/Arkcode/commands
mkdir -p src/Arkcode/commands/handlers
```

Move `Command`, `Kind`, and Handler definitions into `models.py`; move `parse` into `parser.py`; retain Registry logic in `registry.py` and rename it `CommandRegistry`.

- [ ] **Step 3: Define strongly typed command ports**

Create `commands/ports.py` with these exact operations:

```python
from __future__ import annotations

from typing import Protocol

from ..permissions import Mode


class CommandUI(Protocol):
    def println(self, message: str) -> None: pass
    def error(self, message: str) -> None: pass
    def request_exit(self) -> None: pass


class SessionCommands(Protocol):
    def mode(self) -> Mode: pass
    def set_mode(self, mode: Mode) -> None: pass
    def idle(self) -> bool: pass
    def submit_prompt(self, label: str, prompt: str) -> None: pass
    def force_compact(self) -> None: pass
    def open_resume(self) -> None: pass
    def clear_session(self) -> None: pass


class SkillCommands(Protocol):
    def list_skills(self) -> list[tuple[str, str, str]]: pass
    def skill_info(self, name: str) -> str | None: pass
    def reload_skills(self) -> None: pass
    async def invoke_skill(self, name: str, args: str) -> None: pass


class StatusQueries(Protocol):
    def usage(self) -> tuple[int, int]: pass
    def model_name(self) -> str: pass
    def cwd(self) -> str: pass
    def tool_count(self) -> int: pass
    def memory_files(self) -> list[str]: pass
    def session_path(self) -> str: pass
    def session_id(self) -> str: pass
```

Define `CommandContext` and Handler in `models.py`:

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .ports import CommandUI, SessionCommands, SkillCommands, StatusQueries


@dataclass(frozen=True, slots=True)
class CommandContext:
    args: str
    session: SessionCommands
    skills: SkillCommands
    status: StatusQueries
    ui: CommandUI


Handler = Callable[[CommandContext], Awaitable[None]]
```

- [ ] **Step 4: Implement dispatcher policy once**

`commands/dispatcher.py` must:

1. return `False` for an unknown command;
2. reject UI and PROMPT commands while `context.session.idle()` is false with the existing busy message;
3. call the handler once;
4. convert handler exceptions to `context.ui.error(str(error))`;
5. return `True` for every recognized command.

- [ ] **Step 5: Split all built-in handlers**

Create one module for each command with this preserved behavior:

| Module | Command behavior |
|---|---|
| `clear.py` | call `session.clear_session()` |
| `compact.py` | call `session.force_compact()` |
| `do.py` | switch to default mode and submit the existing execute directive |
| `exit.py` | call `ui.request_exit()` |
| `help.py` | render visible commands from the injected registry-backed handler factory |
| `memory.py` | print the current memory file list |
| `permission.py` | print the current permission mode |
| `plan.py` | switch to Plan mode |
| `resume.py` | call `session.open_resume()` |
| `review.py` | submit the existing review prompt with arguments |
| `session.py` | print current session ID and path |
| `skill.py` | list/info/reload Skills and build dynamic Skill handlers |
| `status.py` | print mode, model, cwd, tool count, and usage |

Each module exports one `*_COMMAND` constant except `help.py` and dynamic Skill handlers, which remain factories because they need the active registry or Skill name.

Create `commands/builtins.py` with a stable tuple in the existing alphabetical-visible behavior and a `register_builtins(registry)` function.

- [ ] **Step 6: Update the TUI adapter and dynamic Skill integration**

Replace the old broad `UI` adapter with an object implementing all four ports. Dynamic Skill command registration must retain project-over-user precedence, conflict replacement, hot reload, completion updates, and restoration of an overridden built-in command after Skill deletion.

- [ ] **Step 7: Verify commands and commit**

```bash
.venv/bin/pytest tests/test_command_builtins.py tests/test_command_dispatch.py tests/test_command_registry.py tests/test_command_skills.py tests/commands/test_dispatcher.py tests/test_tui_skills.py -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
git add src tests
git commit -m "refactor: split slash command handlers"
```

---

### Task 7: Split the Agent Stream and Tool Execution Boundaries

**Files:**
- Move: `src/Arkcode/agent/` → `src/Arkcode/agents/`
- Consolidate: Agent event models into `src/Arkcode/agents/events.py`
- Create: `src/Arkcode/agents/streaming.py`
- Create: `src/Arkcode/agents/execution.py`
- Modify: `src/Arkcode/agents/agent.py`
- Modify: `src/Arkcode/agents/runtime.py`
- Modify: Agent, compact, Skills, TUI, and package imports/tests.

**Interfaces:**
- Consumes: current Agent constructor and `run`, `run_force_compact`, Skill activation, event stream, cancellation, approval, tool batching, and unknown-tool behavior.
- Produces: the same public behavior under `Arkcode.agents`, with stream and execution helpers isolated.

- [ ] **Step 1: Update Agent tests to target imports and record failure**

Use:

```python
from Arkcode.agents import Agent, AgentEvent, ApprovalRequest, SessionRuntime
from Arkcode.agents.events import Phase, ToolEvent, Usage
```

Run:

```bash
.venv/bin/pytest tests/test_agent.py tests/test_agent_runtime.py tests/test_skills_executor.py -q
```

Expected: collection fails because `Arkcode.agents` does not exist.

- [ ] **Step 2: Move the package and consolidate event models**

```bash
git mv src/Arkcode/agent src/Arkcode/agents
```

Move `Phase`, `Usage`, `ApprovalRequest`, `ToolEvent`, and `AgentEvent` from `agents/agent.py`, plus compact events from the existing `agents/event.py`, into `agents/events.py`. Delete the now-empty old event module.

- [ ] **Step 3: Extract Provider streaming without changing event order**

Move `_StreamState`, `_next_or_cancel`, and `_stream_once` behavior into `agents/streaming.py` with this callable contract:

```python
async def stream_once(
    provider: Provider,
    request: Request,
    cancel: asyncio.Event,
    state: StreamState,
) -> AsyncIterator[AgentEvent]:
    pass
```

`StreamState` retains text, thinking, signature, calls, usage, ended, ok, and error fields. The function must close the Provider iterator in `finally` exactly as the current Agent does.

- [ ] **Step 4: Extract tool execution without changing batching**

Move `_BatchState`, `_cancelled_result`, permission approval waiting, `execute_one`, `_run_batch`, and `_execute_batched` into `agents/execution.py`. Expose:

```python
class ToolExecutor:
    def __init__(
        self,
        registry: Registry,
        engine: Engine,
        permissions_enabled: bool,
        runtime: SessionRuntime,
    ) -> None:
        pass

    async def execute(
        self,
        calls: list[ToolCall],
        mode: Mode,
        cancel: asyncio.Event,
        state: BatchState,
    ) -> AsyncIterator[AgentEvent]:
        pass
```

Preserve consecutive read-only concurrency, serialized side-effect calls, approval outcomes, persisted allow rules, file-read recovery capture, cancellation, timeout, and result ordering.

- [ ] **Step 5: Reduce Agent to orchestration**

`agents/agent.py` must build the Provider Request, call context management, delegate streaming to `stream_once`, delegate tools to `ToolExecutor`, update Conversation and usage anchors, schedule memory updates, and enforce iteration/unknown-tool limits. It must not contain Textual code or subprocess/tool implementation details.

- [ ] **Step 6: Verify event ordering, cancellation, approvals, and full suite**

```bash
.venv/bin/pytest tests/test_agent.py tests/test_agent_runtime.py tests/test_skills_executor.py tests/compact/test_concurrency.py -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

- [ ] **Step 7: Commit**

```bash
git add src tests
git commit -m "refactor: split agent execution boundaries"
```

---

### Task 8: Introduce Application Runtime and Session Service

**Files:**
- Create: `src/Arkcode/application/__init__.py`
- Create: `src/Arkcode/application/runtime.py`
- Create: `src/Arkcode/application/lifecycle.py`
- Create: `src/Arkcode/application/session.py`
- Create: `src/Arkcode/application/bootstrap.py`
- Move: `src/Arkcode/cli.py` → `src/Arkcode/application/cli.py`
- Modify: `src/Arkcode/__main__.py`
- Modify: `src/Arkcode/tui/app.py` constructor/wiring only.
- Create: `tests/application/test_runtime.py`
- Create: `tests/application/test_session_service.py`
- Move/update: `tests/test_cli.py` → `tests/application/test_cli.py`

**Interfaces:**
- Consumes: Config, MCP manager, tool registry, permission engine, memory manager, instruction loader, session Writer/runtime, Provider factory, Agent, Skill loader/executor, and TUI factory.
- Produces: `ApplicationRuntime`, `SessionService`, `build_runtime`, and `main`.

- [ ] **Step 1: Write lifecycle tests first**

`tests/application/test_runtime.py` must prove this close order with instrumented fakes:

```python
async def test_shutdown_closes_writer_then_tasks_then_mcp() -> None:
    calls: list[str] = []
    runtime = make_runtime(calls)

    await runtime.shutdown()

    assert calls == ["writer", "tasks", "mcp"]
```

`tests/application/test_session_service.py` must prove provider activation creates the Agent once, clear replaces Conversation/Writer only after new session creation succeeds, resume restores messages without re-appending them, and cancel sets the active cancel event.

Run:

```bash
.venv/bin/pytest tests/application -q
```

Expected: collection fails because `Arkcode.application` does not exist.

- [ ] **Step 2: Define ApplicationRuntime**

Create a dataclass in `application/runtime.py` containing:

```python
@dataclass
class ApplicationRuntime:
    workspace: Path
    config: Config
    tools: Registry
    permissions: Engine
    mcp: McpManager
    mcp_status: McpStatus
    memory: MemoryManager
    skills: SkillLoader
    session: SessionService
    cleanup_task: asyncio.Task[None] | None = None

    async def shutdown(self) -> None:
        pass
```

Use the actual imported MCP manager type name from `Arkcode.mcp`; do not introduce a second wrapper type solely to satisfy this annotation.

- [ ] **Step 3: Implement SessionService with explicit ownership**

`application/session.py` owns active Provider, Agent, Conversation, SessionRuntime, Writer, mode, cancel event, and tracked Skill tasks. Implement the operations approved in the design:

```python
class SessionService:
    def activate_provider(self, config: ProviderConfig) -> None: pass
    async def submit_message(self, text: str) -> AsyncIterator[AgentEvent]: pass
    async def force_compact(self) -> tuple[int, int]: pass
    def clear_session(self) -> None: pass
    def resume_session(self, info: SessionInfo) -> None: pass
    def set_mode(self, mode: Mode) -> None: pass
    def cancel_turn(self) -> None: pass
    async def shutdown(self) -> None: pass
```

Preserve the existing atomic clear behavior: construct the new SessionContext and Writer before replacing or closing the old state. Preserve Skill clearing, catalog retention, usage reset, Provider model assignment, and resume callbacks.

- [ ] **Step 4: Move bootstrap and CLI assembly**

Move CLI error handling to `application/cli.py`. Implement async `build_runtime(workspace: Path, version: str) -> ApplicationRuntime` in `bootstrap.py` by moving the current concrete construction from CLI and TUI. `__main__.py` imports `main` from `.application.cli`.

The CLI must still print the same ConfigError text, use the same generic startup error, return the same exit codes, and close MCP in all exit paths.

- [ ] **Step 5: Adapt the existing TUI constructor without decomposing it yet**

Change `new_app` and `ArkCodeApp.__init__` to receive `ApplicationRuntime` or its `SessionService` instead of separately constructing Skills, tools, sessions, and Agent. Keep rendering methods in place until Tasks 9 and 10.

- [ ] **Step 6: Verify lifecycle and integration**

```bash
.venv/bin/pytest tests/application tests/test_tui.py tests/test_tui_skills.py -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

- [ ] **Step 7: Commit**

```bash
git add src tests
git commit -m "refactor: introduce application runtime"
```

---

### Task 9: Extract TUI Widgets, Views, and Streaming Presentation

**Files:**
- Create: `src/Arkcode/tui/styles.tcss`
- Create: `src/Arkcode/tui/state.py`
- Create: `src/Arkcode/tui/widgets/` modules.
- Create: `src/Arkcode/tui/views/` modules.
- Create: `src/Arkcode/tui/streaming/controller.py`
- Create: `src/Arkcode/tui/streaming/state.py`
- Modify: `src/Arkcode/tui/app.py`
- Remove after migration: `src/Arkcode/tui/complete.py`, `stream.py`, `view.py`, and `select.py`.
- Create/move: corresponding `tests/tui/` unit tests.

**Interfaces:**
- Consumes: current `MessageInput`, `CompletionMenu`, provider options, render functions, `StreamControllerMixin`, `ToolDisplay`, and TUI state enum.
- Produces: presentation-only widgets/views and a stream controller with unchanged rendering output.

- [ ] **Step 1: Move view tests to target modules and confirm failure**

Use target imports such as:

```python
from Arkcode.tui.views.messages import error_block, render_markdown, user_block
from Arkcode.tui.views.tools import tool_line, tool_result_summary
from Arkcode.tui.widgets.completion import CompletionMenu
from Arkcode.tui.widgets.message_input import MessageInput
from Arkcode.tui.streaming.state import ToolDisplay
```

Run the affected TUI tests and confirm missing-module failures.

- [ ] **Step 2: Extract CSS and pure state**

Move the existing `ArkCodeApp.CSS` string unchanged into `tui/styles.tcss` and set `CSS_PATH = "styles.tcss"`. Move `SessionState` and `next_mode` into `tui/state.py` without changing enum values or ordering.

- [ ] **Step 3: Extract widgets without business dependencies**

Move:

```text
MessageInput       → widgets/message_input.py
CompletionMenu     → widgets/completion.py
provider_options   → widgets/provider_select.py
status-bar widget construction helpers → widgets/status_bar.py
```

Widgets may import Textual and immutable view/state models, but not Agent, MCP manager, Session Writer, Memory manager, or Skill loader.

- [ ] **Step 4: Split render functions by output type**

Move existing functions without changing returned Rich/Textual objects:

```text
user/error/markdown/streaming blocks → views/messages.py
tool line/result summary             → views/tools.py
approval block                       → views/approvals.py
status bar/MCP status                → views/status.py
banner                               → views/banner.py
```

Update snapshot/exact render assertions before deleting `tui/view.py`.

- [ ] **Step 5: Extract streaming presentation state**

Move `ToolDisplay` and mutable presentation fields into `streaming/state.py`. Convert `StreamControllerMixin` into `StreamingController` in `streaming/controller.py`. It consumes `AgentEvent` and invokes a small host Protocol for widget updates; it must not call Provider or ToolRegistry directly.

- [ ] **Step 6: Verify TUI presentation and delete old modules**

```bash
.venv/bin/pytest tests/tui tests/test_tui.py tests/test_command_complete.py -q
! test -e src/Arkcode/tui/complete.py
! test -e src/Arkcode/tui/stream.py
! test -e src/Arkcode/tui/view.py
! test -e src/Arkcode/tui/select.py
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

- [ ] **Step 7: Commit**

```bash
git add src tests
git commit -m "refactor: extract tui presentation modules"
```

---

### Task 10: Extract TUI Controllers and Command Adapter

**Files:**
- Create: `src/Arkcode/tui/adapters/command_ui.py`
- Create: `src/Arkcode/tui/controllers/approvals.py`
- Create: `src/Arkcode/tui/controllers/chat.py`
- Create: `src/Arkcode/tui/controllers/commands.py`
- Create: `src/Arkcode/tui/controllers/providers.py`
- Create: `src/Arkcode/tui/controllers/sessions.py`
- Create: `src/Arkcode/tui/controllers/skills.py`
- Modify: `src/Arkcode/tui/app.py`
- Remove after migration: `src/Arkcode/tui/commands.py` and `resume.py`.
- Create: controller and adapter tests under `tests/tui/`.

**Interfaces:**
- Consumes: `ApplicationRuntime`, `SessionService`, command ports/dispatcher, provider configurations, session listings, approval futures, and extracted widgets/views.
- Produces: an `ArkCodeApp` that only owns Textual composition/bindings/lifecycle and delegates all actions.

- [ ] **Step 1: Write controller tests before extraction**

Create tests proving:

- Chat controller sends plain input to `SessionService.submit_message` and slash input to command dispatcher.
- Provider controller activates exactly the selected ProviderConfig.
- Session controller starts/cancels resume mode and delegates the selected SessionInfo.
- Approval controller resolves each future once with the same three Outcome values and keyboard mapping.
- Skill controller reloads Skills through SessionService without reaching into Agent internals.
- Command adapter implements all four command Protocols.

Run and confirm missing-module failures:

```bash
.venv/bin/pytest tests/tui/test_controllers.py tests/tui/test_command_adapter.py -q
```

- [ ] **Step 2: Implement the command adapter**

`CommandUIAdapter` receives `ArkCodeApp` only for display primitives and receives `SessionService` for domain operations. It implements `CommandUI`, `SessionCommands`, `SkillCommands`, and `StatusQueries`; it must not read attributes prefixed with `_` from Agent, Registry, or Writer.

- [ ] **Step 3: Extract controllers by interaction**

Move existing logic into the six controller modules. Controllers may call public `ApplicationRuntime` and `SessionService` methods and update widgets through explicit App methods. They may not construct Provider, Agent, Writer, SkillLoader, or MCP manager objects.

- [ ] **Step 4: Reduce ArkCodeApp to its approved responsibility**

Keep in `tui/app.py`:

- Textual `compose` and bindings;
- widget lookup helpers;
- Textual message callbacks that immediately delegate;
- mount/unmount calls into ApplicationRuntime lifecycle;
- immutable references to controllers and presentation state.

Remove concrete dependency construction, direct Conversation replacement, direct Writer closing, direct Skill registry mutation, and Agent private-field access.

- [ ] **Step 5: Verify full TUI behavior and file-size target**

```bash
.venv/bin/pytest tests/tui tests/test_tui.py tests/test_tui_skills.py -q
wc -l src/Arkcode/tui/app.py
```

Expected: TUI tests pass and `app.py` is between 200 and 300 lines. If necessary, move only clearly bounded Textual callbacks to the relevant controller; do not hide business logic in another large file.

- [ ] **Step 6: Run full verification and commit**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
git add src tests
git commit -m "refactor: isolate tui controllers"
```

---

### Task 11: Mirror Tests and Enforce Architecture Boundaries

**Files:**
- Move: remaining root test modules into their matching `tests/<domain>/` directories.
- Move: `tests/compact/` → `tests/context/`.
- Create: `tests/architecture/test_dependencies.py`
- Create: `tests/architecture/test_removed_paths.py`
- Modify: `pyproject.toml` only if test discovery or mypy package selection requires it.

**Interfaces:**
- Consumes: final source package tree.
- Produces: a test tree matching source ownership and executable dependency constraints.

- [ ] **Step 1: Move tests to the approved tree**

Use `git mv` so history remains visible. Apply this ownership mapping:

```text
Agent/runtime tests                    → tests/agents/
CLI/bootstrap/runtime tests            → tests/application/
Command tests                          → tests/commands/
Config tests                           → tests/config/
tests/compact                          → tests/context/
Conversation tests                     → tests/conversations/
Instruction tests                      → tests/instructions/
Provider/LLM tests                     → tests/llm/
MCP tests                              → tests/mcp/
Memory tests                           → tests/memory/
Permission tests                       → tests/permissions/
Prompt tests                           → tests/prompts/
Session tests                          → tests/sessions/
Skill parser/loader/install unit tests → tests/skills/
Tool tests                             → tests/tools/
Textual component/controller tests     → tests/tui/
Cross-domain Agent/Skill/TUI flows     → tests/integration/
```

Keep `tests/fixtures/mcp_stdio_server.py` in place.

- [ ] **Step 2: Add a source dependency guard**

Create `tests/architecture/test_dependencies.py` that parses imports with `ast` and fails when:

- any module under `agents`, `commands`, `context`, `llm`, `mcp`, `memory`, `permissions`, `prompts`, `sessions`, `skills`, or `tools` imports `Arkcode.tui`;
- any domain module imports `Arkcode.application`;
- any module outside `application` constructs the concrete MCP manager, Memory manager, permission engine, or default tool registry;
- any TUI module imports a concrete LLM Provider implementation.

Implement the guard with `ast` rather than text matching so comments and strings do not create false failures:

```python
import ast
from pathlib import Path

SOURCE = Path(__file__).parents[2] / "src" / "Arkcode"
DOMAINS = {
    "agents", "commands", "context", "llm", "mcp", "memory",
    "permissions", "prompts", "sessions", "skills", "tools",
}


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    package = ["Arkcode", *path.relative_to(SOURCE).parent.parts]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                modules.append(node.module)
            else:
                keep = len(package) - (node.level - 1)
                modules.append(".".join([*package[:keep], node.module]))
    return modules


def called_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def test_domains_do_not_import_application_or_tui() -> None:
    failures: list[str] = []
    for domain in sorted(DOMAINS):
        for path in sorted((SOURCE / domain).rglob("*.py")):
            for module in imported_modules(path):
                if module.startswith(("Arkcode.application", "Arkcode.tui")):
                    failures.append(f"{path.relative_to(SOURCE)} -> {module}")
    assert failures == []


def test_tui_does_not_import_concrete_providers() -> None:
    failures = [
        f"{path.relative_to(SOURCE)} -> {module}"
        for path in sorted((SOURCE / "tui").rglob("*.py"))
        for module in imported_modules(path)
        if module.startswith("Arkcode.llm.providers")
    ]
    assert failures == []


def test_concrete_construction_is_confined_to_application() -> None:
    constructors = {
        "MemoryManager",
        "new_default_registry",
        "new_engine",
        "new_manager",
    }
    failures = [
        f"{path.relative_to(SOURCE)} -> {name}"
        for path in sorted(SOURCE.rglob("*.py"))
        if "application" not in path.relative_to(SOURCE).parts
        for name in called_names(path)
        if name in constructors
    ]
    assert failures == []
```

- [ ] **Step 3: Add removed-path assertions**

Create `tests/architecture/test_removed_paths.py`:

```python
from pathlib import Path


def test_old_source_packages_are_removed() -> None:
    root = Path(__file__).parents[2] / "src" / "Arkcode"
    for name in (
        "agent",
        "command",
        "compact",
        "permission",
        "prompt",
        "session",
        "tool",
    ):
        assert not (root / name).exists(), name
```

- [ ] **Step 4: Verify collection, architecture, and full suite**

```bash
.venv/bin/pytest --collect-only -q
.venv/bin/pytest tests/architecture -q
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
```

- [ ] **Step 5: Commit**

```bash
git add tests pyproject.toml
git commit -m "test: mirror domains and enforce architecture"
```

---

### Task 12: Final Documentation, Smoke Verification, and Cleanup

**Files:**
- Modify: `README.md`
- Modify: `.env.example` only if import/module documentation refers to old paths.
- Modify: `spec.md`, `plan.md`, `task.md`, and `checklist.md` to record the completed refactor without changing product requirements.
- Modify: `docs/superpowers/specs/2026-08-08-arkcode-structure-refactor-design.md` only if implementation discovered an approved naming correction.
- Verify: all source/test paths and package metadata.

**Interfaces:**
- Consumes: completed source tree and all prior verification gates.
- Produces: documented final architecture and evidence that no stale import or behavior remains.

- [ ] **Step 1: Update developer documentation**

Document:

- the final source tree;
- the one-way dependency rule;
- the application composition boundary;
- one-command-per-handler convention;
- the TUI controller/view/widget separation;
- commands for tests, Ruff, format, and mypy.

Do not advertise any non-goal feature.

- [ ] **Step 2: Scan for stale paths and forbidden private coupling**

```bash
! rg -n 'Arkcode\.(agent|command|compact|permission|prompt|session|tool)(\.| import)' src tests README.md
! rg -n 'agent\._|writer\._|registry\._' src/Arkcode/tui src/Arkcode/commands
```

Expected: no matches. If a test intentionally asserts absence using a string, exclude `tests/architecture/test_removed_paths.py` from the first scan.

- [ ] **Step 3: Run automated verification from a clean process**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
.venv/bin/python -m Arkcode --version
```

Expected: all checks exit 0 and the version command prints the existing ArkCode version.

- [ ] **Step 4: Run Textual smoke scenarios**

Using test providers or the existing smoke harness, verify and record evidence for:

1. single-Provider startup and multi-Provider selection;
2. ordinary streamed reply and Markdown finalization;
3. read-only tool execution and write approval choices;
4. Plan followed by Do;
5. manual Compact;
6. Clear and Resume;
7. Skill list, inline Skill, fork Skill, install approval, and reload;
8. Escape cancellation and Ctrl+C shutdown.

Do not use real production API keys in logs or committed fixtures.

- [ ] **Step 5: Check final size and status constraints**

```bash
wc -l src/Arkcode/agents/agent.py src/Arkcode/tui/app.py
git status --short
```

Expected: Agent is approximately 300–400 lines, TUI App is approximately 200–300 lines, and only the pre-existing unrelated `.learnings/`, `hello.txt`, and `helloWorld.txt` remain untracked.

- [ ] **Step 6: Commit final documentation**

```bash
git add README.md .env.example spec.md plan.md task.md checklist.md docs
git commit -m "docs: document refactored architecture"
```

- [ ] **Step 7: Perform final verification after the commit**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy src/Arkcode
git log --oneline --decorate -15
git status --short
```

Expected: all verification commands exit 0, the migration is represented by reviewable commits, and no task-scoped changes remain uncommitted.
