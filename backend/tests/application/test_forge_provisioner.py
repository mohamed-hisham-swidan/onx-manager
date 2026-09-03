from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.server.application.services.forge_provisioner import (
    ForgeProvisioner,
    provision_forge_server,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.installer import InstallerResult, ProgressLine
from app.modules.server.domain.runtime_exceptions import (
    InstallerExecutionError,
    InsufficientDiskError,
)
from app.modules.server.domain.value_objects import (
    JavaArguments,
    LocationType,
    MemoryAllocation,
    PortNumber,
    ServerDeployment,
    ServerProperties,
    ServerType,
)
from app.modules.shared.value_objects import MinecraftVersion, ServerId


def _provisioning_server(server_id: str, root_path: str) -> Server:
    server = Server.create(
        server_id=ServerId(server_id),
        name="Forge Test",
        server_type=ServerType.FORGE,
        minecraft_version=MinecraftVersion.parse("1.20.1"),
        memory=MemoryAllocation(1024, 2048),
        java_args=JavaArguments(),
        properties=ServerProperties(port=PortNumber(25565)),
        deployment=ServerDeployment(
            location_type=LocationType.LOCAL,
            root_path=root_path,
            working_directory=".",
            startup_jar="server.jar",
        ),
    )
    server.collect_events()
    server.begin_provisioning()
    return server


def _make_runner(result: InstallerResult) -> object:
    async def run(
        command: str,
        *,
        timeout: float,
        cwd: str | None = None,
    ) -> AsyncGenerator[ProgressLine | InstallerResult, None]:
        _ = (command, timeout, cwd)
        yield ProgressLine(
            stage="success", percent=100, message="Process exited with code 0", raw_line=""
        )
        yield result
        return

    return SimpleNamespace(run=run)


def _make_fs() -> MagicMock:
    fs = MagicMock()
    fs.exists.return_value = True
    fs.write_text.return_value = None
    fs.delete_dir.return_value = None
    fs.write_binary_atomic.return_value = None
    fs.delete.return_value = None
    return fs


def _patch_common(server: Server):
    patches = [
        patch(
            "app.modules.server.application.services.installer_provisioner._load_server",
            new=AsyncMock(return_value=server),
        ),
        patch(
            "app.modules.server.application.services.installer_provisioner._save_server",
            new=AsyncMock(),
        ),
        patch(
            "app.modules.server.application.services.forge_provisioner.resolve_forge_build",
            new=AsyncMock(return_value="1.20.1-47.4.23"),
        ),
        patch(
            "app.modules.server.application.services.installer_provisioner.download_installer_jar",
            new=AsyncMock(return_value="/srv/forge-installer.jar"),
        ),
    ]
    for p in patches:
        p.start()
    return patches


def _patch_disk_space(free_bytes: int):
    p = patch(
        "app.modules.server.application.services.installer_provisioner.shutil.disk_usage",
        return_value=SimpleNamespace(free=free_bytes),
    )
    p.start()
    return p


class TestForgeProvisioner:
    @pytest.mark.asyncio
    async def test_success_persists_launch_config_and_returns_to_created(self) -> None:
        server = _provisioning_server("forge-ok", "/data/forge-ok")
        patches = _patch_common(server)
        disk_patch = _patch_disk_space(64 * 1024 * 1024 * 1024)
        patches.append(disk_patch)
        fs = _make_fs()
        try:
            provisioner = ForgeProvisioner(
                runner=_make_runner(InstallerResult(exit_code=0, output="Installing…done")),
                fs=fs,
            )
            await provisioner.provision("forge-ok", "1.20.1")

            assert server.status == ServerStatus.CREATED
            assert server.launch_config is not None
            expected_cmd = (
                ("run.bat", "nogui") if sys.platform == "win32" else ("bash", "run.sh", "nogui")
            )
            assert server.launch_config.startup_command == expected_cmd
            assert fs.delete.call_count == 1
            assert (
                Path(fs.delete.call_args[0][0]).as_posix()
                == "/data/forge-ok/forge-installer.jar"
            )
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_installer_nonzero_exit_marks_provisioning_failed_and_preserves_dir(self) -> None:
        server = _provisioning_server("forge-err", "/data/forge-err")
        fs = _make_fs()
        patches = _patch_common(server)
        disk_patch = _patch_disk_space(64 * 1024 * 1024 * 1024)
        patches.append(disk_patch)
        try:
            provisioner = ForgeProvisioner(
                runner=_make_runner(InstallerResult(exit_code=1, output="boom")),
                fs=fs,
            )
            with pytest.raises(InstallerExecutionError):
                await provisioner.provision("forge-err", "1.20.1")

            # Ambiguous failure: preserve directory, mark PROVISIONING_FAILED, retryable=False
            assert server.status == ServerStatus.PROVISIONING_FAILED
            assert server.provisioning_retryable is False
            assert "1" in str(server.provisioning_error)
            fs.delete_dir.assert_not_called()
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_timeout_marks_provisioning_failed(self) -> None:
        server = _provisioning_server("forge-to", "/data/forge-to")
        patches = _patch_common(server)
        disk_patch = _patch_disk_space(64 * 1024 * 1024 * 1024)
        patches.append(disk_patch)
        fs = _make_fs()
        try:
            provisioner = ForgeProvisioner(
                runner=_make_runner(InstallerResult(exit_code=None, output="", timed_out=True)),
                fs=fs,
            )
            with pytest.raises(InstallerExecutionError):
                await provisioner.provision("forge-to", "1.20.1")

            assert server.status == ServerStatus.PROVISIONING_FAILED
            assert server.provisioning_retryable is False
            fs.delete_dir.assert_not_called()
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_insufficient_disk_raises_before_install_and_cleans_dir(self) -> None:
        server = _provisioning_server("forge-disk", "/data/forge-disk")
        patches = _patch_common(server)
        disk_patch = _patch_disk_space(100 * 1024 * 1024)
        patches.append(disk_patch)
        fs = _make_fs()
        try:
            provisioner = ForgeProvisioner(
                runner=_make_runner(InstallerResult(exit_code=0, output="")),
                fs=fs,
            )
            with pytest.raises(InsufficientDiskError):
                await provisioner.provision("forge-disk", "1.20.1")

            # Fatal failure: delete directory, mark BROKEN, retryable=False
            assert server.status == ServerStatus.BROKEN
            assert server.provisioning_retryable is False
            fs.delete_dir.assert_called_with("/data/forge-disk")
        finally:
            for p in patches:
                p.stop()

    @pytest.mark.asyncio
    async def test_run_sh_missing_marks_provisioning_failed(self) -> None:
        server = _provisioning_server("forge-norun", "/data/forge-norun")
        fs = _make_fs()
        fs.exists.return_value = False
        patches = _patch_common(server)
        disk_patch = _patch_disk_space(64 * 1024 * 1024 * 1024)
        patches.append(disk_patch)
        try:
            provisioner = ForgeProvisioner(
                runner=_make_runner(InstallerResult(exit_code=0, output="")),
                fs=fs,
            )
            with pytest.raises(InstallerExecutionError, match="run.sh"):
                await provisioner.provision("forge-norun", "1.20.1")

            assert server.status == ServerStatus.PROVISIONING_FAILED
            assert server.provisioning_retryable is False
            fs.delete_dir.assert_not_called()
        finally:
            for p in patches:
                p.stop()

    def test_provision_forge_server_spawns_task(self) -> None:
        import asyncio

        async def _main() -> asyncio.Task[None]:
            with patch(
                "app.modules.server.application.services.forge_provisioner.ForgeProvisioner"
            ) as mock_cls:

                async def provision(server_id: str, minecraft_version: str) -> None:
                    _ = (server_id, minecraft_version)
                    return None

                mock_cls.return_value.provision = provision
                task = provision_forge_server("abc", "1.20.1")
                await task
                return task

        task = asyncio.run(_main())
        assert isinstance(task, asyncio.Task)

    @pytest.mark.asyncio
    async def test_provisioned_task_is_tracked_until_done(self) -> None:
        """The background task must be strongly referenced (registry) so it
        cannot be garbage-collected, and must be dropped once finished."""
        import asyncio

        from app.modules.server.application.services import forge_provisioner as fp

        with patch(
            "app.modules.server.application.services.forge_provisioner.ForgeProvisioner"
        ) as mock_cls:

            async def provision(server_id: str, minecraft_version: str) -> None:
                _ = (server_id, minecraft_version)
                await asyncio.sleep(0)

            mock_cls.return_value.provision = provision
            task = fp.provision_forge_server("tracked-1", "1.20.1")
            assert task in fp._background_tasks
            await task
            await asyncio.sleep(0)
            assert task not in fp._background_tasks

    @pytest.mark.asyncio
    async def test_tracked_task_exception_is_retrieved(self) -> None:
        """A failing provisioning task must not surface "exception never
        retrieved" noise — the registry callback retrieves it."""
        import asyncio

        from app.modules.server.application.services import forge_provisioner as fp

        with patch(
            "app.modules.server.application.services.forge_provisioner.ForgeProvisioner"
        ) as mock_cls:

            async def provision(server_id: str, minecraft_version: str) -> None:
                _ = (server_id, minecraft_version)
                raise RuntimeError("boom")

            mock_cls.return_value.provision = provision
            task = fp.provision_forge_server("tracked-2", "1.20.1")
            with pytest.raises(RuntimeError, match="boom"):
                await task
            await asyncio.sleep(0)
            assert task not in fp._background_tasks
            assert task.exception() is not None
