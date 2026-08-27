from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.server.application.startup_guard import check_startup_readiness

pytestmark = pytest.mark.asyncio


class TestStartupGuard:
    async def test_allows_on_healthy_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            srvd = Path(tmp) / "test-srv"
            srvd.mkdir()
            (srvd / "server.jar").write_text("")
            (srvd / "server.properties").write_text("server-port=25565\n")
            (srvd / "world").mkdir()

            with patch(
                "app.modules.health.infrastructure.integrity._resolve_path",
                return_value=srvd,
            ):
                result = await check_startup_readiness("test-srv")

        assert result.allowed is True

    async def test_blocks_on_critical_issues(self):
        with (
            patch(
                "app.modules.health.infrastructure.integrity.FilesystemIntegrityChecker.check",
            ) as mock_check,
            patch(
                "app.modules.health.infrastructure.environment.HostEnvironmentScanner.scan",
            ),
        ):
            from app.modules.health.domain.value_objects import IntegrityCheck, IntegrityReport

            mock_check.return_value = IntegrityReport(
                server_id="test",
                checks=[
                    IntegrityCheck(
                        check_name="server_jar",
                        severity="critical",
                        status="fail",
                        detail="No .jar files found",
                    ),
                ],
                overall_status="fail",
            )
            result = await check_startup_readiness("test")

        assert result.allowed is False
        assert any("server_jar" in r for r in result.reasons)

    async def test_missing_dir_is_warning_not_block(self):
        with patch(
            "app.modules.health.infrastructure.integrity.FilesystemIntegrityChecker.check",
        ) as mock_check:
            from app.modules.health.domain.value_objects import IntegrityCheck, IntegrityReport

            mock_check.return_value = IntegrityReport(
                server_id="test",
                checks=[
                    IntegrityCheck(
                        check_name="server_directory",
                        severity="critical",
                        status="error",
                        detail="Server directory not found",
                    ),
                ],
                overall_status="fail",
            )
            result = await check_startup_readiness("test")

        assert result.allowed is True
        assert len(result.warnings) >= 1
