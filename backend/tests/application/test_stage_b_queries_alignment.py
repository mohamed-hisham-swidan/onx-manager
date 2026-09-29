from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.versioning.application.queries.get_server_test_runs import (
    GetServerTestRunsHandler,
    GetServerTestRunsQuery,
)
from app.modules.versioning.application.queries.get_test_evidence import (
    GetTestRunEvidenceHandler,
    GetTestRunEvidenceQuery,
)
from app.modules.versioning.application.queries.get_test_status import (
    GetTestStatusHandler,
    GetTestStatusQuery,
)
from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.value_objects import TestRunStatus


@pytest.mark.asyncio
async def test_get_server_test_runs_and_status_alignment() -> None:
    test_run = ServerTestRun(
        id="test-alignment-1",
        server_id="srv-align",
        commit_id="commit-align",
        status=TestRunStatus.PASSED,
        reserved_ram_mb=2048,
        reserved_cores=2,
        runtime_id="rt-align-99",
        test_definition_id="td-align-1",
        evidence_bundle={"schema_version": "1.0", "custom": "field"},
        artifacts_purged=False,
        operation_id="op-align-777",
    )

    mock_repo = MagicMock()
    mock_repo.list_test_runs = AsyncMock(return_value=[test_run])
    mock_repo.get_test_run = AsyncMock(return_value=test_run)

    # 1. Test GetServerTestRunsHandler
    handler_list = GetServerTestRunsHandler(versioning_repo=mock_repo)
    runs = await handler_list.handle(GetServerTestRunsQuery(server_id="srv-align"))
    assert len(runs) == 1
    run_dict = runs[0]

    assert run_dict["id"] == "test-alignment-1"
    assert run_dict["operation_id"] == "op-align-777"
    assert run_dict["reserved_ram_mb"] == 2048
    assert run_dict["reserved_cores"] == 2
    assert run_dict["runtime_id"] == "rt-align-99"
    assert run_dict["test_definition_id"] == "td-align-1"
    assert run_dict["artifacts_purged"] is False
    assert run_dict["evidence_bundle"] == {"schema_version": "1.0", "custom": "field"}

    # 2. Test GetTestStatusHandler
    handler_status = GetTestStatusHandler(versioning_repo=mock_repo)
    status_dict = await handler_status.handle(
        GetTestStatusQuery(server_id="srv-align", test_id="test-alignment-1")
    )
    assert status_dict["id"] == "test-alignment-1"
    assert status_dict["operation_id"] == "op-align-777"
    assert status_dict["reserved_ram_mb"] == 2048
    assert status_dict["reserved_cores"] == 2
    assert status_dict["runtime_id"] == "rt-align-99"
    assert status_dict["test_definition_id"] == "td-align-1"
    assert status_dict["artifacts_purged"] is False
    assert status_dict["evidence_bundle"] == {"schema_version": "1.0", "custom": "field"}


@pytest.mark.asyncio
async def test_get_test_evidence_fallback_dual_keys() -> None:
    test_run = ServerTestRun(
        id="test-fallback-1",
        server_id="srv-fb",
        commit_id="commit-fb",
        status=TestRunStatus.PASSED,
        evidence_bundle=None,  # triggers fallback synthesis
        operation_id="op-fb-888",
    )

    mock_server_repo = MagicMock()
    mock_server_repo.get = AsyncMock()

    mock_versioning_repo = MagicMock()
    mock_versioning_repo.get_test_run = AsyncMock(return_value=test_run)
    mock_versioning_repo.get_runtime = AsyncMock(return_value=None)

    handler = GetTestRunEvidenceHandler(
        server_repo=mock_server_repo,
        versioning_repo=mock_versioning_repo,
    )

    evidence = await handler.handle(
        GetTestRunEvidenceQuery(server_id="srv-fb", test_id="test-fallback-1")
    )

    assert evidence["schema_version"] == "1.0"
    assert evidence["operation_id"] == "op-fb-888"
    assert "boot_passed" in evidence["assertions"]
    assert "boot_gate_passed" in evidence["assertions"]
    assert "blamed_mod" in evidence["crash_analysis"]
    assert "suspected_culprit_mods" in evidence["crash_analysis"]
