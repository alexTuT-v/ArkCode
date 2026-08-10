"""记忆模型输出的 JSON action 解析与统一执行。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..llm import Message, Provider, Request, StreamError, System, TextDelta
from .store import Store
from .types import MemoryScope, NoteType, UpdateAction

logger = logging.getLogger(__name__)
_ACTIONS = {"create", "update", "delete"}
_FIELDS = {"action", "level", "type", "title", "slug", "content", "filename"}


def _strip_json_fence(text: str) -> str:
    lines = text.splitlines()
    if (
        len(lines) >= 2
        and lines[0].strip().lower() == "```json"
        and lines[-1].strip() == "```"
    ):
        return "\n".join(lines[1:-1]).strip()
    return text


def _parse_action(value: Any) -> UpdateAction:
    if not isinstance(value, dict):
        raise ValueError("记忆 action 必须是 JSON 对象")
    unknown = set(value) - _FIELDS
    if unknown:
        raise ValueError(f"记忆 action 包含未知字段: {sorted(unknown)}")
    parsed: dict[str, str] = {}
    for field in _FIELDS:
        raw = value.get(field, "")
        if not isinstance(raw, str):
            raise ValueError(f"记忆 action 字段必须是字符串: {field}")
        parsed[field] = raw
    return UpdateAction(**parsed)


def validate_actions(actions: list[UpdateAction]) -> None:
    for action in actions:
        if action.action not in _ACTIONS:
            raise ValueError(f"未知记忆操作: {action.action}")
        try:
            MemoryScope(action.level)
        except ValueError as error:
            raise ValueError(f"非法记忆层级: {action.level}") from error
        try:
            NoteType(action.type)
        except ValueError as error:
            raise ValueError(f"非法记忆类型: {action.type}") from error

        if action.action == "create":
            Store.validate_slug(action.slug)
            if not action.title.strip() or not action.content.strip():
                raise ValueError("create 必须包含非空 title 和 content")
            continue

        Store.validate_filename(action.filename)
        if not action.filename.startswith(f"{action.type}_"):
            raise ValueError("记忆 filename 与 type 不一致")
        if action.action == "update" and not action.content.strip():
            raise ValueError("update 必须包含非空 content")


def parse_actions(raw: str) -> list[UpdateAction]:
    text = _strip_json_fence(raw.strip())
    start = text.find("[")
    if start < 0:
        raise ValueError("记忆更新响应必须包含 JSON 数组")
    value, consumed = json.JSONDecoder().raw_decode(text[start:])
    if "[" in text[start + consumed :]:
        raise ValueError("记忆更新响应包含多个 JSON 数组")
    if not isinstance(value, list):
        raise ValueError("记忆更新响应必须是 JSON 数组")
    actions = [_parse_action(item) for item in value]
    validate_actions(actions)
    return actions


async def collect_text(provider: Provider, request: Request) -> str:
    chunks: list[str] = []
    async for event in provider.stream(request):
        if isinstance(event, TextDelta):
            chunks.append(event.text)
        elif isinstance(event, StreamError):
            raise event.error
    return "".join(chunks)


class MemoryActionService:
    """串行调用记忆模型并通过两个 Store 执行合法 action。"""

    def __init__(
        self,
        project_store: Store,
        user_store: Store,
        provider: Provider | None,
        model: str,
    ) -> None:
        self._project = project_store
        self._user = user_store
        self._provider = provider
        self._model = model
        self._lock = asyncio.Lock()

    def set_provider(self, provider: Provider, model: str) -> None:
        self._provider = provider
        self._model = model

    async def execute(
        self,
        system_prompt: str,
        payload: dict[str, object],
    ) -> bool:
        try:
            async with self._lock:
                if self._provider is None:
                    return False
                request = Request(
                    messages=[
                        Message(
                            role="user",
                            content=json.dumps(
                                {"model": self._model, **payload},
                                ensure_ascii=False,
                            ),
                        )
                    ],
                    tools=None,
                    system=System(stable=system_prompt),
                )
                actions = parse_actions(await collect_text(self._provider, request))
                if not actions:
                    return True
                try:
                    project_actions = [
                        action for action in actions if action.level == "project"
                    ]
                    user_actions = [
                        action for action in actions if action.level == "user"
                    ]
                    if project_actions:
                        self._project.apply(project_actions)
                    if user_actions:
                        self._user.apply(user_actions)
                finally:
                    try:
                        self._project.rebuild_index()
                    finally:
                        self._user.rebuild_index()
                return True
        except Exception:
            logger.exception("长期记忆 action 执行失败")
            return False
