"""影响界面状态的命令。"""

from ..permission import Mode
from .ui import UI


async def handle_exit(ui: UI, args: str) -> None:
    ui.quit()


async def handle_plan(ui: UI, args: str) -> None:
    ui.set_mode(Mode.PLAN)
    ui.println("已进入计划模式（只读工具）")


async def handle_compact(ui: UI, args: str) -> None:
    if not ui.idle():
        ui.error("请等待当前任务完成")
        return
    ui.force_compact()


async def handle_resume(ui: UI, args: str) -> None:
    if not ui.idle():
        ui.error("请等待当前任务完成")
        return
    ui.open_resume_menu()


async def handle_clear(ui: UI, args: str) -> None:
    ui.clear_and_new_session()
    ui.println("已清空当前会话，开启新 session")
