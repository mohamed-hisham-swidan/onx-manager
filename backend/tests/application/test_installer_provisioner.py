from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import AsyncGenerator, Union
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from app.core.exceptions import DownloadError, DownloadTimeoutError
from app.modules.server.application.services.forge_provisioner import (
    ForgeProvisioner,
    provision_forge_server,
)
from app.modules.server.application.services.installer_provisioner import (
    FailureClass,
    FailureDisposition,
    InstallerProvisioner,
)
from app.modules.server.application.services.neoforge_provisioner import (
    NeoForgeProvisioner,
    provision_neoforge_server,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.installer import InstallerResult, ProgressLine
from app.modules.server.domain.runtime_exceptions import (
    BuildResolutionError,
    InstallerDownloadError,
    InstallerExecutionError,
    InsufficientDiskError,
    MetadataFetchError,
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


def _create_test_server(server_id: str, server_type: ServerType, root_path: str) -> Server:
    server = Server.create(
        server_id=ServerId(server_id),
        name=f"Test {server_type.value}",
        server_type=server_type,
        minecraft_version=MinecraftVersion.parse("1.21.1"),
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
    ) -> AsyncGenerator[Union[ProgressLine, InstallerResult], None]:
        _ = (command, timeout, cwd)
        yield ProgressLine(stage="installing", percent=50, message="Processing…", raw_line="")
        yield result
        return

    return SimpleNamespace(run=run)


def _make_fs() -> MagicMock:
    fs = MagicMock()
    fs.exists.return_value = True
    fs.write_text.return_value = None
    fs.delete_dir.return_value = None
    fs.delete.return_value = None
    fs.write_binary_atomic.return_value = None
    return fs


class ConcreteTestProvisioner(InstallerProvisioner):
    @property
    def provider_name(self) -> str:
        return "TestProvider"

    async def _resolve_build(self, minecraft_version: str) -> str | None:
        return f"{minecraft_version}-1.0.0"

    def _installer_url(self, full_version: str) -> str:
        return f"https://example.com/{full_version}-installer.jar"

    def _installer_filename(self) -> str:
        return "test-installer.jar"

    def _installer_args(self) -> str:
        return "java -jar test-installer.jar --installServer"


class TestFailureClassification:
    def setup_method(self) -> None:
        self.provisioner = ConcreteTestProvisioner()

    def test_insufficient_disk_is_fatal(self) -> None:
        exc = InsufficientDiskError(server_id="s1", free_mb=100, required_mb=4096)
        disp = self.provisioner._classify_failure(exc)
        assert disp.classification == FailureClass.FATAL
        assert disp.preserve_directory is False
        assert disp.retryable is False
        assert disp.target_status == ServerStatus.BROKEN

    def test_build_resolution_genuine_zero_matches_is_fatal(self) -> None:
        exc = BuildResolutionError(server_id="s1", detail="no build", underlying_fetch_failed=False)
        disp = self.provisioner._classify_failure(exc)
        assert disp.classification == FailureClass.FATAL
        assert disp.preserve_directory is False
        assert disp.retryable is False
        assert disp.target_status == ServerStatus.BROKEN

    def test_metadata_fetch_error_is_transient(self) -> None:
        exc = MetadataFetchError(server_id="s1", detail="network timeout")
        disp = self.provisioner._classify_failure(exc)
        assert disp.classification == FailureClass.TRANSIENT
        assert disp.preserve_directory is True
        assert disp.retryable is True
        assert disp.target_status == ServerStatus.PROVISIONING_FAILED

    def test_installer_download_error_is_transient(self) -> None:
        exc = InstallerDownloadError(server_id="s1", detail="502 Bad Gateway", url="http://...")
        disp = self.provisioner._classify_failure(exc)
        assert disp.classification == FailureClass.TRANSIENT
        assert disp.preserve_directory is True
        assert disp.retryable is True
        assert disp.target_status == ServerStatus.PROVISIONING_FAILED

    def test_network_exceptions_are_transient(self) -> None:
        for exc in (
            asyncio.TimeoutError(),
            TimeoutError(),
            aiohttp.ClientError("connection reset"),
            DownloadError("http://...", 503, "Service Unavailable"),
            DownloadTimeoutError("http://...", 60),
        ):
            disp = self.provisioner._classify_failure(exc)
            assert disp.classification == FailureClass.TRANSIENT
            assert disp.preserve_directory is True
            assert disp.retryable is True
            assert disp.target_status == ServerStatus.PROVISIONING_FAILED

    def test_build_resolution_underlying_fetch_failed_is_ambiguous(self) -> None:
        exc = BuildResolutionError(server_id="s1", detail="fetch dropped", underlying_fetch_failed=True)
        disp = self.provisioner._classify_failure(exc)
        assert disp.classification == FailureClass.AMBIGUOUS
        assert disp.preserve_directory is True
        assert disp.retryable is False
        assert disp.target_status == ServerStatus.PROVISIONING_FAILED

    def test_installer_execution_error_is_ambiguous(self) -> None:
        for exc in (
            InstallerExecutionError(server_id="s1", detail="exit code 1", exit_code=1),
            InstallerExecutionError(server_id="s1", detail="timed out", timed_out=True),
            InstallerExecutionError(server_id="s1", detail="run.sh missing"),
        ):
            disp = self.provisioner._classify_failure(exc)
            assert disp.classification == FailureClass.AMBIGUOUS
            assert disp.preserve_directory is True
            assert disp.retryable is False
            assert disp.target_status == ServerStatus.PROVISIONING_FAILED

    def test_unclassified_exception_is_ambiguous(self) -> None:
        exc = RuntimeError("unexpected OS error")
        disp = self.provisioner._classify_failure(exc)
        assert disp.classification == FailureClass.AMBIGUOUS
        assert disp.preserve_directory is True
        assert disp.retryable is False
        assert disp.target_status == ServerStatus.PROVISIONING_FAILED


class TestProvisioningAutoRetry:
    @pytest.mark.asyncio
    async def test_transient_failure_retries_and_succeeds(self) -> None:
        server = _create_test_server("srv-retry-ok", ServerType.NEOFORGE, "/data/srv-retry-ok")
        fs = _make_fs()
        attempts = 0

        async def mock_install(sid, s, mc, s_dir):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise InstallerDownloadError(server_id=str(sid), detail="temporary network drop")
            s.update_launch_config(s.launch_config)
            s.finish_provisioning()
            return s

        with (
            patch("app.modules.server.application.services.installer_provisioner._load_server", AsyncMock(return_value=server)),
            patch("app.modules.server.application.services.installer_provisioner._save_server", AsyncMock()),
            patch("asyncio.sleep", AsyncMock()) as mock_sleep,
        ):
            provisioner = ConcreteTestProvisioner(fs=fs, max_retries=3)
            provisioner._install = mock_install  # type: ignore

            await provisioner.provision("srv-retry-ok", "1.21.1")

            assert attempts == 2
            assert server.status == ServerStatus.CREATED
            assert server.provisioning_error is None
            assert server.provisioning_retryable is False
            mock_sleep.assert_called_once_with(1.0)  # 1.0 * (2 ** 0)

    @pytest.mark.asyncio
    async def test_transient_failure_exhausts_retries_and_marks_non_retryable(self) -> None:
        server = _create_test_server("srv-retry-fail", ServerType.FORGE, "/data/srv-retry-fail")
        fs = _make_fs()
        attempts = 0

        async def mock_install(sid, s, mc, s_dir):
            nonlocal attempts
            attempts += 1
            raise MetadataFetchError(server_id=str(sid), detail="persistent network down")

        with (
            patch("app.modules.server.application.services.installer_provisioner._load_server", AsyncMock(return_value=server)),
            patch("app.modules.server.application.services.installer_provisioner._save_server", AsyncMock()),
            patch("asyncio.sleep", AsyncMock()),
        ):
            provisioner = ConcreteTestProvisioner(fs=fs, max_retries=3)
            provisioner._install = mock_install  # type: ignore

            with pytest.raises(MetadataFetchError):
                await provisioner.provision("srv-retry-fail", "1.20.1")

            assert attempts == 3
            # After exhausting max retries, fall through to AMBIGUOUS handling:
            # preserve directory, target status PROVISIONING_FAILED, retryable=False
            assert server.status == ServerStatus.PROVISIONING_FAILED
            assert server.provisioning_retryable is False
            assert "persistent network down" in str(server.provisioning_error)
            fs.delete_dir.assert_not_called()

    @pytest.mark.asyncio
    async def test_fatal_failure_fails_immediately_without_retry(self) -> None:
        server = _create_test_server("srv-fatal", ServerType.NEOFORGE, "/data/srv-fatal")
        fs = _make_fs()
        attempts = 0

        async def mock_install(sid, s, mc, s_dir):
            nonlocal attempts
            attempts += 1
            raise InsufficientDiskError(server_id=str(sid), free_mb=50, required_mb=4096)

        with (
            patch("app.modules.server.application.services.installer_provisioner._load_server", AsyncMock(return_value=server)),
            patch("app.modules.server.application.services.installer_provisioner._save_server", AsyncMock()),
            patch("asyncio.sleep", AsyncMock()) as mock_sleep,
        ):
            provisioner = ConcreteTestProvisioner(fs=fs, max_retries=3)
            provisioner._install = mock_install  # type: ignore

            with pytest.raises(InsufficientDiskError):
                await provisioner.provision("srv-fatal", "1.21.1")

            assert attempts == 1
            mock_sleep.assert_not_called()
            assert server.status == ServerStatus.BROKEN
            assert server.provisioning_retryable is False
            fs.delete_dir.assert_called_with("/data/srv-fatal")


class TestSubclassContractParity:
    @pytest.mark.parametrize(
        "provisioner_cls,server_type,provider_name,installer_file,installer_cmd",
        [
            (ForgeProvisioner, ServerType.FORGE, "Forge", "forge-installer.jar", "java -jar forge-installer.jar --installServer"),
            (NeoForgeProvisioner, ServerType.NEOFORGE, "NeoForge", "neoforge-installer.jar", "java -jar neoforge-installer.jar --installServer"),
        ],
    )
    def test_subclass_hooks_and_properties(
        self,
        provisioner_cls: type[InstallerProvisioner],
        server_type: ServerType,
        provider_name: str,
        installer_file: str,
        installer_cmd: str,
    ) -> None:
        inst = provisioner_cls()
        assert inst.provider_name == provider_name
        assert inst._installer_filename() == installer_file
        assert inst._installer_args() == installer_cmd
        assert inst._run_sh_name() == "run.sh"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "provisioner_cls,server_type,resolve_fn",
        [
            (ForgeProvisioner, ServerType.FORGE, "app.modules.server.application.services.forge_provisioner.resolve_forge_build"),
            (NeoForgeProvisioner, ServerType.NEOFORGE, "app.modules.server.application.services.neoforge_provisioner.resolve_neoforge_build"),
        ],
    )
    async def test_end_to_end_subclass_provision_flow(
        self,
        provisioner_cls: type[InstallerProvisioner],
        server_type: ServerType,
        resolve_fn: str,
    ) -> None:
        sid = f"srv-{server_type.value}"
        server = _create_test_server(sid, server_type, f"/data/{sid}")
        fs = _make_fs()

        with (
            patch("app.modules.server.application.services.installer_provisioner._load_server", AsyncMock(return_value=server)),
            patch("app.modules.server.application.services.installer_provisioner._save_server", AsyncMock()),
            patch(resolve_fn, AsyncMock(return_value="1.21.1-build-99")),
            patch("app.modules.server.application.services.installer_provisioner.download_installer_jar", AsyncMock(return_value=f"/data/{sid}/installer.jar")),
            patch("app.modules.server.application.services.installer_provisioner.shutil.disk_usage", return_value=SimpleNamespace(free=64 * 1024 * 1024 * 1024)),
        ):
            provisioner = provisioner_cls(
                runner=_make_runner(InstallerResult(exit_code=0, output="Installation complete")),
                fs=fs,
            )
            await provisioner.provision(sid, "1.21.1")

            assert server.status == ServerStatus.CREATED
            assert server.launch_config is not None
            assert server.launch_config.startup_command == "bash run.sh nogui"
            fs.delete.assert_called_with(f"/data/{sid}/{provisioner._installer_filename()}")
