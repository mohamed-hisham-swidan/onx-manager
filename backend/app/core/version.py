from __future__ import annotations

import importlib.metadata
import tomllib
from functools import lru_cache
from pathlib import Path

from app.core.identity import IDENTITY

_DISTRIBUTION_NAME = IDENTITY.dist_name
_FALLBACK_VERSION = "0.1.0"


def _pyproject_path() -> Path:
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


def _read_pyproject_version() -> str | None:
    try:
        with _pyproject_path().open("rb") as fh:
            data = tomllib.load(fh)
        return data["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError):
        return None


@lru_cache(maxsize=1)
def get_app_version() -> str:
    pyproject_version = _read_pyproject_version()
    if pyproject_version is not None:
        return pyproject_version
    try:
        return importlib.metadata.version(_DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return _FALLBACK_VERSION
