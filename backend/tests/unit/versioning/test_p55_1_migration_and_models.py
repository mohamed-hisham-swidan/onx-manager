"""P5.5-1 migration b1e2100000031, ORM models, and exception taxonomy."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command as alembic_command
from app.core.exceptions import (
    ConflictError,
    CurseForgeApiKeyMissingError,
    HealthGateFailedError,
    HostileExecutableError,
    LecMissingError,
    ManualDownloadRequiredError,
    ModpackFormatError,
    UnsupportedForgeVersionError,
    UntrustedDownloadHostError,
    UpgradeBlockerError,
    ValidationError,
)
from app.core.persistence.base import Base
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.operations.domain.enums import OperationType
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.infrastructure.models import (
    LoaderEnvCacheEntryModel,
    PanelIntegrationSecretModel,
    ServerUpgradeModel,
)

PRIOR_HEAD = "b1e2100000030"
P55_REVISION = "b1e2100000031"

SERVER_NEW_COLUMNS = {
    "health_gate_boot_timeout_seconds": False,
    "install_optional_server_files": False,
    "allow_experimental_paper_builds": False,
    "download_host_allowlist_json": True,
}

SERVER_UPGRADE_COLUMNS = {
    "id": False,
    "server_id": False,
    "kind": False,
    "mode": False,
    "status": False,
    "source_mc": True,
    "target_mc": False,
    "source_loader_id": True,
    "source_loader_version": True,
    "target_loader_id": False,
    "target_loader_version": False,
    "target_lec_key": True,
    "upgrade_branch": True,
    "operation_id": True,
    "journal_id": True,
    "previous_main_sha": True,
    "target_main_sha": True,
    "pre_upgrade_backup_id": True,
    "class_c_snapshot_id": True,
    "data_template_id": True,
    "plan_json": True,
    "matrix_json": True,
    "manual_blockers_json": True,
    "pinned_until_confirm": False,
    "health_gate_passed": False,
    "error_code": True,
    "error_message": True,
    "confirmed_at": True,
    "rolled_back_at": True,
    "created_at": False,
    "updated_at": False,
}

LEC_COLUMNS = {
    "lec_key": False,
    "loader_id": False,
    "mc_version": False,
    "loader_version": False,
    "installer_version": True,
    "java_major": True,
    "status": False,
    "size_bytes": False,
    "file_count": False,
    "complete_manifest_sha256": True,
    "created_at": False,
    "last_used_at": False,
    "updated_at": False,
}

PANEL_SECRET_COLUMNS = {
    "integration_key": False,
    "encryption_mode": False,
    "wrapped_dek": False,
    "kek_version": False,
    "nonce": False,
    "ciphertext": False,
    "key_hint": True,
    "created_at": False,
    "updated_at": False,
}


def _sync_url(db_url: str) -> str:
    return db_url.replace("+aiosqlite", "")


def _tables(db_url: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _columns(db_url: str, table: str) -> dict[str, dict]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {c["name"]: c for c in inspect(engine).get_columns(table)}
    finally:
        engine.dispose()


def _indexes(db_url: str, table: str) -> set[str]:
    engine = create_engine(_sync_url(db_url))
    try:
        return {ix["name"] for ix in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _column_default(column: dict) -> str | None:
    raw = column.get("server_default")
    if raw is None:
        raw = column.get("default")
    if raw is None:
        return None
    return str(raw).strip("'\"")


def _create_sqlite_engine(db_file: Path):
    return create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )


@pytest.mark.no_isolated_db
def test_p55_migration_upgrade_columns_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p55-schema.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message

    cfg = reconciler.get_alembic_config()
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD] == [RELEASE_MINIMUM_DB_REVISION]
    assert script.get_revision(P55_REVISION) is not None
    assert script.get_revision(P55_REVISION).down_revision == PRIOR_HEAD

    tables = _tables(db_url)
    assert {"server_upgrades", "loader_env_cache_entries", "panel_integration_secrets"} <= tables

    server_columns = _columns(db_url, "servers")
    for name, nullable in SERVER_NEW_COLUMNS.items():
        assert name in server_columns
        assert bool(server_columns[name]["nullable"]) is nullable
    assert _column_default(server_columns["health_gate_boot_timeout_seconds"]) == "300"
    assert _column_default(server_columns["install_optional_server_files"]) == "1"
    assert _column_default(server_columns["allow_experimental_paper_builds"]) == "0"

    upgrade_columns = _columns(db_url, "server_upgrades")
    for name, nullable in SERVER_UPGRADE_COLUMNS.items():
        assert name in upgrade_columns, name
        assert bool(upgrade_columns[name]["nullable"]) is nullable, name
    assert _column_default(upgrade_columns["kind"]) == "server_upgrade"
    assert _column_default(upgrade_columns["mode"]) == "simple"
    assert _column_default(upgrade_columns["status"]) == "planned"
    assert _column_default(upgrade_columns["pinned_until_confirm"]) == "0"
    assert _column_default(upgrade_columns["health_gate_passed"]) == "0"
    assert _indexes(db_url, "server_upgrades") == {
        "ix_server_upgrades_server_id",
        "ix_server_upgrades_server_status",
        "ix_server_upgrades_server_created",
    }

    lec_columns = _columns(db_url, "loader_env_cache_entries")
    for name, nullable in LEC_COLUMNS.items():
        assert name in lec_columns, name
        assert bool(lec_columns[name]["nullable"]) is nullable, name
    assert _column_default(lec_columns["status"]) == "ready"
    assert _column_default(lec_columns["size_bytes"]) == "0"
    assert _column_default(lec_columns["file_count"]) == "0"
    assert _indexes(db_url, "loader_env_cache_entries") == {
        "ix_loader_env_cache_entries_loader_mc",
        "ix_loader_env_cache_entries_last_used",
    }

    secret_columns = _columns(db_url, "panel_integration_secrets")
    for name, nullable in PANEL_SECRET_COLUMNS.items():
        assert name in secret_columns, name
        assert bool(secret_columns[name]["nullable"]) is nullable, name
    assert _column_default(secret_columns["encryption_mode"]) == "master_kek_v1"
    assert _column_default(secret_columns["kek_version"]) == "1"

    alembic_command.downgrade(cfg, PRIOR_HEAD)
    remaining = _tables(db_url)
    assert "server_upgrades" not in remaining
    assert "loader_env_cache_entries" not in remaining
    assert "panel_integration_secrets" not in remaining
    downgraded_server_columns = _columns(db_url, "servers")
    for name in SERVER_NEW_COLUMNS:
        assert name not in downgraded_server_columns

    alembic_command.upgrade(cfg, P55_REVISION)
    recreated = _tables(db_url)
    assert "server_upgrades" in recreated
    assert "loader_env_cache_entries" in recreated
    assert "panel_integration_secrets" in recreated
    assert set(SERVER_NEW_COLUMNS) <= set(_columns(db_url, "servers"))


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_p55_orm_roundtrip(tmp_path: Path) -> None:
    engine = _create_sqlite_engine(tmp_path / "p55-orm.db")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

        async with factory() as session:
            session.add(
                ServerModel(
                    id="srv-1",
                    name="srv-1",
                    minecraft_version="1.20.1",
                    server_type="paper",
                )
            )
            await session.commit()

        async with factory() as session:
            server = await session.get(ServerModel, "srv-1")
            assert server is not None
            assert server.health_gate_boot_timeout_seconds == 300
            assert server.install_optional_server_files is True
            assert server.allow_experimental_paper_builds is False
            assert server.download_host_allowlist_json is None

            session.add(
                ServerUpgradeModel(
                    id="up-1",
                    server_id="srv-1",
                    target_mc="1.21.4",
                    target_loader_id="fabric",
                    target_loader_version="0.15.11",
                )
            )
            session.add(
                LoaderEnvCacheEntryModel(
                    lec_key="fabric/1.21.4/0.15.11/1.0.1",
                    loader_id="fabric",
                    mc_version="1.21.4",
                    loader_version="0.15.11",
                )
            )
            session.add(
                PanelIntegrationSecretModel(
                    integration_key="curseforge_api_key",
                    encryption_mode="panel_local_key_v1",
                    wrapped_dek=b"\x01" * 60,
                    kek_version=1,
                    nonce=b"\x02" * 12,
                    ciphertext=b"\x03" * 32,
                    key_hint="***...abcd",
                )
            )
            await session.commit()

        async with factory() as session:
            upgrade = await session.get(ServerUpgradeModel, "up-1")
            assert upgrade is not None
            assert upgrade.kind == "server_upgrade"
            assert upgrade.mode == "simple"
            assert upgrade.status == "planned"
            assert upgrade.pinned_until_confirm is False
            assert upgrade.health_gate_passed is False

            lec = await session.get(
                LoaderEnvCacheEntryModel, "fabric/1.21.4/0.15.11/1.0.1"
            )
            assert lec is not None
            assert lec.status == "ready"
            assert lec.size_bytes == 0
            assert lec.file_count == 0

            secret = await session.get(
                PanelIntegrationSecretModel, "curseforge_api_key"
            )
            assert secret is not None
            assert secret.encryption_mode == "panel_local_key_v1"
            assert secret.wrapped_dek == b"\x01" * 60
            assert secret.nonce == b"\x02" * 12
            assert secret.key_hint == "***...abcd"
    finally:
        await engine.dispose()


def test_p55_operation_types() -> None:
    assert OperationType.MODPACK_INSTALL.value == "MODPACK_INSTALL"
    assert OperationType.SERVER_UPGRADE.value == "SERVER_UPGRADE"


def test_p55_exception_taxonomy() -> None:
    forge = UnsupportedForgeVersionError(minecraft_version="1.20.2")
    assert isinstance(forge, ValidationError)
    assert forge.code == "UNSUPPORTED_FORGE_VERSION"
    assert forge.http_status == 422
    assert forge.details["supported_min"] == "1.17.1"
    assert forge.details["supported_max"] == "1.20.1"

    cf = CurseForgeApiKeyMissingError()
    assert isinstance(cf, ConflictError)
    assert cf.code == "CURSEFORGE_API_KEY_MISSING"
    assert cf.http_status == 409
    assert cf.http_status != 401

    hostile = HostileExecutableError(path="x" * 500)
    assert hostile.code == "HOSTILE_EXECUTABLE_REJECTED"
    assert hostile.http_status == 422
    assert hostile.path == "x" * 128
    assert len(hostile.details["path"]) == 128

    untrusted = UntrustedDownloadHostError(
        host="evil.example.com", reason="host_not_in_allowlist"
    )
    assert untrusted.code == "UNTRUSTED_DOWNLOAD_HOST"
    assert untrusted.http_status == 422
    assert untrusted.host == "evil.example.com"
    assert untrusted.reason == "host_not_in_allowlist"

    manual = ManualDownloadRequiredError(
        filename="f" * 200,
        webpage_url="https://example.com/" + "u" * 400,
        expected_size=10,
        expected_sha1="a" * 40,
        expected_sha512="b" * 128,
        project_id=1,
        file_id=2,
    )
    assert manual.code == "MANUAL_DOWNLOAD_REQUIRED"
    assert manual.http_status == 409
    assert len(manual.details["filename"]) == 128
    assert len(manual.details["webpage_url"]) == 256

    blocker = UpgradeBlockerError(blockers=[{"kind": "dependency"}])
    assert blocker.code == "UPGRADE_BLOCKED"
    assert blocker.http_status == 409
    assert blocker.blockers == [{"kind": "dependency"}]

    lec = LecMissingError(lec_key="paper/1.21.4/123")
    assert lec.code == "LEC_MISSING"
    assert lec.http_status == 409
    assert lec.lec_key == "paper/1.21.4/123"

    gate = HealthGateFailedError(step="boot", reason="timeout", rolled_back=True)
    assert gate.code == "HEALTH_GATE_FAILED"
    assert gate.http_status == 502
    assert gate.retryable is False
    assert gate.details["rolled_back"] is True

    fmt = ModpackFormatError("bad pack", field="formatVersion")
    assert fmt.code == "MODPACK_FORMAT_INVALID"
    assert fmt.http_status == 422
