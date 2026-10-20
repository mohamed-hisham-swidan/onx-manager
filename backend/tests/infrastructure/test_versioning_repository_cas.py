import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.persistence.base import Base
from app.modules.versioning.domain.entities import ServerBranch
from app.modules.versioning.domain.value_objects import BranchStatus
from app.modules.versioning.infrastructure.models import ServerBranchModel
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository


def _create_sqlite_engine(db_file: Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"timeout": 30.0, "check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        finally:
            cursor.close()

    return engine


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_advance_branch_head_optimistic_rejects_stale_expected_head(tmp_path: Path) -> None:
    db_file = tmp_path / "cas_stale.sqlite3"
    engine1 = _create_sqlite_engine(db_file)
    engine2 = _create_sqlite_engine(db_file)
    try:
        async with engine1.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory1 = async_sessionmaker(bind=engine1, class_=AsyncSession, expire_on_commit=False)
        factory2 = async_sessionmaker(bind=engine2, class_=AsyncSession, expire_on_commit=False)

        branch_id = f"b-{uuid.uuid4().hex[:8]}"
        server_id = "srv-1"
        h0 = "c-initial"
        h1 = "c-advance-a"
        h2 = "c-advance-b"

        async with factory1() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id=server_id,
                name="main",
                head_commit_id=h0,
                status=BranchStatus.ACTIVE,
            )
            await repo.save_branch(branch)
            await session.commit()

        # Session 1: CAS H0 -> H1
        async with factory1() as session1:
            repo1 = SQLVersioningRepository(session1)
            ok1 = await repo1.advance_branch_head_optimistic(branch_id, h1, h0)
            assert ok1 is True
            await session1.commit()

        # Session 2: CAS with stale expected head H0 -> H2
        async with factory2() as session2:
            repo2 = SQLVersioningRepository(session2)
            ok2 = await repo2.advance_branch_head_optimistic(branch_id, h2, h0)
            assert ok2 is False
            await session2.commit()

        # Verify head is still H1
        async with factory1() as session:
            repo = SQLVersioningRepository(session)
            reloaded = await repo.get_branch(branch_id)
            assert reloaded is not None
            assert reloaded.head_commit_id == h1
    finally:
        await engine1.dispose()
        await engine2.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_advance_branch_head_optimistic_matches_null_head(tmp_path: Path) -> None:
    db_file = tmp_path / "cas_null.sqlite3"
    engine = _create_sqlite_engine(db_file)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        branch_id = f"b-{uuid.uuid4().hex[:8]}"

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id="srv-1",
                name="feature",
                head_commit_id=None,
                status=BranchStatus.CREATED,
            )
            await repo.save_branch(branch)
            await session.commit()

        # First CAS with expected_head=None succeeds
        async with factory() as session:
            repo = SQLVersioningRepository(session)
            ok1 = await repo.advance_branch_head_optimistic(branch_id, "c-first", None)
            assert ok1 is True
            await session.commit()

        # Second CAS with expected_head=None fails because head is now 'c-first'
        async with factory() as session:
            repo = SQLVersioningRepository(session)
            ok2 = await repo.advance_branch_head_optimistic(branch_id, "c-second", None)
            assert ok2 is False
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            reloaded = await repo.get_branch(branch_id)
            assert reloaded is not None
            assert reloaded.head_commit_id == "c-first"
    finally:
        await engine.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_advance_branch_head_sets_status_active(tmp_path: Path) -> None:
    db_file = tmp_path / "cas_active.sqlite3"
    engine = _create_sqlite_engine(db_file)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        branch_id = f"b-{uuid.uuid4().hex[:8]}"

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id="srv-1",
                name="dev",
                head_commit_id=None,
                status=BranchStatus.CREATED,
            )
            await repo.save_branch(branch)
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            ok = await repo.advance_branch_head_optimistic(branch_id, "c-1", None)
            assert ok is True
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            reloaded = await repo.get_branch(branch_id)
            assert reloaded is not None
            assert reloaded.status == BranchStatus.ACTIVE
    finally:
        await engine.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_advance_branch_head_rejects_archived_branch(tmp_path: Path) -> None:
    db_file = tmp_path / "cas_archived.sqlite3"
    engine = _create_sqlite_engine(db_file)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        branch_id = f"b-{uuid.uuid4().hex[:8]}"

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id="srv-1",
                name="old-branch",
                head_commit_id="c-old",
                status=BranchStatus.ARCHIVED,
            )
            await repo.save_branch(branch)
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            ok = await repo.advance_branch_head_optimistic(branch_id, "c-new", "c-old")
            assert ok is False
            await session.commit()

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            reloaded = await repo.get_branch(branch_id)
            assert reloaded is not None
            assert reloaded.head_commit_id == "c-old"
            assert reloaded.status == BranchStatus.ARCHIVED
    finally:
        await engine.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_archived_race_between_read_and_cas_keeps_archived(tmp_path: Path) -> None:
    db_file = tmp_path / "cas_archived_race.sqlite3"
    engine_a = _create_sqlite_engine(db_file)
    engine_b = _create_sqlite_engine(db_file)
    try:
        async with engine_a.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory_a = async_sessionmaker(bind=engine_a, class_=AsyncSession, expire_on_commit=False)
        factory_b = async_sessionmaker(bind=engine_b, class_=AsyncSession, expire_on_commit=False)

        branch_id = f"b-{uuid.uuid4().hex[:8]}"
        initial_head = "c-initial"

        async with factory_a() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id="srv-1",
                name="race-branch",
                head_commit_id=initial_head,
                status=BranchStatus.ACTIVE,
            )
            await repo.save_branch(branch)
            await session.commit()

        # Session A reads active branch
        async with factory_a() as session_a:
            repo_a = SQLVersioningRepository(session_a)
            branch_a = await repo_a.get_branch(branch_id)
            assert branch_a is not None
            assert branch_a.status == BranchStatus.ACTIVE

            # Session B archives branch and commits
            async with factory_b() as session_b:
                repo_b = SQLVersioningRepository(session_b)
                branch_b = await repo_b.get_branch(branch_id)
                assert branch_b is not None
                branch_b.archive()
                await repo_b.save_branch(branch_b)
                await session_b.commit()

            # Session A's CAS attempt
            ok = await repo_a.advance_branch_head_optimistic(
                branch_id, "c-after-archive", initial_head
            )
            assert ok is False
            await session_a.commit()

        # Reload and verify
        async with factory_b() as session:
            repo = SQLVersioningRepository(session)
            reloaded = await repo.get_branch(branch_id)
            assert reloaded is not None
            assert reloaded.status == BranchStatus.ARCHIVED
            assert reloaded.head_commit_id == initial_head
    finally:
        await engine_a.dispose()
        await engine_b.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_stale_metadata_save_does_not_clobber_head(tmp_path: Path) -> None:
    db_file = tmp_path / "cas_stale_metadata.sqlite3"
    engine = _create_sqlite_engine(db_file)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
        branch_id = f"b-{uuid.uuid4().hex[:8]}"
        h0 = "c-0"
        h1 = "c-1"

        async with factory() as session:
            repo = SQLVersioningRepository(session)
            branch = ServerBranch(
                id=branch_id,
                server_id="srv-1",
                name="target",
                head_commit_id=h0,
                status=BranchStatus.ACTIVE,
            )
            await repo.save_branch(branch)
            await session.commit()

        # Load stale branch view into memory
        async with factory() as session:
            repo = SQLVersioningRepository(session)
            stale_branch = await repo.get_branch(branch_id)
            assert stale_branch is not None
            assert stale_branch.head_commit_id == h0

        # In another session, CAS moves head H0 -> H1
        async with factory() as session:
            # Direct SQL update if CAS is not yet implemented, or CAS:
            stmt = (
                update(ServerBranchModel)
                .where(ServerBranchModel.id == branch_id)
                .values(head_commit_id=h1, status=BranchStatus.ACTIVE.value)
            )
            await session.execute(stmt)
            await session.commit()

        # Stale metadata save (e.g. protection/metadata update)
        stale_branch.name = "target-renamed"
        async with factory() as session:
            repo = SQLVersioningRepository(session)
            await repo.save_branch(stale_branch)
            await session.commit()

        # Reload and verify head_commit_id was NOT clobbered back to H0
        async with factory() as session:
            repo = SQLVersioningRepository(session)
            reloaded = await repo.get_branch(branch_id)
            assert reloaded is not None
            assert reloaded.head_commit_id == h1
            assert reloaded.name == "target-renamed"
            assert reloaded.status == BranchStatus.ACTIVE
    finally:
        await engine.dispose()


@pytest.mark.no_isolated_db
@pytest.mark.asyncio
async def test_file_backed_two_engine_losing_cas_surface(tmp_path: Path) -> None:
    """The mandatory R2 experiment described in §2a."""
    db_file = tmp_path / "cas.sqlite3"
    engine_a = _create_sqlite_engine(db_file)
    engine_b = _create_sqlite_engine(db_file)

    try:
        async with engine_a.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory_a = async_sessionmaker(bind=engine_a, class_=AsyncSession, expire_on_commit=False)
        factory_b = async_sessionmaker(bind=engine_b, class_=AsyncSession, expire_on_commit=False)

        branch_id = "b-cas-r2"
        h = "H-initial"

        async with factory_a() as sess:
            branch_model = ServerBranchModel(
                id=branch_id,
                server_id="srv-1",
                name="r2-test",
                head_commit_id=h,
                status="active",
                is_protected=False,
                created_at=datetime.now(UTC),
            )
            sess.add(branch_model)
            await sess.commit()

        # Session A reads branch (acquires WAL snapshot S)
        session_a = factory_a()
        branch_read_stmt = select(ServerBranchModel).where(ServerBranchModel.id == branch_id)
        result_read_a = await session_a.execute(branch_read_stmt)
        branch_a = result_read_a.scalar_one()
        assert branch_a.head_commit_id == h

        # Session B executes raw CAS UPDATE ... WHERE head = H and commits
        async with factory_b() as session_b:
            cas_b_stmt = (
                update(ServerBranchModel)
                .where(
                    ServerBranchModel.id == branch_id,
                    ServerBranchModel.status != "archived",
                    ServerBranchModel.head_commit_id == h,
                )
                .values(head_commit_id="H-writer-B", status="active")
                .execution_options(synchronize_session="fetch")
            )
            res_b = await session_b.execute(cas_b_stmt)
            await session_b.commit()
            assert res_b.rowcount == 1

        # In session A, execute same raw CAS with expected head H
        cas_a_stmt = (
            update(ServerBranchModel)
            .where(
                ServerBranchModel.id == branch_id,
                ServerBranchModel.status != "archived",
                ServerBranchModel.head_commit_id == h,
            )
            .values(head_commit_id="H-writer-A", status="active")
            .execution_options(synchronize_session="fetch")
        )

        outcome_kind = None
        rowcount_seen = None
        exc_seen = None

        try:
            res_a = await session_a.execute(cas_a_stmt)
            await session_a.flush()
            outcome_kind = "rowcount"
            rowcount_seen = res_a.rowcount
        except OperationalError as exc:
            outcome_kind = "operational_error"
            exc_seen = exc
        finally:
            await session_a.close()

        # HALT rule evaluation
        print(
            f"\nR2 EXPERIMENT RESULT: outcome_kind={outcome_kind}, "
            f"rowcount={rowcount_seen}, exc={exc_seen}"
        )
        if outcome_kind == "rowcount":
            # Expected losing CAS rowcount must be 0
            assert rowcount_seen == 0, (
                f"HALT: unexpected rowcount {rowcount_seen} (must be 0 on losing CAS)"
            )
        elif outcome_kind == "operational_error":
            orig = getattr(exc_seen, "orig", None)
            sqlite_code = getattr(orig, "sqlite_errorcode", None)
            sqlite_name = getattr(orig, "sqlite_errorname", None)
            # Must be robust discriminator
            is_snapshot_busy = (
                sqlite_name == "SQLITE_BUSY_SNAPSHOT" or sqlite_code == 517
            )
            assert is_snapshot_busy, (
                "HALT: OperationalError observed without robust "
                f"SQLITE_BUSY_SNAPSHOT discriminator: "
                f"code={sqlite_code}, name={sqlite_name}, exc={exc_seen}"
            )
        else:
            pytest.fail(f"HALT: Unexpected outcome kind: {outcome_kind}")
    finally:
        await engine_a.dispose()
        await engine_b.dispose()
