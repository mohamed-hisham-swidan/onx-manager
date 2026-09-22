"""Concurrency regression test: linearity of EventChain.append_chain under concurrent writes.

Covers TOCTOU race remediation in ``EventChain.append_chain`` (chain.py):
two concurrent appends overlapping the READ (get_last_event) -> COMPUTE ->
WRITE (append/flush) window both read the same initial ``previous_hash``.
With a UNIQUE constraint on ``previous_hash`` and optimistic retry-on-conflict,
one worker flushes successfully while the conflicting worker catches
IntegrityError, rolls back to its savepoint, re-reads the fresh hash,
and completes the append linearly without chain forks.

The test forces the overlap deterministically with an asyncio.Barrier hooked
around ``SQLEventRepository.get_last_event`` on the initial attempt, then asserts
the resulting rows form a linear chain and ``verify_chain()`` passes.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.modules.event_store.models  # noqa: F401  (register tables)
from app.core.event_bus import DomainEvent
from app.core.persistence.base import Base
from app.modules.event_store import repository as repo_mod
from app.modules.event_store.chain import EventChain
from app.modules.event_store.models import StoredEventModel


def _test_engine(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/recon_chain.db",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA synchronous=NORMAL")
        finally:
            cur.close()

    return engine


@pytest.mark.asyncio
@pytest.mark.no_isolated_db
async def test_concurrent_append_chain_stays_linear(tmp_path, monkeypatch) -> None:
    engine = _test_engine(tmp_path)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async with factory() as session:
            await EventChain(session).append_chain(
                DomainEvent(event_type="genesis", event_id="recon-genesis")
            )
            await session.commit()

        barrier = asyncio.Barrier(2)
        orig_get_last = repo_mod.SQLEventRepository.get_last_event
        barrier_passed = False

        async def hooked_get_last(self):
            nonlocal barrier_passed
            result = await orig_get_last(self)
            if not barrier_passed:
                await barrier.wait()
                barrier_passed = True
            return result

        monkeypatch.setattr(
            repo_mod.SQLEventRepository, "get_last_event", hooked_get_last
        )

        async def worker(event_id: str, event_type: str):
            async with factory() as session:
                stored = await EventChain(session).append_chain(
                    DomainEvent(event_type=event_type, event_id=event_id)
                )
                await session.commit()
                return stored

        stored_a, stored_b = await asyncio.gather(
            worker("recon-A", "race.a"),
            worker("recon-B", "race.b"),
        )

        async with factory() as session:
            result = await session.execute(
                select(StoredEventModel).order_by(StoredEventModel.id.asc())
            )
            rows = list(result.scalars().all())

        assert len(rows) == 3
        # Linear chain: the two concurrent rows must NOT share a previous_hash;
        # the later row must point at the earlier row's hash.
        assert stored_a.previous_hash != stored_b.previous_hash
        assert rows[2].previous_hash == rows[1].hash

        async with factory() as session:
            assert await EventChain(session).verify_chain() is True
    finally:
        await engine.dispose()
