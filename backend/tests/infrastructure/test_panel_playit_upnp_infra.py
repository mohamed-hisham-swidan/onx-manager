"""Tests for UPnP and PlayitAgent supervisor infrastructure (Batch 7.2b).

Adheres to strict test safety standards:
  - os.kill and os.killpg hermetically mocked
  - safe sentinel mock PIDs (99999) only
  - guaranteed try/finally: await supervisor.stop() cleanup
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.exposure.domain.value_objects import ExposureStatus
from app.modules.exposure.infrastructure.playit_agent import PlayitAgentSupervisor
from app.modules.exposure.infrastructure.upnp import AsyncUPnPService

SAFE_SENTINEL_PID = 99999


class TestUPnPService:
    @pytest.mark.parametrize(
        "ip,is_private",
        [
            ("192.168.1.1", True),
            ("10.0.0.5", True),
            ("172.16.0.1", True),
            ("100.64.0.1", True),
            ("100.127.255.254", True),
            ("127.0.0.1", True),
            ("8.8.8.8", False),
            ("1.1.1.1", False),
            ("93.184.216.34", False),
        ],
    )
    def test_is_private_or_cgnat(self, ip: str, is_private: bool) -> None:
        assert AsyncUPnPService.is_private_or_cgnat(ip) is is_private

    @pytest.mark.parametrize(
        "port,valid,err_code",
        [
            (8000, True, None),
            (8080, True, None),
            (25565, True, None),
            (0, False, "INVALID_PORT"),
            (65536, False, "INVALID_PORT"),
            (-1, False, "INVALID_PORT"),
            (25575, False, "DENY_LIST_VIOLATION"),
            (3306, False, "DENY_LIST_VIOLATION"),
            (5432, False, "DENY_LIST_VIOLATION"),
            (6379, False, "DENY_LIST_VIOLATION"),
            (27017, False, "DENY_LIST_VIOLATION"),
            (9090, False, "DENY_LIST_VIOLATION"),
            (9100, False, "DENY_LIST_VIOLATION"),
        ],
    )
    def test_validate_external_port(self, port: int, valid: bool, err_code: str | None) -> None:
        is_val, code, _msg = AsyncUPnPService.validate_external_port(port)
        assert is_val is valid
        assert code == err_code

    async def test_attempt_mapping_unsupported_when_discovery_fails(self) -> None:
        service = AsyncUPnPService(timeout=1)
        with patch.object(service, "_discover_igd", return_value=None):
            result = await service.attempt_mapping(internal_port=8000, requested_external_port=8000)
            assert result.success is False
            assert result.error_code == "UPNP_UNSUPPORTED"
            assert "UPnP is disabled" in (result.error_message or "")

    async def test_attempt_mapping_double_nat_detected(self) -> None:
        service = AsyncUPnPService(timeout=1)
        mock_upnp = MagicMock()
        mock_upnp.get_external_ip = AsyncMock(return_value="100.64.1.25")
        mock_upnp.lan_address = "192.168.1.100"

        with patch.object(service, "_discover_igd", return_value=mock_upnp):
            result = await service.attempt_mapping(internal_port=8000, requested_external_port=8000)
            assert result.success is False
            assert result.error_code == "DOUBLE_NAT_DETECTED"
            assert "Double-NAT or CGNAT" in (result.error_message or "")

    async def test_attempt_mapping_success(self) -> None:
        service = AsyncUPnPService(timeout=1)
        mock_upnp = MagicMock()
        mock_upnp.get_external_ip = AsyncMock(return_value="93.184.216.34")
        mock_upnp.lan_address = "192.168.1.100"
        mock_upnp.add_port_mapping = AsyncMock(return_value=None)

        with patch.object(service, "_discover_igd", return_value=mock_upnp):
            result = await service.attempt_mapping(internal_port=8000, requested_external_port=8000)
            assert result.success is True
            assert result.external_ip == "93.184.216.34"
            assert result.external_port == 8000
            assert result.internal_port == 8000
            assert result.auto_fixed is False
            mock_upnp.add_port_mapping.assert_awaited_once_with(
                external_port=8000,
                protocol="TCP",
                internal_port=8000,
                lan_address="192.168.1.100",
                description="MCS-Manager-Panel",
            )

    async def test_attempt_mapping_auto_fix_conflict_retry(self) -> None:
        service = AsyncUPnPService(timeout=1)
        mock_upnp = MagicMock()
        mock_upnp.get_external_ip = AsyncMock(return_value="93.184.216.34")
        mock_upnp.lan_address = "192.168.1.100"

        # Fail first attempt on 8000, succeed second on 8001
        mock_upnp.add_port_mapping = AsyncMock(
            side_effect=[Exception("ConflictInMappingEntry"), None]
        )

        with patch.object(service, "_discover_igd", return_value=mock_upnp):
            result = await service.attempt_mapping(internal_port=8000, requested_external_port=8000)
            assert result.success is True
            assert result.external_ip == "93.184.216.34"
            assert result.external_port == 8001
            assert result.auto_fixed is True
            assert "automatically mapped to alternate port 8001" in (result.fix_hint or "")
            assert mock_upnp.add_port_mapping.await_count == 2

    async def test_delete_mapping_success(self) -> None:
        service = AsyncUPnPService(timeout=1)
        mock_upnp = MagicMock()
        mock_upnp.delete_port_mapping = AsyncMock(return_value=None)

        with patch.object(service, "_discover_igd", return_value=mock_upnp):
            ok = await service.delete_mapping(external_port=8000)
            assert ok is True
            mock_upnp.delete_port_mapping.assert_awaited_once_with(
                external_port=8000, protocol="TCP"
            )


class TestPlayitSupervisor:
    """Subprocess tests with mandatory test safety mocking os.kill / os.killpg."""

    @pytest.fixture(autouse=True)
    def _mock_os_signals(self):
        with (
            patch("os.kill") as mock_kill,
            patch("os.killpg", create=True) as mock_killpg,
            patch("os.getpgid", return_value=SAFE_SENTINEL_PID, create=True),
        ):
            yield mock_kill, mock_killpg

    def _mock_subprocess(
        self,
        pid: int = SAFE_SENTINEL_PID,
        stdout_lines: list[bytes] | None = None,
        stderr_lines: list[bytes] | None = None,
    ):
        proc = AsyncMock()
        proc.pid = pid
        proc.returncode = None
        proc.wait = AsyncMock(return_value=0)
        proc.terminate = MagicMock()
        proc.kill = MagicMock()

        out_lines = list(stdout_lines or [])
        err_lines = list(stderr_lines or [])

        async def _readline_out():
            if out_lines:
                return out_lines.pop(0)
            return b""

        async def _readline_err():
            if err_lines:
                return err_lines.pop(0)
            return b""

        stdout = AsyncMock()
        stdout.readline = AsyncMock(side_effect=_readline_out)
        proc.stdout = stdout

        stderr = AsyncMock()
        stderr.readline = AsyncMock(side_effect=_readline_err)
        proc.stderr = stderr
        return proc

    async def test_start_and_stop_lifecycle_with_secret(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        proc = self._mock_subprocess()

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                await supervisor.start(secret=b"test-secret-123")
                assert supervisor.is_running is True
                assert supervisor._secret_file is not None
                assert supervisor._secret_file.exists()
                assert supervisor.status in (ExposureStatus.STARTING, ExposureStatus.ACTIVE)

                await supervisor.stop()
                assert supervisor.status == ExposureStatus.STOPPED
                assert supervisor._secret_file is None
        finally:
            if supervisor.is_running or supervisor._secret_file is not None:
                await supervisor.stop()

    async def test_claim_url_detection(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        claim_output = [
            b"Starting playit agent in claim mode...\n",
            b"Claim URL: https://playit.gg/claim/abc123xyz\n",
        ]
        proc = self._mock_subprocess(stdout_lines=claim_output)

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                await supervisor.start(secret=None)
                await asyncio.sleep(0.05)
                assert supervisor.claim_code == "abc123xyz"
                assert supervisor.claim_url == "https://playit.gg/claim/abc123xyz"
                assert supervisor.status == ExposureStatus.CLAIM_REQUIRED
        finally:
            await supervisor.stop()

    async def test_auth_failure_marker_detection(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        err_output = [
            b"connecting to playit tunnel...\n",
            b"error: invalid secret or authorization revoked\n",
        ]
        proc = self._mock_subprocess(stdout_lines=err_output)

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                await supervisor.start(secret=b"bad-secret")
                await asyncio.sleep(0.05)
                assert supervisor.status == ExposureStatus.RECLAIM_REQUIRED
        finally:
            await supervisor.stop()

    async def test_restart_supervision(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        proc1 = self._mock_subprocess()
        proc2 = self._mock_subprocess()

        try:
            with patch("asyncio.create_subprocess_exec", side_effect=[proc1, proc2]):
                await supervisor.start(secret=b"secret-1")
                assert supervisor.is_running is True

                await supervisor.restart(secret=b"secret-2")
                assert supervisor.is_running is True
        finally:
            await supervisor.stop()

    async def test_claim_secret_capture(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        captured_secret = None

        async def _on_secret(sec: str) -> None:
            nonlocal captured_secret
            captured_secret = sec

        exchange_output = [
            b"Open this link to finish setting up playit:\n",
            b"https://playit.gg/claim/testclaim123\n",
            b"secret: my_super_secret_playit_key_1234567890\n",
        ]
        proc = self._mock_subprocess(stdout_lines=exchange_output)

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                await supervisor.start(claim_code="testclaim123", on_secret=_on_secret)
                await asyncio.sleep(0.05)
                assert captured_secret == "my_super_secret_playit_key_1234567890"
        finally:
            await supervisor.stop()

    async def test_claim_bare_64_hex_secret_capture(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        captured_secret = None

        async def _on_secret(sec: str) -> None:
            nonlocal captured_secret
            captured_secret = sec

        exchange_output = [
            b"Open this link to finish setting up playit:\n",
            b"https://playit.gg/claim/6cf8d96f0f\n",
            b"Program approved. Finishing setup...\n",
            b"d08c824254113c9cccb943435abd2bcb70f54bcb45b56bc8ede3809988d1d88c\n",
        ]
        proc = self._mock_subprocess(stdout_lines=exchange_output)

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                await supervisor.start(claim_code="6cf8d96f0f", on_secret=_on_secret)
                await asyncio.sleep(0.05)
                assert (
                    captured_secret
                    == "d08c824254113c9cccb943435abd2bcb70f54bcb45b56bc8ede3809988d1d88c"
                )
        finally:
            await supervisor.stop()

    async def test_claim_code_change_forces_restart(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        proc1 = self._mock_subprocess(pid=1001)
        proc2 = self._mock_subprocess(pid=1002)

        try:
            with patch("asyncio.create_subprocess_exec", side_effect=[proc1, proc2]):
                await supervisor.start(claim_code="code-1")
                assert supervisor.is_running is True
                assert supervisor.claim_code == "code-1"
                assert supervisor._process.pid == 1001

                # Re-starting with a new claim code must trigger restart and spawn proc2
                await supervisor.start(claim_code="code-2")
                assert supervisor.is_running is True
                assert supervisor.claim_code == "code-2"
                assert supervisor._process.pid == 1002
        finally:
            await supervisor.stop()

    async def test_stderr_error_capture_concurrent(self) -> None:
        supervisor = PlayitAgentSupervisor(health_interval=0.1)
        stderr_output = [
            b"connecting...\n",
            b"error: unauthorized claim expired\n",
        ]
        proc = self._mock_subprocess(stdout_lines=[], stderr_lines=stderr_output)

        try:
            with patch("asyncio.create_subprocess_exec", return_value=proc):
                await supervisor.start(claim_code="expiredcode")
                await asyncio.sleep(0.05)
                assert supervisor.status == ExposureStatus.RECLAIM_REQUIRED
        finally:
            await supervisor.stop()
