from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.persistence.db import database
from app.modules.operations.domain.aggregate import Operation
from app.modules.operations.domain.enums import OperationStatus, StepStatus
from app.modules.operations.infrastructure.repository import SQLOperationRepository


@pytest.mark.asyncio
async def test_operation_repository_save_and_get():
    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        op = Operation.create(
            type="RUN_TEST",
            target_type="server",
            target_id="srv-100",
            actor_id="user-1",
            idempotency_key="key-abc",
            timeout_seconds=300,
            metadata={"branch": "main"},
        )
        op.add_step("ADMISSION_CHECK", sequence=1, message_key="ops.admission")
        op.add_step("MATERIALIZE_STAGING", sequence=2, safe_to_retry=True)

        saved = await repo.save(op)
        await session.commit()

        assert saved.id == op.id
        assert len(saved.steps) == 2

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        loaded = await repo.get(op.id)
        assert loaded is not None
        assert loaded.id == op.id
        assert loaded.type == "RUN_TEST"
        assert loaded.target_id == "srv-100"
        assert loaded.status == OperationStatus.QUEUED
        assert loaded.idempotency_key == "key-abc"
        assert loaded.timeout_seconds == 300
        assert loaded.metadata == {"branch": "main"}
        assert len(loaded.steps) == 2
        assert loaded.steps[0].step_id == "ADMISSION_CHECK"
        assert loaded.steps[0].sequence == 1
        assert loaded.steps[0].status == StepStatus.PENDING
        assert loaded.steps[1].step_id == "MATERIALIZE_STAGING"
        assert loaded.steps[1].safe_to_retry is True


@pytest.mark.asyncio
async def test_operation_repository_update_steps():
    op = Operation.create(
        type="RUN_TEST",
        target_type="server",
        target_id="srv-200",
    )
    op.add_step("STEP_1", sequence=1)
    op.add_step("STEP_2", sequence=2)

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        await repo.save(op)
        await session.commit()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        loaded = await repo.get(op.id)
        assert loaded is not None
        loaded.start()
        loaded.start_step("STEP_1")
        loaded.update_step_progress("STEP_1", 0.5, context={"detail": "halfway"})
        await repo.save(loaded)
        await session.commit()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        reloaded = await repo.get(op.id)
        assert reloaded is not None
        assert reloaded.status == OperationStatus.RUNNING
        assert reloaded.current_step_id == "STEP_1"
        s1 = reloaded.get_step("STEP_1")
        assert s1 is not None
        assert s1.status == StepStatus.IN_PROGRESS
        assert s1.progress == 0.5
        assert s1.context == {"detail": "halfway"}


@pytest.mark.asyncio
async def test_operation_repository_get_by_idempotency_key():
    op = Operation.create(
        type="SERVER_START",
        target_type="server",
        target_id="srv-300",
        idempotency_key="unique-idem-key-1",
    )
    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        await repo.save(op)
        await session.commit()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        found = await repo.get_by_idempotency_key("server", "srv-300", "unique-idem-key-1")
        assert found is not None
        assert found.id == op.id

        not_found = await repo.get_by_idempotency_key("server", "srv-300", "other-key")
        assert not_found is None


@pytest.mark.asyncio
async def test_operation_repository_unique_idempotency_constraint():
    op1 = Operation.create(
        type="SERVER_START",
        target_type="server",
        target_id="srv-400",
        idempotency_key="same-key",
    )
    op2 = Operation.create(
        type="SERVER_START",
        target_type="server",
        target_id="srv-400",
        idempotency_key="same-key",
    )

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        await repo.save(op1)
        await session.commit()

    with pytest.raises(IntegrityError):
        async with database.session_factory() as session:
            repo = SQLOperationRepository(session)
            await repo.save(op2)
            await session.commit()


@pytest.mark.asyncio
async def test_operation_repository_atomic_request_cancellation():
    op = Operation.create(
        type="RUN_TEST",
        target_type="server",
        target_id="srv-500",
    )
    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        await repo.save(op)
        await session.commit()

    # Cancel while QUEUED -> Should succeed (rowcount == 1)
    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        won = await repo.atomic_request_cancellation(op.id)
        await session.commit()
        assert won is True

    # Second cancel attempt -> Should fail (status is already CANCEL_REQUESTED)
    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        won_second = await repo.atomic_request_cancellation(op.id)
        await session.commit()
        assert won_second is False


@pytest.mark.asyncio
async def test_operation_repository_atomic_timeout():
    op = Operation.create(
        type="RUN_TEST",
        target_type="server",
        target_id="srv-600",
    )
    op.prepare()
    op.start()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        await repo.save(op)
        await session.commit()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        timed_out = await repo.atomic_timeout(op.id)
        await session.commit()
        assert timed_out is True

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        loaded = await repo.get(op.id)
        assert loaded is not None
        assert loaded.status == OperationStatus.TIMED_OUT
        assert loaded.failure_code == "OPERATION_TIMEOUT"

        # Timeout again -> Should return False (not in PREPARING/RUNNING)
        timed_out_again = await repo.atomic_timeout(op.id)
        assert timed_out_again is False


@pytest.mark.asyncio
async def test_operation_repository_active_and_list():
    op1 = Operation.create(type="RUN_TEST", target_type="server", target_id="srv-700")
    op2 = Operation.create(type="BACKUP", target_type="server", target_id="srv-700")
    op2.start()
    op2.complete()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        await repo.save(op1)
        await repo.save(op2)
        await session.commit()

    async with database.session_factory() as session:
        repo = SQLOperationRepository(session)
        active = await repo.get_active_for_target("server", "srv-700")
        assert len(active) == 1
        assert active[0].id == op1.id

        all_ops = await repo.list_operations(target_type="server", target_id="srv-700")
        assert len(all_ops) == 2
