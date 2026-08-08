from datetime import datetime, timedelta

from Arkcode.compact.recovery import (
    build_recovery_attachment,
    render_file_block,
)
from Arkcode.compact.state import FileReadRecord
from Arkcode.llm import ToolDefinition


def test_file_block_keeps_head_and_marks_truncation() -> None:
    record = FileReadRecord("/tmp/a.py", "HEAD" + "x" * 20000, datetime.now())

    rendered = render_file_block(record)

    assert "HEAD" in rendered
    assert rendered.rstrip().endswith("(content truncated)")
    assert len("x" * 18000) > 17500


def test_recovery_attachment_limits_files_and_matches_tools_exactly() -> None:
    now = datetime.now()
    records = [
        FileReadRecord(f"/tmp/{index}.py", str(index), now - timedelta(seconds=index))
        for index in range(7)
    ]
    tools = [
        ToolDefinition(
            name="read_file",
            description="read",
            input_schema={"type": "object", "required": ["path"]},
        ),
        ToolDefinition(
            name="bash",
            description="run",
            input_schema={"type": "object"},
        ),
    ]

    rendered = build_recovery_attachment(records, tools)

    for index in range(5):
        assert f"/tmp/{index}.py" in rendered
    assert "/tmp/5.py" not in rendered
    assert "/tmp/6.py" not in rendered
    assert rendered.index("/tmp/0.py") < rendered.index("/tmp/1.py")
    assert rendered.count("- read_file:") == 1
    assert rendered.count("- bash:") == 1
    assert '"required":["path"]' in rendered
    assert "## 边界提示" in rendered
    assert rendered == build_recovery_attachment(records, tools)
