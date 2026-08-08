import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_permission
from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.saga import SagaOrchestrator, SagaStep
from app.core.settings_store import (
    RESTART_REQUIRED_FIELDS,
    get_live_settings,
    init_settings_store,
    update_settings,
)
from app.main import create_app
from app.tasks.definitions.cleanup_task import run_cleanup_task


class MockHandler(EventHandler):
    def __init__(self, fail_count: int = 0):
        self.calls = 0
        self.fail_count = fail_count

    async def handle(self, event: DomainEvent) -> None:
        self.calls += 1
        if self.calls <= self.fail_count:
            raise RuntimeError("Mock failure")


@pytest.fixture(autouse=True)
def setup_temp_settings(tmp_path, monkeypatch):
    """Isolate settings_store to a temporary file for each test."""
    test_yaml = tmp_path / "settings.yaml"
    monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", test_yaml)
    init_settings_store(test_yaml)
    yield test_yaml


class TestSettingsPersistenceStore:
    def test_init_and_get_defaults(self, setup_temp_settings):
        live = get_live_settings()
        assert live.app_name == "mcs-manager"
        assert live.rate_limit_per_minute == 60
        assert live.circuit_breaker_max_failures == 5
        assert live.circuit_breaker_timeout_seconds == 30
        assert live.event_bus_retry_attempts == 3
        assert live.saga_timeout_seconds == 300
        assert live.idempotency_ttl_hours == 24
        assert live.log_level == "INFO"
        assert live.debug is False

    def test_update_persists_to_file(self, setup_temp_settings):
        test_yaml = setup_temp_settings
        live, restart_fields = update_settings({
            "rate_limit_per_minute": 120,
            "log_level": "DEBUG",
        })
        assert live.rate_limit_per_minute == 120
        assert live.log_level == "DEBUG"
        assert "log_level" in restart_fields
        assert "rate_limit_per_minute" not in restart_fields

        # Verify YAML file content on disk
        with open(test_yaml) as f:
            data = yaml.safe_load(f)
        assert data["rate_limit_per_minute"] == 120
        assert data["log_level"] == "DEBUG"

    def test_init_from_existing_file(self, tmp_path, monkeypatch):
        test_yaml = tmp_path / "existing.yaml"
        test_yaml.write_text(yaml.dump({"rate_limit_per_minute": 45, "app_name": "custom-app"}))
        monkeypatch.setattr("app.core.settings_store._SETTINGS_FILE", test_yaml)
        init_settings_store(test_yaml)

        live = get_live_settings()
        assert live.rate_limit_per_minute == 45
        assert live.app_name == "custom-app"
        assert live.log_level == "INFO"  # Default fallback


class TestConsumerHotReload:
    def test_circuit_breaker_max_failures_hot_reload(self, setup_temp_settings):
        cb = CircuitBreaker("test-cb")
        assert cb.max_failures == 5

        update_settings({"circuit_breaker_max_failures": 2})
        assert cb.max_failures == 2

    def test_circuit_breaker_timeout_seconds_hot_reload(self, setup_temp_settings):
        cb = CircuitBreaker("test-cb")
        assert cb.timeout_seconds == 30.0

        update_settings({"circuit_breaker_timeout_seconds": 15})
        assert cb.timeout_seconds == 15.0

    @pytest.mark.asyncio
    async def test_event_bus_retry_attempts_hot_reload(self, setup_temp_settings):
        eb = EventBus()
        handler = MockHandler(fail_count=5)
        eb.subscribe("test_event", handler)

        # Default is 3 attempts
        assert eb.retry_attempts == 3
        await eb.publish(DomainEvent(event_type="test_event"))
        assert handler.calls == 3

        # Update to 1 attempt
        handler.calls = 0
        update_settings({"event_bus_retry_attempts": 1})
        assert eb.retry_attempts == 1
        await eb.publish(DomainEvent(event_type="test_event"))
        assert handler.calls == 1

    @pytest.mark.asyncio
    async def test_saga_timeout_seconds_hot_reload(self, setup_temp_settings):
        orchestrator = SagaOrchestrator()
        steps = [SagaStep("step1", forward=lambda: None)]

        # Default timeout
        instance1 = await orchestrator.create_saga("test_saga", steps)
        assert instance1.timeout_seconds == 300.0

        # Update live settings
        update_settings({"saga_timeout_seconds": 150})
        instance2 = await orchestrator.create_saga("test_saga", steps)
        assert instance2.timeout_seconds == 150.0

    @pytest.mark.asyncio
    async def test_cleanup_task_idempotency_ttl_hot_reload(self, setup_temp_settings, monkeypatch):
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=AsyncMock(rowcount=0))

        mock_sf = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=None)

        monkeypatch.setattr("app.core.persistence.db.database._session_factory", mock_sf)

        task_params = {
            "cleanup_logs": False,
            "cleanup_idempotency": True,
            "cleanup_events": False,
            "cleanup_task_queue": False,
        }

        # Run with default live setting (24h)
        await run_cleanup_task(task_params)

        # Update live setting to 12h
        update_settings({"idempotency_ttl_hours": 12})
        await run_cleanup_task(task_params)

        assert mock_session.execute.call_count == 2


class TestSettingsAPIEndpoints:
    @pytest.fixture(autouse=True)
    async def setup_db(self):
        from app.core.config import ConfigFactory
        from app.core.persistence.db import database
        from app.core.persistence.base import Base
        database.init(ConfigFactory.global_settings())
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @pytest.mark.asyncio
    async def test_permission_denied_without_permission(self):
        from app.modules.auth.infrastructure.jwt import create_access_token
        app_instance = create_app()

        token = create_access_token(user_id="u1", permissions=[])
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res_get = await client.get("/api/v1/settings", headers=headers)
            assert res_get.status_code == 403

            res_patch = await client.patch("/api/v1/settings", json={"rate_limit_per_minute": 100}, headers=headers)
            assert res_patch.status_code == 403

    @pytest.mark.asyncio
    async def test_get_and_patch_settings_with_permission(self, setup_temp_settings):
        from app.modules.auth.infrastructure.jwt import create_access_token
        app_instance = create_app()

        token = create_access_token(user_id="u1", permissions=["admin:full"])
        headers = {"Authorization": f"Bearer {token}"}
        transport = ASGITransport(app=app_instance)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res_get = await client.get("/api/v1/settings", headers=headers)
            assert res_get.status_code == 200
            data = res_get.json()
            assert data["rate_limit_per_minute"] == 60
            assert "requires_restart" in data
            assert set(data["requires_restart"]) == {"app_name", "log_level", "debug"}

            # Update settings via PATCH
            res_patch = await client.patch(
                "/api/v1/settings",
                json={"rate_limit_per_minute": 90, "log_level": "WARNING"},
                headers=headers,
            )
            assert res_patch.status_code == 200
            patch_data = res_patch.json()
            assert patch_data["success"] is True
            assert patch_data["settings"]["rate_limit_per_minute"] == 90
            assert patch_data["settings"]["log_level"] == "WARNING"
            assert patch_data["requires_restart"] == ["log_level"]

            # Subsequent GET reflects live update without backend restart
            res_get2 = await client.get("/api/v1/settings", headers=headers)
            assert res_get2.status_code == 200
            assert res_get2.json()["rate_limit_per_minute"] == 90
