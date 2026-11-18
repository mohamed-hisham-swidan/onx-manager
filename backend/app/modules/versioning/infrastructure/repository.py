from __future__ import annotations

from sqlalchemy import desc, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.versioning.domain.entities import (
    ImportReview,
    Materialization,
    Runtime,
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
    Tag,
    TestDefinition,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BranchStatus,
    CommitManifest,
    ImportReviewStatus,
    MaterializationMode,
    MaterializationStatus,
    PathClassification,
    PlacementMode,
    RuntimeStatus,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerCommitModel,
    ServerCommitParentModel,
    ServerImportReviewModel,
    ServerMaterializationModel,
    ServerRuntimeModel,
    ServerTagModel,
    ServerTestDefinitionModel,
    ServerTestRunModel,
    ServerWorldSnapshotModel,
)


def _is_sqlite_busy_snapshot(exc: OperationalError) -> bool:
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    return (
        getattr(orig, "sqlite_errorname", None) == "SQLITE_BUSY_SNAPSHOT"
        or getattr(orig, "sqlite_errorcode", None) == 517
    )


class SQLVersioningRepository(VersioningRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # Branches
    async def get_branch(self, branch_id: str) -> ServerBranch | None:
        model = await self._session.get(ServerBranchModel, branch_id)
        return self._branch_to_domain(model) if model else None

    async def get_branch_by_name(self, server_id: str, name: str) -> ServerBranch | None:
        stmt = select(ServerBranchModel).where(
            ServerBranchModel.server_id == server_id,
            ServerBranchModel.name == name,
        )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._branch_to_domain(model) if model else None

    async def list_branches(self, server_id: str) -> list[ServerBranch]:
        stmt = (
            select(ServerBranchModel)
            .where(ServerBranchModel.server_id == server_id)
            .order_by(ServerBranchModel.name)
        )
        res = await self._session.execute(stmt)
        return [self._branch_to_domain(m) for m in res.scalars().all()]

    async def save_branch(self, branch: ServerBranch) -> ServerBranch:
        model = await self._session.get(ServerBranchModel, branch.id)
        status_val = (
            branch.status.value
            if hasattr(branch.status, "value")
            else str(branch.status)
        )
        policy_data = branch.protection_policy.to_dict() if branch.protection_policy else None
        if model is None:
            model = ServerBranchModel(
                id=branch.id,
                server_id=branch.server_id,
                name=branch.name,
                head_commit_id=branch.head_commit_id,
                status=status_val,
                is_protected=branch.is_protected,
                protection_policy=policy_data,
                created_at=branch.created_at,
                port_set_json=branch.port_set,
                runtime_status=branch.runtime_status,
                active_runtime_id=branch.active_runtime_id,
                active_commit_sha=branch.active_commit_sha,
                active_data_template_id=branch.active_data_template_id,
            )
            self._session.add(model)
        else:
            model.name = branch.name
            # head_commit_id is intentionally NOT assigned here
            model.status = status_val
            model.is_protected = branch.is_protected
            model.protection_policy = policy_data
            model.port_set_json = branch.port_set
            model.runtime_status = branch.runtime_status
            model.active_runtime_id = branch.active_runtime_id
            model.active_commit_sha = branch.active_commit_sha
            model.active_data_template_id = branch.active_data_template_id
        await self._session.flush()
        return branch

    async def delete_branch(self, branch_id: str) -> bool:
        model = await self._session.get(ServerBranchModel, branch_id)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    async def advance_branch_head_optimistic(
        self, branch_id: str, new_head: str, expected_head: str | None
    ) -> bool:
        conditions = [
            ServerBranchModel.id == branch_id,
            ServerBranchModel.status != BranchStatus.ARCHIVED.value,
        ]
        if expected_head is None:
            conditions.append(ServerBranchModel.head_commit_id.is_(None))
        else:
            conditions.append(ServerBranchModel.head_commit_id == expected_head)

        stmt = (
            update(ServerBranchModel)
            .where(*conditions)
            .values(head_commit_id=new_head, status=BranchStatus.ACTIVE.value)
            .execution_options(synchronize_session="fetch")
        )
        try:
            result = await self._session.execute(stmt)
            await self._session.flush()
        except OperationalError as exc:
            if _is_sqlite_busy_snapshot(exc):
                return False
            raise
        return result.rowcount == 1

    # Commits
    async def get_commit_parents(self, commit_id: str) -> list[str]:
        stmt = (
            select(ServerCommitParentModel.parent_commit_id)
            .where(ServerCommitParentModel.commit_id == commit_id)
            .order_by(ServerCommitParentModel.parent_index)
        )
        res = await self._session.execute(stmt)
        parents = list(res.scalars().all())
        if not parents:
            model = await self._session.get(ServerCommitModel, commit_id)
            if model and model.parent_commit_id:
                return [model.parent_commit_id]
        return parents

    async def _get_parents_for_commits(self, commit_ids: list[str]) -> dict[str, list[str]]:
        if not commit_ids:
            return {}
        stmt = (
            select(ServerCommitParentModel)
            .where(ServerCommitParentModel.commit_id.in_(commit_ids))
            .order_by(ServerCommitParentModel.commit_id, ServerCommitParentModel.parent_index)
        )
        res = await self._session.execute(stmt)
        result: dict[str, list[str]] = {cid: [] for cid in commit_ids}
        for parent_row in res.scalars().all():
            result[parent_row.commit_id].append(parent_row.parent_commit_id)
        return result

    async def get_commit(self, commit_id: str) -> ServerCommit | None:
        model = await self._session.get(ServerCommitModel, commit_id)
        if not model:
            return None
        parents = await self.get_commit_parents(commit_id)
        return self._commit_to_domain(model, parent_commit_ids=parents)

    async def list_commits(
        self, server_id: str, branch_id: str | None = None, limit: int = 50
    ) -> list[ServerCommit]:
        stmt = select(ServerCommitModel).where(ServerCommitModel.server_id == server_id)
        if branch_id:
            stmt = stmt.where(ServerCommitModel.branch_id == branch_id)
        stmt = stmt.order_by(desc(ServerCommitModel.created_at)).limit(limit)
        res = await self._session.execute(stmt)
        models = res.scalars().all()
        if not models:
            return []
        commit_ids = [m.id for m in models]
        parents_map = await self._get_parents_for_commits(commit_ids)
        return [
            self._commit_to_domain(m, parent_commit_ids=parents_map.get(m.id))
            for m in models
        ]

    async def save_commit(self, commit: ServerCommit) -> ServerCommit:
        model = await self._session.get(ServerCommitModel, commit.id)
        if model is not None:
            from app.core.exceptions import ConflictError

            raise ConflictError(f"Commit '{commit.id}' is immutable and cannot be updated")

        primary_parent = (
            commit.parent_commit_id
            or (commit.parent_commit_ids[0] if commit.parent_commit_ids else None)
        )
        model = ServerCommitModel(
            id=commit.id,
            server_id=commit.server_id,
            branch_id=commit.branch_id,
            parent_commit_id=primary_parent,
            author_id=commit.author_id,
            message=commit.message,
            manifest_json=commit.manifest.to_dict(),
            world_snapshot_id=commit.world_snapshot_id,
            created_at=commit.created_at,
        )
        self._session.add(model)

        for idx, pid in enumerate(commit.parent_commit_ids):
            parent_model = ServerCommitParentModel(
                commit_id=commit.id,
                parent_commit_id=pid,
                parent_index=idx,
            )
            self._session.add(parent_model)

        await self._session.flush()
        return commit

    # World Snapshots
    async def get_snapshot(self, snapshot_id: str) -> ServerWorldSnapshot | None:
        model = await self._session.get(ServerWorldSnapshotModel, snapshot_id)
        return self._snapshot_to_domain(model) if model else None

    async def save_snapshot(self, snapshot: ServerWorldSnapshot) -> ServerWorldSnapshot:
        model = await self._session.get(ServerWorldSnapshotModel, snapshot.id)
        if model is None:
            model = ServerWorldSnapshotModel(
                id=snapshot.id,
                server_id=snapshot.server_id,
                storage_path=snapshot.storage_path,
                size_bytes=snapshot.size_bytes,
                created_at=snapshot.created_at,
            )
            self._session.add(model)
        else:
            model.storage_path = snapshot.storage_path
            model.size_bytes = snapshot.size_bytes
        await self._session.flush()
        return snapshot

    # Test Runs
    async def get_test_run(self, test_run_id: str) -> ServerTestRun | None:
        model = await self._session.get(ServerTestRunModel, test_run_id)
        return self._test_run_to_domain(model) if model else None

    async def get_active_test_run_for_server(self, server_id: str) -> ServerTestRun | None:
        stmt = select(ServerTestRunModel).where(
            ServerTestRunModel.server_id == server_id,
            ServerTestRunModel.status.in_(
                [
                    TestRunStatus.PENDING.value,
                    TestRunStatus.BOOTING.value,
                    TestRunStatus.RUNNING.value,
                ]
            ),
        )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._test_run_to_domain(model) if model else None

    async def list_test_runs(self, server_id: str, limit: int = 20) -> list[ServerTestRun]:
        stmt = (
            select(ServerTestRunModel)
            .where(ServerTestRunModel.server_id == server_id)
            .order_by(desc(ServerTestRunModel.created_at))
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return [self._test_run_to_domain(m) for m in res.scalars().all()]

    async def list_active_test_runs(self) -> list[ServerTestRun]:
        stmt = (
            select(ServerTestRunModel)
            .where(
                ServerTestRunModel.status.in_(
                    [
                        TestRunStatus.PENDING.value,
                        TestRunStatus.BOOTING.value,
                        TestRunStatus.RUNNING.value,
                    ]
                )
            )
            .order_by(ServerTestRunModel.created_at)
        )
        res = await self._session.execute(stmt)
        return [self._test_run_to_domain(m) for m in res.scalars().all()]

    async def save_test_run(self, test_run: ServerTestRun) -> ServerTestRun:
        if test_run.expires_at is None and test_run.created_at is not None:
            from datetime import timedelta

            from app.core.config import AppSettings

            retention_hours = AppSettings().test_artifact_retention_hours
            test_run.expires_at = test_run.created_at + timedelta(hours=retention_hours)

        model = await self._session.get(ServerTestRunModel, test_run.id)
        if model is None:
            model = ServerTestRunModel(
                id=test_run.id,
                server_id=test_run.server_id,
                commit_id=test_run.commit_id,
                node_id=test_run.node_id,
                status=test_run.status.value
                if isinstance(test_run.status, TestRunStatus)
                else test_run.status,
                ephemeral_port=test_run.ephemeral_port,
                log_output=test_run.log_output,
                failure_reason=test_run.failure_reason,
                created_at=test_run.created_at,
                expires_at=test_run.expires_at,
                bot_count=test_run.bot_count,
                duration_minutes=test_run.duration_minutes,
                placement_mode=(
                    test_run.placement_mode.value
                    if isinstance(test_run.placement_mode, PlacementMode)
                    else test_run.placement_mode
                ),
                bot_tech=(
                    test_run.bot_tech.value
                    if isinstance(test_run.bot_tech, BotTech)
                    else test_run.bot_tech
                ),
                reserved_ram_mb=test_run.reserved_ram_mb,
                reserved_cores=test_run.reserved_cores,
                runtime_id=test_run.runtime_id,
                test_definition_id=test_run.test_definition_id,
                evidence_bundle=test_run.evidence_bundle,
                artifacts_purged=test_run.artifacts_purged,
                operation_id=test_run.operation_id,
                branch_name=test_run.branch_name,
                data_template_id=test_run.data_template_id,
                port_set_json=test_run.port_set,
            )
            self._session.add(model)
        else:
            model.status = (
                test_run.status.value
                if isinstance(test_run.status, TestRunStatus)
                else test_run.status
            )
            model.ephemeral_port = test_run.ephemeral_port
            model.log_output = test_run.log_output
            model.failure_reason = test_run.failure_reason
            model.expires_at = test_run.expires_at
            if test_run.reserved_ram_mb is not None:
                model.reserved_ram_mb = test_run.reserved_ram_mb
            if test_run.reserved_cores is not None:
                model.reserved_cores = test_run.reserved_cores
            if test_run.runtime_id is not None:
                model.runtime_id = test_run.runtime_id
            if test_run.test_definition_id is not None:
                model.test_definition_id = test_run.test_definition_id
            if test_run.evidence_bundle is not None:
                model.evidence_bundle = test_run.evidence_bundle
            if test_run.operation_id is not None:
                model.operation_id = test_run.operation_id
            model.branch_name = test_run.branch_name
            model.data_template_id = test_run.data_template_id
            model.port_set_json = test_run.port_set
            model.artifacts_purged = test_run.artifacts_purged
        await self._session.flush()
        return test_run

    # Tags
    async def get_tag(self, server_id: str, name: str) -> Tag | None:
        stmt = select(ServerTagModel).where(
            ServerTagModel.server_id == server_id,
            ServerTagModel.name == name,
        )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._tag_to_domain(model) if model else None

    async def list_tags(self, server_id: str) -> list[Tag]:
        stmt = (
            select(ServerTagModel)
            .where(ServerTagModel.server_id == server_id)
            .order_by(ServerTagModel.name)
        )
        res = await self._session.execute(stmt)
        return [self._tag_to_domain(m) for m in res.scalars().all()]

    async def save_tag(self, tag: Tag) -> Tag:
        from app.core.exceptions import ConflictError

        existing = await self.get_tag(tag.server_id, tag.name)
        if existing is not None:
            raise ConflictError(f"Tag '{tag.name}' already exists on server '{tag.server_id}'")

        model = ServerTagModel(
            id=tag.id,
            server_id=tag.server_id,
            name=tag.name,
            commit_id=tag.commit_id,
            created_at=tag.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return tag

    # Materializations
    async def get_materialization(self, materialization_id: str) -> Materialization | None:
        model = await self._session.get(ServerMaterializationModel, materialization_id)
        return self._materialization_to_domain(model) if model else None

    async def list_materializations(self, server_id: str) -> list[Materialization]:
        stmt = (
            select(ServerMaterializationModel)
            .where(ServerMaterializationModel.server_id == server_id)
            .order_by(desc(ServerMaterializationModel.created_at))
        )
        res = await self._session.execute(stmt)
        return [self._materialization_to_domain(m) for m in res.scalars().all()]

    async def save_materialization(self, materialization: Materialization) -> Materialization:
        model = await self._session.get(ServerMaterializationModel, materialization.id)
        classification_data = {
            k: v.value if hasattr(v, "value") else str(v)
            for k, v in materialization.path_classification.items()
        }
        status_val = (
            materialization.status.value
            if hasattr(materialization.status, "value")
            else str(materialization.status)
        )
        mode_val = (
            materialization.mode.value
            if hasattr(materialization.mode, "value")
            else str(materialization.mode)
        )
        if model is None:
            model = ServerMaterializationModel(
                id=materialization.id,
                server_id=materialization.server_id,
                commit_id=materialization.commit_id,
                root_path=materialization.root_path,
                status=status_val,
                mode=mode_val,
                revision=materialization.revision,
                path_classification=classification_data,
                created_at=materialization.created_at,
            )
            self._session.add(model)
        else:
            model.status = status_val
            model.mode = mode_val
            model.revision = materialization.revision
            model.path_classification = classification_data
        await self._session.flush()
        return materialization

    # Import Reviews
    async def get_import_review(self, review_id: str) -> ImportReview | None:
        model = await self._session.get(ServerImportReviewModel, review_id)
        return self._import_review_to_domain(model) if model else None

    async def list_import_reviews(self, server_id: str, limit: int = 50) -> list[ImportReview]:
        stmt = (
            select(ServerImportReviewModel)
            .where(ServerImportReviewModel.server_id == server_id)
            .order_by(desc(ServerImportReviewModel.created_at))
            .limit(limit)
        )
        res = await self._session.execute(stmt)
        return [self._import_review_to_domain(m) for m in res.scalars().all()]

    async def save_import_review(self, review: ImportReview) -> ImportReview:
        model = await self._session.get(ServerImportReviewModel, review.id)
        status_val = review.status.value if hasattr(review.status, "value") else str(review.status)
        if model is None:
            model = ServerImportReviewModel(
                id=review.id,
                server_id=review.server_id,
                commit_id=review.commit_id,
                parent_commit_id=review.parent_commit_id,
                branch_name=review.branch_name,
                status=status_val,
                changes=review.changes,
                revert_commit_id=review.revert_commit_id,
                created_at=review.created_at,
                updated_at=review.updated_at,
            )
            self._session.add(model)
        else:
            model.status = status_val
            model.changes = review.changes
            model.revert_commit_id = review.revert_commit_id
            model.updated_at = review.updated_at
        await self._session.flush()
        return review

    # Test Definitions
    async def get_test_definition(self, definition_id: str) -> TestDefinition | None:
        model = await self._session.get(ServerTestDefinitionModel, definition_id)
        return self._test_definition_to_domain(model) if model else None

    async def list_test_definitions(self, server_id: str) -> list[TestDefinition]:
        stmt = (
            select(ServerTestDefinitionModel)
            .where(ServerTestDefinitionModel.server_id == server_id)
            .order_by(ServerTestDefinitionModel.created_at)
        )
        res = await self._session.execute(stmt)
        return [self._test_definition_to_domain(m) for m in res.scalars().all()]

    async def save_test_definition(self, definition: TestDefinition) -> TestDefinition:
        model = await self._session.get(ServerTestDefinitionModel, definition.id)
        bot_tech = (
            definition.bot_technology.value
            if isinstance(definition.bot_technology, BotTech)
            else definition.bot_technology
        )
        placement_mode = (
            definition.placement_mode.value
            if isinstance(definition.placement_mode, PlacementMode)
            else definition.placement_mode
        )
        if model is None:
            model = ServerTestDefinitionModel(
                id=definition.id,
                server_id=definition.server_id,
                name=definition.name,
                description=definition.description,
                server_type=definition.server_type,
                bot_technology=bot_tech,
                bot_count=definition.bot_count,
                duration_seconds=definition.duration_seconds,
                join_stagger_seconds=definition.join_stagger_seconds,
                connect_grace_seconds=definition.connect_grace_seconds,
                placement_mode=placement_mode,
                assertion_rules=definition.assertion_rules,
                timeout_seconds=definition.timeout_seconds,
                created_at=definition.created_at,
                updated_at=definition.updated_at,
            )
            self._session.add(model)
        else:
            model.name = definition.name
            model.description = definition.description
            model.server_type = definition.server_type
            model.bot_technology = bot_tech
            model.bot_count = definition.bot_count
            model.duration_seconds = definition.duration_seconds
            model.join_stagger_seconds = definition.join_stagger_seconds
            model.connect_grace_seconds = definition.connect_grace_seconds
            model.placement_mode = placement_mode
            model.assertion_rules = definition.assertion_rules
            model.timeout_seconds = definition.timeout_seconds
            model.updated_at = definition.updated_at
        await self._session.flush()
        return definition

    async def delete_test_definition(self, definition_id: str) -> bool:
        model = await self._session.get(ServerTestDefinitionModel, definition_id)
        if model:
            await self._session.delete(model)
            await self._session.flush()
            return True
        return False

    # Runtimes
    async def get_runtime(self, runtime_id: str) -> Runtime | None:
        model = await self._session.get(ServerRuntimeModel, runtime_id)
        return self._runtime_to_domain(model) if model else None

    async def save_runtime(self, runtime: Runtime) -> Runtime:
        model = await self._session.get(ServerRuntimeModel, runtime.id)
        status_val = (
            runtime.status.value
            if isinstance(runtime.status, RuntimeStatus)
            else runtime.status
        )
        if model is None:
            model = ServerRuntimeModel(
                id=runtime.id,
                server_id=runtime.server_id,
                commit_id=runtime.commit_id,
                materialization_id=runtime.materialization_id,
                provider_type=runtime.provider_type,
                container_id=runtime.container_id,
                pid=runtime.pid,
                port=runtime.port,
                status=status_val,
                exit_code=runtime.exit_code,
                oom_killed=runtime.oom_killed,
                started_at=runtime.started_at,
                stopped_at=runtime.stopped_at,
                created_at=runtime.created_at,
                branch_name=runtime.branch_name,
                data_template_id=runtime.data_template_id,
                port_set_json=runtime.port_set,
                allow_public_test_join=runtime.allow_public_test_join,
                export_path=runtime.export_path,
            )
            self._session.add(model)
        else:
            model.container_id = runtime.container_id
            model.pid = runtime.pid
            model.port = runtime.port
            model.status = status_val
            model.exit_code = runtime.exit_code
            model.oom_killed = runtime.oom_killed
            model.stopped_at = runtime.stopped_at
            model.branch_name = runtime.branch_name
            model.data_template_id = runtime.data_template_id
            model.port_set_json = runtime.port_set
            model.allow_public_test_join = runtime.allow_public_test_join
            model.export_path = runtime.export_path
        await self._session.flush()
        return runtime

    async def get_active_runtime_for_branch(
        self, server_id: str, branch_name: str
    ) -> Runtime | None:
        stmt = (
            select(ServerRuntimeModel)
            .where(
                ServerRuntimeModel.server_id == server_id,
                ServerRuntimeModel.branch_name == branch_name,
                ServerRuntimeModel.status.in_(("starting", "running")),
            )
            .order_by(desc(ServerRuntimeModel.created_at))
        )
        res = await self._session.execute(stmt)
        model = res.scalar_one_or_none()
        return self._runtime_to_domain(model) if model else None

    async def list_active_runtimes(
        self, server_id: str | None = None, *, exclude_main: bool = False
    ) -> list[Runtime]:
        stmt = select(ServerRuntimeModel).where(
            ServerRuntimeModel.status.in_(("starting", "running"))
        )
        if server_id is not None:
            stmt = stmt.where(ServerRuntimeModel.server_id == server_id)
        if exclude_main:
            stmt = stmt.where(
                (ServerRuntimeModel.branch_name.is_(None))
                | (ServerRuntimeModel.branch_name != "main")
            )
        stmt = stmt.order_by(ServerRuntimeModel.created_at)
        res = await self._session.execute(stmt)
        return [self._runtime_to_domain(m) for m in res.scalars().all()]

    # Model mappers
    @staticmethod
    def _branch_to_domain(m: ServerBranchModel) -> ServerBranch:
        from app.modules.versioning.domain.value_objects import BranchStatus

        status_str = getattr(m, "status", None)
        if status_str:
            try:
                status = BranchStatus(status_str)
            except ValueError:
                status = BranchStatus.ACTIVE if m.head_commit_id else BranchStatus.CREATED
        else:
            status = BranchStatus.ACTIVE if m.head_commit_id else BranchStatus.CREATED

        is_protected = bool(getattr(m, "is_protected", False))
        policy_data = getattr(m, "protection_policy", None)
        from app.modules.versioning.domain.entities import BranchProtectionPolicy

        protection_policy = (
            BranchProtectionPolicy.from_dict(policy_data)
            if policy_data
            else (BranchProtectionPolicy() if is_protected else None)
        )

        return ServerBranch(
            id=m.id,
            server_id=m.server_id,
            name=m.name,
            head_commit_id=m.head_commit_id,
            created_at=m.created_at,
            status=status,
            is_protected=is_protected,
            protection_policy=protection_policy,
            port_set=getattr(m, "port_set_json", None),
            runtime_status=getattr(m, "runtime_status", None) or "stopped",
            active_runtime_id=getattr(m, "active_runtime_id", None),
            active_commit_sha=getattr(m, "active_commit_sha", None),
            active_data_template_id=getattr(m, "active_data_template_id", None),
        )

    @staticmethod
    def _snapshot_to_domain(m: ServerWorldSnapshotModel) -> ServerWorldSnapshot:
        return ServerWorldSnapshot(
            id=m.id,
            server_id=m.server_id,
            storage_path=m.storage_path,
            size_bytes=m.size_bytes,
            created_at=m.created_at,
        )

    @staticmethod
    def _commit_to_domain(
        m: ServerCommitModel, parent_commit_ids: list[str] | None = None
    ) -> ServerCommit:
        manifest_data = m.manifest_json if isinstance(m.manifest_json, dict) else {}
        if parent_commit_ids is None:
            parents = [m.parent_commit_id] if m.parent_commit_id else []
        elif not parent_commit_ids and m.parent_commit_id:
            parents = [m.parent_commit_id]
        else:
            parents = parent_commit_ids

        return ServerCommit(
            id=m.id,
            server_id=m.server_id,
            message=m.message,
            manifest=CommitManifest.from_dict(manifest_data),
            branch_id=m.branch_id,
            parent_commit_id=m.parent_commit_id,
            parent_commit_ids=parents,
            author_id=m.author_id,
            world_snapshot_id=m.world_snapshot_id,
            created_at=m.created_at,
        )

    @staticmethod
    def _tag_to_domain(m: ServerTagModel) -> Tag:
        return Tag(
            id=m.id,
            server_id=m.server_id,
            name=m.name,
            commit_id=m.commit_id,
            created_at=m.created_at,
        )

    @staticmethod
    def _test_run_to_domain(m: ServerTestRunModel) -> ServerTestRun:
        return ServerTestRun(
            id=m.id,
            server_id=m.server_id,
            commit_id=m.commit_id,
            node_id=m.node_id,
            status=TestRunStatus(m.status)
            if m.status in TestRunStatus._value2member_map_
            else TestRunStatus.PENDING,
            ephemeral_port=m.ephemeral_port,
            log_output=m.log_output,
            failure_reason=m.failure_reason,
            created_at=m.created_at,
            expires_at=m.expires_at,
            bot_count=m.bot_count,
            duration_minutes=m.duration_minutes,
            placement_mode=(
                PlacementMode(m.placement_mode)
                if m.placement_mode in PlacementMode._value2member_map_
                else PlacementMode.SIDECAR
            ),
            bot_tech=(
                BotTech(m.bot_tech) if m.bot_tech in BotTech._value2member_map_ else BotTech.AUTO
            ),
            reserved_ram_mb=m.reserved_ram_mb,
            reserved_cores=m.reserved_cores,
            runtime_id=m.runtime_id,
            test_definition_id=m.test_definition_id,
            evidence_bundle=m.evidence_bundle,
            artifacts_purged=bool(m.artifacts_purged) if m.artifacts_purged is not None else False,
            operation_id=m.operation_id,
            branch_name=getattr(m, "branch_name", None),
            data_template_id=getattr(m, "data_template_id", None),
            port_set=getattr(m, "port_set_json", None),
        )

    @staticmethod
    def _materialization_to_domain(m: ServerMaterializationModel) -> Materialization:
        classifications: dict[str, PathClassification] = {}
        if isinstance(m.path_classification, dict):
            for k, v in m.path_classification.items():
                try:
                    classifications[k] = PathClassification(v)
                except ValueError:
                    classifications[k] = PathClassification.TRACKED

        mode = (
            MaterializationMode(m.mode)
            if m.mode in MaterializationMode._value2member_map_
            else MaterializationMode.READONLY
        )
        status = (
            MaterializationStatus(m.status)
            if m.status in MaterializationStatus._value2member_map_
            else MaterializationStatus.PENDING
        )

        return Materialization(
            id=m.id,
            commit_id=m.commit_id,
            root_path=m.root_path,
            status=status,
            path_classification=classifications,
            created_at=m.created_at,
            mode=mode,
            server_id=m.server_id,
            revision=m.revision,
        )

    @staticmethod
    def _import_review_to_domain(m: ServerImportReviewModel) -> ImportReview:
        status = (
            ImportReviewStatus(m.status)
            if m.status in ImportReviewStatus._value2member_map_
            else ImportReviewStatus.PENDING
        )

        return ImportReview(
            id=m.id,
            server_id=m.server_id,
            commit_id=m.commit_id,
            parent_commit_id=m.parent_commit_id,
            branch_name=m.branch_name,
            status=status,
            changes=list(m.changes) if isinstance(m.changes, list) else [],
            revert_commit_id=m.revert_commit_id,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _test_definition_to_domain(m: ServerTestDefinitionModel) -> TestDefinition:
        bot_tech = (
            BotTech(m.bot_technology)
            if m.bot_technology in BotTech._value2member_map_
            else BotTech.MINEFLAYER
        )
        placement_mode = (
            PlacementMode(m.placement_mode)
            if m.placement_mode in PlacementMode._value2member_map_
            else PlacementMode.SIDECAR
        )
        return TestDefinition(
            id=m.id,
            server_id=m.server_id,
            name=m.name,
            description=m.description or "",
            server_type=m.server_type,
            bot_technology=bot_tech,
            bot_count=m.bot_count,
            duration_seconds=m.duration_seconds,
            join_stagger_seconds=m.join_stagger_seconds,
            connect_grace_seconds=m.connect_grace_seconds,
            placement_mode=placement_mode,
            assertion_rules=m.assertion_rules or {},
            timeout_seconds=m.timeout_seconds,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @staticmethod
    def _runtime_to_domain(m: ServerRuntimeModel) -> Runtime:
        status = (
            RuntimeStatus(m.status)
            if m.status in RuntimeStatus._value2member_map_
            else RuntimeStatus.STARTING
        )
        return Runtime(
            id=m.id,
            server_id=m.server_id,
            commit_id=m.commit_id,
            materialization_id=m.materialization_id,
            provider_type=m.provider_type,
            container_id=m.container_id,
            pid=m.pid,
            port=m.port,
            status=status,
            exit_code=m.exit_code,
            oom_killed=bool(m.oom_killed) if m.oom_killed is not None else False,
            started_at=m.started_at,
            stopped_at=m.stopped_at,
            created_at=m.created_at,
            branch_name=getattr(m, "branch_name", None),
            data_template_id=getattr(m, "data_template_id", None),
            port_set=getattr(m, "port_set_json", None),
            allow_public_test_join=bool(getattr(m, "allow_public_test_join", False)),
            export_path=getattr(m, "export_path", None),
        )

