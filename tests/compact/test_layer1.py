from pathlib import Path

import pytest

from Arkcode.compact.layer1 import build_preview, offload_and_snip, spill_single
from Arkcode.compact.state import ContentReplacementState, new_session_context
from Arkcode.llm import Message, ToolResult


def tool_message(*items: tuple[str, str]) -> Message:
    return Message(
        role="tool",
        tool_results=[ToolResult(tool_id, content) for tool_id, content in items],
    )


def test_large_result_is_offloaded_with_stable_preview(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    state = ContentReplacementState()
    original = "中" * 20000
    messages = [tool_message(("call-1", original))]

    first = offload_and_snip(messages, state, session)
    second = offload_and_snip(messages, state, session)
    preview = first[0].tool_results[0].content

    assert messages[0].tool_results[0].content == original
    assert second[0].tool_results[0].content is preview
    assert "original size: 60000 bytes" in preview
    assert "[saved to]" in preview
    assert "[head preview]" in preview
    assert "文件读取工具" in preview
    assert "不要凭头部预览猜测" in preview
    assert (Path(session.spill_dir) / "call-1").read_text() == original


def test_aggregate_limit_offloads_largest_until_under_budget(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    messages = [
        tool_message(
            ("one", "a" * 80000),
            ("two", "b" * 80000),
            ("three", "c" * 80000),
        )
    ]

    result = offload_and_snip(messages, ContentReplacementState(), session)
    contents = [item.content for item in result[0].tool_results]

    assert sum(len(content.encode()) for content in contents) <= 200000
    assert sum("[content offloaded]" in content for content in contents) >= 2


def test_spill_failure_keeps_original_and_retries_next_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = new_session_context(str(tmp_path))
    state = ContentReplacementState()
    messages = [tool_message(("call-1", "x" * 60000))]
    attempts = 0

    def fail_once(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("disk full")
        return spill_single(*args, **kwargs)

    monkeypatch.setattr("Arkcode.compact.layer1.spill_single", fail_once)

    first = offload_and_snip(messages, state, session)
    second = offload_and_snip(messages, state, session)

    assert first[0].tool_results[0].content == "x" * 60000
    assert "[content offloaded]" in second[0].tool_results[0].content
    assert attempts == 2


def test_preview_head_respects_line_and_utf8_byte_limits(tmp_path: Path) -> None:
    session = new_session_context(str(tmp_path))
    content = ("中" * 1000 + "\n") * 30

    result = offload_and_snip(
        [tool_message(("call-1", content))],
        ContentReplacementState(),
        session,
    )
    preview = result[0].tool_results[0].content
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


def test_frozen_kept_result_still_counts_toward_new_aggregate_budget(
    tmp_path: Path,
) -> None:
    session = new_session_context(str(tmp_path))
    state = ContentReplacementState()
    kept = "k" * 40000
    offload_and_snip([tool_message(("kept", kept))], state, session)

    result = offload_and_snip(
        [
            tool_message(
                ("kept", kept),
                ("one", "a" * 45000),
                ("two", "b" * 45000),
                ("three", "c" * 45000),
                ("four", "d" * 45000),
            )
        ],
        state,
        session,
    )

    contents = [item.content for item in result[0].tool_results]
    assert contents[0] == kept
    assert any("[content offloaded]" in content for content in contents[1:])
