import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from textual.widgets import RichLog

import Arkcode.skills.executor as executor_module
import Arkcode.tool.install_skill as install_tool_module
import Arkcode.tui.app as app_module
from Arkcode.command import NopUI
from Arkcode.config import ProviderConfig
from Arkcode.llm import Request, StreamEnd, StreamEvent, TextDelta
from Arkcode.tool import new_default_registry
from Arkcode.tui.app import ArkCodeApp, SessionState
from Arkcode.tui.commands import AppUI
from Arkcode.tui.complete import CompletionMenu


class RecordingProvider:
    name = "fake"
    model = "main-model"

    def __init__(self, release: asyncio.Event | None = None) -> None:
        self.requests: list[Request] = []
        self.release = release
        self.cancelled = False

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        try:
            if self.release is not None:
                await self.release.wait()
            yield TextDelta("skill result")
            yield StreamEnd("end")
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def config() -> ProviderConfig:
    return ProviderConfig("fake", "openai", "secret", "main-model")


def write_skill(
    root: Path,
    name: str,
    *,
    mode: str = "inline",
    context: str = "none",
    body: str = "Run $ARGUMENTS",
) -> Path:
    path = root / ".Arkcode" / "skills" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {name} description\n"
        f"mode: {mode}\ncontext: {context}\n---\n{body}",
        encoding="utf-8",
    )
    return path


def log_text(log: RichLog) -> str:
    return "\n".join(line.text for line in log.lines)


def test_app_constructs_loader_and_load_skill_before_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "commit")
    registry = new_default_registry()

    app = ArkCodeApp([config()], "1.0", registry, workspace=tmp_path)

    assert registry.get("LoadSkill") is app.load_skill_tool
    assert registry.get("InstallSkill") is app.install_skill_tool
    assert app.skill_loader.get_catalog() == [("commit", "commit description")]
    assert app.cmd_registry.lookup("skill") is not None
    assert app.workspace == tmp_path.resolve()


@pytest.mark.asyncio
async def test_provider_activation_catalog_help_and_reload_are_atomic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    old = write_skill(tmp_path, "review", body="secret SOP")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    monkeypatch.setattr(executor_module, "new_provider", lambda _: provider)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.agent is not None
        assert "review description" in app.agent._skill_catalog
        assert "secret SOP" not in app.agent._skill_catalog
        assert app.cmd_registry.lookup("review").description.endswith("[skill]")  # type: ignore[union-attr]

        await app.submit("/help")
        assert "/skill" in log_text(app.query_one("#log", RichLog))
        old.unlink()
        write_skill(tmp_path, "commit")
        AppUI(app).reload_skills()

        assert app.cmd_registry.lookup("review").description == "请求审查当前上下文"  # type: ignore[union-attr]
        assert app.cmd_registry.lookup("commit") is not None
        assert "commit description" in app.agent._skill_catalog
        assert "review description" not in app.agent._skill_catalog


@pytest.mark.asyncio
async def test_multi_provider_selection_completes_skill_assembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "commit")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    second = ProviderConfig("second", "openai", "secret", "second-model")
    app = ArkCodeApp(
        [config(), second],
        "1.0",
        new_default_registry(),
        workspace=tmp_path,
    )

    async with app.run_test() as pilot:
        await pilot.press("down", "enter")
        await pilot.pause()

        assert app.agent is not None
        assert app.skill_executor is not None
        assert app.cmd_registry.lookup("commit") is not None
        assert "commit description" in app.agent._skill_catalog


@pytest.mark.asyncio
async def test_inline_skill_activates_and_clear_only_removes_active_sop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "commit")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    monkeypatch.setattr(executor_module, "new_provider", lambda _: provider)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/commit src")
        for _ in range(30):
            await pilot.pause()
            if app.state is SessionState.IDLE and provider.requests:
                break

        assert app.agent is not None
        assert app.agent.active_skills == {"commit": "Run src"}
        assert provider.requests[0].messages[0].content == "/commit src"
        assert "Run src" in provider.requests[0].system.environment
        await app.submit("/clear")
        assert app.agent.active_skills == {}
        assert "commit description" in app.agent._skill_catalog


@pytest.mark.asyncio
async def test_clear_failure_preserves_conversation_writer_and_active_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "commit")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.agent is not None
        app.agent.activate_skill("commit", "SOP")
        app.conv.add_user("keep")
        old_conversation = app.conv
        old_writer = app.writer
        monkeypatch.setattr(
            "Arkcode.tui.commands.new_session_context",
            lambda _: (_ for _ in ()).throw(RuntimeError("disk failed")),
        )

        await app.submit("/clear")

        assert app.conv is old_conversation
        assert app.writer is old_writer
        assert app.conv.messages()[0].content == "keep"
        assert app.agent.active_skills == {"commit": "SOP"}


@pytest.mark.asyncio
async def test_fork_result_returns_as_system_reminder_without_main_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "research", mode="fork")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    monkeypatch.setattr(executor_module, "new_provider", lambda _: provider)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.agent is not None
        app.agent.activate_skill("keep", "main SOP")
        before = app.conv.messages()
        await app.submit("/research topic")
        for _ in range(30):
            await pilot.pause()
            if not app._fork_tasks:
                break

        assert len(provider.requests) == 1
        assert provider.requests[0].messages[-1].content == "Run topic"
        assert app.conv.messages()[:-1] == before
        assert app.agent.active_skills == {"keep": "main SOP"}
        assert "<system-reminder>" in app.conv.messages()[-1].content
        assert "skill result" in app.conv.messages()[-1].content
        assert "skill result" in log_text(app.query_one("#log", RichLog))


@pytest.mark.asyncio
async def test_unmount_cancels_pending_fork_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "research", mode="fork")
    release = asyncio.Event()
    provider = RecordingProvider(release)
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    monkeypatch.setattr(executor_module, "new_provider", lambda _: provider)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/research topic")
        for _ in range(30):
            await pilot.pause()
            if provider.requests:
                break
        assert app._fork_tasks

    assert provider.cancelled is True
    assert app._fork_tasks == set()


@pytest.mark.asyncio
async def test_skill_local_commands_do_not_change_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path, "commit")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.usage_in = 123
        app.usage_out = 45
        await app.submit("/skill list")
        await app.submit("/skill info commit")

        assert (app.usage_in, app.usage_out) == (123, 45)
        assert provider.requests == []
        output = log_text(app.query_one("#log", RichLog))
        assert "source: project" in output
        assert "path:" in output
        assert "commit.md" in output
        assert "directory: false" in output


def test_nop_ui_skill_extensions_are_safe_defaults() -> None:
    ui = NopUI()
    assert ui.skill_list() == []
    assert ui.skill_info("missing") is None
    ui.reload_skills()
    ui.append_system_message("x", "result")
    ui.clear_active_skills()


@pytest.mark.asyncio
async def test_install_tool_callback_hot_registers_command_and_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_root = tmp_path / "home" / ".Arkcode" / "skills"
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    provider = RecordingProvider()
    monkeypatch.setattr(app_module, "new_provider", lambda _: provider)

    async def fake_install(source: object, root: Path) -> str:
        assert root == user_root
        path = root / "remote" / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\nname: remote\ndescription: Remote skill\n---\nRemote SOP",
            encoding="utf-8",
        )
        return "remote"

    monkeypatch.setattr(install_tool_module, "install_skill", fake_install)
    app = ArkCodeApp([config()], "1.0", new_default_registry(), workspace=tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        result = await app.install_skill_tool.execute(
            '{"url":"https://skills.sh/acme/repo/remote"}'
        )

        assert result.is_error is False
        assert app.cmd_registry.lookup("remote") is not None
        assert app.agent is not None
        assert "remote: Remote skill" in app.agent._skill_catalog
        assert "Remote SOP" not in app.agent._skill_catalog
        await app.submit("/help")
        assert "/remote" in log_text(app.query_one("#log", RichLog))
        completion = CompletionMenu()
        completion.update("/rem", app.cmd_registry)
        assert [item.name for item in completion.items] == ["remote"]
