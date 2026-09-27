from __future__ import annotations

import pytest

from app.modules.operations.domain import (
    InvalidStateTransitionError,
    Operation,
    OperationCancelledEvent,
    OperationCompletedEvent,
    OperationFailedEvent,
    OperationLogEvent,
    OperationStartedEvent,
    OperationStatus,
    OperationStepEvent,
    OperationTerminalConflictError,
    OperationType,
    StepStatus,
    TargetType,
)


def test_operation_creation_and_steps() -> None:
    op = Operation.create(
        type=OperationType.RUN_TEST.value,
        target_type=TargetType.SERVER.value,
        target_id="srv-1",
        actor_id="user-1",
        idempotency_key="idem-1",
    )
    assert op.status == OperationStatus.QUEUED
    assert op.is_active is True
    assert op.is_terminal is False
    assert op.last_event_seq == 0

    step1 = op.add_step("ADMISSION_CHECK", message_key="ops.admission")
    step2 = op.add_step("MATERIALIZE_STAGING", message_key="ops.materialize")

    assert len(op.steps) == 2
    assert step1.sequence == 1
    assert step2.sequence == 2
    assert op.current_step_id == "ADMISSION_CHECK"


def test_monotonic_event_seq() -> None:
    op = Operation.create(
        type=OperationType.RUN_TEST.value,
        target_type=TargetType.SERVER.value,
        target_id="srv-1",
    )
    seq1 = op.next_event_seq()
    seq2 = op.next_event_seq()
    seq3 = op.next_event_seq()
    assert seq1 == 1
    assert seq2 == 2
    assert seq3 == 3
    assert op.last_event_seq == 3


def test_state_machine_valid_lifecycle() -> None:
    op = Operation.create(
        type=OperationType.START_SERVER.value,
        target_type=TargetType.SERVER.value,
        target_id="srv-1",
    )
    op.add_step("STEP_1")
    op.prepare()
    assert op.status == OperationStatus.PREPARING

    op.start()
    assert op.status == OperationStatus.RUNNING
    assert op.started_at is not None

    step = op.start_step("STEP_1")
    assert step.status == StepStatus.IN_PROGRESS

    op.update_step_progress("STEP_1", 0.5)
    assert step.progress == 0.5

    op.complete_step("STEP_1")
    assert step.status == StepStatus.COMPLETED

    op.complete()
    assert op.status == OperationStatus.COMPLETED
    assert op.is_terminal is True
    assert op.finished_at is not None


def test_invalid_transitions_raise() -> None:
    op = Operation.create(
        type=OperationType.START_SERVER.value,
        target_type=TargetType.SERVER.value,
    )
    # Cannot complete from QUEUED
    with pytest.raises(InvalidStateTransitionError):
        op.complete()

    op.prepare()
    op.start()
    op.complete()

    # Terminal operations cannot transition
    with pytest.raises(OperationTerminalConflictError):
        op.fail("ERR", "Failed after complete")

    with pytest.raises(OperationTerminalConflictError):
        op.request_cancellation()


def test_cancellation_lifecycle() -> None:
    op = Operation.create(
        type=OperationType.RUN_TEST.value,
        target_type=TargetType.SERVER.value,
    )
    op.add_step("STEP_1")
    op.prepare()
    op.start()
    op.start_step("STEP_1")

    op.request_cancellation()
    assert op.status == OperationStatus.CANCEL_REQUESTED
    assert op.cancellation_requested is True

    op.cancel()
    assert op.status == OperationStatus.CANCELLED
    assert op.is_terminal is True
    assert op.get_step("STEP_1").status == StepStatus.CANCELLED


def test_retry_semantics() -> None:
    op = Operation.create(
        type=OperationType.RUN_TEST.value,
        target_type=TargetType.SERVER.value,
    )
    op.add_step("STEP_1")
    op.prepare()
    op.start()
    op.start_step("STEP_1")
    op.fail_step("STEP_1", safe_to_retry=False)
    op.fail("STEP_FAILED", "Failed in step 1")

    # Cannot retry because safe_to_retry is False
    with pytest.raises(InvalidStateTransitionError):
        op.retry()

    # Now make it safe to retry
    op.get_step("STEP_1").safe_to_retry = True
    op.retry()
    assert op.status == OperationStatus.PREPARING
    assert op.failure_code is None
    assert op.finished_at is None


def test_domain_events_instantiation() -> None:
    start_ev = OperationStartedEvent(
        operation_id="op-1",
        event_seq=1,
        type="RUN_TEST",
        target_type="server",
        target_id="srv-1",
        server_id="srv-1",
    )
    assert start_ev.event_type == "OperationStartedEvent"
    assert start_ev.event_seq == 1

    step_ev = OperationStepEvent(
        operation_id="op-1",
        event_seq=2,
        server_id="srv-1",
        step_id="MATERIALIZE_STAGING",
        sequence=2,
        status="IN_PROGRESS",
        progress=0.45,
        elapsed_ms=1204,
        safe_to_retry=True,
    )
    assert step_ev.event_type == "OperationStepEvent"
    assert step_ev.step_id == "MATERIALIZE_STAGING"
    assert step_ev.event_seq == 2

    log_ev = OperationLogEvent(
        operation_id="op-1",
        event_seq=3,
        server_id="srv-1",
        message="Extracting files",
    )
    assert log_ev.message == "Extracting files"

    comp_ev = OperationCompletedEvent(
        operation_id="op-1",
        event_seq=4,
        target_type="server",
        server_id="srv-1",
        type="RUN_TEST",
        elapsed_ms=5000,
    )
    assert comp_ev.elapsed_ms == 5000

    fail_ev = OperationFailedEvent(
        operation_id="op-1",
        event_seq=5,
        target_type="server",
        server_id="srv-1",
        type="RUN_TEST",
        failure_code="TIMEOUT",
        error_message="Timed out",
    )
    assert fail_ev.failure_code == "TIMEOUT"

    canc_ev = OperationCancelledEvent(
        operation_id="op-1",
        event_seq=6,
        target_type="server",
        server_id="srv-1",
        type="RUN_TEST",
    )
    assert canc_ev.event_seq == 6
