"""Stage D admission-gate tests (global cap + stored RAM/core earmarks).

Uses file-backed SQLite databases (tmp_path) so the BEGIN IMMEDIATE
serialization and cross-connection earmark visibility match the production
file-DB behavior. The Postgres-family SELECT ... FOR UPDATE branch is covered
by a mocked-dialect unit test (CI runs SQLite only — no silent pretending).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401 (FK metadata)
import app.modules.server.infrastructure.models  # noqa: F401 (FK metadata)
import app.modules.versioning.infrastructure.models  # noqa: F401
from app.core.exceptions import BotRunInsufficientResourcesError, ConflictError
from app.core.persistence.base import Base
from app.modules.versioning.application.scheduling.admission import (
    _admission_settings,
    _claim_global_lock,
    admit,
)
from app.modules.versioning.domain.value_objects import TestRunStatus
from app.modules.versioning.infrastructure.models import (
    ServerAdmissionLeaseModel,
    ServerTestRunModel,
)
from app.modules.versioning.infrastructure.resource_probe import (
    ResourcePreflightProbe,
)

pytestmark = pytest.mark.no_isolated_db


@pytest.fixture
async def adm_engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/adm.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


def _big_headroom():
    mem = SimpleNamespace(available=64 * 1024 * 1024 * 1024)
    return (
        patch("psutil.virtual_memory", return_value=mem),
        patch("os.cpu_count", return_value=32),
    )


def _tight_headroom(avail_mb: int):
    mem = SimpleNamespace(available=avail_mb * 1024 * 1024)
    return (
        patch("psutil.virtual_memory", return_value=mem),
        patch("os.cpu_count", return_value=32),
    )


async def _row_by_id(engine: AsyncEngine, run_id: str) -> dict[str, Any]:
    async with engine.connect() as conn:
        res = await conn.execute(
            ServerTestRunModel.__table__.select().where(
                ServerTestRunModel.__table__.c.id == run_id
            )
        )
        return dict(res.mappings().one())


async def _insert_run(
    engine: AsyncEngine,
    run_id: str,
    *,
    server_id: str = "srv-d-1",
    status: str = TestRunStatus.PENDING.value,
    created_at: datetime | None = None,
    bot_count: int = 5,
    reserved_ram_mb: int | None = None,
    reserved_cores: int | None = None,
) -> None:
    async with engine.connect() as conn:
        await conn.execute(
            ServerTestRunModel.__table__.insert().values(
                id=run_id,
                server_id=server_id,
                commit_id="c-d-1",
                node_id="local",
                status=status,
                created_at=created_at or datetime.now(UTC),
                bot_count=bot_count,
                duration_minutes=15,
                placement_mode="sidecar",
                bot_tech="auto",
                reserved_ram_mb=reserved_ram_mb,
                reserved_cores=reserved_cores,
            )
        )
        await conn.commit()


@pytest.mark.asyncio
async def test_cap_enforcement_and_earmark_values(adm_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        exp_ram, exp_cores = ResourcePreflightProbe.calculate_required_resources(
            5, "paper"
        )
        for i in range(3):
            res = await admit(
                server_id="srv-d-1",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=adm_engine,
                max_runs=3,
            )
            assert res.occupied_count == i
            assert res.test_run.reserved_ram_mb == exp_ram
            assert res.test_run.reserved_cores == exp_cores
            row = await _row_by_id(adm_engine, res.test_run.id)
            assert row["status"] == TestRunStatus.PENDING.value
            assert row["reserved_ram_mb"] == exp_ram
            assert row["reserved_cores"] == exp_cores

        with pytest.raises(ConflictError, match="Global concurrent test-run cap"):
            await admit(
                server_id="srv-d-1",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=adm_engine,
                max_runs=3,
            )

        # Sentinel lease row exists (seeded on first admission against create_all schemas).
        async with adm_engine.connect() as conn:
            lease_rows = (
                await conn.execute(select(ServerAdmissionLeaseModel.id))
            ).scalars().all()
            assert lease_rows == [1]


@pytest.mark.asyncio
async def test_occupied_uses_stored_earmarks_not_recompute(adm_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        first = await admit(
            server_id="srv-d-1",
            commit_id="c-d-1",
            bot_count=5,
            server_type="paper",
            engine=adm_engine,
            max_runs=10,
        )
        stored_ram = first.test_run.reserved_ram_mb
        assert stored_ram is not None and stored_ram > 1000

    # Shrink the formula AFTER admission: if the occupied set were recomputed,
    # the old run would now count ~100MB. Tighten headroom so stored denies
    # (stored + 100 > avail) but recomputed would admit (100 + 100 < avail).
    with (
        patch.object(
            ResourcePreflightProbe,
            "calculate_required_resources",
            return_value=(100, 1),
        ),
        _tight_headroom(stored_ram + 100 - 1)[0],
        _tight_headroom(stored_ram + 100 - 1)[1],
    ):
        with pytest.raises(BotRunInsufficientResourcesError) as exc_info:
            await admit(
                server_id="srv-d-2",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=adm_engine,
                max_runs=10,
            )
        assert exc_info.value.details["occupied"] == 1
        assert exc_info.value.details["earmarked_ram_mb"] == stored_ram


@pytest.mark.asyncio
async def test_null_legacy_row_recomputed_and_backfilled(adm_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        await _insert_run(adm_engine, "legacy-1", reserved_ram_mb=None, reserved_cores=None)
        exp_ram, exp_cores = ResourcePreflightProbe.calculate_required_resources(
            5, "paper"
        )
        await admit(
            server_id="srv-d-1",
            commit_id="c-d-1",
            bot_count=5,
            server_type="paper",
            engine=adm_engine,
            max_runs=10,
        )
        legacy = await _row_by_id(adm_engine, "legacy-1")
        assert legacy["reserved_ram_mb"] == exp_ram
        assert legacy["reserved_cores"] == exp_cores


@pytest.mark.asyncio
async def test_stale_runs_reaped_freeing_slots(adm_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        old = datetime.now(UTC) - timedelta(hours=7)
        await _insert_run(
            adm_engine,
            "stale-1",
            status=TestRunStatus.RUNNING.value,
            created_at=old,
            reserved_ram_mb=4096,
            reserved_cores=2,
        )
        res = await admit(
            server_id="srv-d-1",
            commit_id="c-d-1",
            bot_count=5,
            server_type="paper",
            engine=adm_engine,
            max_runs=3,
            stale_hours=6.0,
        )
        assert res.occupied_count == 0
        stale = await _row_by_id(adm_engine, "stale-1")
        assert stale["status"] == TestRunStatus.CANCELLED.value
        assert stale["failure_reason"] == "stale reservation reaped"


@pytest.mark.asyncio
async def test_drain_mode_cap_zero(adm_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2, pytest.raises(ConflictError, match="Global concurrent test-run cap"):
        await admit(
            server_id="srv-d-1",
            commit_id="c-d-1",
            bot_count=5,
            server_type="paper",
            engine=adm_engine,
            max_runs=0,
        )


@pytest.mark.asyncio
async def test_denial_still_commits_reap(adm_engine) -> None:
    # A denied admission must still persist the reap: otherwise a stale phantom
    # would survive every denial and leak its slot until the next success.
    p1, p2 = _big_headroom()
    with p1, p2:
        for i in range(3):
            await admit(
                server_id=f"srv-d-{i}",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=adm_engine,
                max_runs=3,
            )
        old = datetime.now(UTC) - timedelta(hours=7)
        await _insert_run(
            adm_engine,
            "stale-denied",
            status=TestRunStatus.RUNNING.value,
            created_at=old,
            reserved_ram_mb=4096,
            reserved_cores=2,
        )
        with pytest.raises(ConflictError, match="Global concurrent test-run cap"):
            await admit(
                server_id="srv-d-9",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=adm_engine,
                max_runs=3,
            )
        stale = await _row_by_id(adm_engine, "stale-denied")
        assert stale["status"] == TestRunStatus.CANCELLED.value
        assert stale["failure_reason"] == "stale reservation reaped"


def test_settings_defaults() -> None:
    assert _admission_settings() == (3, 6.0)


@pytest.mark.asyncio
async def test_k_concurrent_admits_exact_free_slots(adm_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        await admit(
            server_id="srv-d-1",
            commit_id="c-d-1",
            bot_count=5,
            server_type="paper",
            engine=adm_engine,
            max_runs=3,
        )

        async def _one(i: int):
            return await admit(
                server_id=f"srv-d-{i}",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=adm_engine,
                max_runs=3,
            )

        results = await asyncio.gather(*(_one(i) for i in range(5)), return_exceptions=True)
        ok = [r for r in results if not isinstance(r, BaseException)]
        denied = [r for r in results if isinstance(r, ConflictError)]
        # 1 pre-existing + cap 3 => exactly 2 of the 5 racers admitted.
        assert len(ok) == 2
        assert len(denied) == 3


@pytest.mark.asyncio
async def test_two_connections_second_observes_first_earmark(tmp_path) -> None:
    # Same FILE database behind two engines = the cross-"worker" shape.
    shared = tmp_path / "shared.db"
    eng_a = create_async_engine(f"sqlite+aiosqlite:///{shared}")
    eng_b = create_async_engine(f"sqlite+aiosqlite:///{shared}")
    async with eng_a.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        p1, p2 = _big_headroom()
        with p1, p2:
            first = await admit(
                server_id="srv-d-1",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=eng_a,
                max_runs=10,
            )
        stored = first.test_run.reserved_ram_mb or 0
        req, _ = ResourcePreflightProbe.calculate_required_resources(5, "paper")
        q1, q2 = _tight_headroom(stored + req - 100)
        # Without observing A's committed earmark, B would admit
        # (0 + req < avail). With it, B must deny.
        with q1, q2, pytest.raises(BotRunInsufficientResourcesError):
            await admit(
                server_id="srv-d-2",
                commit_id="c-d-1",
                bot_count=5,
                server_type="paper",
                engine=eng_b,
                max_runs=10,
            )
    finally:
        await eng_a.dispose()
        await eng_b.dispose()


class _FakeResult:
    def __init__(self, row: Any = None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _FakeConn:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = SimpleNamespace(name=dialect_name)
        self.statements: list[str] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(str(stmt))
        return _FakeResult(None)

    async def exec_driver_sql(self, sql: str) -> None:
        self.statements.append(sql)


@pytest.mark.asyncio
async def test_claim_shape_postgres_uses_for_update() -> None:
    fake = _FakeConn("postgresql")
    await _claim_global_lock(fake)
    assert any("FOR UPDATE" in s for s in fake.statements)


@pytest.mark.asyncio
async def test_claim_shape_sqlite_uses_begin_immediate() -> None:
    fake = _FakeConn("sqlite")
    await _claim_global_lock(fake)
    assert "BEGIN IMMEDIATE" in fake.statements
    assert not any("FOR UPDATE" in s for s in fake.statements)
