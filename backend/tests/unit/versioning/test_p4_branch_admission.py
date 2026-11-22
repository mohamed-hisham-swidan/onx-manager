from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

import app.modules.auth.infrastructure.models  # noqa: F401
import app.modules.server.infrastructure.models  # noqa: F401
import app.modules.versioning.infrastructure.models  # noqa: F401
from app.core.exceptions import (
    BotRunInsufficientResourcesError,
    BranchConcurrencyLimitError,
    BranchRuntimeActiveError,
    ServerModeVersioningDisabledError,
    ValidationError,
)
from app.core.persistence.base import Base
from app.modules.server.infrastructure.models import ServerModel
from app.modules.versioning.application.scheduling.admission import (
    BRANCH_DEFAULT_MEMORY_MB,
    BRANCH_MEMORY_FLOOR_MB,
    LIGHTWEIGHT_BRANCH_MEMORY_FLOOR_MB,
    MAX_CONCURRENT_BRANCH_RUNS_LIMIT,
    RuntimeAdmissionScheduler,
    admit_branch_runtime,
)

pytestmark = pytest.mark.no_isolated_db

_POSIX_ONLY = pytest.mark.skipif(
    os.name != "posix",
    reason="P4 branch admission requires a POSIX host; Windows = Simple-only",
)


@pytest.fixture
async def db_engine(tmp_path):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/adm.db")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # seed server
    async with eng.begin() as conn:
        await conn.execute(
            ServerModel.__table__.insert().values(
                id="srv-1",
                name="srv",
                server_type="paper",
                minecraft_version="1.20.4",
                memory_max_mb=4096,
                cpu_cores=4,
                mode="advanced",
                root_path=str(tmp_path / "server"),
            )
        )
    yield eng
    await eng.dispose()


def _big_headroom():
    mem = SimpleNamespace(available=64 * 1024 * 1024 * 1024)
    return (
        patch("psutil.virtual_memory", return_value=mem),
        patch("os.cpu_count", return_value=32),
    )


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_default_cap_second_raises(db_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        d1 = await admit_branch_runtime(
            server_id="srv-1",
            branch_name="b1",
            commit_sha="a" * 40,
            engine=db_engine,
        )
        assert d1.server_branch_cap == 1
        with pytest.raises(BranchConcurrencyLimitError) as ei:
            await admit_branch_runtime(
                server_id="srv-1",
                branch_name="b2",
                commit_sha="b" * 40,
                engine=db_engine,
            )
        assert "stop an active branch run" in str(ei.value)


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_configurable_cap_up_to_3(db_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        for i in range(3):
            d = await admit_branch_runtime(
                server_id="srv-1",
                branch_name=f"br{i}",
                commit_sha=f"{i}" * 40 if False else "c" * 40,
                max_concurrent_branch_runs=3,
                engine=db_engine,
            )
            assert d.server_branch_cap == 3
        with pytest.raises(BranchConcurrencyLimitError):
            await admit_branch_runtime(
                server_id="srv-1",
                branch_name="brx",
                commit_sha="d" * 40,
                max_concurrent_branch_runs=3,
                engine=db_engine,
            )
    # cap > 3 rejected
    with pytest.raises(ValidationError):
        await admit_branch_runtime(
            server_id="srv-1",
            branch_name="bry",
            commit_sha="e" * 40,
            max_concurrent_branch_runs=5,
            engine=db_engine,
        )


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_same_branch_twice_raises(db_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        await admit_branch_runtime(
            server_id="srv-1", branch_name="same", commit_sha="f" * 40, engine=db_engine
        )
        with pytest.raises(BranchRuntimeActiveError):
            await admit_branch_runtime(
                server_id="srv-1", branch_name="same", commit_sha="f" * 40, engine=db_engine
            )


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_memory_floors_and_default(db_engine) -> None:
    # resolve_branch_resources static
    sched = RuntimeAdmissionScheduler()
    # standard
    mem_min, mem_max, cores = sched.resolve_branch_resources(
        server_type="paper", server_memory_max_mb=None, requested_memory_mb=None
    )
    assert mem_max == BRANCH_DEFAULT_MEMORY_MB
    # floor enforcement
    with pytest.raises(ValidationError):
        sched.resolve_branch_resources(
            server_type="paper", server_memory_max_mb=None, requested_memory_mb=1024
        )
    with pytest.raises(ValidationError):
        sched.resolve_branch_resources(
            server_type="vanilla", server_memory_max_mb=None, requested_memory_mb=512
        )
    # lightweight floor 1024
    mm, mx, cc = sched.resolve_branch_resources(
        server_type="vanilla", server_memory_max_mb=None, requested_memory_mb=1024
    )
    assert mx == 1024
    # standard floor 2048
    mm, mx, cc = sched.resolve_branch_resources(
        server_type="forge", server_memory_max_mb=1024, requested_memory_mb=None
    )
    assert mx >= BRANCH_MEMORY_FLOOR_MB
    # lightweight unspecified defaults server memory or 4096
    mm, mx, cc = sched.resolve_branch_resources(
        server_type="velocity", server_memory_max_mb=512, requested_memory_mb=None
    )
    assert mx >= LIGHTWEIGHT_BRANCH_MEMORY_FLOOR_MB
    # pids_limit
    p1, p2 = _big_headroom()
    with p1, p2:
        d = await admit_branch_runtime(
            server_id="srv-1", branch_name="memtest", commit_sha="g" * 40, engine=db_engine
        )
        assert d.pids_limit == 2048
        assert d.memory_min_mb == min(1024, d.memory_max_mb)


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_global_headroom_denial(db_engine) -> None:
    # tight headroom
    mem = SimpleNamespace(available=0)
    p1 = patch("psutil.virtual_memory", return_value=mem)
    p2 = patch("os.cpu_count", return_value=1)
    with p1, p2, pytest.raises(BotRunInsufficientResourcesError):
        await admit_branch_runtime(
            server_id="srv-1", branch_name="hr", commit_sha="h" * 40, engine=db_engine
        )


@_POSIX_ONLY
@pytest.mark.asyncio
async def test_concurrent_gather_serializes(db_engine) -> None:
    p1, p2 = _big_headroom()
    with p1, p2:
        async def attempt(name):
            try:
                return await admit_branch_runtime(
                    server_id="srv-1", branch_name=name, commit_sha="i" * 40, engine=db_engine
                )
            except Exception as e:
                return e

        results = await asyncio.gather(
            attempt("c1"), attempt("c2"), attempt("c3"), return_exceptions=True
        )
        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1
        assert len(failures) == 2
        assert all(isinstance(f, BranchConcurrencyLimitError) for f in failures)


@pytest.mark.asyncio
async def test_windows_fail_closed(monkeypatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    with pytest.raises(ServerModeVersioningDisabledError):
        await admit_branch_runtime(server_id="srv-1", branch_name="w", commit_sha="j" * 40)


def test_lightweight_server_types_floor_constants() -> None:
    assert BRANCH_MEMORY_FLOOR_MB == 2048
    assert LIGHTWEIGHT_BRANCH_MEMORY_FLOOR_MB == 1024
    assert BRANCH_DEFAULT_MEMORY_MB == 4096
    assert MAX_CONCURRENT_BRANCH_RUNS_LIMIT == 3
