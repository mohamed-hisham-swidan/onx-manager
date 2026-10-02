from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    AutoCommitLiveChangesCommand,
    ConfirmImportReviewCommand,
    CreateMaterializationCommand,
    DismissImportReviewCommand,
    GetMaterializationFileQuery,
    GetMaterializationsQuery,
    GetMaterializationTreeQuery,
    RemoveMaterializationCommand,
    RevertImportReviewCommand,
    ScanLiveChangesQuery,
    SetMaterializationEditModeCommand,
    WriteMaterializedFileCommand,
)
from app.modules.versioning.application.commands.remove_materialization import (
    cleanup_server_materializations,
)
from app.modules.versioning.domain.entities import ServerBranch, ServerCommit, Tag
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    CommitManifest,
    ImportReviewStatus,
    MaterializationMode,
    MaterializationStatus,
)
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

    yield cb, qb, eb

    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


@pytest.fixture
async def seed_env(tmp_path: Path):
    server_dir = tmp_path / "server_root"
    server_dir.mkdir(parents=True, exist_ok=True)
    (server_dir / "server.properties").write_text("difficulty=easy\nmotd=Live\n")
    (server_dir / "config").mkdir(parents=True, exist_ok=True)
    (server_dir / "config" / "paper-global.yml").write_text("timings: false\n")

    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-c-1",
            name="StageCTestServer",
            server_type="paper",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(server_dir),
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
        )
        session.add(server)

        repo = SQLVersioningRepository(session)
        manifest = CommitManifest(
            server_type="paper",
            minecraft_version="1.21.1",
            configs={
                "server.properties": "difficulty=easy\nmotd=Initial\n",
                "config/paper-global.yml": "timings: false\n",
            },
            mods=[],
            env_vars={"JAVA_ARGS": "-Xmx2G"},
        )
        commit = ServerCommit(
            id="c-initial",
            server_id="srv-c-1",
            message="Initial commit",
            manifest=manifest,
            parent_commit_ids=[],
        )
        await repo.save_commit(commit)

        branch = ServerBranch(
            id="b-main",
            server_id="srv-c-1",
            name="main",
            head_commit_id="c-initial",
            status=BranchStatus.ACTIVE,
        )
        await repo.save_branch(branch)

        tag = Tag(
            id="tag-v1",
            server_id="srv-c-1",
            name="v1.0.0",
            commit_id="c-initial",
        )
        await repo.save_tag(tag)
        await session.commit()

    return server_dir


class TestStageCMaterializationCommands:
    async def test_materialize_from_commit_branch_tag(
        self, init_test_db, seed_env: Path
    ) -> None:
        cb, qb, _ = init_test_db

        # 1. Materialize by direct commit_id
        res1 = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="c-initial",
            )
        )
        assert res1.success
        mat1 = res1.data
        assert mat1["commit_id"] == "c-initial"
        assert mat1["mode"] == MaterializationMode.READONLY.value
        assert mat1["status"] == MaterializationStatus.READY.value
        assert (seed_env / mat1["root_path"] / "server.properties").read_text() == (
            "difficulty=easy\nmotd=Initial\n"
        )

        # 2. Materialize by branch name
        res2 = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="branch",
                ref="main",
            )
        )
        assert res2.success
        mat2 = res2.data
        assert mat2["commit_id"] == "c-initial"

        # 3. Materialize by tag name
        res3 = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="tag",
                ref="v1.0.0",
            )
        )
        assert res3.success
        mat3 = res3.data
        assert mat3["commit_id"] == "c-initial"

        # 4. Unknown revision
        res_bad = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="nonexistent-rev",
            )
        )
        assert not res_bad.success

    async def test_lazy_staleness_on_branch_advance(
        self, init_test_db, seed_env: Path
    ) -> None:
        assert seed_env.exists()
        cb, qb, _ = init_test_db

        # Materialize tracking branch 'main'
        res = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="branch",
                ref="main",
            )
        )
        assert res.success
        mat_id = res.data["id"]

        # Advance branch 'main' to a new commit
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            new_commit = ServerCommit(
                id="c-next",
                server_id="srv-c-1",
                message="Second commit",
                manifest=CommitManifest(
                    server_type="paper",
                    minecraft_version="1.21.1",
                    configs={"server.properties": "difficulty=hard\n"},
                ),
                parent_commit_ids=["c-initial"],
            )
            await repo.save_commit(new_commit)
            branch = await repo.get_branch_by_name("srv-c-1", "main")
            branch.head_commit_id = "c-next"
            await repo.save_branch(branch)
            await session.commit()

        # Query materializations: should lazily detect branch head changed and mark STALE
        mats = await qb.ask(GetMaterializationsQuery(server_id="srv-c-1"))
        matched = next(m for m in mats if m["id"] == mat_id)
        assert matched["status"] == MaterializationStatus.STALE.value

    async def test_browse_tree_and_file(self, init_test_db, seed_env: Path) -> None:
        assert seed_env.exists()
        cb, qb, _ = init_test_db

        res = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="c-initial",
            )
        )
        assert res.success
        mat_id = res.data["id"]

        # Browse tree
        tree = await qb.ask(
            GetMaterializationTreeQuery(
                server_id="srv-c-1",
                materialization_id=mat_id,
            )
        )
        assert any(item["path"] == "server.properties" for item in tree["entries"])
        assert any(item["path"] == "config/paper-global.yml" for item in tree["entries"])

        # Browse file - text
        file_res = await qb.ask(
            GetMaterializationFileQuery(
                server_id="srv-c-1",
                materialization_id=mat_id,
                path="server.properties",
            )
        )
        assert file_res["content"] == "difficulty=easy\nmotd=Initial\n"
        assert file_res["encoding"] == "utf-8"

        # Traversal attempt
        from app.core.exceptions import ValidationError
        with pytest.raises(ValidationError, match="Path escapes materialization root"):
            await qb.ask(
                GetMaterializationFileQuery(
                    server_id="srv-c-1",
                    materialization_id=mat_id,
                    path="../escaping.txt",
                )
            )

    async def test_edit_mode_and_file_write(self, init_test_db, seed_env: Path) -> None:
        cb, qb, _ = init_test_db

        res = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="c-initial",
            )
        )
        mat_id = res.data["id"]

        # 1. Write when READONLY -> rejected
        write_fail = await cb.send(
            WriteMaterializedFileCommand(
                server_id="srv-c-1",
                materialization_id=mat_id,
                path="server.properties",
                content="difficulty=peaceful\n",
            )
        )
        assert not write_fail.success
        assert "read-only" in write_fail.error.lower()

        # 2. Switch mode to EDITABLE
        mode_res = await cb.send(
            SetMaterializationEditModeCommand(
                server_id="srv-c-1",
                materialization_id=mat_id,
                enabled=True,
            )
        )
        assert mode_res.success
        assert mode_res.data["mode"] == MaterializationMode.EDITABLE.value

        # 3. Write to PERSISTENT path -> rejected
        write_world = await cb.send(
            WriteMaterializedFileCommand(
                server_id="srv-c-1",
                materialization_id=mat_id,
                path="world/level.dat",
                content="binary data",
            )
        )
        assert not write_world.success
        assert "non-tracked" in write_world.error.lower()

        # 4. Write to TRACKED path -> succeeds
        write_ok = await cb.send(
            WriteMaterializedFileCommand(
                server_id="srv-c-1",
                materialization_id=mat_id,
                path="server.properties",
                content="difficulty=peaceful\n",
            )
        )
        assert write_ok.success

        # Verify on disk
        target = seed_env / res.data["root_path"] / "server.properties"
        assert target.read_text() == "difficulty=peaceful\n"

    async def test_remove_materialization(self, init_test_db, seed_env: Path) -> None:
        cb, qb, _ = init_test_db

        res = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="c-initial",
            )
        )
        mat_id = res.data["id"]
        mat_dir = seed_env / res.data["root_path"]
        assert mat_dir.exists()

        rem_res = await cb.send(
            RemoveMaterializationCommand(
                server_id="srv-c-1",
                materialization_id=mat_id,
            )
        )
        assert rem_res.success
        assert not mat_dir.exists()

        # Check DB status is REMOVED
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            mat = await repo.get_materialization(mat_id)
            assert mat.status == MaterializationStatus.REMOVED

    async def test_scan_live_changes_and_determinism(
        self, init_test_db, seed_env: Path
    ) -> None:
        cb, qb, _ = init_test_db

        # Modify server.properties on live server root
        (seed_env / "server.properties").write_text("difficulty=hard\nmotd=ModifiedLive\n")
        # Add new tracked config file in config/
        (seed_env / "config" / "custom.json").write_text('{"key": "val"}')

        # Query scan
        scan1 = await qb.ask(
            ScanLiveChangesQuery(
                server_id="srv-c-1",
                source="main",
            )
        )
        scan2 = await qb.ask(
            ScanLiveChangesQuery(
                server_id="srv-c-1",
                source="main",
            )
        )

        # Determinism check
        assert scan1 == scan2
        paths_changed = [c["path"] for c in scan1["changes"]]
        assert "server.properties" in paths_changed
        assert "config/custom.json" in paths_changed

        # Fallback: pseudo-source 'server' and empty source resolve to 'main'
        scan_server = await qb.ask(
            ScanLiveChangesQuery(
                server_id="srv-c-1",
                source="server",
            )
        )
        assert scan_server == scan1

        scan_empty = await qb.ask(
            ScanLiveChangesQuery(
                server_id="srv-c-1",
                source="",
            )
        )
        assert scan_empty == scan1

        # Non-existent branch still raises NotFoundError
        from app.core.exceptions import NotFoundError
        with pytest.raises(NotFoundError):
            await qb.ask(
                ScanLiveChangesQuery(
                    server_id="srv-c-1",
                    source="non-existent-branch",
                )
            )

    async def test_scan_live_changes_unversioned_server_returns_empty(
        self, init_test_db, tmp_path: Path
    ) -> None:
        _, qb, _ = init_test_db
        async with database.session_factory() as session:
            unversioned = ServerModel(
                id="srv-unversioned",
                name="UnversionedServer",
                server_type="paper",
                minecraft_version="1.21.1",
                status="STOPPED",
                root_path=str(tmp_path / "empty_dir"),
                deployment_host="127.0.0.1",
                port=25566,
                java_args="-Xmx2G",
            )
            session.add(unversioned)
            await session.commit()

        res = await qb.ask(
            ScanLiveChangesQuery(
                server_id="srv-unversioned",
                source="server",
            )
        )
        assert res == {"changes": [], "auto_commit": None}

    async def test_auto_commit_and_review_lifecycle(
        self, init_test_db, seed_env: Path
    ) -> None:
        from unittest.mock import patch
        cb, qb, _ = init_test_db

        # Modify live server.properties
        (seed_env / "server.properties").write_text("difficulty=normal\n")

        # Auto-commit live changes
        with (
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
        ):
            ac_res = await cb.send(
                AutoCommitLiveChangesCommand(
                    server_id="srv-c-1",
                    branch="main",
                )
            )
        assert ac_res.success
        review_id = ac_res.data["review_id"]
        commit_id = ac_res.data["commit_id"]

        assert review_id is not None
        assert commit_id is not None

        # Branch head should have advanced to new commit
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            branch = await repo.get_branch_by_name("srv-c-1", "main")
            assert branch.head_commit_id == commit_id

        # Confirm review
        conf_res = await cb.send(
            ConfirmImportReviewCommand(
                server_id="srv-c-1",
                review_id=review_id,
            )
        )
        assert conf_res.success
        assert conf_res.data["status"] == ImportReviewStatus.CONFIRMED.value

        # Dismiss on terminal review fails
        dis_fail = await cb.send(
            DismissImportReviewCommand(
                server_id="srv-c-1",
                review_id=review_id,
            )
        )
        assert not dis_fail.success

    async def test_auto_commit_revert_restores_live(
        self, init_test_db, seed_env: Path
    ) -> None:
        from unittest.mock import patch
        cb, qb, _ = init_test_db

        # Modify live server.properties
        (seed_env / "server.properties").write_text("difficulty=extreme\n")

        # Auto-commit
        with (
            patch(
                "app.modules.versioning.infrastructure.storage_probe.StorageCapabilityProbe.assert_supports_reflink"
            ),
            patch(
                "app.modules.versioning.infrastructure.btrfs_zfs_driver.BtrfsZfsSnapshotDriver.create_snapshot",
                return_value=1024,
            ),
        ):
            ac_res = await cb.send(
                AutoCommitLiveChangesCommand(
                    server_id="srv-c-1",
                    branch="main",
                )
            )
            assert ac_res.success
            review_id = ac_res.data["review_id"]

            # Revert review
            rev_res = await cb.send(
                RevertImportReviewCommand(
                    server_id="srv-c-1",
                    review_id=review_id,
                )
            )
        assert rev_res.success
        assert rev_res.data["status"] == ImportReviewStatus.REVERTED.value

        # Check live server.properties has been restored to parent commit content
        assert (seed_env / "server.properties").read_text() == (
            "difficulty=easy\nmotd=Initial\n"
        )

        # Branch head advanced to revert commit
        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            branch = await repo.get_branch_by_name("srv-c-1", "main")
            assert branch.head_commit_id == rev_res.data["revert_commit_id"]

    async def test_cleanup_server_materializations_hook(
        self, init_test_db, seed_env: Path
    ) -> None:
        cb, _, eb = init_test_db

        # Create two materializations
        res1 = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="c-initial",
            )
        )
        res2 = await cb.send(
            CreateMaterializationCommand(
                server_id="srv-c-1",
                revision_type="commit",
                ref="c-initial",
            )
        )
        dir1 = seed_env / res1.data["root"]
        dir2 = seed_env / res2.data["root"]
        assert dir1.exists()
        assert dir2.exists()

        # Run best-effort cleanup hook
        await cleanup_server_materializations("srv-c-1", eb)

        assert not dir1.exists()
        assert not dir2.exists()

        async with database.session_factory() as session:
            repo = SQLVersioningRepository(session)
            mats = await repo.list_materializations("srv-c-1")
            for m in mats:
                assert m.status == MaterializationStatus.REMOVED
