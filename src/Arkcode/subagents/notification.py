"""`<task-notification>` 完成通知格式化。"""

from __future__ import annotations

from .models import BackgroundTask


def format_task_notification(job: BackgroundTask) -> str:
    name_part = f' (name="{job.name}")' if job.name else ""
    result = job.result or (str(job.error) if job.error is not None else "")
    return (
        "<task-notification>\n"
        f"Job {job.id}{name_part}: {job.status.value}\n"
        f"Result: {result}\n"
        "</task-notification>"
    )
