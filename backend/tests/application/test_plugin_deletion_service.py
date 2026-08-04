import pytest

from app.core.persistence.db import database
from app.modules.plugin.application.services.plugin_deletion_service import (
    consume_pending_plugin_deletions,
)
from app.modules.plugin.domain.aggregate import Plugin
from app.modules.plugin.infrastructure.repository import SQLPluginRepository
from app.modules.server.infrastructure.fs import LocalFileSystem
from app.modules.shared.value_objects import PluginId, PluginVersion, ServerId


class _FailDeleteFS(LocalFileSystem):
    def delete(self, _path: str) -> None:
        raise OSError("simulated locked file")


async def _seed_pending(plugin_id: str, server_id: str, filename: str | None) -> None:
    async with database.session_factory() as session:
        repo = SQLPluginRepository(session)
        plugin = Plugin.install(
            plugin_id=PluginId(plugin_id),
            server_id=ServerId(server_id),
            name=(filename.rsplit(".", 1)[0] if filename else plugin_id),
            version=PluginVersion.parse("1.0.0"),
            filename=filename,
            source="detected",
        )
        plugin.request_deletion()
        plugin.collect_events()
        await repo.save(plugin)
        await session.commit()


async def _rows_for(server_id: str) -> list[Plugin]:
    async with database.session_factory() as session:
        repo = SQLPluginRepository(session)
        return await repo.list_all_by_server(ServerId(server_id))


@pytest.mark.usefixtures("init_test_db")
class TestConsumePendingPluginDeletions:
    @pytest.mark.asyncio
    async def test_no_pending_noop(self, tmp_path) -> None:
        server_dir = str(tmp_path / "del-none")
        results = await consume_pending_plugin_deletions("del-none", server_dir)
        assert results == []

    @pytest.mark.asyncio
    async def test_deletes_file_and_row(self, tmp_path) -> None:
        import os

        server_dir = str(tmp_path / "del-hit")
        await _seed_pending("del-hit-1", "del-hit", "Old.jar")
        os.makedirs(os.path.join(server_dir, "plugins"), exist_ok=True)
        jar_path = os.path.join(server_dir, "plugins", "Old.jar")
        with open(jar_path, "wb") as f:
            f.write(b"PK\x03\x04fake-jar")

        results = await consume_pending_plugin_deletions("del-hit", server_dir)
        assert results == [
            {
                "plugin_id": "del-hit-1",
                "filename": "Old.jar",
                "deleted": True,
                "error": None,
            }
        ]
        assert os.path.exists(jar_path) is False
        assert await _rows_for("del-hit") == []

    @pytest.mark.asyncio
    async def test_already_missing_file_still_removes_row(self, tmp_path) -> None:
        server_dir = str(tmp_path / "del-absent")
        await _seed_pending("del-absent-1", "del-absent", "Gone.jar")

        results = await consume_pending_plugin_deletions("del-absent", server_dir)
        assert results[0]["deleted"] is True
        assert results[0]["filename"] == "Gone.jar"
        assert await _rows_for("del-absent") == []

    @pytest.mark.asyncio
    async def test_os_error_preserves_pending_row(self, tmp_path) -> None:
        import os

        server_dir = str(tmp_path / "del-locked")
        await _seed_pending("del-locked-1", "del-locked", "Locked.jar")
        os.makedirs(os.path.join(server_dir, "plugins"), exist_ok=True)
        jar_path = os.path.join(server_dir, "plugins", "Locked.jar")
        with open(jar_path, "wb") as f:
            f.write(b"PK\x03\x04fake-jar")

        results = await consume_pending_plugin_deletions(
            "del-locked", server_dir, fs=_FailDeleteFS()
        )
        assert results[0]["deleted"] is False
        assert results[0]["error"] == "simulated locked file"
        assert os.path.exists(jar_path) is True

        rows = await _rows_for("del-locked")
        assert len(rows) == 1
        assert rows[0].pending_deletion is True
        assert rows[0].filename == "Locked.jar"

    @pytest.mark.asyncio
    async def test_row_without_filename_is_cleared(self, tmp_path) -> None:
        server_dir = str(tmp_path / "del-nofname")
        await _seed_pending("del-nofname-1", "del-nofname", None)

        results = await consume_pending_plugin_deletions("del-nofname", server_dir)
        assert results[0]["deleted"] is True
        assert await _rows_for("del-nofname") == []
