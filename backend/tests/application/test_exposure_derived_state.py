from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401  (users FK target)
import app.modules.server.infrastructure.models  # noqa: F401  (servers FK target)
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.exposure.application.commands import (
    ReconcileExposureCommand,
    ReconcileExposureHandler,
    _fold_aggregate,
)
from app.modules.exposure.domain.aggregate import (
    ServerExposure,
    ServerExposureTarget,
)
from app.modules.exposure.domain.value_objects import (
    DesiredState,
    ExposureMethod,
    ExposureStatus,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLServerExposureRepository,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def exposure_db():
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield
    await engine.dispose()
    database._engine = None
    database._session_factory = None


def _exposure(
    server_id: str,
    method: ExposureMethod | str,
    desired_state: DesiredState | str,
    targets: list[ServerExposureTarget] | None = None,
) -> ServerExposure:
    exposure = ServerExposure(
        server_id=server_id,
        method=method,
        id=f"exp_{server_id}",
        desired_state=desired_state,
    )
    if targets:
        for t in targets:
            exposure._targets.append(t)  # type: ignore[attr-defined]
    return exposure


def _target(status: ExposureStatus | str) -> ServerExposureTarget:
    return ServerExposureTarget(
        exposure_id="exp_x",
        local_port=25565,
        status=status,
    )


async def _persist(session: AsyncSession, exposures: list[ServerExposure]) -> None:
    repo = SQLServerExposureRepository(session)
    for exposure in exposures:
        await repo.save(exposure)
    await session.commit()


class TestFoldAggregate:
    @pytest.mark.parametrize(
        "target_statuses",
        [
            [ExposureStatus.ACTIVE],
            [ExposureStatus.ERROR],
            [ExposureStatus.CLAIM_REQUIRED],
        ],
    )
    async def test_disabled_override_targets(self, target_statuses) -> None:
        exposure = _exposure(
            "srv_d",
            ExposureMethod.PLAYIT,
            DesiredState.DISABLED,
            [_target(s) for s in target_statuses],
        )
        _fold_aggregate(exposure)
        assert exposure.aggregate_status == ExposureStatus.DISABLED

    async def test_enabled_single_active(self) -> None:
        exposure = _exposure(
            "srv_a",
            ExposureMethod.PLAYIT,
            DesiredState.ENABLED,
            [_target(ExposureStatus.ACTIVE)],
        )
        _fold_aggregate(exposure)
        assert exposure.aggregate_status == ExposureStatus.ACTIVE

    async def test_enabled_error_over_active(self) -> None:
        exposure = _exposure(
            "srv_b",
            ExposureMethod.PLAYIT,
            DesiredState.ENABLED,
            [
                _target(ExposureStatus.ERROR),
                _target(ExposureStatus.ACTIVE),
            ],
        )
        _fold_aggregate(exposure)
        assert exposure.aggregate_status == ExposureStatus.ERROR

    async def test_enabled_claim_required_over_active(self) -> None:
        exposure = _exposure(
            "srv_c",
            ExposureMethod.PLAYIT,
            DesiredState.ENABLED,
            [
                _target(ExposureStatus.CLAIM_REQUIRED),
                _target(ExposureStatus.ACTIVE),
            ],
        )
        _fold_aggregate(exposure)
        assert exposure.aggregate_status == ExposureStatus.CLAIM_REQUIRED


class TestReconcileDesiredAgentRunning:
    async def _run_reconcile(self, exposures: list[ServerExposure], _exposure_db) -> bool:
        async with database._session_factory() as session:
            await _persist(session, exposures)

        event_bus = EventBus()
        handler = ReconcileExposureHandler(event_bus)

        async with database._session_factory() as session:
            agent_repo = SQLHostAgentRepository(session)
            agent = await agent_repo.get()
            assert agent.desired_agent_running is False
            await agent_repo.save(agent)
            await session.commit()

        await handler.handle(ReconcileExposureCommand())

        async with database._session_factory() as session:
            agent_repo = SQLHostAgentRepository(session)
            agent = await agent_repo.get()
            return agent.desired_agent_running

    async def test_playit_enabled_derives_true(self, exposure_db) -> None:
        assert (
            await self._run_reconcile(
                [_exposure("s1", ExposureMethod.PLAYIT, DesiredState.ENABLED)], exposure_db
            )
            is True
        )

    async def test_port_forward_only_derives_false(self, exposure_db) -> None:
        assert (
            await self._run_reconcile(
                [_exposure("s1", ExposureMethod.PORT_FORWARD, DesiredState.ENABLED)], exposure_db
            )
            is False
        )

    async def test_cloudflare_tcp_only_derives_false(self, exposure_db) -> None:
        assert (
            await self._run_reconcile(
                [_exposure("s1", ExposureMethod.CLOUDFLARE_TCP, DesiredState.ENABLED)], exposure_db
            )
            is False
        )

    async def test_mixed_playit_and_non_playit_derives_true(self, exposure_db) -> None:
        assert (
            await self._run_reconcile(
                [
                    _exposure("s1", ExposureMethod.PLAYIT, DesiredState.ENABLED),
                    _exposure("s2", ExposureMethod.PORT_FORWARD, DesiredState.ENABLED),
                ],
                exposure_db,
            )
            is True
        )

    async def test_none_enabled_derives_false(self, exposure_db) -> None:
        assert (
            await self._run_reconcile(
                [
                    _exposure("s1", ExposureMethod.PLAYIT, DesiredState.DISABLED),
                    _exposure("s2", ExposureMethod.PORT_FORWARD, DesiredState.ENABLED),
                ],
                exposure_db,
            )
            is False
        )
