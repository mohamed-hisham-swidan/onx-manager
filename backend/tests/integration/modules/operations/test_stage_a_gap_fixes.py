"""Stage A gap-fix regressions (RECON-verified gaps, approved design only).

Covers, with focused tests and no docker dependency:
1. RUN_TEST executor registration -> cooperative cancel (no orphaned run
   while the Operation claims CANCELLED).
2. ``record_step_progress()`` persistence + events (+ runner best-effort ping).
3. Designed per-operation timeout path (``_handle_timeout`` + watcher +
   cancel/timeout precedence).
4. Startup QUEUED policy: PURGE default exact, RE_DISPATCH preservation,
   unknown-value fallback.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from app.modules.operations.application.services.executor import (
    OperationRecoveryReconciler,
)
from app.modules.operations.application.services.operation_service import (
    OperationService,
    get_operation_service,
    reset_operation_service,
)
from app.modules.operations.domain.enums import OperationStatus
from app.modules.versioning.domain.value_objects import TestRunStatus
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestHandle,
)


class _FakeBus:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, evt) -> None:
        self.events.append(evt)


RUN_TEST_STEPS = [
    {"step_id": "ADMISSION_CHECK", "sequence": 1},
    {"step_id": "MATERIALIZE_STAGING", "sequence": 2, "safe_to_retry": True},
    {"step_id": "BOOTSTRAP_VERIFY", "sequence": 3, "safe_to_retry": True},
    {"step_id": "SYNTHETIC_PLAYER", "sequence": 4, "safe_to_retry": True},
    {"step_id": "CLEANUP", "sequence": 5},
]


async def _make_op(svc: OperationService, **kwargs):
    kwargs.setdefault("type", "RUN_TEST")
    kwargs.setdefault("target_type", "server")
    kwargs.setdefault("target_id", "srv-gap-1")
    kwargs.setdefault("initial_steps", [dict(s) for s in RUN_TEST_STEPS])
    return await svc.create_operation(**kwargs)


async def _cleanup_global_service(svc: OperationService) -> None:
    ex = svc.executor
    stray = [
        t
        for t in list(ex._running_tasks.values()) + list(ex._timeout_watchers.values())
        if not t.done()
    ]
    for t in stray:
        t.cancel()
    if stray:
        await asyncio.sleep(0)
    ex._running_tasks.clear()
    ex._timeout_watchers.clear()
    reset_operation_service()


# ── Fix 1: cooperative cancellation ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_without_registered_task_completes_immediately():
    """No executor task -> immediate CANCELLED (pre-existing behavior kept)."""
    svc = OperationService(event_bus=_FakeBus())
    op = await _make_op(svc)

    assert svc.executor.cancel_task(op.id) is False
    done = await svc.request_cancellation(op.id)
    assert done.status == OperationStatus.CANCELLED


@pytest.mark.asyncio
async def test_registered_task_takes_cooperative_cancel_path():
    """Registered task -> CANCEL_REQUESTED, task cancelled, worker confirms."""
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    op = await _make_op(svc)
    await svc.start_step(op.id, "ADMISSION_CHECK")

    task = asyncio.create_task(asyncio.sleep(30))
    svc.executor.register_task(op.id, task)

    requested = await svc.request_cancellation(op.id)
    assert requested.status == OperationStatus.CANCEL_REQUESTED
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()

    confirmed = await svc.confirm_cancellation(op.id)
    assert confirmed.status == OperationStatus.CANCELLED
    # Worker confirmation is idempotent.
    confirmed_again = await svc.confirm_cancellation(op.id)
    assert confirmed_again.status == OperationStatus.CANCELLED


@pytest.mark.asyncio
async def test_runner_cleanup_cancelled_path_marks_cancelled(tmp_path):
    """cleanup_test(cancelled=True): container removed, op CANCELLED not FAILED."""
    reset_operation_service()
    bus = _FakeBus()
    svc = get_operation_service(event_bus=bus)
    try:
        op = await _make_op(svc)
        await svc.start_step(op.id, "SYNTHETIC_PLAYER")

        # Mirror production: verification task registered, user cancels,
        # worker (cleanup_test) finishes and confirms.
        worker_task = asyncio.create_task(asyncio.sleep(30))
        svc.executor.register_task(op.id, worker_task)
        requested = await svc.request_cancellation(op.id)
        assert requested.status == OperationStatus.CANCEL_REQUESTED
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task

        test_dir = tmp_path / "t-cancel"
        test_dir.mkdir()
        (test_dir / "debug.log").write_text("keep me")
        handle = TestHandle(
            test_id="t-cancel",
            server_id="srv-gap-1",
            container_name="onx-test-missing-xyz",
            test_dir=str(test_dir),
            sidecar_runner=None,
            status=TestRunStatus.FAILED,
            operation_id=op.id,
        )

        runner = DockerTestExecutionRunner()
        await runner.cleanup_test(handle, passed=False, cancelled=True)

        reloaded = await svc.get_operation(op.id)
        assert reloaded.status == OperationStatus.CANCELLED
        assert reloaded.failure_code is None
        cleanup_step = reloaded.get_step("CLEANUP")
        assert cleanup_step is not None
        # Dir retained for post-cancel debugging (passed=False + retention).
        assert (test_dir / "debug.log").exists()
    finally:
        await _cleanup_global_service(svc)


@pytest.mark.asyncio
async def test_runner_cleanup_normal_paths_unchanged(tmp_path):
    """Non-cancel cleanup still COMPLETES on pass and TEST_FAILED on fail."""
    reset_operation_service()
    bus = _FakeBus()
    svc = get_operation_service(event_bus=bus)
    try:
        runner = DockerTestExecutionRunner()

        op_ok = await _make_op(svc)
        await svc.start_step(op_ok.id, "SYNTHETIC_PLAYER")
        dir_ok = tmp_path / "t-ok"
        dir_ok.mkdir()
        handle_ok = TestHandle(
            test_id="t-ok",
            server_id="srv-gap-1",
            container_name="onx-test-missing-xyz",
            test_dir=str(dir_ok),
            sidecar_runner=None,
            status=TestRunStatus.PASSED,
            operation_id=op_ok.id,
        )
        await runner.cleanup_test(handle_ok, passed=True)
        assert (await svc.get_operation(op_ok.id)).status == OperationStatus.COMPLETED
        assert not dir_ok.exists()

        op_bad = await _make_op(svc)
        await svc.start_step(op_bad.id, "SYNTHETIC_PLAYER")
        dir_bad = tmp_path / "t-bad"
        dir_bad.mkdir()
        handle_bad = TestHandle(
            test_id="t-bad",
            server_id="srv-gap-1",
            container_name="onx-test-missing-xyz",
            test_dir=str(dir_bad),
            sidecar_runner=None,
            status=TestRunStatus.FAILED,
            operation_id=op_bad.id,
        )
        await runner.cleanup_test(handle_bad, passed=False)
        reloaded_bad = await svc.get_operation(op_bad.id)
        assert reloaded_bad.status == OperationStatus.FAILED
        assert reloaded_bad.failure_code == "TEST_FAILED"
    finally:
        await _cleanup_global_service(svc)


# ── Fix 2: record_step_progress ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_step_progress_persists_and_emits():
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    op = await _make_op(svc)
    await svc.start_step(op.id, "SYNTHETIC_PLAYER")
    seq_before = (await svc.get_operation(op.id)).last_event_seq

    step = await svc.record_step_progress(
        op.id, "SYNTHETIC_PLAYER", 0.4, context={"spawn_ok": 2}
    )
    assert step.progress == 0.4
    assert step.context["spawn_ok"] == 2

    reloaded = await svc.get_operation(op.id)
    assert reloaded.get_step("SYNTHETIC_PLAYER").progress == 0.4
    assert reloaded.last_event_seq == seq_before + 1
    assert bus.events[-1].event_type == "OperationStepEvent"
    assert bus.events[-1].progress == 0.4


@pytest.mark.asyncio
async def test_runner_report_progress_is_best_effort():
    runner = DockerTestExecutionRunner()
    # No operation id -> silent no-op, never raises.
    await runner._report_progress(None, "SYNTHETIC_PLAYER", 0.5)
    # Unknown operation id -> swallowed to debug, never raises.
    await runner._report_progress("op-does-not-exist", "SYNTHETIC_PLAYER", 0.5)


# ── Fix 3: timeout path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_timeout_commits_timed_out():
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    op = await _make_op(svc, timeout_seconds=600)
    await svc.start_step(op.id, "BOOTSTRAP_VERIFY")

    won = await svc.executor._handle_timeout(op.id)
    assert won is True

    reloaded = await svc.get_operation(op.id)
    assert reloaded.status == OperationStatus.TIMED_OUT
    assert reloaded.failure_code == "OPERATION_TIMEOUT"
    assert reloaded.error_message == "Operation exceeded configured timeout limit"
    assert bus.events[-1].event_type == "OperationFailedEvent"
    assert bus.events[-1].event_seq == reloaded.last_event_seq

    # Second attempt: already terminal, yields.
    assert await svc.executor._handle_timeout(op.id) is False


@pytest.mark.asyncio
async def test_timeout_yields_to_cancellation():
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    op = await _make_op(svc)
    await svc.start_step(op.id, "BOOTSTRAP_VERIFY")

    task = asyncio.create_task(asyncio.sleep(30))
    svc.executor.register_task(op.id, task)
    try:
        requested = await svc.request_cancellation(op.id)
        assert requested.status == OperationStatus.CANCEL_REQUESTED

        won = await svc.executor._handle_timeout(op.id)
        assert won is False
        assert (await svc.get_operation(op.id)).status == OperationStatus.CANCEL_REQUESTED
    finally:
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_timeout_watcher_fires_on_running_operation():
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    op = await _make_op(svc)
    await svc.start_step(op.id, "BOOTSTRAP_VERIFY")

    watcher = svc.executor.schedule_timeout_watch(op.id, 0.05)
    assert watcher is not None
    # Await the watcher itself (no concurrent polling: the isolated test DB
    # is a single shared connection).
    await asyncio.wait_for(watcher, timeout=5)
    reloaded = await svc.get_operation(op.id)
    assert reloaded.status == OperationStatus.TIMED_OUT
    assert op.id not in svc.executor._timeout_watchers


@pytest.mark.asyncio
async def test_timeout_watch_ignored_for_non_positive_budget():
    svc = OperationService(event_bus=_FakeBus())
    assert svc.executor.schedule_timeout_watch("op-x", 0) is None
    assert svc.executor.schedule_timeout_watch("op-x", -5) is None
    assert svc.executor.schedule_timeout_watch("op-x", None) is None


# ── Fix 4: startup QUEUED policy ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_startup_reconciler_purge_default_exact(monkeypatch):
    monkeypatch.delenv("ONX_OPERATION_STARTUP_QUEUE_POLICY", raising=False)
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    queued = await _make_op(svc)
    running = await _make_op(svc)
    await svc.start_step(running.id, "ADMISSION_CHECK")

    await OperationRecoveryReconciler(event_bus=bus).reconcile_on_startup()

    q = await svc.get_operation(queued.id)
    assert q.status == OperationStatus.FAILED
    assert q.failure_code == "QUEUE_PURGED_ON_RESTART"
    assert q.error_message == (
        "Operation was queued when backend restarted and was purged "
        "per default startup policy"
    )
    r = await svc.get_operation(running.id)
    assert r.status == OperationStatus.FAILED
    assert r.failure_code == "PROCESS_TERMINATED"
    assert r.error_message == (
        "Operation execution aborted due to unexpected backend termination"
    )


@pytest.mark.asyncio
async def test_startup_reconciler_redispatch_preserves_queued(monkeypatch):
    monkeypatch.setenv("ONX_OPERATION_STARTUP_QUEUE_POLICY", "RE_DISPATCH")
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    queued = await _make_op(svc)
    running = await _make_op(svc)
    await svc.start_step(running.id, "ADMISSION_CHECK")

    await OperationRecoveryReconciler(event_bus=bus).reconcile_on_startup()

    assert (await svc.get_operation(queued.id)).status == OperationStatus.QUEUED
    r = await svc.get_operation(running.id)
    assert r.status == OperationStatus.FAILED
    assert r.failure_code == "PROCESS_TERMINATED"


@pytest.mark.asyncio
async def test_startup_reconciler_unknown_policy_falls_back_to_purge(monkeypatch):
    monkeypatch.setenv("ONX_OPERATION_STARTUP_QUEUE_POLICY", "BOGUS_VALUE")
    bus = _FakeBus()
    svc = OperationService(event_bus=bus)
    queued = await _make_op(svc)

    await OperationRecoveryReconciler(event_bus=bus).reconcile_on_startup()

    q = await svc.get_operation(queued.id)
    assert q.status == OperationStatus.FAILED
    assert q.failure_code == "QUEUE_PURGED_ON_RESTART"


# ── Handler timeout budget (Fix 3 companion) ─────────────────────────────


@pytest.mark.asyncio
async def test_run_isolated_test_timeout_budget_covers_full_run(tmp_path):
    """RUN_TEST op timeout = boot + duration + watchdog (no 600s false-fire)."""
    from app.modules.versioning.application.commands.run_isolated_test import (
        RunIsolatedTestCommand,
        RunIsolatedTestHandler,
    )

    reset_operation_service()
    bus = _FakeBus()
    svc = get_operation_service(event_bus=bus)
    captured: dict = {}
    try:
        server = SimpleNamespace(
            server_id="srv-gap-1",
            server_type="vanilla",
            minecraft_version="1.21.1",
            deployment=SimpleNamespace(server_dir=str(tmp_path)),
            bot_verification_settings=None,
            startup_timeout_seconds=None,
        )
        commit = SimpleNamespace(
            id="commit-1",
            server_id="srv-gap-1",
            manifest=SimpleNamespace(
                server_type="vanilla",
                minecraft_version="1.21.1",
                configs={},
                mods=[],
            ),
        )

        class _ServerRepo:
            async def get(self, _sid):
                return server

        class _VersioningRepo:
            async def list_commits(self, _sid, limit=1):
                return [commit][:limit]

            async def get_commit(self, _cid):
                return commit

            async def get_test_definition(self, _did):
                return None

            async def save_test_run(self, run):
                captured["run"] = run
                return run

        class _Runner:
            async def run_test(self, spec):
                captured["spec"] = spec
                return TestHandle(
                    test_id=spec.test_id,
                    server_id=spec.server_id,
                    container_name="onx-test-x",
                    test_dir=str(tmp_path),
                    sidecar_runner=None,
                    status=TestRunStatus.BOOTING,
                    operation_id=spec.operation_id,
                )

            async def cleanup_test(self, handle, passed=True):
                captured["cleanup_handle"] = handle
                captured["cleanup_passed"] = passed
                return None

        handler = RunIsolatedTestHandler(
            server_repo=_ServerRepo(),
            versioning_repo=_VersioningRepo(),
            test_runner=_Runner(),
            event_bus=bus,
        )
        res = await handler.handle(RunIsolatedTestCommand(server_id="srv-gap-1"))
        assert res.success is True

        op = await svc.get_operation(res.details["operation_id"])
        # defaults: boot 120 (live test_boot_timeout) + 15m duration + 5m watchdog
        assert op.timeout_seconds == 120 + 15 * 60 + 5 * 60
        assert captured["spec"].operation_id == op.id
    finally:
        await _cleanup_global_service(svc)
