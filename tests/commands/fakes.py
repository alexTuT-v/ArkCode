"""命令端口实现的测试替身，用于 mypy 校验 Protocol 实现。"""

from __future__ import annotations

from dataclasses import dataclass, field

from Arkcode.commands import CommandContext
from Arkcode.permissions import Mode


@dataclass
class FakeUI:
    lines: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    exit_requested: int = 0

    def println(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def request_exit(self) -> None:
        self.exit_requested += 1


class FakeSession:
    def __init__(self) -> None:
        self.current_mode = Mode.DEFAULT
        self.modes: list[Mode] = []
        self.submitted: list[tuple[str, str]] = []
        self.resumed_by_id: list[str] = []
        self.deleted: list[str] = []
        self.memory_cleared = 0
        self.sandbox_status_value = (False, False, "", False)
        self.sandbox_error: str | None = None
        self.sandbox_enables: list[bool] = []
        self.sandbox_disables = 0
        self.compacts = 0
        self.resumes = 0
        self.clears = 0
        self.busy = False

    def mode(self) -> Mode:
        return self.current_mode

    def set_mode(self, mode: Mode) -> None:
        self.current_mode = mode
        self.modes.append(mode)

    def idle(self) -> bool:
        return not self.busy

    def submit_prompt(self, label: str, prompt: str) -> None:
        self.submitted.append((label, prompt))

    def force_compact(self) -> None:
        self.compacts += 1

    def open_resume(self) -> None:
        self.resumes += 1

    def clear_session(self) -> None:
        self.clears += 1

    def resume_by_id(self, session_id: str) -> bool:
        self.resumed_by_id.append(session_id)
        return True

    def delete_session(self, session_id: str) -> bool:
        self.deleted.append(session_id)
        return True

    def clear_memory(self) -> None:
        self.memory_cleared += 1

    def status(self) -> object:
        from Arkcode.commands.models import SandboxStatus

        enabled, auto_allow, backend, available = self.sandbox_status_value
        return SandboxStatus(enabled, auto_allow, backend, available)

    def enable(self, auto_allow: bool) -> str | None:
        self.sandbox_enables.append(auto_allow)
        return self.sandbox_error

    def disable(self) -> None:
        self.sandbox_disables += 1


class FakeSkills:
    def __init__(self) -> None:
        self.skills: list[tuple[str, str, str]] = []
        self.info: str | None = None
        self.info_for: str | None = None
        self.reload_count = 0
        self.invoked: list[tuple[str, str]] = []

    def list_skills(self) -> list[tuple[str, str, str]]:
        return self.skills

    def skill_info(self, name: str) -> str | None:
        if self.info_for is not None and name != self.info_for:
            return None
        return self.info

    def reload_skills(self) -> None:
        self.reload_count += 1

    async def invoke_skill(self, name: str, args: str) -> None:
        self.invoked.append((name, args))


class FakeStatus:
    @dataclass(frozen=True)
    class SessionRow:
        id: str
        title: str
        size: int = 0

    @dataclass(frozen=True)
    class ServerRow:
        name: str
        tool_count: int
        connected: bool
        error: str | None = None

    def __init__(self) -> None:
        self.usage_in = 0
        self.usage_out = 0
        self.model = "model"
        self.workspace = "/workspace"
        self.tools = 0
        self.memory: list[str] = []
        self.session_path_value = "/workspace/.Arkcode/sessions/id"
        self.session_id_value = "id"
        self.sessions: list[FakeStatus.SessionRow] = []
        self.memory_dirs_value = ("", "")
        self.servers: list[FakeStatus.ServerRow] = []

    def usage(self) -> tuple[int, int]:
        return self.usage_in, self.usage_out

    def model_name(self) -> str:
        return self.model

    def cwd(self) -> str:
        return self.workspace

    def tool_count(self) -> int:
        return self.tools

    def memory_files(self) -> list[str]:
        return self.memory

    def session_path(self) -> str:
        return self.session_path_value

    def session_id(self) -> str:
        return self.session_id_value

    def session_list(self) -> list[object]:
        return list(self.sessions)

    def memory_dirs(self) -> tuple[str, str]:
        return self.memory_dirs_value

    def mcp_server_status(self) -> list[object]:
        return list(self.servers)


def make_context(
    *,
    args: str = "",
    ui: FakeUI | None = None,
    session: FakeSession | None = None,
    skills: FakeSkills | None = None,
    status: FakeStatus | None = None,
) -> tuple[CommandContext, FakeUI, FakeSession, FakeSkills, FakeStatus]:
    """构造带全新 fakes 的 CommandContext。"""

    fake_ui = ui or FakeUI()
    fake_session = session or FakeSession()
    fake_skills = skills or FakeSkills()
    fake_status = status or FakeStatus()
    context = CommandContext(
        args=args,
        session=fake_session,
        skills=fake_skills,
        status=fake_status,
        ui=fake_ui,
        sandbox=fake_session,
    )
    return context, fake_ui, fake_session, fake_skills, fake_status
