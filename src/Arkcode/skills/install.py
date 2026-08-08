"""从受信任的 GitHub 来源安全安装目录型 Skill。"""

from __future__ import annotations

import base64
import binascii
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx

from .parser import SkillParseError, parse_skill_file

MAX_FILE_SIZE = 1024 * 1024
MAX_TOTAL_SIZE = 8 * 1024 * 1024
MAX_FILE_COUNT = 64
MAX_RECURSION_DEPTH = 4


class SkillInstallError(RuntimeError):
    """远程 Skill 来源无效或无法安全安装。"""


@dataclass(frozen=True, slots=True)
class SkillSource:
    owner: str
    repo: str
    ref: str
    path: str
    expected_name: str | None = None


def _safe_parts(path: str) -> list[str]:
    decoded = unquote(path)
    if decoded.startswith("//"):
        raise SkillInstallError("URL contains an unsafe or missing path")
    if decoded.startswith("/"):
        decoded = decoded[1:]
    pure = PurePosixPath(decoded)
    parts = list(pure.parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SkillInstallError("URL contains an unsafe or missing path")
    return parts


def parse_skill_url(url: str) -> SkillSource:
    """解析 skills.sh、GitHub tree 或 raw SKILL.md URL。"""

    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise SkillInstallError("Skill URL must use HTTPS")
    if parsed.query or parsed.fragment:
        raise SkillInstallError("Skill URL must not contain query or fragment")
    parts = _safe_parts(parsed.path)

    if parsed.hostname == "skills.sh":
        if len(parts) != 3:
            raise SkillInstallError("skills.sh URL must contain owner/repo/skill")
        owner, repo, name = parts
        return SkillSource(owner, repo, "", name, name)

    if parsed.hostname == "github.com":
        if len(parts) < 5 or parts[2] != "tree":
            raise SkillInstallError("GitHub URL must point to a tree path")
        owner, repo, _, ref, *skill_path = parts
        return SkillSource(owner, repo, ref, "/".join(skill_path))

    if parsed.hostname == "raw.githubusercontent.com":
        if len(parts) < 5 or parts[-1] != "SKILL.md":
            raise SkillInstallError("Raw GitHub URL must point to SKILL.md")
        owner, repo, ref, *skill_path = parts
        expected = skill_path[-2] if len(skill_path) >= 2 else None
        return SkillSource(
            owner,
            repo,
            ref,
            "/".join(skill_path),
            expected,
        )

    raise SkillInstallError("Unsupported Skill URL host")


def _new_client() -> httpx.AsyncClient:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(headers=headers, timeout=30.0, follow_redirects=False)


@dataclass
class _Limits:
    file_count: int = 0
    total_size: int = 0

    def add_file(self, declared_size: int) -> None:
        if declared_size < 0 or declared_size > MAX_FILE_SIZE:
            raise SkillInstallError("Skill file size limit exceeded")
        self.file_count += 1
        if self.file_count > MAX_FILE_COUNT:
            raise SkillInstallError("Skill file count limit exceeded")
        self.total_size += declared_size
        if self.total_size > MAX_TOTAL_SIZE:
            raise SkillInstallError("Skill total size limit exceeded")

    def add_actual_extra(self, extra: int) -> None:
        if extra <= 0:
            return
        self.total_size += extra
        if self.total_size > MAX_TOTAL_SIZE:
            raise SkillInstallError("Skill total size limit exceeded")


class _Downloader:
    def __init__(
        self,
        client: httpx.AsyncClient,
        source: SkillSource,
        staging: Path,
    ) -> None:
        self.client = client
        self.source = source
        self.staging = staging.resolve()
        self.root = PurePosixPath(source.path)
        self.limits = _Limits()

    def _url(self, api_path: str) -> str:
        owner = quote(self.source.owner, safe="")
        repo = quote(self.source.repo, safe="")
        path = quote(api_path, safe="/")
        return f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    async def _get(self, api_path: str) -> Any:
        params = {"ref": self.source.ref} if self.source.ref else None
        try:
            response = await self.client.get(self._url(api_path), params=params)
        except httpx.HTTPError as error:
            raise SkillInstallError(f"GitHub API request failed: {error}") from error
        if response.status_code != 200:
            raise SkillInstallError(
                f"GitHub API returned {response.status_code} for {api_path}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise SkillInstallError("GitHub API returned invalid JSON") from error

    def _node(self, value: Any) -> tuple[str, str, int]:
        if not isinstance(value, dict):
            raise SkillInstallError("GitHub API node must be an object")
        node_type = value.get("type")
        api_path = value.get("path")
        size = value.get("size", 0)
        if node_type not in {"file", "dir"}:
            raise SkillInstallError("Unsupported GitHub API node type")
        if not isinstance(api_path, str) or not isinstance(size, int):
            raise SkillInstallError("GitHub API node has invalid path or size")
        pure = PurePosixPath(api_path)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise SkillInstallError("GitHub API node path is unsafe")
        try:
            pure.relative_to(self.root)
        except ValueError as error:
            raise SkillInstallError(
                "GitHub API node path escapes Skill root"
            ) from error
        return node_type, api_path, size

    def _destination(self, api_path: str, *, root_file: bool = False) -> Path:
        relative = (
            PurePosixPath("SKILL.md")
            if root_file
            else PurePosixPath(api_path).relative_to(self.root)
        )
        destination = self.staging.joinpath(*relative.parts).resolve()
        if not destination.is_relative_to(self.staging):
            raise SkillInstallError("GitHub API node path escapes staging")
        return destination

    async def _write_file(
        self,
        api_path: str,
        declared_size: int,
        *,
        root_file: bool = False,
    ) -> None:
        value = await self._get(api_path)
        node_type, returned_path, returned_size = self._node(value)
        if node_type != "file" or returned_path != api_path:
            raise SkillInstallError("GitHub API returned an unexpected file node")
        encoding = value.get("encoding")
        content = value.get("content")
        if encoding != "base64" or not isinstance(content, str):
            raise SkillInstallError("GitHub API file must contain base64 content")
        try:
            raw = base64.b64decode(content, validate=True)
        except (binascii.Error, ValueError) as error:
            raise SkillInstallError(
                "GitHub API returned invalid base64 content"
            ) from error
        actual_size = len(raw)
        if actual_size > MAX_FILE_SIZE or returned_size > MAX_FILE_SIZE:
            raise SkillInstallError("Skill file size limit exceeded")
        self.limits.add_actual_extra(max(0, actual_size - declared_size))
        destination = self._destination(api_path, root_file=root_file)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)

    async def _download_directory(self, api_path: str, depth: int) -> None:
        if depth > MAX_RECURSION_DEPTH:
            raise SkillInstallError("Skill recursion depth limit exceeded")
        value = await self._get(api_path)
        if not isinstance(value, list):
            raise SkillInstallError("GitHub API directory must be a list")
        nodes = [self._node(item) for item in value]
        for node_type, _, size in nodes:
            if node_type == "file":
                self.limits.add_file(size)
        for node_type, child_path, size in nodes:
            if node_type == "file":
                await self._write_file(child_path, size)
            else:
                await self._download_directory(child_path, depth + 1)

    async def download(self) -> None:
        if self.root.name == "SKILL.md":
            value = await self._get(self.source.path)
            node_type, api_path, size = self._node(value)
            if node_type != "file" or api_path != self.source.path:
                raise SkillInstallError("Raw Skill source is not a file")
            self.limits.add_file(size)
            await self._write_file(api_path, size, root_file=True)
            return
        await self._download_directory(self.source.path, 0)


async def install_skill(source: SkillSource, install_root: Path) -> str:
    """下载、验证后在同一文件系统内原子发布一个 Skill。"""

    _safe_parts(source.owner)
    _safe_parts(source.repo)
    if source.ref:
        _safe_parts(source.ref)
    _safe_parts(source.path)
    root = install_root.resolve()
    root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".skill-install-", dir=root) as temporary:
        staging = Path(temporary)
        async with _new_client() as client:
            await _Downloader(client, source, staging).download()

        skill_file = staging / "SKILL.md"
        if not skill_file.is_file():
            raise SkillInstallError("Downloaded Skill is missing SKILL.md")
        try:
            metadata = parse_skill_file(skill_file, is_directory=True)
        except SkillParseError as error:
            raise SkillInstallError(
                f"Downloaded SKILL.md is invalid: {error}"
            ) from error
        if source.expected_name is not None and metadata.name != source.expected_name:
            raise SkillInstallError(
                f"Downloaded Skill name '{metadata.name}' does not match expected "
                f"name '{source.expected_name}'"
            )
        target = root / metadata.name
        if target.exists():
            raise SkillInstallError(f"Skill target already exists: {target}")
        try:
            staging.rename(target)
        except OSError as error:
            raise SkillInstallError(f"Failed to publish Skill: {error}") from error
        return metadata.name
