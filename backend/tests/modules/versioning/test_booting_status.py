from __future__ import annotations

from app.modules.versioning.application.scheduling.admission import _ACTIVE_STATUSES
from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.value_objects import (
    PlacementMode,
    TestRunStatus,
)


def test_test_run_status_booting_enum() -> None:
    assert TestRunStatus.BOOTING == "BOOTING"
    assert TestRunStatus.BOOTING in _ACTIVE_STATUSES
    assert _ACTIVE_STATUSES == (
        TestRunStatus.PENDING,
        TestRunStatus.BOOTING,
        TestRunStatus.RUNNING,
    )


def test_server_test_run_mark_booting() -> None:
    run = ServerTestRun(
        id="run-12345",
        server_id="srv-12345",
        commit_id="c" * 40,
        status=TestRunStatus.PENDING,
        bot_count=1,
        placement_mode=PlacementMode.SIDECAR,
    )
    assert run.status == TestRunStatus.PENDING

    run.mark_booting()
    assert run.status == TestRunStatus.BOOTING

    run.mark_running()
    assert run.status == TestRunStatus.RUNNING

    run.mark_passed()
    assert run.status == TestRunStatus.PASSED
