import json
from pathlib import Path

import pytest

import Arkcode.context.spill as spill_module
from Arkcode.context.constants import MESSAGE_AGGREGATE_LIMIT, SINGLE_RESULT_LIMIT
from Arkcode.context.spill import (
    build_preview,
    prepare_tool_results,
    spill_single,
)
from Arkcode.context.state import new_session_context
from Arkcode.llm import Message, ToolCall, ToolResult


def tool_message(*items: tuple[str, str]) -> Message:
    return Message(
        role="tool",
        tool_results=[ToolResult(tool_id, content) for tool_id, content in items],
    )


def test_large_result_preview_is_stable_across_repeats(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    original = "中" * 20000
    calls = [ToolCall("call-1", "read_file", "{}")]

    first = prepare_tool_results(
        [ToolResult("call-1", original)],
        calls,
        session,
    )
    second = prepare_tool_results(
        [ToolResult("call-1", original)],
        calls,
        session,
    )
    preview = first[0].content

    assert second[0].content == preview
    assert "original size: 60000 bytes" in preview
    assert "[saved to]" in preview
    assert "[head preview]" in preview
    assert "文件读取工具" in preview
    assert "不要凭头部预览猜测" in preview
    assert (Path(session.spill_dir) / "call-1").read_text() == original


def test_spill_failure_keeps_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = new_session_context(str(tmp_path))
    from unittest.mock import Mock

    monkeypatch.setattr(spill_module, "spill_single", Mock(side_effect=OSError("full")))
    original = "x" * 60000

    prepared = prepare_tool_results(
        [ToolResult("call-1", original)],
        [ToolCall("call-1", "read_file", "{}")],
        session,
    )

    assert prepared[0].content == original


def test_preview_head_respects_line_and_utf8_byte_limits(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    content = ("中" * 1000 + "\n") * 30

    prepared = prepare_tool_results(
        [ToolResult("call-1", content)],
        [ToolCall("call-1", "read_file", "{}")],
        session,
    )
    preview = prepared[0].content
    head = preview.split("[head preview]\n", 1)[1].split("\n完整内容已保存", 1)[0]

    assert len(head.encode()) <= 2048
    assert len(head.splitlines()) <= 20


def test_spill_single_does_not_rewrite_existing_file(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    spill_single(session, "same-id", "first")
    path = Path(session.spill_dir) / "same-id"
    first_mtime = path.stat().st_mtime_ns
    spill_single(session, "same-id", "second")

    assert path.read_text() == "first"
    assert path.stat().st_mtime_ns == first_mtime


def test_build_preview_is_deterministic() -> None:
    first = build_preview(10, "head", "/tmp/result")
    second = build_preview(10, "head", "/tmp/result")

    assert first == second


def test_large_result_is_final_before_conversation_append(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    calls = [ToolCall("c1", "read_file", '{"path":"large.txt"}')]

    prepared = prepare_tool_results(
        [ToolResult("c1", "x" * (SINGLE_RESULT_LIMIT + 1))],
        calls,
        session,
    )

    assert prepared[0].content.startswith("[content offloaded]")
    assert (Path(session.spill_dir) / "c1").exists()


def test_spill_failure_keeps_original_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import Mock

    monkeypatch.setattr(
        spill_module,
        "spill_single",
        Mock(side_effect=OSError("full")),
    )
    original = "x" * (SINGLE_RESULT_LIMIT + 1)

    prepared = prepare_tool_results(
        [ToolResult("c1", original)],
        [ToolCall("c1", "read_file", "{}")],
        new_session_context(str(tmp_path)),
    )

    assert prepared[0].content == original


def test_aggregate_budget_spills_largest_until_under_limit(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    calls = [
        ToolCall("one", "read_file", "{}"),
        ToolCall("two", "read_file", "{}"),
        ToolCall("three", "read_file", "{}"),
    ]

    prepared = prepare_tool_results(
        [
            ToolResult("one", "a" * 80000),
            ToolResult("two", "b" * 80000),
            ToolResult("three", "c" * 80000),
        ],
        calls,
        session,
    )

    contents = [result.content for result in prepared]
    assert sum(len(content.encode()) for content in contents) <= MESSAGE_AGGREGATE_LIMIT
    assert sum("[content offloaded]" in content for content in contents) >= 2


def test_spill_readback_is_exempt_from_again_spill(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    spill_path = Path(session.spill_dir) / "c1"
    spill_path.write_text("saved content", encoding="utf-8")
    calls = [
        ToolCall(
            "c1",
            "read_file",
            json.dumps({"path": str(spill_path)}),
        )
    ]

    prepared = prepare_tool_results(
        [ToolResult("c1", "saved content")],
        calls,
        session,
    )

    assert prepared[0].content == "saved content"
    assert "[content offloaded]" not in prepared[0].content
