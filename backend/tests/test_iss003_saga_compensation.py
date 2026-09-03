from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.core.saga import SagaOrchestrator, SagaStatus, SagaStep, SagaStepStatus


@pytest.mark.asyncio
async def test_all_compensation_steps_succeed() -> None:
    """ISS-003: When compensation succeeds, status is COMPENSATED."""
    orchestrator = SagaOrchestrator()

    comp1 = MagicMock()
    step1 = SagaStep(name="step1", forward=MagicMock(), compensate=comp1)
    step2 = SagaStep(
        name="step2",
        forward=MagicMock(side_effect=RuntimeError("Forward boom")),
        compensate=MagicMock(),
    )

    saga = await orchestrator.create_saga("test_saga", [step1, step2])
    result = await orchestrator.execute(saga.saga_id)

    assert result.status == SagaStatus.COMPENSATED
    assert comp1.called
    assert step1.status == SagaStepStatus.COMPENSATED


@pytest.mark.asyncio
async def test_compensation_step_raises_sets_failed() -> None:
    """ISS-003: When compensation raises, status is FAILED and errors are recorded."""
    orchestrator = SagaOrchestrator()

    failing_comp = MagicMock(side_effect=RuntimeError("Compensation exploded"))
    step1 = SagaStep(name="step1", forward=MagicMock(), compensate=failing_comp)
    step2 = SagaStep(
        name="step2",
        forward=MagicMock(side_effect=RuntimeError("Forward boom")),
        compensate=MagicMock(),
    )

    saga = await orchestrator.create_saga("test_saga_fail", [step1, step2])
    result = await orchestrator.execute(saga.saga_id)

    assert result.status == SagaStatus.FAILED, f"Expected FAILED but got {result.status}"
    assert "Compensation exploded" in (result.error or "")
    assert step1.status == SagaStepStatus.FAILED
    assert step1.error == "Compensation exploded"


@pytest.mark.asyncio
async def test_failed_at_step_itself_is_never_compensated() -> None:
    """ISS-003: The step that failed during forward execution is never compensated."""
    orchestrator = SagaOrchestrator()

    comp1 = MagicMock()
    failed_step_comp = MagicMock()

    step1 = SagaStep(name="step1", forward=MagicMock(), compensate=comp1)
    step2 = SagaStep(
        name="step2",
        forward=MagicMock(side_effect=RuntimeError("Step 2 failed")),
        compensate=failed_step_comp,
    )

    saga = await orchestrator.create_saga("test_saga_skip_failed", [step1, step2])
    result = await orchestrator.execute(saga.saga_id)

    assert comp1.called
    assert not failed_step_comp.called
    assert result.status == SagaStatus.COMPENSATED
