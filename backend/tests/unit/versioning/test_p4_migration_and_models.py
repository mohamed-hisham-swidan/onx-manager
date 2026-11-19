"""P4-1 Alembic b1e2100000029 schema + models + repository round-trip tests."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command as alembic_command
from app.core.persistence.base import Base
from app.core.persistence.db_revision import (
    EXPECTED_ALEMBIC_HEAD,
    RELEASE_MINIMUM_DB_REVISION,
)
from app.core.persistence.reconciler import DatabaseReconciler, ReconcileStatus
from app.modules.activity.infrastructure.models import ServerActivityLogModel
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.domain.entities import (
    Runtime,
    ServerBranch,
    ServerTestRun,
)
from app.modules.versioning.domain.value_objects import (
    BranchStatus,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import (
    ServerBranchModel,
    ServerDataTemplateModel,
    ServerRuntimeModel,
    ServerTestRunModel,
)
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

PRIOR_HEAD = "b1e2100000028"
P4_REVISION = "b1e2100000029"


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


def _create_sqlite_engine(db_file: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )
    return engine


@pytest.mark.no_isolated_db
def test_p4_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'p4-schema.db'}"
    reconciler = DatabaseReconciler(db_url=db_url)
    result = reconciler.reconcile(auto_upgrade=True)
    assert result.status == ReconcileStatus.RECONCILED, result.message
    cfg = reconciler.get_alembic_config()

    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [EXPECTED_ALEMBIC_HEAD]
    assert script.get_revision(P4_REVISION).down_revision == PRIOR_HEAD
    assert RELEASE_MINIMUM_DB_REVISION == EXPECTED_ALEMBIC_HEAD

    assert "server_data_templates" in _tables(db_url)

    template_cols = _columns(db_url, "server_data_templates")
    assert {
        "id",
        "server_id",
        "name",
        "description",
        "source_branch_name",
        "source_commit_sha",
        "storage_path",
        "file_count",
        "total_bytes",
        "status",
        "operation_id",
        "created_at",
        "updated_at",
    } <= set(template_cols)

    branch_cols = _columns(db_url, "server_branches")
    for c in (
        "port_set_json",
        "runtime_status",
        "active_runtime_id",
        "active_commit_sha",
        "active_data_template_id",
    ):
        assert c in branch_cols

    runtime_cols = _columns(db_url, "server_runtimes")
    for c in (
        "branch_name",
        "data_template_id",
        "port_set_json",
        "allow_public_test_join",
        "export_path",
    ):
        assert c in runtime_cols
    assert "ix_server_runtimes_server_branch" in _indexes(db_url, "server_runtimes")

    test_run_cols = _columns(db_url, "server_test_runs")
    for c in ("branch_name", "data_template_id", "port_set_json"):
        assert c in test_run_cols

    server_cols = _columns(db_url, "servers")
    assert "rcon_save_off_active" in server_cols
    assert "max_concurrent_branch_runs" in server_cols

    activity_cols = _columns(db_url, "server_activity_logs")
    assert "branch_name" in activity_cols
    assert "ix_activity_server_branch_timestamp" in _indexes(db_url, "server_activity_logs")

    # downgrade
    alembic_command.downgrade(cfg, PRIOR_HEAD)
    remaining = _tables(db_url)
    assert "server_data_templates" not in remaining

    alembic_command.upgrade(cfg, P4_REVISION)
    assert "server_data_templates" in _tables(db_url)


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_p4_repository_roundtrip(tmp_path: Path) -> None:
    db_file = tmp_path / "p4-repo.db"
    engine = _create_sqlite_engine(db_file)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        branch_id = f"branch-{uuid.uuid4().hex[:8]}"
        server_id = "server-1"
        runtime_id = f"rt-{uuid.uuid4().hex[:8]}"
        run_id = f"run-{uuid.uuid4().hex[:8]}"

        port_set = {"game_port": 25601, "rcon_port": 25602}

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id=server_id,
                name="main",
                head_commit_id="commit-1",
                status=BranchStatus.ACTIVE,
                port_set=port_set,
                runtime_status="running",
                active_runtime_id=runtime_id,
                active_commit_sha="commit-1",
                active_data_template_id="tmpl-1",
            )
            await repo.save_branch(branch)
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            loaded = await repo.get_branch(branch_id)
            assert loaded is not None
            assert loaded.port_set == port_set
            assert loaded.runtime_status == "running"
            assert loaded.active_runtime_id == runtime_id
            assert loaded.active_commit_sha == "commit-1"
            assert loaded.active_data_template_id == "tmpl-1"

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            runtime = Runtime(
                id=runtime_id,
                server_id=server_id,
                commit_id="commit-1",
                branch_name="main",
                data_template_id="tmpl-1",
                port_set=port_set,
                allow_public_test_join=True,
                export_path="/tmp/export",
            )
            await repo.save_runtime(runtime)
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            loaded_rt = await repo.get_runtime(runtime_id)
            assert loaded_rt is not None
            assert loaded_rt.branch_name == "main"
            assert loaded_rt.data_template_id == "tmpl-1"
            assert loaded_rt.port_set == port_set
            assert loaded_rt.allow_public_test_join is True
            assert loaded_rt.export_path == "/tmp/export"

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            run = ServerTestRun(
                id=run_id,
                server_id=server_id,
                commit_id="commit-1",
                status=TestRunStatus.PENDING,
                branch_name="main",
                data_template_id="tmpl-1",
                port_set=port_set,
            )
            await repo.save_test_run(run)
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            loaded_run = await repo.get_test_run(run_id)
            assert loaded_run is not None
            assert loaded_run.branch_name == "main"
            assert loaded_run.data_template_id == "tmpl-1"
            assert loaded_run.port_set == port_set
    finally:
        await engine.dispose()


@pytest.mark.no_isolated_db
def test_p4_models_columns_present() -> None:
    # Ensure ORM models define expected columns
    assert "rcon_save_off_active" in ServerModel.__table__.columns
    assert "max_concurrent_branch_runs" in ServerModel.__table__.columns
    assert "branch_name" in ServerActivityLogModel.__table__.columns
    assert "port_set_json" in ServerBranchModel.__table__.columns
    assert "branch_name" in ServerRuntimeModel.__table__.columns
    assert "port_set_json" in ServerTestRunModel.__table__.columns
    assert ServerDataTemplateModel.__tablename__ == "server_data_templates"
