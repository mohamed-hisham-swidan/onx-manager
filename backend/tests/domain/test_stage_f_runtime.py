"""Stage F Runtime Domain Entity and Attach Model Test Suite.

Verifies:
- Runtime construction, immutability of commit_id, and lifecycle transitions
- Runtime attach model to ServerTestRun (1:1 relationship via runtime_id)
"""

import pytest

from app.modules.versioning.domain.entities import Runtime, ServerTestRun
from app.modules.versioning.domain.value_objects import RuntimeStatus, TestRunStatus


def test_runtime_construction_and_defaults() -> None:
    rt = Runtime(
        id="rt-001",
        commit_id="commit-abc1234",
        server_id="srv-1",
    )
    assert rt.id == "rt-001"
    assert rt.commit_id == "commit-abc1234"
    assert rt.server_id == "srv-1"
    assert rt.provider_type == "docker"
    assert rt.status == RuntimeStatus.STARTING
    assert rt.container_id is None
    assert rt.pid is None
    assert rt.port is None
    assert rt.exit_code is None
    assert rt.oom_killed is False
    assert rt.started_at is not None
    assert rt.stopped_at is None


def test_runtime_commit_id_immutability() -> None:
    rt = Runtime(
        id="rt-002",
        commit_id="commit-abc1234",
    )
    with pytest.raises(ValueError, match="Runtime commit_id is immutable"):
        rt.commit_id = "commit-diff5678"


def test_runtime_rejects_mutable_references() -> None:
    with pytest.raises(ValueError, match="Runtime cannot bind directly to a mutable branch"):
        Runtime(id="rt-003", commit_id="branch:develop")

    with pytest.raises(ValueError, match="Runtime cannot bind directly to a mutable branch"):
        Runtime(id="rt-004", commit_id="refs/heads/main")


def test_runtime_lifecycle_transitions() -> None:
    rt = Runtime(
        id="rt-005",
        commit_id="commit-1111",
    )
    assert rt.status == RuntimeStatus.STARTING

    rt.mark_running(container_id="cont-123", pid=4567, port=25565)
    assert rt.status == RuntimeStatus.RUNNING
    assert rt.container_id == "cont-123"
    assert rt.pid == 4567
    assert rt.port == 25565

    rt.mark_terminated(exit_code=0)
    assert rt.status == RuntimeStatus.TERMINATED
    assert rt.exit_code == 0
    assert rt.stopped_at is not None


def test_runtime_crashed_transition() -> None:
    rt = Runtime(
        id="rt-006",
        commit_id="commit-2222",
    )
    rt.mark_running(container_id="cont-456")
    rt.mark_crashed(exit_code=137, oom_killed=True)
    assert rt.status == RuntimeStatus.CRASHED
    assert rt.exit_code == 137
    assert rt.oom_killed is True
    assert rt.stopped_at is not None


def test_runtime_attach_model_to_server_test_run() -> None:
    rt = Runtime(
        id="rt-attach-1",
        commit_id="commit-3333",
        server_id="srv-attach",
    )
    run = ServerTestRun(
        id="test-run-attach-1",
        server_id="srv-attach",
        commit_id="commit-3333",
        status=TestRunStatus.RUNNING,
        runtime_id=rt.id,
        test_definition_id="td-custom-1",
    )
    assert run.runtime_id == rt.id
    assert run.test_definition_id == "td-custom-1"
    assert run.artifacts_purged is False
    assert run.evidence_bundle is None
