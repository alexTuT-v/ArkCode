import asyncio
import time
from collections.abc import AsyncIterator

import pytest
from rich.console import Console
from textual.widgets import OptionList, RichLog, Static, TextArea

import Arkcode.tui.app as app_module
from Arkcode.config import ProviderConfig
from Arkcode.llm import Message, StreamEvent
from Arkcode.tui.app import ArkCodeApp, MessageInput, SessionState
from Arkcode.tui.view import status_bar


def provider_config(name: str = "Claude", model: str = "claude-test") -> ProviderConfig:
    return ProviderConfig(
        name=name,
        protocol="anthropic",
        api_key="secret",
        model=model,
    )


class ControlledProvider:
    def __init__(
        self,
        events: list[StreamEvent],
        *,
        release: asyncio.Event | None = None,
        name: str = "Claude",
        model: str = "claude-test",
    ) -> None:
        self.name = name
        self.model = model
        self.events = events
        self.release = release
        self.received: list[list[Message]] = []

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        self.received.append(msgs)
        if self.release is not None:
            await self.release.wait()
        for event in self.events:
            yield event


def log_text(log: RichLog) -> str:
    return "\n".join(line.text for line in log.lines)


def static_text(widget: Static) -> str:
    console = Console(width=100, record=True)
    console.print(widget.render())
    return console.export_text()


def rich_text(renderable: object) -> str:
    console = Console(width=100, record=True)
    console.print(renderable)
    return console.export_text()


@pytest.mark.asyncio
async def test_single_provider_enters_chat_with_complete_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.provider is provider
        assert app.query_one("#log", RichLog).display is True
        assert "ArkCode v0.1.0" in log_text(app.query_one("#log", RichLog))
        assert "Ready" in log_text(app.query_one("#log", RichLog))
        assert static_text(app.query_one("#prompt", Static)).strip() == "❯"
        assert app.query_one("#input", TextArea).placeholder == "Send a message..."
        prompt_region = app.query_one("#prompt", Static).region
        status_region = app.query_one("#statusbar", Static).region
        assert prompt_region.intersection(status_region).area == 0
        assert app.query_one("#input-row").region.height == 4
        assert app.query_one("#statusbar", Static)
        rendered_status = rich_text(status_bar(provider))
        assert "Claude" in rendered_status
        assert "claude-test" in rendered_status


@pytest.mark.asyncio
async def test_80x24_layout_keeps_conversation_visible_and_input_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        log = app.query_one("#log", RichLog)
        prompt = app.query_one("#prompt", Static)
        input_box = app.query_one("#input", TextArea)
        input_row = app.query_one("#input-row")
        status = app.query_one("#statusbar", Static)

        assert len(log.lines) <= log.content_region.height
        assert "ArkCode v0.1.0" in log_text(log)
        assert prompt.content_region.y == input_box.content_region.y
        assert input_row.region.intersection(status.region).area == 0


@pytest.mark.asyncio
async def test_multiple_providers_require_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = ControlledProvider([], name="GPT", model="gpt-test")
    monkeypatch.setattr(app_module, "new_provider", lambda config: selected)
    app = ArkCodeApp(
        [
            provider_config(),
            provider_config(name="GPT", model="gpt-test"),
        ]
    )

    async with app.run_test() as pilot:
        options = app.query_one("#provider-select", OptionList)
        assert app.state is SessionState.SELECTING
        assert options.display is True
        assert app.query_one("#input", TextArea).display is False

        await pilot.press("down", "enter")
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.provider is selected
        assert options.display is False
        assert app.query_one("#input", TextArea).display is True
        assert app.query_one("#statusbar", Static)
        rendered_status = rich_text(status_bar(selected))
        assert "GPT" in rendered_status
        assert "gpt-test" in rendered_status


@pytest.mark.asyncio
async def test_submit_streams_then_stores_markdown_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [
            StreamEvent(text="**你好**"),
            StreamEvent(done=True),
        ],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("第一轮")
        await pilot.pause()

        assert app.state is SessionState.STREAMING
        assert app.query_one("#input", TextArea).disabled is True
        assert app.query_one("#input", TextArea).text == ""
        app.turn_start = time.monotonic() - 2.2
        app._tick()
        assert "Imagining… (2s)" in static_text(app.query_one("#streaming", Static))

        release.set()
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.query_one("#input", TextArea).disabled is False
        assert provider.received == [[Message(role="user", content="第一轮")]]
        assert app.conv.messages() == [
            Message(role="user", content="第一轮"),
            Message(role="assistant", content="**你好**"),
        ]
        completed = log_text(app.query_one("#log", RichLog))
        assert "第一轮" in completed
        assert "你好" in completed
        assert "2." in completed
        assert static_text(app.query_one("#streaming", Static)) == "\n"


@pytest.mark.asyncio
async def test_buffered_text_delta_yields_control_for_live_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider(
        [StreamEvent(text="实时文本"), StreamEvent(done=True)]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test():
        await app.submit("请流式回复")
        await asyncio.sleep(0)

        assert app.state is SessionState.STREAMING
        assert app.cur_reply == "实时文本"
        assert "实时文本" in static_text(app.query_one("#streaming", Static))


@pytest.mark.asyncio
async def test_text_delta_waits_for_a_render_frame_before_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider(
        [StreamEvent(text="一帧文本"), StreamEvent(done=True)]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test() as pilot:
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()
        streaming_view = app.query_one("#streaming", Static)

        async def wait_for_refresh() -> bool:
            refresh_started.set()
            await release_refresh.wait()
            return True

        monkeypatch.setattr(streaming_view, "wait_for_refresh", wait_for_refresh)
        await app.submit("请流式回复")
        await asyncio.wait_for(refresh_started.wait(), timeout=0.2)

        assert app.state is SessionState.STREAMING
        assert app.cur_reply == "一帧文本"

        release_refresh.set()
        await pilot.pause()
        assert app.state is SessionState.IDLE


@pytest.mark.asyncio
async def test_error_returns_to_idle_without_adding_assistant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([StreamEvent(err=RuntimeError("bad key"))])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("会失败")
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.conv.messages() == [Message(role="user", content="会失败")]
        assert "bad key" in log_text(app.query_one("#log", RichLog))
        assert app.query_one("#input", TextArea).disabled is False


@pytest.mark.asyncio
async def test_alt_enter_inserts_newline_and_enter_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [StreamEvent(text="ok"), StreamEvent(done=True)],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()])

    async with app.run_test() as pilot:
        input_box = app.query_one("#input", MessageInput)
        input_box.focus()
        await pilot.press("h", "i", "alt+enter", "x", "enter")
        await pilot.pause()

        assert app.state is SessionState.STREAMING
        assert app.conv.messages()[0] == Message(role="user", content="hi\nx")

        release.set()
        await pilot.pause()
