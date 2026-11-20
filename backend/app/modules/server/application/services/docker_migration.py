"""Idempotent Local -> Docker server migration (P6-1 / OD-v8.6-1).

Phase P6 consolidates every server onto ``DockerProvider``. Legacy rows created
by the former local providers keep their data directory, world files, configs
and lockfiles; only the runtime provider / location metadata and the
``.onx-manager/server.json`` identity document are rewritten to ``docker``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.identity import IDENTITY
from app.modules.server.application.services.identity_writer import write_server_identity
from app.modules.server.domain.value_objects import LocationType
from app.modules.server.infrastructure.fs import FileSystem, local_fs
from app.modules.server.infrastructure.models import ServerModel

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.services.docker_migration")

LEGACY_LOCAL_PROVIDERS: frozenset[str] = frozenset(
    {"", "local", "local_linux", "local_windows"}
)

_CONTAINER_ID_PREFIXES = ("onx-", "mcs-")


@dataclass(frozen=True)
class LocalToDockerMigrationRecord:
    server_id: str
    name: str
    previous_provider: str
    previous_location_type: str
    identity_updated: bool
    cleared_stale_external_id: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalToDockerMigrationReport:
    migrated: tuple[LocalToDockerMigrationRecord, ...] = ()
    skipped_already_docker: int = 0
    errors: tuple[str, ...] = ()

    @property
    def migrated_count(self) -> int:
        return len(self.migrated)


def _read_existing_created_at(
    root_path: str, fs: FileSystem
) -> str | None:
    identity_path = (
        Path(root_path) / IDENTITY.identity_dir_new / IDENTITY.identity_file
    )
    if not fs.exists(str(identity_path)):
        return None
    try:
        doc = json.loads(fs.read_text(str(identity_path)))
    except (OSError, ValueError):
        return None
    created_at = doc.get("created_at") if isinstance(doc, dict) else None
    return created_at if isinstance(created_at, str) else None


def _migrate_model(
    model: ServerModel,
    *,
    fs: FileSystem,
) -> LocalToDockerMigrationRecord:
    """Mutate one ORM row + identity document; caller owns the commit."""
    previous_provider = str(model.provider or "")
    previous_location_type = str(model.location_type or "")
    warnings: list[str] = []

    root_path = str(model.root_path or "")
    identity_updated = False
    if root_path:
        if fs.is_dir(root_path):
            created_at = _read_existing_created_at(root_path, fs)
            write_server_identity(
                dir_path=root_path,
                uid=str(model.id),
                provider="docker",
                fs=fs,
                created_at=created_at,
            )
            identity_updated = True
        else:
            warnings.append(f"Server directory not found: {root_path}")

    cleared_stale_external_id = False
    external_id = str(model.external_id or "")
    if external_id and not external_id.startswith(_CONTAINER_ID_PREFIXES):
        cleared_stale_external_id = True

    model.provider = "docker"  # type: ignore[reportAttributeAccessIssue]
    model.location_type = LocationType.DOCKER.value  # type: ignore[reportAttributeAccessIssue]
    if model.deployment_pid is not None and previous_provider in LEGACY_LOCAL_PROVIDERS:
        model.deployment_pid = None  # type: ignore[reportAttributeAccessIssue]
    if cleared_stale_external_id:
        model.external_id = None  # type: ignore[reportAttributeAccessIssue]

    return LocalToDockerMigrationRecord(
        server_id=str(model.id),
        name=str(model.name),
        previous_provider=previous_provider,
        previous_location_type=previous_location_type,
        identity_updated=identity_updated,
        cleared_stale_external_id=cleared_stale_external_id,
        warnings=tuple(warnings),
    )


async def migrate_server_to_docker(
    session: AsyncSession,
    server_id: str,
    *,
    fs: FileSystem | None = None,
) -> LocalToDockerMigrationRecord | None:
    """Migrate a single server row to Docker. Returns ``None`` when already done."""
    model = await session.get(ServerModel, server_id)
    if model is None:
        raise NotFoundError(f"Server '{server_id}' not found")

    if (
        str(model.provider or "") == "docker"
        and str(model.location_type or "") == LocationType.DOCKER.value
    ):
        return None

    record = _migrate_model(model, fs=fs or local_fs)
    await session.commit()
    logger.info(
        'Migrated server "%s" (%s) from provider=%r/%s to docker',
        record.name,
        record.server_id,
        record.previous_provider,
        record.previous_location_type,
    )
    return record


async def migrate_all_local_servers_to_docker(
    session: AsyncSession,
    *,
    fs: FileSystem | None = None,
) -> LocalToDockerMigrationReport:
    """Migrate every legacy local row, isolating per-row failures."""
    fs_impl = fs or local_fs

    skipped_stmt = (
        select(func.count())
        .select_from(ServerModel)
        .where(
            ServerModel.provider == "docker",
            ServerModel.location_type == LocationType.DOCKER.value,
        )
    )
    skipped_already_docker = int((await session.execute(skipped_stmt)).scalar_one())

    legacy_stmt = select(ServerModel).where(
        or_(
            ServerModel.provider.in_(sorted(LEGACY_LOCAL_PROVIDERS)),
            ServerModel.location_type == LocationType.LOCAL.value,
        )
    )
    rows = (await session.execute(legacy_stmt)).scalars().all()

    migrated: list[LocalToDockerMigrationRecord] = []
    errors: list[str] = []
    for model in rows:
        try:
            migrated.append(_migrate_model(model, fs=fs_impl))
        except Exception as exc:  # noqa: BLE001 - startup must survive one bad row
            errors.append(f"{model.id}: {exc}")
            logger.warning(
                "Local-to-Docker migration failed for server %s: %s",
                model.id,
                exc,
            )

    await session.commit()

    report = LocalToDockerMigrationReport(
        migrated=tuple(migrated),
        skipped_already_docker=skipped_already_docker,
        errors=tuple(errors),
    )
    if report.migrated_count:
        logger.info(
            "Migrated %d server(s) from local providers to docker",
            report.migrated_count,
        )
    return report
