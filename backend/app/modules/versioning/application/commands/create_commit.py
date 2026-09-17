from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import ConflictError, NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.domain.entities import (
    ServerBranch,
    ServerCommit,
    ServerWorldSnapshot,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.infrastructure.btrfs_zfs_driver import BtrfsZfsSnapshotDriver
from app.modules.versioning.infrastructure.manifest_builder import ManifestBuilder
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe


class CreateCommitCommand(Command):
    server_id: str
    message: str
    branch_name: str = "main"
    author_id: str | None = None


class CreateCommitHandler(CommandHandler[CreateCommitCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: CreateCommitCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

        if self._server_repo is not None and self._versioning_repo is not None:
            res = await self._execute(command, self._server_repo, self._versioning_repo, events)
        else:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with database.session_factory() as session:
                        server_repo = self._server_repo or SQLServerRepository(session)
                        versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                        events.clear()
                        res = await self._execute(command, server_repo, versioning_repo, events)
                        await session.commit()
                    break
                except Exception as exc:
                    is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                    if is_lock and attempt < max_retries - 1:
                        await asyncio.sleep(0.05 * (2**attempt))
                        continue
                    raise

        if self._event_bus is not None and res.success:
            for ev in events:
                await self._event_bus.publish(ev)

        return res

    async def _execute(
        self,
        command: CreateCommitCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # 1. Fetch server
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        server_dir = server.deployment.server_dir
        if not os.path.exists(server_dir):
            raise NotFoundError(f"Server directory '{server_dir}' not found on disk")

        # 2. Assert storage capability supports reflink
        StorageCapabilityProbe.assert_supports_reflink(server_dir)

        # 3. Resolve or auto-create branch
        from app.modules.versioning.domain.value_objects import BranchStatus

        branch = await versioning_repo.get_branch_by_name(command.server_id, command.branch_name)
        if branch is None:
            branch = ServerBranch(
                id=str(uuid.uuid4()),
                server_id=command.server_id,
                name=command.branch_name,
                status=BranchStatus.CREATED,
            )
            await versioning_repo.save_branch(branch)
        elif branch.status == BranchStatus.ARCHIVED:
            raise ConflictError(f"Cannot commit to archived branch '{branch.name}'")

        # 4. Create COW world snapshot
        snapshot_id = str(uuid.uuid4())
        snapshot_dir = Path(server_dir) / ".onx" / "snapshots" / snapshot_id
        size_bytes = BtrfsZfsSnapshotDriver.create_snapshot(server_dir, snapshot_dir)

        world_snapshot = ServerWorldSnapshot(
            id=snapshot_id,
            server_id=command.server_id,
            storage_path=str(snapshot_dir),
            size_bytes=size_bytes,
        )
        await versioning_repo.save_snapshot(world_snapshot)

        # 5. Build CommitManifest
        manifest = ManifestBuilder.build_manifest(
            server_dir=server_dir,
            server_type=server.server_type,
            minecraft_version=server.minecraft_version,
            java_args=server.java_args.raw
            if hasattr(server.java_args, "raw")
            else str(server.java_args),
        )

        # 6. Save commit
        commit_id = str(uuid.uuid4())
        commit = ServerCommit(
            id=commit_id,
            server_id=command.server_id,
            message=command.message,
            manifest=manifest,
            branch_id=branch.id,
            parent_commit_id=branch.head_commit_id,
            author_id=command.author_id,
            world_snapshot_id=snapshot_id,
        )
        if branch.head_commit_id:
            parent_commit = await versioning_repo.get_commit(branch.head_commit_id)
            commit.validate_parent(parent_commit)
        await versioning_repo.save_commit(commit)

        # 7. Advance branch head and activate
        branch.advance_head(commit_id)
        await versioning_repo.save_branch(branch)

        from app.modules.versioning.domain.events import CommitCreatedEvent

        event = CommitCreatedEvent(
            server_id=command.server_id,
            commit_id=commit_id,
            message=command.message,
            branch_name=branch.name,
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=commit_id,
            details={
                "commit_id": commit_id,
                "server_id": command.server_id,
                "branch_name": branch.name,
                "world_snapshot_id": snapshot_id,
                "message": command.message,
            },
        )
