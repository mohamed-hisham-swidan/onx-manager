from __future__ import annotations

import importlib.machinery
import json
import subprocess
import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check-version-propagation"

_MODULE_NAME = "check_version_propagation"


def _load_checker() -> pytest.Module:
    loader = importlib.machinery.SourceFileLoader(_MODULE_NAME, str(_SCRIPT))
    spec = importlib.util.spec_from_loader(_MODULE_NAME, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def checker():
    return _load_checker()


def _write_fixtures(  # noqa: PLR0913
    tmp_path: Path,
    pyproject_version: str,
    package_version: str,
) -> tuple[Path, Path]:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        f'[project]\nname = "onx-manager"\nversion = "{pyproject_version}"\n',
        encoding="utf-8",
    )
    package = tmp_path / "package.json"
    package.write_text(
        json.dumps({"name": "onx-frontend", "version": package_version}),
        encoding="utf-8",
    )
    return pyproject, package


def test_matching_versions_pass(checker) -> None:
    agree, report = checker.check("0.1.0", "0.1.0", "0.1.0")
    assert agree is True
    assert "pyproject.toml: 0.1.0" in report
    assert "package.json: 0.1.0" in report
    assert "runtime: 0.1.0" in report
    assert report.endswith("PASS")


def test_pyproject_package_mismatch_fails(checker) -> None:
    agree, report = checker.check("0.2.0", "0.1.0", "0.1.0")
    assert agree is False
    assert report.endswith("FAIL")


def test_runtime_mismatch_fails(checker) -> None:
    agree, report = checker.check("0.1.0", "0.1.0", "0.2.0")
    assert agree is False
    assert report.endswith("FAIL")


def _args(pyproject: Path, package: Path, runtime: str) -> list[str]:
    return [
        "--pyproject",
        str(pyproject),
        "--package-json",
        str(package),
        "--runtime-version",
        runtime,
    ]


def test_main_ok_on_matching_fixtures(tmp_path: Path, checker) -> None:
    pyproject, package = _write_fixtures(tmp_path, "0.1.0", "0.1.0")
    rc = checker.main(_args(pyproject, package, "0.1.0"))
    assert rc == 0


def test_main_fails_on_pyproject_package_mismatch(tmp_path: Path, checker) -> None:
    pyproject, package = _write_fixtures(tmp_path, "0.2.0", "0.1.0")
    rc = checker.main(_args(pyproject, package, "0.1.0"))
    assert rc == 1


def test_main_fails_on_runtime_mismatch(tmp_path: Path, checker) -> None:
    pyproject, package = _write_fixtures(tmp_path, "0.1.0", "0.1.0")
    rc = checker.main(_args(pyproject, package, "0.2.0"))
    assert rc == 1


def test_actual_ci_invocation_passes() -> None:
    """Run the script exactly as CI will: real sources + real runtime probe."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "PASS" in result.stdout
    keys = ("pyproject.toml: ", "package.json: ", "runtime: ")
    values = [
        line.split(":", 1)[1].strip()
        for line in result.stdout.splitlines()
        if any(line.startswith(k) for k in keys)
    ]
    assert len(values) == 3
    assert len(set(values)) == 1, f"propagated versions disagree: {values}"
