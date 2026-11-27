from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.routers.versioning import _effective_commit_permissions, get_refresh_state
from app.modules.server.domain.value_objects import ServerType
from app.modules.versioning.application.queries.scan_live_changes import (
    ScanLiveChangesHandler,
    ScanLiveChangesQuery,
)
from app.modules.versioning.domain.value_objects import CommitManifest


def test_commit_manifest_normalizes_server_type_enum_and_legacy_string() -> None:
    manifest_enum = CommitManifest(
        server_type=ServerType.PURPUR,  # type: ignore[arg-type]
        minecraft_version="1.21.1",
    )
    assert manifest_enum.to_dict()["server_type"] == "purpur"

    manifest_legacy = CommitManifest.from_dict(
        {"server_type": "ServerType.PURPUR", "minecraft_version": "1.21.1"}
    )
    assert manifest_legacy.server_type == "purpur"
    assert manifest_legacy.to_dict()["server_type"] == "purpur"


def test_effective_commit_permissions_aligns_db_resolved_server_admin() -> None:
    db_server_admin = {
        "user_id": "u-sa",
        "roles": ["server_admin"],
        "permissions": ["server:read", "server:version:read"],
        "db_resolved": True,
    }
    perms = _effective_commit_permissions(db_server_admin)
    assert "server:version:branch:bypass_protection" in perms

    synthetic_without_bypass = {
        "user_id": "u-test",
        "roles": ["server_admin"],
        "permissions": ["server:version:commit"],
        "db_resolved": False,
    }
    assert _effective_commit_permissions(synthetic_without_bypass) == ["server:version:commit"]


@pytest.mark.asyncio
async def test_get_refresh_state_can_confirm_only_when_completed(tmp_path: Path) -> None:
    from app.core.persistence.db import database

    prev_dir = tmp_path / "prev"
    prev_dir.mkdir()

    def _make_journal(phase: str):
        return SimpleNamespace(
            journal_id="j-1",
            server_id="srv-1",
            phase=phase,
            terminal=True,
            target_main_sha="a" * 40,
            previous_main_sha="b" * 40,
            class_c_snapshot_id="snap-1",
            staging_path=None,
            previous_path=str(prev_dir),
            used_exchange=False,
            retention_policy="until_confirm",
            previous_tree_expires_at=None,
            error=None,
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )

    fake_session = AsyncMock()
    fake_session.get = AsyncMock(return_value=None)
    fake_session_ctx = AsyncMock()
    fake_session_ctx.__aenter__.return_value = fake_session
    fake_session_ctx.__aexit__.return_value = False

    fake_server_repo = MagicMock()
    fake_server_repo.get = AsyncMock(return_value=SimpleNamespace(id="srv-1"))

    fake_journal_repo = MagicMock()
    fake_journal_repo.get_active_for_server = AsyncMock(return_value=None)

    with (
        patch.object(database, "_session_factory", return_value=fake_session_ctx),
        patch(
            "app.modules.server.infrastructure.repository.SQLServerRepository",
            return_value=fake_server_repo,
        ),
        patch(
            "app.modules.versioning.infrastructure.refresh_journal.RefreshJournalRepository",
            return_value=fake_journal_repo,
        ),
    ):
        fake_journal_repo.get_latest_for_server = AsyncMock(
            return_value=_make_journal("ROLLED_BACK")
        )
        res_rolled_back = await get_refresh_state("srv-1", {"user_id": "u1"})
        assert res_rolled_back.can_confirm_upgrade is False
        assert res_rolled_back.can_rollback is False

        fake_journal_repo.get_latest_for_server = AsyncMock(
            return_value=_make_journal("COMPLETED")
        )
        res_completed = await get_refresh_state("srv-1", {"user_id": "u1"})
        assert res_completed.can_confirm_upgrade is True
        assert res_completed.can_rollback is True


@pytest.mark.asyncio
async def test_scan_live_changes_native_git_main_empty_and_branch_dirty(tmp_path: Path) -> None:
    worktree = tmp_path / "wt-feat"
    worktree.mkdir()

    fake_runner = MagicMock()
    fake_runner.run.return_value = SimpleNamespace(
        returncode=0,
        stdout=" M server.properties\n?? config/new.yml\n D old.yml\n",
    )

    fake_service = MagicMock()
    fake_service.get_branch.return_value = SimpleNamespace(
        name="feat-1",
        sha="a" * 40,
        worktree_path=worktree,
        worktree_locked=False,
    )
    fake_service.open_runner.return_value = fake_runner

    fake_ctx = SimpleNamespace(layout=MagicMock(), server_root=tmp_path, service=fake_service)

    server_repo = MagicMock()
    server_repo.get = AsyncMock(return_value=SimpleNamespace(id="srv-git"))
    versioning_repo = MagicMock()

    handler = ScanLiveChangesHandler(server_repo=server_repo, versioning_repo=versioning_repo)

    with patch(
        "app.modules.versioning.application.git_branch_adapter.git_branch_context",
        return_value=fake_ctx,
    ):
        main_res = await handler.handle(ScanLiveChangesQuery(server_id="srv-git", source="main"))
        assert main_res == {"changes": [], "auto_commit": None}

        feat_res = await handler.handle(
            ScanLiveChangesQuery(server_id="srv-git", source="feat-1")
        )
        assert feat_res["changes"] == [
            {"path": "config/new.yml", "change": "added", "classification": "tracked"},
            {"path": "old.yml", "change": "removed", "classification": "tracked"},
            {"path": "server.properties", "change": "modified", "classification": "tracked"},
        ]
