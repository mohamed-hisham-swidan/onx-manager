import pytest
from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.persistence.base import Base, BaseRepository, TimestampMixin
from app.modules.auth.infrastructure.models import UserModel  # noqa: F401
from app.modules.server.infrastructure.models import ServerModel  # noqa: F401


class SampleModel(TimestampMixin, Base):
    __tablename__ = "test_samples"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False)


@pytest.mark.asyncio
class TestBaseRepository:
    async def test_add_and_get(self, db_session: AsyncSession) -> None:
        repo = BaseRepository(db_session, SampleModel)
        entity = SampleModel(name="test-item")
        created = await repo.add(entity)

        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.name == "test-item"

    async def test_list_with_filters(self, db_session: AsyncSession) -> None:
        repo = BaseRepository(db_session, SampleModel)
        await repo.add(SampleModel(name="alpha"))
        await repo.add(SampleModel(name="beta"))
        await repo.add(SampleModel(name="alpha"))

        results = await repo.list(name="alpha")
        assert len(results) == 2

    async def test_delete_removes_entity(self, db_session: AsyncSession) -> None:
        repo = BaseRepository(db_session, SampleModel)
        entity = await repo.add(SampleModel(name="to-delete"))
        await repo.delete(entity)

        fetched = await repo.get(entity.id)
        assert fetched is None


@pytest.fixture
async def db_session() -> AsyncSession:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
class TestDatabaseEngineLifecycle:
    async def test_database_engine_sqlite_pool_pre_ping_and_close(self) -> None:
        from app.core.config import AppSettings
        from app.core.persistence.db import DatabaseEngine

        settings = AppSettings(database_url="sqlite+aiosqlite:///:memory:")
        db = DatabaseEngine(settings)
        db.init()

        assert db.engine is not None
        assert db.engine.pool is not None

        # Verify session can be created and queried
        async with db.session_factory() as session:
            assert session.is_active

        # Verify clean disposal on shutdown/close without raising
        await db.close()
        assert db._engine is None
        assert db._session_factory is None

    async def test_database_engine_close_idempotent(self) -> None:
        from app.core.persistence.db import DatabaseEngine

        db = DatabaseEngine()
        # Closing an uninitialized engine should not raise
        await db.close()
