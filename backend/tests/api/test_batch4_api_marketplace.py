from __future__ import annotations

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.exceptions import DownloadError
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.main import app
from app.modules.auth.infrastructure.jwt import create_access_token
from app.modules.monitoring.domain.aggregate import AlertCondition, AlertRule, AlertSeverity
from app.modules.monitoring.infrastructure.repository import SQLAlertRuleRepository
from app.modules.plugin.infrastructure.dependency_resolver import DependencyResolver
from app.modules.plugin.infrastructure.providers.modrinth import ModrinthProvider
from app.modules.shared.value_objects import ServerId


@pytest.fixture(autouse=True)
async def init_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory
    yield
    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


class TestBatch4CDependencyResolver:
    """F040: DependencyResolver supports diamond dependencies without false cycle detection."""

    def test_diamond_dependency_resolves(self) -> None:
        resolver = DependencyResolver()
        # D has no dependencies
        resolver.register_plugin("D", "1.0.0", [])
        # B and C both depend on D
        resolver.register_plugin("B", "1.0.0", [{"name": "D", "min_version": "1.0.0"}])
        resolver.register_plugin("C", "1.0.0", [{"name": "D", "min_version": "1.0.0"}])
        # A depends on both B and C
        resolver.register_plugin("A", "1.0.0", ["B", "C"])

        result = resolver.resolve("A")
        assert result.success is True
        assert len(result.conflicts) == 0
        assert result.resolved[0].name == "A"
        assert len(result.resolved[0].dependencies) == 2

    def test_true_circular_dependency_detected(self) -> None:
        resolver = DependencyResolver()
        resolver.register_plugin("A", "1.0.0", ["B"])
        resolver.register_plugin("B", "1.0.0", ["A"])

        result = resolver.resolve("A")
        assert result.success is False
        assert len(result.conflicts) == 1
        assert "Circular dependency detected" in result.conflicts[0].message


class TestBatch4CModrinthNo404Retry:
    """F063: ModrinthProvider does not retry 404.

    Marketplace router converts 404 to NotFoundError.
    """

    @pytest.mark.asyncio
    async def test_get_json_does_not_retry_404(self) -> None:
        provider = ModrinthProvider()
        attempts = 0

        async def mock_do_get_json(_client, url, _params):
            nonlocal attempts
            attempts += 1
            raise DownloadError(url, 404)

        with patch.object(ModrinthProvider, "_do_get_json", side_effect=mock_do_get_json):
            with pytest.raises(DownloadError) as exc_info:
                await provider._get_json("/project/nonexistent")
            assert exc_info.value.status == 404
            assert attempts == 1  # No retries!

    @pytest.mark.asyncio
    async def test_marketplace_router_returns_404(self) -> None:
        async def mock_get_project(_self, project_id):
            raise DownloadError(f"https://api.modrinth.com/v2/project/{project_id}", 404)

        token = create_access_token(
            user_id="test",
            roles=["admin", "owner"],
            permissions=["admin:full", "plugin:manage", "global.settings"],
        )
        auth_headers = {"Authorization": f"Bearer {token}"}

        with (
            patch.object(ModrinthProvider, "get_project", mock_get_project),
            patch(
                "app.api.v1.routers.marketplace.require_permission",
                return_value=lambda: {"user_id": "test"},
            ),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/api/v1/marketplace/projects/missing-plugin",
                    headers=auth_headers,
                )
                assert resp.status_code == 404
                body = resp.json()
                msg = body.get("message", "").lower()
                assert "not found" in msg or body.get("code") == "NOT_FOUND"


class TestBatch4CMonitoringAlertsWiring:
    """F064: list_alerts and delete_alert_rule wired to SQLAlertRuleRepository."""

    @pytest.mark.asyncio
    async def test_list_and_delete_alert_rules(self) -> None:
        # Create an alert rule in the DB
        async with database.session_factory() as session:
            repo = SQLAlertRuleRepository(session)
            rule = AlertRule(
                server_id=ServerId("srv-1"),
                metric_name="cpu_percent",
                condition=AlertCondition.GREATER_THAN,
                threshold=90.0,
                severity=AlertSeverity.CRITICAL,
                cooldown_minutes=10,
            )
            await repo.save(rule)
            await session.commit()
            rule_id = rule._alert_rule_id

        token = create_access_token(
            user_id="test",
            roles=["admin", "owner"],
            permissions=["admin:full", "global.settings"],
        )
        auth_headers = {"Authorization": f"Bearer {token}"}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # 1. List alerts
            with patch(
                "app.api.v1.routers.monitoring.get_current_user",
                return_value={"user_id": "test"},
            ):
                resp = await ac.get("/api/v1/monitoring/alerts", headers=auth_headers)
                assert resp.status_code == 200
                alerts = resp.json()
                assert len(alerts) >= 1
                assert any(a["id"] == rule_id and a["server_id"] == "srv-1" for a in alerts)

            # 2. Delete alert
            with patch(
                "app.api.v1.routers.monitoring.require_permission",
                return_value=lambda: {"user_id": "test"},
            ):
                del_resp = await ac.delete(
                    f"/api/v1/monitoring/alerts/{rule_id}",
                    headers=auth_headers,
                )
                assert del_resp.status_code == 204

                # Idempotent delete of nonexistent rule
                del_resp2 = await ac.delete(
                    f"/api/v1/monitoring/alerts/{rule_id}",
                    headers=auth_headers,
                )
                assert del_resp2.status_code == 204

            # 3. Verify gone
            with patch(
                "app.api.v1.routers.monitoring.get_current_user",
                return_value={"user_id": "test"},
            ):
                resp2 = await ac.get("/api/v1/monitoring/alerts", headers=auth_headers)
                assert not any(a["id"] == rule_id for a in resp2.json())
