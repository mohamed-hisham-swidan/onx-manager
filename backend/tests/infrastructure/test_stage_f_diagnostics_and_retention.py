"""Stage F Diagnostics, Crash Correlation, and Artifact Retention Test Suite.

Verifies:
- Container diagnostics and PatternCrashAnalyzer integration
- EvidenceBundle schema §(e) conformity
- Lazy artifact retention and pruning via PruneTestArtifactsCommand / reap_stale_reservations
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.event_bus import EventBus
from app.core.persistence.base import Base
from app.core.persistence.db import database
from app.modules.health.infrastructure.crash_analyzer import PatternCrashAnalyzer
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.commands.prune_test_artifacts import (
    PruneTestArtifactsHandler,
)
from app.modules.versioning.application.scheduling.admission import (
    reap_stale_reservations,
)
from app.modules.versioning.domain.entities import ServerTestRun
from app.modules.versioning.domain.events import TestRunFailedEvent
from app.modules.versioning.domain.value_objects import (
    PlacementMode,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.models import ServerTestRunModel
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe
from app.modules.versioning.infrastructure.test_runner import (
    DockerTestExecutionRunner,
    TestSpec,
)


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

    yield
    database._engine = old_engine
    database._session_factory = old_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_pattern_crash_analyzer_correlation() -> None:
    analyzer = PatternCrashAnalyzer()
    crash_content = (
        "---- Minecraft Crash Report ----\n"
        "Time: 2026-09-18 10:00:00\n"
        "Description: Exception in server tick loop\n"
        "net.minecraftforge.fml.ModLoadingException: Mod supermod encountered an error\n"
    )
    analysis = analyzer.analyze_crash_content(crash_content)
    assert analysis.blamed_mod == "supermod"
    assert analysis.failure_code.value == "MOD_CRASH"

    event = TestRunFailedEvent(
        server_id="srv-diag",
        test_id="tr-diag-1",
        commit_id="c-diag-1",
        failure_code="SERVER_CRASH",
        blamed_mod="supermod",
    )
    assert event.server_id == "srv-diag"
    assert event.blamed_mod == "supermod"


@pytest.mark.asyncio
async def test_evidence_bundle_generation(tmp_path: Path) -> None:
    from app.modules.versioning.domain.entities import ServerCommit
    from app.modules.versioning.domain.value_objects import (
        BotTech,
        BotVerificationConfig,
        CommitManifest,
    )

    srv_id = "srv-ev-1"
    test_id = "tr-ev-100"
    srv_dir = tmp_path / "server"
    srv_dir.mkdir(parents=True, exist_ok=True)

    eb = EventBus()
    runner = DockerTestExecutionRunner(event_bus=eb)

    async with database.session_factory() as session:
        server = ServerModel(
            id=srv_id,
            name="EvServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(srv_dir),
            deployment_host="127.0.0.1",
            port=25565,
        )
        session.add(server)

        repo = SQLVersioningRepository(session)
        init_run = ServerTestRun(
            id=test_id,
            server_id=srv_id,
            commit_id="c-ev-1",
            status=TestRunStatus.RUNNING,
        )
        await repo.save_test_run(init_run)
        await session.commit()

    manifest = CommitManifest(
        server_type="vanilla",
        minecraft_version="1.21.1",
    )
    commit = ServerCommit(
        id="c-ev-1",
        server_id=srv_id,
        message="evidence test commit",
        manifest=manifest,
    )
    bot_cfg = BotVerificationConfig(
        bot_count=2,
        duration_minutes=1,
        bot_tech=BotTech.FAKEPLAYER_NEXT,
        placement_mode=PlacementMode.SIDECAR,
    )
    test_spec = TestSpec(
        test_id=test_id,
        server_id=srv_id,
        commit=commit,
        server_dir=str(srv_dir),
        bot_config=bot_cfg,
    )

    test_dir_path = srv_dir / ".onx" / "tests" / test_id
    logs_dir = test_dir_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / "latest.log").write_text(
        "[12:00:10] [Server thread/INFO]: Done (5.12s)! For help, type 'help'\n",
        encoding="utf-8",
    )

    from app.modules.versioning.infrastructure.resource_probe import ResourcePreflightProbe

    def fake_run(cmd, **_kwargs):
        from unittest.mock import MagicMock

        cmd_str = " ".join(str(c) for c in cmd)
        if "inspect" in cmd_str and "State.Running" in cmd_str:
            return MagicMock(returncode=0, stdout="true\n", stderr="")
        if "inspect" in cmd_str and "State.ExitCode" in cmd_str:
            return MagicMock(returncode=0, stdout="0\n", stderr="")
        if "inspect" in cmd_str and "State.OOMKilled" in cmd_str:
            return MagicMock(returncode=0, stdout="false\n", stderr="")
        if "inspect" in cmd_str and "IPAddress" in cmd_str:
            return MagicMock(returncode=0, stdout="172.17.0.2\n", stderr="")
        return MagicMock(returncode=0, stdout="container-id\n", stderr="")

    with (
        patch.object(StorageCapabilityProbe, "assert_supports_reflink", return_value=None),
        patch.object(ResourcePreflightProbe, "assert_sufficient_resources", return_value=None),
        patch("subprocess.run", side_effect=fake_run),
        patch("asyncio.sleep", new=AsyncMock()),
        patch.object(runner, "cleanup_test", new=AsyncMock()),
    ):
        handle = await runner.run_test(test_spec)
        fut = runner._active_runs[handle.test_id]._completion_future
        await fut

    assert handle.status == TestRunStatus.PASSED
    assert handle.runtime_id is not None
    # Query persisted test run to verify evidence bundle
    async with database.session_factory() as session:
        db_run = await session.get(ServerTestRunModel, test_id)
        assert db_run is not None
        assert db_run.runtime_id == handle.runtime_id
        assert db_run.evidence_bundle is not None
        bundle = db_run.evidence_bundle
        assert bundle["runtime"]["exit_code"] == 0
        assert bundle["runtime"]["container_name"] == handle.container_name
        assert bundle["assertions"]["clean_shutdown"] is True
        assert "log_tail" in bundle

        from app.modules.versioning.infrastructure.models import ServerRuntimeModel

        async with database.session_factory() as session:
            db_rt = await session.get(ServerRuntimeModel, handle.runtime_id)
            assert db_rt is not None
            assert db_rt.status == "terminated"


@pytest.mark.asyncio
async def test_lazy_artifact_pruning(tmp_path: Path, monkeypatch) -> None:
    srv_id = "srv-prune"
    servers_dir = tmp_path / "servers"
    servers_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ONX_SERVERS_DATA_DIR", str(servers_dir))
    # Create directories for:
    # 1. Fresh failed run (< 24h old) -> MUST BE RETAINED
    # 2. Expired failed run (> 24h old) -> MUST BE PRUNED
    fresh_test_dir = servers_dir / srv_id / ".onx" / "tests" / "tr-fresh"
    fresh_test_dir.mkdir(parents=True, exist_ok=True)
    (fresh_test_dir / "crash.log").write_text("fresh crash details")

    expired_test_dir = servers_dir / srv_id / ".onx" / "tests" / "tr-expired"
    expired_test_dir.mkdir(parents=True, exist_ok=True)
    (expired_test_dir / "crash.log").write_text("old crash details")

    now = datetime.now(UTC)

    async with database.session_factory() as session:
        server = ServerModel(
            id=srv_id,
            name="PruneServer",
            server_type="vanilla",
            minecraft_version="1.21.1",
            status="STOPPED",
            root_path=str(servers_dir / srv_id),
            deployment_host="127.0.0.1",
            port=25565,
        )
        session.add(server)

        repo = SQLVersioningRepository(session)
        # Fresh run (1 hour ago)
        run_fresh = ServerTestRun(
            id="tr-fresh",
            server_id=srv_id,
            commit_id="c-fresh",
            status=TestRunStatus.FAILED,
            failure_reason="SERVER_CRASH",
            created_at=now - timedelta(hours=1),
            artifacts_purged=False,
        )
        await repo.save_test_run(run_fresh)

        # Expired run (30 hours ago)
        run_expired = ServerTestRun(
            id="tr-expired",
            server_id=srv_id,
            commit_id="c-expired",
            status=TestRunStatus.FAILED,
            failure_reason="SERVER_CRASH",
            created_at=now - timedelta(hours=30),
            artifacts_purged=False,
        )
        await repo.save_test_run(run_expired)
        await session.commit()

    # Run lazy pruning
    async with database.session_factory() as session:
        result = await PruneTestArtifactsHandler.execute_pruning(
            session=session,
            server_id=srv_id,
            retention_hours=24,
            now=now,
        )
        await session.commit()

    assert result.success is True
    assert result.details["pruned_count"] == 1

    # Verify filesystem state
    assert fresh_test_dir.exists(), "Fresh run artifacts must be retained"
    assert not expired_test_dir.exists(), "Expired run artifacts must be removed"

    # Verify DB artifacts_purged flag
    async with database.session_factory() as session:
        m_fresh = await session.get(ServerTestRunModel, "tr-fresh")
        m_expired = await session.get(ServerTestRunModel, "tr-expired")
        assert m_fresh.artifacts_purged is False
        assert m_expired.artifacts_purged is True

    # Verify reap_stale_reservations invocation also prunes
    async with database.session_factory() as session:
        await reap_stale_reservations(session)
