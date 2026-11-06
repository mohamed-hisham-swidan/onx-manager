from __future__ import annotations

import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.persistence.db import database
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.commands.prune_test_artifacts import (
    PruneTestArtifactsHandler,
)
from app.modules.versioning.application.scheduling.admission import (
    reap_stale_reservations,
)
from app.modules.versioning.domain.cleanup import TestCleanupPlan
from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.paths import resolve_test_dir
from app.modules.versioning.domain.value_objects import TestRunStatus
from app.modules.versioning.infrastructure.cleanup import execute_cleanup_plan
from app.modules.versioning.infrastructure.models import ServerTestRunModel
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

# ==============================================================================
# 1. Canonical Path Derivation & Traversal Guards (resolve_test_dir)
# ==============================================================================

def test_resolve_test_dir_canonical_derivation_and_guards() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "server-1"
        server_dir.mkdir(parents=True, exist_ok=True)

        # 1. Valid derivation: <server_dir>/.onx/tests/<test_id>
        resolved = resolve_test_dir(server_dir, "test-123")
        expected = (server_dir.resolve() / ".onx" / "tests" / "test-123").resolve()
        assert resolved == expected

        match_err = "path separators and traversal tokens are not allowed"

        # 2. Traversal via '..'
        with pytest.raises(ValueError, match=match_err):
            resolve_test_dir(server_dir, "../escaped")

        # 3. Traversal to filesystem root
        with pytest.raises(ValueError, match=match_err):
            resolve_test_dir(server_dir, "../../../../etc/passwd")

        # 4. Traversal targeting tests root itself ('.')
        with pytest.raises(ValueError, match=match_err):
            resolve_test_dir(server_dir, ".")

        # 5. Separator injection ('/' and '\\')
        with pytest.raises(ValueError, match=match_err):
            resolve_test_dir(server_dir, "sub/dir")

        with pytest.raises(ValueError, match=match_err):
            resolve_test_dir(server_dir, "sub\\dir")

        # 6. Empty test ID or whitespace
        with pytest.raises(ValueError, match="test_id cannot be empty"):
            resolve_test_dir(server_dir, "")

        with pytest.raises(ValueError, match="test_id cannot be empty"):
            resolve_test_dir(server_dir, "   ")

        # 7. Empty server_dir
        with pytest.raises(ValueError, match="server_dir cannot be empty"):
            resolve_test_dir("", "test-123")


# ==============================================================================
# 2. TestCleanupPlan.create() Authoritative Containment & Rejection Tests
# ==============================================================================

def test_cleanup_plan_server_dir_omission() -> None:
    """Omission test: verifies fail-open path inference is completely prohibited."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "srv-1"
        test_dir = resolve_test_dir(server_dir, "test-123")

        # Empty server_dir
        with pytest.raises(ValueError, match="server_dir cannot be empty"):
            TestCleanupPlan.create(
                server_id="srv-1",
                test_id="test-123",
                container_name="cnt-1",
                test_dir=test_dir,
                server_dir="",
                passed=True,
            )

        # Missing / omitted server_dir argument entirely
        with pytest.raises(TypeError):
            TestCleanupPlan.create(  # type: ignore[call-arg]
                server_id="srv-1",
                test_id="test-123",
                container_name="cnt-1",
                test_dir=test_dir,
                passed=True,
            )


def test_cleanup_plan_mismatch_and_cross_server() -> None:
    """Mismatch & Cross-Server test: rejects paths not matching canonical resolve_test_dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server_a_dir = Path(tmpdir) / "srv-a"
        server_b_dir = Path(tmpdir) / "srv-b"
        server_a_dir.mkdir()
        server_b_dir.mkdir()

        test_dir_b = resolve_test_dir(server_b_dir, "test-123")

        # Cross-server test_dir supplied with server_a_dir
        with pytest.raises(ValueError, match="Cross-server or mismatching test path detected"):
            TestCleanupPlan.create(
                server_id="srv-a",
                test_id="test-123",
                container_name="cnt-1",
                test_dir=test_dir_b,
                server_dir=server_a_dir,
                passed=True,
            )


def test_cleanup_plan_tests_root_rejection() -> None:
    """Tests-root rejection: prevents accidental mass deletion of .onx/tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "srv-1"
        tests_root = (server_dir / ".onx" / "tests").resolve()

        with pytest.raises(ValueError, match="cannot be tests root or metadata directory"):
            TestCleanupPlan.create(
                server_id="srv-1",
                test_id="tests",
                container_name="cnt-1",
                test_dir=tests_root,
                server_dir=server_dir,
                passed=True,
            )


def test_cleanup_plan_traversal_and_escaping_paths() -> None:
    """Traversal & escaping paths rejection: rejects '..' and path escapes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "srv-1"
        tests_root = server_dir / ".onx" / "tests"

        match_err = "path separators and traversal tokens are not allowed"
        # Traversal in test_id
        with pytest.raises(ValueError, match=match_err):
            TestCleanupPlan.create(
                server_id="srv-1",
                test_id="../escape",
                container_name="cnt-1",
                test_dir=tests_root / "../escape",
                server_dir=server_dir,
                passed=True,
            )


def test_cleanup_plan_test_id_mismatch() -> None:
    """Test ID mismatch: leaf name must match test_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "srv-1"
        test_dir_456 = resolve_test_dir(server_dir, "test-456")

        with pytest.raises(ValueError, match="must match test identity"):
            TestCleanupPlan.create(
                server_id="srv-1",
                test_id="test-123",
                container_name="cnt-1",
                test_dir=test_dir_456,
                server_dir=server_dir,
                passed=True,
            )


def test_cleanup_plan_no_substring_bypass() -> None:
    """Structural validation rejects paths containing .onx and tests but outside container."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_base = Path(tmpdir) / "not.onx" / "tests" / "test-123"
        fake_base.mkdir(parents=True, exist_ok=True)

        err_match = "Test directory must be directly inside '.onx/tests' container"
        with pytest.raises(ValueError, match=err_match):
            TestCleanupPlan.create(
                server_id="srv-1",
                test_id="test-123",
                container_name="cnt-1",
                test_dir=fake_base,
                server_dir=Path(tmpdir) / "srv-1",
                passed=True,
            )


# ==============================================================================
# 3. Pure Domain Cleanup Plan Lifecycle Tests
# ==============================================================================

def test_cleanup_plan_pure_lifecycle_retention() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "srv-1"
        test_dir_pass = resolve_test_dir(server_dir, "test-pass")
        test_dir_fail = resolve_test_dir(server_dir, "test-fail")
        test_dir_cancel = resolve_test_dir(server_dir, "test-cancel")

        # 1. Passed test: purges artifacts immediately
        plan_pass = TestCleanupPlan.create(
            server_id="srv-1",
            test_id="test-pass",
            container_name="cnt-pass",
            test_dir=test_dir_pass,
            server_dir=server_dir,
            passed=True,
            cancelled=False,
            retention_hours=24.0,
        )
        assert plan_pass.remove_container is True
        assert plan_pass.purge_artifacts is True
        assert plan_pass.reason == "passed_purge"

        # 2. Failed test with retention: retains artifacts
        plan_fail = TestCleanupPlan.create(
            server_id="srv-1",
            test_id="test-fail",
            container_name="cnt-fail",
            test_dir=test_dir_fail,
            server_dir=server_dir,
            passed=False,
            cancelled=False,
            retention_hours=24.0,
        )
        assert plan_fail.remove_container is True
        assert plan_fail.purge_artifacts is False
        assert plan_fail.reason == "failed_retention"

        # 3. Cancelled test with retention: retains artifacts
        plan_cancel = TestCleanupPlan.create(
            server_id="srv-1",
            test_id="test-cancel",
            container_name="cnt-cancel",
            test_dir=test_dir_cancel,
            server_dir=server_dir,
            passed=False,
            cancelled=True,
            retention_hours=24.0,
        )
        assert plan_cancel.remove_container is True
        assert plan_cancel.purge_artifacts is False
        assert plan_cancel.reason == "cancelled_retention"

        # 4. Failed test with zero retention: purges artifacts
        plan_zero_ret = TestCleanupPlan.create(
            server_id="srv-1",
            test_id="test-fail",
            container_name="cnt-fail",
            test_dir=test_dir_fail,
            server_dir=server_dir,
            passed=False,
            cancelled=False,
            retention_hours=0.0,
        )
        assert plan_zero_ret.purge_artifacts is True


# ==============================================================================
# 4. Infrastructure Teardown Execution
# ==============================================================================

@pytest.mark.asyncio
async def test_execute_cleanup_plan_physical_actions() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        server_dir = Path(tmpdir) / "srv-1"
        test_dir = resolve_test_dir(server_dir, "t-1")
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "server.properties").write_text("motd=test")

        plan = TestCleanupPlan(
            test_id="t-1",
            server_id="srv-1",
            test_dir=test_dir,
            container_name="c-1",
            remove_container=True,
            purge_artifacts=True,
            retention_hours=0.0,
            reason="passed_purge",
        )

        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=0)

            result = await execute_cleanup_plan(plan)
            assert result.container_removed is True
            assert result.artifacts_purged is True
            assert result.error is None
            assert not test_dir.exists()


@pytest.mark.asyncio
async def test_execute_cleanup_plan_docker_failure_sets_container_removed_false() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "t-fail"
        test_dir.mkdir()

        plan = TestCleanupPlan(
            test_id="t-fail",
            server_id="srv-1",
            test_dir=test_dir,
            container_name="c-fail",
            remove_container=True,
            purge_artifacts=False,
            retention_hours=0.0,
            reason="failed_test",
        )

        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=1, stderr="no such container")

            result = await execute_cleanup_plan(plan)
            assert result.container_removed is False
            assert result.error is not None
            assert "no such container" in result.error


# ==============================================================================
# 5. Missing Server Row / NULL root_path Safe Skip Verification (Reap & Prune)
# ==============================================================================

@pytest.mark.asyncio
async def test_reap_stale_reservations_missing_server_or_null_root_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifies reap_stale_reservations skips safely without path guessing."""
    now = datetime.now(UTC)
    caplog.set_level(logging.WARNING)

    async with database.session_factory() as session:
        # Server with NULL root_path
        server_null = ServerModel(
            id="srv-null-root",
            name="Null Root Server",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=None,
            deployment_host="127.0.0.1",
            port=25565,
        )
        session.add(server_null)

        repo = SQLVersioningRepository(session)
        # Test run with missing server
        run_missing_srv = ServerTestRun(
            id="tr-missing-srv",
            server_id="srv-non-existent",
            commit_id="c-1",
            status=TestRunStatus.FAILED,
            failure_reason="SERVER_CRASH",
            created_at=now - timedelta(hours=30),
            artifacts_purged=False,
        )
        await repo.save_test_run(run_missing_srv)

        # Test run with NULL root_path server
        run_null_root = ServerTestRun(
            id="tr-null-root",
            server_id="srv-null-root",
            commit_id="c-2",
            status=TestRunStatus.FAILED,
            failure_reason="SERVER_CRASH",
            created_at=now - timedelta(hours=30),
            artifacts_purged=False,
        )
        await repo.save_test_run(run_null_root)
        await session.commit()

    # Execute reap_stale_reservations
    async with database.session_factory() as session:
        await reap_stale_reservations(session, at=now, artifact_retention_hours=24)
        await session.commit()

    # Verify warnings were logged and no exceptions were raised
    warnings = [rec.message for rec in caplog.records if rec.levelno >= logging.WARNING]
    expected_missing = (
        "Skipping artifact cleanup for test tr-missing-srv: "
        "server srv-non-existent missing or root_path is NULL"
    )
    expected_null = (
        "Skipping artifact cleanup for test tr-null-root: "
        "server srv-null-root missing or root_path is NULL"
    )
    assert any(expected_missing in msg for msg in warnings)
    assert any(expected_null in msg for msg in warnings)

    # Verify both test runs are marked artifacts_purged=True to prevent infinite retry loops
    async with database.session_factory() as session:
        m_missing = await session.get(ServerTestRunModel, "tr-missing-srv")
        m_null = await session.get(ServerTestRunModel, "tr-null-root")
        assert m_missing.artifacts_purged is True
        assert m_null.artifacts_purged is True


@pytest.mark.asyncio
async def test_prune_test_artifacts_missing_server_or_null_root_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Verifies execute_pruning skips safely without path guessing."""
    now = datetime.now(UTC)
    caplog.set_level(logging.WARNING)

    async with database.session_factory() as session:
        # Server with NULL root_path
        server_null = ServerModel(
            id="srv-prune-null",
            name="Null Root Server Prune",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=None,
            deployment_host="127.0.0.1",
            port=25566,
        )
        session.add(server_null)

        repo = SQLVersioningRepository(session)
        # Test run with missing server
        run_missing = ServerTestRun(
            id="tr-prune-missing",
            server_id="srv-prune-nonexistent",
            commit_id="c-3",
            status=TestRunStatus.FAILED,
            failure_reason="SERVER_CRASH",
            created_at=now - timedelta(hours=30),
            artifacts_purged=False,
        )
        await repo.save_test_run(run_missing)

        # Test run with NULL root_path server
        run_null = ServerTestRun(
            id="tr-prune-null",
            server_id="srv-prune-null",
            commit_id="c-4",
            status=TestRunStatus.CANCELLED,
            failure_reason="Discarded by user",
            created_at=now - timedelta(hours=30),
            artifacts_purged=False,
        )
        await repo.save_test_run(run_null)
        await session.commit()

    # Execute pruning
    async with database.session_factory() as session:
        result = await PruneTestArtifactsHandler.execute_pruning(
            session=session,
            retention_hours=24,
            now=now,
        )
        await session.commit()

    assert result.success is True
    assert result.details["pruned_count"] == 2

    # Verify warnings were logged
    warnings = [rec.message for rec in caplog.records if rec.levelno >= logging.WARNING]
    expected_missing = (
        "Skipping artifact cleanup for test tr-prune-missing: "
        "server srv-prune-nonexistent missing or root_path is NULL"
    )
    expected_null = (
        "Skipping artifact cleanup for test tr-prune-null: "
        "server srv-prune-null missing or root_path is NULL"
    )
    assert any(expected_missing in msg for msg in warnings)
    assert any(expected_null in msg for msg in warnings)

    # Verify both test runs are marked artifacts_purged=True
    async with database.session_factory() as session:
        m_missing = await session.get(ServerTestRunModel, "tr-prune-missing")
        m_null = await session.get(ServerTestRunModel, "tr-prune-null")
        assert m_missing.artifacts_purged is True
        assert m_null.artifacts_purged is True
