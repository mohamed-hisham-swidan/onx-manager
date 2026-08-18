import asyncio
import hashlib
import logging
import os
import re
import shutil
import tarfile
import tempfile
import time
from pathlib import Path

from app.core.saga import SagaOrchestrator, SagaStep
from app.modules.backup.domain.aggregate import BackupStatus, BackupType
from app.modules.backup.domain.repository import BackupRepository
from app.modules.backup.infrastructure.repository import SQLBackupRepository
from app.modules.server.infrastructure.providers.base import ServerHandle
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import BackupJobId, ServerId
from app.modules.storage.base import StorageBackend
from app.modules.storage.encryption import BackupEncryption
from app.core.persistence.unit_of_work import UnitOfWork

logger = logging.getLogger(__name__)

CONFIG_FILES: tuple[str, ...] = (
    "server.properties",
    "eula.txt",
    "whitelist.json",
    "ops.json",
    "banned-players.json",
    "banned-ips.json",
)

# Suffixes appended to the deployment's primary_world to form each dimension
# folder name. The base (no suffix) world folder is always required; nether and
# the_end are archived only when present on disk.
DIMENSION_SUFFIXES: tuple[str, ...] = ("", "_nether", "_the_end")

# Which dimension suffixes each backup type archives as whole folders. The base
# world (suffix "") is required for every dimension type; nether and the_end are
# archived only when present on disk. plugins/config types archive no dimension.
_BACKUP_TYPE_DIMS: dict[BackupType, tuple[str, ...]] = {
    BackupType.FULL: DIMENSION_SUFFIXES,
    BackupType.WORLDS: DIMENSION_SUFFIXES,
    BackupType.WORLD: ("",),
    BackupType.NETHER: ("_nether",),
    BackupType.END: ("_the_end",),
    BackupType.PLUGINS: (),
    BackupType.CONFIG: (),
}

# Timeout for a save-all on a running server to be confirmed via console
# output. A normal world save completes in a few seconds even on a loaded
# world; 30s is an order of magnitude beyond that but still well inside the
# backup saga's 600s budget, so a genuinely stalled save fails fast without
# aborting a legitimately slow one.
SAVE_ALL_CONFIRMATION_TIMEOUT_S = 30.0
SAVE_ALL_POLL_INTERVAL_S = 0.5

# Minecraft's save-all completion line. No sample log output exists in this
# repo, so both the vanilla wording ("Saved the game") and the
# paper/purpur/spigot wording ("Saved the world") are matched,
# case-insensitively.
_SAVE_CONFIRMED_RE = re.compile(r"saved the (game|world)", re.IGNORECASE)


_CANCELLED_BACKUPS: set[str] = set()


class BackupCancelledError(Exception):
    pass


def cancel_backup(backup_id: str) -> None:
    _CANCELLED_BACKUPS.add(str(backup_id))


def is_backup_cancelled(backup_id: str) -> bool:
    return str(backup_id) in _CANCELLED_BACKUPS


def clear_cancelled_backup(backup_id: str) -> None:
    _CANCELLED_BACKUPS.discard(str(backup_id))


def artifact_path(backup_id: BackupJobId) -> str:
    return f"{backup_id}.tar.gz.enc"


class BackupSaga:
    def __init__(self, saga_orchestrator: SagaOrchestrator) -> None:
        self._saga = saga_orchestrator
        self._result_size: int = 0
        self._result_checksum: str = ""
        self._result_storage_path: str = ""
        self._temp_dir: str | None = None
        self._tar_path: str | None = None
        self._enc_path: str | None = None

    async def execute(
        self,
        backup_id: BackupJobId,
        server_id: ServerId,
        storage: StorageBackend,
        encryption: BackupEncryption | None = None,
        backup_type: BackupType = BackupType.FULL,
    ) -> None:
        steps = [
            SagaStep(
                name="save_world",
                forward=self._save_world(backup_id, server_id),
                compensate=None,
            ),
            SagaStep(
                name="compress_backup",
                forward=self._compress(backup_id, server_id, backup_type),
                compensate=self._cleanup_compressed(),
            ),
            SagaStep(
                name="encrypt_backup",
                forward=self._encrypt(backup_id, encryption),
                compensate=self._cleanup_encrypted(),
            ),
            SagaStep(
                name="upload_backup",
                forward=self._upload(backup_id, storage, encryption),
                compensate=self._remove_uploaded(backup_id, storage),
            ),
            SagaStep(
                name="verify_backup",
                forward=self._verify(backup_id, storage, encryption),
                compensate=self._mark_failed(backup_id),
            ),
        ]

        try:
            instance = await self._saga.create_saga("backup", steps, timeout_seconds=600.0)
            result = await self._saga.execute(instance.saga_id)

            async with UnitOfWork() as uow:
                repo: BackupRepository = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                if result.status.value == "completed":
                    job.mark_completed(
                        size_bytes=self._result_size,
                        checksum=self._result_checksum,
                        storage_path=self._result_storage_path,
                    )
                elif is_backup_cancelled(str(backup_id)) or (result.error and "cancelled" in result.error.lower()) or (result.error and "timeout" in result.error.lower()):
                    job.mark_failed_timeout(result.error or "Backup cancelled due to timeout")
                else:
                    job.mark_failed(result.error or "Backup saga failed")
                await repo.save_job(job)
                await uow.commit()
        finally:
            clear_cancelled_backup(str(backup_id))

    def _save_world(self, backup_id: BackupJobId, server_id: ServerId):
        async def fn() -> None:
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            if not await self._server_is_running(server_id):
                logger.info("World save not required — server %s is not running (backup %s)", server_id, backup_id)
                return

            server = await self._load_server(server_id)
            if not server.runtime or not server.runtime.external_id:
                raise RuntimeError(
                    f"Server {server_id} is running but has no runtime handle — "
                    f"cannot send save-all for backup {backup_id}",
                )

            handle = ServerHandle(
                provider=server.runtime.provider,
                server_id=str(server_id),
                external_id=server.runtime.external_id,
            )
            from app.modules.server.infrastructure.providers import provider_factory

            provider = provider_factory.get(server.runtime.provider)
            await provider.execute_command(handle, "save-all")
            await self._wait_for_save_confirmed(backup_id, server_id, provider, handle)
            logger.info(
                "Save-all confirmed for server %s (backup %s) — proceeding with backup",
                server_id, backup_id,
            )

        return fn

    async def _wait_for_save_confirmed(
        self,
        backup_id: BackupJobId,
        server_id: ServerId,
        provider,
        handle: ServerHandle,
    ) -> None:
        deadline = time.monotonic() + SAVE_ALL_CONFIRMATION_TIMEOUT_S
        while True:
            lines = await provider.console(handle, tail=200)
            for line in lines:
                if _SAVE_CONFIRMED_RE.search(line):
                    return
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"save-all confirmation not observed within "
                    f"{SAVE_ALL_CONFIRMATION_TIMEOUT_S:.0f}s for server {server_id}, "
                    f"backup {backup_id}",
                )
            await asyncio.sleep(SAVE_ALL_POLL_INTERVAL_S)

    def _compress(
        self,
        backup_id: BackupJobId,
        server_id: ServerId,
        backup_type: BackupType = BackupType.FULL,
    ):
        async def fn() -> None:
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            server_dir, primary_world = await self._resolve_server_dir(server_id)
            self._temp_dir = tempfile.mkdtemp(prefix=f"mcs-backup-{str(backup_id)[:8]}-")
            self._tar_path = os.path.join(self._temp_dir, f"{backup_id}.tar.gz")
            self._write_tar(self._tar_path, server_dir, primary_world, backup_type, backup_id=str(backup_id))
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            logger.info(
                "Backup compressed: %s (%d bytes)",
                backup_id, os.path.getsize(self._tar_path),
            )

        return fn

    def _encrypt(self, backup_id: BackupJobId, encryption: BackupEncryption | None):
        async def fn() -> None:
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            if encryption is None:
                raise RuntimeError(f"Encryption is required to complete backup {backup_id}")
            if not self._tar_path or not os.path.exists(self._tar_path):
                raise RuntimeError(f"Compressed artifact missing for backup {backup_id}")
            self._enc_path = f"{self._tar_path}.enc"
            with open(self._tar_path, "rb") as f:
                plaintext = f.read()
            encrypted = encryption.encrypt(plaintext)
            with open(self._enc_path, "wb") as f:
                f.write(encrypted)
            os.remove(self._tar_path)
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            logger.info(
                "Backup encrypted: %s (%d bytes plaintext -> %d bytes ciphertext)",
                backup_id, len(plaintext), len(encrypted),
            )

        return fn

    def _upload(
        self,
        backup_id: BackupJobId,
        storage: StorageBackend,
        encryption: BackupEncryption | None,
    ):
        async def fn() -> None:
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            if not self._enc_path or not os.path.exists(self._enc_path):
                raise RuntimeError(f"Encrypted artifact missing for backup {backup_id}")
            with open(self._enc_path, "rb") as f:
                encrypted = f.read()
            path = artifact_path(backup_id)
            await storage.write(path, encrypted)
            self._result_size = len(encrypted)
            self._result_checksum = encryption.checksum(encrypted) if encryption else hashlib.sha256(encrypted).hexdigest()
            self._result_storage_path = path
            logger.info(
                "Backup uploaded: %s -> %s (%d bytes, sha256=%s)",
                backup_id, path, self._result_size, self._result_checksum[:16],
            )
            self._cleanup_temp_dir()

        return fn

    def _verify(
        self,
        backup_id: BackupJobId,
        storage: StorageBackend,
        encryption: BackupEncryption | None,
    ):
        async def fn() -> None:
            if is_backup_cancelled(str(backup_id)):
                raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
            path = artifact_path(backup_id)
            data = await storage.read(path)
            actual_size = len(data)
            actual_checksum = encryption.checksum(data) if encryption else hashlib.sha256(data).hexdigest()
            if actual_size != self._result_size:
                raise RuntimeError(
                    f"Backup {backup_id} size mismatch: expected {self._result_size}, got {actual_size}",
                )
            if actual_checksum != self._result_checksum:
                raise RuntimeError(
                    f"Backup {backup_id} checksum mismatch: expected {self._result_checksum}, got {actual_checksum}",
                )
            logger.info("Backup verified: %s (%d bytes, sha256=%s)", backup_id, actual_size, actual_checksum[:16])

        return fn

    def _cleanup_compressed(self):
        async def fn() -> None:
            if self._tar_path and os.path.exists(self._tar_path):
                os.remove(self._tar_path)
                logger.info("Cleaned up compressed data for %s", self._tar_path)
            self._cleanup_temp_dir()

        return fn

    def _cleanup_encrypted(self):
        async def fn() -> None:
            if self._enc_path and os.path.exists(self._enc_path):
                os.remove(self._enc_path)
                logger.info("Cleaned up encrypted data for %s", self._enc_path)
            self._cleanup_temp_dir()

        return fn

    def _remove_uploaded(self, backup_id: BackupJobId, storage: StorageBackend):
        async def fn() -> None:
            path = artifact_path(backup_id)
            try:
                await storage.delete(path)
            except Exception as exc:
                logger.warning("Failed to remove uploaded backup %s: %s", path, exc)
            else:
                logger.info("Removed uploaded backup: %s", path)
            self._cleanup_temp_dir()

        return fn

    def _mark_failed(self, backup_id: BackupJobId):
        async def fn() -> None:
            async with UnitOfWork() as uow:
                repo: BackupRepository = SQLBackupRepository(uow.session)
                job = await repo.get_job(backup_id)
                job.mark_failed("Verification failed in backup saga")
                await repo.save_job(job)
                await uow.commit()

        return fn

    def _cleanup_temp_dir(self) -> None:
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def _write_tar(
        self,
        tar_path: str,
        server_dir: str,
        primary_world: str = "world",
        backup_type: BackupType = BackupType.FULL,
        backup_id: str = "",
    ) -> None:
        dim_names: dict[str, str] = {s: f"{primary_world}{s}" for s in DIMENSION_SUFFIXES}
        dim_suffixes = _BACKUP_TYPE_DIMS[backup_type]
        include_plugins = backup_type in (BackupType.FULL, BackupType.PLUGINS)
        include_config = backup_type in (BackupType.FULL, BackupType.CONFIG)

        required_suffix = {
            BackupType.WORLDS: "",
            BackupType.WORLD: "",
            BackupType.NETHER: "_nether",
            BackupType.END: "_the_end",
        }.get(backup_type)
        if required_suffix is not None:
            required_dir = Path(server_dir) / dim_names[required_suffix]
            if not required_dir.is_dir():
                raise FileNotFoundError(f"World directory not found: {required_dir}")

        with tarfile.open(tar_path, "w:gz") as tar:
            for suffix in dim_suffixes:
                if backup_id and is_backup_cancelled(backup_id):
                    raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
                dim_name = dim_names[suffix]
                candidate = Path(server_dir) / dim_name
                if candidate.is_dir():
                    tar.add(str(candidate), arcname=dim_name)

            # playerdata/ from dimensions NOT archived whole above is pulled into a
            # separate namespace so restore never mistakes a partial dimension for a
            # whole one. Only applies to dimension-bearing types.
            if backup_type in (
                BackupType.FULL,
                BackupType.WORLDS,
                BackupType.WORLD,
                BackupType.NETHER,
                BackupType.END,
            ):
                for suffix, dim_name in dim_names.items():
                    if backup_id and is_backup_cancelled(backup_id):
                        raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
                    if suffix in dim_suffixes:
                        continue
                    playerdata_dir = Path(server_dir) / dim_name / "playerdata"
                    if playerdata_dir.is_dir():
                        arcname = f"mcs_playerdata/{dim_name}/playerdata"
                        tar.add(str(playerdata_dir), arcname=arcname)

            if include_plugins:
                if backup_id and is_backup_cancelled(backup_id):
                    raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
                plugins_dir = Path(server_dir) / "plugins"
                if plugins_dir.is_dir():
                    tar.add(str(plugins_dir), arcname="plugins")

            if include_config:
                for name in CONFIG_FILES:
                    if backup_id and is_backup_cancelled(backup_id):
                        raise BackupCancelledError(f"Backup {backup_id} cancelled due to timeout")
                    candidate = Path(server_dir) / name
                    if candidate.is_file():
                        tar.add(str(candidate), arcname=name)

    async def _resolve_server_dir(self, server_id: ServerId) -> tuple[str, str]:
        async with UnitOfWork() as uow:
            repo = SQLServerRepository(uow.session)
            server = await repo.get(server_id)
            if server.deployment is None or not server.deployment.root_path:
                raise ValueError(f"Server {server_id} has no deployment root path — cannot back up")
            primary_world = server.deployment.primary_world or "world"
            return server.deployment.server_directory(), primary_world

    async def _server_is_running(self, server_id: ServerId) -> bool:
        async with UnitOfWork() as uow:
            repo = SQLServerRepository(uow.session)
            server = await repo.get(server_id)
            return server.status.value == "running"

    async def _load_server(self, server_id: ServerId):
        async with UnitOfWork() as uow:
            repo = SQLServerRepository(uow.session)
            return await repo.get(server_id)
