"""Anthropic 系统块缓存边界与 reminder 历史合法性测试。"""

from Arkcode.llm import System
from Arkcode.llm.anthropic_provider import (
    _append_reminder_anthropic,
    _to_anthropic_system,
)


def test_stable_system_has_cache_control_but_environment_does_not() -> None:
    blocks = _to_anthropic_system(
        System(stable="stable instructions", environment="Environment:\nDate: today")
    )

    assert blocks == [
        {
            "type": "text",
            "text": "stable instructions",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "Environment:\nDate: today"},
    ]
    assert "cache_control" not in blocks[1]


def test_reminder_merges_into_tool_result_user_turn() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call-1",
                    "content": "ok",
                }
            ],
        }
    ]

    _append_reminder_anthropic(messages, "<system-reminder>plan</system-reminder>")

    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"][-1] == {
        "type": "text",
        "text": "<system-reminder>plan</system-reminder>",
    }
