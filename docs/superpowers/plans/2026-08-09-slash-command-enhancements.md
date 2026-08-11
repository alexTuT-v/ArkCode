# Slash Command 增强 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 ArkCode 的 Slash Command 基础设施（usage 元数据、`/help` 详情、`/session` 与 `/memory` 子命令、自定义 Markdown 命令），并新增 `/mcp` 状态命令与 `/sandbox` OS 级沙箱（三态 + 自动放行）。

**Architecture:** 三个 phase 按依赖顺序实施：Phase 1 命令基础设施（`commands/models.py` 元数据 → help 详情 → session/memory 子命令 → 自定义命令 loader）；Phase 2 在 `mcp/manager.py` 暴露 server 级状态并新增 `/mcp` 命令；Phase 3 新增 `sandbox/` 包（Seatbelt / bwrap 双后端）、Bash 沙箱挂载、权限引擎自动放行与 `/sandbox` 命令。命令层始终通过强类型端口访问能力。

**Tech Stack:** Python 3.12+、asyncio、Textual、PyYAML、pytest、pytest-asyncio、Ruff、strict mypy。

## Global Constraints

- 按用户要求**不自动 git commit**：每任务验证全绿即可，提交由用户手动执行；任务最后的"提交"步骤替换为"确认无未验证改动"。
- 不改变现有 12 个内置命令的 name / kind / 无参数输出；`tests/integration/test_behavior_contracts.py` 必须保持通过。
- 不改变 Bash 非零退出码语义、超时与进程树处理。
- 不引入新第三方依赖（sandbox 仅包装系统自带 `bwrap` / `sandbox-exec`）。
- 本期不做：`/rewind`、`/worktree`、`/tasks`、`/trace`、hooks、ToolSearch、子命令级补全。
- 每个任务结束需跑定向测试；Phase 末跑 `pytest -q`、`ruff check .`、`ruff format --check .`、`mypy src/Arkcode`。
- 遵循现有代码风格：Ruff line-length 88、`from __future__ import annotations`、类型注解完整。

---

### Task 1: Command 元数据（usage / arg_prompt）

**Files:**
- Modify: `src/Arkcode/commands/models.py`
- Modify: `src/Arkcode/commands/handlers/help.py`
- Modify: `src/Arkcode/commands/handlers/session.py`
- Modify: `src/Arkcode/commands/handlers/memory.py`
- Test: `tests/commands/test_metadata.py`（新建）

**Interfaces:**
- Consumes: 现有 `Command` dataclass（name / description / kind / handler / aliases / hidden）。
- Produces: `Command` 增加 `usage: str = ""` 与 `arg_prompt: str = ""`（位于 `aliases` 之后、`hidden` 之前）；Task 2–11 依赖这两个字段展示用法。

- [ ] **Step 1: 写失败测试**

新建 `tests/commands/test_metadata.py`：

```python
from Arkcode.commands import Command, CommandContext, CommandKind


async def _noop(context: CommandContext) -> None:
    return None


def test_command_carries_usage_metadata() -> None:
    command = Command(
        "session",
        "显示当前会话信息",
        CommandKind.LOCAL,
        _noop,
        usage="/session [list | resume <id> | new | delete <id>]",
        arg_prompt="子命令与参数",
    )

    assert command.usage == "/session [list | resume <id> | new | delete <id>]"
    assert command.arg_prompt == "子命令与参数"


def test_usage_defaults_to_empty() -> None:
    command = Command("status", "状态", CommandKind.LOCAL, _noop)

    assert command.usage == ""
    assert command.arg_prompt == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/commands/test_metadata.py -q`
Expected: FAIL（`Command.__init__` 收到意外关键字参数 `usage`）

- [ ] **Step 3: 实现字段**

在 `src/Arkcode/commands/models.py` 的 `Command` 中 `aliases` 之后加入：

```python
    aliases: list[str] = field(default_factory=list)
    usage: str = ""
    arg_prompt: str = ""
    hidden: bool = False
```

- [ ] **Step 4: 为现有 handler 补充 usage**

`handlers/help.py` 的 `Command("help", "显示全部可用命令", CommandKind.LOCAL, handle_help)` 改为追加 `usage="/help [命令名]"`。
`handlers/session.py` 的 `SESSION_COMMAND` 追加 `usage="/session [list | resume <id> | new | delete <id>]"`。
`handlers/memory.py` 的 `MEMORY_COMMAND` 追加 `usage="/memory [list | clear | edit]"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/commands -q`
Expected: PASS（新增 2 项，其余命令测试不受影响——字段位于 `aliases` 之后，现有位置参数调用兼容）

- [ ] **Step 6: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/commands tests/commands`
Expected: 无输出（通过）

---

### Task 2: /help <命令名> 详情

**Files:**
- Modify: `src/Arkcode/commands/handlers/help.py`
- Test: `tests/commands/test_builtins.py`（追加）

**Interfaces:**
- Consumes: `Command.usage` / `Command.arg_prompt`（Task 1）、`CommandRegistry.lookup`。
- Produces: `make_help_command(registry)` 在带参数时输出详情（别名 / 描述 / 用法 / 参数）。

- [ ] **Step 1: 写失败测试**

在 `tests/commands/test_builtins.py` 追加（复用现有 `builtins()` 与 `make_context`）：

```python
@pytest.mark.asyncio
async def test_help_with_command_name_shows_detail() -> None:
    registry = builtins()
    context, ui, _, _, _ = make_context(args="session")

    await dispatch(registry, "help", context)

    output = ui.lines[0]
    assert "/session" in output
    assert "用法: /session [list | resume <id> | new | delete <id>]" in output


@pytest.mark.asyncio
async def test_help_unknown_command_is_friendly() -> None:
    registry = builtins()
    context, ui, _, _, _ = make_context(args="nope")

    await dispatch(registry, "help", context)

    assert "未知命令：nope" in ui.lines[0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/commands/test_builtins.py -q`
Expected: FAIL（help 仍渲染全部命令，忽略 args）

- [ ] **Step 3: 实现详情分支**

`handlers/help.py` 的 `handle_help` 改为：

```python
    async def handle_help(context: CommandContext) -> None:
        name = context.args.strip()
        if not name:
            commands = registry.visible()
            width = max((len(command.name) for command in commands), default=0)
            context.ui.println(
                "\n".join(
                    f"/{command.name.ljust(width)}  {command.description}"
                    for command in commands
                )
            )
            return
        command = registry.lookup(name)
        if command is None:
            context.ui.println(f"未知命令：{name}，输入 /help 查看可用命令")
            return
        lines = [f"/{command.name}"]
        if command.aliases:
            lines[0] += f"  (别名: {', '.join('/' + alias for alias in command.aliases)})"
        lines.append(f"  {command.description}")
        if command.usage:
            lines.append(f"  用法: {command.usage}")
        if command.arg_prompt:
            lines.append(f"  参数: {command.arg_prompt}")
        context.ui.println("\n".join(lines))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/commands -q`
Expected: PASS（无参数 help 输出不变，新增两项通过）

- [ ] **Step 5: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/commands tests/commands`
Expected: 无输出

---

### Task 3: /session 子命令

**Files:**
- Modify: `src/Arkcode/sessions/listing.py`
- Modify: `src/Arkcode/commands/ports.py`
- Modify: `src/Arkcode/commands/handlers/session.py`
- Modify: `src/Arkcode/tui/adapters/command_ui.py`
- Modify: `tests/commands/fakes.py`
- Test: `tests/commands/test_session_command.py`（新建）

**Interfaces:**
- Consumes: `SessionInfo`（id / title / modified_at / model / size / dir）、`list_sessions`、`SessionController.resume(info)`（TUI 侧）。
- Produces: `SessionCommands` 新增 `resume_by_id(session_id: str) -> bool` 与 `delete_session(session_id: str) -> bool`；`StatusQueries` 新增 `session_list() -> list[SessionInfo]`；`sessions.delete_session(sessions_dir, session_id) -> bool`。

- [ ] **Step 1: 写失败测试**

新建 `tests/commands/test_session_command.py`：

```python
from pathlib import Path

import pytest

from Arkcode.commands import CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import FakeSession, FakeStatus, FakeUI, make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


@pytest.mark.asyncio
async def test_session_list_renders_sessions() -> None:
    context, ui, session, _, status = make_context(args="list")
    status.sessions = [
        FakeStatus.SessionRow("20260808-120000-abcd", "alpha topic", 1234),
        FakeStatus.SessionRow("20260807-120000-aaaa", "beta topic", 56),
    ]

    await dispatch(builtins(), "session", context)

    assert "20260808-120000-abcd" in ui.lines[0]
    assert "alpha topic" in ui.lines[0]


@pytest.mark.asyncio
async def test_session_resume_delegates_by_id() -> None:
    context, ui, session, _, status = make_context(args="resume 20260808-120000-abcd")
    status.sessions = [
        FakeStatus.SessionRow("20260808-120000-abcd", "alpha", 10),
    ]

    await dispatch(builtins(), "session", context)

    assert session.resumed_by_id == ["20260808-120000-abcd"]


@pytest.mark.asyncio
async def test_session_delete_refuses_current_session() -> None:
    context, ui, session, _, status = make_context(args="delete 20260808-120000-abcd")
    status.session_id_value = "20260808-120000-abcd"

    await dispatch(builtins(), "session", context)

    assert session.deleted == []
    assert "不能删除当前活跃的会话" in ui.lines[0]


@pytest.mark.asyncio
async def test_session_unknown_subcommand_shows_usage() -> None:
    context, ui, session, _, _ = make_context(args="wat")

    await dispatch(builtins(), "session", context)

    assert "用法: /session" in ui.lines[0]
```

- [ ] **Step 2: 扩展 fakes 与端口**

`tests/commands/fakes.py`：

```python
class FakeStatus:
    @dataclass(frozen=True)
    class SessionRow:
        id: str
        title: str
        size: int = 0

    def __init__(self) -> None:
        ...
        self.sessions: list[FakeStatus.SessionRow] = []

    def session_list(self) -> list[object]:
        return list(self.sessions)
```

`FakeSession` 增加 `self.resumed_by_id: list[str] = []` 与 `self.deleted: list[str] = []`，以及：

```python
    def resume_by_id(self, session_id: str) -> bool:
        self.resumed_by_id.append(session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        self.deleted.append(session_id)
        return True
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest tests/commands/test_session_command.py -q`
Expected: FAIL（端口方法不存在、handler 忽略 args）

- [ ] **Step 4: 实现 delete_session**

`src/Arkcode/sessions/listing.py` 末尾追加：

```python
import shutil


def delete_session(sessions_dir: str, session_id: str) -> bool:
    """删除指定会话目录；目录不存在返回 False。"""

    directory = Path(sessions_dir) / session_id
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True
```

- [ ] **Step 5: 实现端口方法**

`commands/ports.py`：

```python
from ..sessions import SessionInfo


class SessionCommands(Protocol):
    ...
    def resume_by_id(self, session_id: str) -> bool: ...
    def delete_session(self, session_id: str) -> bool: ...


class StatusQueries(Protocol):
    ...
    def session_list(self) -> list[SessionInfo]: ...
```

（`clear_memory` / `memory_dirs` 由 Task 4 加入，届时同步更新 adapter。）

- [ ] **Step 6: 实现 handler 分派**

`handlers/session.py` 替换 `handle_session`：

```python
async def handle_session(context: CommandContext) -> None:
    parts = context.args.split(None, 1)
    sub = parts[0] if parts else ""
    if not sub:
        context.ui.println(
            f"Session: {context.status.session_id()}\nPath: {context.status.session_path()}"
        )
        return
    if sub == "list":
        items = context.status.session_list()
        if not items:
            context.ui.println("没有已保存的会话")
            return
        lines = ["会话列表："]
        for item in items[:10]:
            lines.append(f"  {item.id}  {item.title}  [{item.size} bytes]")
        context.ui.println("\n".join(lines))
        return
    if sub == "resume":
        session_id = parts[1].strip() if len(parts) > 1 else ""
        if not session_id:
            context.ui.println("用法: /session resume <id>")
            return
        if not context.session.resume_by_id(session_id):
            context.ui.println(f"会话未找到: {session_id}")
        return
    if sub == "new":
        context.session.clear_session()
        context.ui.println("新会话已创建")
        return
    if sub == "delete":
        session_id = parts[1].strip() if len(parts) > 1 else ""
        if not session_id:
            context.ui.println("用法: /session delete <id>")
            return
        if session_id == context.status.session_id():
            context.ui.println("不能删除当前活跃的会话")
            return
        if context.session.delete_session(session_id):
            context.ui.println(f"会话已删除: {session_id}")
        else:
            context.ui.println(f"会话未找到: {session_id}")
        return
    context.ui.println("用法: /session [list | resume <id> | new | delete <id>]")
```

- [ ] **Step 7: 实现 adapter 委托**

`tui/adapters/command_ui.py` 的 `SessionCommands` 区段追加：

```python
    def resume_by_id(self, session_id: str) -> bool:
        info = next(
            (
                item
                for item in list_sessions(self._session.sessions_dir)
                if item.id == session_id
            ),
            None,
        )
        if info is None:
            return False
        asyncio.create_task(self._app.sessions.resume(info))
        return True

    def delete_session(self, session_id: str) -> bool:
        return delete_session_dir(self._session.sessions_dir, session_id)
```

顶部 import 补：

```python
from ...sessions import (
    SessionInfo,
    delete_session as delete_session_dir,
    list_sessions,
)
```

`StatusQueries` 区段追加：

```python
    def session_list(self) -> list[SessionInfo]:
        return list_sessions(self._session.sessions_dir)
```

（`clear_memory` 在 Task 4 实现；此处端口已声明，mypy 会要求方法存在，因此 Task 4 必须紧随其后。）

- [ ] **Step 8: 运行测试确认通过**

Run: `.venv/bin/pytest tests/commands tests/application -q`
Expected: PASS（新增 4 项；fakes 已实现新端口方法）

- [ ] **Step 9: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode tests/commands`
Expected: 无输出

---

### Task 4: /memory 子命令

**Files:**
- Modify: `src/Arkcode/memory/store.py`
- Modify: `src/Arkcode/memory/manager.py`
- Modify: `src/Arkcode/application/session.py`
- Modify: `src/Arkcode/commands/handlers/memory.py`
- Modify: `src/Arkcode/tui/adapters/command_ui.py`
- Modify: `tests/commands/fakes.py`
- Test: `tests/memory/test_store_clear.py`（新建）、`tests/commands/test_memory_command.py`（新建）

**Interfaces:**
- Consumes: `Store`（`_dir`、`_rebuild_index`）、`MemoryManager`（`project_store` / `user_store`）。
- Produces: `Store.clear()`、`MemoryManager.clear()`、`SessionService.clear_memory()`、`SessionCommands.clear_memory()`、`StatusQueries.memory_dirs() -> tuple[str, str]`。

- [ ] **Step 1: 写失败测试**

新建 `tests/memory/test_store_clear.py`：

```python
from pathlib import Path

from Arkcode.memory.store import Store


def test_clear_removes_notes_and_rebuilds_index(tmp_path: Path) -> None:
    store = Store(str(tmp_path))
    store.ensure_dir()
    (tmp_path / "user_preference_keep_memory.md").write_text(
        "---\ntype: user_preference\ntitle: t\n---\n内容",
        encoding="utf-8",
    )
    (tmp_path / "MEMORY.md").write_text("- [user_preference] t — 内容", encoding="utf-8")

    store.clear()

    assert not (tmp_path / "user_preference_keep_memory.md").exists()
    assert (tmp_path / "MEMORY.md").exists()
    assert "- [user_preference]" not in (tmp_path / "MEMORY.md").read_text(encoding="utf-8")
```

新建 `tests/commands/test_memory_command.py`：

```python
import pytest

from Arkcode.commands import CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import make_context


def builtins() -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry)
    return registry


@pytest.mark.asyncio
async def test_memory_clear_delegates() -> None:
    context, ui, session, _, _ = make_context(args="clear")

    await dispatch(builtins(), "memory", context)

    assert session.memory_cleared == 1
    assert "所有记忆已清空" in ui.lines[0]


@pytest.mark.asyncio
async def test_memory_edit_shows_directories() -> None:
    context, ui, session, _, status = make_context(args="edit")
    status.memory_dirs_value = ("/work/.Arkcode/memory", "/home/.Arkcode/memory")

    await dispatch(builtins(), "memory", context)

    assert "/work/.Arkcode/memory" in ui.lines[0]
    assert "/home/.Arkcode/memory" in ui.lines[0]
```

- [ ] **Step 2: 扩展 fakes**

`FakeSession` 增加 `self.memory_cleared = 0` 与 `def clear_memory(self) -> None: self.memory_cleared += 1`。
`FakeStatus` 增加 `self.memory_dirs_value = ("", "")` 与 `def memory_dirs(self) -> tuple[str, str]: return self.memory_dirs_value`。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest tests/memory/test_store_clear.py tests/commands/test_memory_command.py -q`
Expected: FAIL（`Store.clear` 不存在、端口方法不存在）

- [ ] **Step 4: 实现 Store.clear 与 MemoryManager.clear**

`memory/store.py` 追加：

```python
    def clear(self) -> None:
        """删除目录内全部笔记并重建索引；MEMORY.md 本身保留。"""

        with self._lock:
            for path in self._dir.glob("*.md"):
                if path.name == "MEMORY.md":
                    continue
                try:
                    path.unlink()
                except OSError:
                    pass
            self._rebuild_index()
```

`memory/manager.py` 追加：

```python
    def clear(self) -> None:
        """清空项目级与用户级 store 的全部记忆笔记。"""

        self.project_store.clear()
        self.user_store.clear()
```

- [ ] **Step 5: 实现 SessionService.clear_memory 与端口**

`application/session.py` 追加：

```python
    def clear_memory(self) -> None:
        if self._memory is not None:
            self._memory.clear()
```

`commands/ports.py` 的 `SessionCommands` 追加 `def clear_memory(self) -> None: ...`，
`StatusQueries` 追加 `def memory_dirs(self) -> tuple[str, str]: ...`。

`tui/adapters/command_ui.py` 追加：

```python
    def clear_memory(self) -> None:
        self._session.clear_memory()

    def memory_dirs(self) -> tuple[str, str]:
        manager = self._app.mem_mgr
        if manager is None:
            return "", ""
        return manager.dirs()
```

`memory/manager.py` 增加 `dirs()`：

```python
    def dirs(self) -> tuple[str, str]:
        return str(self.project_store._dir), str(self.user_store._dir)
```

`StatusQueries` 端口增加 `memory_dirs() -> tuple[str, str]`。

- [ ] **Step 6: 实现 handler 分派**

`handlers/memory.py` 替换 `handle_memory`：

```python
async def handle_memory(context: CommandContext) -> None:
    parts = context.args.split(None, 1)
    sub = parts[0] if parts else ""
    if sub in ("", "list"):
        files = context.status.memory_files()
        context.ui.println("\n".join(files) if files else "无已加载的记忆文件")
        return
    if sub == "clear":
        context.session.clear_memory()
        context.ui.println("所有记忆已清空")
        return
    if sub == "edit":
        project_dir, user_dir = context.status.memory_dirs()
        context.ui.println(f"项目级记忆目录: {project_dir}\n用户级记忆目录: {user_dir}")
        return
    context.ui.println("用法: /memory [list | clear | edit]")
```

- [ ] **Step 7: 运行测试确认通过**

Run: `.venv/bin/pytest tests/memory tests/commands tests/application -q`
Expected: PASS

- [ ] **Step 8: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode tests/memory tests/commands`
Expected: 无输出

---

### Task 5: 自定义 Markdown 命令加载器

**Files:**
- Create: `src/Arkcode/commands/loader.py`
- Modify: `src/Arkcode/commands/__init__.py`
- Modify: `src/Arkcode/tui/controllers/skills.py`
- Test: `tests/commands/test_loader.py`（新建）

**Interfaces:**
- Consumes: `CommandRegistry.register`、`Command`、`CommandKind.PROMPT`、`SessionCommands.submit_prompt`。
- Produces: `register_custom_commands(registry: CommandRegistry, work_dir: str | Path) -> None`。

- [ ] **Step 1: 写失败测试**

新建 `tests/commands/test_loader.py`：

```python
from pathlib import Path

from Arkcode.commands import CommandKind, CommandRegistry, register_builtins
from Arkcode.commands.loader import register_custom_commands

from .fakes import FakeSession, FakeSkills, FakeStatus, FakeUI


def write_command(root: Path, relative: str, body: str, frontmatter: str = "") -> Path:
    path = root / ".Arkcode" / "commands" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    text = f"---\n{frontmatter}\n---\n{body}" if frontmatter else body
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_registers_prompt_commands_with_namespace(tmp_path: Path) -> None:
    write_command(
        tmp_path,
        "git/log.md",
        "总结最近的提交: $ARGUMENTS",
        "description: 查看 git 日志",
    )
    registry = CommandRegistry()

    register_custom_commands(registry, tmp_path)

    command = registry.lookup("git:log")
    assert command is not None
    assert command.kind is CommandKind.PROMPT
    assert command.description == "查看 git 日志"


def test_loader_substitutes_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_command(tmp_path, "run.md", "执行 $ARGUMENTS")
    registry = CommandRegistry()
    register_custom_commands(registry, tmp_path)

    async def invoke() -> None:
        command = registry.lookup("run")
        assert command is not None
        session = FakeSession()
        context = CommandContext(
            args="tests",
            session=session,
            skills=FakeSkills(),
            status=FakeStatus(),
            ui=FakeUI(),
            sandbox=FakeSession(),
        )
        await command.handler(context)
        return session

    import asyncio

    session = asyncio.run(invoke())
    assert session.submitted == [("/run", "执行 tests")]
```

文件顶部 import 补：

```python
import pytest

from Arkcode.commands import CommandContext, CommandKind, CommandRegistry
from Arkcode.commands.loader import register_custom_commands

from .fakes import FakeSession, FakeSkills, FakeStatus, FakeUI
```

- [ ] **Step 2: 扩展 fakes**

`FakeSession` 已有 `submit_prompt`（记录到 `self.submitted: list[tuple[str, str]]`），
无需扩展；断言直接使用 `session.submitted`。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest tests/commands/test_loader.py -q`
Expected: FAIL（`Arkcode.commands.loader` 不存在）

- [ ] **Step 4: 实现 loader**

新建 `src/Arkcode/commands/loader.py`：

```python
"""从 .Arkcode/commands/ 加载自定义 Markdown 命令。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .models import Command, CommandContext, CommandKind
from .registry import CommandRegistry

logger = logging.getLogger(__name__)


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return {}, content
    parts = stripped.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}, content
    if not isinstance(meta, dict):
        return {}, content
    return meta, parts[2]


def _command_name(root: Path, path: Path) -> str:
    relative = path.relative_to(root).with_suffix("")
    return ":".join(relative.parts)


def _make_prompt_handler(body: str, name: str) -> Handler:
    async def handler(context: CommandContext) -> None:
        rendered = body.replace("$ARGUMENTS", context.args)
        if "$ARGUMENTS" not in body and context.args:
            rendered = f"{rendered}\n\n## User Request\n{context.args}"
        context.session.submit_prompt(f"/{name}", rendered)

    return handler


def register_custom_commands(
    registry: CommandRegistry,
    work_dir: str | Path,
) -> None:
    """扫描 .Arkcode/commands/*.md 并注册为 PROMPT 命令。"""

    root = Path(work_dir).resolve() / ".Arkcode" / "commands"
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*.md")):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _split_frontmatter(content)
        name = _command_name(root, path)
        description = str(meta.get("description") or name)
        aliases = meta.get("aliases")
        if isinstance(aliases, str):
            aliases = [aliases]
        if not isinstance(aliases, list) or not all(
            isinstance(item, str) for item in aliases
        ):
            aliases = []
        argument_hint = str(meta.get("argument-hint", ""))
        command = Command(
            name,
            description,
            CommandKind.PROMPT,
            _make_prompt_handler(body, name),
            aliases=aliases,
            usage=f"/{name} [args]",
            arg_prompt=argument_hint,
        )
        try:
            registry.register(command)
        except (RuntimeError, ValueError) as error:
            logger.warning("跳过自定义命令 %s：%s", name, error)
```

`_make_prompt_handler` 的 `Handler` 类型需从 models 导入：

```python
from .models import Command, CommandContext, CommandKind, Handler
```

- [ ] **Step 5: 导出并接入命令表重建**

`commands/__init__.py` 追加：

```python
from .loader import register_custom_commands
```

`tui/controllers/skills.py` 的 `rebuild()` 在 `register_builtins(registry)` 之后追加：

```python
        register_custom_commands(registry, self._app.workspace)
```

并补 import：`from ...commands import register_custom_commands`。

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/commands -q`
Expected: PASS（新增 loader 测试；内置命令测试不受影响——测试用临时目录不产生自定义命令）

- [ ] **Step 7: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/commands src/Arkcode/tui tests/commands`
Expected: 无输出

---

### Task 6: MCP manager server 级状态

**Files:**
- Modify: `src/Arkcode/mcp/manager.py`
- Test: `tests/mcp/test_manager_status.py`（新建）

**Interfaces:**
- Consumes: `Manager._sessions`（`_Session(name, session)`）、`Manager._tools`（`McpTool.full_name`）、`McpStatus`。
- Produces: `McpServerStatus`（name / tool_count / connected / error）与 `Manager.server_summary() -> list[McpServerStatus]`。

- [ ] **Step 1: 写失败测试**

新建 `tests/mcp/test_manager_status.py`：

```python
from Arkcode.mcp.manager import McpServerStatus, Manager
from Arkcode.mcp.manager import _Session
from Arkcode.mcp.tool_adapter import McpTool


class Caller:
    async def call_tool(self, name: str, arguments: dict | None = None):
        return None


def _tool(server: str) -> McpTool:
    return McpTool(
        full_name=f"mcp__{server}__echo",
        remote_name="echo",
        tool_description="echo",
        input_schema={"type": "object"},
        _read_only=True,
        caller=Caller(),
    )


def test_server_summary_reports_connected_and_failed() -> None:
    manager = Manager(configured_servers=2)
    manager._sessions.append(_Session(name="demo", session=object()))
    manager._tools.append(_tool("demo"))
    manager._failures["broken"] = "connect refused"

    summary = manager.server_summary()

    assert summary == [
        McpServerStatus(name="broken", tool_count=0, connected=False, error="connect refused"),
        McpServerStatus(name="demo", tool_count=1, connected=True, error=None),
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/mcp/test_manager_status.py -q`
Expected: FAIL（`McpServerStatus` / `server_summary` 不存在；`_failures` 不存在）

- [ ] **Step 3: 实现状态类型与记录**

`mcp/manager.py` 在 `McpStatus` 之后追加：

```python
@dataclass(frozen=True)
class McpServerStatus:
    """单个 MCP server 的运行时状态。"""

    name: str
    tool_count: int
    connected: bool
    error: str | None = None
```

`Manager.__init__` 增加 `self._failures: dict[str, str] = {}`。

`_wait_until_ready` 中 `if error is not None:` 分支改为：

```python
    if error is not None:
        manager._failures[name] = str(error)
        print(f"[mcp] warn: connect server {name} failed: {error}", file=sys.stderr)
```

`_do_connect` 成功路径（`manager._sessions.append(...)` 之后）追加 `manager._failures.pop(name, None)`。

- [ ] **Step 4: 实现 server_summary**

`mcp/manager.py` 的 `Manager` 追加：

```python
    def server_summary(self) -> list[McpServerStatus]:
        connected = {session.name for session in self._sessions}
        counts: dict[str, int] = {}
        for tool in self._tools:
            parts = tool.full_name.split("__")
            if len(parts) >= 3:
                server = parts[1]
                counts[server] = counts.get(server, 0) + 1
        names = sorted(set(connected) | set(self._failures))
        return [
            McpServerStatus(
                name=name,
                tool_count=counts.get(name, 0),
                connected=name in connected,
                error=self._failures.get(name),
            )
            for name in names
        ]
```

- [ ] **Step 5: 导出并运行测试**

`mcp/__init__.py` 的 `__all__` 追加 `"McpServerStatus"`。

Run: `.venv/bin/pytest tests/mcp -q`
Expected: PASS

- [ ] **Step 6: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/mcp tests/mcp`
Expected: 无输出

---

### Task 7: /mcp 命令

**Files:**
- Modify: `src/Arkcode/commands/models.py`
- Modify: `src/Arkcode/commands/ports.py`
- Create: `src/Arkcode/commands/handlers/mcp.py`
- Modify: `src/Arkcode/commands/builtins.py`
- Modify: `src/Arkcode/tui/adapters/command_ui.py`
- Modify: `src/Arkcode/tui/app.py`
- Test: `tests/commands/test_mcp_command.py`（新建）、`tests/commands/test_builtins.py`（更新命令数）

**Interfaces:**
- Consumes: `Manager.server_summary()`（Task 6）、`ArkCodeApp.mcp_manager`。
- Produces: `McpServerInfo`（commands 层 dataclass）、`StatusQueries.mcp_server_status()`、内置命令 `mcp`。

- [ ] **Step 1: 写失败测试**

新建 `tests/commands/test_mcp_command.py`：

```python
import pytest

from Arkcode.commands import CommandKind, CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import FakeSession, FakeSkills, FakeStatus, FakeUI, make_context


def test_builtins_now_include_mcp() -> None:
    registry = CommandRegistry()
    register_builtins(registry)

    names = [item.name for item in registry.visible()]

    assert "mcp" in names
    assert names[-1] == "status"
    assert registry.lookup("mcp").kind is CommandKind.LOCAL


@pytest.mark.asyncio
async def test_mcp_renders_server_status() -> None:
    context, ui, session, _, status = make_context()
    status.servers = [
        FakeStatus.ServerRow("demo", 1, True, None),
        FakeStatus.ServerRow("broken", 0, False, "connect refused"),
    ]

    await dispatch(builtins(), "mcp", context)

    assert "1/2 已连接" in ui.lines[0]
    assert "demo" in ui.lines[0]
    assert "broken" in ui.lines[0]
    assert "connect refused" in ui.lines[0]
```

- [ ] **Step 2: 扩展 fakes**

`FakeStatus` 增加：

```python
    @dataclass(frozen=True)
    class ServerRow:
        name: str
        tool_count: int
        connected: bool
        error: str | None = None

    self.servers: list[FakeStatus.ServerRow] = []

    def mcp_server_status(self) -> list[object]:
        return list(self.servers)
```

（handler 使用 `McpServerInfo`，测试 fake 返回结构相同字段的对象即可。）

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest tests/commands/test_mcp_command.py -q`
Expected: FAIL（`mcp` 命令不存在）

- [ ] **Step 4: 实现命令领域模型与端口**

`commands/models.py` 追加：

```python
@dataclass(frozen=True, slots=True)
class McpServerInfo:
    name: str
    tool_count: int
    connected: bool
    error: str | None = None
```

`commands/ports.py` 的 `StatusQueries` 追加：

```python
    def mcp_server_status(self) -> list[McpServerInfo]: ...
```

`commands/__init__.py` 导出 `McpServerInfo`。

- [ ] **Step 5: 实现 handler 并注册**

新建 `src/Arkcode/commands/handlers/mcp.py`：

```python
"""/mcp 命令：显示 MCP server 连接状态与工具数量。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_mcp(context: CommandContext) -> None:
    servers = context.status.mcp_server_status()
    if not servers:
        context.ui.println("未配置 MCP")
        return
    connected = sum(1 for server in servers if server.connected)
    lines = [f"MCP 状态（{connected}/{len(servers)} 已连接）"]
    for server in servers:
        state = "已连接" if server.connected else "失败"
        suffix = f"  {server.error}" if server.error else ""
        lines.append(
            f"  {server.name}  [{state}]  {server.tool_count} tools{suffix}"
        )
    context.ui.println("\n".join(lines))


MCP_COMMAND = Command(
    "mcp",
    "显示 MCP 服务器状态",
    CommandKind.LOCAL,
    handle_mcp,
    usage="/mcp",
)
```

`commands/builtins.py` 导入 `MCP_COMMAND` 并加入 `definitions`（放在 `status` 之前，注册顺序不影响可见排序）。

- [ ] **Step 6: 实现 adapter 与 App 装配**

`tui/adapters/command_ui.py` 顶部 import 补：

```python
from ...commands import McpServerInfo
```

`StatusQueries` 区段追加：

```python
    def mcp_server_status(self) -> list[McpServerInfo]:
        manager = self._app.mcp_manager
        if manager is None:
            return []
        return [
            McpServerInfo(
                name=status.name,
                tool_count=status.tool_count,
                connected=status.connected,
                error=status.error,
            )
            for status in manager.server_summary()
        ]
```

`tui/app.py`：

- `ArkCodeApp.__init__` 参数末尾加 `mcp_manager: object | None = None`，`self.mcp_manager = mcp_manager`。
- `new_app` 传 `mcp_manager=runtime.mcp`。

- [ ] **Step 7: 运行测试确认通过**

先在 `tests/integration/test_behavior_contracts.py` 的 `test_builtin_slash_command_contract_is_stable`
期望列表中加入 `"mcp"`（字母序位于 `help` 与 `memory` 之间），并同步更新
`tests/commands/test_builtins.py::test_registers_exactly_twelve_visible_commands`
（改名为 `test_registers_thirteen_visible_commands`，列表加入 `"mcp"`）与
`tests/tui/test_tui.py` 中依赖命令数量的断言（`len(app.completion.items) == 13` → `14`）。

Run: `.venv/bin/pytest tests/commands tests/application tests/tui tests/integration -q`
Expected: PASS

- [ ] **Step 8: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode tests/commands tests/tui`
Expected: 无输出

---

### Task 8: sandbox 包（抽象 + 双后端）

**Files:**
- Create: `src/Arkcode/sandbox/__init__.py`
- Create: `src/Arkcode/sandbox/bwrap.py`
- Create: `src/Arkcode/sandbox/seatbelt.py`
- Test: `tests/sandbox/__init__.py`、`tests/sandbox/test_sandbox.py`（新建）

**Interfaces:**
- Consumes: 无（纯新模块）。
- Produces: `SandboxConfig`（allow_write / deny_write / network_enabled）、`Sandbox`（wrap / available）、`create_sandbox() -> Sandbox | None`、`BwrapSandbox`、`SeatbeltSandbox`。

- [ ] **Step 1: 写失败测试**

新建 `tests/sandbox/test_sandbox.py`：

```python
from Arkcode.sandbox import SandboxConfig, create_sandbox
from Arkcode.sandbox.bwrap import BwrapSandbox
from Arkcode.sandbox.seatbelt import SeatbeltSandbox


def test_bwrap_wrap_builds_isolated_command() -> None:
    sandbox = BwrapSandbox()
    config = SandboxConfig(
        allow_write=["/workspace"],
        deny_write=["/workspace/.Arkcode/config.yaml"],
        network_enabled=False,
    )

    wrapped = sandbox.wrap("git status", config)

    assert wrapped.startswith("bwrap --unshare-user --unshare-pid --ro-bind / /")
    assert "--bind /workspace /workspace" in wrapped
    assert "--ro-bind /workspace/.Arkcode/config.yaml /workspace/.Arkcode/config.yaml" in wrapped
    assert "--unshare-net" in wrapped
    assert wrapped.endswith("-- bash -c git status")


def test_bwrap_network_enabled_omits_unshare_net() -> None:
    wrapped = BwrapSandbox().wrap(
        "true",
        SandboxConfig(network_enabled=True),
    )
    assert "--unshare-net" not in wrapped


def test_seatbelt_profile_denies_default_and_allows_write() -> None:
    sandbox = SeatbeltSandbox()
    config = SandboxConfig(
        allow_write=["/workspace"],
        deny_write=["/workspace/.Arkcode/config.yaml"],
        network_enabled=False,
    )

    wrapped = sandbox.wrap("make test", config)

    assert wrapped.startswith("/usr/bin/sandbox-exec -p")
    assert "(deny default)" in wrapped
    assert '(allow file-write* (subpath "/workspace"))' in wrapped
    assert '(deny file-write* (literal "/workspace/.Arkcode/config.yaml"))' in wrapped
    assert "(deny network*)" in wrapped


def test_create_sandbox_returns_none_on_unknown_platform(monkeypatch) -> None:
    monkeypatch.setattr("platform.system", lambda: "Windows")
    assert create_sandbox() is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/sandbox -q`
Expected: FAIL（包不存在）

- [ ] **Step 3: 实现基类与工厂**

`src/Arkcode/sandbox/__init__.py`：

```python
"""OS 级沙箱：限制 Bash 命令的文件写入与网络访问。

macOS 使用 sandbox-exec（Seatbelt），Linux 使用 bubblewrap（bwrap）。
与 permissions/sandbox.py 的路径级检查不同，这里是操作系统层面的强制隔离。
"""

from __future__ import annotations

import platform
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SandboxConfig:
    """沙箱配置：可写白名单、强制只读黑名单与网络开关。"""

    allow_write: list[str] = field(default_factory=list)
    deny_write: list[str] = field(default_factory=list)
    network_enabled: bool = False


class Sandbox(ABC):
    """沙箱抽象基类，各平台实现 wrap() 与 available()。"""

    @abstractmethod
    def wrap(self, command: str, config: SandboxConfig) -> str:
        """把原始命令包装为沙箱内执行的命令字符串。"""
        ...

    @abstractmethod
    def available(self) -> bool:
        """检测当前环境是否支持该沙箱。"""
        ...


def create_sandbox() -> Sandbox | None:
    """按操作系统选择沙箱实现；不支持的平台返回 None。"""

    system = platform.system()
    if system == "Darwin":
        from .seatbelt import SeatbeltSandbox

        return SeatbeltSandbox()
    if system == "Linux":
        from .bwrap import BwrapSandbox

        return BwrapSandbox()
    return None
```

- [ ] **Step 4: 实现 bwrap 后端**

`src/Arkcode/sandbox/bwrap.py`：

```python
"""Linux bubblewrap（bwrap）沙箱后端。"""

from __future__ import annotations

import shlex
import shutil
from pathlib import Path

from . import Sandbox, SandboxConfig


class BwrapSandbox(Sandbox):
    """通过 bwrap 创建隔离用户命名空间，根文件系统只读。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        args = [
            "bwrap",
            "--unshare-user",
            "--unshare-pid",
            "--ro-bind",
            "/",
            "/",
        ]
        for path in config.allow_write:
            resolved = str(Path(path).resolve())
            args.extend(["--bind", resolved, resolved])
        for path in config.deny_write:
            resolved = str(Path(path).resolve())
            args.extend(["--ro-bind", resolved, resolved])
        if not config.network_enabled:
            args.append("--unshare-net")
        args.extend(["--proc", "/proc", "--dev", "/dev", "--"])
        args.extend(["bash", "-c", command])
        return " ".join(shlex.quote(part) for part in args)

    def available(self) -> bool:
        return shutil.which("bwrap") is not None
```

- [ ] **Step 5: 实现 seatbelt 后端**

`src/Arkcode/sandbox/seatbelt.py`：

```python
"""macOS Seatbelt（sandbox-exec）沙箱后端。"""

from __future__ import annotations

import shlex
from pathlib import Path

from . import Sandbox, SandboxConfig

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _build_profile(config: SandboxConfig) -> str:
    rules = [
        "(version 1)",
        "(deny default)",
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        '(allow file-read* (subpath "/"))',
    ]
    for path in config.allow_write:
        resolved = str(Path(path).resolve())
        rules.append(f'(allow file-write* (subpath "{resolved}"))')
    for path in config.deny_write:
        resolved = str(Path(path).resolve())
        matcher = "subpath" if Path(resolved).is_dir() else "literal"
        rules.append(f'(deny file-write* ({matcher} "{resolved}"))')
    if config.network_enabled:
        rules.append("(allow network*)")
    else:
        rules.append("(deny network*)")
    return "\n".join(rules)


class SeatbeltSandbox(Sandbox):
    """基于 sandbox-exec 的内核级沙箱。"""

    def wrap(self, command: str, config: SandboxConfig) -> str:
        profile = _build_profile(config)
        return (
            f"{_SANDBOX_EXEC} -p {shlex.quote(profile)} "
            f"bash -c {shlex.quote(command)}"
        )

    def available(self) -> bool:
        return Path(_SANDBOX_EXEC).is_file()
```

- [ ] **Step 6: 运行测试确认通过**

Run: `.venv/bin/pytest tests/sandbox -q`
Expected: PASS

- [ ] **Step 7: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/sandbox tests/sandbox`
Expected: 无输出

---

### Task 9: Bash 工具沙箱挂载

**Files:**
- Modify: `src/Arkcode/tools/builtins/bash.py`
- Test: `tests/tools/test_bash_sandbox.py`（新建）

**Interfaces:**
- Consumes: `Sandbox` / `SandboxConfig`（Task 8）。
- Produces: `BashTool(sandbox=None, sandbox_config=None)` 构造参数与同名公开属性；Task 11 的 `/sandbox` 命令通过 `registry.get("bash")` 注入。

- [ ] **Step 1: 写失败测试**

新建 `tests/tools/test_bash_sandbox.py`：

```python
import asyncio

from Arkcode.sandbox import Sandbox, SandboxConfig
from Arkcode.tools.builtins.bash import BashTool


class FakeSandbox(Sandbox):
    def __init__(self) -> None:
        self.wrapped: list[tuple[str, SandboxConfig]] = []

    def wrap(self, command: str, config: SandboxConfig) -> str:
        self.wrapped.append((command, config))
        return f"wrap:{command}"

    def available(self) -> bool:
        return True


def test_bash_wraps_command_when_sandbox_injected() -> None:
    sandbox = FakeSandbox()
    tool = BashTool(sandbox=sandbox, sandbox_config=SandboxConfig())

    assert tool.sandbox is sandbox
    assert tool.sandbox_config is not None


def test_bash_defaults_to_no_sandbox() -> None:
    tool = BashTool()
    assert tool.sandbox is None
    assert tool.sandbox_config is None
```

（execute 侧的行为由集成测试在 Task 11 覆盖：注入 fake 后 `execute` 使用包装命令。此处仅断言属性与构造。）

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/tools/test_bash_sandbox.py -q`
Expected: FAIL（`BashTool` 不接受关键字参数 `sandbox`）

- [ ] **Step 3: 实现构造与 execute 包装**

`src/Arkcode/tools/builtins/bash.py`：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...sandbox import Sandbox, SandboxConfig


class BashTool(Tool):
    """异步执行 shell 命令并捕获输出。"""

    read_only = False

    def __init__(
        self,
        sandbox: Sandbox | None = None,
        sandbox_config: SandboxConfig | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.sandbox_config = sandbox_config
```

`execute` 中，`process = await asyncio.create_subprocess_shell(command, ...)` 之前插入：

```python
        actual_command = command
        if (
            self.sandbox is not None
            and self.sandbox_config is not None
            and self.sandbox.available()
        ):
            actual_command = self.sandbox.wrap(command, self.sandbox_config)
```

并把 `create_subprocess_shell(command, ...)` 改为 `create_subprocess_shell(actual_command, ...)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/pytest tests/tools/test_bash_sandbox.py tests/tools -q`
Expected: PASS（现有 Bash 行为不变）

- [ ] **Step 5: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/tools tests/tools`
Expected: 无输出

---

### Task 10: 权限引擎自动放行

**Files:**
- Modify: `src/Arkcode/permissions/engine.py`
- Modify: `src/Arkcode/application/session.py`
- Test: `tests/permissions/test_engine_sandbox.py`（新建）

**Interfaces:**
- Consumes: `Engine.check(mode, call, read_only)` 现有决策路径。
- Produces: `Engine.sandbox_enabled: bool = False`、`SessionService.permissions` 属性；Task 11 的 `/sandbox` 命令通过 adapter 读写。

- [ ] **Step 1: 写失败测试**

新建 `tests/permissions/test_engine_sandbox.py`：

```python
import pytest

from pathlib import Path

from Arkcode.llm import ToolCall
from Arkcode.permissions import Decision, Mode, new_engine


def _write_call() -> ToolCall:
    return ToolCall("call-1", "write_file", '{"path": "out.txt"}')


def test_sandbox_enabled_auto_allows_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    # 默认 DEFAULT 模式下 write 为 ASK
    decision, _ = engine.check(Mode.DEFAULT, _write_call(), False)
    assert decision is Decision.ASK

    engine.sandbox_enabled = True
    decision, _ = engine.check(Mode.DEFAULT, _write_call(), False)

    assert decision is Decision.ALLOW


def test_sandbox_enabled_does_not_override_plan_deny(tmp_path: Path) -> None:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    engine.sandbox_enabled = True

    decision, _ = engine.check(Mode.PLAN, _write_call(), False)

    assert decision is Decision.DENY
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/pytest tests/permissions/test_engine_sandbox.py -q`
Expected: FAIL（`sandbox_enabled` 属性不存在，且 ASK 未被放行）

- [ ] **Step 3: 实现引擎标志与放行**

`permissions/engine.py` 的 `Engine` 增加类属性：

```python
    sandbox_enabled: bool = False
```

`check()` 中两处返回 `Decision.ASK` 的位置改为放行判断：

```python
        if ask_hit:
            decision = Decision.ALLOW if self.sandbox_enabled else Decision.ASK
            return decision, f"匹配 ask 规则：{friendly_name(call.name)}({target})"
```

与：

```python
        decision = mode_fallback(mode, category)
        if decision is Decision.ASK:
            if self.sandbox_enabled:
                return Decision.ALLOW, f"{mode} 模式下 {category.name.lower()} 类操作已由沙箱自动放行"
            return decision, f"{mode} 模式下 {category.name.lower()} 类操作需确认"
```

（Plan 模式的 DENY 来自 `mode_fallback`，不在 ASK 分支，保持不变。）

- [ ] **Step 4: 暴露 SessionService.permissions**

`application/session.py` 追加：

```python
    @property
    def permissions(self) -> Engine | None:
        return self._permissions
```

（`Engine` 已在 import 中。）

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/pytest tests/permissions tests/application -q`
Expected: PASS

- [ ] **Step 6: 确认无未验证改动（不提交）**

Run: `.venv/bin/ruff check src/Arkcode/permissions src/Arkcode/application`
Expected: 无输出

---

### Task 11: /sandbox 命令与 SandboxCommands 端口

**Files:**
- Modify: `src/Arkcode/commands/models.py`
- Modify: `src/Arkcode/commands/ports.py`
- Create: `src/Arkcode/commands/handlers/sandbox.py`
- Modify: `src/Arkcode/commands/builtins.py`
- Modify: `src/Arkcode/commands/__init__.py`
- Modify: `src/Arkcode/tui/controllers/commands.py`
- Modify: `src/Arkcode/tui/adapters/command_ui.py`
- Modify: `tests/commands/fakes.py`
- Modify: `tests/commands/test_skills.py`
- Modify: `tests/tui/test_command_adapter.py`
- Test: `tests/commands/test_sandbox_command.py`（新建）

**Interfaces:**
- Consumes: `Sandbox` / `SandboxConfig` / `create_sandbox`（Task 8）、`BashTool.sandbox`（Task 9）、`Engine.sandbox_enabled` / `SessionService.permissions`（Task 10）。
- Produces: `SandboxStatus`、`SandboxCommands` Protocol、`CommandContext.sandbox` 字段、内置命令 `sandbox`。

- [ ] **Step 1: 写失败测试**

新建 `tests/commands/test_sandbox_command.py`：

```python
import pytest

from Arkcode.commands import CommandKind, CommandRegistry, register_builtins
from Arkcode.commands.dispatcher import dispatch

from .fakes import FakeSession, FakeSkills, FakeStatus, FakeUI, make_context


def test_builtins_now_include_sandbox() -> None:
    registry = CommandRegistry()
    register_builtins(registry)
    command = registry.lookup("sandbox")
    assert command is not None
    assert command.kind is CommandKind.LOCAL


@pytest.mark.asyncio
async def test_sandbox_status_renders_state() -> None:
    context, ui, session, _, _ = make_context()
    session.sandbox_status_value = (True, True, "SeatbeltSandbox", True)

    await dispatch(builtins(), "sandbox", context)

    assert "已启用" in ui.lines[0]
    assert "SeatbeltSandbox" in ui.lines[0]


@pytest.mark.asyncio
async def test_sandbox_enable_returns_error_message() -> None:
    context, ui, session, _, _ = make_context(args="1")
    session.sandbox_error = "错误: 当前系统不支持沙箱（仅支持 macOS / Linux）"

    await dispatch(builtins(), "sandbox", context)

    assert session.sandbox_enables == [True]
    assert "错误: 当前系统不支持沙箱" in ui.lines[0]


@pytest.mark.asyncio
async def test_sandbox_off_disables() -> None:
    context, ui, session, _, _ = make_context(args="off")

    await dispatch(builtins(), "sandbox", context)

    assert session.sandbox_disables == 1
```

- [ ] **Step 2: 扩展 fakes**

`FakeSession` 增加：

```python
    self.sandbox_status_value = (False, False, "", False)
    self.sandbox_error: str | None = None
    self.sandbox_enables: list[bool] = []
    self.sandbox_disables = 0

    def sandbox_status(self) -> object:
        from Arkcode.commands.models import SandboxStatus

        enabled, auto_allow, backend, available = self.sandbox_status_value
        return SandboxStatus(enabled, auto_allow, backend, available)

    def sandbox_enable(self, auto_allow: bool) -> str | None:
        self.sandbox_enables.append(auto_allow)
        return self.sandbox_error

    def sandbox_disable(self) -> None:
        self.sandbox_disables += 1
```

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest tests/commands/test_sandbox_command.py -q`
Expected: FAIL（`sandbox` 命令与端口不存在）

- [ ] **Step 4: 实现模型与端口**

`commands/models.py` 追加：

```python
@dataclass(frozen=True, slots=True)
class SandboxStatus:
    enabled: bool
    auto_allow: bool
    backend: str
    available: bool
```

`commands/ports.py` 追加：

```python
from .models import SandboxStatus


class SandboxCommands(Protocol):
    def status(self) -> SandboxStatus: ...
    def enable(self, auto_allow: bool) -> str | None: ...
    def disable(self) -> None: ...
```

`CommandContext` 增加字段：

```python
@dataclass(frozen=True, slots=True)
class CommandContext:
    args: str
    session: SessionCommands
    skills: SkillCommands
    status: StatusQueries
    ui: CommandUI
    sandbox: SandboxCommands
```

`commands/__init__.py` 导出 `SandboxCommands`、`SandboxStatus`。

- [ ] **Step 5: 更新全部构造点与契约测试**

`src/Arkcode/tui/controllers/commands.py` 的 `CommandContext(...)` 追加 `sandbox=self._ui`。
`tests/commands/fakes.py` 的 `make_context` 追加 `sandbox=fake_session`（FakeSession 已实现端口方法）。
`tests/commands/test_skills.py` 两处手工 `CommandContext(...)` 追加 `sandbox=FakeSession()`。
`tests/tui/test_command_adapter.py` 的 `CommandContext(...)` 追加 `sandbox=adapter`。
在 `tests/integration/test_behavior_contracts.py` 的期望列表中加入 `"sandbox"`
（字母序位于 `review` 与 `session` 之间），并同步更新
`tests/commands/test_builtins.py` 的可见命令数量断言（13 → 14，列表加入 `"sandbox"`）。
`tests/tui/test_tui.py` 的 `assert len(app.completion.items) == 13` 改为 `== 15`
（`/` 补全含 14 个内置命令 + 1 个 `/skill`）。
`test_registers_exactly_thirteen_visible_commands` 更名为
`test_registers_exactly_fourteen_visible_commands`。

- [ ] **Step 6: 实现 handler 并注册**

新建 `src/Arkcode/commands/handlers/sandbox.py`：

```python
"""/sandbox 命令：OS 级沙箱三态切换。"""

from __future__ import annotations

from ..models import Command, CommandContext, CommandKind


async def handle_sandbox(context: CommandContext) -> None:
    parts = context.args.split(None, 1)
    sub = parts[0] if parts else ""
    if not sub:
        status = context.sandbox.status()
        context.ui.println(
            "\n".join(
                (
                    "沙箱状态",
                    f"  OS 沙箱: {'已启用' if status.enabled else '未启用'}",
                    f"  自动放行: {'是' if status.auto_allow else '否'}",
                    f"  后端: {status.backend or '无'}",
                    f"  后端可用: {'是' if status.available else '否'}",
                )
            )
        )
        return
    if sub in ("1", "on-auto"):
        error = context.sandbox.enable(True)
        context.ui.println(error if error else "沙箱已启用（自动放行）")
        return
    if sub in ("2", "on"):
        error = context.sandbox.enable(False)
        context.ui.println(error if error else "沙箱已启用（常规权限）")
        return
    if sub in ("3", "off"):
        context.sandbox.disable()
        context.ui.println("沙箱已关闭")
        return
    context.ui.println("用法: /sandbox [1|on-auto | 2|on | 3|off]")


SANDBOX_COMMAND = Command(
    "sandbox",
    "沙箱管理",
    CommandKind.LOCAL,
    handle_sandbox,
    usage="/sandbox [1|on-auto | 2|on | 3|off]",
)
```

`commands/builtins.py` 导入 `SANDBOX_COMMAND` 并加入 `definitions`。

- [ ] **Step 7: 实现 adapter 端口**

`tui/adapters/command_ui.py` 追加：

```python
    # ---- SandboxCommands ----

    def sandbox_status(self) -> SandboxStatus:
        engine = self._session.permissions
        bash = self._app.tool_registry.get("bash")
        sandbox = getattr(bash, "sandbox", None) if bash else None
        enabled = engine.sandbox_enabled if engine is not None else False
        return SandboxStatus(
            enabled=enabled,
            auto_allow=enabled,
            backend=type(sandbox).__name__ if sandbox else "",
            available=sandbox.available() if sandbox else False,
        )

    def sandbox_enable(self, auto_allow: bool) -> str | None:
        from ..sandbox import SandboxConfig, create_sandbox

        bash = self._app.tool_registry.get("bash")
        if bash is None:
            return "错误: 未找到 Bash 工具"
        sandbox = getattr(bash, "sandbox", None)
        if sandbox is None:
            sandbox = create_sandbox()
            if sandbox is None:
                return "错误: 当前系统不支持沙箱（仅支持 macOS / Linux）"
        if not sandbox.available():
            return f"错误: 沙箱后端 {type(sandbox).__name__} 不可用，请安装对应工具"
        workspace = self._app.workspace
        config = SandboxConfig(
            allow_write=[str(workspace), tempfile.gettempdir()],
            deny_write=[
                str(workspace / ".Arkcode" / "config.yaml"),
                str(workspace / ".Arkcode" / "permissions.local.yaml"),
                str(workspace / ".Arkcode" / "skills"),
            ],
            network_enabled=False,
        )
        bash.sandbox = sandbox
        bash.sandbox_config = config
        engine = self._session.permissions
        if engine is not None:
            engine.sandbox_enabled = auto_allow
        return None

    def sandbox_disable(self) -> None:
        bash = self._app.tool_registry.get("bash")
        if bash is not None:
            bash.sandbox = None
            bash.sandbox_config = None
        engine = self._session.permissions
        if engine is not None:
            engine.sandbox_enabled = False
```

头部 import 补 `import tempfile`、`from ...commands.models import SandboxStatus`。

- [ ] **Step 8: 运行测试确认通过**

Run: `.venv/bin/pytest tests/commands tests/tui tests/permissions tests/tools -q`
Expected: PASS（全部构造点已更新）

- [ ] **Step 9: 全量验证并确认无未验证改动**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src/Arkcode`
Expected: 全绿；不 git commit

---

### Task 12: README 命令文档与最终验证

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 全部已完成任务。
- Produces: README 命令清单更新与最终验证记录。

- [ ] **Step 1: 更新 README 命令清单**

在 README 的对话界面说明处补充新命令：

```markdown
### Slash 命令

- `/help [命令名]`：列出命令或查看单个命令的用法详情
- `/session [list | resume <id> | new | delete <id>]`：会话管理
- `/memory [list | clear | edit]`：记忆管理
- `/mcp`：查看 MCP 服务器状态
- `/sandbox [1|on-auto | 2|on | 3|off]`：OS 级沙箱三态切换
```

- [ ] **Step 2: 全量验证**

Run: `.venv/bin/pytest -q`
Expected: 全绿（现有 412 项 + 本期新增项）

Run: `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy src/Arkcode && .venv/bin/python -m Arkcode --version`
Expected: 全部通过，版本输出 `0.1.0`

- [ ] **Step 3: 行为契约复核**

Run: `.venv/bin/pytest tests/integration/test_behavior_contracts.py -q`
Expected: PASS（契约列表已含 `mcp` 与 `sandbox`，共 14 项）

- [ ] **Step 4: 确认无未验证改动（不提交）**

Run: `git status --short`
Expected: 本次所有改动未提交（由用户手动提交）
