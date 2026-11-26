"""Simple server baseline adoption service.

P2-1 Core Substrate — B4d
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.core.allowlist import open_safe_path_fd
from app.core.exceptions import (
    CasUnsupportedPlatformError,
    ValidationError,
)
from app.core.host_state import ensure_host_state_layout, validate_server_segment
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.server.domain.aggregate import ServerId, ServerMode
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.versioning.application.loader_ref import derive_loader_ref
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.domain.lockfile import (
    EnvServer,
    LockfileFile,
    LockfileV21,
    Origin,
)
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.server_tree_scanner import scan_server_tree


def _platform_is_posix() -> bool:
    """Return True if running on POSIX."""
    return os.name == "posix"


@dataclass(frozen=True)
class BaselineAdoptionResult:
    """Result of baseline lockfile adoption for a Simple server.

    Note on warnings: reserved for future adoption warnings; unknown-type loader
    warnings use Python warnings.warn in this batch.
    """

    status: str  # created | already_present | reconciled | skipped
    reason: str = ""
    lockfile_path: str = ""
    files_count: int = 0
    cas_ingested: int = 0
    quarantined: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def stage_and_ingest(
    server_root: Path,
    relpath: str,
    server_meta_dir: Path,
    cas: ArtifactCas,
) -> LockfileFile:
    fd = open_safe_path_fd(
        str(server_root),
        relpath,
        flags=os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    staged_path: Path | None = None
    try:
        st_before = os.fstat(fd)
        if not stat.S_ISREG(st_before.st_mode):
            raise ValidationError(f"Source file {relpath} is not a regular file")
        fp_before = (
            st_before.st_dev,
            st_before.st_ino,
            st_before.st_size,
            st_before.st_mtime_ns,
        )

        staged_name = f".onx-adopt.{uuid.uuid4().hex}.tmp"
        staged_path = server_meta_dir / staged_name

        flags = (
            os.O_CREAT
            | getattr(os, "O_EXCL", 0)
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0)
        )
        staged_fd = os.open(str(staged_path), flags, 0o600)
        try:
            if _platform_is_posix():
                os.fchmod(staged_fd, 0o600)
            hasher = hashlib.sha256()
            total_written = 0
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                hasher.update(chunk)
                offset = 0
                while offset < len(chunk):
                    n = os.write(staged_fd, chunk[offset:])
                    if n <= 0:
                        raise OSError("write returned 0 bytes")
                    offset += n
                total_written += len(chunk)
            if _platform_is_posix():
                os.fsync(staged_fd)
        finally:
            os.close(staged_fd)

        st_after = os.fstat(fd)
        fp_after = (
            st_after.st_dev,
            st_after.st_ino,
            st_after.st_size,
            st_after.st_mtime_ns,
        )
        if fp_before != fp_after or total_written != st_after.st_size:
            raise ValidationError(f"Source file {relpath} was modified concurrently")

        computed_sha = hasher.hexdigest()
        digest = cas.put_file(staged_path)
        if digest != computed_sha:
            raise ValidationError(
                f"Digest mismatch for {relpath}: CAS computed {digest}, expected {computed_sha}"
            )

        return LockfileFile(
            path=relpath,
            sha256=digest,
            size=st_after.st_size,
            optional=False,
            env_server=EnvServer.REQUIRED,
            origin=Origin.USER,
        )
    finally:
        if staged_path is not None and os.path.lexists(staged_path):
            with contextlib.suppress(Exception):
                os.unlink(staged_path)
        os.close(fd)


def _sha256_safe_file(server_root: Path, relpath: str) -> str:
    """Compute SHA-256 of ``relpath`` safely using O_NOFOLLOW."""
    fd = open_safe_path_fd(
        str(server_root),
        relpath,
        flags=os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValidationError(f"Source file {relpath} is not a regular file")
        hasher = hashlib.sha256()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            hasher.update(chunk)
        return hasher.hexdigest()
    finally:
        os.close(fd)


async def ensure_simple_baseline_lockfile(
    server_id: str,
    *,
    reconcile_addons: bool = False,
) -> BaselineAdoptionResult:
    """Ensure an authoritative baseline lockfile exists (and optionally reconcile live addons)."""
    # Step 1: validate segment
    validate_server_segment(server_id)

    # Step 2: query repository via UnitOfWork
    async with UnitOfWork() as uow:
        server = await SQLServerRepository(uow.session).get(ServerId(server_id))

    # Step 3: check mode
    if server.mode != ServerMode.SIMPLE:
        return BaselineAdoptionResult(status="skipped", reason="not_simple")

    # Step 4: check deployment and compute server_root
    if not server.deployment or not server.deployment.root_path:
        return BaselineAdoptionResult(status="skipped", reason="no_deployment")

    server_root = Path(os.path.abspath(server.deployment.server_directory()))

    # Step 5: ensure host state layout and containment check
    layout = ensure_host_state_layout()
    layout_root_str = os.path.abspath(str(layout.root))
    server_root_str = os.path.abspath(str(server_root))

    if layout_root_str == server_root_str:
        raise ValidationError("Server root and host-state root must not coincide")

    try:
        if os.path.commonpath([layout_root_str, server_root_str]) == layout_root_str:
            raise ValidationError(
                f"Server root ({server_root_str}) cannot be inside host-state directory "
                f"({layout_root_str})"
            )
        if os.path.commonpath([layout_root_str, server_root_str]) == server_root_str:
            raise ValidationError(
                f"Host-state directory ({layout_root_str}) cannot be inside server root "
                f"({server_root_str})"
            )
    except ValueError:
        pass

    service = LockfileService(layout)
    cas = ArtifactCas(layout.cas)

    # Step 6: check if lockfile already exists
    existing_lockfile: LockfileV21 | None = None
    if service.exists(server_id):
        existing_lockfile = service.read(server_id)
        if existing_lockfile is not None and not reconcile_addons:
            return BaselineAdoptionResult(
                status="already_present",
                reason="lockfile_already_exists",
                lockfile_path=str(service.path_for(server_id)),
                files_count=len(existing_lockfile.files),
            )

    # Step 7: scan server tree
    report = scan_server_tree(server_root)
    if report.truncated:
        raise ValidationError(
            "Server tree scan was truncated due to limit thresholds; cannot adopt baseline"
        )

    # Step 8: check POSIX platform
    if not _platform_is_posix():
        raise CasUnsupportedPlatformError(
            "Artifact CAS is only supported on POSIX in this slice"
        )

    # Step 9: ingest A-JAR and A-CAS files in sorted path order
    server_meta_dir = layout.server_meta_dir(server_id)
    server_meta_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if _platform_is_posix():
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
        try:
            dir_fd = os.open(str(server_meta_dir), flags)
            try:
                os.fchmod(dir_fd, 0o700)
            finally:
                os.close(dir_fd)
        except OSError:
            pass

    target_files = [f for f in report.files if f.classification in ("A-JAR", "A-CAS")]
    existing_by_path = (
        {f.path: f for f in existing_lockfile.files}
        if existing_lockfile is not None
        else {}
    )
    ingested_files: list[LockfileFile] = []
    cas_ingested = 0

    for scanned_file in target_files:
        prev_entry = existing_by_path.get(scanned_file.path)
        if prev_entry is not None and cas.has(prev_entry.sha256):
            disk_sha = _sha256_safe_file(server_root, scanned_file.path)
            if disk_sha == prev_entry.sha256:
                ingested_files.append(prev_entry)
                continue
        lf_file = stage_and_ingest(server_root, scanned_file.path, server_meta_dir, cas)
        ingested_files.append(lf_file)
        cas_ingested += 1

    # Step 10: construct LockfileV21
    mc_version = (
        existing_lockfile.mc
        if existing_lockfile is not None
        else (str(server.minecraft_version) if server.minecraft_version else "1.0")
    )
    loader = (
        existing_lockfile.loader
        if existing_lockfile is not None
        else derive_loader_ref(server)
    )
    sorted_files = tuple(sorted(ingested_files, key=lambda f: f.path))
    if (
        existing_lockfile is not None
        and sorted_files == existing_lockfile.files
        and mc_version == existing_lockfile.mc
        and loader == existing_lockfile.loader
    ):
        return BaselineAdoptionResult(
            status="already_present",
            reason="lockfile_already_exists",
            lockfile_path=str(service.path_for(server_id)),
            files_count=len(existing_lockfile.files),
            quarantined=report.quarantined,
            warnings=(),
        )

    lockfile = LockfileV21(
        format=2,
        mc=mc_version,
        loader=loader,
        base_overrides=existing_lockfile.base_overrides if existing_lockfile is not None else {},
        files=sorted_files,
        lec=existing_lockfile.lec if existing_lockfile is not None else None,
        modpack=existing_lockfile.modpack if existing_lockfile is not None else None,
    )

    # Step 11: atomic write
    written_path = service.write(server_id, lockfile)

    # Step 12: return result
    return BaselineAdoptionResult(
        status="reconciled" if existing_lockfile is not None else "created",
        lockfile_path=str(written_path),
        files_count=len(lockfile.files),
        cas_ingested=cas_ingested,
        quarantined=report.quarantined,
        warnings=(),
    )
