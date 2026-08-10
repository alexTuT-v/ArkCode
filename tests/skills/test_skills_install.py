import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

import Arkcode.skills.install as install_module
from Arkcode.skills.install import (
    MAX_FILE_COUNT,
    MAX_FILE_SIZE,
    MAX_RECURSION_DEPTH,
    MAX_TOTAL_SIZE,
    SkillInstallError,
    SkillSource,
    install_skill,
    parse_skill_url,
)


def encoded(content: str) -> str:
    return base64.b64encode(content.encode()).decode()


def file_node(path: str, content: str, *, size: int | None = None) -> dict[str, Any]:
    return {
        "type": "file",
        "name": Path(path).name,
        "path": path,
        "size": len(content.encode()) if size is None else size,
        "encoding": "base64",
        "content": encoded(content),
    }


def install_client(
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
) -> None:
    monkeypatch.setattr(
        install_module,
        "_new_client",
        lambda: httpx.AsyncClient(transport=handler),
    )


def test_parse_supported_skill_urls() -> None:
    skills = parse_skill_url("https://skills.sh/acme/skills/review")
    assert skills == SkillSource("acme", "skills", "", "review", "review")

    tree = parse_skill_url("https://github.com/acme/skills/tree/main/review")
    assert tree == SkillSource("acme", "skills", "main", "review")

    raw = parse_skill_url(
        "https://raw.githubusercontent.com/acme/skills/v1/review/SKILL.md"
    )
    assert raw == SkillSource("acme", "skills", "v1", "review/SKILL.md", "review")


@pytest.mark.asyncio
async def test_github_token_header_is_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    public_client = install_module._new_client()
    assert "Authorization" not in public_client.headers
    await public_client.aclose()

    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    authenticated_client = install_module._new_client()
    assert authenticated_client.headers["Authorization"] == "Bearer secret-token"
    await authenticated_client.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "http://skills.sh/acme/repo/review",
        "https://example.com/acme/repo/review",
        "https://skills.sh/acme/repo",
        "https://github.com/acme/repo/blob/main/review",
        "https://github.com/acme/repo/tree/main",
        "https://raw.githubusercontent.com/acme/repo/main/review.md",
        "https://raw.githubusercontent.com/acme/repo/main/../SKILL.md",
    ],
)
def test_parse_rejects_unsupported_or_incomplete_urls(url: str) -> None:
    with pytest.raises(SkillInstallError):
        parse_skill_url(url)


@pytest.mark.asyncio
async def test_install_directory_recursively_and_renames_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_text = "---\nname: review\ndescription: Review code\n---\nReview SOP"

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/contents/review"):
            return httpx.Response(
                200,
                json=[
                    {"type": "file", "path": "review/SKILL.md", "size": 61},
                    {"type": "dir", "path": "review/references", "size": 0},
                ],
            )
        if path.endswith("/contents/review/references"):
            return httpx.Response(
                200,
                json=[
                    {"type": "file", "path": "review/references/rule.txt", "size": 4}
                ],
            )
        if path.endswith("/contents/review/SKILL.md"):
            return httpx.Response(200, json=file_node("review/SKILL.md", skill_text))
        if path.endswith("/contents/review/references/rule.txt"):
            return httpx.Response(
                200,
                json=file_node("review/references/rule.txt", "rule"),
            )
        return httpx.Response(404)

    install_client(monkeypatch, httpx.MockTransport(respond))
    install_root = tmp_path / "skills"

    name = await install_skill(
        SkillSource("acme", "skills", "main", "review"),
        install_root,
    )

    assert name == "review"
    assert (install_root / "review" / "SKILL.md").read_text() == skill_text
    assert (install_root / "review" / "references" / "rule.txt").read_text() == "rule"
    assert list(install_root.glob(".skill-install-*")) == []


@pytest.mark.asyncio
async def test_install_raw_skill_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill_text = "---\nname: review\ndescription: Review code\n---\nSOP"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(
            200,
            json=file_node("review/SKILL.md", skill_text),
        )

    install_client(monkeypatch, httpx.MockTransport(respond))

    name = await install_skill(
        SkillSource("acme", "skills", "v1", "review/SKILL.md", "review"),
        tmp_path / "skills",
    )

    assert name == "review"
    assert (tmp_path / "skills" / "review" / "SKILL.md").is_file()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 500])
async def test_install_reports_github_api_errors_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    install_client(
        monkeypatch,
        httpx.MockTransport(lambda _: httpx.Response(status, text="failed")),
    )
    root = tmp_path / "skills"

    with pytest.raises(SkillInstallError, match=str(status)):
        await install_skill(SkillSource("a", "b", "main", "review"), root)

    assert list(root.glob(".skill-install-*")) == []


@pytest.mark.asyncio
async def test_install_rejects_invalid_base64(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = file_node("review/SKILL.md", "x")
    node["content"] = "%%%"
    install_client(
        monkeypatch,
        httpx.MockTransport(lambda _: httpx.Response(200, json=node)),
    )

    with pytest.raises(SkillInstallError, match="base64"):
        await install_skill(
            SkillSource("a", "b", "main", "review/SKILL.md"),
            tmp_path / "skills",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("listing", "message"),
    [
        ([{"type": "file", "path": "../escape", "size": 1}], "path"),
        ([{"type": "symlink", "path": "review/link", "size": 1}], "type"),
        (
            [{"type": "file", "path": "review/huge", "size": MAX_FILE_SIZE + 1}],
            "file size",
        ),
        (
            [
                {"type": "file", "path": f"review/{index}", "size": 0}
                for index in range(MAX_FILE_COUNT + 1)
            ],
            "file count",
        ),
        (
            [
                {
                    "type": "file",
                    "path": f"review/{index}",
                    "size": MAX_FILE_SIZE,
                }
                for index in range(MAX_TOTAL_SIZE // MAX_FILE_SIZE + 1)
            ],
            "total size",
        ),
    ],
)
async def test_install_enforces_node_path_type_and_size_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    listing: list[dict[str, Any]],
    message: str,
) -> None:
    install_client(
        monkeypatch,
        httpx.MockTransport(lambda _: httpx.Response(200, json=listing)),
    )

    with pytest.raises(SkillInstallError, match=message):
        await install_skill(
            SkillSource("a", "b", "main", "review"),
            tmp_path / "skills",
        )


@pytest.mark.asyncio
async def test_install_enforces_recursion_depth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        relative = request.url.path.split("/contents/", 1)[1]
        return httpx.Response(
            200,
            json=[{"type": "dir", "path": f"{relative}/next", "size": 0}],
        )

    install_client(monkeypatch, httpx.MockTransport(respond))

    with pytest.raises(SkillInstallError, match="recursion depth"):
        await install_skill(
            SkillSource("a", "b", "main", "review"),
            tmp_path / "skills",
        )
    assert MAX_RECURSION_DEPTH == 4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("skill_text", "message"),
    [
        (None, "SKILL.md"),
        ("not frontmatter", "frontmatter"),
        ("---\nname: other\ndescription: Other\n---\nSOP", "expected"),
    ],
)
async def test_install_validates_skill_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    skill_text: str | None,
    message: str,
) -> None:
    if skill_text is None:
        response: Any = [{"type": "file", "path": "review/readme.md", "size": 1}]
    else:
        response = file_node("review/SKILL.md", skill_text)

    def respond(request: httpx.Request) -> httpx.Response:
        if isinstance(response, list):
            if request.url.path.endswith("readme.md"):
                return httpx.Response(200, json=file_node("review/readme.md", "x"))
            return httpx.Response(200, json=response)
        return httpx.Response(200, json=response)

    install_client(monkeypatch, httpx.MockTransport(respond))

    with pytest.raises(SkillInstallError, match=message):
        await install_skill(
            SkillSource("a", "b", "main", "review/SKILL.md", "review")
            if skill_text is not None
            else SkillSource("a", "b", "main", "review", "review"),
            tmp_path / "skills",
        )


@pytest.mark.asyncio
async def test_install_never_overwrites_existing_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "skills" / "review"
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("keep")
    skill_text = "---\nname: review\ndescription: Review\n---\nSOP"
    install_client(
        monkeypatch,
        httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json=file_node("review/SKILL.md", skill_text),
            )
        ),
    )

    with pytest.raises(SkillInstallError, match="exists"):
        await install_skill(
            SkillSource("a", "b", "main", "review/SKILL.md"),
            tmp_path / "skills",
        )

    assert marker.read_text() == "keep"
