"""进程级依赖装配：ArkCode 的唯一 composition root。"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta
from pathlib import Path

from .. import mcp as mcp_client
from ..config import load
from ..instructions import Loader
from ..memory import Manager as MemoryManager
from ..permissions import new_engine
from ..sessions import clean_expired
from ..skills import SkillLoader
from ..subagents.approvals import ApprovalBroker
from ..subagents.catalog import Catalog
from ..subagents.launcher import SubAgentLauncher
from ..subagents.manager import TaskManager
from ..subagents.tools import (
    AgentTool,
    JobGetTool,
    JobListTool,
    JobSendTool,
    JobStopTool,
)
from ..tools import new_default_registry
from .runtime import ApplicationRuntime
from .session import SessionService


async def build_runtime(workspace: Path, version: str) -> ApplicationRuntime:
    """构造进程级依赖并建立 ApplicationRuntime。"""

    root = Path(workspace).resolve()
    config = load(".env")
    instruction_text = Loader(root).load()
    sessions_dir = str(root / ".Arkcode" / "sessions")
    memory_manager = MemoryManager(
        str(root / ".Arkcode" / "memory"),
        str(Path.home() / ".Arkcode" / "memory"),
        None,
        "",
        sessions_dir,
    )
    memory_text = memory_manager.load_index()
    registry = new_default_registry()
    mcp_config = mcp_client.load_config(str(root))
    mcp_manager = await mcp_client.new_manager(mcp_config, version=version)
    try:
        for remote_tool in mcp_manager.tools():
            registry.register(remote_tool)
        engine, error = new_engine(str(root))
        if error is not None:
            print(f"权限引擎降级: {error}", file=sys.stderr)
        catalog = Catalog(root, Path.home())
        catalog.load()
        task_manager = TaskManager()
        approval_broker = ApprovalBroker()
        launcher = SubAgentLauncher(
            catalog=catalog,
            task_manager=task_manager,
            broker=approval_broker,
            engine=engine,
            version=version,
            workspace=root,
            providers=list(config.providers),
            parent_config=config.providers[0] if config.providers else None,
            enable_background=config.enable_subagent_background,
        )
        registry.register(AgentTool(launcher))
        registry.register(JobListTool(task_manager))
        registry.register(JobGetTool(task_manager))
        registry.register(JobStopTool(task_manager))
        registry.register(JobSendTool(task_manager))
        registry.disable_timeout("Agent")
        skills = SkillLoader(root)
        skills.load_all()
        session = SessionService(
            workspace=root,
            version=version,
            registry=registry,
            permissions=engine,
            skills=skills,
            memory=memory_manager,
            instruction_text=instruction_text,
            memory_text=memory_text,
            sessions_dir=sessions_dir,
            mcp_instructions=mcp_manager.instructions_text(),
            config=config,
            provider_configs=list(config.providers),
            task_manager=task_manager,
            catalog=catalog,
            approval_broker=approval_broker,
            launcher=launcher,
        )
        cleanup_task = asyncio.create_task(
            asyncio.to_thread(clean_expired, sessions_dir, timedelta(days=30))
        )
        return ApplicationRuntime(
            workspace=root,
            version=version,
            config=config,
            tools=registry,
            permissions=engine,
            mcp=mcp_manager,
            mcp_status=mcp_manager.status(),
            memory=memory_manager,
            skills=skills,
            session=session,
            cleanup_task=cleanup_task,
            catalog=catalog,
            task_manager=task_manager,
            approval_broker=approval_broker,
            launcher=launcher,
        )
    except Exception:
        await mcp_manager.close()
        raise
