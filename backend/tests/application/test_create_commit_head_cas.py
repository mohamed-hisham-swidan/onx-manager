import asyncio
import contextlib
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import ConflictError
from app.core.persistence.base import Base
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import ServerDeployment
from app.modules.server.infrastructure.models import ServerModel
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.application.commands.create_branch import (
    CreateBranchCommand,
    CreateBranchHandler,
)
from app.modules.versioning.application.commands.create_commit import (
    CreateCommitCommand,
    CreateCommitHandler,
)
from app.modules.versioning.application.commands.discard_test import (
    DiscardTestCommand,
    DiscardTestHandler,
)
from app.modules.versioning.application.commands.merge_commits import (
    MergeCommitsCommand,
    MergeCommitsHandler,
)
from app.modules.versioning.application.queries.get_commit_history import (
    GetCommitHistoryHandler,
    GetCommitHistoryQuery,
)
from app.modules.versioning.application.queries.get_server_branches import (
    GetServerBranchesHandler,
    GetServerBranchesQuery,
)
from app.modules.versioning.application.queries.get_test_status import (
    GetTestStatusHandler,
    GetTestStatusQuery,
)
from app.modules.versioning.domain.entities import (
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    CommitManifest,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import ServerBranchModel, ServerCommitModel
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_runner import TestExecutionRunner


class InMemoryVersioningRepository(VersioningRepository):
    def __init__(self) -> None:
        self.branches: dict[str, ServerBranch] = {}
        self.commits: dict[str, ServerCommit] = {}
        self.snapshots: dict[str, ServerWorldSnapshot] = {}
        self.test_runs: dict[str, ServerTestRun] = {}

    async def get_branch(self, branch_id: str) -> ServerBranch | None:
        return self.branches.get(branch_id)

    async def get_branch_by_name(self, server_id: str, name: str) -> ServerBranch | None:
        for b in self.branches.values():
            if b.server_id == server_id and b.name == name:
                return b
        return None

    async def list_branches(self, server_id: str) -> list[ServerBranch]:
        return [b for b in self.branches.values() if b.server_id == server_id]

    async def save_branch(self, branch: ServerBranch) -> ServerBranch:
        self.branches[branch.id] = branch
        return branch

    async def advance_branch_head_optimistic(
        self, branch_id: str, new_head: str, expected_head: str | None
    ) -> bool:
        branch = self.branches.get(branch_id)
        if branch is None:
            return False
        if branch.status == BranchStatus.ARCHIVED:
            return False
        if branch.head_commit_id != expected_head:
            return False
        branch.advance_head(new_head)
        return True

    async def get_commit(self, commit_id: str) -> ServerCommit | None:
        return self.commits.get(commit_id)

    async def list_commits(
        self, server_id: str, branch_id: str | None = None, limit: int = 50
    ) -> list[ServerCommit]:
        res = [c for c in self.commits.values() if c.server_id == server_id]
        if branch_id:
            res = [c for c in res if c.branch_id == branch_id]
        return res[:limit]

    async def save_commit(self, commit: ServerCommit) -> ServerCommit:
        self.commits[commit.id] = commit
        return commit

    async def get_snapshot(self, snapshot_id: str) -> ServerWorldSnapshot | None:
        return self.snapshots.get(snapshot_id)

    async def save_snapshot(self, snapshot: ServerWorldSnapshot) -> ServerWorldSnapshot:
        self.snapshots[snapshot.id] = snapshot
        return snapshot

    async def get_test_run(self, test_run_id: str) -> ServerTestRun | None:
        return self.test_runs.get(test_run_id)

    async def get_active_test_run_for_server(self, server_id: str) -> ServerTestRun | None:
        for r in self.test_runs.values():
            if r.server_id == server_id and r.status in (
                TestRunStatus.PENDING,
                TestRunStatus.RUNNING,
            ):
                return r
        return None

    async def list_test_runs(self, server_id: str, limit: int = 20) -> list[ServerTestRun]:
        return [r for r in self.test_runs.values() if r.server_id == server_id][:limit]

    async def save_test_run(self, test_run: ServerTestRun) -> ServerTestRun:
        self.test_runs[test_run.id] = test_run
        return test_run


BaseInMemoryRepo = InMemoryVersioningRepository

PATCH_REFLINK = (
    "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe"
    ".assert_supports_reflink"
)
PATCH_DRIVER = (
    "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver"
    ".create_snapshot"
)


def _create_sqlite_engine(db_file: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cursor.close()

    return engine


class StaleOverrideInMemoryRepo(BaseInMemoryRepo):
    """In-memory repo supporting stale_branch_override for get_branch_by_name."""

    def __init__(
        self,
        canonical_repo: BaseInMemoryRepo | None = None,
        stale_branch: ServerBranch | None = None,
    ) -> None:
        if canonical_repo is not None:
            self.branches = canonical_repo.branches
            self.commits = canonical_repo.commits
            self.snapshots = canonical_repo.snapshots
            self.test_runs = canonical_repo.test_runs
        else:
            super().__init__()
        self.stale_branch = stale_branch

    async def get_branch_by_name(self, server_id: str, name: str) -> ServerBranch | None:
        if self.stale_branch is not None and self.stale_branch.name == name:
            return self.stale_branch
        return await super().get_branch_by_name(server_id, name)


@pytest.mark.asyncio
async def test_create_commit_stale_head_raises_conflict_and_leaves_no_orphan(
    tmp_path: Path,
) -> None:
    srv_dir = tmp_path / "srv-fake"
    srv_dir.mkdir()
    (srv_dir / "server.properties").write_text("motd=Test\n", encoding="utf-8")
    world_dir = srv_dir / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"dat")

    mock_server = MagicMock(spec=Server)
    mock_server.id = ServerId("srv-1")
    mock_server.server_type = "vanilla"
    mock_server.minecraft_version = "1.21.1"
    mock_server.java_args = "-Xmx2G"
    mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

    server_repo = AsyncMock(spec=ServerRepository)
    server_repo.get.return_value = mock_server

    shared_repo = StaleOverrideInMemoryRepo()
    initial_branch = ServerBranch(
        id="br-shared",
        server_id="srv-1",
        name="main",
        head_commit_id=None,
        status=BranchStatus.CREATED,
    )
    await shared_repo.save_branch(initial_branch)

    # 1. Handler A runs on shared repo
    handler_a = CreateCommitHandler(server_repo, shared_repo)
    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
    ):
        res_a = await handler_a.handle(
            CreateCommitCommand(server_id="srv-1", message="Commit A", branch_name="main")
        )
        assert res_a.success is True
        commit_a = res_a.entity_id
        assert shared_repo.branches["br-shared"].head_commit_id == commit_a

    # 2. Build stale view with head_commit_id=None (as read in step 1)
    stale_branch = ServerBranch(
        id="br-shared",
        server_id="srv-1",
        name="main",
        head_commit_id=None,
        status=BranchStatus.CREATED,
    )
    stale_repo = StaleOverrideInMemoryRepo(canonical_repo=shared_repo, stale_branch=stale_branch)

    # 3. Handler B runs on stale_repo
    handler_b = CreateCommitHandler(server_repo, stale_repo)
    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
        pytest.raises(ConflictError) as exc_info,
    ):
        await handler_b.handle(
            CreateCommitCommand(server_id="srv-1", message="Commit B", branch_name="main")
        )
    assert exc_info.value.http_status == 409

    # Assert branch head is still commit_a
    assert shared_repo.branches["br-shared"].head_commit_id == commit_a
    # Assert commit_a remains referenced and commit_b is absent
    assert set(shared_repo.commits.keys()) == {commit_a}


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_create_commit_real_db_stale_head_conflict_two_engines(tmp_path: Path) -> None:
    db_file = tmp_path / "handler-cas.sqlite3"
    engine_a = _create_sqlite_engine(db_file)
    engine_b = _create_sqlite_engine(db_file)

    try:
        async with engine_a.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory_a = async_sessionmaker(bind=engine_a, class_=AsyncSession, expire_on_commit=False)
        factory_b = async_sessionmaker(bind=engine_b, class_=AsyncSession, expire_on_commit=False)

        server_id = "srv-cas-db"
        srv_dir = tmp_path / "srv-real"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=Real\n", encoding="utf-8")
        world_dir = srv_dir / "world"
        world_dir.mkdir()
        (world_dir / "level.dat").write_bytes(b"dat")

        initial_head = "c-initial"

        async with factory_a() as sess:
            server_model = ServerModel(
                id=server_id,
                name="CasServer",
                server_type="paper",
                minecraft_version="1.21.4",
                status="STOPPED",
                root_path=str(srv_dir),
                port=25565,
                mode="advanced",
            )
            branch_model = ServerBranchModel(
                id="br-cas",
                server_id=server_id,
                name="main",
                head_commit_id=initial_head,
                status="active",
                is_protected=False,
                created_at=datetime.now(UTC),
            )
            commit_model = ServerCommitModel(
                id=initial_head,
                server_id=server_id,
                message="Initial head",
                manifest_json={},
                branch_id="br-cas",
                created_at=datetime.now(UTC),
            )
            sess.add(server_model)
            sess.add(branch_model)
            sess.add(commit_model)
            await sess.commit()

        read_done = asyncio.Event()
        gate = asyncio.Event()

        class GatedSQLVersioningRepository(SQLVersioningRepository):
            async def get_branch_by_name(self, s_id: str, name: str) -> ServerBranch | None:
                b = await super().get_branch_by_name(s_id, name)
                read_done.set()
                await gate.wait()
                return b

            async def save_snapshot(self, snapshot: ServerWorldSnapshot) -> ServerWorldSnapshot:
                # No-op so CAS UPDATE is the first write after B's stale read
                return snapshot

        session_b = factory_b()
        server_repo_b = SQLServerRepository(session_b)
        versioning_repo_b = GatedSQLVersioningRepository(session_b)

        handler_b = CreateCommitHandler(server_repo_b, versioning_repo_b)

        session_a = factory_a()
        server_repo_a = SQLServerRepository(session_a)
        versioning_repo_a = SQLVersioningRepository(session_a)
        handler_a = CreateCommitHandler(server_repo_a, versioning_repo_a)

        with (
            patch(PATCH_REFLINK),
            patch(PATCH_DRIVER, return_value=100),
        ):
            # Launch handler B in background; it will read branch and pause on gate
            task_b = asyncio.create_task(
                handler_b.handle(
                    CreateCommitCommand(
                        server_id=server_id, message="Commit B", branch_name="main"
                    )
                )
            )

            try:
                # Wait until handler B has read the branch with head=c-initial
                try:
                    await asyncio.wait_for(read_done.wait(), timeout=30)
                except TimeoutError:
                    if task_b.done() and not task_b.cancelled():
                        exc = task_b.exception()
                        if exc is not None:
                            raise exc from None
                    raise

                # Handler A completes first
                res_a = await handler_a.handle(
                    CreateCommitCommand(server_id=server_id, message="Commit A", branch_name="main")
                )
                assert res_a.success is True
                commit_a = res_a.entity_id
                await session_a.commit()
                await session_a.close()

                # Release gate for handler B
                gate.set()

                with pytest.raises(ConflictError) as exc_info:
                    await task_b
                assert exc_info.value.http_status == 409
            finally:
                if not task_b.done():
                    task_b.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await task_b

        await session_b.close()

        # Reload state from DB: head must be commit_a, only commit_a added
        async with factory_a() as sess:
            repo = SQLVersioningRepository(sess)
            branch = await repo.get_branch("br-cas")
            assert branch is not None
            assert branch.head_commit_id == commit_a

            commits = await repo.list_commits(server_id)
            commit_ids = {c.id for c in commits}
            assert commit_ids == {initial_head, commit_a}
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.asyncio
async def test_create_commit_validates_existing_parent(tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-parent"
    srv_dir.mkdir()
    (srv_dir / "server.properties").write_text("motd=Test\n")
    world_dir = srv_dir / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"dat")

    mock_server = MagicMock(spec=Server)
    mock_server.id = ServerId("srv-1")
    mock_server.server_type = "vanilla"
    mock_server.minecraft_version = "1.21.1"
    mock_server.java_args = "-Xmx2G"
    mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

    server_repo = AsyncMock(spec=ServerRepository)
    server_repo.get.return_value = mock_server

    fake_repo = BaseInMemoryRepo()
    branch = ServerBranch(
        id="br-parent-test",
        server_id="srv-1",
        name="main",
        head_commit_id="c-parent",
        status=BranchStatus.ACTIVE,
    )
    parent_commit = ServerCommit(
        id="c-parent",
        server_id="srv-OTHER",  # Mismatched server!
        message="Foreign parent",
        manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={}),
    )
    await fake_repo.save_branch(branch)
    await fake_repo.save_commit(parent_commit)

    handler = CreateCommitHandler(server_repo, fake_repo)
    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
        pytest.raises(ValueError, match="Cross-server parent rejected"),
    ):
        await handler.handle(
            CreateCommitCommand(server_id="srv-1", message="Child", branch_name="main")
        )


@pytest.mark.asyncio
async def test_merge_stale_head_raises_conflict_and_keeps_head() -> None:
    server_repo = AsyncMock(spec=ServerRepository)
    mock_server = MagicMock(spec=Server)
    mock_server.id = ServerId("srv-1")
    server_repo.get.return_value = mock_server

    manifest = CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={})
    p1 = ServerCommit(id="c-1", server_id="srv-1", message="P1", manifest=manifest)
    p2 = ServerCommit(id="c-2", server_id="srv-1", message="P2", manifest=manifest)
    c3 = ServerCommit(id="c-3", server_id="srv-1", message="P3", manifest=manifest)

    canonical_repo = StaleOverrideInMemoryRepo()
    await canonical_repo.save_commit(p1)
    await canonical_repo.save_commit(p2)
    await canonical_repo.save_commit(c3)

    branch = ServerBranch(
        id="br-merge",
        server_id="srv-1",
        name="feature-merge",
        head_commit_id="c-1",
        status=BranchStatus.ACTIVE,
    )
    await canonical_repo.save_branch(branch)

    # Stale view holds head_commit_id="c-1"
    stale_branch = ServerBranch(
        id="br-merge",
        server_id="srv-1",
        name="feature-merge",
        head_commit_id="c-1",
        status=BranchStatus.ACTIVE,
    )
    stale_repo = StaleOverrideInMemoryRepo(canonical_repo=canonical_repo, stale_branch=stale_branch)

    # Concurrently, canonical head advances to c-3
    canonical_repo.branches["br-merge"].head_commit_id = "c-3"

    handler = MergeCommitsHandler(server_repo, stale_repo)
    cmd = MergeCommitsCommand(
        server_id="srv-1",
        target_branch_name="feature-merge",
        parent_commit_ids=["c-1", "c-2"],
        message="Merge",
    )
    with pytest.raises(ConflictError) as exc_info:
        await handler.handle(cmd)

    assert exc_info.value.http_status == 409
    assert canonical_repo.branches["br-merge"].head_commit_id == "c-3"
    # Ensure no merge commit was persisted
    assert set(canonical_repo.commits.keys()) == {"c-1", "c-2", "c-3"}


@pytest.mark.asyncio
async def test_fake_cas_rejects_archived_branch() -> None:
    repo = BaseInMemoryRepo()
    branch = ServerBranch(
        id="br-arch",
        server_id="srv-1",
        name="arch",
        head_commit_id="c-0",
        status=BranchStatus.ARCHIVED,
    )
    await repo.save_branch(branch)
    ok = await repo.advance_branch_head_optimistic("br-arch", "c-new", "c-0")
    assert ok is False


@pytest.mark.asyncio
async def test_create_commit_second_commit_on_non_null_head_succeeds(tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-second"
    srv_dir.mkdir()
    (srv_dir / "server.properties").write_text("motd=Test\n")
    world_dir = srv_dir / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"dat")

    mock_server = MagicMock(spec=Server)
    mock_server.id = ServerId("srv-1")
    mock_server.server_type = "vanilla"
    mock_server.minecraft_version = "1.21.1"
    mock_server.java_args = "-Xmx2G"
    mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

    server_repo = AsyncMock(spec=ServerRepository)
    server_repo.get.return_value = mock_server

    repo = BaseInMemoryRepo()
    manifest = CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={})
    c1 = ServerCommit(id="c-1", server_id="srv-1", message="C1", manifest=manifest)
    await repo.save_commit(c1)

    branch = ServerBranch(
        id="br-second",
        server_id="srv-1",
        name="main",
        head_commit_id="c-1",
        status=BranchStatus.ACTIVE,
    )
    await repo.save_branch(branch)

    handler = CreateCommitHandler(server_repo, repo)
    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
    ):
        res = await handler.handle(
            CreateCommitCommand(server_id="srv-1", message="C2", branch_name="main")
        )
        assert res.success is True
        c2_id = res.entity_id
        reloaded = await repo.get_branch("br-second")
        assert reloaded is not None
        assert reloaded.head_commit_id == c2_id
        c2 = await repo.get_commit(c2_id)
        assert c2 is not None
        assert c2.parent_commit_id == "c-1"


@pytest.mark.asyncio
async def test_first_commit_transitions_created_to_active(tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-trans"
    srv_dir.mkdir()
    (srv_dir / "server.properties").write_text("motd=Test\n")
    world_dir = srv_dir / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"dat")

    mock_server = MagicMock(spec=Server)
    mock_server.id = ServerId("srv-1")
    mock_server.server_type = "vanilla"
    mock_server.minecraft_version = "1.21.1"
    mock_server.java_args = "-Xmx2G"
    mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

    server_repo = AsyncMock(spec=ServerRepository)
    server_repo.get.return_value = mock_server

    repo = BaseInMemoryRepo()
    branch = ServerBranch(
        id="br-trans",
        server_id="srv-1",
        name="main",
        head_commit_id=None,
        status=BranchStatus.CREATED,
    )
    await repo.save_branch(branch)

    handler = CreateCommitHandler(server_repo, repo)
    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
    ):
        res = await handler.handle(
            CreateCommitCommand(server_id="srv-1", message="First", branch_name="main")
        )
        assert res.success is True
        reloaded = await repo.get_branch("br-trans")
        assert reloaded is not None
        assert reloaded.status == BranchStatus.ACTIVE


@pytest.mark.asyncio
async def test_successful_cas_does_not_persist_stale_branch_object(tmp_path: Path) -> None:
    srv_dir = tmp_path / "srv-spy"
    srv_dir.mkdir()
    (srv_dir / "server.properties").write_text("motd=Test\n")
    world_dir = srv_dir / "world"
    world_dir.mkdir()
    (world_dir / "level.dat").write_bytes(b"dat")

    mock_server = MagicMock(spec=Server)
    mock_server.id = ServerId("srv-1")
    mock_server.server_type = "vanilla"
    mock_server.minecraft_version = "1.21.1"
    mock_server.java_args = "-Xmx2G"
    mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

    server_repo = AsyncMock(spec=ServerRepository)
    server_repo.get.return_value = mock_server

    repo = BaseInMemoryRepo()
    manifest = CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={})
    c1 = ServerCommit(id="c-1", server_id="srv-1", message="C1", manifest=manifest)
    await repo.save_commit(c1)

    branch = ServerBranch(
        id="br-spy",
        server_id="srv-1",
        name="main",
        head_commit_id="c-1",
        status=BranchStatus.ACTIVE,
    )
    await repo.save_branch(branch)

    # Spy on save_branch
    original_save = repo.save_branch
    save_branch_calls = []

    async def spy_save(b: ServerBranch) -> ServerBranch:
        save_branch_calls.append(b)
        return await original_save(b)

    repo.save_branch = spy_save

    handler = CreateCommitHandler(server_repo, repo)
    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
    ):
        res = await handler.handle(
            CreateCommitCommand(server_id="srv-1", message="C2", branch_name="main")
        )
        assert res.success is True

    # Assert save_branch was NOT called on the head-advance path
    assert len(save_branch_calls) == 0, (
        f"Expected 0 calls to save_branch on head advance, got {len(save_branch_calls)}"
    )
    reloaded = await repo.get_branch("br-spy")
    assert reloaded is not None
    assert reloaded.head_commit_id == res.entity_id
    assert reloaded.status == BranchStatus.ACTIVE


@pytest.mark.asyncio
async def test_archived_branch_named_locked_main_is_not_retried(tmp_path: Path) -> None:
    server_id = f"srv-lock-{uuid.uuid4().hex[:6]}"
    srv_dir = tmp_path / server_id
    srv_dir.mkdir()
    (srv_dir / "server.properties").write_text("motd=Lock\n")

    from app.core.persistence.db import database

    async with database.session_factory() as sess:
        server = ServerModel(
            id=server_id,
            name="LockedServer",
            server_type="paper",
            minecraft_version="1.21.4",
            status="STOPPED",
            root_path=str(srv_dir),
            port=25565,
            mode="advanced",
        )
        branch = ServerBranchModel(
            id=f"br-{uuid.uuid4().hex[:6]}",
            server_id=server_id,
            name="locked-main",
            head_commit_id="c-1",
            status="archived",
            is_protected=False,
            created_at=datetime.now(UTC),
        )
        sess.add(server)
        sess.add(branch)
        await sess.commit()

    handler = CreateCommitHandler()
    call_count = 0
    orig_execute = handler._execute

    async def counting_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await orig_execute(*args, **kwargs)

    handler._execute = counting_execute

    with (
        patch(PATCH_REFLINK),
        patch(PATCH_DRIVER, return_value=100),
        pytest.raises(ConflictError) as exc_info,
    ):
        await handler.handle(
            CreateCommitCommand(server_id=server_id, message="msg", branch_name="locked-main")
        )

    assert exc_info.value.http_status == 409
    assert call_count == 1, f"Expected exactly 1 attempt without retry, got {call_count}"


@pytest.mark.asyncio
async def test_merge_archived_branch_named_locked_main_is_not_retried() -> None:
    server_id = f"srv-merge-lock-{uuid.uuid4().hex[:6]}"

    from app.core.persistence.db import database

    async with database.session_factory() as sess:
        server = ServerModel(
            id=server_id,
            name="MergeLockServer",
            server_type="paper",
            minecraft_version="1.21.4",
            status="STOPPED",
            root_path="/tmp/null",
            port=25565,
            mode="advanced",
        )
        branch = ServerBranchModel(
            id=f"br-{uuid.uuid4().hex[:6]}",
            server_id=server_id,
            name="locked-main",
            head_commit_id="c-1",
            status="archived",
            is_protected=False,
            created_at=datetime.now(UTC),
        )
        sess.add(server)
        sess.add(branch)
        await sess.commit()

    handler = MergeCommitsHandler()
    call_count = 0
    orig_execute = handler._execute

    async def counting_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await orig_execute(*args, **kwargs)

    handler._execute = counting_execute

    with pytest.raises(ConflictError) as exc_info:
        await handler.handle(
            MergeCommitsCommand(
                server_id=server_id,
                target_branch_name="locked-main",
                parent_commit_ids=["c-1", "c-2"],
                message="merge",
            )
        )

    assert exc_info.value.http_status == 409
    assert call_count == 1, f"Expected exactly 1 attempt without retry, got {call_count}"


@pytest.mark.asyncio
async def test_create_branch_and_commit_workflow() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=ProdServer\n", encoding="utf-8")
        world_dir = srv_dir / "world"
        world_dir.mkdir()
        (world_dir / "level.dat").write_bytes(b"dat")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-1")
        mock_server.server_type = "vanilla"
        mock_server.minecraft_version = "1.21.1"
        mock_server.java_args = "-Xmx2G"
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()

        # 1. Create branch
        branch_handler = CreateBranchHandler(server_repo, v_repo)
        b_res = await branch_handler.handle(
            CreateBranchCommand(server_id="srv-1", name="feat-trial")
        )
        assert b_res.is_success
        assert len(v_repo.branches) == 1

        # 2. Create commit
        commit_handler = CreateCommitHandler(server_repo, v_repo)
        with (
            patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
            patch("subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            c_res = await commit_handler.handle(
                CreateCommitCommand(
                    server_id="srv-1", message="Initial trial commit", branch_name="feat-trial"
                )
            )
            assert c_res.is_success
            assert len(v_repo.commits) == 1
            commit = v_repo.commits[c_res.entity_id]
            assert commit.message == "Initial trial commit"
            assert "server.properties" in commit.manifest.configs
            assert v_repo.branches[b_res.entity_id].head_commit_id == commit.id


@pytest.mark.asyncio
async def test_discard_test_workflow() -> None:
    server_repo = AsyncMock(spec=ServerRepository)
    mock_server = MagicMock(spec=Server)
    mock_server.deployment = ServerDeployment(root_path="/tmp/srv", working_directory=".")
    server_repo.get.return_value = mock_server

    v_repo = InMemoryVersioningRepository()
    test_run = ServerTestRun(
        id="t-discard", server_id="srv-1", commit_id="c-1", status=TestRunStatus.RUNNING
    )
    await v_repo.save_test_run(test_run)

    test_runner = AsyncMock(spec=TestExecutionRunner)
    discard_handler = DiscardTestHandler(server_repo, v_repo, test_runner=test_runner)

    res = await discard_handler.handle(DiscardTestCommand(server_id="srv-1", test_id="t-discard"))
    assert res.is_success
    assert res.details["status"] == "CANCELLED"
    assert v_repo.test_runs["t-discard"].status == TestRunStatus.CANCELLED
    assert test_runner.cleanup_test.called


@pytest.mark.asyncio
async def test_versioning_query_handlers() -> None:
    v_repo = InMemoryVersioningRepository()

    branch = ServerBranch(id="b-1", server_id="srv-1", name="main", head_commit_id="c-1")
    await v_repo.save_branch(branch)

    manifest = CommitManifest(
        server_type="paper", minecraft_version="1.21.1", configs={"paper.yml": ""}
    )
    commit = ServerCommit(
        id="c-1", server_id="srv-1", branch_id="b-1", message="First", manifest=manifest
    )
    await v_repo.save_commit(commit)

    test_run = ServerTestRun(
        id="t-1",
        server_id="srv-1",
        commit_id="c-1",
        status=TestRunStatus.PASSED,
        bot_count=2,
        duration_minutes=5,
    )
    await v_repo.save_test_run(test_run)

    branches = await GetServerBranchesHandler(v_repo).handle(
        GetServerBranchesQuery(server_id="srv-1")
    )
    assert len(branches) == 1
    assert branches[0]["name"] == "main"

    commits = await GetCommitHistoryHandler(v_repo).handle(GetCommitHistoryQuery(server_id="srv-1"))
    assert len(commits) == 1
    assert commits[0]["message"] == "First"

    t_status = await GetTestStatusHandler(v_repo).handle(
        GetTestStatusQuery(server_id="srv-1", test_id="t-1")
    )
    assert t_status["status"] == "PASSED"
    assert t_status["bot_count"] == 2
