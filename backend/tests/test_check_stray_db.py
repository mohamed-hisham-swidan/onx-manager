from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "check-stray-db"


def _load_module():
    loader = SourceFileLoader("check_stray_db", str(_SCRIPT_PATH))
    spec = spec_from_loader("check_stray_db", loader)
    assert spec is not None
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_find_stray_db_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    # Monkeypatch checked directories to isolated tmp_path
    monkeypatch.setattr(module, "_CHECK_DIRS", (tmp_path,))

    # Initially empty
    assert module.find_stray_db_files() == []

    # Add stray db file
    stray_db = tmp_path / "stray.db"
    stray_db.write_text("dummy")

    assert module.find_stray_db_files() == [stray_db]

    # Add stray wal and shm
    stray_wal = tmp_path / "another.db-wal"
    stray_wal.write_text("wal")
    stray_shm = tmp_path / "another.db-shm"
    stray_shm.write_text("shm")

    assert sorted(module.find_stray_db_files()) == sorted([stray_db, stray_wal, stray_shm])


def test_main_returns_0_when_clean() -> None:
    module = _load_module()

    # Currently clean in real repo
    assert module.main() == 0
