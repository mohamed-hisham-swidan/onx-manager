from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from sqlalchemy.exc import OperationalError

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus
from app.core.exceptions import (
    BranchProtectedError,
    ConflictError,
    NotFoundError,
    PermissionDenied,
)
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository
from app.modules.server.domain.aggregate import Server
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import (
    GitBranchContext,
    git_branch_context,
)
from app.modules.versioning.domain.entities import (
    BranchProtectionPolicy,
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
    force: bool = False
    force_reason: str | None = None
    caller_permissions: list[str] | None = None


class CreateCommitHandler(CommandHandler[CreateCommitCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
        activity_repo: ActivityRepository | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus
        self._activity_repo = activity_repo

    async def handle(self, command: CreateCommitCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.activity.infrastructure.repository import SQLActivityRepository
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            activity_repo = self._activity_repo or SQLActivityRepository()
            res = await self._execute(
                command, self._server_repo, self._versioning_repo, activity_repo, events
            )
        else:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with database.session_factory() as session:
                        await ensure_versioning_allowed(command.server_id, session=session)
                        server_repo = self._server_repo or SQLServerRepository(session)
                        versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                        activity_repo = self._activity_repo or SQLActivityRepository(session)
                        events.clear()
                        res = await self._execute(
                            command, server_repo, versioning_repo, activity_repo, events
                        )
                        await session.commit()
                    break
                except ConflictError:
                    raise
                except Exception as exc:
                    is_lock = isinstance(exc, OperationalError) and (
                        "locked" in str(exc).lower() or "busy" in str(exc).lower()
                    )
                    if is_lock and attempt < max_retries - 1:
                        await asyncio.sleep(0.05 * (2**attempt))
                        continue
                    raise

        if self._event_bus is not None and res.success:
            for ev in events:
                await self._event_bus.publish(ev)

        return res

    async def _enforce_protected_branch(
        self,
        command: CreateCommitCommand,
        branch: ServerBranch,
        activity_repo: ActivityRepository,
    ) -> None:
        """Enforce protected-branch force policy and audit any bypass."""
        if not branch.is_protected or branch.can_commit_directly():
            return

        if not command.force:
            raise BranchProtectedError(
                f"Direct commits to protected branch '{branch.name}' are forbidden. "
                "Changes must be verified on a working branch and merged."
            )

        policy = branch.protection_policy or BranchProtectionPolicy()
        if not policy.allow_force_bypass:
            raise BranchProtectedError(
                f"Force bypass is disabled by protection policy on branch '{branch.name}'"
            )

        perms = command.caller_permissions or []
        if "admin:full" not in perms and "server:version:branch:bypass_protection" not in perms:
            raise PermissionDenied(
                "Caller lacks 'server:version:branch:bypass_protection' to bypass branch protection"
            )

        audit_log = ServerActivityLog(
            id=str(uuid.uuid4()),
            server_id=command.server_id,
            event_type="versioning.branch_protection_bypassed",
            summary=f"Direct commit to protected branch '{branch.name}' was force-bypassed",
            actor_type="user" if command.author_id else "system",
            actor_id=command.author_id,
            details={
                "branch": branch.name,
                "reason": command.force_reason or "",
            },
        )
        await activity_repo.save(audit_log)

    async def _execute_native_git(
        self,
        command: CreateCommitCommand,
        server: Server,
        context: GitBranchContext,
        versioning_repo: VersioningRepository,
        activity_repo: ActivityRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        """Run the native Git Save & Commit path for an Advanced repository."""
        from app.modules.versioning.domain.events import CommitCreatedEvent
        from app.modules.versioning.domain.value_objects import BranchStatus
        from app.modules.versioning.infrastructure.git_repository import MAIN_BRANCH
        from app.modules.versioning.infrastructure.git_save_commit import (
            GitSaveCommitService,
        )

        if command.branch_name == MAIN_BRANCH:
            raise BranchProtectedError(
                "Direct commits to branch 'main' are forbidden; "
                "commit to a working branch and merge instead"
            )

        branch = await versioning_repo.get_branch_by_name(command.server_id, command.branch_name)
        if branch is None:
            from app.modules.versioning.domain.value_objects import BranchStatus

            branch = ServerBranch(
                id=str(uuid.uuid4()),
                server_id=command.server_id,
                name=command.branch_name,
                status=BranchStatus.CREATED,
            )
            await versioning_repo.save_branch(branch)
        if branch.status == BranchStatus.ARCHIVED:
            raise ConflictError(f"Cannot commit to archived branch '{branch.name}'")
        await self._enforce_protected_branch(command, branch, activity_repo)

        result = GitSaveCommitService(context.layout).save(
            str(server.id),
            context.server_root,
            command.branch_name,
            command.message,
        )

        from app.modules.versioning.domain.value_objects import (
            CommitManifest,
            normalize_server_type_str,
        )

        # D-7: project native Git commit into SQLite so DB-backed queries see it.
        if result.commit_id:
            if await versioning_repo.get_commit(result.commit_id) is None:
                commit = ServerCommit(
                    id=result.commit_id,
                    server_id=command.server_id,
                    branch_id=branch.id,
                    message=command.message,
                    author_id=command.author_id,
                    parent_commit_id=result.parent_commit_id,
                    parent_commit_ids=[result.parent_commit_id] if result.parent_commit_id else [],
                    manifest=CommitManifest(
                        server_type=normalize_server_type_str(server.server_type),
                        minecraft_version=str(server.minecraft_version),
                    ),
                )
                await versioning_repo.save_commit(commit)
            branch.head_commit_id = result.commit_id
            await versioning_repo.save_branch(branch)

        event = CommitCreatedEvent(
            server_id=command.server_id,
            commit_id=result.commit_id,
            message=command.message,
            branch_name=result.branch_name,
        )
        if events is not None:
            events.append(event)
        elif self._event_bus is not None:
            await self._event_bus.publish(event)

        return CommandResult(
            success=True,
            entity_id=result.commit_id,
            details={
                "commit_id": result.commit_id,
                "parent_commit_id": result.parent_commit_id,
                "server_id": command.server_id,
                "branch_name": result.branch_name,
                "message": result.message,
                "files": list(result.files),
                "routed_to_cas": list(result.routed_to_cas),
                "quarantined": list(result.quarantined),
                "snapshot_hash": None,
                "changes_summary": None,
                "warnings": list(result.warnings),
                "noop": False,
                "engine": "native-git",
            },
        )

    async def _execute(
        self,
        command: CreateCommitCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        activity_repo: ActivityRepository,
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # 1. Fetch server
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        git_context = git_branch_context(server)
        if git_context is not None:
            return await self._execute_native_git(
                command, server, git_context, versioning_repo, activity_repo, events
            )

        server_dir = server.deployment.server_dir
        if not os.path.exists(server_dir):
            raise NotFoundError(f"Server directory '{server_dir}' not found on disk")

        # 2. Check storage capability (reflink preferred; falls back to standard copy on ext4/NTFS)
        supports_reflink = StorageCapabilityProbe.probe_path(server_dir)

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
        else:
            if branch.status == BranchStatus.ARCHIVED:
                raise ConflictError(f"Cannot commit to archived branch '{branch.name}'")
            await self._enforce_protected_branch(command, branch, activity_repo)

        expected_head = branch.head_commit_id

        # 4. Create world snapshot (reflink when supported, standard copy fallback on ext4/NTFS)
        snapshot_id = str(uuid.uuid4())
        snapshot_dir = Path(server_dir) / ".onx" / "snapshots" / snapshot_id
        size_bytes = BtrfsZfsSnapshotDriver.create_snapshot(
            server_dir,
            snapshot_dir,
            allow_copy_fallback=not supports_reflink,
        )

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

        updated = await versioning_repo.advance_branch_head_optimistic(
            branch.id, commit_id, expected_head
        )
        if not updated:
            raise ConflictError(
                f"Concurrent commit detected for branch id '{branch.id}': head moved "
                f"from {expected_head!r} while the commit was being created. "
                "Re-read and retry."
            )
        await versioning_repo.save_commit(commit)

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
