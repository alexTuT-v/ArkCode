"""进程级依赖装配：ArkCode 的唯一 composition root。"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
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
from ..tools.workspace import ExecutionPathContext
from ..worktrees import WorktreeManager
from ..worktrees.integration import WorktreeEnvironmentPreparer
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
            worktree_preparer_factory=(
                lambda: WorktreeEnvironmentPreparer(worktree_manager)
                if worktree_manager is not None
                else None
            ),
        )
        registry.register(AgentTool(launcher))
        registry.register(JobListTool(task_manager))
        registry.register(JobGetTool(task_manager))
        registry.register(JobStopTool(task_manager))
        registry.register(JobSendTool(task_manager))
        registry.disable_timeout("Agent")
        team_manager = None
        worktree_manager: WorktreeManager | None = None
        sweep_task: asyncio.Task[None] | None = None
        try:
            worktree_manager = await WorktreeManager.open(root)
            from ..teams.manager import TeamManager
            from ..teams.registry import AgentNameRegistry
            from ..teams.spawner import TeamSpawner
            from ..teams.tools import (
                SendMessageTool,
                TeamCreateTool,
                TeamDeleteTool,
                TeamServices,
            )

            team_manager = TeamManager(
                Path.home(),
                wt_mgr=worktree_manager,
                task_mgr=task_manager,
                name_registry=AgentNameRegistry(),
            )
            services = TeamServices(
                team_manager=team_manager,
                task_manager=task_manager,
            )
            registry.register(TeamCreateTool(services))
            registry.register(TeamDeleteTool(services))
            registry.register(SendMessageTool(services))
            spawner = TeamSpawner(
                team_manager=team_manager,
                worktree_manager=worktree_manager,
                launcher=launcher,
                session_root=root / ".Arkcode" / "sessions",
            )
            agent_tool = registry.get("Agent")
            if agent_tool is not None:
                agent_tool.set_team_spawner(spawner)  # type: ignore[attr-defined]
            async def _sweep_background() -> None:
                await worktree_manager.sweep_stale(
                    datetime.now().astimezone() - timedelta(hours=24)
                )

            sweep_task = asyncio.create_task(_sweep_background())
        except Exception as exc:
            print(f"警告: Worktree 功能未启用: {exc}", file=sys.stderr)
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
            worktree_manager=worktree_manager,
            team_manager=team_manager,
        )
        if (
            worktree_manager is not None
            and worktree_manager.current_session is not None
        ):
            session.set_active_workspace(
                ExecutionPathContext.at(
                    worktree_manager.current_session.worktree_path
                )
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
            worktree_manager=worktree_manager,
            sweep_task=sweep_task,
            team_manager=team_manager,
        )
    except Exception:
        await mcp_manager.close()
        raise
