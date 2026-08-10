"""权限引擎沙箱自动放行测试。"""

from pathlib import Path

import pytest

from Arkcode.llm import ToolCall
from Arkcode.permissions import Decision, Mode, new_engine


def _write_call() -> ToolCall:
    return ToolCall("call-1", "write_file", '{"path": "out.txt"}')


def test_sandbox_enabled_auto_allows_ask(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    decision, _ = engine.check(Mode.DEFAULT, _write_call(), False)
    assert decision is Decision.ASK

    engine.sandbox_enabled = True
    decision, _ = engine.check(Mode.DEFAULT, _write_call(), False)

    assert decision is Decision.ALLOW


def test_sandbox_enabled_does_not_override_path_deny(tmp_path: Path) -> None:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    engine.sandbox_enabled = True
    call = ToolCall("call-1", "write_file", '{"path": "/etc/passwd"}')

    decision, _ = engine.check(Mode.DEFAULT, call, False)

    assert decision is Decision.DENY
