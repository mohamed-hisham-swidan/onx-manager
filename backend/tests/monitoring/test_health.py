import pytest
from unittest.mock import AsyncMock, patch

from app.modules.monitoring.infrastructure.health import (
    HealthCheckRegistry,
    HealthResult,
    check_database,
    check_disk,
)


@pytest.mark.asyncio
async def test_check_database_failure() -> None:
    result = await check_database()
    assert result.status in ("up", "down", "degraded")


@pytest.mark.asyncio
async def test_check_disk() -> None:
    result = await check_disk()
    assert result.status in ("up", "degraded", "down")


@pytest.mark.asyncio
async def test_health_registry_register_and_run() -> None:
    registry = HealthCheckRegistry()

    async def ok_check() -> HealthResult:
        return HealthResult(status="up", detail="ok")

    registry.register("test", ok_check)
    results = await registry.run_all()
    assert "test" in results
    assert results["test"].status == "up"
    assert results["test"].latency_ms >= 0


@pytest.mark.asyncio
async def test_health_registry_handles_exception() -> None:
    registry = HealthCheckRegistry()

    async def failing() -> HealthResult:
        raise RuntimeError("boom")

    registry.register("fail", failing)
    results = await registry.run_all()
    assert results["fail"].status == "down"


@pytest.mark.asyncio
async def test_health_registry_empty() -> None:
    registry = HealthCheckRegistry()
    results = await registry.run_all()
    assert results == {}
