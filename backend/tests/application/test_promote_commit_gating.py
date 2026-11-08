from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.command_bus import CommandBus, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import ValidationError
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository
from app.modules.server.application.commands.start_server import StartServerCommand
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.repository import ServerRepository
from app.modules.server.domain.value_objects import ServerDeployment
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.application.commands.promote_commit import (
    PromoteCommitCommand,
    PromoteCommitHandler,
)
from app.modules.versioning.application.queries.get_server_test_runs import (
    GetServerTestRunsHandler,
    GetServerTestRunsQuery,
)
from app.modules.versioning.domain.entities import (
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
)
from app.modules.versioning.domain.events import CommitPromotedEvent
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    CommitManifest,
    TestRunStatus,
)
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
        runs = [r for r in self.test_runs.values() if r.server_id == server_id]
        runs.sort(key=lambda x: x.created_at, reverse=True)
        return runs[:limit]

    async def save_test_run(self, test_run: ServerTestRun) -> ServerTestRun:
        self.test_runs[test_run.id] = test_run
        return test_run


class InMemoryActivityRepository(ActivityRepository):
    def __init__(self) -> None:
        self.logs: list[ServerActivityLog] = []

    async def save(self, log: ServerActivityLog) -> None:
        self.logs.append(log)

    async def list_by_server(
        self,
        server_id: str,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        from_date: float | None = None,
        to_date: float | None = None,
    ) -> tuple[list[ServerActivityLog], int]:
        _ = (from_date, to_date)
        matching = [entry for entry in self.logs if entry.server_id == server_id]
        if event_type:
            matching = [entry for entry in matching if entry.event_type == event_type]
        return matching[offset : offset + limit], len(matching)

    async def delete_older_than(self, cutoff_timestamp: float) -> int:
        before = len(self.logs)
        self.logs = [entry for entry in self.logs if entry.timestamp >= cutoff_timestamp]
        return before - len(self.logs)


@pytest.fixture
def test_setup():
    with tempfile.TemporaryDirectory() as tmpdir:
        srv_dir = Path(tmpdir) / "srv"
        srv_dir.mkdir()
        (srv_dir / "server.properties").write_text("motd=Base\n", encoding="utf-8")

        mock_server = MagicMock(spec=Server)
        mock_server.id = ServerId("srv-gate-1")
        mock_server.status = ServerStatus.STOPPED
        mock_server.deployment = ServerDeployment(root_path=str(srv_dir), working_directory=".")

        server_repo = AsyncMock(spec=ServerRepository)
        server_repo.get.return_value = mock_server

        v_repo = InMemoryVersioningRepository()
        act_repo = InMemoryActivityRepository()
        command_bus = AsyncMock(spec=CommandBus)
        test_runner = AsyncMock(spec=TestExecutionRunner)
        event_bus = AsyncMock(spec=EventBus)

        handler = PromoteCommitHandler(
            server_repo=server_repo,
            versioning_repo=v_repo,
            command_bus=command_bus,
            test_runner=test_runner,
            event_bus=event_bus,
            activity_repo=act_repo,
        )

        yield {
            "srv_dir": srv_dir,
            "server_repo": server_repo,
            "v_repo": v_repo,
            "act_repo": act_repo,
            "handler": handler,
            "event_bus": event_bus,
            "test_runner": test_runner,
            "command_bus": command_bus,
        }


@pytest.mark.asyncio
async def test_promote_rejects_failed_test_run(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    handler = test_setup["handler"]

    commit = ServerCommit(
        id="c-failing",
        server_id="srv-gate-1",
        message="Broken update",
        manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={}),
    )
    await v_repo.save_commit(commit)

    test_run = ServerTestRun(
        id="t-fail-1",
        server_id="srv-gate-1",
        commit_id="c-failing",
        status=TestRunStatus.FAILED,
        failure_reason="Bot connection refused",
    )
    await v_repo.save_test_run(test_run)

    with pytest.raises(ValidationError, match="Only PASSED test runs can be promoted"):
        await handler.handle(
            PromoteCommitCommand(server_id="srv-gate-1", test_id="t-fail-1", force=False)
        )


@pytest.mark.asyncio
async def test_promote_rejects_running_or_pending_test_run(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    handler = test_setup["handler"]

    commit = ServerCommit(
        id="c-pending",
        server_id="srv-gate-1",
        message="In progress",
        manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={}),
    )
    await v_repo.save_commit(commit)

    test_run = ServerTestRun(
        id="t-running-1",
        server_id="srv-gate-1",
        commit_id="c-pending",
        status=TestRunStatus.RUNNING,
    )
    await v_repo.save_test_run(test_run)

    with pytest.raises(ValidationError, match="has status 'RUNNING'"):
        await handler.handle(
            PromoteCommitCommand(server_id="srv-gate-1", test_id="t-running-1", force=False)
        )


@pytest.mark.asyncio
async def test_promote_invalidation_guard_blocks_promotion_if_newer_run_failed(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    handler = test_setup["handler"]

    commit = ServerCommit(
        id="c-retested",
        server_id="srv-gate-1",
        message="Retested commit",
        manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={}),
    )
    await v_repo.save_commit(commit)

    now = time.time()
    # Run 1: PASSED at T0
    run_passed = ServerTestRun(
        id="t-passed-1",
        server_id="srv-gate-1",
        commit_id="c-retested",
        status=TestRunStatus.PASSED,
        created_at=now - 100,
    )
    await v_repo.save_test_run(run_passed)

    # Run 2: FAILED at T0 + 50 (newer test run for the exact same commit failed)
    run_failed = ServerTestRun(
        id="t-failed-subsequent",
        server_id="srv-gate-1",
        commit_id="c-retested",
        status=TestRunStatus.FAILED,
        failure_reason="Subsequent test failed due to mod conflict",
        created_at=now - 50,
    )
    await v_repo.save_test_run(run_failed)

    # Attempting to promote the earlier PASSED run should be blocked by the invalidation guard
    with pytest.raises(ValidationError, match="A subsequent test run .* failed for this commit"):
        await handler.handle(
            PromoteCommitCommand(server_id="srv-gate-1", test_id="t-passed-1", force=False)
        )


@pytest.mark.asyncio
async def test_promote_succeeds_when_passed_and_no_newer_failures(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    handler = test_setup["handler"]

    commit = ServerCommit(
        id="c-good",
        server_id="srv-gate-1",
        message="Good commit",
        manifest=CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=GoodServer\n"},
        ),
    )
    await v_repo.save_commit(commit)

    now = time.time()
    run = ServerTestRun(
        id="t-pass-clean",
        server_id="srv-gate-1",
        commit_id="c-good",
        status=TestRunStatus.PASSED,
        created_at=now,
    )
    await v_repo.save_test_run(run)

    res = await handler.handle(
        PromoteCommitCommand(server_id="srv-gate-1", test_id="t-pass-clean", force=False)
    )
    assert res.is_success
    assert res.details["promoted"] is True
    props_text = (test_setup["srv_dir"] / "server.properties").read_text(encoding="utf-8")
    assert props_text == "motd=GoodServer\n"


@pytest.mark.asyncio
async def test_force_promote_bypasses_failure_and_writes_activity_log(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    act_repo = test_setup["act_repo"]
    event_bus = test_setup["event_bus"]
    handler = test_setup["handler"]

    commit = ServerCommit(
        id="c-forced",
        server_id="srv-gate-1",
        message="Emergency override commit",
        manifest=CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={"server.properties": "motd=ForcedPromoteServer\n"},
        ),
    )
    await v_repo.save_commit(commit)

    test_run = ServerTestRun(
        id="t-failed-emergency",
        server_id="srv-gate-1",
        commit_id="c-forced",
        status=TestRunStatus.FAILED,
        failure_reason="Handshake timeout in test container",
    )
    await v_repo.save_test_run(test_run)

    res = await handler.handle(
        PromoteCommitCommand(
            server_id="srv-gate-1",
            test_id="t-failed-emergency",
            force=True,
            force_reason="Manually validated; urgent security patch",
            actor_id="admin-operator-42",
        )
    )

    assert res.is_success
    assert res.details["promoted"] is True
    assert res.details["forced"] is True
    assert res.details["force_reason"] == "Manually validated; urgent security patch"

    # Verify ActivityLog entry was recorded
    logs, count = await act_repo.list_by_server("srv-gate-1")
    assert count >= 1
    force_log = next(
        (log_item for log_item in logs if log_item.event_type == "versioning.force_promoted"), None
    )
    assert force_log is not None
    assert force_log.actor_id == "admin-operator-42"
    assert "force-promoted" in force_log.summary
    assert force_log.details.get("forced") is True
    assert force_log.details.get("force_reason") == "Manually validated; urgent security patch"

    # Verify DomainEvent emitted with forced=True
    event_bus.publish.assert_called()
    called_events = [call.args[0] for call in event_bus.publish.call_args_list]
    promoted_event = next(
        (e for e in called_events if isinstance(e, CommitPromotedEvent)), None
    )
    assert promoted_event is not None
    assert promoted_event.forced is True
    assert promoted_event.actor_id == "admin-operator-42"


@pytest.mark.asyncio
async def test_get_server_test_runs_query() -> None:
    v_repo = InMemoryVersioningRepository()

    for i in range(5):
        run = ServerTestRun(
            id=f"t-query-{i}",
            server_id="srv-query-1",
            commit_id="c-query-1",
            status=TestRunStatus.PASSED if i % 2 == 0 else TestRunStatus.FAILED,
            created_at=float(i * 10),
        )
        await v_repo.save_test_run(run)

    handler = GetServerTestRunsHandler(v_repo)
    result = await handler.handle(GetServerTestRunsQuery(server_id="srv-query-1", limit=3))
    assert len(result) == 3
    # Verify sorted descending by created_at
    assert result[0]["id"] == "t-query-4"
    assert result[1]["id"] == "t-query-3"
    assert result[2]["id"] == "t-query-2"


@pytest.mark.asyncio
async def test_promote_uses_atomic_text_writer_for_configs(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    fake_fs = MagicMock()

    handler = PromoteCommitHandler(
        server_repo=test_setup["server_repo"],
        versioning_repo=v_repo,
        command_bus=test_setup["command_bus"],
        test_runner=test_setup["test_runner"],
        event_bus=test_setup["event_bus"],
        activity_repo=test_setup["act_repo"],
        fs=fake_fs,
    )

    configs = {
        "server.properties": "motd=AtomicServer\n",
        "ops.json": "[]\n",
    }
    commit = ServerCommit(
        id="c-atomic",
        server_id="srv-gate-1",
        message="Atomic config writes",
        manifest=CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs=configs,
        ),
    )
    await v_repo.save_commit(commit)
    run = ServerTestRun(
        id="t-atomic",
        server_id="srv-gate-1",
        commit_id="c-atomic",
        status=TestRunStatus.PASSED,
        created_at=time.time(),
    )
    await v_repo.save_test_run(run)

    res = await handler.handle(
        PromoteCommitCommand(server_id="srv-gate-1", test_id="t-atomic", force=False)
    )

    assert res.is_success
    expected = {
        str(test_setup["srv_dir"] / rel_path): content
        for rel_path, content in configs.items()
    }
    calls = {
        call.args[0]: call.args[1]
        for call in fake_fs.write_text_atomic.call_args_list
    }
    assert calls == expected
    for call in fake_fs.write_text_atomic.call_args_list:
        assert call.kwargs.get("encoding") == "utf-8"


@pytest.mark.asyncio
async def test_promote_config_write_failure_on_second_file_raises_filesystem_error(
    test_setup,
) -> None:
    v_repo = test_setup["v_repo"]
    written: list[str] = []
    fake_fs = MagicMock()

    def write_text_atomic(path: str, content: str, encoding: str = "utf-8") -> None:
        _ = content, encoding
        written.append(path)
        if len(written) == 2:
            raise OSError("simulated disk full")

    fake_fs.write_text_atomic.side_effect = write_text_atomic

    test_setup["server_repo"].get.return_value.status = ServerStatus.STOPPED

    handler = PromoteCommitHandler(
        server_repo=test_setup["server_repo"],
        versioning_repo=v_repo,
        command_bus=test_setup["command_bus"],
        test_runner=test_setup["test_runner"],
        event_bus=test_setup["event_bus"],
        activity_repo=test_setup["act_repo"],
        fs=fake_fs,
    )

    configs = {
        "server.properties": "motd=AtomicServer\n",
        "ops.json": "[]\n",
    }
    commit = ServerCommit(
        id="c-atomic-fail",
        server_id="srv-gate-1",
        message="Atomic config write failure",
        manifest=CommitManifest(
            server_type="vanilla",
            minecraft_version="1.21.1",
            configs=configs,
        ),
    )
    await v_repo.save_commit(commit)
    run = ServerTestRun(
        id="t-atomic-fail",
        server_id="srv-gate-1",
        commit_id="c-atomic-fail",
        status=TestRunStatus.PASSED,
        created_at=time.time(),
    )
    await v_repo.save_test_run(run)

    res = await handler.handle(
        PromoteCommitCommand(server_id="srv-gate-1", test_id="t-atomic-fail", force=False)
    )
    assert res.success is False
    assert res.error_code == "PROMOTE_SWAP_ROLLED_BACK"
    assert "Filesystem write failed" in res.error
    assert "ops.json" in res.error
    assert "simulated disk full" in res.error
    assert res.details.get("rolled_back") is True

    assert written == [
        str(test_setup["srv_dir"] / "server.properties"),
        str(test_setup["srv_dir"] / "ops.json"),
    ]

    test_setup["test_runner"].cleanup_test.assert_not_called()
    assert not any(
        isinstance(call.args[0], StartServerCommand)
        for call in test_setup["command_bus"].send.call_args_list
    )
    test_setup["event_bus"].publish.assert_not_called()


@pytest.mark.asyncio
async def test_promote_fails_when_stop_not_confirmed(test_setup) -> None:
    v_repo = test_setup["v_repo"]
    commit = ServerCommit(
        id="c-stop-unconfirmed",
        server_id="srv-gate-1",
        message="Valid commit",
        manifest=CommitManifest(server_type="vanilla", minecraft_version="1.21.1", configs={}),
    )
    await v_repo.save_commit(commit)
    test_run = ServerTestRun(
        id="t-stop-unconfirmed",
        server_id="srv-gate-1",
        commit_id="c-stop-unconfirmed",
        status=TestRunStatus.PASSED,
        created_at=time.time(),
    )
    await v_repo.save_test_run(test_run)

    test_setup["server_repo"].get.return_value.status = ServerStatus.RUNNING
    test_setup["command_bus"].send = AsyncMock(
        return_value=CommandResult(success=False, error="Stop failed")
    )

    handler = PromoteCommitHandler(
        server_repo=test_setup["server_repo"],
        versioning_repo=v_repo,
        command_bus=test_setup["command_bus"],
        test_runner=test_setup["test_runner"],
        event_bus=test_setup["event_bus"],
        activity_repo=test_setup["act_repo"],
        fs=MagicMock(),
    )

    result = await handler.handle(
        PromoteCommitCommand(server_id="srv-gate-1", test_id="t-stop-unconfirmed", force=False)
    )
    assert result.success is False
    assert result.error_code == "PROMOTE_STOP_NOT_CONFIRMED"
    assert result.error_code == "PROMOTE_STOP_NOT_CONFIRMED"
