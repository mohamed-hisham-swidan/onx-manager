from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    ArchiveBranchCommand,
    CreateBranchCommand,
    CreateCommitCommand,
    CreateTagCommand,
    DiffCommitsQuery,
    GetBranchHistoryQuery,
    GetServerTagQuery,
    GetServerTagsQuery,
    MergeCommitsCommand,
)
from app.modules.versioning.domain.entities import ServerBranch, ServerCommit
from app.modules.versioning.domain.value_objects import BranchStatus, CommitManifest
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.registration import register_handlers


@pytest.fixture(autouse=True)
async def init_test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine = database._engine
    old_factory = database._session_factory
    database._engine = engine
    database._session_factory = session_factory

    cb = CommandBus()
    qb = QueryBus()
    eb = EventBus()
    register_handlers(cb, qb, eb)

    yield cb, qb

    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


@pytest.fixture
async def seed_server():
    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-b-1",
            name="StageBTestServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path="/tmp/test_stage_b_server_dir",
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
            mode="advanced",
        )
        session.add(server)
        await session.commit()
    return "srv-b-1"


def _sample_manifest(configs: dict[str, str] | None = None) -> CommitManifest:
    return CommitManifest(
        server_type="vanilla",
        minecraft_version="1.21.1",
        configs=configs or {"server.properties": "motd=StageB"},
        mods=[],
        env_vars={"JAVA_OPTS": "-Xmx1G"},
        java_args="",
    )


class TestBranchStatusPersistenceAndArchive:
    @pytest.mark.asyncio
    async def test_branch_status_persistence_roundtrip(
        self, init_test_db, seed_server
    ) -> None:
        cb, _ = init_test_db
        server_id = seed_server

        # 1. Create branch
        res = await cb.send(CreateBranchCommand(server_id=server_id, name="dev"))
        assert res.success is True

        # 2. Verify in fresh DB session: status is created
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            branch = await repo.get_branch_by_name(server_id, "dev")
            assert branch is not None
            assert branch.status == BranchStatus.CREATED

        # 3. Archive branch
        res_arch = await cb.send(ArchiveBranchCommand(server_id=server_id, name="dev"))
        assert res_arch.success is True

        # 4. Verify in fresh DB session: status is archived
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            branch_archived = await repo.get_branch_by_name(server_id, "dev")
            assert branch_archived is not None
            assert branch_archived.status == BranchStatus.ARCHIVED

        # 5. Verify CreateCommitCommand fails against archived branch
        with (
            patch("os.path.exists", return_value=True),
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
            patch(
                "app.modules.versioning.infrastructure.manifest_builder.ManifestBuilder.build_manifest",
                return_value=_sample_manifest(),
            ),
        ):
            res_commit = await cb.send(
                CreateCommitCommand(
                    server_id=server_id,
                    branch_name="dev",
                    message="Commit to archived branch",
                )
            )
            assert res_commit.success is False
            assert "Cannot commit to archived branch 'dev'" in res_commit.error

    @pytest.mark.asyncio
    async def test_archive_nonexistent_branch_fails(self, init_test_db, seed_server) -> None:
        cb, _ = init_test_db
        res = await cb.send(ArchiveBranchCommand(server_id=seed_server, name="ghost"))
        assert res.success is False
        assert "Branch 'ghost' not found" in res.error


class TestMultiParentCommitPersistence:
    @pytest.mark.asyncio
    async def test_multi_parent_commit_persistence_roundtrip(self, seed_server) -> None:
        server_id = seed_server

        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            p1 = ServerCommit(
                id="parent-1",
                server_id=server_id,
                message="Parent 1",
                manifest=_sample_manifest(),
            )
            p2 = ServerCommit(
                id="parent-2",
                server_id=server_id,
                message="Parent 2",
                manifest=_sample_manifest(),
            )
            await repo.save_commit(p1)
            await repo.save_commit(p2)
            await session.commit()

        # Save merge commit referencing parent-1 and parent-2
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            merge_commit = ServerCommit(
                id="merge-1",
                server_id=server_id,
                message="Merge parent-1 and parent-2",
                manifest=_sample_manifest(),
                parent_commit_ids=["parent-1", "parent-2"],
            )
            await repo.save_commit(merge_commit)
            await session.commit()

        # Reload in a completely fresh session
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            loaded = await repo.get_commit("merge-1")
            assert loaded is not None
            assert loaded.parent_commit_id == "parent-1"
            assert loaded.parent_commit_ids == ["parent-1", "parent-2"]

            parents = await repo.get_commit_parents("merge-1")
            assert parents == ["parent-1", "parent-2"]


class TestTagsAndHistoryQueries:
    @pytest.mark.asyncio
    async def test_tag_lifecycle_and_queries(self, init_test_db, seed_server) -> None:
        cb, qb = init_test_db
        server_id = seed_server

        # Seed a commit
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            c = ServerCommit(
                id="commit-t1",
                server_id=server_id,
                message="Release commit",
                manifest=_sample_manifest(),
            )
            await repo.save_commit(c)
            await session.commit()

        # Create tag
        res = await cb.send(
            CreateTagCommand(server_id=server_id, name="v1.0.0", commit_id="commit-t1")
        )
        assert res.success is True

        # Query all tags
        tags = await qb.ask(GetServerTagsQuery(server_id=server_id))
        assert len(tags) == 1
        assert tags[0]["name"] == "v1.0.0"
        assert tags[0]["commit_id"] == "commit-t1"

        # Query single tag
        tag = await qb.ask(GetServerTagQuery(server_id=server_id, name="v1.0.0"))
        assert tag is not None
        assert tag["name"] == "v1.0.0"

        # Duplicate tag name rejected
        res_dup = await cb.send(
            CreateTagCommand(server_id=server_id, name="v1.0.0", commit_id="commit-t1")
        )
        assert res_dup.success is False
        assert "Tag 'v1.0.0' already exists" in res_dup.error

        # Non-existent commit rejected
        res_ghost = await cb.send(
            CreateTagCommand(server_id=server_id, name="v2.0.0", commit_id="ghost-commit")
        )
        assert res_ghost.success is False
        assert "Commit 'ghost-commit' not found" in res_ghost.error

    @pytest.mark.asyncio
    async def test_merge_commits_command_and_branch_history(
        self, init_test_db, seed_server
    ) -> None:
        cb, qb = init_test_db
        server_id = seed_server

        # Create branch and 2 parent commits
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            c1 = ServerCommit(
                id="c-main-1",
                server_id=server_id,
                message="Main commit",
                manifest=_sample_manifest({"motd": "MCS Main"}),
            )
            c2 = ServerCommit(
                id="c-feat-1",
                server_id=server_id,
                message="Feature commit",
                manifest=_sample_manifest({"motd": "MCS Main"}),
            )
            branch = ServerBranch(
                id="br-main",
                server_id=server_id,
                name="main",
                head_commit_id=c1.id,
                status=BranchStatus.ACTIVE,
            )
            await repo.save_commit(c1)
            await repo.save_commit(c2)
            await repo.save_branch(branch)
            await session.commit()

        # Merge c1 and c2 into main
        res = await cb.send(
            MergeCommitsCommand(
                server_id=server_id,
                target_branch_name="main",
                parent_commit_ids=["c-main-1", "c-feat-1"],
                message="Merge feature into main",
            )
        )
        assert res.success is True
        merge_commit_id = res.entity_id

        # Verify branch head was advanced
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            b = await repo.get_branch_by_name(server_id, "main")
            assert b is not None
            assert b.head_commit_id == merge_commit_id

        # Query branch history
        history = await qb.ask(GetBranchHistoryQuery(server_id=server_id, branch_name="main"))
        history_ids = [c["id"] for c in history]
        assert merge_commit_id in history_ids
        assert "c-main-1" in history_ids
        assert "c-feat-1" in history_ids

    @pytest.mark.asyncio
    async def test_merge_conflict_rejected_without_explicit_manifest(
        self, init_test_db, seed_server
    ) -> None:
        cb, _ = init_test_db
        server_id = seed_server

        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            c1 = ServerCommit(
                id="cm-1",
                server_id=server_id,
                message="Main commit",
                manifest=_sample_manifest({"motd": "Version A"}),
            )
            c2 = ServerCommit(
                id="cm-2",
                server_id=server_id,
                message="Feature commit",
                manifest=_sample_manifest({"motd": "Version B"}),
            )
            branch = ServerBranch(
                id="br-m",
                server_id=server_id,
                name="dev",
                head_commit_id=c1.id,
                status=BranchStatus.ACTIVE,
            )
            await repo.save_commit(c1)
            await repo.save_commit(c2)
            await repo.save_branch(branch)
            await session.commit()

        # Merge without manifest resolution must fail with ConflictError
        res_conflict = await cb.send(
            MergeCommitsCommand(
                server_id=server_id,
                target_branch_name="dev",
                parent_commit_ids=["cm-1", "cm-2"],
                message="Merge without resolution",
            )
        )
        assert res_conflict.success is False
        assert "Merge conflict: manifests differ" in res_conflict.error

        # Merge with explicit manifest resolution succeeds
        resolved = _sample_manifest({"motd": "Resolved Motd"}).to_dict()
        res = await cb.send(
            MergeCommitsCommand(
                server_id=server_id,
                target_branch_name="dev",
                parent_commit_ids=["cm-1", "cm-2"],
                message="Merge with resolution",
                manifest=resolved,
            )
        )
        assert res.success is True

    @pytest.mark.asyncio
    async def test_diff_commits_query(self, init_test_db, seed_server) -> None:
        _, qb = init_test_db
        server_id = seed_server

        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            c1 = ServerCommit(
                id="diff-1",
                server_id=server_id,
                message="Commit 1",
                manifest=_sample_manifest({"file1.txt": "v1"}),
            )
            c2 = ServerCommit(
                id="diff-2",
                server_id=server_id,
                message="Commit 2",
                manifest=_sample_manifest({"file1.txt": "v2", "file2.txt": "new"}),
            )
            await repo.save_commit(c1)
            await repo.save_commit(c2)
            await session.commit()

        diff = await qb.ask(
            DiffCommitsQuery(
                server_id=server_id,
                from_commit_id="diff-1",
                to_commit_id="diff-2",
            )
        )
        assert diff["has_changes"] is True
        assert diff["configs"]["modified"]["file1.txt"] == {"old": "v1", "new": "v2"}
        assert diff["configs"]["added"]["file2.txt"] == "new"
