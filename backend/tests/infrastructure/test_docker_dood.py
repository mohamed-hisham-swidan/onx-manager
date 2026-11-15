import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from app.core.config import AppSettings
from app.modules.server.domain.value_objects import LocationType, ServerDeployment
from app.modules.server.infrastructure.installer import ContainerInstallerRunner
from app.modules.server.infrastructure.providers.docker import (
    DockerProvider,
    normalize_host_path,
    resolve_host_mount_path,
)


def _make_docker_command_fake(pid_ip: str = "1234 172.17.0.5\n"):
    async def fake_docker_command(*args: object, **_kwargs: object):
        if not args:
            return (0, "")
        cmd = args[0]
        if cmd == "inspect":
            if "--format" in args and "{{json .}}" in args:
                return (1, "")
            return (0, pid_ip)
        if cmd in ("create", "start", "rm"):
            return (0, "")
        return (0, "")
    return fake_docker_command


class TestDooDHostPathResolution:
    """Test resolve_host_mount_path for DooD sibling container volume mounts."""

    def test_native_host_mode_returns_normalized_path(self) -> None:
        """When ONX_HOST_DATA_DIR is unset, returns normalized container path unchanged."""
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_host_mount_path("/app/data/servers/test-srv-1")
            expected = normalize_host_path("/app/data/servers/test-srv-1")
            assert resolved == expected

    def test_dood_translates_app_data_servers_path(self) -> None:
        """When ONX_HOST_DATA_DIR is set, translates /app/data/servers/{id} to host path."""
        host_dir = "/home/deploy/onx/data/servers"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            resolved = resolve_host_mount_path("/app/data/servers/survival-world")
            assert resolved == "/home/deploy/onx/data/servers/survival-world"

    def test_dood_translates_relative_data_servers_path(self) -> None:
        """Translates relative data/servers/{id} path using ONX_HOST_DATA_DIR."""
        host_dir = "/srv/minecraft/servers"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            resolved = resolve_host_mount_path("data/servers/lobby")
            assert resolved == "/srv/minecraft/servers/lobby"

    def test_dood_translates_exact_base_servers_dir(self) -> None:
        """Translates exact base servers dir to host servers dir."""
        host_dir = "/srv/minecraft/servers"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            resolved = resolve_host_mount_path("/app/data/servers")
            assert resolved == "/srv/minecraft/servers"

    def test_dood_translates_windows_host_path(self) -> None:
        """Translates host path with Windows drive letter and backslashes to forward slashes."""
        host_dir = r"D:\games\onx\data\servers"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            resolved = resolve_host_mount_path("/app/data/servers/creative")
            assert resolved == "D:/games/onx/data/servers/creative"

    def test_dood_fallback_for_custom_leaf_path(self) -> None:
        """When path is not under standard base dirs, resolves leaf name under host dir."""
        host_dir = "/opt/onx/data/servers"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            resolved = resolve_host_mount_path("/tmp/custom-server-leaf")
            assert resolved == "/opt/onx/data/servers/custom-server-leaf"

    def test_empty_path_returns_empty_string(self) -> None:
        """Empty or whitespace container path returns empty string."""
        assert resolve_host_mount_path("") == ""
        assert resolve_host_mount_path("   ") == ""

    def test_mcs_legacy_host_data_dir_env_supported(self) -> None:
        """Fallback to legacy MCS_HOST_DATA_DIR environment variable."""
        with patch.dict(os.environ, {"MCS_HOST_DATA_DIR": "/legacy/host/servers"}, clear=True):
            resolved = resolve_host_mount_path("/app/data/servers/legacy-srv")
            assert resolved == "/legacy/host/servers/legacy-srv"

    def test_app_settings_loads_host_data_dir(self) -> None:
        """AppSettings loads host_data_dir from environment."""
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": "/host/dir"}):
            settings = AppSettings()
            assert settings.host_data_dir == "/host/dir"

    def test_dood_trailing_slash_normalization(self) -> None:
        """Trailing slashes in container paths or host dir are normalized (O1 fix)."""
        host_dir = "/srv/minecraft/servers/"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            # Exact base path with trailing slash
            assert resolve_host_mount_path("/app/data/servers/") == "/srv/minecraft/servers"
            # Subpath with trailing slash
            res = resolve_host_mount_path("/app/data/servers/world/")
            assert res == "/srv/minecraft/servers/world"

    def test_dood_dot_dot_normalization(self) -> None:
        """Paths containing '..' and redundant slashes are normalized before matching (O2 fix)."""
        host_dir = "/srv/minecraft/servers"
        with patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}):
            assert (
                resolve_host_mount_path("/app/data/servers/../servers/lobby")
                == "/srv/minecraft/servers/lobby"
            )
            assert (
                resolve_host_mount_path("/app/data/servers/nested/../survival")
                == "/srv/minecraft/servers/survival"
            )


class TestDooDDockerProviderVolumeMount:
    """Test DockerProvider.start() and ContainerInstallerRunner volume mounts with DooD."""

    @pytest.mark.asyncio
    async def test_docker_provider_start_uses_dood_host_mount(self) -> None:
        """DockerProvider.start() translates volume mount path when ONX_HOST_DATA_DIR is set."""
        provider = DockerProvider()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path="/app/data/servers/dood-test-1",
            startup_jar="server.jar",
        )
        host_dir = "/host/mount/servers"

        with (
            patch.dict(
                os.environ,
                {"ONX_HOST_DATA_DIR": host_dir, "MCS_SERVERS_DATA_DIR": "/app/data/servers"},
            ),
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch(
                "app.modules.server.infrastructure.providers.docker.prepare_data_ownership",
                AsyncMock(),
            ),
        ):
            mock_cmd.side_effect = _make_docker_command_fake()
            await provider.start(
                server_id="dood-test-1",
                config={"server_id": "dood-test-1", "port": 25565},
                deployment=deployment,
            )

            # Locate the 'create' command in mock_cmd calls
            create_calls = [c for c in mock_cmd.call_args_list if c[0][0] == "create"]
            assert len(create_calls) == 1
            create_args = list(create_calls[0][0])
            # Verify volume mount uses translated host path
            v_idx = create_args.index("-v")
            mount_arg = create_args[v_idx + 1]
            assert mount_arg == "/host/mount/servers/dood-test-1:/data"

    @pytest.mark.asyncio
    async def test_docker_provider_start_native_mount_when_dood_unset(self) -> None:
        """DockerProvider.start() uses normalized local path when ONX_HOST_DATA_DIR is unset."""
        provider = DockerProvider()
        deployment = ServerDeployment(
            location_type=LocationType.DOCKER,
            root_path="/data/servers/native-test-1",
            startup_jar="server.jar",
        )

        with (
            patch.dict(os.environ, {"MCS_SERVERS_DATA_DIR": "/data/servers"}, clear=True),
            patch.object(provider, "_ensure_image", AsyncMock()),
            patch.object(provider, "_docker_command", AsyncMock()) as mock_cmd,
            patch(
                "app.modules.server.infrastructure.providers.docker.prepare_data_ownership",
                AsyncMock(),
            ),
        ):
            mock_cmd.side_effect = _make_docker_command_fake()
            await provider.start(
                server_id="native-test-1",
                config={"server_id": "native-test-1", "port": 25565},
                deployment=deployment,
            )

            create_calls = [c for c in mock_cmd.call_args_list if c[0][0] == "create"]
            assert len(create_calls) == 1
            create_args = list(create_calls[0][0])
            v_idx = create_args.index("-v")
            mount_arg = create_args[v_idx + 1]
            expected = f"{normalize_host_path('/data/servers/native-test-1')}:/data"
            assert mount_arg == expected

    @pytest.mark.asyncio
    async def test_container_installer_runner_uses_dood_host_mount(self) -> None:
        """ContainerInstallerRunner translates cwd volume mount when ONX_HOST_DATA_DIR is set."""
        runner = ContainerInstallerRunner()
        host_dir = "/srv/host/data/servers"

        captured_args: list[str] = []

        async def fake_subprocess_exec(*args: str, **_kwargs: object) -> AsyncMock:
            nonlocal captured_args
            captured_args = list(args)
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.stdout = AsyncMock()

            async def empty_generator():
                if False:
                    yield b""

            mock_proc.stdout.__aiter__ = lambda _self: empty_generator()
            mock_proc.wait = AsyncMock(return_value=0)
            return mock_proc

        with (
            patch.dict(os.environ, {"ONX_HOST_DATA_DIR": host_dir}),
            patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess_exec),
        ):
            outputs = []
            async for out in runner.run(
                "echo test",
                timeout=5.0,
                cwd="/app/data/servers/installer-srv",
            ):
                outputs.append(out)

            assert "-v" in captured_args
            v_idx = captured_args.index("-v")
            assert captured_args[v_idx + 1] == "/srv/host/data/servers/installer-srv:/data"


class TestComposeDooDPolicyIntegrity:
    """Validate docker-compose.yml and docker-compose.dood.yml security boundaries."""

    def test_default_compose_never_mounts_docker_socket(self) -> None:
        """Default docker-compose.yml MUST NOT mount /var/run/docker.sock (Decision 12)."""
        compose_path = Path(__file__).parents[3] / "docker-compose.yml"
        assert compose_path.exists(), "docker-compose.yml not found at repo root"
        with open(compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        backend_volumes = data["services"]["backend"].get("volumes", [])
        for vol in backend_volumes:
            assert "docker.sock" not in str(vol), (
                f"SECURITY VIOLATION: docker.sock found in default compose file: {vol}"
            )

    def test_dood_compose_mounts_docker_socket_and_binds_servers(self) -> None:
        """docker-compose.dood.yml MUST mount docker.sock and set ONX_HOST_DATA_DIR."""
        dood_path = Path(__file__).parents[3] / "docker-compose.dood.yml"
        assert dood_path.exists(), "docker-compose.dood.yml not found at repo root"
        with open(dood_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        backend = data["services"]["backend"]
        volumes = backend.get("volumes", [])
        has_socket = any("/var/run/docker.sock" in str(v) for v in volumes)
        assert has_socket, "docker-compose.dood.yml must mount /var/run/docker.sock"

        # Confirms user is set to root for socket access
        assert backend.get("user") == "root"

        # Confirms ONX_HOST_DATA_DIR is passed in environment
        env = backend.get("environment", [])
        has_host_data_env = any("ONX_HOST_DATA_DIR" in str(e) for e in env)
        assert has_host_data_env, "docker-compose.dood.yml must specify ONX_HOST_DATA_DIR"
