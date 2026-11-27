from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.health.application.event_handlers.server_crashed_handler import (
    HandleServerCrashHandler,
)
from app.modules.health.domain.value_objects import (
    CrashClassification,
    HealthStatusEnum,
)
from app.modules.health.infrastructure.health_calculator import SignalHealthCalculator
from app.modules.health.infrastructure.integrity import _check_modern_forge_layout
from app.modules.monitoring.infrastructure.collector import _parse_tick_query
from app.modules.monitoring.infrastructure.health import (
    check_database,
    check_disk,
    check_dlq_depth,
)
from app.modules.server.domain.events import ServerCrashedEvent


@pytest.fixture(autouse=True)
async def init_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = factory
    yield
    await engine.dispose()
    database._engine = old_engine
    database._session_factory = old_factory


@pytest.mark.asyncio
async def test_f024_parse_tick_query_lagging_server():
    """F024: Lagging server report with both target and actual TPS parses actual TPS."""
    lagging_log = (
        "The target tick rate is 20.0 per second. The average tick time is 70.4ms "
        "(target 50.0ms), with 14.2 ticks per second (71% of target)."
    )
    tps = _parse_tick_query(lagging_log)
    assert tps == 14.2

    healthy_log = (
        "The target tick rate is 20.0 per second. The average tick time is 12.1ms "
        "(target 50.0ms), with 20.0 ticks per second (100% of target)."
    )
    assert _parse_tick_query(healthy_log) == 20.0

    minimal_log = "Target tick rate: 20.0 per second."
    assert _parse_tick_query(minimal_log) is None

    mspt_only_log = "Average time per tick: 80.0ms"
    assert _parse_tick_query(mspt_only_log) == 12.5


@pytest.mark.asyncio
async def test_f025_check_database_uses_text_sql():
    """F025: check_database executes text('SELECT 1') and reports up when reachable."""
    result = await check_database()
    assert result.status == "up"
    assert "reachable" in result.detail.lower()


@pytest.mark.asyncio
async def test_f026_check_disk_resolves_data_dir():
    """F026: check_disk resolves data directory and reports free disk space."""
    result = await check_disk()
    assert result.status in ("up", "degraded")
    assert "GB free" in result.detail or "critically low" in result.detail

    with patch("shutil.disk_usage", side_effect=OSError("Drive unavailable")):
        failed_result = await check_disk()
        assert failed_result.status == "degraded"
        assert "Drive unavailable" in failed_result.detail


@pytest.mark.asyncio
async def test_f027_check_dlq_depth_reports_accurate_count():
    """F027: check_dlq_depth uses get_dead_letter_count and accepts zero arguments."""
    with patch(
        "app.modules.event_store.repository.SQLEventRepository.get_dead_letter_count",
        new=AsyncMock(return_value=5),
    ):
        result = await check_dlq_depth()
        assert result.status == "degraded"
        assert "5 messages in dead letter queue" in result.detail

    with patch(
        "app.modules.event_store.repository.SQLEventRepository.get_dead_letter_count",
        new=AsyncMock(return_value=0),
    ):
        result = await check_dlq_depth()
        assert result.status == "up"
        assert result.detail == "No dead letters"


@pytest.mark.asyncio
async def test_f030_health_calculator_recovery_transition():
    """F030: Recovering from WARNING to HEALTHY is permitted directly."""
    calc = SignalHealthCalculator()
    transitioned = calc._apply_transition(HealthStatusEnum.WARNING, HealthStatusEnum.HEALTHY)
    assert transitioned == HealthStatusEnum.HEALTHY

    degraded = calc._apply_transition(HealthStatusEnum.HEALTHY, HealthStatusEnum.BROKEN)
    assert degraded != HealthStatusEnum.BROKEN
    assert degraded in (HealthStatusEnum.WARNING, HealthStatusEnum.CRITICAL)


def test_f031_modern_forge_windows_run_bat(tmp_path: Path):
    """F031: Modern Forge server directory containing run.bat + libraries/ passes integrity."""
    srvd = tmp_path / "srv-forge-win"
    srvd.mkdir()
    (srvd / "run.bat").write_text(
        "@echo off\r\njava @user_jvm_args.txt @libraries/net/minecraftforge/..."
    )
    (srvd / "libraries").mkdir()

    checks = []
    _check_modern_forge_layout(srvd, checks)
    assert len(checks) == 1
    assert checks[0].status == "pass"
    assert "run.bat" in checks[0].detail


@pytest.mark.asyncio
async def test_f035_server_crashed_handler_collects_evidence(tmp_path: Path, monkeypatch):
    """F035: HandleServerCrashHandler resolves server directory and passes to evidence collector."""
    servers_dir = tmp_path / "servers"
    srv_dir = servers_dir / "srv-crash-1"
    logs_dir = srv_dir / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "latest.log").write_text(
        "[Server thread/INFO]: Server started\n[Server thread/ERROR]: Crash\n"
    )

    monkeypatch.setenv("MCS_SERVERS_DATA_DIR", str(servers_dir))

    bus = EventBus()
    handler = HandleServerCrashHandler(bus)

    classification = CrashClassification(
        evidence_id="ev-123",
        failure_code="OOM",
        confidence=0.9,
        summary="OOM crash",
        suggested_action="increase RAM",
    )
    mock_rec = AsyncMock(return_value=MagicMock(events=[]))
    with (
        patch.object(handler._classifier, "classify", new=AsyncMock(return_value=classification)),
        patch.object(handler._recovery, "trigger", new=mock_rec),
    ):
        await handler.handle(ServerCrashedEvent(server_id="srv-crash-1", exit_code=137))

    bundle = await handler._collector.collect("srv-crash-1")
    assert not any("Server directory not found" in err for err in bundle.collection_errors)


@pytest.mark.asyncio
async def test_get_health_dashboard_endpoint() -> None:
    from app.api.v1.routers.health import get_health_dashboard

    res = await get_health_dashboard(
        current_user={"user_id": "admin", "roles": ["admin"], "permissions": ["admin:full"]}
    )
    assert res.total_servers >= 0
    assert res.healthy >= 0
    assert isinstance(res.servers, list)


@pytest.mark.asyncio
async def test_get_health_dashboard_ignores_orphaned_health_records() -> None:
    from datetime import UTC, datetime

    from app.api.v1.routers.health import get_health_dashboard
    from app.core.persistence.db import database
    from app.modules.health.infrastructure.models import HealthStatusModel
    from app.modules.health.infrastructure.repository import SQLHealthRepository
    from app.modules.server.infrastructure.models import ServerModel

    async with database.session_factory() as session:
        session.add(
            ServerModel(
                id="srv-active-1",
                name="Active Server",
                server_type="paper",
                minecraft_version="1.21.4",
                status="running",
            )
        )
        session.add(
            HealthStatusModel(
                server_id="srv-active-1",
                classification="healthy",
                contributing_factors="[]",
                trend="stable",
                confidence=0.95,
                last_updated=datetime.now(UTC),
            )
        )
        session.add(
            HealthStatusModel(
                server_id="ghost-deleted-server",
                classification="critical",
                contributing_factors='["Critical: crash=UNKNOWN_RUNTIME_FAILURE"]',
                trend="declining",
                confidence=0.65,
                last_updated=datetime.now(UTC),
            )
        )
        await session.commit()

    res = await get_health_dashboard(
        current_user={"user_id": "admin", "roles": ["admin"], "permissions": ["admin:full"]}
    )
    assert res.total_servers == 1
    assert res.healthy == 1
    assert res.critical == 0
    assert [s.server_id for s in res.servers] == ["srv-active-1"]

    async with database.session_factory() as session:
        pruned = await SQLHealthRepository(session).prune_orphaned()
        await session.commit()
        assert pruned == 1

