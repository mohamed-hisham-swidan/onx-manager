from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ProviderError
from app.modules.server.domain.diagnostics import FailureCode
from app.modules.server.domain.value_objects import (
    LaunchConfiguration,
    LocationType,
    ServerDeployment,
)
from app.modules.server.infrastructure.providers.base import (
    ServerHandle,
    ServerRuntimeStatus,
)
from app.modules.server.infrastructure.providers.docker import (
    DockerProvider,
    resolve_docker_image,
)


class TestDockerProviderContract:
    @pytest.mark.asyncio
    async def test_docker_ping_success_and_failure(self) -> None:
        provider = DockerProvider()

        # Success on Linux OSType
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "linux\n")
            assert await provider.ping() is True
            mock_cmd.assert_awaited_once_with("info", "--format", "{{.OSType}}")

        # Failure on Windows OSType (Decision 7: Linux containers mode mandatory)
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "windows\n")
            assert await provider.ping() is False

        # Failure on daemon offline / non-zero exit
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (1, "Cannot connect to the Docker daemon")
            assert await provider.ping() is False

    @pytest.mark.asyncio
    async def test_docker_start_with_launch_config_jar(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-paper"
        srv_dir.mkdir()

        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_jar="paper-1.20.4.jar",
        )
        launch_config = LaunchConfiguration(
            java_executable="java",
            startup_jar="paper-1.20.4.jar",
            jvm_flags=("-Dfile.encoding=UTF-8", "-XX:+UseG1GC"),
            environment={"CUSTOM_ENV": "123"},
        )
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25565,
            "container_port": 25565,
            "memory_min_mb": 2048,
            "memory_max_mb": 4096,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()) as mock_ensure,
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (1, "No such container"),  # inspect
                (0, ""),  # create
                (0, ""),  # start
                (0, "4567\n"),  # inspect pid
            ]
            result = await provider.start(
                server_id="paper-srv",
                config=config,
                deployment=deployment,
                launch_config=launch_config,
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 4567
        assert result.port == 25565
        assert result.metadata["container_name"] == "onx-paper-srv"
        assert result.metadata["server_dir"] == str(srv_dir)
        mock_ensure.assert_awaited_once_with("eclipse-temurin:21-jre-jammy")

        create_args = list([c[0] for c in mock_docker.call_args_list if c[0][0] == "create"][0])
        assert create_args[0] == "create"
        assert "--name" in create_args
        assert create_args[create_args.index("--name") + 1] == "onx-paper-srv"
        assert "-p" in create_args
        assert create_args[create_args.index("-p") + 1] == "25565:25565"
        assert "--memory" in create_args
        # 4096 + 512 = 4608m headroom
        assert create_args[create_args.index("--memory") + 1] == "4608m"

        # Volume mount contract (Decision 3)
        assert "-v" in create_args
        assert create_args[create_args.index("-v") + 1] == f"{srv_dir.as_posix()}:/data"
        assert "-w" in create_args
        assert create_args[create_args.index("-w") + 1] == "/data"

        # Environment
        assert "-e" in create_args
        assert "CUSTOM_ENV=123" in create_args

        # Image & JAR launch translation (Decision 4)
        assert "eclipse-temurin:21-jre-jammy" in create_args
        img_idx = create_args.index("eclipse-temurin:21-jre-jammy")
        cmd_tokens = create_args[img_idx + 1 :]
        assert cmd_tokens[0] == "java"
        assert "-Dfile.encoding=UTF-8" in cmd_tokens
        assert "-XX:+UseG1GC" in cmd_tokens
        assert "-Xms2048M" in cmd_tokens
        assert "-Xmx4096M" in cmd_tokens
        assert "-jar" in cmd_tokens
        assert cmd_tokens[cmd_tokens.index("-jar") + 1] == "/data/paper-1.20.4.jar"
        assert cmd_tokens[-1] == "nogui"

    @pytest.mark.asyncio
    async def test_docker_start_with_forge_script(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-forge"
        srv_dir.mkdir()

        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_command=["bash", "run.sh", "nogui"],
        )
        launch_config = LaunchConfiguration(
            startup_command=["bash", "run.sh", "nogui"],
            jvm_flags=("-Dfml.readTimeout=180",),
        )
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "port": 25570,
            "memory_min_mb": 3072,
            "memory_max_mb": 6144,
            "cpu_cores": 4,
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (1, "No such container"),  # inspect
                (0, ""),  # create
                (0, ""),  # start
                (0, "5678\n"),  # inspect pid
            ]
            result = await provider.start(
                server_id="forge-srv",
                config=config,
                deployment=deployment,
                launch_config=launch_config,
            )

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 5678

        # Verify user_jvm_args.txt was created on host (Decision 4)
        jvm_args_file = srv_dir / "user_jvm_args.txt"
        assert jvm_args_file.exists()
        content = jvm_args_file.read_text(encoding="utf-8")
        assert "-Xms3072M" in content
        assert "-Xmx6144M" in content
        assert "-XX:ActiveProcessorCount=4" in content
        assert "-Dfml.readTimeout=180" in content

        create_args = list([c[0] for c in mock_docker.call_args_list if c[0][0] == "create"][0])
        assert "--cpus" in create_args
        assert create_args[create_args.index("--cpus") + 1] == "4"

        # Container command translated to bash /data/run.sh nogui (Decision 4)
        img_idx = create_args.index("eclipse-temurin:21-jre-jammy")
        cmd_tokens = create_args[img_idx + 1 :]
        assert cmd_tokens == ["bash", "/data/run.sh", "nogui"]

    @pytest.mark.asyncio
    async def test_docker_start_rejects_server_dir_outside_servers_root(
        self, tmp_path: Path
    ) -> None:
        from app.core.exceptions import PathContainmentError

        provider = DockerProvider()
        for outside in (tmp_path / "test_servers", tmp_path / "test_servers2" / "x"):
            outside.mkdir(parents=True, exist_ok=True)
            deployment = ServerDeployment(
                location_type=LocationType.DOCKER,
                root_path=str(outside),
            )
            with (
                patch.object(provider, "_ensure_image", AsyncMock()),
                patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
                pytest.raises(PathContainmentError),
            ):
                await provider.start(
                    server_id="srv-out", config={"server_id": "srv-out"}, deployment=deployment
                )
            assert not [c for c in mock_cmd.call_args_list if c[0][0] == "create"]

    @pytest.mark.asyncio
    async def test_docker_start_cpu_allocation_and_affinity(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(tmp_path / "test_servers" / "srv-cpu"),
        )
        config: dict[str, Any] = {
            "image": "eclipse-temurin:21-jre-jammy",
            "cpu_cores": 2,
            "cpu_affinity": "0,1",
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (1, "No such container"),  # inspect
                (0, ""),  # create
                (0, ""),  # start
                (0, "1111\n"),  # inspect pid
            ]
            await provider.start(
                server_id="cpu-srv",
                config=config,
                deployment=deployment,
            )

        create_args = list([c[0] for c in mock_docker.call_args_list if c[0][0] == "create"][0])
        assert "--cpus" in create_args
        assert create_args[create_args.index("--cpus") + 1] == "2"
        assert "--cpuset-cpus" in create_args
        assert create_args[create_args.index("--cpuset-cpus") + 1] == "0,1"

        # Java command includes -XX:ActiveProcessorCount=2
        assert "-XX:ActiveProcessorCount=2" in create_args

    @pytest.mark.asyncio
    async def test_docker_stop_graceful_and_force(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="stop-srv",
            external_id="onx-stop-srv",
        )

        # Force stop uses docker kill
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
            mock_docker.return_value = (0, "")
            await provider.stop(handle, force=True)
            mock_docker.assert_any_await("kill", "onx-stop-srv")

        # Graceful stop: execute_command succeeds and container exits
        with (
            patch.object(provider, "execute_command", AsyncMock()) as mock_exec,
            patch.object(provider, "status", AsyncMock(return_value=ServerRuntimeStatus.STOPPED)),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            await provider.stop(handle, force=False)
            mock_exec.assert_awaited_once_with(handle, "stop")
            # Container exited cleanly, docker stop not called
            mock_docker.assert_not_called()

        # Graceful stop fallback: execute_command fails, falls back to docker stop -t 30
        with (
            patch.object(
                provider,
                "execute_command",
                AsyncMock(side_effect=RuntimeError("RCON fail")),
            ),
            patch.object(
                provider,
                "_docker_command",
                AsyncMock(return_value=(0, "")),
            ) as mock_docker,
        ):
            await provider.stop(handle, force=False)
            mock_docker.assert_any_await("stop", "-t", "30", "onx-stop-srv")

    @pytest.mark.asyncio
    async def test_docker_stop_exit_verification_and_failure(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="exit-srv",
            external_id="onx-exit-srv",
        )

        # 1. Force kill fails to exit -> raises ProviderError
        with (
            patch.object(provider, "_docker_command", AsyncMock(return_value=(0, "killed"))),
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=False)),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await provider.stop(handle, force=True)
            assert "did not exit after docker kill" in str(exc_info.value)

        # 2. Graceful stop fails to exit -> raises ProviderError
        with (
            patch.object(provider, "execute_command", AsyncMock(side_effect=RuntimeError("RCON fail"))),
            patch.object(provider, "_docker_command", AsyncMock(return_value=(0, ""))),
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=False)),
        ):
            with pytest.raises(ProviderError) as exc_info:
                await provider.stop(handle, force=False)
            assert "still running after docker stop -t 30" in str(exc_info.value)

        # 3. If container does not exist / is not running -> returns cleanly
        with (
            patch.object(provider, "_docker_command", AsyncMock(return_value=(1, "Error: No such container: onx-exit-srv"))),
        ):
            await provider.stop(handle, force=True)

    @pytest.mark.asyncio
    async def test_docker_console_logs(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="log-srv",
            external_id="onx-log-srv",
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
            mock_docker.return_value = (
                0,
                "2026-09-11T00:00:00Z [Server thread/INFO]: Starting server...\n"
                "2026-09-11T00:00:01Z [Server thread/INFO]: Done (1.234s)!\n",
            )
            logs = await provider.console(handle, tail=50)

        mock_docker.assert_awaited_once_with(
            "logs", "--tail", "50", "--timestamps", "onx-log-srv"
        )
        assert len(logs) == 2
        assert "Done" in logs[1]

    @pytest.mark.asyncio
    async def test_docker_execute_command_tokenized(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="exec-srv",
            external_id="onx-exec-srv",
        )

        with (
            patch.object(provider, "_resolve_rcon_credentials", AsyncMock(return_value=None)),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.return_value = (0, "Made player an operator\n")
            out = await provider.execute_command(handle, "op player; echo 'injection'")

        mock_docker.assert_awaited_once_with(
            "exec", "onx-exec-srv", "rcon-cli", "--", "op player; echo 'injection'"
        )
        assert "Made player an operator" in out

    @pytest.mark.asyncio
    async def test_docker_stale_container_conflict_recovery(self) -> None:
        import json

        provider = DockerProvider()
        exited_inspect = {
            "State": {"Status": "exited", "ExitCode": 0},
            "Config": {
                "Labels": {
                    "com.onx-manager.server_id": "test-conflict",
                }
            },
        }
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.side_effect = [
                (0, json.dumps(exited_inspect)),  # pre-inspect
                (0, "onx-test-conflict"),  # rm
                (0, ""),  # retry create
                (0, ""),  # start
                (0, "3333\n"),  # inspect pid
            ]
            result = await provider.start(server_id="test-conflict", config={})

        assert result.status == ServerRuntimeStatus.RUNNING
        assert result.pid == 3333
        # rm was invoked with container name without -f
        rm_call = mock_docker.call_args_list[1][0]
        assert rm_call == ("rm", "onx-test-conflict")

    @pytest.mark.asyncio
    async def test_docker_start_creation_failure_raises_provider_error(self) -> None:
        provider = DockerProvider()
        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_docker,
        ):
            mock_docker.return_value = (1, "invalid memory value")
            with pytest.raises(ProviderError) as exc_info:
                await provider.start(server_id="fail-srv", config={})

        assert "docker start failed" in str(exc_info.value)


class TestDockerDestroy:
    @pytest.mark.asyncio
    async def test_docker_destroy_removes_container_and_clears_rcon_cache(self) -> None:
        provider = DockerProvider()
        provider._rcon_cache["srv-del-1"] = {
            "host": "127.0.0.1",
            "port": 25575,
            "password": "secret",
            "server_dir": "/tmp/data",
        }
        handle = ServerHandle(
            provider="docker",
            server_id="srv-del-1",
            external_id="onx-srv-del-1",
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
            mock_docker.return_value = (0, "onx-srv-del-1")
            await provider.destroy(handle)

        rm_calls = [c[0] for c in mock_docker.call_args_list if c[0][:2] == ("rm", "-f")]
        assert any("onx-srv-del-1" in c for c in rm_calls)
        assert "srv-del-1" not in provider._rcon_cache

    @pytest.mark.asyncio
    async def test_docker_destroy_empty_external_id_resolves_fallback(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-del-2",
            external_id="",
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
            mock_docker.return_value = (0, "onx-srv-del-2")
            await provider.destroy(handle)

        rm_calls = [c[0] for c in mock_docker.call_args_list if c[0][:2] == ("rm", "-f")]
        assert any("onx-srv-del-2" in c for c in rm_calls)

    @pytest.mark.asyncio
    async def test_docker_destroy_already_removed_container_graceful(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-del-3",
            external_id="onx-srv-del-3",
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
            mock_docker.return_value = (1, "Error: No such container: onx-srv-del-3")
            # Must not raise an exception
            await provider.destroy(handle)

        rm_calls = [c[0] for c in mock_docker.call_args_list if c[0][:2] == ("rm", "-f")]
        assert any("onx-srv-del-3" in c for c in rm_calls)

    @pytest.mark.asyncio
    async def test_docker_destroy_cli_missing_graceful(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="srv-del-4",
            external_id="onx-srv-del-4",
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_docker:
            mock_docker.side_effect = FileNotFoundError("No such file or directory: 'docker'")
            # Must degrade gracefully without bubbling up exception
            await provider.destroy(handle)

    @pytest.mark.asyncio
    async def test_docker_ensure_image_cached_skips_pull(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "inspect-json")
            await provider.ensure_image("eclipse-temurin:21-jre-jammy")

        mock_cmd.assert_awaited_once_with(
            "image", "inspect", "eclipse-temurin:21-jre-jammy", log_failure=False
        )

    @pytest.mark.asyncio
    async def test_docker_ensure_image_missing_initiates_pull(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.side_effect = [
                (1, "No such image"),
                (0, "Downloaded newer image"),
            ]
            await provider.ensure_image("eclipse-temurin:21-jre-jammy")

        assert mock_cmd.await_count == 2
        mock_cmd.assert_any_await(
            "image", "inspect", "eclipse-temurin:21-jre-jammy", log_failure=False
        )
        mock_cmd.assert_any_await("pull", "eclipse-temurin:21-jre-jammy")

    @pytest.mark.asyncio
    async def test_docker_ensure_image_pull_timeout_raises_provider_error(self) -> None:
        provider = DockerProvider()
        with (
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch("asyncio.wait_for", AsyncMock(side_effect=TimeoutError())),
        ):
            mock_cmd.return_value = (1, "No such image")
            with pytest.raises(ProviderError) as exc_info:
                await provider.ensure_image("eclipse-temurin:21-jre-jammy", timeout=5.0)

        assert exc_info.value.operation == "pull"
        assert exc_info.value.details["timeout_seconds"] == 5.0
        assert exc_info.value.details["image"] == "eclipse-temurin:21-jre-jammy"

    @pytest.mark.asyncio
    async def test_docker_ensure_image_pull_failure_raises_provider_error(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.side_effect = [
                (1, "No such image"),
                (1, "network connection failed"),
            ]
            with pytest.raises(ProviderError) as exc_info:
                await provider.ensure_image("eclipse-temurin:21-jre-jammy")

        assert exc_info.value.operation == "pull"
        assert "network connection failed" in exc_info.value.details["detail"]

    @pytest.mark.asyncio
    async def test_docker_prepare_environment_calls_ensure_image(self) -> None:
        provider = DockerProvider()
        with patch.object(provider, "ensure_image", AsyncMock()) as mock_ensure:
            await provider.prepare_environment(
                server_id="test-srv",
                config={"image": "custom-mc:1.21"},
            )

        mock_ensure.assert_awaited_once_with("custom-mc:1.21")

    def test_resolve_docker_image_by_version(self) -> None:
        # Minecraft 26.x (Paper 26.1+) requires Java 25
        assert resolve_docker_image(minecraft_version="26.2.0") == "eclipse-temurin:25-jre"
        assert resolve_docker_image(minecraft_version="26.1") == "eclipse-temurin:25-jre"

        # Minecraft 1.20.5 - 1.21.x requires Java 21
        assert (
            resolve_docker_image(minecraft_version="1.21.4") == "eclipse-temurin:21-jre-jammy"
        )
        assert (
            resolve_docker_image(minecraft_version="1.20.5") == "eclipse-temurin:21-jre-jammy"
        )

        # Minecraft 1.17 - 1.20.4 requires Java 17
        assert (
            resolve_docker_image(minecraft_version="1.20.4") == "eclipse-temurin:17-jre-jammy"
        )
        assert (
            resolve_docker_image(minecraft_version="1.17.1") == "eclipse-temurin:17-jre-jammy"
        )

        # Minecraft <= 1.16.5 requires Java 8
        assert (
            resolve_docker_image(minecraft_version="1.16.5") == "eclipse-temurin:8-jre-jammy"
        )
        assert (
            resolve_docker_image(minecraft_version="1.12.2") == "eclipse-temurin:8-jre-jammy"
        )

        # Explicit config['image'] takes precedence
        assert (
            resolve_docker_image(
                config={"image": "custom/java:latest"},
                minecraft_version="26.2.0",
            )
            == "custom/java:latest"
        )

    @pytest.mark.asyncio
    async def test_docker_collect_diagnostics_java_version_mismatch(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with (
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch.object(provider, "console", AsyncMock()) as mock_console,
        ):
            mock_cmd.return_value = (0, "1|false|\n")
            mock_console.return_value = [
                "Minecraft 26.1 and newer requires running the server with Java 25 or above.",
                "For information on how to update Java, see docs.papermc.io/misc/java-install",
            ]
            diag = await provider.collect_diagnostics(handle)

        assert diag.provider == "docker"
        assert diag.exit_code == 1
        assert diag.failure_code == FailureCode.JAVA_VERSION_MISMATCH
        assert len(diag.last_log_lines) == 2

    @pytest.mark.asyncio
    async def test_docker_collect_diagnostics_oom_killed(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with (
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch.object(provider, "console", AsyncMock()) as mock_console,
        ):
            mock_cmd.return_value = (0, "137|true|\n")
            mock_console.return_value = []
            diag = await provider.collect_diagnostics(handle)

        assert diag.exit_code == 137
        assert diag.failure_code == FailureCode.MEMORY_EXHAUSTED
        assert "OOMKilled" in diag.failure_reason

    @pytest.mark.asyncio
    async def test_docker_collect_diagnostics_file_not_found_exit_code(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with (
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch.object(provider, "console", AsyncMock()) as mock_console,
        ):
            mock_cmd.return_value = (0, "127|false|\n")
            mock_console.return_value = ["/bin/sh: java: not found"]
            diag = await provider.collect_diagnostics(handle)

        assert diag.exit_code == 127
        assert diag.failure_code == FailureCode.FILE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_docker_collect_diagnostics_clean_running_or_stopped(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with (
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch.object(provider, "console", AsyncMock()) as mock_console,
        ):
            mock_cmd.return_value = (0, "0|false|\n")
            mock_console.return_value = ["Server listening on port 25565"]
            diag = await provider.collect_diagnostics(handle)

        assert diag.exit_code == 0
        assert diag.failure_code is None
        assert diag.last_log_lines == ["Server listening on port 25565"]

    @pytest.mark.asyncio
    async def test_docker_status_clean_exit_returns_stopped(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            for exit_code in (0, 137, 143):
                # OOMKilled false
                mock_cmd.return_value = (0, f"exited {exit_code} false\n")
                status = await provider.status(handle)
                assert (
                    status == ServerRuntimeStatus.STOPPED
                ), f"Failed for exit_code={exit_code} false"

                # Missing third token (tolerant parsing)
                mock_cmd.return_value = (0, f"exited {exit_code}\n")
                status = await provider.status(handle)
                assert (
                    status == ServerRuntimeStatus.STOPPED
                ), f"Failed for exit_code={exit_code} missing token"

    @pytest.mark.asyncio
    async def test_docker_status_oom_killed_returns_error(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            for exit_code in (0, 137, 143, 1):
                mock_cmd.return_value = (0, f"exited {exit_code} true\n")
                status = await provider.status(handle)
                assert (
                    status == ServerRuntimeStatus.ERROR
                ), f"Failed for exit_code={exit_code} true"

    @pytest.mark.asyncio
    async def test_docker_status_error_exit_returns_error(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "exited 1 false\n")
            status = await provider.status(handle)
            assert status == ServerRuntimeStatus.ERROR

            mock_cmd.return_value = (0, "exited 1\n")
            status = await provider.status(handle)
            assert status == ServerRuntimeStatus.ERROR

    @pytest.mark.asyncio
    async def test_docker_status_running_returns_running(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            for out in ("running 0 false\n", "running 0 true\n", "running 0\n"):
                mock_cmd.return_value = (0, out)
                status = await provider.status(handle)
                assert status == ServerRuntimeStatus.RUNNING

    @pytest.mark.asyncio
    async def test_docker_start_foreign_container_refused(self, tmp_path: Path) -> None:
        import json

        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-foreign"
        srv_dir.mkdir()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_jar="server.jar",
        )

        foreign_inspect = {
            "State": {"Status": "running", "Pid": 9999},
            "Config": {
                "Labels": {
                    "com.onx-manager.server_id": "someone-elses-server",
                }
            },
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
        ):
            mock_cmd.return_value = (0, json.dumps(foreign_inspect))

            with pytest.raises(ProviderError) as exc_info:
                await provider.start(
                    server_id="my-srv",
                    deployment=deployment,
                    config={"image": "eclipse-temurin:21-jre-jammy"},
                )

            assert "Refusing to touch foreign container" in str(exc_info.value)
            # Never run docker rm or docker stop against foreign container
            rm_or_stop_calls = [
                c for c in mock_cmd.call_args_list if c[0] and c[0][0] in ("rm", "stop", "kill")
            ]
            assert not rm_or_stop_calls

    @pytest.mark.asyncio
    async def test_docker_start_running_container_adopted_when_fingerprint_matches(
        self, tmp_path: Path
    ) -> None:
        import json

        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-adopt"
        srv_dir.mkdir()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_jar="server.jar",
        )

        from app.modules.server.infrastructure.providers.docker import (
            _compute_config_fingerprint,
            build_docker_server_cmd,
            resolve_host_mount_path,
        )

        server_cmd = build_docker_server_cmd(
            startup_command=None,
            startup_jar="server.jar",
            jvm_flags=None,
            memory_min_mb=1024,
            memory_max_mb=2048,
            cpu_cores=0,
            image="eclipse-temurin:21-jre-jammy",
            force_itzg_entrypoint=True,
        )
        host_mount = resolve_host_mount_path(str(srv_dir))
        fp = _compute_config_fingerprint(
            image="eclipse-temurin:21-jre-jammy",
            memory_min=1024,
            memory_max=2048,
            cpu_cores=0,
            cpu_affinity="",
            ports=["25565:25565"],
            mounts=[f"{host_mount}:/data"],
            env={},
            cmd=server_cmd,
        )

        running_inspect = {
            "State": {"Status": "running", "Pid": 7777},
            "Config": {
                "Labels": {
                    "com.onx-manager.server_id": "adopt-srv",
                    "com.onx-manager.config-fingerprint": fp,
                }
            },
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.2"}}},
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
        ):
            mock_cmd.return_value = (0, json.dumps(running_inspect))

            result = await provider.start(
                server_id="adopt-srv",
                deployment=deployment,
                config={"image": "eclipse-temurin:21-jre-jammy", "port": 25565},
            )

            assert result.status == ServerRuntimeStatus.RUNNING
            assert result.metadata.get("adopted") is True
            assert result.pid == 7777
            # Never run create or rm
            create_or_rm = [
                c for c in mock_cmd.call_args_list if c[0] and c[0][0] in ("create", "rm")
            ]
            assert not create_or_rm

    @pytest.mark.asyncio
    async def test_docker_start_running_container_fails_closed_when_fingerprint_mismatched(
        self, tmp_path: Path
    ) -> None:
        import json

        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-mismatch"
        srv_dir.mkdir()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_jar="server.jar",
        )

        mismatched_inspect = {
            "State": {"Status": "running", "Pid": 8888},
            "Config": {
                "Labels": {
                    "com.onx-manager.server_id": "mismatch-srv",
                    "com.onx-manager.config-fingerprint": "different-old-fingerprint",
                }
            },
        }

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
        ):
            mock_cmd.return_value = (0, json.dumps(mismatched_inspect))

            with pytest.raises(ProviderError) as exc_info:
                await provider.start(
                    server_id="mismatch-srv",
                    deployment=deployment,
                    config={"image": "eclipse-temurin:21-jre-jammy"},
                )

            assert "already running with a different or legacy configuration" in str(exc_info.value)
            # Never run rm -f on a running container
            rm_force_calls = [
                c for c in mock_cmd.call_args_list if c[0] and c[0][0] == "rm" and "-f" in c[0]
            ]
            assert not rm_force_calls

    @pytest.mark.asyncio
    async def test_docker_start_exited_container_removes_and_recreates(
        self, tmp_path: Path
    ) -> None:
        import json

        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-exited"
        srv_dir.mkdir()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_jar="server.jar",
        )

        exited_inspect = {
            "State": {"Status": "exited", "ExitCode": 0},
            "Config": {
                "Labels": {
                    "com.onx-manager.server_id": "exited-srv",
                }
            },
        }

        async def fake_cmd(*args, **kwargs):
            if args[0] == "inspect" and "--format" in args and "{{json .}}" in args:
                return 0, json.dumps(exited_inspect)
            if args[0] == "rm":
                # Ensure rm was NOT force (-f)
                assert "-f" not in args
                return 0, ""
            if args[0] == "create":
                return 0, ""
            if args[0] == "start":
                return 0, ""
            if args[0] == "inspect":
                return 0, "54321\n"
            return 0, ""

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock(side_effect=fake_cmd)) as mock_cmd,
        ):
            result = await provider.start(
                server_id="exited-srv",
                deployment=deployment,
                config={"image": "eclipse-temurin:21-jre-jammy"},
            )

            assert result.status == ServerRuntimeStatus.RUNNING
            rm_calls = [c for c in mock_cmd.call_args_list if c[0] and c[0][0] == "rm"]
            assert len(rm_calls) == 1
            assert rm_calls[0][0] == ("rm", "onx-exited-srv")
            create_calls = [c for c in mock_cmd.call_args_list if c[0] and c[0][0] == "create"]
            assert len(create_calls) == 1

    @pytest.mark.asyncio
    async def test_get_container_ip_and_address(self) -> None:
        provider = DockerProvider()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
        )
        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            mock_cmd.return_value = (0, "172.17.0.7 \n")
            ip = await provider.get_container_ip("onx-test-srv")
            assert ip == "172.17.0.7"

            addr = await provider.get_address(handle)
            assert addr == "172.17.0.7"

    @pytest.mark.asyncio
    async def test_docker_wait_ready_success(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "srv-test"
        srv_dir.mkdir()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
            metadata={"root_path": str(srv_dir)},
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            async def _docker_cmd(*args: Any) -> tuple[int, str]:
                if "logs" in args:
                    return (0, "[00:00:10 INFO] Done (10.234s)! For help, type help\n")
                if "inspect" in args:
                    return (0, "running 0\n")
                return (0, "")

            mock_cmd.side_effect = _docker_cmd
            ready = await provider.wait_ready(
                server_id="test-srv",
                handle=handle,
                timeout=5.0,
            )
            assert ready is True

    @pytest.mark.asyncio
    async def test_docker_wait_ready_timeout(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "srv-test"
        srv_dir.mkdir()
        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
            metadata={"root_path": str(srv_dir)},
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            async def _docker_cmd(*args: Any) -> tuple[int, str]:
                if "logs" in args:
                    return (0, "[00:00:01 INFO] Preparing spawn area: 10%\n")
                if "inspect" in args:
                    return (0, "running 0\n")
                return (0, "")

            mock_cmd.side_effect = _docker_cmd
            ready = await provider.wait_ready(
                server_id="test-srv",
                handle=handle,
                timeout=0.05,
            )
            assert ready is False

    @pytest.mark.asyncio
    async def test_docker_wait_ready_crash(self, tmp_path: Path) -> None:
        provider = DockerProvider()
        srv_dir = tmp_path / "srv-test"
        crash_dir = srv_dir / "crash-reports"
        crash_dir.mkdir(parents=True)
        crash_file = crash_dir / "crash-2026-09-23_12.00.00-server.txt"
        crash_file.write_text("---- Minecraft Crash Report ----\nDescription: boom\n")

        handle = ServerHandle(
            provider="docker",
            server_id="test-srv",
            external_id="onx-test-srv",
            metadata={"root_path": str(srv_dir)},
        )

        with patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd:
            async def _docker_cmd(*args: Any) -> tuple[int, str]:
                if "inspect" in args:
                    return (0, "running 0\n")
                return (0, "")

            mock_cmd.side_effect = _docker_cmd
            ready = await provider.wait_ready(
                server_id="test-srv",
                handle=handle,
                timeout=5.0,
            )
            assert ready is False

    @pytest.mark.asyncio
    async def test_docker_adopt_retains_session_name_and_operations_never_target_empty(
        self, tmp_path: Path
    ) -> None:
        import json

        from app.modules.server.infrastructure.providers.docker import (
            _compute_config_fingerprint,
            build_docker_server_cmd,
            resolve_host_mount_path,
        )

        provider = DockerProvider()
        srv_dir = tmp_path / "test_servers" / "srv-adopt-f1"
        srv_dir.mkdir(parents=True)
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path=str(srv_dir),
            startup_jar="server.jar",
        )

        server_cmd = build_docker_server_cmd(
            startup_command=None,
            startup_jar="server.jar",
            jvm_flags=None,
            memory_min_mb=1024,
            memory_max_mb=2048,
            cpu_cores=0,
            image="eclipse-temurin:21-jre-jammy",
            force_itzg_entrypoint=True,
        )
        host_mount = resolve_host_mount_path(str(srv_dir))
        fp = _compute_config_fingerprint(
            image="eclipse-temurin:21-jre-jammy",
            memory_min=1024,
            memory_max=2048,
            cpu_cores=0,
            cpu_affinity="",
            ports=["25565:25565"],
            mounts=[f"{host_mount}:/data"],
            env={},
            cmd=server_cmd,
        )

        running_inspect = {
            "State": {"Status": "running", "Pid": 9999},
            "Config": {
                "Labels": {
                    "com.onx-manager.server_id": "srv-f1",
                    "com.onx-manager.config-fingerprint": fp,
                }
            },
            "NetworkSettings": {"Networks": {"bridge": {"IPAddress": "172.17.0.5"}}},
        }

        executed_commands: list[tuple] = []

        async def fake_docker_runner(*args: Any, **_kwargs: Any) -> tuple[int, str]:
            executed_commands.append(args)
            cmd = args[0] if args else ""
            fmt = "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}"
            if cmd == "inspect" and "--format" in args and "{{json .}}" in args:
                return 0, json.dumps(running_inspect)
            if cmd == "inspect" and fmt in args:
                return 0, "running 0 false"
            if cmd == "inspect" and "{{.State.Pid}}" in args:
                return 0, "9999"
            if cmd in ("stop", "kill"):
                return 0, ""
            if cmd == "exec":
                return 0, "command executed"
            return 0, ""

        with (
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", side_effect=fake_docker_runner),
            patch.object(provider, "_wait_for_container_exit", AsyncMock(return_value=True)),
        ):
            result = await provider.start(
                server_id="srv-f1",
                deployment=deployment,
                config={"image": "eclipse-temurin:21-jre-jammy", "port": 25565},
            )

            assert result.metadata.get("session_name") == "onx-srv-f1"
            assert result.metadata.get("container_name") == "onx-srv-f1"

            empty_ext_handle = ServerHandle(
                provider="docker",
                server_id="srv-f1",
                external_id="",
                metadata=result.metadata,
            )

            executed_commands.clear()
            st = await provider.status(empty_ext_handle)
            assert st == ServerRuntimeStatus.RUNNING

            await provider.execute_command(empty_ext_handle, "help")
            await provider.stop(empty_ext_handle, force=True)

            for call_args in executed_commands:
                assert "" not in call_args, f"Targeted empty string in docker command: {call_args}"
                assert "onx-srv-f1" in call_args, f"Expected container in call: {call_args}"



