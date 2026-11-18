from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.exceptions import (
    BranchRuntimeActiveError,
    ConflictError,
    ServerModeVersioningDisabledError,
)
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    ArchiveBranchCommand,
    CreateBranchCommand,
    DeleteBranchCommand,
)
from app.modules.versioning.application.commands.archive_branch import ArchiveBranchHandler
from app.modules.versioning.application.commands.delete_branch import DeleteBranchHandler
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.registration import register_handlers

pytestmark = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only Git branch/worktree operations; Windows = Simple-only",
)

SERVER_ID = "srv-lock"


def _lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


@pytest.fixture
def layout_and_root(tmp_path: Path):
    from app.core.config import AppSettings

    settings = AppSettings(
        host_state_dir=str(tmp_path / "host-state"),
        servers_data_dir=str(tmp_path / "servers"),
    )
    from app.core.host_state import ensure_host_state_layout

    layout = ensure_host_state_layout(settings)
    root = tmp_path / "servers" / "srv-1"
    root.mkdir(parents=True)
    (root / "server.properties").write_text("motd=Hello\n")
    return layout, root


def _init_repo(layout, root):
    from app.modules.versioning.infrastructure.git_repository import GitRepositoryService

    GitRepositoryService(layout).initialize("srv-1", root, _lockfile())


@pytest.mark.asyncio
async def test_lock_worktree_creates_real_lock(layout_and_root) -> None:
    layout, root = layout_and_root
    _init_repo(layout, root)
    svc = GitBranchService(layout)
    svc.create_branch("srv-1", root, "feature/x")
    path = svc.lock_worktree("srv-1", root, "feature/x", reason="runtime:rt1")
    assert path == root / ".onx" / "worktrees" / "feature" / "x"
    branches = svc.list_branches("srv-1", root)
    info = next(b for b in branches if b.name == "feature/x")
    assert info.worktree_locked is True
    assert info.worktree_lock_reason == "runtime:rt1"


@pytest.mark.asyncio
async def test_double_lock_raises(layout_and_root) -> None:
    layout, root = layout_and_root
    _init_repo(layout, root)
    svc = GitBranchService(layout)
    svc.create_branch("srv-1", root, "feature/x")
    svc.lock_worktree("srv-1", root, "feature/x", reason="runtime:rt1")
    with pytest.raises(BranchRuntimeActiveError):
        svc.lock_worktree("srv-1", root, "feature/x", reason="runtime:rt2")


@pytest.mark.asyncio
async def test_unlock_worktree_behavior(layout_and_root) -> None:
    layout, root = layout_and_root
    _init_repo(layout, root)
    svc = GitBranchService(layout)
    svc.create_branch("srv-1", root, "feature/x")
    svc.lock_worktree("srv-1", root, "feature/x", reason="runtime:rt1")
    # mismatched expected_reason
    with pytest.raises(ConflictError):
        svc.unlock_worktree("srv-1", root, "feature/x", expected_reason="runtime:other")
    # correct
    assert svc.unlock_worktree("srv-1", root, "feature/x", expected_reason="runtime:rt1") is True
    branches = svc.list_branches("srv-1", root)
    info = next(b for b in branches if b.name == "feature/x")
    assert info.worktree_locked is False
    # idempotent
    assert svc.unlock_worktree("srv-1", root, "feature/x", ignore_unlocked=True) is False


@pytest.mark.asyncio
async def test_windows_fail_closed_lock_unlock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(os, "name", "nt")
    root = tmp_path / "server"
    root.mkdir()
    svc = GitBranchService(None)  # type: ignore[arg-type]
    with pytest.raises(ServerModeVersioningDisabledError):
        svc.lock_worktree("srv-1", root, "feature/x", reason="runtime:rt1")
    with pytest.raises(ServerModeVersioningDisabledError):
        svc.unlock_worktree("srv-1", root, "feature/x")


# --- branch guards via handlers ---

async def _seed_server(root: Path, *, with_repository: bool = True) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="Lock Server",
                server_type="paper",
                minecraft_version="1.20.4",
                status="STOPPED",
                root_path=str(root),
                working_directory=".",
                startup_jar="server.jar",
                deployment_host="127.0.0.1",
                port=25565,
                java_args="-Xmx1G",
                mode="advanced",
            )
        )
        await session.commit()
    if with_repository:
        layout = ensure_host_state_layout()
        GitRepositoryService(layout).initialize(SERVER_ID, root, _lockfile())
        from app.modules.versioning.domain.entities import BranchProtectionPolicy, ServerBranch
        from app.modules.versioning.domain.value_objects import BranchStatus

        async with database.session_factory() as session:
            await SQLVersioningRepository(session).save_branch(
                ServerBranch(
                    id="branch-main",
                    server_id=SERVER_ID,
                    name="main",
                    status=BranchStatus.ACTIVE,
                    is_protected=True,
                    protection_policy=BranchProtectionPolicy(),
                )
            )
            await session.commit()


@pytest.fixture(autouse=True)
def _host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    host_state_dir = tmp_path / "host-state"
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(host_state_dir))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    return host_state_dir




@pytest.mark.asyncio
async def test_guard_runtime_status(tmp_path: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)
    # create branch

    cb = CommandBus()
    from app.core.query_bus import QueryBus

    register_handlers(cb, QueryBus(), EventBus())
    await cb.send(CreateBranchCommand(server_id=SERVER_ID, name="dev"))

    # set runtime_status running in DB
    async with database.session_factory() as session:
        repo = SQLVersioningRepository(session)
        br = await repo.get_branch_by_name(SERVER_ID, "dev")
        br.runtime_status = "running"
        br.active_runtime_id = "rt-1"
        await repo.save_branch(br)
        await session.commit()

    # archive should raise
    handler = ArchiveBranchHandler()
    with pytest.raises(BranchRuntimeActiveError):
        await handler.handle(ArchiveBranchCommand(server_id=SERVER_ID, name="dev"))

    handler2 = DeleteBranchHandler()
    with pytest.raises(BranchRuntimeActiveError):
        await handler2.handle(DeleteBranchCommand(server_id=SERVER_ID, name="dev"))


@pytest.mark.asyncio
async def test_guard_active_runtime_row(tmp_path: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)
    from app.core.query_bus import QueryBus

    cb = CommandBus()
    register_handlers(cb, QueryBus(), EventBus())
    await cb.send(CreateBranchCommand(server_id=SERVER_ID, name="dev"))

    # insert commit + runtime row
    async with database.session_factory() as session:

        from app.modules.versioning.infrastructure.models import (
            ServerCommitModel,
            ServerRuntimeModel,
        )

        session.add(
            ServerCommitModel(id="commit1", server_id=SERVER_ID, message="m", manifest_json={})
        )
        session.add(
            ServerRuntimeModel(
                id="rt-2",
                server_id=SERVER_ID,
                commit_id="commit1",
                provider_type="docker",
                status="running",
                branch_name="dev",
                started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                created_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
            )
        )
        await session.commit()

    handler = ArchiveBranchHandler()
    with pytest.raises(BranchRuntimeActiveError):
        await handler.handle(ArchiveBranchCommand(server_id=SERVER_ID, name="dev"))


@pytest.mark.asyncio
async def test_guard_worktree_locked_runtime(tmp_path: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)
    from app.core.query_bus import QueryBus

    cb = CommandBus()
    register_handlers(cb, QueryBus(), EventBus())
    await cb.send(CreateBranchCommand(server_id=SERVER_ID, name="dev"))

    # lock worktree with runtime reason
    layout = ensure_host_state_layout()
    svc = GitBranchService(layout)
    svc.lock_worktree(SERVER_ID, root, "dev", reason="runtime:rt-3")

    handler = ArchiveBranchHandler()
    with pytest.raises(BranchRuntimeActiveError):
        await handler.handle(ArchiveBranchCommand(server_id=SERVER_ID, name="dev"))


@pytest.mark.asyncio
async def test_succeed_after_unlock(tmp_path: Path) -> None:
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)
    from app.core.query_bus import QueryBus

    cb = CommandBus()
    register_handlers(cb, QueryBus(), EventBus())
    await cb.send(CreateBranchCommand(server_id=SERVER_ID, name="dev"))

    layout = ensure_host_state_layout()
    svc = GitBranchService(layout)
    svc.lock_worktree(SERVER_ID, root, "dev", reason="runtime:rt-4")
    svc.unlock_worktree(SERVER_ID, root, "dev", expected_reason="runtime:rt-4")

    # archive succeeds
    res = await cb.send(ArchiveBranchCommand(server_id=SERVER_ID, name="dev"))
    assert res.success is True
    # delete? branch archived already; create new for delete
    await cb.send(CreateBranchCommand(server_id=SERVER_ID, name="dev2"))
    res2 = await cb.send(DeleteBranchCommand(server_id=SERVER_ID, name="dev2"))
    assert res2.success is True
