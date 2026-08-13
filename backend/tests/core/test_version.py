import importlib.metadata
import re
from pathlib import Path

import pytest

from app.core import version
from app.core.version import get_app_version

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_APP_DIR = _BACKEND_DIR / "app"
_EXCLUDED_FILES = {
    "app/core/version.py",
    "app/modules/plugin/infrastructure/manifest.py",
}


@pytest.fixture(autouse=True)
def _clear_version_cache() -> None:
    version.get_app_version.cache_clear()
    yield
    version.get_app_version.cache_clear()


def test_pyproject_value_wins_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version, "_read_pyproject_version", lambda: "9.9.9")
    assert get_app_version() == "9.9.9"


def test_metadata_used_when_pyproject_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(version, "_read_pyproject_version", lambda: None)
    assert get_app_version() == importlib.metadata.version("mcs-manager")


def test_emergency_fallback_when_both_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(version, "_read_pyproject_version", lambda: None)
    monkeypatch.setattr(version.importlib.metadata, "version", _raise)
    assert get_app_version() == "4.0.0"


def test_resolver_is_cached() -> None:
    assert version.get_app_version.cache_info().maxsize == 1


def test_shipped_pyproject_parses_with_tomllib() -> None:
    pyproject_path = version._pyproject_path()
    assert pyproject_path.exists()
    assert version._read_pyproject_version() == "4.0.0"


def test_single_source_matches_installed_metadata() -> None:
    assert get_app_version() == importlib.metadata.version("mcs-manager")
    assert get_app_version() == "4.0.0"


@pytest.mark.parametrize("path", [p for p in (_APP_DIR).rglob("*.py")])
def test_no_hardcoded_version_literal_outside_allowed_files(path: Path) -> None:
    rel = path.relative_to(_BACKEND_DIR).as_posix()
    if rel in _EXCLUDED_FILES:
        pytest.skip(reason=f"allows a centralized fallback/plugin floor: {rel}")
    content = path.read_text()
    assert re.search(r'"4\.0\.0"', content) is None, f"hardcoded app version in {rel}"
