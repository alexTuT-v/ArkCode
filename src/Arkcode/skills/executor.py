"""Skill inline 与 fork 两种执行路径。"""

import asyncio
from pathlib import Path

from ..agents import Agent, SessionRuntime
from ..config import ProviderConfig, effective_context_window
from ..context import (
    CompactCircuitBreaker,
    RecoveryState,
    new_session_context,
)
from ..context.prompts import build_summary_prompt, extract_summary
from ..conversations import Conversation
from ..llm import Request, StreamError, TextDelta, new_provider
from ..permissions import Engine, Mode
from ..tools.registry import Registry
from .parser import SkillMeta, substitute_arguments

SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})


class SkillExecutor:
    """让显式 Slash Skill 与自动激活共享同一套执行语义。"""

    def __init__(
        self,
        agent: Agent,
        conversation: Conversation,
        provider_config: ProviderConfig,
        registry: Registry,
        engine: Engine | None,
        version: str,
        work_dir: Path,
    ) -> None:
        self._agent = agent
        self._conversation = conversation
        self._provider_config = provider_config
        self._registry = registry
        self._engine = engine
        self._version = version
        self._work_dir = work_dir

    def execute_inline(self, skill: SkillMeta, args: str) -> None:
        rendered = substitute_arguments(skill.prompt_body, args)
        self._agent.activate_skill(skill.name, rendered)

    async def _summarize(self, provider: object) -> str:
        chunks: list[str] = []
        request = Request(
            messages=build_summary_prompt(self._conversation.messages()),
            tools=None,
        )
        async for event in provider.stream(request):  # type: ignore[attr-defined]
            if isinstance(event, StreamError):
                raise event.error
            if isinstance(event, TextDelta):
                chunks.append(event.text)
        return extract_summary("".join(chunks))

    def _new_runtime(self, config: ProviderConfig) -> SessionRuntime:
        return SessionRuntime(
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(str(self._work_dir)),
            context_window=effective_context_window(config),
        )

    async def execute_fork(self, skill: SkillMeta, args: str) -> str:
        try:
            rendered = substitute_arguments(skill.prompt_body, args)
            config = (
                self._provider_config.model_copy(update={"model": skill.model})
                if skill.model
                else self._provider_config
            )
            provider = new_provider(config)

            if skill.context == "recent":
                history = [
                    message
                    for message in self._conversation.messages()
                    if message.role in {"user", "assistant"}
                ][-5:]
                child_conversation = Conversation.from_messages(history)
            else:
                child_conversation = Conversation()
                if skill.context == "full":
                    summary = await self._summarize(provider)
                    child_conversation.add_user(
                        f"## Previous conversation summary\n{summary}"
                    )
            child_conversation.add_user(rendered)

            child_agent = Agent(
                provider,
                self._registry.without(SYSTEM_TOOL_NAMES),
                self._version,
                self._engine,
                runtime=self._new_runtime(config),
            )
            chunks: list[str] = []
            async for event in child_agent.run(
                child_conversation,
                Mode.NORMAL,
                asyncio.Event(),
            ):
                if event.err is not None:
                    raise event.err
                if event.text:
                    chunks.append(event.text)
                if event.done:
                    break
            return "".join(chunks)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return f"[skill {skill.name} failed: {error}]"
