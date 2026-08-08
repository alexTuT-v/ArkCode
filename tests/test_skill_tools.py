from pathlib import Path

import pytest

from Arkcode.skills import SkillLoader
from Arkcode.tool import InstallSkillTool, Registry, Result
from Arkcode.tool.load_skill import LoadSkillTool


def write_skill(root: Path, body: str = "secret SOP") -> Path:
    path = root / ".Arkcode" / "skills" / "review.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\nname: review\ndescription: Review code\n---\n" + body,
        encoding="utf-8",
    )
    return path


class RecordingAgent:
    def __init__(self) -> None:
        self.activated: list[tuple[str, str]] = []

    def activate_skill(self, name: str, body: str) -> None:
        self.activated.append((name, body))


class NamedTool:
    read_only = True

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name

    def name(self) -> str:
        return self.tool_name

    def description(self) -> str:
        return self.tool_name

    def parameters(self) -> dict[str, object]:
        return {"type": "object"}

    async def execute(self, args: str) -> Result:
        raise AssertionError("not called")


def test_load_skill_metadata_and_schema() -> None:
    tool = LoadSkillTool()

    assert tool.name() == "LoadSkill"
    assert tool.read_only is True
    assert "activate" in tool.description().lower()
    assert tool.parameters() == {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    }


@pytest.mark.asyncio
async def test_load_skill_reports_uninitialized_dependencies() -> None:
    result = await LoadSkillTool().execute('{"name":"review"}')

    assert result.is_error is True
    assert "not properly initialized" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    ["not json", "{}", '{"name": 7}', '{"name": ""}'],
)
async def test_load_skill_rejects_invalid_arguments(args: str) -> None:
    result = await LoadSkillTool().execute(args)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_load_skill_unknown_lists_available_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    write_skill(tmp_path)
    loader = SkillLoader(tmp_path)
    loader.load_all()
    agent = RecordingAgent()
    tool = LoadSkillTool(loader, agent)  # type: ignore[arg-type]

    result = await tool.execute('{"name":"missing"}')

    assert result.is_error is True
    assert "review" in result.content
    assert agent.activated == []


@pytest.mark.asyncio
async def test_load_skill_hot_reloads_and_does_not_return_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    path = write_skill(tmp_path, "old SOP")
    loader = SkillLoader(tmp_path)
    loader.load_all()
    path.write_text(
        "---\nname: review\ndescription: Review code\n---\nnew secret SOP",
        encoding="utf-8",
    )
    agent = RecordingAgent()
    tool = LoadSkillTool(loader, agent)  # type: ignore[arg-type]

    result = await tool.execute('{"name":"review"}')

    assert result.is_error is False
    assert agent.activated == [("review", "new secret SOP")]
    assert "new secret SOP" not in result.content
    assert result.content == (
        "Skill 'review' activated. SOP pinned to environment context."
    )


def test_registry_without_preserves_order_and_source_registry() -> None:
    registry = Registry()
    registry.register(NamedTool("first"))  # type: ignore[arg-type]
    registry.register(NamedTool("LoadSkill"))  # type: ignore[arg-type]
    registry.register(NamedTool("last"))  # type: ignore[arg-type]

    filtered = registry.without({"LoadSkill"})

    assert [item.name for item in filtered.definitions()] == ["first", "last"]
    assert [item.name for item in registry.definitions()] == [
        "first",
        "LoadSkill",
        "last",
    ]


class ReloadingLoader:
    def __init__(self, order: list[str] | None = None) -> None:
        self.reload_count = 0
        self.order = order

    def reload(self) -> list[object]:
        self.reload_count += 1
        if self.order is not None:
            self.order.append("reload")
        return []


def test_install_skill_metadata_and_write_schema() -> None:
    tool = InstallSkillTool()

    assert tool.name() == "InstallSkill"
    assert tool.read_only is False
    assert "install" in tool.description().lower()
    assert tool.parameters() == {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
        "additionalProperties": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "args",
    ["not json", "{}", '{"url": 7}', '{"url": ""}', '{"url":"http://x"}'],
)
async def test_install_skill_rejects_invalid_arguments(args: str) -> None:
    result = await InstallSkillTool().execute(args)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_install_skill_reports_uninitialized_loader() -> None:
    result = await InstallSkillTool().execute(
        '{"url":"https://skills.sh/acme/repo/review"}'
    )

    assert result.is_error is True
    assert "not properly initialized" in result.content


@pytest.mark.asyncio
async def test_install_success_reloads_and_notifies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Arkcode.tool.install_skill as install_tool_module

    calls: list[tuple[object, Path]] = []

    async def fake_install(source: object, root: Path) -> str:
        calls.append((source, root))
        return "review"

    monkeypatch.setattr(install_tool_module, "install_skill", fake_install)
    order: list[str] = []
    loader = ReloadingLoader(order)
    notified: list[bool] = []

    def notify() -> None:
        order.append("callback")
        notified.append(True)

    tool = InstallSkillTool(
        loader,  # type: ignore[arg-type]
        tmp_path,
        notify,
    )

    result = await tool.execute('{"url":"https://skills.sh/acme/repo/review"}')

    assert result == Result("Skill 'review' installed and registered.")
    assert calls and calls[0][1] == tmp_path
    assert loader.reload_count == 1
    assert notified == [True]
    assert order == ["reload", "callback"]


@pytest.mark.asyncio
async def test_install_failure_does_not_reload_or_notify(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Arkcode.tool.install_skill as install_tool_module

    async def fake_install(source: object, root: Path) -> str:
        raise RuntimeError("download failed")

    monkeypatch.setattr(install_tool_module, "install_skill", fake_install)
    loader = ReloadingLoader()
    notified: list[bool] = []
    tool = InstallSkillTool(
        loader,  # type: ignore[arg-type]
        tmp_path,
        lambda: notified.append(True),
    )

    result = await tool.execute('{"url":"https://skills.sh/acme/repo/review"}')

    assert result.is_error is True
    assert "download failed" in result.content
    assert loader.reload_count == 0
    assert notified == []


@pytest.mark.asyncio
async def test_install_refresh_failure_is_not_reported_as_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Arkcode.tool.install_skill as install_tool_module

    async def fake_install(source: object, root: Path) -> str:
        return "review"

    monkeypatch.setattr(install_tool_module, "install_skill", fake_install)
    loader = ReloadingLoader()

    def broken_callback() -> None:
        raise RuntimeError("refresh failed")

    tool = InstallSkillTool(
        loader,  # type: ignore[arg-type]
        tmp_path,
        broken_callback,
    )

    result = await tool.execute('{"url":"https://skills.sh/acme/repo/review"}')

    assert result.is_error is True
    assert "refresh failed" in result.content
