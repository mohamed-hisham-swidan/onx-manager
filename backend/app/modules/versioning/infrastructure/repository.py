from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.versioning.domain.entities import (
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
)
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import (
    BotTech,
    CommitManifest,
    PlacementMode,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerCommitModel,
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
        if model is None:
            model = ServerBranchModel(
                id=branch.id,
                server_id=branch.server_id,
                name=branch.name,
                head_commit_id=branch.head_commit_id,
                created_at=branch.created_at,
            )
            self._session.add(model)
        else:
            model.name = branch.name
            model.head_commit_id = branch.head_commit_id
        await self._session.flush()
        return branch

    # Commits
    async def get_commit(self, commit_id: str) -> ServerCommit | None:
        model = await self._session.get(ServerCommitModel, commit_id)
        return self._commit_to_domain(model) if model else None

    async def list_commits(
        self, server_id: str, branch_id: str | None = None, limit: int = 50
    ) -> list[ServerCommit]:
        stmt = select(ServerCommitModel).where(ServerCommitModel.server_id == server_id)
        if branch_id:
            stmt = stmt.where(ServerCommitModel.branch_id == branch_id)
        stmt = stmt.order_by(desc(ServerCommitModel.created_at)).limit(limit)
        res = await self._session.execute(stmt)
        return [self._commit_to_domain(m) for m in res.scalars().all()]

    async def save_commit(self, commit: ServerCommit) -> ServerCommit:
        model = await self._session.get(ServerCommitModel, commit.id)
        if model is None:
            model = ServerCommitModel(
                id=commit.id,
                server_id=commit.server_id,
                branch_id=commit.branch_id,
                parent_commit_id=commit.parent_commit_id,
                author_id=commit.author_id,
                message=commit.message,
                manifest_json=commit.manifest.to_dict(),
                world_snapshot_id=commit.world_snapshot_id,
                created_at=commit.created_at,
            )
            self._session.add(model)
        else:
            model.message = commit.message
            model.manifest_json = commit.manifest.to_dict()
            model.world_snapshot_id = commit.world_snapshot_id
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
        await self._session.flush()
        return test_run

    # Model mappers
    @staticmethod
    def _branch_to_domain(m: ServerBranchModel) -> ServerBranch:
        return ServerBranch(
            id=m.id,
            server_id=m.server_id,
            name=m.name,
            head_commit_id=m.head_commit_id,
            created_at=m.created_at,
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
    def _commit_to_domain(m: ServerCommitModel) -> ServerCommit:
        manifest_data = m.manifest_json if isinstance(m.manifest_json, dict) else {}
        return ServerCommit(
            id=m.id,
            server_id=m.server_id,
            message=m.message,
            manifest=CommitManifest.from_dict(manifest_data),
            branch_id=m.branch_id,
            parent_commit_id=m.parent_commit_id,
            author_id=m.author_id,
            world_snapshot_id=m.world_snapshot_id,
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
        )
