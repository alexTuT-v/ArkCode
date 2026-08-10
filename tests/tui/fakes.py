"""TUI 控制器与适配器测试的轻量替身。"""

from __future__ import annotations

from dataclasses import dataclass, field

from Arkcode.commands import CommandRegistry
from Arkcode.permissions import Mode
from Arkcode.tools import new_default_registry
from Arkcode.tui.state import SessionState
from Arkcode.tui.widgets.completion import CompletionMenu


class DummyWidget:
    def __init__(self) -> None:
        self.display = True
        self.disabled = False
        self.options: list[str] = []
        self.highlighted: int | None = None
        self.lines: list[object] = []
        self.text = ""
        self.focused = False

    def set_options(self, options: list[str]) -> None:
        self.options = options

    def focus(self) -> None:
        self.focused = True

    def write(self, renderable: object) -> None:
        self.lines.append(renderable)

    def clear(self) -> None:
        self.lines.clear()
        self.text = ""


@dataclass
class FakeSession:
    mode: Mode = Mode.DEFAULT
    provider = None
    skill_executor = None
    agent = None
    permissions = None
    activated: list[object] = field(default_factory=list)
    cleared = 0
    resumed: list[object] = field(default_factory=list)
    writer_closed = 0

    def activate_provider(self, config: object) -> None:
        self.activated.append(config)

    def set_mode(self, mode: Mode) -> None:
        self.mode = mode

    def clear_session(self) -> None:
        self.cleared += 1

    def resume_session(self, info: object) -> None:
        self.resumed.append(info)

    @property
    def journal(self) -> object:
        return _JournalProxy(self)

    def close(self) -> None:
        self.writer_closed += 1

    @property
    def runtime(self) -> object:
        return _RuntimeProxy()

    @property
    def skills(self) -> object:
        return _SkillsProxy()


class _JournalProxy:
    def __init__(self, session: FakeSession) -> None:
        self._session = session
        self.path = "/workspace/.Arkcode/sessions/id/conversation.jsonl"

    def close(self) -> None:
        self._session.writer_closed += 1


class _RuntimeProxy:
    context_window = 200000

    @property
    def session(self) -> object:
        return _SessionProxy()


class _SessionProxy:
    session_id = "id"


class _SkillsProxy:
    def get_catalog(self) -> list[tuple[str, str]]:
        return []

    def get_source_label(self, name: str) -> str | None:
        return "project"

    def get(self, name: str) -> None:
        return None

    def reload(self) -> None:
        return None


class FakeSkillsController:
    def __init__(self) -> None:
        self.registered = 0
        self.reloads = 0

    def register_dynamic_commands(self) -> None:
        self.registered += 1

    def reload_skills(self) -> None:
        self.reloads += 1


class FakeApp:
    def __init__(self) -> None:
        self.state = SessionState.IDLE
        self.pending = None
        self.approve_cursor = 0
        self.completion = CompletionMenu()
        self.cmd_registry = CommandRegistry()
        self.tool_registry = new_default_registry()
        self.resume_items: list[object] = []
        self.resume_filtered: list[object] = []
        self.resume_query = ""
        self.resume_list = DummyWidget()
        self.log = DummyWidget()
        self.input = DummyWidget()
        self.streaming = FakeStreaming()
        self.statusbar_updated = 0
        self.exited = 0
        self.usage_in = 0
        self.usage_out = 0
        self.usage_cache_read = 0
        self.usage_cache_creation = 0
        self.skills = FakeSkillsController()
        self.load_skill_tool = DummyWidget()
        self.mem_mgr = None
        self.turn_start = 0.0
        self._stream_task = None
        self._timer = None
        self.workspace = "/workspace"

    def query_one(self, selector: str, widget_type: object = object) -> DummyWidget:
        if selector == "#log":
            return self.log
        if selector in {"#input", "#prompt", "#streaming", "#statusbar", "#completion"}:
            return self.input
        if selector == "#resume-list":
            return self.resume_list
        return DummyWidget()

    def query(self, selector: str) -> list[DummyWidget]:
        return []

    def update_statusbar(self) -> None:
        self.statusbar_updated += 1

    def refresh_streaming_view(self) -> None:
        return None

    def render_completion(self) -> None:
        return None

    def write_log(self, renderable: object) -> None:
        self.log.write(renderable)

    def clear_log(self) -> None:
        self.log.clear()

    def set_interval(self, interval: float, callback: object) -> object:
        return None

    def _tick(self) -> None:
        return None

    def exit(self) -> None:
        self.exited += 1


class FakeStreaming:
    def __init__(self) -> None:
        self.reset_count = 0
        self.consumed: list[object] = []

    def reset(self) -> None:
        self.reset_count += 1

    async def consume(self, events: object) -> None:
        self.consumed.append(events)
        async for _ in events:  # type: ignore[attr-defined]
            pass
