from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any, NamedTuple, cast

import aiohttp

from app.core.config import AppSettings
from app.core.event_bus import EventBus
from app.core.exceptions import DownloadError, DownloadTimeoutError, UnsupportedForgeVersionError
from app.core.persistence.db import database
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.application.services.jar_service import (
    download_installer_jar,
)
from app.modules.server.domain.aggregate import Server, ServerStatus
from app.modules.server.domain.events import ForgeProvisionProgressEvent
from app.modules.server.domain.installer import (
    InstallerResult,
    InstallerRunner,
    ProgressLine,
    RunnerOutput,
)
from app.modules.server.domain.runtime_exceptions import (
    BuildResolutionError,
    InstallerDownloadError,
    InstallerExecutionError,
    InsufficientDiskError,
    MetadataFetchError,
)
from app.modules.server.domain.value_objects import LaunchConfiguration
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.installer import resolve_installer_runner
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_SECONDS: float = 1800.0
MIN_FREE_DISK_MB: int = 4096
JVM_ARGS_FILENAME: str = "user_jvm_args.txt"
MAX_PROVISION_RETRIES: int = 3


class FailureClass(Enum):
    TRANSIENT = "transient"
    AMBIGUOUS = "ambiguous"
    FATAL = "fatal"


class FailureDisposition(NamedTuple):
    classification: FailureClass
    preserve_directory: bool
    retryable: bool
    target_status: ServerStatus


class ProvisioningRegistry:
    _tasks: dict[str, asyncio.Task[Any]] = {}
    _processes: dict[str, Any] = {}

    @classmethod
    def register_task(cls, server_id: str, task: asyncio.Task[Any]) -> None:
        cls._tasks[str(server_id)] = task

    @classmethod
    def register_process(cls, server_id: str, proc: Any) -> None:
        cls._processes[str(server_id)] = proc

    @classmethod
    def unregister(cls, server_id: str) -> None:
        sid = str(server_id)
        cls._tasks.pop(sid, None)
        cls._processes.pop(sid, None)

    @classmethod
    async def cancel_and_wait(cls, server_id: str, timeout: float = 15.0) -> bool:
        sid = str(server_id)
        proc = cls._processes.pop(sid, None)
        task = cls._tasks.pop(sid, None)

        if proc is not None:
            try:
                if hasattr(proc, "terminate"):
                    proc.terminate()
                elif hasattr(proc, "kill"):
                    proc.kill()
            except Exception as exc:
                logger.debug("Error terminating provisioning process for %s: %s", sid, exc)

        if task is not None and not task.done():
            task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            except (asyncio.CancelledError, TimeoutError, Exception) as exc:
                logger.debug("Wait for cancelled provisioning task %s ended with %s", sid, exc)

        if proc is not None:
            try:
                if hasattr(proc, "kill"):
                    proc.kill()
            except Exception:
                pass

        return True


class InstallerProvisioner(ABC):
    """Abstract base class for Forge and NeoForge server provisioning flows."""

    def __init__(
        self,
        runner: InstallerRunner | None = None,
        fs: FileSystem | None = None,
        event_bus: EventBus | None = None,
        *,
        install_timeout: float = INSTALL_TIMEOUT_SECONDS,
        min_free_disk_mb: int = MIN_FREE_DISK_MB,
        max_retries: int = MAX_PROVISION_RETRIES,
    ) -> None:
        self._runner = resolve_installer_runner(runner)
        self._fs = fs or local_fs
        self._event_bus = event_bus or EventBus()
        self._install_timeout = install_timeout
        self._min_free_disk_mb = min_free_disk_mb
        self._max_retries = max_retries

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name (e.g. 'Forge' or 'NeoForge')."""
        ...

    @abstractmethod
    async def _resolve_build(self, minecraft_version: str) -> str | None:
        """Resolve full version string for the given Minecraft version."""
        ...

    @abstractmethod
    def _installer_url(self, full_version: str) -> str:
        """Return the remote Maven URL to download the installer jar."""
        ...

    @abstractmethod
    def _installer_filename(self) -> str:
        """Return the local installer filename (e.g. 'forge-installer.jar')."""
        ...

    @abstractmethod
    def _installer_args(self) -> str:
        """Return the CLI command string to execute the installer."""
        ...

    @abstractmethod
    def _unix_args_relpath(self, minecraft_version: str, full_version: str) -> str:
        """Return the canonical ``libraries/.../unix_args.txt`` relative path."""
        ...

    def _run_sh_name(self) -> str:
        """Return the expected launcher script name."""
        return "run.sh"

    def _detect_launch_script(self, server_dir: str) -> tuple[str, list[str]]:
        """Detect whether run.sh or run.bat was produced.

        Returns (script_name, startup_command).
        """
        run_sh = self._run_sh_name()
        run_bat = "run.bat"
        sh_path = os.path.join(server_dir, run_sh)
        bat_path = os.path.join(server_dir, run_bat)

        sh_exists = self._fs.exists(sh_path)
        bat_exists = self._fs.exists(bat_path)

        if sys.platform == "win32":
            if bat_exists:
                return run_bat, [run_bat, "nogui"]
            if sh_exists:
                return run_sh, ["bash", run_sh, "nogui"]
        else:
            if sh_exists:
                return run_sh, ["bash", run_sh, "nogui"]
            if bat_exists:
                return run_bat, [run_bat, "nogui"]

        return "", []

    def _classify_failure(self, exc: Exception) -> FailureDisposition:
        """Classify a provisioning exception into TRANSIENT, AMBIGUOUS, or FATAL."""
        if isinstance(exc, (InsufficientDiskError, UnsupportedForgeVersionError)):
            return FailureDisposition(
                classification=FailureClass.FATAL,
                preserve_directory=False,
                retryable=False,
                target_status=ServerStatus.BROKEN,
            )

        if isinstance(exc, BuildResolutionError) and not exc.underlying_fetch_failed:
            # Metadata fetch succeeded but genuinely returned zero builds for this version
            return FailureDisposition(
                classification=FailureClass.FATAL,
                preserve_directory=False,
                retryable=False,
                target_status=ServerStatus.BROKEN,
            )

        if isinstance(
            exc,
            (
                MetadataFetchError,
                InstallerDownloadError,
                asyncio.TimeoutError,
                TimeoutError,
                aiohttp.ClientError,
                DownloadError,
                DownloadTimeoutError,
            ),
        ):
            return FailureDisposition(
                classification=FailureClass.TRANSIENT,
                preserve_directory=True,
                retryable=True,
                target_status=ServerStatus.PROVISIONING_FAILED,
            )

        # InstallerExecutionError, BuildResolutionError with underlying fetch failed, or unknown
        return FailureDisposition(
            classification=FailureClass.AMBIGUOUS,
            preserve_directory=True,
            retryable=False,
            target_status=ServerStatus.PROVISIONING_FAILED,
        )

    async def provision(self, server_id: str, minecraft_version: str) -> None:
        """Run the provisioning flow with auto-retry on TRANSIENT failures."""
        sid = ServerId(server_id)
        server_dir: str | None = None

        try:
            for attempt in range(self._max_retries):
                try:
                    server = await _load_server(sid)
                    if server.deployment is None:
                        raise InstallerExecutionError(
                            server_id=str(sid),
                            detail="server has no deployment directory",
                        )
                    server_dir = server.deployment.server_directory()

                    server = await self._install(sid, server, minecraft_version, server_dir)
                    try:
                        fresh_check = await _load_server(sid)
                        if fresh_check is None:
                            logger.info(
                                "Server %s was deleted during provisioning; skipping finish save",
                                sid,
                            )
                            return
                    except Exception:
                        logger.info(
                            "Server %s was deleted during provisioning; skipping finish save",
                            sid,
                        )
                        return

                    await _save_server(server, self._event_bus)
                    logger.info(
                        '%s provisioning complete for server "%s" (%s) — '
                        'start_command="bash %s nogui"',
                        self.provider_name,
                        server.name,
                        sid,
                        self._run_sh_name(),
                    )
                    return
                except Exception as exc:
                    disp = self._classify_failure(exc)
                    if (
                        disp.classification == FailureClass.TRANSIENT
                        and attempt < self._max_retries - 1
                    ):
                        backoff = 1.0 * (2**attempt)
                        logger.warning(
                            "%s provisioning attempt %d/%d for server %s failed "
                            "transiently (%s: %s). Retrying in %.1fs...",
                            self.provider_name,
                            attempt + 1,
                            self._max_retries,
                            sid,
                            type(exc).__name__,
                            exc,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue

                    if (
                        disp.classification == FailureClass.TRANSIENT
                        and attempt >= self._max_retries - 1
                    ):
                        logger.error(
                            "%s provisioning exhausted %d attempts for server %s (%s: %s). "
                            "Manual intervention required.",
                            self.provider_name,
                            self._max_retries,
                            sid,
                            type(exc).__name__,
                            exc,
                        )
                        await self._fail_provisioning(sid, server_dir, exc, force_retryable=False)
                        raise

                    # Non-transient (FATAL or AMBIGUOUS)
                    await self._fail_provisioning(sid, server_dir, exc)
                    raise
        finally:
            ProvisioningRegistry.unregister(str(sid))

    async def _install(
        self,
        sid: ServerId,
        server: Server,
        minecraft_version: str,
        server_dir: str,
    ) -> Server:
        """Template method executing the complete installation pipeline."""
        self._check_disk_space(str(sid), server_dir)

        full_version = await self._resolve_build(minecraft_version)
        if full_version is None:
            raise BuildResolutionError(
                server_id=str(sid),
                detail=f"no {self.provider_name} build found for Minecraft {minecraft_version}",
                underlying_fetch_failed=False,
            )

        installer_url = self._installer_url(full_version)
        installer_dest = os.path.join(server_dir, self._installer_filename())
        await download_installer_jar(installer_url, installer_dest, fs=self._fs)

        result: InstallerResult | None = None
        installer_stream = cast(
            AsyncGenerator[RunnerOutput, None],
            self._runner.run(
                self._installer_args(),
                timeout=self._install_timeout,
                cwd=server_dir,
            ),
        )
        async for progress in installer_stream:
            if isinstance(progress, ProgressLine):
                if self._event_bus:
                    await self._event_bus.publish(
                        ForgeProvisionProgressEvent(
                            server_id=sid,
                            stage=progress.stage,
                            percent=progress.percent,
                            message=progress.message,
                        )
                    )
            elif isinstance(progress, InstallerResult):
                result = progress

        if result is None:
            raise InstallerExecutionError(
                server_id=str(sid),
                detail="installer did not return a result",
            )

        if result.timed_out:
            raise InstallerExecutionError(
                server_id=str(sid),
                detail=f"installer timed out after {self._install_timeout}s",
                timed_out=True,
            )
        if result.exit_code != 0:
            raise InstallerExecutionError(
                server_id=str(sid),
                detail=f"installer exited with code {result.exit_code}",
                exit_code=result.exit_code,
            )

        script_name = ""
        startup_command: list[str] = []
        if AppSettings().allow_legacy_run_sh:
            script_name, startup_command = self._detect_launch_script(server_dir)
            if not script_name:
                raise InstallerExecutionError(
                    server_id=str(sid),
                    detail=(
                        f"installer finished but neither {self._run_sh_name()} "
                        "nor run.bat was produced"
                    ),
                )
        else:
            unix_args_rel = self._unix_args_relpath(minecraft_version, full_version)
            unix_args_path = os.path.join(server_dir, unix_args_rel)
            if not self._fs.exists(unix_args_path):
                raise InstallerExecutionError(
                    server_id=str(sid),
                    detail=f"installer finished but {unix_args_rel} was not produced",
                )
            startup_command = [
                "java",
                "@user_jvm_args.txt",
                f"@{unix_args_rel}",
                "nogui",
            ]
            for name in (
                "run.sh",
                "run.bat",
                "ServerStarterJar",
                "serverstarter.jar",
                self._installer_filename(),
            ):
                target = os.path.join(server_dir, name)
                try:
                    if self._fs.exists(target):
                        self._fs.delete(target)
                except Exception as exc:
                    logger.warning(
                        "Could not remove builder artifact %s (server %s, %s: %s)",
                        target,
                        sid,
                        type(exc).__name__,
                        exc,
                    )

        try:
            self._fs.delete(installer_dest)
        except Exception as exc:
            logger.warning(
                "Could not remove installer jar %s after successful install (server %s, %s: %s)",
                installer_dest,
                sid,
                type(exc).__name__,
                exc,
            )

        self._write_user_jvm_args(server, server_dir)

        server.update_launch_config(
            LaunchConfiguration(startup_command=startup_command),
        )
        server.finish_provisioning()
        return server

    def _check_disk_space(self, server_id: str, server_dir: str) -> None:
        try:
            free_mb = int(shutil.disk_usage(server_dir).free / (1024 * 1024))
        except OSError:
            free_mb = 0
        if free_mb < self._min_free_disk_mb:
            raise InsufficientDiskError(
                server_id=server_id,
                free_mb=free_mb,
                required_mb=self._min_free_disk_mb,
            )

    def _write_user_jvm_args(self, server: Server, server_dir: str) -> None:
        content = f"-Xms{server.memory.min_mb}M\n-Xmx{server.memory.max_mb}M\n"
        self._fs.write_text(
            os.path.join(server_dir, JVM_ARGS_FILENAME),
            content,
        )

    async def _fail_provisioning(
        self,
        sid: ServerId,
        server_dir: str | None,
        exc: Exception,
        force_retryable: bool | None = None,
    ) -> None:
        disp = self._classify_failure(exc)
        retryable = disp.retryable if force_retryable is None else force_retryable

        logger.error(
            "%s provisioning failed for server %s (%s) — %s: %s",
            self.provider_name,
            sid,
            disp.classification.value,
            type(exc).__name__,
            exc,
        )

        if not disp.preserve_directory and server_dir:
            try:
                self._fs.delete_dir(server_dir)
            except Exception as cleanup_exc:
                logger.exception(
                    "Failed to clean up server directory %s after fatal provisioning "
                    "error (%s: %s)",
                    server_dir,
                    type(cleanup_exc).__name__,
                    cleanup_exc,
                )

        try:
            server = await _load_server(sid)
            if server is None:
                logger.info("Server %s was deleted; skipping fail_provisioning save", sid)
                return
        except Exception:
            logger.info("Server %s was deleted; skipping fail_provisioning save", sid)
            return

        server.fail_provisioning(
            error=str(exc),
            retryable=retryable,
            fatal=(disp.classification == FailureClass.FATAL),
        )
        try:
            await _save_server(server, self._event_bus)
        except Exception as state_exc:
            logger.exception(
                "Failed to persist failed provisioning state for server %s (%s: %s)",
                sid,
                type(state_exc).__name__,
                state_exc,
            )


async def _load_server(server_id: ServerId) -> Server:
    async with database.session_factory() as session:
        repo = SQLServerRepository(session)
        return await repo.get(server_id)


async def _save_server(server: Server, event_bus: EventBus) -> None:
    async with UnitOfWork(event_bus) as uow:
        repo = SQLServerRepository(uow.session)
        await repo.save(server)
        for event in server.collect_events():
            uow.add_event(event)
        await uow.commit()
