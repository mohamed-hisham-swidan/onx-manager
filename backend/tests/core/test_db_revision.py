from __future__ import annotations

from pathlib import Path

import pytest

from app.core.persistence.db_revision import (
    RELEASE_MINIMUM_DB_REVISION,
    evaluate_revision,
    load_revision_parents,
)

_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "alembic"


@pytest.fixture(scope="module")
def graph() -> dict[str, str | None]:
    return load_revision_parents(_MIGRATIONS_DIR)


@pytest.fixture()
def parents() -> dict[str, str | None]:
    # Synthetic linear chain: 001 -> 002 -> 003 -> 004
    return {
        "001": None,
        "002": "001",
        "003": "002",
        "004": "003",
    }


class TestEvaluationExactAndAncestry:
    def test_exact_minimum_is_compatible(self) -> None:
        status = evaluate_revision([RELEASE_MINIMUM_DB_REVISION])
        assert status.ok is True

    def test_compatible_descendant_is_allowed(self, parents) -> None:
        # current=004 is a descendant of minimum=003 in the synthetic chain.
        status = evaluate_revision(["004"], minimum_revision="003", parents=parents)
        assert status.ok is True

    def test_db_behind_minimum_is_rejected(self, parents) -> None:
        # current=001/002 walk up from 003 -> minimum not reachable.
        status = evaluate_revision(["001"], minimum_revision="003", parents=parents)
        assert status.ok is False
        assert "behind" in status.message.lower()
        assert "alembic upgrade head" in status.message

    def test_missing_revision_fails_closed(self) -> None:
        status = evaluate_revision([])
        assert status.ok is False
        assert "no schema revision" in status.message.lower()
        assert "alembic upgrade head" in status.message

    def test_unknown_revision_is_rejected(self, parents) -> None:
        status = evaluate_revision(["deadbeef"], minimum_revision="003", parents=parents)
        assert status.ok is False
        assert "unknown" in status.message.lower()

    def test_multiple_heads_are_rejected(self, parents) -> None:
        status = evaluate_revision(["002", "004"], minimum_revision="003", parents=parents)
        assert status.ok is False

    def test_unrelated_revision_is_rejected(self) -> None:
        # Two disjoint chains: the DB is on detour_a, minimum is on the main chain.
        p = {
            "main-1": None,
            "main-2": "main-1",
            "detour-a": None,
        }
        status = evaluate_revision(["detour-a"], minimum_revision="main-2", parents=p)
        assert status.ok is False

    def test_minimum_itself_missing_from_graph_is_rejected(self, parents) -> None:
        status = evaluate_revision(["002"], minimum_revision="ZZZ", parents=parents)
        assert status.ok is False
        assert "not present in the migration history" in status.message.lower()


class TestGraphReflectsRelease:
    def test_release_minimum_is_the_single_head(self, graph) -> None:
        # The release minimum must be the unique leaf head of the migration graph
        # (a revision no other revision depends on).
        assert RELEASE_MINIMUM_DB_REVISION in graph
        parents_referenced = {down for down in graph.values() if down is not None}
        heads = [r for r in graph if r not in parents_referenced]
        assert heads == [RELEASE_MINIMUM_DB_REVISION]

    def test_release_minimum_is_reachable_from_root(self, graph) -> None:
        # Walking down_revision from the minimum must terminate at the single root,
        # proving every released migration is an ancestor of the minimum (linear).
        node = RELEASE_MINIMUM_DB_REVISION
        chain = []
        while node is not None:
            chain.append(node)
            node = graph[node]
        roots = [r for r in graph if graph[r] is None]
        assert len(roots) == 1
        assert chain[-1] == roots[0]


class TestNoSecretsAndNoUpgrade:
    def test_error_message_does_not_leak_database_url(self, parents) -> None:
        # The message may only name revision ids — never a DB URL or credentials.
        status = evaluate_revision(["001"], minimum_revision="003", parents=parents)
        assert "supersecret" not in status.message
        assert "://" not in status.message

    def test_no_auto_upgrade_wording(self) -> None:
        # The message instructs the operator to run migrations; it must not
        # imply the application runs them itself.
        status = evaluate_revision([])
        assert "alembic upgrade head" in status.message


# ── Live DB integration: use the project's persistence abstraction ──────────


@pytest.fixture()
def live_db(tmp_path):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.persistence.db import database

    db_file = tmp_path / "db.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    database._engine = engine
    database._session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    yield engine


@pytest.mark.asyncio
async def test_live_db_at_minimum_starts(live_db) -> None:
    from sqlalchemy import text

    from app.core.persistence.db_revision import check_database_compatibility

    async with live_db.begin() as conn:
        await conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
            {"r": RELEASE_MINIMUM_DB_REVISION},
        )

    status = await check_database_compatibility()
    assert status.ok is True
    await live_db.dispose()


@pytest.mark.asyncio
async def test_live_db_behind_minimum_rejected(live_db) -> None:
    from sqlalchemy import text

    from app.core.persistence.db_revision import check_database_compatibility

    async with live_db.begin() as conn:
        await conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
            {"r": "001"},
        )

    status = await check_database_compatibility()
    assert status.ok is False
    assert "alembic upgrade head" in status.message
    await live_db.dispose()


@pytest.mark.asyncio
async def test_live_db_compatible_descendant_starts(live_db, monkeypatch) -> None:
    # A future migration extends the graph above the release head. The live DB
    # reports that future revision; the check must allow it because the
    # release minimum is still reachable in the ancestry. The graph loading is
    # extended (not the compatibility logic) -- exactly like the real world
    # after 4.0.x ships a follow-up migration.
    from sqlalchemy import text

    from app.core.persistence import db_revision

    real_graph = db_revision.load_revision_parents(_MIGRATIONS_DIR)
    extended = dict(real_graph)
    extended["future-01"] = RELEASE_MINIMUM_DB_REVISION

    def fake_load(_scripts_dir=None):
        return extended

    monkeypatch.setattr(
        "app.core.persistence.db_revision.load_revision_parents",
        fake_load,
    )

    async with live_db.begin() as conn:
        await conn.execute(
            text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)")
        )
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:r)"),
            {"r": "future-01"},
        )

    status = await db_revision.check_database_compatibility()
    assert status.ok is True
    assert "future-01" in status.message
    await live_db.dispose()


@pytest.mark.asyncio
async def test_no_automatic_migration_runs(live_db) -> None:
    # Startup check must never create the alembic_version table itself.
    from sqlalchemy import text

    from app.core.persistence.db_revision import check_database_compatibility

    status = await check_database_compatibility()
    assert status.ok is False

    async with live_db.connect() as conn:
        exists = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
        )
        assert exists.fetchone() is None
    await live_db.dispose()
