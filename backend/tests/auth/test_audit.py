from __future__ import annotations

import pytest
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.infrastructure.audit import AuditLogger
from app.core.persistence.base import Base


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
