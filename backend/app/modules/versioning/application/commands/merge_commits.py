from __future__ import annotations

import asyncio
import uuid
from typing import Any

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
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.git_branch_adapter import git_branch_context
from app.modules.versioning.domain.dag import check_cycle
from app.modules.versioning.domain.entities import BranchProtectionPolicy, ServerCommit
from app.modules.versioning.domain.events import CommitCreatedEvent, MergeCommitCreatedEvent
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    CommitManifest,
    normalize_server_type_str,
)
from app.modules.versioning.infrastructure.dynamic_class_c import DynamicClassCService
from app.modules.versioning.infrastructure.git_merge import GitMergeService


class MergeCommitsCommand(Command):
    server_id: str
    target_branch_name: str
    parent_commit_ids: list[str]
    message: str
    author_id: str | None = None
    manifest: dict[str, Any] | None = None
    force: bool = False
    force_reason: str | None = None
    caller_permissions: list[str] | None = None


class MergeCommitsHandler(CommandHandler[MergeCommitsCommand]):
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

    async def handle(self, command: MergeCommitsCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        events: list[DomainEvent] = []

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            from app.modules.activity.infrastructure.repository import SQLActivityRepository

            activity_repo = self._activity_repo or SQLActivityRepository()
            res = await self._execute(
                command, self._server_repo, self._versioning_repo, activity_repo, events
            )  # noqa: E501
        else:
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    async with database.session_factory() as session:
                        await ensure_versioning_allowed(command.server_id, session=session)
                        server_repo = self._server_repo or SQLServerRepository(session)
                        versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                        from app.modules.activity.infrastructure.repository import (
                            SQLActivityRepository,
                        )

                        activity_repo = self._activity_repo or SQLActivityRepository(session)
                        events.clear()
                        res = await self._execute(
                            command, server_repo, versioning_repo, activity_repo, events
                        )  # noqa: E501
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

    async def _execute(
        self,
        command: MergeCommitsCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
        activity_repo: ActivityRepository | None = None,  # noqa: ARG002
        events: list[DomainEvent] | None = None,
    ) -> CommandResult:
        from app.modules.shared.value_objects import ServerId

        # 1. Verify server exists
        try:
            server = await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        # 2. Native-Git vs DB-only dispatch
        git_context = git_branch_context(server)
        if git_context is not None:
            return await self._execute_native_git(
                command, server, git_context, versioning_repo, activity_repo, events
            )

        # DB-only manifest merge flow (legacy)
        # 2. Verify target branch exists and is not archived
        branch = await versioning_repo.get_branch_by_name(
            command.server_id, command.target_branch_name
        )
        if branch is None:
            raise NotFoundError(
                f"Branch '{command.target_branch_name}' not found on server '{command.server_id}'"
            )
        if branch.status == BranchStatus.ARCHIVED:
            raise ConflictError(f"Cannot commit to archived branch '{branch.name}'")

        # Merging a working branch into 'main' is the intended promotion path;
        # branch protection on custom non-main branches still gates merges when
        # allow_direct_commit is disabled.
        effective_protected = branch.is_protected and branch.name != "main"
        policy = branch.protection_policy or BranchProtectionPolicy()
        if effective_protected and not branch.can_commit_directly():
            if not command.force:
                raise BranchProtectedError(
                    f"Direct merge commit into protected branch '{branch.name}' is forbidden."
                )
            if not policy.allow_force_bypass:
                raise BranchProtectedError(
                    f"Force bypass is disabled by protection policy on branch '{branch.name}'"
                )
            perms = command.caller_permissions or []
            if "admin:full" not in perms and "server:version:branch:bypass_protection" not in perms:
                raise PermissionDenied(
                    "Caller lacks 'server:version:branch:bypass_protection' "
                    "to bypass branch protection"
                )

        expected_head = branch.head_commit_id

        # 3. Validate parents
        if len(command.parent_commit_ids) < 2:
            raise ValueError("A merge commit requires at least two parent commits")

        if len(command.parent_commit_ids) != len(set(command.parent_commit_ids)):
            raise ValueError("Duplicate parent commit references are not allowed")

        parent_commits: list[ServerCommit] = []
        for pid in command.parent_commit_ids:
            parent = await versioning_repo.get_commit(pid)
            if parent is None:
                raise NotFoundError(
                    f"Parent commit '{pid}' not found on server '{command.server_id}'"
                )
            if parent.server_id != command.server_id:
                raise ValueError(
                    f"Cross-server parent rejected: parent server '{parent.server_id}' "
                    f"does not match commit server '{command.server_id}'"
                )
            parent_commits.append(parent)

        new_commit_id = str(uuid.uuid4())

        # 4. Cycle check
        has_cycle = await check_cycle(
            new_commit_id, command.parent_commit_ids, versioning_repo.get_commit_parents
        )
        if has_cycle:
            raise ValueError("Merge rejected: introduces a cycle in the commit DAG")

        # 5. Determine resolved manifest
        if command.manifest is not None:
            resolved_manifest = CommitManifest.from_dict(command.manifest)
        else:
            first_manifest = parent_commits[0].manifest
            if all(p.manifest == first_manifest for p in parent_commits[1:]):
                resolved_manifest = first_manifest
            else:
                raise ConflictError(
                    "Merge conflict: manifests differ and no resolved manifest was provided"
                )

        # 6. Create merge commit
        commit = ServerCommit(
            id=new_commit_id,
            server_id=command.server_id,
            message=command.message,
            manifest=resolved_manifest,
            branch_id=branch.id,
            parent_commit_ids=list(command.parent_commit_ids),
            author_id=command.author_id,
            world_snapshot_id=parent_commits[0].world_snapshot_id,
        )

        # 7. Advance branch head via CAS and save commit
        updated = await versioning_repo.advance_branch_head_optimistic(
            branch.id, new_commit_id, expected_head
        )
        if not updated:
            raise ConflictError(
                f"Concurrent merge detected for branch id '{branch.id}': head moved "
                f"from {expected_head!r} while the merge was being created."
            )
        await versioning_repo.save_commit(commit)

        commit_event = CommitCreatedEvent(
            server_id=command.server_id,
            commit_id=commit.id,
            message=commit.message,
            branch_name=branch.name,
        )
        merge_event = MergeCommitCreatedEvent(
            server_id=command.server_id,
            commit_id=commit.id,
            parent_commit_ids=list(command.parent_commit_ids),
            branch_name=branch.name,
        )

        if events is not None:
            events.append(commit_event)
            events.append(merge_event)
        elif self._event_bus is not None:
            await self._event_bus.publish(commit_event)
            await self._event_bus.publish(merge_event)

        return CommandResult(
            success=True,
            entity_id=commit.id,
            details={
                "commit_id": commit.id,
                "server_id": command.server_id,
                "branch_name": branch.name,
                "parent_commit_ids": command.parent_commit_ids,
            },
        )

    async def _execute_native_git(
        self, command, server, git_context, versioning_repo, activity_repo=None, events=None
    ):  # noqa: E501

        # validate parent count
        if len(command.parent_commit_ids) < 2:
            raise ValueError("A merge commit requires at least two parent commits")
        if len(command.parent_commit_ids) != len(set(command.parent_commit_ids)):
            raise ValueError("Duplicate parent commit references are not allowed")

        # check DB branch record
        branch = await versioning_repo.get_branch_by_name(
            command.server_id, command.target_branch_name
        )
        if branch is not None and branch.status == BranchStatus.ARCHIVED:
            raise ConflictError(f"Cannot commit to archived branch '{branch.name}'")

        # Merging into 'main' is the normal workflow (direct commits to main are blocked).
        # Custom non-main protected branches still enforce allow_direct_commit / force bypass.
        effective_protected = (
            branch.is_protected if branch is not None else False
        ) and command.target_branch_name != "main"
        policy = (
            branch.protection_policy if branch is not None else None
        ) or BranchProtectionPolicy()
        can_direct = branch.can_commit_directly() if branch is not None else False
        _bypass = False
        if effective_protected and not can_direct:
            if not command.force:
                raise BranchProtectedError(
                    f"Direct merge commit into protected branch '{command.target_branch_name}' is forbidden."  # noqa: E501
                )
            if not policy.allow_force_bypass:
                raise BranchProtectedError(
                    f"Force bypass is disabled by protection policy on branch '{command.target_branch_name}'"  # noqa: E501
                )
            perms = command.caller_permissions or []
            if "admin:full" not in perms and "server:version:branch:bypass_protection" not in perms:
                raise PermissionDenied(
                    "Caller lacks 'server:version:branch:bypass_protection' to bypass branch protection"  # noqa: E501
                )
            _bypass = True

        # audit written after successful merge (below)

        # load dynamic class c
        dyn_service = DynamicClassCService(git_context.layout)
        try:
            dynamic_class_c = dyn_service.list_paths(command.server_id)
        finally:
            dyn_service.close()

        git_merge = GitMergeService(git_context.layout)
        merge_result = git_merge.merge(
            server_id=command.server_id,
            server_root=git_context.server_root,
            target_branch_name=command.target_branch_name,
            parent_commit_ids=command.parent_commit_ids,
            message=command.message,
            dynamic_class_c=dynamic_class_c,
        )

        if _bypass and activity_repo is not None:
            audit_branch = branch.name if branch is not None else command.target_branch_name
            audit_log = ServerActivityLog(
                id=str(__import__("uuid").uuid4()),
                server_id=command.server_id,
                event_type="versioning.branch_protection_bypassed",
                summary=f"Merge commit to protected branch '{audit_branch}' was force-bypassed",
                actor_type="user" if command.author_id else "system",
                actor_id=command.author_id,
                details={"branch": audit_branch, "reason": command.force_reason or ""},
            )
            await activity_repo.save(audit_log)

        # D-7 projection
        if branch is not None:
            if await versioning_repo.get_commit(merge_result.commit_id) is None:
                commit = ServerCommit(
                    id=merge_result.commit_id,
                    server_id=command.server_id,
                    message=command.message,
                    manifest=CommitManifest(
                        server_type=normalize_server_type_str(server.server_type),
                        minecraft_version=str(server.minecraft_version),
                    ),
                    branch_id=branch.id,
                    parent_commit_ids=list(merge_result.parent_commit_ids),
                    author_id=command.author_id,
                )
                await versioning_repo.save_commit(commit)
            updated = await versioning_repo.advance_branch_head_optimistic(
                branch.id, merge_result.commit_id, branch.head_commit_id
            )
            if not updated:
                raise ConflictError(
                    f"Concurrent merge detected for branch id '{branch.id}': head moved "
                    f"from {branch.head_commit_id!r} while the merge was being created."
                )

        if command.target_branch_name == "main":
            from app.modules.plugin.application.branch_plugins import (
                sync_main_lockfile_addons_to_server_root,
            )

            sync_main_lockfile_addons_to_server_root(server, layout=git_context.layout)

        commit_event = CommitCreatedEvent(
            server_id=command.server_id,
            commit_id=merge_result.commit_id,
            message=command.message,
            branch_name=command.target_branch_name,
        )
        merge_event = MergeCommitCreatedEvent(
            server_id=command.server_id,
            commit_id=merge_result.commit_id,
            parent_commit_ids=list(merge_result.parent_commit_ids),
            branch_name=command.target_branch_name,
        )
        if events is not None:
            events.append(commit_event)
            events.append(merge_event)

        return CommandResult(
            success=True,
            entity_id=merge_result.commit_id,
            details={
                "commit_id": merge_result.commit_id,
                "server_id": command.server_id,
                "branch_name": merge_result.target_branch_name,
                "parent_commit_ids": list(merge_result.parent_commit_ids),
                "files": list(merge_result.changed_files),
                "warnings": list(merge_result.warnings),
                "engine": "native-git",
            },
        )
