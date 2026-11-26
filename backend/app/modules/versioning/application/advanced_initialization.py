"""Advanced-server Git bootstrap: host lockfile, CAS ingest, eager ``main``.

P2-2 Repo / branches. Used by the Advanced create path after the panel has
written the initial server files. The authoritative lockfile lives under host
state; the server tree copy of ``onx-jars.lock.json`` is Class E and never
enters the repository.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import (
    CasUnsupportedPlatformError,
    GitRepositoryStateError,
    ValidationError,
)
from app.core.host_state import (
    HostStateLayout,
    ensure_host_state_layout,
    validate_server_segment,
)
from app.modules.server.domain.aggregate import Server, ServerMode
from app.modules.versioning.application.baseline_adoption import stage_and_ingest
from app.modules.versioning.application.loader_ref import derive_loader_ref
from app.modules.versioning.application.lockfile_service import LockfileService
from app.modules.versioning.domain.lockfile import LockfileFile, LockfileV21
from app.modules.versioning.infrastructure.artifact_cas import ArtifactCas
from app.modules.versioning.infrastructure.git_repository import (
    GitRepositoryService,
    RepositoryInitResult,
    validate_server_root,
)
from app.modules.versioning.infrastructure.server_tree_scanner import scan_server_tree


@dataclass(frozen=True)
class AdvancedInitializationResult:
    """Outcome of the Advanced Git bootstrap for one server."""

    server_id: str
    repository: RepositoryInitResult
    lockfile_path: Path
    files_count: int
    cas_ingested: int
    quarantined: tuple[str, ...]


def _validate_containment(server_root: Path, layout: HostStateLayout) -> None:
    layout_root = os.path.abspath(str(layout.root))
    root = os.path.abspath(str(server_root))
    if layout_root == root:
        raise ValidationError("Server root and host-state root must not coincide")
    try:
        if os.path.commonpath([layout_root, root]) == layout_root:
            raise ValidationError(
                f"Server root ({root}) cannot be inside host-state directory ({layout_root})"
            )
        if os.path.commonpath([layout_root, root]) == root:
            raise ValidationError(
                f"Host-state directory ({layout_root}) cannot be inside server root ({root})"
            )
    except ValueError:
        # Different drives on Windows: no containment possible.
        pass


def _ensure_server_meta_dir(layout: HostStateLayout, server_id: str) -> Path:
    server_meta_dir = layout.server_meta_dir(server_id)
    server_meta_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_DIRECTORY", 0)
        try:
            dir_fd = os.open(str(server_meta_dir), flags)
            try:
                os.fchmod(dir_fd, 0o700)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    return server_meta_dir


def initialize_advanced_server(server: Server) -> AdvancedInitializationResult:
    """Create the host lockfile, CAS entries, and the native Git repository.

    The operation is idempotent: when the repository already exists the
    existing authoritative lockfile is reused and never rewritten.
    """
    if server.mode != ServerMode.ADVANCED:
        raise ValidationError("Advanced initialization requires an Advanced server")
    if os.name != "posix":
        raise CasUnsupportedPlatformError(
            "Advanced mode is only supported on POSIX hosts in this release"
        )
    if not server.deployment or not server.deployment.root_path:
        raise ValidationError("Advanced server has no deployment root")

    server_id = str(server.id)
    validate_server_segment(server_id)
    server_root = validate_server_root(os.path.abspath(server.deployment.server_directory()))
    layout = ensure_host_state_layout()
    _validate_containment(server_root, layout)

    lockfile_service = LockfileService(layout)
    repo_git = layout.repo_dir(server_id) / "repo.git"

    if repo_git.exists() or repo_git.is_symlink():
        existing = lockfile_service.read(server_id)
        if existing is None:
            raise GitRepositoryStateError(
                "Existing Git repository has no authoritative host lockfile",
                details={"server_id": server_id},
            )
        repository = GitRepositoryService(layout).initialize(server_id, server_root, existing)
        return AdvancedInitializationResult(
            server_id=server_id,
            repository=repository,
            lockfile_path=lockfile_service.path_for(server_id),
            files_count=len(existing.files),
            cas_ingested=0,
            quarantined=(),
        )

    report = scan_server_tree(server_root)
    if report.truncated:
        raise ValidationError(
            "Server tree scan was truncated; cannot create a complete initial commit"
        )

    server_meta_dir = _ensure_server_meta_dir(layout, server_id)
    cas = ArtifactCas(layout.cas)
    ingested: list[LockfileFile] = []
    for scanned in report.files:
        if scanned.classification not in ("A-JAR", "A-CAS"):
            continue
        ingested.append(stage_and_ingest(server_root, scanned.path, server_meta_dir, cas))

    mc_version = str(server.minecraft_version) if server.minecraft_version else "1.0"
    lockfile = LockfileV21(
        format=2,
        mc=mc_version,
        loader=derive_loader_ref(server),
        base_overrides={},
        files=tuple(sorted(ingested, key=lambda item: item.path)),
        lec=None,
        modpack=None,
    )
    lockfile_path = lockfile_service.write(server_id, lockfile)

    repository = GitRepositoryService(layout).initialize(server_id, server_root, lockfile)
    return AdvancedInitializationResult(
        server_id=server_id,
        repository=repository,
        lockfile_path=lockfile_path,
        files_count=len(lockfile.files),
        cas_ingested=len(ingested),
        quarantined=report.quarantined,
    )


__all__ = ["AdvancedInitializationResult", "initialize_advanced_server"]
