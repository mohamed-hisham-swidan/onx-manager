from __future__ import annotations

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ProviderFactory,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
    provider_factory,
)
from app.modules.server.infrastructure.providers.circuit_breaker_wrapper import (
    CircuitBreakerProviderWrapper,
)
from app.modules.server.infrastructure.providers.cloud import CloudProviderStub
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.server.infrastructure.providers.local import LocalLinuxProvider
from app.modules.server.infrastructure.providers.local_windows import LocalWindowsProvider
from app.modules.server.infrastructure.providers.remote import SSHProvider


class TestProviderFactory:
    def test_register_and_get(self) -> None:
        factory = ProviderFactory()
        provider = LocalLinuxProvider()
        factory.register(provider)
        assert factory.get("local") is provider
        assert "local" in factory.list_types()

    def test_get_unregistered_raises(self) -> None:
        factory = ProviderFactory()
        with pytest.raises(ValueError, match="No provider registered"):
            factory.get("nonexistent")

    def test_default_registrations(self) -> None:
        assert "local" in provider_factory.list_types()
        assert "local_windows" in provider_factory.list_types()
        assert "docker" in provider_factory.list_types()


class TestServerHandle:
    def test_create_handle(self) -> None:
        handle = ServerHandle(
            provider="local",
            server_id="s1",
            external_id="onx-s1",
            metadata={"key": "val"},
        )
        assert str(handle) == "local/s1:onx-s1"
        assert handle.metadata["key"] == "val"


class TestDeploymentResult:
    def test_create_result(self) -> None:
        result = DeploymentResult(
            status=ServerRuntimeStatus.RUNNING,
            address="127.0.0.1",
            port=25565,
            pid=1234,
            metadata={"key": "val"},
        )
        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 1234
        assert result.metadata["key"] == "val"


class TestCircuitBreakerWrapper:
    @pytest.mark.asyncio
    async def test_wraps_provider(self) -> None:
        inner = LocalLinuxProvider()
        wrapped = CircuitBreakerProviderWrapper(inner)
        assert wrapped.provider_type == "local"
        assert wrapped.wrapped is inner
        assert wrapped.breaker.name == "provider:local"

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_open(self) -> None:
        inner = LocalLinuxProvider()
        wrapped = CircuitBreakerProviderWrapper(inner)
        import time as t

        wrapped.breaker._state = wrapped.breaker._state.__class__.OPEN
        wrapped.breaker._failure_count = 5
        wrapped.breaker._last_failure_time = t.time()
        result = await wrapped.ping()
        assert result is False

    @pytest.mark.asyncio
    async def test_status_returns_unknown_on_open(self) -> None:
        inner = LocalLinuxProvider()
        handle = ServerHandle(provider="test", server_id="x", external_id="y")
        wrapped = CircuitBreakerProviderWrapper(inner)
        import time as t

        wrapped.breaker._state = wrapped.breaker._state.__class__.OPEN
        wrapped.breaker._failure_count = 5
        wrapped.breaker._last_failure_time = t.time()
        result = await wrapped.status(handle)
        assert result == ServerRuntimeStatus.UNKNOWN


class TestCloudProviderStub:
    @pytest.mark.asyncio
    async def test_stub_returns_false_ping(self) -> None:
        stub = CloudProviderStub()
        assert await stub.ping() is False

    @pytest.mark.asyncio
    async def test_stub_raises_start(self) -> None:
        stub = CloudProviderStub()
        with pytest.raises(NotImplementedError):
            await stub.start("test", {})

    @pytest.mark.asyncio
    async def test_provision_vm(self) -> None:
        from app.modules.server.infrastructure.providers.cloud import (
            CloudProviderType,
            CloudVMConfig,
        )

        stub = CloudProviderStub()
        config = CloudVMConfig(
            provider=CloudProviderType.AWS,
            region="us-east-1",
            instance_type="t3.medium",
            image="ami-123",
        )
        instance = await stub.provision_vm(config)
        assert instance.instance_id == "stub-instance"
        assert instance.public_ip == "127.0.0.1"


class TestProviderTypes:
    @pytest.mark.asyncio
    async def test_linux_provider_type(self) -> None:
        assert LocalLinuxProvider().provider_type == "local"

    @pytest.mark.asyncio
    async def test_windows_provider_type(self) -> None:
        assert LocalWindowsProvider().provider_type == "local_windows"

    @pytest.mark.asyncio
    async def test_docker_provider_type(self) -> None:
        assert DockerProvider().provider_type == "docker"

    @pytest.mark.asyncio
    async def test_ssh_provider_type(self) -> None:
        provider = SSHProvider(host="localhost")
        assert provider.provider_type == "ssh"

    @pytest.mark.asyncio
    async def test_cloud_provider_type(self) -> None:
        assert CloudProviderStub().provider_type == "cloud"


class TestLocalLinuxProviderStart:
    @pytest.mark.asyncio
    async def test_start_with_launch_config(self) -> None:
        provider = LocalLinuxProvider()
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command="",
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/onx/test-server",
        )

        from unittest.mock import MagicMock

        with patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)):
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()):
                with patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run:
                    with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)):
                        with patch.object(provider, "_fs", MagicMock()) as mock_fs:
                            result = await provider.start(
                                server_id="test-srv",
                                deployment=deployment,
                                launch_config=lc,
                            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 1234
        assert result.port == 25565
        cmd = mock_run.call_args[0][0]
        assert "tmux new-session" in cmd
        assert "java -Xms1024M -Xmx2048M" in cmd
        assert "-jar server.jar" in cmd

    @pytest.mark.asyncio
    async def test_start_without_launch_config_uses_config_dict(self) -> None:
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/onx/test-server",
        )
        config = {
            "java_args": ["-XX:+UseG1GC"],
            "memory_min_mb": 2048,
            "memory_max_mb": 4096,
            "port": 25566,
        }

        from unittest.mock import MagicMock

        with patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)):
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()):
                with patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run:
                    with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=5678)):
                        with patch.object(provider, "_fs", MagicMock()):
                            result = await provider.start(
                                server_id="test-srv-2",
                                config=config,
                                deployment=deployment,
                                launch_config=None,
                            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 5678
        assert result.port == 25566
        cmd = mock_run.call_args[0][0]
        assert "-Xms2048M" in cmd
        assert "-Xmx4096M" in cmd
        assert "-XX:+UseG1GC" in cmd

    @pytest.mark.asyncio
    async def test_start_launch_config_with_startup_command(self) -> None:
        provider = LocalLinuxProvider()
        lc = LaunchConfiguration(
            java_executable="/usr/lib/jvm/java-21/bin/java",
            startup_command="cd /srv && java -jar paper.jar nogui",
            startup_jar="irrelevant.jar",
        )
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/srv/minecraft",
        )

        from unittest.mock import MagicMock

        with patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)):
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()):
                with patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run:
                    with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=999)):
                        with patch.object(provider, "_fs", MagicMock()):
                            result = await provider.start(
                                server_id="test-cmd",
                                deployment=deployment,
                                launch_config=lc,
                            )

        cmd = mock_run.call_args[0][0]
        assert "cd /srv/minecraft && cd /srv && java -jar paper.jar nogui" in cmd

    @pytest.mark.asyncio
    async def test_start_tmux_failure_raises(self) -> None:
        from unittest.mock import MagicMock

        provider = LocalLinuxProvider()
        deployment = ServerDeployment(location_type=LocationType.LOCAL, root_path="/tmp/x")
        with patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)):
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()):
                with patch.object(provider, "_run_command", AsyncMock(return_value=1)):
                    with patch.object(provider, "_fs", MagicMock()):
                        from app.core.exceptions import ProviderError

                        with pytest.raises(ProviderError, match="tmux session creation failed"):
                            await provider.start(server_id="fail", deployment=deployment)


class TestLocalLinuxProviderWaitReady:
    @pytest.mark.asyncio
    async def test_wait_ready_done_found(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s1", external_id="onx-s1")

        with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=True)):
            with patch.object(
                provider,
                "console",
                AsyncMock(return_value=["line1", 'Done (10.234s)! For help, type "help"']),
            ):
                ready = await provider.wait_ready("s1", handle, timeout=5)
        assert ready is True

    @pytest.mark.asyncio
    async def test_wait_ready_session_missing(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s2", external_id="onx-s2")

        with patch.object(provider, "console", AsyncMock(return_value=[])):
            with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=False)):
                ready = await provider.wait_ready("s2", handle, timeout=5)
        assert ready is False

    @pytest.mark.asyncio
    async def test_wait_ready_pid_is_none(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s3", external_id="onx-s3")

        with patch.object(provider, "console", AsyncMock(return_value=[])):
            with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=True)):
                with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=None)):
                    ready = await provider.wait_ready("s3", handle, timeout=5)
        assert ready is False

    @pytest.mark.asyncio
    async def test_wait_ready_pid_dead(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s4", external_id="onx-s4")

        with patch.object(provider, "console", AsyncMock(return_value=[])):
            with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=True)):
                with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=5555)):
                    with patch.object(provider, "_is_pid_alive", AsyncMock(return_value=False)):
                        ready = await provider.wait_ready("s4", handle, timeout=5)
        assert ready is False

    @pytest.mark.asyncio
    async def test_wait_ready_deadline_exceeded(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s5", external_id="onx-s5")

        with patch.object(provider, "console", AsyncMock(return_value=[])):
            with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=True)):
                with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=6666)):
                    with patch.object(provider, "_is_pid_alive", AsyncMock(return_value=True)):
                        ready = await provider.wait_ready("s5", handle, timeout=0.1)
        assert ready is False

    @pytest.mark.asyncio
    async def test_wait_ready_console_failure_logged(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s6", external_id="onx-s6")

        with patch.object(provider, "console", AsyncMock(side_effect=RuntimeError("tmux error"))):
            with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=True)):
                with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=7777)):
                    with patch.object(provider, "_is_pid_alive", AsyncMock(return_value=False)):
                        ready = await provider.wait_ready("s6", handle, timeout=0.1)
        assert ready is False


class TestLocalLinuxProviderStop:
    @pytest.mark.asyncio
    async def test_stop_process_already_gone(self) -> None:
        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s7", external_id="onx-s7")

        with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=None)):
            with patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run:
                await provider.stop(handle, force=True)

        cmd = mock_run.call_args[0][0]
        assert "tmux kill-session" in cmd

    @pytest.mark.asyncio
    async def test_stop_process_lookup_error_on_sigterm(self) -> None:
        import signal

        provider = LocalLinuxProvider()
        handle = ServerHandle(provider="local", server_id="s8", external_id="onx-s8")

        def kill_side_effect(pid, sig):
            if sig == signal.SIGTERM:
                raise ProcessLookupError()
            if sig == signal.SIGKILL:
                raise ProcessLookupError()

        with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=8888)):
            with patch.object(provider, "_run_command", AsyncMock(return_value=0)):
                with patch(
                    "app.modules.server.infrastructure.providers.local.os.kill",
                    side_effect=kill_side_effect,
                ):
                    await provider.stop(handle, force=True)


class TestLocalLinuxProviderPreFlight:
    @pytest.mark.asyncio
    async def test_verify_port_free_success(self) -> None:
        provider = LocalLinuxProvider()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        result = await provider._verify_port_free(free_port, "srv1")
        assert result is None

    @pytest.mark.asyncio
    async def test_verify_port_free_in_use(self) -> None:
        provider = LocalLinuxProvider()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            s.listen()
            port = s.getsockname()[1]
            from app.core.exceptions import ProviderError

            with pytest.raises(ProviderError, match="already in use"):
                await provider._verify_port_free(port, "srv1")

    @pytest.mark.asyncio
    async def test_cleanup_stale_tmux_exists(self) -> None:
        provider = LocalLinuxProvider()
        with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=True)):
            with patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run:
                await provider._cleanup_stale_tmux("onx-srv1")
        cmd = mock_run.call_args[0][0]
        assert "tmux kill-session" in cmd
        assert "onx-srv1" in cmd

    @pytest.mark.asyncio
    async def test_cleanup_stale_tmux_not_exists(self) -> None:
        provider = LocalLinuxProvider()
        with patch.object(provider, "_tmux_has_session", AsyncMock(return_value=False)):
            with patch.object(provider, "_run_command", AsyncMock()) as mock_run:
                await provider._cleanup_stale_tmux("onx-srv1")
        mock_run.assert_not_called()

    @pytest.mark.asyncio
    async def test_find_java_processes_found(self) -> None:
        provider = LocalLinuxProvider()
        fake_ps_output = "12345\n67890\n"
        with patch.object(
            provider, "_run_command_with_output", AsyncMock(return_value=(0, fake_ps_output))
        ):
            pids = await provider._find_java_processes("/srv/minecraft")
        assert pids == [12345, 67890]

    @pytest.mark.asyncio
    async def test_find_java_processes_not_found(self) -> None:
        provider = LocalLinuxProvider()
        with patch.object(provider, "_run_command_with_output", AsyncMock(return_value=(0, ""))):
            pids = await provider._find_java_processes("/srv/nonexistent")
        assert pids == []

    @pytest.mark.asyncio
    async def test_kill_processes(self) -> None:
        import signal

        provider = LocalLinuxProvider()
        with patch("app.modules.server.infrastructure.providers.local.os.kill") as mock_kill:
            await provider._kill_processes([1001, 1002])
        assert mock_kill.call_count == 4  # SIGTERM + SIGKILL per PID
        assert mock_kill.call_args_list[0][0] == (1001, signal.SIGTERM)
        assert mock_kill.call_args_list[1][0] == (1002, signal.SIGTERM)
        assert mock_kill.call_args_list[2][0] == (1001, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_kill_processes_skips_gone(self) -> None:
        provider = LocalLinuxProvider()
        with patch(
            "app.modules.server.infrastructure.providers.local.os.kill",
            side_effect=ProcessLookupError,
        ):
            await provider._kill_processes([9999])

    @pytest.mark.asyncio
    async def test_start_cleans_up_stale_tmux(self) -> None:
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(location_type=LocationType.LOCAL, root_path="/tmp/onx/test")
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command="",
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        with patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)):
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()) as mock_clean:
                with patch.object(provider, "_run_command", AsyncMock(return_value=0)):
                    with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)):
                        with patch.object(provider, "_fs", MagicMock()):
                            await provider.start(
                                server_id="srv-clean",
                                deployment=deployment,
                                launch_config=lc,
                            )
        mock_clean.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_verifies_port(self) -> None:
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(location_type=LocationType.LOCAL, root_path="/tmp/onx/test")
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command="",
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        with patch.object(provider, "_verify_port_free", AsyncMock()) as mock_verify:
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()):
                with patch.object(provider, "_run_command", AsyncMock(return_value=0)):
                    with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)):
                        with patch.object(provider, "_fs", MagicMock()):
                            await provider.start(
                                server_id="srv-port",
                                deployment=deployment,
                                launch_config=lc,
                            )
        mock_verify.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_port_contested_raises(self) -> None:
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(location_type=LocationType.LOCAL, root_path="/tmp/onx/test")
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command="",
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        from app.core.exceptions import ProviderError

        with patch.object(
            provider,
            "_verify_port_free",
            AsyncMock(side_effect=ProviderError("local", "start", "Port in use")),
        ):
            with patch.object(provider, "_fs", MagicMock()):
                with pytest.raises(ProviderError, match="Port in use"):
                    await provider.start(
                        server_id="srv-contested",
                        deployment=deployment,
                        launch_config=lc,
                    )

    @pytest.mark.asyncio
    async def test_start_process_dies_immediately(self) -> None:
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(location_type=LocationType.LOCAL, root_path="/tmp/onx/test")
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command="",
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        from app.core.exceptions import ProviderError

        with patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)):
            with patch.object(provider, "_cleanup_stale_tmux", AsyncMock()):
                with patch.object(provider, "_run_command", AsyncMock(side_effect=[0, 0])):
                    with patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=None)):
                        with patch.object(
                            provider, "_find_java_processes", AsyncMock(return_value=[1111, 2222])
                        ):
                            with patch.object(
                                provider, "_kill_processes", AsyncMock()
                            ) as mock_kill:
                                with patch.object(provider, "_fs", MagicMock()):
                                    with pytest.raises(ProviderError, match="died immediately"):
                                        await provider.start(
                                            server_id="srv-dies",
                                            deployment=deployment,
                                            launch_config=lc,
                                        )
        mock_kill.assert_awaited_once_with([1111, 2222])


class TestProviderCapabilities:
    def test_base_provider_default_capabilities(self) -> None:
        class DummyProvider(ServerProvider):
            @property
            def provider_type(self) -> str:
                return "dummy"

            async def ping(self) -> bool:
                return True

            async def start(self, *args, **kwargs):
                pass

            async def stop(self, *args, **kwargs):
                pass

            async def status(self, *args, **kwargs):
                pass

            async def console(self, *args, **kwargs):
                pass

            async def execute_command(self, *args, **kwargs):
                pass

            async def destroy(self, *args, **kwargs):
                pass

        assert DummyProvider().capabilities() == []
        assert CloudProviderStub().capabilities() == []

    def test_local_linux_provider_capabilities(self) -> None:
        capabilities = LocalLinuxProvider().capabilities()
        assert capabilities == ["process", "console", "exec"]
        assert "filesystem" not in capabilities
        assert "docker" not in capabilities

    def test_local_windows_provider_capabilities(self) -> None:
        capabilities = LocalWindowsProvider().capabilities()
        assert capabilities == ["process", "console", "exec"]
        assert "powershell" not in capabilities

    def test_docker_provider_capabilities(self) -> None:
        capabilities = DockerProvider().capabilities()
        assert capabilities == ["process", "console", "exec"]
        assert "docker" not in capabilities
        assert "logs" not in capabilities

    def test_circuit_breaker_wrapper_delegates_capabilities(self) -> None:
        inner = LocalLinuxProvider()
        wrapped = CircuitBreakerProviderWrapper(inner)
        assert wrapped.capabilities() == ["process", "console", "exec"]


class TestDockerProvider:
    @pytest.mark.asyncio
    async def test_start_creates_container_with_ownership_labels(self) -> None:
        provider = DockerProvider()
        config = {
            "image": "itzg/minecraft-server:latest",
            "port": 25565,
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with patch.object(provider, "_ensure_image", AsyncMock()) as mock_ensure:
            with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
                mock_docker.side_effect = [
                    (0, ""),  # create
                    (0, ""),  # start
                    (0, "12345\n"),  # inspect pid
                ]
                result = await provider.start(server_id="test-server-42", config=config)

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 12345
        assert result.port == 25565
        mock_ensure.assert_awaited_once_with("itzg/minecraft-server:latest")

        create_call_args = mock_docker.call_args_list[0][0][0]
        assert "create --name onx-test-server-42" in create_call_args
        assert "--label com.onx-manager.managed=true" in create_call_args
        assert "--label com.onx-manager.server_id=test-server-42" in create_call_args
        assert "--label com.onx-manager.runtime=docker" in create_call_args
