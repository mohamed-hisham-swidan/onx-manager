from __future__ import annotations

import pytest

from app.core.persistence.db import database
from app.modules.backup.infrastructure.models import BackupJobModel


class TestBackupPinnedMetadata:
    def test_pinned_column_metadata(self) -> None:
        column = BackupJobModel.__table__.c.pinned
        assert column.nullable is False
        assert column.default is not None
        assert column.default.arg is False


class TestBackupPinnedPersistence:
    @pytest.mark.asyncio
    async def test_default_pinned_round_trips_false(self) -> None:
        async with database.session_factory() as session:
            job = BackupJobModel(id="bak-pin-1", server_id="srv-1")
            session.add(job)
            await session.commit()

        async with database.session_factory() as session:
            loaded = await session.get(BackupJobModel, "bak-pin-1")
            assert loaded is not None
            assert loaded.id == "bak-pin-1"
            assert loaded.server_id == "srv-1"
            assert loaded.pinned is False

    @pytest.mark.asyncio
    async def test_explicit_pinned_true_round_trips(self) -> None:
        async with database.session_factory() as session:
            job = BackupJobModel(id="bak-pin-2", server_id="srv-1", pinned=True)
            session.add(job)
            await session.commit()

        async with database.session_factory() as session:
            loaded = await session.get(BackupJobModel, "bak-pin-2")
            assert loaded is not None
            assert loaded.id == "bak-pin-2"
            assert loaded.server_id == "srv-1"
            assert loaded.pinned is True
