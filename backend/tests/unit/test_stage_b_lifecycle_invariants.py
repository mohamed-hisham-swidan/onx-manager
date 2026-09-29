from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.value_objects import TestRunStatus
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
)


def test_server_test_run_terminal_guards_raise_value_error() -> None:
    now = datetime.now(UTC)
    run = ServerTestRun(
        id="test-terminal-1",
        server_id="srv-1",
        commit_id="commit-1",
        status=TestRunStatus.PASSED,
        created_at=now,
    )
    assert run.is_terminal is True

    # Calling mark_passed, mark_failed, or mark_cancelled on terminal run raises ValueError
    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        run.mark_passed()

    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        run.mark_failed("Another failure")

    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        run.mark_cancelled()

    # Now verify FAILED terminal run
    run_failed = ServerTestRun(
        id="test-terminal-2",
        server_id="srv-1",
        commit_id="commit-1",
        status=TestRunStatus.FAILED,
        created_at=now,
    )
    assert run_failed.is_terminal is True
    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        run_failed.mark_passed()

    # Now verify CANCELLED terminal run
    run_cancelled = ServerTestRun(
        id="test-terminal-3",
        server_id="srv-1",
        commit_id="commit-1",
        status=TestRunStatus.CANCELLED,
        created_at=now,
    )
    assert run_cancelled.is_terminal is True
    with pytest.raises(ValueError, match="Cannot transition terminal test run"):
        run_cancelled.mark_failed("late failure")


def test_server_test_run_non_terminal_transitions() -> None:
    now = datetime.now(UTC)
    run = ServerTestRun(
        id="test-non-term",
        server_id="srv-1",
        commit_id="commit-1",
        status=TestRunStatus.RUNNING,
        created_at=now,
    )
    assert run.is_terminal is False

    # Can transition to PASSED
    run.mark_passed(log_output="Server started successfully")
    assert run.status == TestRunStatus.PASSED
    assert run.is_terminal is True
    assert run.log_output == "Server started successfully"

    # Verify expires_at can be stamped
    run.expires_at = now + timedelta(hours=24.0)
    assert run.expires_at is not None
    assert run.expires_at > now


@pytest.mark.asyncio
async def test_atomic_persistence_persists_runtime_id_and_benignly_skips_terminal_rows() -> None:
    runner = DockerTestExecutionRunner()
    handle = MagicMock()
    handle.test_id = "test-atomic-1"
    handle.runtime_id = "rt-12345678"
    handle.status = TestRunStatus.PASSED

    # 1. Normal transition: rowcount == 1
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_cursor)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = mock_session
    mock_factory = MagicMock(return_value=mock_ctx)

    with patch("app.core.persistence.db.database._session_factory", mock_factory):
        await runner._persist_test_outcome(
            test_id=handle.test_id,
            passed=True,
            failure_reason=None,
            log_output="done",
            runtime_id=handle.runtime_id,
            evidence_bundle={"schema_version": "1.0"},
        )
        assert mock_session.commit.called

    # 2. Benign skip: rowcount == 0 (already terminal)
    mock_cursor_skip = MagicMock()
    mock_cursor_skip.rowcount = 0
    mock_session_skip = AsyncMock()
    mock_session_skip.execute = AsyncMock(return_value=mock_cursor_skip)
    mock_ctx_skip = AsyncMock()
    mock_ctx_skip.__aenter__.return_value = mock_session_skip
    mock_factory_skip = MagicMock(return_value=mock_ctx_skip)

    with patch("app.core.persistence.db.database._session_factory", mock_factory_skip):
        # Does not raise, logs warning and commits benignly
        await runner._persist_test_outcome(
            test_id=handle.test_id,
            passed=False,
            failure_reason="Late failure",
            log_output="late logs",
            runtime_id=handle.runtime_id,
            evidence_bundle=None,
        )
        assert mock_session_skip.commit.called
