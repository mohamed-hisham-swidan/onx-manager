from __future__ import annotations

import socket
import sys
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

    @pytest.mark.asyncio
    async def test_start_forwards_all_four_arguments(self) -> None:
        inner = MagicMock(spec=ServerProvider)
        inner.start = AsyncMock(
            return_value=DeploymentResult(
                status=ServerRuntimeStatus.RUNNING,
                address="127.0.0.1",
                port=25565,
                pid=123,
            )
        )
        inner.provider_type = "mock"
        wrapped = CircuitBreakerProviderWrapper(inner)

        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/test",
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
        )
        config = {"port": 25565}

        result = await wrapped.start(
            server_id="srv-1",
            config=config,
            deployment=deployment,
            launch_config=lc,
        )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 123
        inner.start.assert_awaited_once_with(
            server_id="srv-1",
            config=config,
            deployment=deployment,
            launch_config=lc,
        )

    @pytest.mark.asyncio
    async def test_start_defaults_optional_arguments(self) -> None:
        inner = MagicMock(spec=ServerProvider)
        inner.start = AsyncMock(
            return_value=DeploymentResult(
                status=ServerRuntimeStatus.RUNNING,
                address="127.0.0.1",
                port=25565,
                pid=456,
            )
        )
        inner.provider_type = "mock"
        wrapped = CircuitBreakerProviderWrapper(inner)

        result = await wrapped.start(server_id="srv-2")

        assert result.status == ServerRuntimeStatus.RUNNING
        inner.start.assert_awaited_once_with(
            server_id="srv-2",
            config=None,
            deployment=None,
            launch_config=None,
        )


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
    async def test_stub_raises_start_with_four_kwargs(self) -> None:
        stub = CloudProviderStub()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/cloud",
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
        )
        with pytest.raises(NotImplementedError, match="CloudProvider.start requires a provisioned VM"):
            await stub.start(
                server_id="test",
                config={"port": 25565},
                deployment=deployment,
                launch_config=lc,
            )

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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "LocalLinuxProvider is POSIX-only; Windows uses "
        "LocalWindowsProvider (see test_local_windows_provider.py)"
    ),
)
class TestLocalLinuxProviderStart:
    @pytest.mark.asyncio
    async def test_start_with_launch_config(self) -> None:
        provider = LocalLinuxProvider()
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
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
            startup_command=["bash", "run.sh", "nogui"],
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
        assert "cd /srv/minecraft && bash run.sh nogui" in cmd

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

    @pytest.mark.asyncio
    async def test_local_provider_start_quotes_all_jvm_args(self) -> None:
        import shlex

        provider = LocalLinuxProvider()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/onx/test server dir",
        )
        lc = LaunchConfiguration(
            java_executable="/usr/lib/jvm/java 21/bin/java",
            jvm_flags=(
                '-XX:OnOutOfMemoryError="kill -9 %p"',
                '-Dproperty="hello world"',
                "-Dcustom.msg=welcome to minecraft",
            ),
            startup_jar="server.jar",
        )
        config = {
            "memory_min_mb": 2048,
            "memory_max_mb": 4096,
            "port": 25565,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
            patch.object(provider, "_fs", MagicMock()),
        ):
            result = await provider.start(
                server_id="test-quoting",
                config=config,
                deployment=deployment,
                launch_config=lc,
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 1234
        full_cmd = mock_run.call_args[0][0]

        expected_tokens = [
            "/usr/lib/jvm/java 21/bin/java",
            '-XX:OnOutOfMemoryError="kill -9 %p"',
            '-Dproperty="hello world"',
            "-Dcustom.msg=welcome to minecraft",
            "-jar",
            "server.jar",
            "nogui",
            "-Xms2048M",
            "-Xmx4096M",
        ]
        expected_inner_cmd = " ".join(shlex.quote(t) for t in expected_tokens)
        expected_pane_cmd = (
            f"cd {shlex.quote('/tmp/onx/test server dir')} && exec {expected_inner_cmd}"
        )

        tmux_parts = shlex.split(full_cmd)
        assert tmux_parts[0] == "tmux"
        assert tmux_parts[1] == "new-session"
        assert tmux_parts[2] == "-d"
        assert tmux_parts[3] == "-s"
        assert tmux_parts[4] == "onx-test-quoting"
        assert tmux_parts[5].endswith(expected_pane_cmd)

    @pytest.mark.asyncio
    async def test_local_provider_start_legacy_path_quotes_all_jvm_args(self) -> None:
        import shlex

        from app.core.identity import IDENTITY

        provider = LocalLinuxProvider()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/onx/test server dir",
        )

        flags_list = [
            '-XX:OnOutOfMemoryError="kill -9 %p"',
            '-Dproperty="hello world"',
            "-Dcustom.msg=welcome to minecraft",
        ]
        config_list = {
            "java_args": flags_list,
            "memory_min_mb": 2048,
            "memory_max_mb": 4096,
            "port": 25565,
        }

        fixed_uuid_1 = MagicMock(hex="0123456789abcdef0123456789abcdef")
        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
            patch.object(provider, "_fs", MagicMock()),
            patch(
                "app.modules.server.infrastructure.providers.local.uuid.uuid4",
                return_value=fixed_uuid_1,
            ),
        ):
            await provider.start(
                server_id="test-legacy-list",
                config=config_list,
                deployment=deployment,
                launch_config=None,
            )

        captured_list_cmd = mock_run.call_args[0][0]
        session_list = f"{IDENTITY.temp_prefix_new}test-legacy-list"
        tokens_list = [
            "java",
            *flags_list,
            "-Xms2048M",
            "-Xmx4096M",
            "-jar",
            deployment.startup_jar,
            "nogui",
        ]
        expected_inner_list = " ".join(shlex.quote(t) for t in tokens_list)
        marker_list = (
            f"export {IDENTITY.process_marker_new}=1 "
            f"{IDENTITY.env_prefix_new}INSTANCE_ID={fixed_uuid_1.hex[:16]}; "
        )
        expected_pane_list = (
            f"{marker_list}cd {shlex.quote(deployment.server_directory())} && "
            f"exec {expected_inner_list}"
        )
        expected_tmux_list = (
            f"tmux new-session -d -s {shlex.quote(session_list)} "
            f"{shlex.quote(expected_pane_list)}"
        )
        assert captured_list_cmd == expected_tmux_list

        # Repeat with java_args as a single STRING with spaces to cover shlex.split branch
        flags_str = (
            '-XX:OnOutOfMemoryError="kill -9 %p" '
            '-Dproperty="hello world" '
            '"-Dcustom.msg=welcome to minecraft"'
        )
        config_str = {
            "java_args": flags_str,
            "memory_min_mb": 2048,
            "memory_max_mb": 4096,
            "port": 25565,
        }

        fixed_uuid_2 = MagicMock(hex="fedcba9876543210fedcba9876543210")
        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run_str,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=5678)),
            patch.object(provider, "_fs", MagicMock()),
            patch(
                "app.modules.server.infrastructure.providers.local.uuid.uuid4",
                return_value=fixed_uuid_2,
            ),
        ):
            await provider.start(
                server_id="test-legacy-str",
                config=config_str,
                deployment=deployment,
                launch_config=None,
            )

        captured_str_cmd = mock_run_str.call_args[0][0]
        session_str = f"{IDENTITY.temp_prefix_new}test-legacy-str"
        parsed_str_flags = shlex.split(flags_str)
        tokens_str = [
            "java",
            *parsed_str_flags,
            "-Xms2048M",
            "-Xmx4096M",
            "-jar",
            deployment.startup_jar,
            "nogui",
        ]
        expected_inner_str = " ".join(shlex.quote(t) for t in tokens_str)
        marker_str = (
            f"export {IDENTITY.process_marker_new}=1 "
            f"{IDENTITY.env_prefix_new}INSTANCE_ID={fixed_uuid_2.hex[:16]}; "
        )
        expected_pane_str = (
            f"{marker_str}cd {shlex.quote(deployment.server_directory())} && "
            f"exec {expected_inner_str}"
        )
        expected_tmux_str = (
            f"tmux new-session -d -s {shlex.quote(session_str)} "
            f"{shlex.quote(expected_pane_str)}"
        )
        assert captured_str_cmd == expected_tmux_str

    @pytest.mark.asyncio
    async def test_local_provider_start_rejects_stored_unsafe_args(self) -> None:
        from app.core.exceptions import ProviderError

        provider = LocalLinuxProvider()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/onx/test-server",
        )
        config = {
            "java_args": ["-Xmx1G;calc"],
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_fs", MagicMock()),
        ):
            with pytest.raises(
                ProviderError, match="Invalid JVM argument in stored configuration"
            ):
                await provider.start(
                    server_id="test-unsafe",
                    config=config,
                    deployment=deployment,
                )
            assert mock_run.call_count == 0

    @pytest.mark.asyncio
    async def test_local_provider_start_exec_prefix_and_pid_resolution(self) -> None:
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/onx/test-server",
        )
        config = {
            "java_args": ["-XX:+UseG1GC"],
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=4321)),
            patch.object(provider, "_fs", MagicMock()),
        ):
            result = await provider.start(
                server_id="test-pid-res",
                config=config,
                deployment=deployment,
            )
            assert result.pid == 4321
            cmd = mock_run.call_args[0][0]
            assert " && exec " in cmd

            handle = ServerHandle(
                provider="local",
                server_id="test-pid-res",
                external_id="test-pid-res",
            )
            with patch("app.modules.server.infrastructure.providers.local.os.kill"):
                await provider.stop(handle, force=True)
            stop_calls = [
                call[0][0]
                for call in mock_run.call_args_list
                if "kill-session" in call[0][0]
            ]
            assert len(stop_calls) > 0
            assert "kill-session" in stop_calls[0]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "LocalLinuxProvider is POSIX-only; Windows uses "
        "LocalWindowsProvider (see test_local_windows_provider.py)"
    ),
)
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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "LocalLinuxProvider is POSIX-only; Windows uses "
        "LocalWindowsProvider (see test_local_windows_provider.py)"
    ),
)
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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "LocalLinuxProvider is POSIX-only; Windows uses "
        "LocalWindowsProvider (see test_local_windows_provider.py)"
    ),
)
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
            startup_command=None,
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
            startup_command=None,
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
            startup_command=None,
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        from app.core.exceptions import ProviderError

        with patch.object(
            provider,
            "_verify_port_free",
            AsyncMock(side_effect=ProviderError("local", "start", "Port in use")),
        ), patch.object(provider, "_fs", MagicMock()):
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
            startup_command=None,
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

    @pytest.mark.asyncio
    async def test_find_java_processes_quotes_server_dir(self) -> None:
        import shlex
        provider = LocalLinuxProvider()
        tricky_dir = "/tmp/server's dir with spaces"
        with patch.object(
            provider, "_run_command_with_output", AsyncMock(return_value=(0, ""))
        ) as mock_run:
            await provider._find_java_processes(tricky_dir)
            cmd = mock_run.call_args[0][0]
            # Must contain properly quoted server_dir with no syntax error in shlex
            assert shlex.quote(tricky_dir) in cmd

    @pytest.mark.asyncio
    async def test_start_quotes_server_dir_and_session_with_special_chars(self) -> None:
        import shlex
        provider = LocalLinuxProvider()
        deployment = ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path="/tmp/my server's/dir with spaces",
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
            jvm_flags=("-Xms1024M", "-Xmx2048M"),
        )
        with (
            patch.object(provider, "_verify_port_free", AsyncMock(return_value=True)),
            patch.object(provider, "_cleanup_stale_tmux", AsyncMock()),
            patch.object(provider, "_run_command", AsyncMock(return_value=0)) as mock_run,
            patch.object(provider, "_get_tmux_pid", AsyncMock(return_value=1234)),
            patch.object(provider, "_fs", MagicMock()),
        ):
            await provider.start(
                server_id="srv-quotes",
                deployment=deployment,
                launch_config=lc,
            )
        # tmux new-session call
        tmux_cmd = mock_run.call_args[0][0]
        assert "tmux new-session" in tmux_cmd
        # Ensure it parses cleanly without shell syntax error
        parsed_tokens = shlex.split(tmux_cmd)
        assert len(parsed_tokens) >= 5
        assert parsed_tokens[0] == "tmux"
        assert parsed_tokens[1] == "new-session"


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

        create_call_args = list(mock_docker.call_args_list[0][0])
        assert create_call_args[0] == "create"
        assert "--name" in create_call_args
        name_idx = create_call_args.index("--name")
        assert create_call_args[name_idx + 1] == "onx-test-server-42"
        assert "--label" in create_call_args
        assert "com.onx-manager.managed=true" in create_call_args
        assert "com.onx-manager.server_id=test-server-42" in create_call_args
        assert "com.onx-manager.runtime=docker" in create_call_args

    @pytest.mark.asyncio
    async def test_docker_start_quotes_special_characters(self) -> None:
        provider = DockerProvider()
        config = {
            "image": "itzg/minecraft-server:latest",
            "world_dir": "/data/my world's/dir",
            "port": 25565,
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (0, ""),  # create
                (0, ""),  # start
                (0, "12345\n"),  # inspect pid
            ]
            await provider.start(server_id="srv 'special' 42", config=config)

        create_call_args = list(mock_docker.call_args_list[0][0])
        assert create_call_args[0] == "create"
        assert "--name" in create_call_args
        name_idx = create_call_args.index("--name")
        assert create_call_args[name_idx + 1] == "onx-srv 'special' 42"
        assert "-v" in create_call_args
        vol_idx = create_call_args.index("-v")
        assert create_call_args[vol_idx + 1].endswith(":/data")
        assert "my world's/dir" in create_call_args[vol_idx + 1]

    @pytest.mark.asyncio
    async def test_docker_start_accepts_four_kwargs_without_type_error(self) -> None:
        provider = DockerProvider()
        config = {
            "image": "itzg/minecraft-server:latest",
            "port": 25565,
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path="/tmp/docker-srv",
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
        )

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (0, ""),  # create
                (0, ""),  # start
                (0, "7890\n"),  # inspect pid
            ]
            result = await provider.start(
                server_id="docker-4-kwarg",
                config=config,
                deployment=deployment,
                launch_config=lc,
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 7890


class TestSSHProvider:
    @pytest.mark.asyncio
    async def test_ssh_start_quotes_special_characters(self) -> None:
        import shlex
        provider = SSHProvider(host="10.0.0.1")
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "9999\n"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        config = {
            "server_dir": "/opt/minecraft/my server's/dir",
            "jar_path": "my custom 'server'.jar",
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_get_connection", AsyncMock(return_value=mock_conn)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            res = await provider.start("srv 'test' 1", config)

        assert res.pid == 9999
        calls = [call[0][0] for call in mock_conn.run.call_args_list]
        mkdir_cmd = calls[0]
        tmux_cmd = calls[1]
        assert "mkdir -p" in mkdir_cmd
        assert shlex.quote("/opt/minecraft/my server's/dir") in mkdir_cmd
        assert "tmux new-session" in tmux_cmd
        parsed = shlex.split(tmux_cmd)
        assert parsed[0] == "tmux"
        assert parsed[1] == "new-session"

    @pytest.mark.asyncio
    async def test_ssh_start_accepts_four_kwargs_without_type_error(self) -> None:
        provider = SSHProvider(host="10.0.0.1")
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "5555\n"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        config = {
            "server_dir": "/opt/minecraft/srv1",
            "jar_path": "server.jar",
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }
        deployment = ServerDeployment(
            location_type=LocationType.SSH,
            root_path="/opt/minecraft/srv1",
        )
        lc = LaunchConfiguration(
            java_executable="java",
            startup_command=None,
            startup_jar="server.jar",
        )

        with (
            patch.object(provider, "_get_connection", AsyncMock(return_value=mock_conn)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            res = await provider.start(
                server_id="ssh-4-kwarg",
                config=config,
                deployment=deployment,
                launch_config=lc,
            )

        assert res.pid == 5555

    @pytest.mark.asyncio
    async def test_remote_provider_start_quotes_all_jvm_args(self) -> None:
        import shlex

        provider = SSHProvider(host="10.0.0.1")
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "7777\n"
        mock_result.stderr = ""
        mock_conn.run = AsyncMock(return_value=mock_result)

        lc = LaunchConfiguration(
            java_executable="/usr/lib/jvm/java 21/bin/java",
            jvm_flags=(
                '-XX:OnOutOfMemoryError="kill -9 %p"',
                '-Dproperty="hello world"',
                "-Dcustom.msg=welcome to minecraft",
            ),
            startup_jar="server.jar",
        )
        config = {
            "server_dir": "/opt/minecraft/srv with spaces",
            "jar_path": "server.jar",
            "memory_min_mb": 1024,
            "memory_max_mb": 2048,
        }

        with (
            patch.object(provider, "_get_connection", AsyncMock(return_value=mock_conn)),
            patch("asyncio.sleep", AsyncMock()),
        ):
            res = await provider.start(
                server_id="ssh-quotes",
                config=config,
                launch_config=lc,
            )

        assert res.pid == 7777
        calls = [call[0][0] for call in mock_conn.run.call_args_list]
        tmux_cmd = calls[1]

        expected_tokens = [
            "/usr/lib/jvm/java 21/bin/java",
            '-XX:OnOutOfMemoryError="kill -9 %p"',
            '-Dproperty="hello world"',
            "-Dcustom.msg=welcome to minecraft",
            "-Xms1024M",
            "-Xmx2048M",
            "-jar",
            "server.jar",
            "nogui",
        ]
        expected_inner_cmd = " ".join(shlex.quote(t) for t in expected_tokens)
        expected_pane_cmd = (
            f"cd {shlex.quote('/opt/minecraft/srv with spaces')} && exec {expected_inner_cmd}"
        )
        expected_tmux_cmd = (
            f"tmux new-session -d -s {shlex.quote('onx-ssh-quotes')} "
            f"{shlex.quote(expected_pane_cmd)}"
        )

        assert tmux_cmd == expected_tmux_cmd

    @pytest.mark.asyncio
    async def test_ssh_get_connection_builds_kwargs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import sys
        import types

        mock_conn = MagicMock()
        mock_connect = AsyncMock(return_value=mock_conn)
        fake_asyncssh = types.ModuleType("asyncssh")
        fake_asyncssh.connect = mock_connect
        monkeypatch.setitem(sys.modules, "asyncssh", fake_asyncssh)

        provider = SSHProvider(
            host="192.168.1.50",
            port=2222,
            username="admin",
            client_keys=["/id_rsa"],
            passphrase="secret",
            known_hosts="/known_hosts",
            keepalive_seconds=45,
        )

        conn = await provider._get_connection()
        assert conn is mock_conn
        mock_connect.assert_awaited_once_with(
            host="192.168.1.50",
            port=2222,
            username="admin",
            known_hosts="/known_hosts",
            keepalive_interval=45,
            client_keys=["/id_rsa"],
            passphrase="secret",
        )
