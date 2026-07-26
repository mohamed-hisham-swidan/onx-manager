import pytest

from app.core.saga import (
    SagaOrchestrator,
    SagaStatus,
    SagaStep,
    SagaStepStatus,
)


@pytest.mark.asyncio
class TestSagaOrchestrator:
    async def test_execute_all_steps_successfully(self) -> None:
        orchestrator = SagaOrchestrator()
        execution: list[str] = []

        steps = [
            SagaStep(name="step1", forward=lambda: execution.append("s1")),
            SagaStep(name="step2", forward=lambda: execution.append("s2")),
            SagaStep(name="step3", forward=lambda: execution.append("s3")),
        ]

        instance = await orchestrator.create_saga("test-saga", steps)
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.COMPLETED
        assert execution == ["s1", "s2", "s3"]

    async def test_compensation_on_failure(self) -> None:
        orchestrator = SagaOrchestrator()
        execution: list[str] = []
        compensation: list[str] = []

        steps = [
            SagaStep(
                name="step1",
                forward=lambda: execution.append("s1"),
                compensate=lambda: compensation.append("c1"),
            ),
            SagaStep(
                name="step2",
                forward=lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                compensate=lambda: compensation.append("c2"),
            ),
            SagaStep(
                name="step3",
                forward=lambda: execution.append("s3"),
                compensate=lambda: compensation.append("c3"),
            ),
        ]

        instance = await orchestrator.create_saga("failing-saga", steps)
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.COMPENSATED
        assert execution == ["s1"]
        assert compensation == ["c2", "c1"]

    async def test_compensation_without_compensate_action(self) -> None:
        orchestrator = SagaOrchestrator()

        steps = [
            SagaStep(name="step1", forward=lambda: None),
            SagaStep(name="step2", forward=lambda: (_ for _ in ()).throw(RuntimeError("fail"))),
        ]

        instance = await orchestrator.create_saga("partial", steps)
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.COMPENSATED

    async def test_single_step_success(self) -> None:
        orchestrator = SagaOrchestrator()
        called: list[bool] = [False]

        def mark_called() -> None:
            called[0] = True

        steps = [SagaStep(name="only", forward=mark_called)]

        instance = await orchestrator.create_saga("single", steps)
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.COMPLETED
        assert called[0] is True

    async def test_load_nonexistent_saga(self) -> None:
        orchestrator = SagaOrchestrator()
        with pytest.raises(ValueError, match="not found"):
            await orchestrator.execute("nonexistent")
