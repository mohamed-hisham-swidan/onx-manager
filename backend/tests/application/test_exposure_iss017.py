from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import init_active_panel_bind
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.settings_store import init_settings_store
from app.modules.exposure.application.commands import (
    CreateExposureTargetCommand,
    CreateExposureTargetHandler,
    SetServerExposureCommand,
    SetServerExposureHandler,
)
from app.modules.exposure.infrastructure.playit_agent import (
    get_playit_supervisor,
    reset_playit_supervisor,
)
from app.modules.exposure.infrastructure.upnp import UPnPResult
from tests.application.test_server_upnp_commands import _create_test_server


@pytest.fixture(autouse=True)
async def setup_test_db(tmp_path, monkeypatch):
    test_yaml = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", test_yaml)
    init_settings_store(test_yaml)
    init_active_panel_bind("127.0.0.1", 8000)

    test_db = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{test_db}")
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    database._engine = engine
    database._session_factory = session_factory

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await get_playit_supervisor().stop()
    reset_playit_supervisor()

    yield

    await get_playit_supervisor().stop()
    reset_playit_supervisor()
    await engine.dispose()


@pytest.mark.asyncio
async def test_uow_commits_before_network_call() -> None:
    """ISS-017: Verify UnitOfWork commits before external network calls are made."""
    server = await _create_test_server("srv-iss017-1", port=25565)
    bus = EventBus()
    handler = SetServerExposureHandler(bus)

    create_handler = CreateExposureTargetHandler(bus)
    await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))

    call_order: list[str] = []

    orig_commit = UnitOfWork.commit

    async def tracking_commit(self: UnitOfWork) -> None:
        call_order.append("uow_commit")
        await orig_commit(self)

    async def tracking_attempt_mapping(*_args, **_kwargs) -> UPnPResult:
        call_order.append("network_upnp_mapping")
        return UPnPResult(
            success=True,
            external_ip="198.51.100.1",
            external_port=25565,
            internal_port=25565,
        )

    with (
        patch.object(UnitOfWork, "commit", tracking_commit),
        patch(
            "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
            side_effect=tracking_attempt_mapping,
        ),
    ):
        res = await handler.handle(
            SetServerExposureCommand(
                server_id=str(server.id),
                method="port_forward",
                desired_state="ENABLED",
            )
        )
        assert res.success is True
        assert "uow_commit" in call_order
        assert "network_upnp_mapping" in call_order
        first_commit_idx = call_order.index("uow_commit")
        network_idx = call_order.index("network_upnp_mapping")
        assert first_commit_idx < network_idx, f"Commit before network call: {call_order}"


@pytest.mark.asyncio
async def test_network_failure_does_not_fail_db_transaction() -> None:
    """ISS-017: Failing network call does NOT hold up or fail the DB transaction."""
    server = await _create_test_server("srv-iss017-2", port=25566)
    bus = EventBus()
    handler = SetServerExposureHandler(bus)

    create_handler = CreateExposureTargetHandler(bus)
    await create_handler.handle(CreateExposureTargetCommand(server_id=str(server.id)))

    async def slow_failing_mapping(*_args, **_kwargs) -> UPnPResult:
        await asyncio.sleep(0.01)
        return UPnPResult(
            success=False,
            error_code="UPNP_DISCOVERY_TIMEOUT",
            error_message="Gateway device did not respond within timeout",
        )

    with patch(
        "app.modules.exposure.application.commands.AsyncUPnPService.attempt_mapping",
        side_effect=slow_failing_mapping,
    ):
        res = await handler.handle(
            SetServerExposureCommand(
                server_id=str(server.id),
                method="port_forward",
                desired_state="ENABLED",
            )
        )
        assert res.success is True
        assert res.data["desired_state"] == "ENABLED"
        assert res.data["targets"][0]["status"] == "ERROR"
        assert res.data["targets"][0]["error_code"] == "UPNP_DISCOVERY_TIMEOUT"
