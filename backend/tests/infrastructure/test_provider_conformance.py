from __future__ import annotations

import inspect
import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import MCSError, ProviderError
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
    provider_factory,
)
from app.modules.server.infrastructure.providers.circuit_breaker_wrapper import (
    CircuitBreakerProviderWrapper,
)
from app.modules.server.infrastructure.providers.cloud import (
    CloudProvider,
    CloudProviderStub,
)
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.server.infrastructure.providers.local import LocalLinuxProvider
from app.modules.server.infrastructure.providers.local_windows import LocalWindowsProvider
from app.modules.server.infrastructure.providers.remote import SSHProvider

CANONICAL_CAPABILITIES = frozenset({"process", "console", "exec"})


def create_mocked_provider(name: str) -> ServerProvider:
    """Create a provider instance suitable for mock contract testing."""
    if name == "local_linux":
        mock_fs = MagicMock()
        mock_fs.exists.return_value = True
        return LocalLinuxProvider(fs=mock_fs)
    elif name == "local_windows":
        return LocalWindowsProvider()
    elif name == "docker":
        return DockerProvider()
    elif name == "cloud":
        return CloudProviderStub()
    elif name == "circuit_breaker":
        mock_inner = LocalLinuxProvider(fs=MagicMock())
        return CircuitBreakerProviderWrapper(wrapped=mock_inner)
    elif name == "ssh":
        return SSHProvider(host="127.0.0.1", port=22, username="test-user")
    raise ValueError(f"Unknown provider: {name}")


ALL_PROVIDER_NAMES = [
    "local_linux",
    "local_windows",
    "docker",
    "cloud",
    "circuit_breaker",
    "ssh",
]


@pytest.fixture(params=ALL_PROVIDER_NAMES)
def provider_name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def provider(provider_name: str) -> ServerProvider:
    return create_mocked_provider(provider_name)


@pytest.fixture(autouse=True)
def _mock_provider_io(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Generator[None, None, None]:
    """Universal I/O sandbox for provider conformance tests."""
    if "docker" in request.keywords and os.environ.get("RUN_DOCKER_TESTS") == "1":
        yield
        return

    dynamic_pid = 54321 + (abs(hash(request.node.name)) % 10000)
    recorded_kills: list[tuple[int, int]] = []

    def _record_kill(pid: int, sig: int) -> None:
        recorded_kills.append((pid, sig))

    request.node.dynamic_pid = dynamic_pid
    request.node.recorded_kills = recorded_kills

    mock_conn = MagicMock()
    mock_conn.run = AsyncMock(
        return_value=MagicMock(returncode=0, stdout=f"{dynamic_pid}\n", stderr="")
    )

    async def _fake_docker_cmd(*args: object, **_kwargs: object) -> tuple[int, str]:
        if not args:
            return (0, "")
        cmd = args[0]
        if cmd == "inspect":
            if "--format" in args and "{{json .}}" in args:
                return (1, "")
            return (0, f"{dynamic_pid} 172.17.0.5\n")
        return (0, "linux\n")

    with (
        patch.dict(
            os.environ,
            {"MCS_SERVERS_DATA_DIR": str(tmp_path), "ONX_SERVERS_DATA_DIR": str(tmp_path)},
        ),
        patch("os.kill", side_effect=_record_kill),
        patch.object(DockerProvider, "_docker_command", AsyncMock(side_effect=_fake_docker_cmd)),
        patch.object(DockerProvider, "_ensure_image", AsyncMock()),
        patch.object(
            LocalLinuxProvider,
            "_run_command_with_output",
            AsyncMock(return_value=(0, f"{dynamic_pid}\n")),
        ),
        patch.object(LocalLinuxProvider, "_verify_port_free", AsyncMock()),
        patch.object(LocalLinuxProvider, "_is_pid_alive", AsyncMock(return_value=False)),
        patch.object(LocalWindowsProvider, "_verify_port_free", AsyncMock()),
        patch.object(SSHProvider, "_get_connection", AsyncMock(return_value=mock_conn)),
        patch(
            "asyncio.create_subprocess_exec",
            AsyncMock(return_value=MagicMock(pid=dynamic_pid)),
        ),
        patch("asyncio.sleep", AsyncMock()),
        patch("app.modules.server.infrastructure.providers.local.asyncio.sleep", AsyncMock()),
    ):
        yield


@pytest.fixture
def standard_deployment(tmp_path: Path) -> ServerDeployment:
    server_dir = tmp_path / "test-srv"
    server_dir.mkdir(parents=True, exist_ok=True)
    return ServerDeployment(
        location_type=LocationType.LOCAL,
        root_path=str(server_dir),
        startup_jar="server.jar",
        startup_command="java -jar server.jar",
    )


@pytest.fixture
def standard_launch_config() -> LaunchConfiguration:
    return LaunchConfiguration(
        java_executable="java",
        startup_jar="server.jar",
        startup_command=["java", "-jar", "server.jar"],
    )


@pytest.fixture
def standard_handle(provider: ServerProvider) -> ServerHandle:
    return ServerHandle(
        provider=provider.provider_type,
        server_id="test-srv",
        external_id=f"onx-test-srv-{provider.provider_type}",
        metadata={"managed": True},
    )


class TestProviderClassConformance:
    """Validate that all concrete providers strictly comply with ServerProvider ABC."""

    def test_isinstance_server_provider(self, provider: ServerProvider) -> None:
        """Provider must be an instance of ServerProvider."""
        assert isinstance(provider, ServerProvider)
        assert issubclass(provider.__class__, ServerProvider)

    def test_provider_type_contract(self, provider: ServerProvider) -> None:
        """provider_type must be a non-empty string."""
        ptype = provider.provider_type
        assert isinstance(ptype, str)
        assert len(ptype.strip()) > 0

    def test_capabilities_contract(self, provider: ServerProvider) -> None:
        """capabilities() must return a list of strings within canonical vocabulary."""
        caps = provider.capabilities()
        assert isinstance(caps, list)
        for cap in caps:
            assert isinstance(cap, str)
            assert cap in CANONICAL_CAPABILITIES, (
                f"Unknown capability '{cap}' returned by {provider}"
            )

    def test_start_signature_has_four_kwargs(self, provider: ServerProvider) -> None:
        """start() must accept server_id, config, deployment, launch_config."""
        sig = inspect.signature(provider.start)
        params = sig.parameters

        assert "server_id" in params, f"{provider} start() missing server_id"
        assert "config" in params, f"{provider} start() missing config"
        assert "deployment" in params, f"{provider} start() missing deployment"
        assert "launch_config" in params, f"{provider} start() missing launch_config"

        # config, deployment, launch_config must have defaults (optional kwargs)
        assert params["config"].default is not inspect.Parameter.empty
        assert params["deployment"].default is not inspect.Parameter.empty
        assert params["launch_config"].default is not inspect.Parameter.empty

    def test_stop_signature_conformance(self, provider: ServerProvider) -> None:
        """stop() must accept handle and optional force flag."""
        sig = inspect.signature(provider.stop)
        params = sig.parameters

        assert "handle" in params
        assert "force" in params
        assert params["force"].default is not inspect.Parameter.empty

    def test_status_signature_conformance(self, provider: ServerProvider) -> None:
        """status() must accept handle parameter."""
        sig = inspect.signature(provider.status)
        assert "handle" in sig.parameters

    def test_console_signature_conformance(self, provider: ServerProvider) -> None:
        """console() must accept handle and tail parameter."""
        sig = inspect.signature(provider.console)
        assert "handle" in sig.parameters
        assert "tail" in sig.parameters
        assert sig.parameters["tail"].default is not inspect.Parameter.empty

    def test_execute_command_signature_conformance(self, provider: ServerProvider) -> None:
        """execute_command() must accept handle and command parameter."""
        sig = inspect.signature(provider.execute_command)
        assert "handle" in sig.parameters
        assert "command" in sig.parameters

    def test_destroy_signature_conformance(self, provider: ServerProvider) -> None:
        """destroy() must accept handle parameter."""
        sig = inspect.signature(provider.destroy)
        assert "handle" in sig.parameters


class TestProviderRuntimeExecutionContract:
    """Validate runtime method execution contracts with mocked I/O."""

    @pytest.mark.asyncio
    async def test_ping_returns_boolean(self, provider: ServerProvider) -> None:
        """ping() must return a boolean without raising unexpected exceptions."""
        res = await provider.ping()
        assert isinstance(res, bool)

    @pytest.mark.asyncio
    async def test_start_accepts_all_kwargs_without_type_error(
        self,
        provider: ServerProvider,
        standard_deployment: ServerDeployment,
        standard_launch_config: LaunchConfiguration,
    ) -> None:
        """start() must execute with all 4 keyword arguments without raising TypeError."""
        try:
            result = await provider.start(
                server_id="test-srv",
                config={"server_id": "test-srv", "port": 25565},
                deployment=standard_deployment,
                launch_config=standard_launch_config,
            )
            assert isinstance(result, DeploymentResult)
        except NotImplementedError:
            # CloudProvider explicitly raises NotImplementedError for unprovisioned VMs
            assert isinstance(provider, (CloudProvider, CloudProviderStub))

    @pytest.mark.asyncio
    async def test_destroy_graceful_completion(
        self,
        request: pytest.FixtureRequest,
        provider: ServerProvider,
        standard_handle: ServerHandle,
    ) -> None:
        """destroy() must complete cleanly or raise expected ProviderError/NotImplementedError."""
        try:
            await provider.destroy(standard_handle)
        except NotImplementedError:
            assert isinstance(provider, (CloudProvider, CloudProviderStub))
        except ProviderError:
            pass  # Acceptable domain error under failure simulation

        if provider.provider_type == "local":
            expected_pid = getattr(request.node, "dynamic_pid", None)
            recorded = getattr(request.node, "recorded_kills", [])
            assert any(pid == expected_pid for pid, _ in recorded)

    @pytest.mark.asyncio
    async def test_status_returns_runtime_enum(
        self,
        provider: ServerProvider,
        standard_handle: ServerHandle,
    ) -> None:
        """status() must return a ServerRuntimeStatus enum member."""
        try:
            st = await provider.status(standard_handle)
            assert isinstance(st, ServerRuntimeStatus)
        except NotImplementedError:
            assert isinstance(provider, (CloudProvider, CloudProviderStub))

    @pytest.mark.asyncio
    async def test_base_helper_methods_conformance(
        self,
        provider: ServerProvider,
        standard_handle: ServerHandle,
    ) -> None:
        """Default base methods from ServerProvider must function consistently."""
        with patch.object(provider, "status", AsyncMock(return_value=ServerRuntimeStatus.RUNNING)):
            # wait_ready returns bool
            ready = await provider.wait_ready("test-srv", standard_handle, timeout=5.0)
            assert isinstance(ready, bool)

            # verify_process returns bool
            verified = await provider.verify_process(standard_handle)
            assert isinstance(verified, bool)

            # collect_diagnostics returns RuntimeDiagnostics with matching provider
            diag = await provider.collect_diagnostics(standard_handle)
            assert diag.provider == provider.provider_type

            # get_runtime_pid returns int or None
            try:
                pid = await provider.get_runtime_pid(standard_handle)
                assert pid is None or isinstance(pid, int)
            except Exception:
                pass


class TestProviderExceptionContract:
    """Validate that operational failures follow the ProviderError / MCSError contract."""

    @pytest.mark.asyncio
    async def test_operational_failures_raise_provider_error(self) -> None:
        """Simulated operational errors in DockerProvider must raise ProviderError."""
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="fail-srv",
            external_id="onx-fail-srv",
        )

        with patch.object(
            provider,
            "_docker_command",
            AsyncMock(side_effect=ProviderError("docker", "console", "daemon died")),
        ):
            with pytest.raises(MCSError) as exc_info:
                await provider.console(handle)
            assert isinstance(exc_info.value, ProviderError)
            assert "docker" in str(exc_info.value)


class TestDefaultProviderFactoryConformance:
    """Validate that all providers registered in the default factory satisfy ServerProvider."""

    def test_default_factory_registrations(self) -> None:
        """Every provider in provider_factory must be a concrete ServerProvider."""
        types = provider_factory.list_types()
        assert "local" in types
        assert "local_windows" in types
        assert "docker" in types

        for ptype in types:
            prov = provider_factory.get(ptype)
            assert isinstance(prov, ServerProvider)
            assert prov.provider_type == ptype
            assert isinstance(prov.capabilities(), list)


class TestDockerLiveDaemonConformance:
    """Live Docker daemon tests, gated behind pytest mark 'docker'."""

    @pytest.mark.docker
    @pytest.mark.asyncio
    async def test_live_docker_daemon_ping(self) -> None:
        """Gated live test verifying real Docker daemon connectivity when enabled."""
        if os.environ.get("RUN_DOCKER_TESTS") != "1":
            pytest.skip("Skipping live Docker test: RUN_DOCKER_TESTS != '1'")

        provider = DockerProvider()
        ping_ok = await provider.ping()
        assert ping_ok is True, f"Live Docker daemon ping failed: {provider._last_ping_error}"
