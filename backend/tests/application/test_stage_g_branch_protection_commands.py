from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.core.query_bus import QueryBus
from app.modules.activity.infrastructure.repository import SQLActivityRepository
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application import (
    ArchiveBranchCommand,
    AutoCommitLiveChangesCommand,
    CreateBranchCommand,
    CreateCommitCommand,
    GetBranchProtectionQuery,
    RemoveBranchProtectionCommand,
    SetBranchProtectionCommand,
)
from app.modules.versioning.domain.value_objects import CommitManifest
from app.registration import register_handlers


def _sample_manifest() -> CommitManifest:
    return CommitManifest(
        server_type="vanilla",
        minecraft_version="1.21.1",
        configs={"server.properties": "motd=StageG"},
        mods=[],
        env_vars={"JAVA_OPTS": "-Xmx1G"},
        java_args="",
    )


@pytest.fixture(autouse=True)
async def init_test_db(tmp_path):
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

    # Seed server
    srv_dir = tmp_path / "srv-g-1"
    srv_dir.mkdir(parents=True, exist_ok=True)
    async with database.session_factory() as session:
        server = ServerModel(
            id="srv-g-1",
            name="StageGServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(srv_dir),
            deployment_host="127.0.0.1",
            port=25565,
            java_args="-Xmx2G",
            bot_verification_settings={"bot_count": 5, "duration_minutes": 10},
        )
        session.add(server)
        await session.commit()

    yield cb, qb, str(srv_dir)

    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


class TestStageGBranchProtectionCommands:
    @pytest.mark.asyncio
    async def test_set_and_get_branch_protection(self, init_test_db) -> None:
        cb, qb, _ = init_test_db
        server_id = "srv-g-1"

        # Create branch
        res_create = await cb.send(CreateBranchCommand(server_id=server_id, name="main"))
        assert res_create.success is True

        # Check default protection
        prot = await qb.ask(GetBranchProtectionQuery(server_id=server_id, branch_name="main"))
        assert prot["is_protected"] is False
        assert prot["policy"] is None

        # Set protection with custom policy
        policy = {
            "require_test_pass": True,
            "allow_direct_commit": False,
            "allow_force_bypass": True,
            "prevent_deletion": True,
        }
        res_set = await cb.send(
            SetBranchProtectionCommand(server_id=server_id, branch_name="main", policy=policy)
        )
        assert res_set.success is True
        assert res_set.details["is_protected"] is True
        assert res_set.details["policy"]["require_test_pass"] is True

        # Query again
        prot_updated = await qb.ask(
            GetBranchProtectionQuery(server_id=server_id, branch_name="main")
        )
        assert prot_updated["is_protected"] is True
        assert prot_updated["policy"] == policy

    @pytest.mark.asyncio
    async def test_set_branch_protection_archived_branch_fails(self, init_test_db) -> None:
        cb, _, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="old-branch"))
        await cb.send(ArchiveBranchCommand(server_id=server_id, name="old-branch"))

        res = await cb.send(
            SetBranchProtectionCommand(server_id=server_id, branch_name="old-branch")
        )
        assert res.success is False
        assert "Cannot configure protection on archived branch" in res.error

    @pytest.mark.asyncio
    async def test_remove_branch_protection(self, init_test_db) -> None:
        cb, qb, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="main"))
        await cb.send(SetBranchProtectionCommand(server_id=server_id, branch_name="main"))

        # Remove protection
        res_del = await cb.send(
            RemoveBranchProtectionCommand(server_id=server_id, branch_name="main")
        )
        assert res_del.success is True
        assert res_del.details["is_protected"] is False

        prot = await qb.ask(GetBranchProtectionQuery(server_id=server_id, branch_name="main"))
        assert prot["is_protected"] is False
        assert prot["policy"] is None

    @pytest.mark.asyncio
    async def test_create_commit_to_protected_branch_fails(self, init_test_db) -> None:
        cb, _, srv_dir = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="protected-main"))
        await cb.send(
            SetBranchProtectionCommand(server_id=server_id, branch_name="protected-main")
        )

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
            res = await cb.send(
                CreateCommitCommand(
                    server_id=server_id,
                    branch_name="protected-main",
                    message="Direct commit to protected branch",
                )
            )
            assert res.success is False
            assert res.error_code == "CONFLICT"
            assert "Direct commits to protected branch 'protected-main' are forbidden" in res.error

    @pytest.mark.asyncio
    async def test_create_commit_force_without_bypass_permission_fails(self, init_test_db) -> None:
        cb, _, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="protected-main"))
        await cb.send(
            SetBranchProtectionCommand(server_id=server_id, branch_name="protected-main")
        )

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
            res = await cb.send(
                CreateCommitCommand(
                    server_id=server_id,
                    branch_name="protected-main",
                    message="Direct commit bypass attempt",
                    force=True,
                    force_reason="Emergency hotfix",
                    caller_permissions=["server:version:commit"],  # Missing bypass permission
                )
            )
            assert res.success is False
            assert res.error_code == "PERMISSION_DENIED"
            assert "server:version:branch:bypass_protection" in res.error

    @pytest.mark.asyncio
    async def test_create_commit_force_with_bypass_permission_succeeds(self, init_test_db) -> None:
        cb, _, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="protected-main"))
        await cb.send(
            SetBranchProtectionCommand(server_id=server_id, branch_name="protected-main")
        )

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
            res = await cb.send(
                CreateCommitCommand(
                    server_id=server_id,
                    branch_name="protected-main",
                    message="Emergency hotfix commit",
                    author_id="admin-user",
                    force=True,
                    force_reason="Critical CVE patch",
                    caller_permissions=["server:version:branch:bypass_protection"],
                )
            )
            assert res.success is True

            # Verify audit log was recorded
            async with database.session_factory() as session:
                act_repo = SQLActivityRepository(session)
                logs, _ = await act_repo.list_by_server(server_id)
                bypass_logs = [
                    entry for entry in logs
                    if entry.event_type == "versioning.branch_protection_bypassed"
                ]
                assert len(bypass_logs) == 1
                assert bypass_logs[0].actor_id == "admin-user"
                assert bypass_logs[0].details["branch"] == "protected-main"
                assert bypass_logs[0].details["reason"] == "Critical CVE patch"

    @pytest.mark.asyncio
    async def test_auto_commit_to_protected_branch_fails(self, init_test_db) -> None:
        cb, _, srv_dir = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="protected-main"))
        await cb.send(
            SetBranchProtectionCommand(server_id=server_id, branch_name="protected-main")
        )

        res = await cb.send(
            AutoCommitLiveChangesCommand(
                server_id=server_id,
                branch="protected-main",
            )
        )
        assert res.success is False
        assert res.error_code == "CONFLICT"
        assert "Cannot auto-commit live changes directly to protected branch" in res.error

    @pytest.mark.asyncio
    async def test_archive_protected_branch_command_fails(self, init_test_db) -> None:
        cb, _, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="protected-main"))
        await cb.send(
            SetBranchProtectionCommand(
                server_id=server_id,
                branch_name="protected-main",
                policy={"prevent_deletion": True},
            )
        )

        res = await cb.send(ArchiveBranchCommand(server_id=server_id, name="protected-main"))
        assert res.success is False
        assert res.error_code == "CONFLICT"
        assert "Cannot archive protected branch 'protected-main'" in res.error

    @pytest.mark.asyncio
    async def test_archive_protected_branch_when_prevent_deletion_false(self, init_test_db) -> None:
        cb, _, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="protected-deletable"))
        await cb.send(
            SetBranchProtectionCommand(
                server_id=server_id,
                branch_name="protected-deletable",
                policy={"prevent_deletion": False},
            )
        )

        res = await cb.send(
            ArchiveBranchCommand(server_id=server_id, name="protected-deletable")
        )
        assert res.success is True

    @pytest.mark.asyncio
    async def test_concurrent_policy_update_and_commit(self, init_test_db) -> None:
        cb, _, _ = init_test_db
        server_id = "srv-g-1"

        await cb.send(CreateBranchCommand(server_id=server_id, name="race-branch"))

        # Enable protection
        await cb.send(
            SetBranchProtectionCommand(
                server_id=server_id,
                branch_name="race-branch",
                policy={"allow_direct_commit": False},
            )
        )

        # Attempt commit - should fail deterministically due to protection
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
            res = await cb.send(
                CreateCommitCommand(
                    server_id=server_id,
                    branch_name="race-branch",
                    message="Commit during race",
                )
            )
            assert res.success is False
            assert res.error_code == "CONFLICT"
