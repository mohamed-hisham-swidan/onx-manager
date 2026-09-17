from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.versioning.domain.entities import (
    ImportReview,
    Materialization,
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
    Tag,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    BotTech,
    CommitManifest,
    ImportReviewStatus,
    MaterializationMode,
    MaterializationStatus,
    PathClassification,
    PlacementMode,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerCommitModel,
    ServerCommitParentModel,
    ServerImportReviewModel,
    ServerMaterializationModel,
    ServerTagModel,
    ServerTestRunModel,
    ServerWorldSnapshotModel,
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
        if model is None:
            model = ServerBranchModel(
                id=branch.id,
                server_id=branch.server_id,
                name=branch.name,
                head_commit_id=branch.head_commit_id,
                status=status_val,
                created_at=branch.created_at,
            )
            self._session.add(model)
        else:
            model.name = branch.name
            model.head_commit_id = branch.head_commit_id
            model.status = status_val
        await self._session.flush()
        return branch

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
                [TestRunStatus.PENDING.value, TestRunStatus.RUNNING.value]
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
                    [TestRunStatus.PENDING.value, TestRunStatus.RUNNING.value]
                )
            )
            .order_by(ServerTestRunModel.created_at)
        )
        res = await self._session.execute(stmt)
        return [self._test_run_to_domain(m) for m in res.scalars().all()]

    async def save_test_run(self, test_run: ServerTestRun) -> ServerTestRun:
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

        return ServerBranch(
            id=m.id,
            server_id=m.server_id,
            name=m.name,
            head_commit_id=m.head_commit_id,
            created_at=m.created_at,
            status=status,
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

