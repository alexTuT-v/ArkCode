import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console
from textual.widgets import OptionList, RichLog, Static, TextArea

import Arkcode.tui.app as app_module
from Arkcode.agent import NOTICE_CANCELLED, NOTICE_STREAM_ERR, ApprovalRequest
from Arkcode.config import ProviderConfig
from Arkcode.llm import (
    Message,
    Request,
    StreamEnd,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolCallComplete,
    ToolDefinition,
)
from Arkcode.permission import Mode, Outcome, new_engine
from Arkcode.prompt import EXECUTE_DIRECTIVE, plan_reminder
from Arkcode.tool import Registry, Result, new_default_registry
from Arkcode.tui.app import ArkCodeApp, MessageInput, SessionState
from Arkcode.tui.stream import ToolDisplay
from Arkcode.tui.view import (
    status_bar,
    streaming_block,
    tool_line,
    tool_result_summary,
)


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
        self.received: list[tuple[list[Message], list[ToolDefinition], str]] = []

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.received.append((req.messages, req.tools, req.reminder))
        if self.release is not None:
            await self.release.wait()
        for event in self.events:
            yield event


class ScriptedProvider(ControlledProvider):
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        super().__init__([])
        self.scripts = scripts
        self.call_count = 0

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.received.append((req.messages, req.tools, req.reminder))
        script = self.scripts[self.call_count]
        self.call_count += 1
        for event in script:
            yield event


class SlowReadTool:
    read_only = True

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def name(self) -> str:
        return "slow_read"

    def description(self) -> str:
        return "等待测试释放后返回。"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        self.started.set()
        await self.release.wait()
        return Result("slow result")


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


def complete(call: ToolCall) -> ToolCallComplete:
    return ToolCallComplete(call.id, call.name, json.loads(call.input))


def end(input_tokens: int = 0, output_tokens: int = 0) -> StreamEnd:
    return StreamEnd("tool_use", input_tokens, output_tokens)


def make_app(providers: list[ProviderConfig]) -> ArkCodeApp:
    return ArkCodeApp(providers, "0.1.0", new_default_registry())


def make_permission_app(providers: list[ProviderConfig], root: Path) -> ArkCodeApp:
    engine, error = new_engine(str(root))
    assert error is None
    return ArkCodeApp(providers, "0.1.0", new_default_registry(), engine)


async def wait_until_idle(
    pilot: Any,
    app: ArkCodeApp,
    attempts: int = 100,
) -> None:
    for _ in range(attempts):
        await pilot.pause()
        if app.state is SessionState.IDLE:
            return
    pytest.fail("应用未在预期时间内回到 IDLE")


@pytest.mark.asyncio
async def test_single_provider_enters_chat_with_complete_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.provider is provider
        assert app.query_one("#log", RichLog).display is True
        assert "Ark Code v0.1.0" in log_text(app.query_one("#log", RichLog))
        assert "Ready" in log_text(app.query_one("#log", RichLog))
        assert static_text(app.query_one("#prompt", Static)).strip() == "❯"
        assert app.query_one("#input", TextArea).placeholder == "Send a message..."
        prompt_region = app.query_one("#prompt", Static).region
        status_region = app.query_one("#statusbar", Static).region
        assert prompt_region.intersection(status_region).area == 0
        assert app.query_one("#input-row").region.height == 4
        assert app.query_one("#statusbar", Static)
        rendered_status = rich_text(status_bar(provider))
        assert "DEFAULT" in rendered_status
        assert "Claude" not in rendered_status
        assert "claude-test" in rendered_status


@pytest.mark.asyncio
async def test_80x24_layout_keeps_conversation_visible_and_input_aligned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        log = app.query_one("#log", RichLog)
        prompt = app.query_one("#prompt", Static)
        input_box = app.query_one("#input", TextArea)
        input_row = app.query_one("#input-row")
        status = app.query_one("#statusbar", Static)

        assert len(log.lines) <= log.content_region.height
        assert "Ark Code v0.1.0" in log_text(log)
        assert prompt.content_region.y == input_box.content_region.y
        assert input_row.region.intersection(status.region).area == 0


@pytest.mark.asyncio
async def test_multiple_providers_require_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = ControlledProvider([], name="GPT", model="gpt-test")
    monkeypatch.setattr(app_module, "new_provider", lambda config: selected)
    app = make_app(
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
        assert "DEFAULT" in rendered_status
        assert "GPT" not in rendered_status
        assert "gpt-test" in rendered_status


@pytest.mark.asyncio
async def test_shift_tab_cycles_permission_modes_and_statusbar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([TextDelta("模式保持"), end()])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        expected = [
            Mode.ACCEPT_EDITS,
            Mode.PLAN,
            Mode.BYPASS,
            Mode.DEFAULT,
        ]
        labels = ["ACCEPT EDITS", "PLAN", "BYPASS", "DEFAULT"]
        for mode, label in zip(expected, labels, strict=True):
            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.mode is mode
            assert app.state is SessionState.IDLE
            status = rich_text(status_bar(provider, app.mode))
            assert label in status
            assert "Claude" not in status

        output = log_text(app.query_one("#log", RichLog))
        assert output.count("已切换到") == 4

        await pilot.press("shift+tab")
        assert app.mode is Mode.ACCEPT_EDITS
        await app.submit("开始下一轮")
        await wait_until_idle(pilot, app)
        assert app.mode is Mode.ACCEPT_EDITS


@pytest.mark.asyncio
async def test_approval_menu_returns_allow_forever_and_persists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "approved.txt"
    requested = ToolCall(
        "write-approval",
        "write_file",
        json.dumps({"path": str(target), "content": "approved"}),
    )
    provider = ScriptedProvider(
        [[complete(requested), end()], [TextDelta("写入完成"), end()]]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_permission_app([provider_config()], tmp_path)

    async with app.run_test() as pilot:
        await app.submit("写入文件")
        for _ in range(30):
            await pilot.pause()
            if app.state is SessionState.APPROVING:
                break

        assert app.state is SessionState.APPROVING
        assert app.pending is not None
        assert app.approve_cursor == 0
        menu = static_text(app.query_one("#streaming", Static))
        assert "允许本次" in menu
        assert "永久允许" in menu
        assert "拒绝本次" in menu

        response = app.pending.respond
        await pilot.press("down", "enter")
        await wait_until_idle(pilot, app)

        assert response.result() is Outcome.ALLOW_FOREVER
        assert target.read_text(encoding="utf-8") == "approved"
        assert (tmp_path / ".Arkcode/settings.local.yaml").is_file()
        assert app.mode is Mode.DEFAULT


@pytest.mark.asyncio
async def test_escape_denies_pending_approval_without_exiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "denied.txt"
    requested = ToolCall(
        "write-denied",
        "write_file",
        json.dumps({"path": str(target), "content": "no"}),
    )
    provider = ScriptedProvider(
        [[complete(requested), end()], [TextDelta("已处理拒绝"), end()]]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_permission_app([provider_config()], tmp_path)

    async with app.run_test() as pilot:
        await app.submit("不要写")
        for _ in range(30):
            await pilot.pause()
            if app.state is SessionState.APPROVING:
                break
        assert app.pending is not None
        response = app.pending.respond

        await pilot.press("escape")
        await wait_until_idle(pilot, app)

        assert response.result() is Outcome.DENY_ONCE
        assert not target.exists()
        assert app.state is SessionState.IDLE
        assert app.conv.messages()[-1].content == NOTICE_CANCELLED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "outcome"),
    [("1", Outcome.ALLOW_ONCE), ("3", Outcome.DENY_ONCE)],
)
async def test_approval_numeric_shortcuts(
    key: str,
    outcome: Outcome,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        response: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
        app.query_one("#input", TextArea).disabled = True
        app.pending = ApprovalRequest("bash", "git status", "需要确认", response)
        app.state = SessionState.APPROVING
        app._refresh_streaming_view()

        await pilot.press(key)
        await pilot.pause()

        assert response.result() is outcome
        assert app.state is SessionState.STREAMING
        app.state = SessionState.IDLE


@pytest.mark.asyncio
async def test_submit_streams_then_stores_markdown_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [
            TextDelta("**你好**"),
            end(),
        ],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("第一轮")
        await pilot.pause()

        assert app.state is SessionState.STREAMING
        assert app.query_one("#input", TextArea).disabled is True
        assert app.query_one("#input", TextArea).text == ""
        app.turn_start = time.monotonic() - 2.2
        app._tick()
        streaming = static_text(app.query_one("#streaming", Static))
        assert "Imagining… (2s" in streaming
        assert "第 1 轮" in streaming

        release.set()
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.query_one("#input", TextArea).disabled is False
        assert provider.received[0][0] == [Message(role="user", content="第一轮")]
        assert len(provider.received[0][1]) == 6
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
    provider = ControlledProvider([TextDelta("实时文本"), end()])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("请流式回复")
        for _ in range(20):
            await pilot.pause()
            if app.cur_reply:
                break

        assert (
            app.cur_reply == "实时文本" or app.conv.messages()[-1].content == "实时文本"
        )
        assert (
            app.cur_reply == "实时文本" or app.conv.messages()[-1].content == "实时文本"
        )


@pytest.mark.asyncio
async def test_text_delta_waits_for_a_render_frame_before_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([TextDelta("一帧文本"), end()])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

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
    provider = ControlledProvider([StreamError(RuntimeError("bad key"))])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("会失败")
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.conv.messages() == [
            Message(role="user", content="会失败"),
            Message(role="assistant", content=NOTICE_STREAM_ERR),
        ]
        assert "bad key" in log_text(app.query_one("#log", RichLog))
        assert app.query_one("#input", TextArea).disabled is False


@pytest.mark.asyncio
async def test_alt_enter_inserts_newline_and_enter_submits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [TextDelta("ok"), end()],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        input_box = app.query_one("#input", MessageInput)
        input_box.focus()
        await pilot.press("h", "i", "alt+enter", "x", "enter")
        await pilot.pause()

        assert app.state is SessionState.STREAMING
        assert app.conv.messages()[0] == Message(role="user", content="hi\nx")

        release.set()
        await pilot.pause()


def test_tool_rendering_has_claude_code_style_and_bounded_summary() -> None:
    line = rich_text(tool_line("read_file", '{"path":"a.txt"}'))
    summary = rich_text(
        tool_result_summary("\n".join(f"line {index}" for index in range(20)), False)
    )
    error = rich_text(tool_result_summary("not found", True))

    assert "● read_file(" in line
    assert "⎿" in summary
    assert "[truncated]" in summary
    assert "not found" in error


@pytest.mark.asyncio
async def test_plan_then_do_switches_mode_and_executes_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "planned.txt"
    provider = ScriptedProvider(
        [
            [TextDelta("计划内容"), end()],
            [
                complete(
                    ToolCall(
                        "planned-write",
                        "write_file",
                        json.dumps(
                            {"path": str(target), "content": "按计划执行"},
                            ensure_ascii=False,
                        ),
                    )
                ),
                end(),
            ],
            [TextDelta("计划执行完成"), end()],
        ]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("/plan")
        await pilot.pause()

        assert app.mode is Mode.PLAN
        assert app.state is SessionState.IDLE
        assert "计划模式" in log_text(app.query_one("#log", RichLog))
        assert "PLAN" in rich_text(
            status_bar(provider, app.mode, app.usage_in, app.usage_out)
        )

        await app.submit("检查后制定方案")
        await wait_until_idle(pilot, app)

        assert [tool.name for tool in provider.received[0][1]] == [
            "read_file",
            "glob",
            "grep",
        ]
        assert provider.received[0][2] == plan_reminder(full=True)

        await app.submit("/do")
        await wait_until_idle(pilot, app)

        assert app.mode is Mode.NORMAL
        assert len(provider.received[1][1]) == 6
        assert provider.received[1][2] == ""
        assert provider.received[1][0][-1] == Message(
            role="user",
            content=EXECUTE_DIRECTIVE,
        )
        assert target.read_text(encoding="utf-8") == "按计划执行"
        assert app.conv.messages()[-1].content == "计划执行完成"


@pytest.mark.asyncio
async def test_escape_cancels_turn_without_exiting_and_next_turn_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [TextDelta("继续成功"), end()],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("取消这一轮")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

        assert app.state is SessionState.IDLE
        assert app.conv.messages()[-1] == Message(
            role="assistant",
            content=NOTICE_CANCELLED,
        )
        assert app.turn_cancel is None

        release.set()
        await app.submit("继续")
        for _ in range(20):
            await pilot.pause()
            if app.state is SessionState.IDLE:
                break

        assert app.state is SessionState.IDLE
        assert app.conv.messages()[-1].content == "继续成功"


@pytest.mark.asyncio
async def test_usage_and_iteration_are_rendered_and_accumulated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [
            TextDelta("完成"),
            StreamEnd("end_turn", 1200, 34, 800, 120),
        ],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("统计用量")
        await pilot.pause()

        assert "第 1 轮" in static_text(app.query_one("#streaming", Static))

        release.set()
        for _ in range(20):
            await pilot.pause()
            if app.state is SessionState.IDLE:
                break

        assert app.usage_in == 1200
        assert app.usage_out == 34
        assert app.usage_cache_read == 800
        assert app.usage_cache_creation == 120
        status = rich_text(
            status_bar(
                provider,
                app.mode,
                app.usage_in,
                app.usage_out,
                app.usage_cache_read,
                app.usage_cache_creation,
            )
        )
        assert "↑1.2k" in status
        assert "↓34" in status
        assert "cache 读 800 / 写 120" in status


def test_streaming_block_lists_multiple_running_tools_in_order() -> None:
    rendered = rich_text(
        streaming_block(
            "",
            2,
            [
                ToolDisplay("read_file", '{"path":"a"}'),
                ToolDisplay("grep", '{"pattern":"x"}'),
            ],
            3,
        )
    )

    assert rendered.index("read_file") < rendered.index("grep")
    assert rendered.count("Running") == 2


@pytest.mark.asyncio
async def test_full_tui_loop_reads_then_writes_across_iterations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.md"
    target = tmp_path / "summary.txt"
    source.write_text("Agent Loop 会持续调用工具。", encoding="utf-8")
    provider = ScriptedProvider(
        [
            [
                TextDelta("先读取源文件。"),
                complete(
                    ToolCall("read-1", "read_file", json.dumps({"path": str(source)}))
                ),
                end(10, 1),
            ],
            [
                TextDelta("根据内容写摘要。"),
                complete(
                    ToolCall(
                        "write-1",
                        "write_file",
                        json.dumps(
                            {
                                "path": str(target),
                                "content": "Agent Loop 可自动多轮调用工具。",
                            },
                            ensure_ascii=False,
                        ),
                    )
                ),
                end(20, 2),
            ],
            [
                TextDelta("读写任务完成。"),
                end(30, 3),
            ],
        ]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("读取 source.md 后写入 summary.txt")
        await wait_until_idle(pilot, app)

        assert provider.call_count == 3
        assert target.read_text(encoding="utf-8") == "Agent Loop 可自动多轮调用工具。"
        assert (app.usage_in, app.usage_out) == (60, 6)
        output = log_text(app.query_one("#log", RichLog))
        positions = [
            output.index("先读取源文件"),
            output.index("read_file"),
            output.index("根据内容写摘要"),
            output.index("write_file"),
            output.index("读写任务完成"),
        ]
        assert positions == sorted(positions)


@pytest.mark.asyncio
async def test_tui_remains_responsive_while_slow_tool_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slow_tool = SlowReadTool()
    registry = Registry()
    registry.register(slow_tool)
    provider = ScriptedProvider(
        [
            [
                complete(ToolCall("slow-1", "slow_read", "{}")),
                end(),
            ],
            [TextDelta("慢工具完成。"), end()],
        ]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = ArkCodeApp([provider_config()], "0.1.0", registry)

    async with app.run_test() as pilot:
        await app.submit("运行慢工具")
        await asyncio.wait_for(slow_tool.started.wait(), timeout=0.5)

        app.turn_start = time.monotonic() - 2.2
        app._tick()
        rendered = static_text(app.query_one("#streaming", Static))
        assert app.state is SessionState.STREAMING
        assert "slow_read" in rendered
        assert "Running" in rendered
        assert "(2s)" in rendered

        slow_tool.release.set()
        await wait_until_idle(pilot, app)


@pytest.mark.asyncio
async def test_concurrent_tool_batch_scrollback_preserves_model_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    target = tmp_path / "combined.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    calls = [
        ToolCall(
            "read-1",
            "read_file",
            json.dumps({"path": str(first)}),
        ),
        ToolCall(
            "read-2",
            "read_file",
            json.dumps({"path": str(second)}),
        ),
        ToolCall(
            "write-1",
            "write_file",
            json.dumps({"path": str(target), "content": "first+second"}),
        ),
    ]
    provider = ScriptedProvider(
        [
            [
                TextDelta("开始并发读取后写入。"),
                *(complete(call) for call in calls),
                end(),
            ],
            [TextDelta("批处理完成。"), end()],
        ]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("并发读取两个文件后写入")
        await wait_until_idle(pilot, app)

        output = log_text(app.query_one("#log", RichLog))
        preamble = output.index("开始并发读取后写入")
        read_one = output.index("read_file", preamble)
        read_two = output.index("read_file", read_one + 1)
        write = output.index("write_file", read_two)
        final = output.index("批处理完成", write)
        assert preamble < read_one < read_two < write < final
        assert target.read_text() == "first+second"


@pytest.mark.asyncio
async def test_ctrl_c_cancels_streaming_turn_without_exiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()
    provider = ControlledProvider(
        [TextDelta("不应到达"), end()],
        release=release,
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("等待并取消")
        await pilot.pause()
        await pilot.press("ctrl+c")
        await wait_until_idle(pilot, app)

        assert app.is_running
        assert app.conv.messages()[-1].content == NOTICE_CANCELLED


@pytest.mark.asyncio
async def test_ctrl_c_exits_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ControlledProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert not app.is_running


@pytest.mark.asyncio
async def test_stream_error_recovers_and_next_turn_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ScriptedProvider(
        [
            [StreamError(ConnectionError("temporary outage"))],
            [TextDelta("恢复成功"), end()],
        ]
    )
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("触发临时错误")
        await wait_until_idle(pilot, app)
        assert "temporary outage" in log_text(app.query_one("#log", RichLog))

        await app.submit("重试")
        await wait_until_idle(pilot, app)

        assert app.conv.messages()[-1].content == "恢复成功"
        output = log_text(app.query_one("#log", RichLog))
        assert output.index("temporary outage") < output.index("恢复成功")


@pytest.mark.asyncio
async def test_thinking_is_transient_and_not_written_as_final_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    class ThinkingProvider(ControlledProvider):
        async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
            self.received.append((req.messages, req.tools, req.reminder))
            yield ThinkingDelta("先分析文件")
            await release.wait()
            yield TextDelta("最终答复")
            yield StreamEnd("end_turn")

    provider = ThinkingProvider([])
    monkeypatch.setattr(app_module, "new_provider", lambda config: provider)
    app = make_app([provider_config()])

    async with app.run_test() as pilot:
        await app.submit("请分析")
        for _ in range(10):
            await pilot.pause()
            if app.cur_thinking:
                break

        assert "先分析文件" in static_text(app.query_one("#streaming", Static))
        release.set()
        await wait_until_idle(pilot, app)

        output = log_text(app.query_one("#log", RichLog))
        assert "最终答复" in output
        assert "先分析文件" not in output
