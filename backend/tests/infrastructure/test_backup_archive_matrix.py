from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from app.core.saga import SagaOrchestrator
from app.modules.backup.domain.aggregate import BackupType
from app.services.backup_orchestrator import CONFIG_FILES, BackupSaga


def _write(path: Path, rel: str, content: str = "") -> Path:
    target = path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def _seed_server_dir(server_dir: Path) -> None:
    _write(server_dir, "world/region/r.0.0.mca", "world-region")
    _write(server_dir, "world/playerdata/abc.dat", "world-pd")
    _write(server_dir, "world_nether/DIM-1/r.0.0.mca", "nether-region")
    _write(server_dir, "world_nether/playerdata/abc.dat", "nether-pd")
    _write(server_dir, "world_the_end/DIM1/r.0.0.mca", "end-region")
    _write(server_dir, "world_the_end/playerdata/abc.dat", "end-pd")
    _write(server_dir, "plugins/essentials.jar", "plugin-jar")
    for name in CONFIG_FILES:
        _write(server_dir, name, f"cfg:{name}")


def _archive_names(server_dir: Path, backup_type: BackupType) -> list[str]:
    saga = BackupSaga(SagaOrchestrator())
    tar_path = str(server_dir / "out.tar.gz")
    saga._write_tar(tar_path, str(server_dir), primary_world="world", backup_type=backup_type)
    with tarfile.open(tar_path, "r:gz") as tar:
        return tar.getnames()


class TestWriteTarContentMatrix:
    @pytest.mark.parametrize(
        ("backup_type", "expected_dims", "expect_plugins", "expect_config", "expect_pd_namespace"),
        [
            (BackupType.FULL, {"world", "world_nether", "world_the_end"}, True, True, set()),
            (BackupType.WORLDS, {"world", "world_nether", "world_the_end"}, False, False, set()),
            (
                BackupType.WORLD,
                {"world"},
                False,
                False,
                {
                    "mcs_playerdata/world_nether/playerdata",
                    "mcs_playerdata/world_the_end/playerdata",
                },
            ),
            (
                BackupType.NETHER,
                {"world_nether"},
                False,
                False,
                {"mcs_playerdata/world/playerdata", "mcs_playerdata/world_the_end/playerdata"},
            ),
            (
                BackupType.END,
                {"world_the_end"},
                False,
                False,
                {"mcs_playerdata/world/playerdata", "mcs_playerdata/world_nether/playerdata"},
            ),
            (BackupType.PLUGINS, set(), True, False, set()),
            (BackupType.CONFIG, set(), False, True, set()),
        ],
    )
    def test_archive_contents(
        self,
        tmp_path: Path,
        backup_type: BackupType,
        expected_dims: set[str],
        expect_plugins: bool,
        expect_config: bool,
        expect_pd_namespace: set[str],
    ) -> None:
        server_dir = tmp_path / "server"
        _seed_server_dir(server_dir)

        names = _archive_names(server_dir, backup_type)

        actual_dims = {n for n in names if n in {"world", "world_nether", "world_the_end"}}
        assert actual_dims == expected_dims

        assert ("plugins" in names) is expect_plugins

        config_present = {n for n in names if n in CONFIG_FILES}
        assert bool(config_present) is expect_config
        if expect_config:
            assert config_present == set(CONFIG_FILES)

        pd_namespace = {
            "/".join(n.split("/")[:3]) for n in names if n.startswith("mcs_playerdata/")
        }
        assert pd_namespace == expect_pd_namespace

    def test_playerdata_rides_inside_whole_dimension_not_namespaced(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _seed_server_dir(server_dir)

        names = _archive_names(server_dir, BackupType.WORLD)

        assert "world/playerdata/abc.dat" in names
        assert "mcs_playerdata/world/playerdata" not in names

    def test_missing_dimension_on_disk_skipped_without_error(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "only-overworld")

        names = _archive_names(server_dir, BackupType.WORLD)

        assert "world" in names
        assert not any(n.startswith("mcs_playerdata/") for n in names)

    def test_plugins_type_requires_no_dimension_folder(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "plugins/essentials.jar", "jar")

        names = _archive_names(server_dir, BackupType.PLUGINS)

        assert "plugins" in names
        assert not any(n.startswith("world") for n in names)

    def test_config_type_requires_no_dimension_folder(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        for name in CONFIG_FILES:
            _write(server_dir, name, f"cfg:{name}")

        names = _archive_names(server_dir, BackupType.CONFIG)

        assert set(CONFIG_FILES) <= set(names)
        assert "plugins" not in names

    def test_nether_type_raises_when_nether_folder_missing(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "only-overworld")

        with pytest.raises(FileNotFoundError, match="world_nether"):
            _archive_names(server_dir, BackupType.NETHER)

    def test_end_type_raises_when_end_folder_missing(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "world/level.dat", "only-overworld")

        with pytest.raises(FileNotFoundError, match="world_the_end"):
            _archive_names(server_dir, BackupType.END)

    def test_custom_primary_world(self, tmp_path: Path) -> None:
        server_dir = tmp_path / "server"
        _write(server_dir, "mypvp/level.dat", "pvp")
        _write(server_dir, "mypvp_nether/playerdata/x.dat", "npd")

        saga = BackupSaga(SagaOrchestrator())
        tar_path = str(server_dir / "out.tar.gz")
        saga._write_tar(
            tar_path, str(server_dir), primary_world="mypvp", backup_type=BackupType.WORLD,
        )
        with tarfile.open(tar_path, "r:gz") as tar:
            names = tar.getnames()

        assert "mypvp" in names
        assert "mcs_playerdata/mypvp_nether/playerdata" in names
