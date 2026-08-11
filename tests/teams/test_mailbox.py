"""Mailbox、广播、注册表与协议测试。"""

import asyncio
import os
import time
from pathlib import Path

import pytest

from Arkcode.teams.mailbox import Box
from Arkcode.teams.models import Message, MessageType
from Arkcode.teams.protocol import new_message
from Arkcode.teams.registry import AgentNameRegistry


def make_box(tmp_path: Path) -> Box:
    return Box(tmp_path / "team")


@pytest.mark.asyncio
async def test_direct_write_read_unread(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    message = new_message("lead", "hello alice")
    await box.write("agent-a1", message)
    messages = await box.read("agent-a1")
    assert len(messages) == 1
    assert messages[0].text == "hello alice"
    assert messages[0].read is False
    assert (tmp_path / "team" / "mailbox" / "agent-a1.json").is_file()


@pytest.mark.asyncio
async def test_mark_read(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    await box.write("agent-a1", new_message("lead", "one"))
    await box.write("agent-a1", new_message("lead", "two"))
    await box.mark_read("agent-a1", [0])
    messages = await box.read("agent-a1")
    assert messages[0].read is True
    assert messages[1].read is False


@pytest.mark.asyncio
async def test_broadcast_targets(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    team_members = ["agent-a1", "agent-a2", "agent-a3"]
    await box.broadcast("lead", team_members, new_message("lead", "hi all"))
    for agent_id in team_members:
        assert len(await box.read(agent_id)) == 1


@pytest.mark.asyncio
async def test_concurrent_writes_no_loss(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    await asyncio.gather(
        *(
            box.write("agent-a1", new_message("lead", f"msg-{index}"))
            for index in range(10)
        )
    )
    messages = await box.read("agent-a1")
    assert len(messages) == 10
    assert {message.text for message in messages} == {
        f"msg-{index}" for index in range(10)
    }


@pytest.mark.asyncio
async def test_stale_lock_is_cleaned(tmp_path: Path) -> None:
    box = make_box(tmp_path)
    lock_path = tmp_path / "team" / "mailbox" / "agent-a1.json.lock"
    lock_path.touch()
    old = time.time() - 20
    os.utime(lock_path, (old, old))
    await box.write("agent-a1", new_message("lead", "after stale"))
    assert len(await box.read("agent-a1")) == 1


def test_message_protocol_camel_case_request_id() -> None:
    message = new_message(
        "alice",
        "计划",
        message_type=MessageType.PLAN_APPROVAL_REQUEST,
        request_id="req-123",
    )
    value = message.to_dict()
    assert value["requestId"] == "req-123"
    assert value["type"] == "plan_approval_request"
    restored = Message.from_dict(value)
    assert restored.type is MessageType.PLAN_APPROVAL_REQUEST
    assert restored.request_id == "req-123"


def test_name_registry_register_resolve_unregister() -> None:
    registry = AgentNameRegistry()
    registry.register("alice", "agent-a1")
    assert registry.resolve("alice") == "agent-a1"
    assert registry.resolve("agent-a1") == "agent-a1"
    assert registry.name_of("agent-a1") == "alice"
    registry.register("alice", "agent-a2")
    assert registry.resolve("alice") == "agent-a2"
    registry.unregister("alice")
    assert registry.resolve("alice") is None
