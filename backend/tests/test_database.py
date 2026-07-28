import pytest
from sqlalchemy import Column, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declared_attr

from app.core.persistence.base import Base, BaseRepository, TimestampMixin


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
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()
