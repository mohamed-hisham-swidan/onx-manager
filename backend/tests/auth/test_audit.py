from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.modules.auth.infrastructure.audit import AuditLogger


@pytest.fixture
async def audit_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = session_factory()
    yield session
    await session.close()
    await engine.dispose()


class TestAuditLog:
    async def test_log_entry_created(self, audit_session: AsyncSession) -> None:
        logger = AuditLogger(audit_session)
        await logger.log(
            action="server.start",
            actor_type="user",
            actor_id="user_1",
            resource_type="server",
            resource_id="srv_1",
            outcome="success",
        )
        await audit_session.commit()
        result = await audit_session.execute(sa_text("SELECT COUNT(*) FROM audit_log"))
        assert result.scalar() == 1

    async def test_hash_chain_integrity(self, audit_session: AsyncSession) -> None:
        logger = AuditLogger(audit_session)
        for i in range(5):
            await logger.log(
                action=f"test.action.{i}",
                actor_type="user",
                actor_id=f"user_{i}",
                resource_type="test",
                resource_id=f"res_{i}",
                outcome="success",
            )
        await audit_session.commit()
        result = await logger.verify_chain()
        assert result["valid"] is True, f"Chain verification failed: {result['errors']}"
        assert result["checked"] == 5
        assert len(result["errors"]) == 0

    async def test_chain_tampering_detected(self, audit_session: AsyncSession) -> None:
        logger = AuditLogger(audit_session)
        for i in range(3):
            await logger.log(
                action=f"test.action.{i}",
                actor_type="user",
                actor_id="user_1",
                resource_type="test",
                resource_id="res_1",
                outcome="success",
            )
        await audit_session.commit()
        await audit_session.execute(
            sa_text("UPDATE audit_log SET action = 'tampered' WHERE id = 2")
        )
        await audit_session.commit()
        result = await logger.verify_chain()
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    async def test_empty_log_chain_valid(self, audit_session: AsyncSession) -> None:
        logger = AuditLogger(audit_session)
        result = await logger.verify_chain()
        assert result["valid"] is True
        assert result["checked"] == 0

    async def test_concurrent_audit_log_stays_linear(self, tmp_path, monkeypatch) -> None:
        from sqlalchemy import event as sa_event

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path}/audit_concurrency.db",
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

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            # Genesis log
            async with factory() as session:
                await AuditLogger(session).log(
                    action="genesis",
                    actor_type="system",
                    actor_id="sys",
                    resource_type="system",
                    resource_id="root",
                    outcome="success",
                )
                await session.commit()

            barrier = asyncio.Barrier(2)
            orig_get_latest = AuditLogger._get_latest_hash
            barrier_passed = False

            async def hooked_get_latest(self):
                nonlocal barrier_passed
                res = await orig_get_latest(self)
                if not barrier_passed:
                    await barrier.wait()
                    barrier_passed = True
                return res

            monkeypatch.setattr(AuditLogger, "_get_latest_hash", hooked_get_latest)

            async def worker(action: str, user_id: str):
                async with factory() as session:
                    await AuditLogger(session).log(
                        action=action,
                        actor_type="user",
                        actor_id=user_id,
                        resource_type="session",
                        resource_id=user_id,
                        outcome="success",
                    )
                    await session.commit()

            await asyncio.gather(
                worker("user.login.A", "user-A"),
                worker("user.login.B", "user-B"),
            )

            async with factory() as session:
                logger = AuditLogger(session)
                result = await logger.verify_chain()
                assert result["valid"] is True, f"Chain verification failed: {result['errors']}"
                assert result["checked"] == 3
                assert len(result["errors"]) == 0

                rows_res = await session.execute(
                    sa_text("SELECT id, previous_hash, hash FROM audit_log ORDER BY id ASC")
                )
                rows = rows_res.fetchall()
                assert len(rows) == 3
                assert rows[1][1] != rows[2][1]
                assert rows[2][1] == rows[1][2]
        finally:
            await engine.dispose()

    async def test_concurrent_audit_log_genesis_race(self, tmp_path, monkeypatch) -> None:
        from sqlalchemy import event as sa_event

        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path}/audit_genesis_concurrency.db",
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

        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)

            # Unseeded genesis race
            barrier = asyncio.Barrier(2)
            orig_get_latest = AuditLogger._get_latest_hash
            barrier_passed = False

            async def hooked_get_latest(self):
                nonlocal barrier_passed
                res = await orig_get_latest(self)
                if not barrier_passed:
                    await barrier.wait()
                    barrier_passed = True
                return res

            monkeypatch.setattr(AuditLogger, "_get_latest_hash", hooked_get_latest)

            async def worker(action: str, user_id: str):
                async with factory() as session:
                    await AuditLogger(session).log(
                        action=action,
                        actor_type="user",
                        actor_id=user_id,
                        resource_type="session",
                        resource_id=user_id,
                        outcome="success",
                    )
                    await session.commit()

            await asyncio.gather(
                worker("user.login.1", "user-1"),
                worker("user.login.2", "user-2"),
            )

            async with factory() as session:
                logger = AuditLogger(session)
                result = await logger.verify_chain()
                assert result["valid"] is True, f"Chain verification failed: {result['errors']}"
                assert result["checked"] == 2
                assert len(result["errors"]) == 0

                rows_res = await session.execute(
                    sa_text("SELECT id, previous_hash, hash FROM audit_log ORDER BY id ASC")
                )
                rows = rows_res.fetchall()
                assert len(rows) == 2
                assert rows[0][1] == "0" * 64
                assert rows[1][1] == rows[0][2]
        finally:
            await engine.dispose()
