"""Git-backed branch command tests for P2-2 acceptance #2."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.host_state import ensure_host_state_layout
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    ArchiveBranchCommand,
    CreateBranchCommand,
    DeleteBranchCommand,
    GetServerBranchesQuery,
)
from app.modules.versioning.domain.lockfile import LoaderRef, LockfileV21
from app.modules.versioning.infrastructure.git_branches import GitBranchService
from app.modules.versioning.infrastructure.git_repository import GitRepositoryService
from app.modules.versioning.infrastructure.git_runner import GitRunner
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.registration import register_handlers

SERVER_ID = "srv-git-branch"


@pytest.fixture(autouse=True)
def _host_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    host_state_dir = tmp_path / "host-state"
    monkeypatch.setenv("ONX_HOST_STATE_DIR", str(host_state_dir))
    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(tmp_path / "servers"))
    return host_state_dir


@pytest.fixture
def git_buses() -> tuple[CommandBus, QueryBus]:
    command_bus = CommandBus()
    query_bus = QueryBus()
    register_handlers(command_bus, query_bus, EventBus())
    return command_bus, query_bus


def _empty_lockfile() -> LockfileV21:
    return LockfileV21(
        format=2,
        mc="1.20.4",
        loader=LoaderRef(id="paper", version="499"),
        base_overrides={},
        files=(),
    )


async def _seed_server(root: Path, *, with_repository: bool = True) -> None:
    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id=SERVER_ID,
                name="Git Branch Server",
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
        GitRepositoryService(layout).initialize(SERVER_ID, root, _empty_lockfile())
        from app.modules.versioning.domain.entities import (
            BranchProtectionPolicy,
            ServerBranch,
        )
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


def _git_branches(root: Path) -> list[str]:
    layout = ensure_host_state_layout()
    return [branch.name for branch in GitBranchService(layout).list_branches(SERVER_ID, root)]


@pytest.mark.asyncio
async def test_create_archive_delete_map_to_git_refs_and_db(
    tmp_path: Path, git_buses: tuple[CommandBus, QueryBus]
) -> None:
    command_bus, query_bus = git_buses
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)

    created = await command_bus.send(CreateBranchCommand(server_id=SERVER_ID, name="dev"))
    assert created.success is True
    assert _git_branches(root) == ["dev", "main"]
    assert (root / ".onx" / "worktrees" / "dev").is_dir()

    async with database.session_factory() as session:
        row = await SQLVersioningRepository(session).get_branch_by_name(SERVER_ID, "dev")
    assert row is not None
    assert row.status.value == "active"

    listed = await query_bus.ask(GetServerBranchesQuery(server_id=SERVER_ID))
    by_name = {item["name"]: item for item in listed}
    assert set(by_name) == {"main", "dev"}
    assert len(by_name["dev"]["head_commit_id"]) == 40
    assert by_name["dev"]["worktree_path"].endswith("/.onx/worktrees/dev")

    archived = await command_bus.send(ArchiveBranchCommand(server_id=SERVER_ID, name="dev"))
    assert archived.success is True
    assert _git_branches(root) == ["dev", "main"]
    assert not (root / ".onx" / "worktrees" / "dev").exists()
    async with database.session_factory() as session:
        row = await SQLVersioningRepository(session).get_branch_by_name(SERVER_ID, "dev")
    assert row is not None
    assert row.status.value == "archived"

    deleted = await command_bus.send(DeleteBranchCommand(server_id=SERVER_ID, name="dev"))
    assert deleted.success is True
    assert _git_branches(root) == ["main"]
    async with database.session_factory() as session:
        row = await SQLVersioningRepository(session).get_branch_by_name(SERVER_ID, "dev")
    assert row is None


@pytest.mark.asyncio
async def test_main_is_not_archivable_or_deletable(
    tmp_path: Path, git_buses: tuple[CommandBus, QueryBus]
) -> None:
    command_bus, _ = git_buses
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)

    archived = await command_bus.send(ArchiveBranchCommand(server_id=SERVER_ID, name="main"))
    assert archived.success is False
    assert "main" in (archived.error or "").lower()

    deleted = await command_bus.send(DeleteBranchCommand(server_id=SERVER_ID, name="main"))
    assert deleted.success is False
    assert "main" in (deleted.error or "").lower()
    assert _git_branches(root) == ["main"]


@pytest.mark.asyncio
async def test_delete_refuses_unmerged_branch(
    tmp_path: Path, git_buses: tuple[CommandBus, QueryBus]
) -> None:
    command_bus, _ = git_buses
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)
    created = await command_bus.send(CreateBranchCommand(server_id=SERVER_ID, name="feature"))
    assert created.success is True

    worktree = root / ".onx" / "worktrees" / "feature"
    (worktree / "config").mkdir()
    (worktree / "config" / "new.yml").write_text("enabled: true\n", encoding="utf-8")

    layout = ensure_host_state_layout()
    repo_dir = layout.repo_dir(SERVER_ID)
    runner = GitRunner(
        repo_path=repo_dir / "repo.git",
        config_path=repo_dir / "gitconfig",
    )
    runner.run("add", "config/new.yml", cwd=worktree)
    runner.run("commit", "-m", "feature change", cwd=worktree)

    deleted = await command_bus.send(DeleteBranchCommand(server_id=SERVER_ID, name="feature"))
    assert deleted.success is False
    assert "not merged" in (deleted.error or "")
    assert _git_branches(root) == ["feature", "main"]


@pytest.mark.asyncio
async def test_db_only_advanced_server_keeps_legacy_branch_lifecycle(
    tmp_path: Path, git_buses: tuple[CommandBus, QueryBus]
) -> None:
    command_bus, _ = git_buses
    root = tmp_path / "server-no-repo"
    root.mkdir()
    await _seed_server(root, with_repository=False)

    created = await command_bus.send(CreateBranchCommand(server_id=SERVER_ID, name="legacy"))
    assert created.success is True
    assert not (root / ".onx").exists()

    archived = await command_bus.send(ArchiveBranchCommand(server_id=SERVER_ID, name="legacy"))
    assert archived.success is True

    deleted = await command_bus.send(DeleteBranchCommand(server_id=SERVER_ID, name="legacy"))
    assert deleted.success is True


@pytest.mark.asyncio
async def test_invalid_git_branch_name_leaves_no_db_row(
    tmp_path: Path, git_buses: tuple[CommandBus, QueryBus]
) -> None:
    command_bus, _ = git_buses
    root = tmp_path / "server"
    root.mkdir()
    await _seed_server(root)

    created = await command_bus.send(CreateBranchCommand(server_id=SERVER_ID, name="..bad"))
    assert created.success is False
    assert _git_branches(root) == ["main"]
    async with database.session_factory() as session:
        rows = await SQLVersioningRepository(session).list_branches(SERVER_ID)
    assert [row.name for row in rows] == ["main"]
