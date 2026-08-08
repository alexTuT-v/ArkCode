"""命令处理器可使用的最小 UI 能力。"""

import asyncio
from typing import Protocol

from ..permission import Mode


class UI(Protocol):
    def println(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def mode(self) -> Mode: ...
    def set_mode(self, mode: Mode) -> None: ...
    def inject_and_send(self, label: str, prompt: str) -> None: ...
    def usage_in(self) -> int: ...
    def usage_out(self) -> int: ...
    def model_name(self) -> str: ...
    def cwd(self) -> str: ...
    def tool_count(self) -> int: ...
    def memory_files(self) -> list[str]: ...
    def session_path(self) -> str: ...
    def session_id(self) -> str: ...
    def quit(self) -> None: ...
    def force_compact(self) -> None: ...
    def open_resume_menu(self) -> None: ...
    def clear_and_new_session(self) -> None: ...
    def idle(self) -> bool: ...
    def skill_list(self) -> list[tuple[str, str, str]]: ...
    def skill_info(self, name: str) -> str | None: ...
    def reload_skills(self) -> None: ...
    def append_system_message(self, name: str, result: str) -> None: ...
    def clear_active_skills(self) -> None: ...
    def track_skill_task(self, task: asyncio.Task[None]) -> None: ...


class NopUI:
    def println(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass

    def mode(self) -> Mode:
        return Mode.DEFAULT

    def set_mode(self, mode: Mode) -> None:
        pass

    def inject_and_send(self, label: str, prompt: str) -> None:
        pass

    def usage_in(self) -> int:
        return 0

    def usage_out(self) -> int:
        return 0

    def model_name(self) -> str:
        return ""

    def cwd(self) -> str:
        return ""

    def tool_count(self) -> int:
        return 0

    def memory_files(self) -> list[str]:
        return []

    def session_path(self) -> str:
        return ""

    def session_id(self) -> str:
        return ""

    def quit(self) -> None:
        pass

    def force_compact(self) -> None:
        pass

    def open_resume_menu(self) -> None:
        pass

    def clear_and_new_session(self) -> None:
        pass

    def idle(self) -> bool:
        return True

    def skill_list(self) -> list[tuple[str, str, str]]:
        return []

    def skill_info(self, name: str) -> str | None:
        return None

    def reload_skills(self) -> None:
        pass

    def append_system_message(self, name: str, result: str) -> None:
        pass

    def clear_active_skills(self) -> None:
        pass

    def track_skill_task(self, task: asyncio.Task[None]) -> None:
        pass
