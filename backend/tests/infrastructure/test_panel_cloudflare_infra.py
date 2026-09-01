"""Unit tests for Batch 7.2a panel infrastructure (Batch 7.2a).

Covers the config bind accessors (Decision 3), the Cloudflare API client
(tunnel/ingress/CNAME + auth-error mapping), and the cloudflared supervisor
(token-file handling, restart bound, health probe).
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import get_panel_bind, panel_ingress_target


@pytest.fixture(autouse=True)
def _clean_env():
    saved = {k: os.environ.get(k) for k in ("MCS_PANEL_BIND_HOST", "MCS_PANEL_BIND_PORT")}
    os.environ.pop("MCS_PANEL_BIND_HOST", None)
    os.environ.pop("MCS_PANEL_BIND_PORT", None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _reload_settings() -> None:
    pass


class TestPanelBind:
    def test_defaults(self) -> None:
        host, port = get_panel_bind()
        assert host == "127.0.0.1"
        assert port == 8000

    def test_env_override(self) -> None:
        os.environ["MCS_PANEL_BIND_HOST"] = "127.0.0.2"
        os.environ["MCS_PANEL_BIND_PORT"] = "9000"
        _reload_settings()
        try:
            host, port = get_panel_bind()
            assert host == "127.0.0.2"
            assert port == 9000
        finally:
            _reload_settings()

    def test_ingress_loopback(self) -> None:
        assert panel_ingress_target() == "http://127.0.0.1:8000"

    def test_ingress_localhost_normalized(self) -> None:
        os.environ["MCS_PANEL_BIND_HOST"] = "localhost"
        _reload_settings()
        try:
            assert panel_ingress_target() == "http://127.0.0.1:8000"
        finally:
            _reload_settings()

    def test_ingress_ipv6_loopback_normalized(self) -> None:
        os.environ["MCS_PANEL_BIND_HOST"] = "::1"
        _reload_settings()
        try:
            assert panel_ingress_target() == "http://127.0.0.1:8000"
        finally:
            _reload_settings()

    @pytest.mark.parametrize(
        "host",
        ["0.0.0.0", "::", "::0", "0:0:0:0:0:0:0:0", "", "192.168.1.10"],
    )
    def test_ingress_rejects_non_loopback(self, host: str) -> None:
        from app.core.exceptions import InvalidValueError

        os.environ["MCS_PANEL_BIND_HOST"] = host
        _reload_settings()
        try:
            with pytest.raises(InvalidValueError):
                panel_ingress_target()
        finally:
            _reload_settings()


class _FakeResponse:
    def __init__(self, body: dict, status: int = 200) -> None:
        self._body = body
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, **_kwargs):
        return self._body


class _FakeHttp:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        resp = self._responses.pop(0)
        return _FakeResponse(resp["body"], resp.get("status", 200))


_PATCH_GET_HTTP_CLIENT = "app.modules.exposure.infrastructure.cloudflare.get_http_client"


class TestCloudflareClient:
    async def test_create_named_tunnel(self) -> None:
        from app.modules.exposure.infrastructure.cloudflare import CloudflareClient

        http = _FakeHttp(
            {"body": {"success": True, "result": [{"id": "acc-1"}]}},
            {
                "body": {
                    "success": True,
                    "result": {"id": "tun-1", "token": "tok"},
                }
            },
        )
        with patch(_PATCH_GET_HTTP_CLIENT, return_value=http):
            client = CloudflareClient("tok")
            result = await client.create_named_tunnel(name="onx-panel-x.example.com")
        assert result.tunnel_id == "tun-1"
        assert result.token == "tok"
        assert http.calls[0][0] == "GET"
        assert http.calls[1][0] == "POST"

    async def test_configure_ingress_sends_catch_all(self) -> None:
        from app.modules.exposure.infrastructure.cloudflare import CloudflareClient

        http = _FakeHttp(
            {"body": {"success": True, "result": [{"id": "acc-1"}]}},
            {"body": {"success": True, "result": {}}},
        )
        with patch(_PATCH_GET_HTTP_CLIENT, return_value=http):
            client = CloudflareClient("tok")
            await client.configure_ingress(
                "tun-1",
                [
                    {"hostname": "x.example.com", "service": "http://127.0.0.1:8000"},
                    {"service": "http_status:404"},
                ],
            )
        _, _, kwargs = http.calls[1]
        payload = kwargs["json"]
        assert payload["config"]["ingress"][-1] == {"service": "http_status:404"}

    async def test_create_cname(self) -> None:
        from app.modules.exposure.infrastructure.cloudflare import CloudflareClient

        http = _FakeHttp(
            {"body": {"success": True, "result": [{"id": "zone-1"}]}},
            {"body": {"success": True, "result": {}}},
        )
        with patch(_PATCH_GET_HTTP_CLIENT, return_value=http):
            client = CloudflareClient("tok")
            await client.create_cname("panel.example.com", "tun-abc")
        _, _, kwargs = http.calls[1]
        payload = kwargs["json"]
        assert payload["type"] == "CNAME"
        assert payload["name"] == "panel.example.com"
        assert payload["content"] == "tun-abc.cfargotunnel.com"
        assert payload["proxied"] is True

    async def test_auth_error_code_maps_to_reclaim(self) -> None:
        from app.modules.exposure.infrastructure.cloudflare import (
            CloudflareAuthError,
            CloudflareClient,
        )

        http = _FakeHttp(
            {
                "body": {
                    "success": False,
                    "errors": [{"code": 10000, "message": "Authentication error"}],
                }
            }
        )
        with patch(_PATCH_GET_HTTP_CLIENT, return_value=http):
            client = CloudflareClient("tok")
            with pytest.raises(CloudflareAuthError):
                await client.create_named_tunnel(name="onx-panel-x.example.com")

    async def test_http_401_maps_to_reclaim(self) -> None:
        from app.modules.exposure.infrastructure.cloudflare import (
            CloudflareAuthError,
            CloudflareClient,
        )

        http = _FakeHttp({"body": {"success": False, "errors": []}, "status": 401})
        with patch(_PATCH_GET_HTTP_CLIENT, return_value=http):
            client = CloudflareClient("tok")
            with pytest.raises(CloudflareAuthError):
                await client.create_named_tunnel(name="onx-panel-x.example.com")

    async def test_other_error_maps_to_api_error(self) -> None:
        from app.modules.exposure.infrastructure.cloudflare import (
            CloudflareApiError,
            CloudflareClient,
        )

        http = _FakeHttp(
            {
                "body": {
                    "success": False,
                    "errors": [{"code": 81044, "message": "Zone not found"}],
                }
            }
        )
        with patch(_PATCH_GET_HTTP_CLIENT, return_value=http):
            client = CloudflareClient("tok")
            with pytest.raises(CloudflareApiError):
                await client.create_named_tunnel(name="onx-panel-x.example.com")


class TestCloudflaredSupervisor:
    @pytest.fixture(autouse=True)
    def _mock_os_signals(self):
        with (
            patch("os.kill", return_value=None) as mock_kill,
            patch("os.killpg", return_value=None, create=True) as mock_killpg,
        ):
            yield {"kill": mock_kill, "killpg": mock_killpg}

    async def test_token_file_permissions(self) -> None:
        from pathlib import Path

        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        supervisor = CloudflaredSupervisor()
        token_file = supervisor._write_token_file(b"secret-token")
        try:
            assert Path(token_file).exists()
            assert Path(token_file).stat().st_mode & 0o777 == 0o600
            assert Path(token_file).read_bytes() == b"secret-token"
        finally:
            await supervisor._delete_token_file()

    async def test_start_uses_token_file_flag(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        supervisor = CloudflaredSupervisor()
        process = AsyncMock()
        process.returncode = None
        process.pid = 99999
        process.stderr = None

        def fake_create(*_args, **_kwargs):
            return process

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_create)):
            await supervisor.start(b"tok")
        try:
            assert supervisor.is_running
            assert supervisor.status.value == "STARTING"
        finally:
            await supervisor.stop()

    async def test_restart_bound_reached(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        supervisor = CloudflaredSupervisor(max_restarts=2, backoff_base=0.01)
        supervisor._restart_count = 2
        process = AsyncMock()
        process.returncode = 1
        process.pid = 99999
        process.stderr = None
        supervisor._process = process

        try:
            await supervisor._handle_process_exit()
            assert supervisor.status.value == "ERROR"
            assert supervisor._stop_event.is_set()
        finally:
            supervisor._process = None

    async def test_auth_markers_detected(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        supervisor = CloudflaredSupervisor()
        markers = [
            b"2026/01/01 ERR failed to connect to the edge, error: Invalid access token\n",
            b"ERR  error code: 1033\n",
            b"unable to authenticate: invalid token provided\n",
        ]
        process = AsyncMock()
        process.returncode = None
        process.pid = 99999
        process.stderr = None

        def fake_create(*_args, **_kwargs):
            return process

        from unittest.mock import patch as _patch

        with _patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_create)):
            await supervisor.start(b"tok")
        try:
            reader = AsyncMock()
            reader.readline = AsyncMock(side_effect=[markers[0], b""])
            await supervisor._read_stderr(reader)
            assert supervisor.status.value == "RECLAIM_REQUIRED"
        finally:
            await supervisor.stop()

    async def test_is_running_reflects_process(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        supervisor = CloudflaredSupervisor()
        assert supervisor.is_running is False
        supervisor._process = AsyncMock()
        supervisor._process.returncode = None
        assert supervisor.is_running is True
        supervisor._process = None

    async def test_start_captures_real_command_vector(self) -> None:
        """VULN-118896 regression: the supervisor must spawn ``cloudflared tunnel
        run --token-file <path>`` and never pass the plaintext token via argv.

        This captures the REAL positional arguments passed to
        ``asyncio.create_subprocess_exec`` (not a status side-effect).
        """
        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        captured: list[tuple] = []

        def fake_create(*_args, **_kwargs):
            captured.append(_args)
            process = AsyncMock()
            process.returncode = None
            process.pid = 99999
            process.stderr = None
            return process

        supervisor = CloudflaredSupervisor()
        token = b"plaintext-tunnel-token-do-not-leak"
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_create)):
            await supervisor.start(token)
        try:
            assert captured, "create_subprocess_exec must be invoked"
            argv = list(captured[0])
            assert argv[0] == "cloudflared"
            assert argv[1] == "tunnel"
            assert argv[2] == "run"
            assert "--token-file" in argv
            flag_index = argv.index("--token-file")
            assert argv[flag_index + 1] == str(supervisor._token_file)
            assert "--token" not in argv
            assert token.decode("ascii") not in " ".join(argv)
        finally:
            await supervisor.stop()

    async def test_token_file_lifecycle(self) -> None:
        """start() creates a 0600 token file containing the token;
        stop() terminates the process group and removes the file."""
        from pathlib import Path

        from app.modules.exposure.infrastructure.cloudflared import CloudflaredSupervisor

        supervisor = CloudflaredSupervisor()

        def fake_create(*_args, **_kwargs):
            process = AsyncMock()
            process.returncode = None
            process.pid = 99999
            process.stderr = None
            return process

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=fake_create)):
            await supervisor.start(b"secret-token-value")
        try:
            token_file = supervisor._token_file
            assert token_file is not None
            assert Path(token_file).exists()
            assert Path(token_file).stat().st_mode & 0o777 == 0o600
            assert Path(token_file).read_bytes() == b"secret-token-value"

            await supervisor.stop()
            assert supervisor._token_file is None
            assert not Path(token_file).exists()
            assert supervisor.status == "STOPPED" or supervisor.status.value == "STOPPED"
        finally:
            if supervisor.is_running or supervisor._token_file is not None:
                await supervisor.stop()


class TestCloudflaredHealthProbe:
    """The health probe must try the documented metrics range (20241..20245)
    and accept the FIRST reachable endpoint (Batch 7.2a Deviation 2)."""

    def _fake_open(self, attempts, reject_first: bool = False):
        from unittest.mock import MagicMock

        from app.modules.exposure.infrastructure.cloudflared import _METRICS_PORTS

        def _open(host, port):
            attempts.append((host, port))
            if reject_first and port == _METRICS_PORTS[0]:
                raise ConnectionRefusedError()
            writer = AsyncMock()
            writer.close = MagicMock()
            return (AsyncMock(), writer)

        return _open

    async def test_healthy_first_port(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import (
            _METRICS_PORTS,
            CloudflaredSupervisor,
        )

        attempts: list[tuple[str, int]] = []
        supervisor = CloudflaredSupervisor()
        fake_open = self._fake_open(attempts)
        with patch("asyncio.open_connection", new=AsyncMock(side_effect=fake_open)):
            assert await supervisor._probe_health() is True
        assert attempts[0] == ("127.0.0.1", _METRICS_PORTS[0])

    async def test_healthy_alternate_port(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import (
            _METRICS_PORTS,
            CloudflaredSupervisor,
        )

        attempts: list[tuple[str, int]] = []
        supervisor = CloudflaredSupervisor()
        fake_open = self._fake_open(attempts, reject_first=True)
        with patch("asyncio.open_connection", new=AsyncMock(side_effect=fake_open)):
            assert await supervisor._probe_health() is True
        # The failed first port must not abort the probe; a later port wins.
        assert len(attempts) == 2
        assert attempts[0] == ("127.0.0.1", _METRICS_PORTS[0])
        assert attempts[1][1] == _METRICS_PORTS[1]

    async def test_no_port_reachable(self) -> None:
        from app.modules.exposure.infrastructure.cloudflared import (
            _METRICS_PORTS,
            CloudflaredSupervisor,
        )

        attempts: list[tuple[str, int]] = []
        supervisor = CloudflaredSupervisor()

        def _refuse(host, port):
            attempts.append((host, port))
            raise ConnectionRefusedError()

        with patch("asyncio.open_connection", new=AsyncMock(side_effect=_refuse)):
            assert await supervisor._probe_health() is False
        # The entire range was tried before concluding unhealthy.
        assert [p for _, p in attempts] == _METRICS_PORTS
