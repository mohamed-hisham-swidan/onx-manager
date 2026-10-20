import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.command_bus import CommandBus
from app.core.exceptions import NotFoundError
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import ServerDeployment
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
from app.modules.versioning.application.commands.promote_commit import (
    PromoteCommitCommand,
    PromoteCommitHandler,
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
async def test_promote_commit_workflow() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=OldServer\n", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-1")
        mock_server.status = ServerStatus.STOPPED
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()

        manifest = CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=PromotedNewServer\n"},
        )
        commit = ServerCommit(
            id="c-999", server_id="srv-1", message="Promote me", manifest=manifest
        )
        await v_repo.save_commit(commit)

        test_run = ServerTestRun(
            id="t-999",
            server_id="srv-1",
            commit_id="c-999",
            status=TestRunStatus.PASSED,
        )
        await v_repo.save_test_run(test_run)

        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)

        promote_handler = PromoteCommitHandler(
            server_repo=server_repo,
            versioning_repo=v_repo,
            command_bus=command_bus,
            test_runner=test_runner,
        )

        res = await promote_handler.handle(PromoteCommitCommand(server_id="srv-1", test_id="t-999"))
        assert res.is_success
        assert res.details["promoted"] is True

        # Assert live server.properties was updated to promoted manifest content
        assert (srv_dir / "server.properties").read_text(
            encoding="utf-8"
        ) == "motd=PromotedNewServer\n"
        assert test_runner.cleanup_test.called


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
async def test_promote_commit_with_keep_world_changes() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=OldServer\n", encoding="utf-8")
        live_world = srv_dir / "world"
        live_world.mkdir()
        (live_world / "level.dat").write_text("old-level-data", encoding="utf-8")

        test_dir = srv_dir / ".onx" / "tests" / "t-world"
        test_dir.mkdir(parents=True)
        test_world = test_dir / "world"
        test_world.mkdir()
        (test_world / "level.dat").write_text("new-level-data-from-test", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-1")
        mock_server.status = ServerStatus.STOPPED
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()
        manifest = CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=NewWorldServer\n"},
        )
        commit = ServerCommit(
            id="c-world", server_id="srv-1", message="World change commit", manifest=manifest
        )
        await v_repo.save_commit(commit)

        test_run = ServerTestRun(
            id="t-world",
            server_id="srv-1",
            commit_id="c-world",
            status=TestRunStatus.PASSED,
        )
        await v_repo.save_test_run(test_run)

        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)

        promote_handler = PromoteCommitHandler(
            server_repo=server_repo,
            versioning_repo=v_repo,
            command_bus=command_bus,
            test_runner=test_runner,
        )

        res = await promote_handler.handle(
            PromoteCommitCommand(server_id="srv-1", test_id="t-world", keep_world_changes=True)
        )
        assert res.is_success
        assert res.details["kept_world_changes"] is True
        assert (live_world / "level.dat").read_text(encoding="utf-8") == "new-level-data-from-test"


@pytest.mark.asyncio
async def test_promote_rejects_nonexistent_test_or_server() -> None:
    server_repo = AsyncMock(spec=ServerRepository)
    server_repo.get.side_effect = Exception("Not found")
    v_repo = InMemoryVersioningRepository()
    command_bus = AsyncMock(spec=CommandBus)

    promote_handler = PromoteCommitHandler(
        server_repo=server_repo,
        versioning_repo=v_repo,
        command_bus=command_bus,
    )

    with pytest.raises(NotFoundError):
        await promote_handler.handle(PromoteCommitCommand(server_id="srv-missing", test_id="t-1"))


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
