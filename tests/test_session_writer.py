from pathlib import Path

from Arkcode.session import Writer


def test_writer_exposes_absolute_jsonl_path(tmp_path: Path) -> None:
    with Writer(str(tmp_path / "session")) as writer:
        assert Path(writer.path).is_absolute()
        assert Path(writer.path).is_file()
