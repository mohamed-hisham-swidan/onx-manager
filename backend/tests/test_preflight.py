"""Tests for scripts/preflight.sh process reconciliation and preflight port resolution."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PREFLIGHT_SCRIPT = PROJECT_ROOT / "scripts" / "preflight.sh"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.preflight import resolve_preferred_backend_port  # noqa: E402

skip_on_win32 = pytest.mark.skipif(
    sys.platform == "win32",
    reason="preflight.sh is a POSIX bash script; not executed on Windows host",
)


def run_bash_preflight_fn(
    fn_name: str, *args: str, env_override: dict | None = None
) -> tuple[int, str]:
    """Source preflight.sh and invoke a specific bash function with args."""
    env = os.environ.copy()
    env["MCS_PROJECT_ROOT"] = str(PROJECT_ROOT)
    if env_override:
        env.update(env_override)

    arg_str = " ".join(f'"{a}"' for a in args)
    cmd = f'source "{PREFLIGHT_SCRIPT}" 2>/dev/null || true; {fn_name} {arg_str}'
    proc = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return proc.returncode, proc.stdout + proc.stderr


@skip_on_win32
def test_preflight_script_executable():
    assert PREFLIGHT_SCRIPT.exists(), f"preflight.sh not found at {PREFLIGHT_SCRIPT}"
    assert os.access(PREFLIGHT_SCRIPT, os.X_OK), "preflight.sh is not executable"


@skip_on_win32
def test_preflight_belongs_to_project_exclusions():
    """Verify that current process is recognized."""
    rc, _ = run_bash_preflight_fn("belongs_to_project", str(os.getpid()))
    # Current python test process is inside PROJECT_ROOT so belongs_to_project should return 0
    assert rc == 0


@skip_on_win32
def test_preflight_dry_run_success(tmp_path: Path):
    """Verify preflight.sh runs cleanly in smart mode without errors."""
    env = os.environ.copy()
    env["ONX_PROJECT_ROOT"] = str(tmp_path)
    env["ONX_BACKEND_PORT"] = "59180"
    env["ONX_FRONTEND_PORT"] = "59181"
    env["ONX_DB_PATH"] = str(tmp_path / "dummy_preflight.db")
    proc = subprocess.run(
        [str(PREFLIGHT_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"preflight.sh failed with stdout/err:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "onx-manager — Preflight" in proc.stdout
    assert "Smart reconciliation" in proc.stdout
    assert "Preflight Summary" in proc.stdout


@skip_on_win32
def test_preflight_force_clean_flag(tmp_path: Path):
    """Verify preflight.sh recognizes --restart / --stop as force clean mode."""
    dummy_db = tmp_path / "dummy_preflight.db"
    dummy_db.touch()
    env = os.environ.copy()
    env["ONX_PROJECT_ROOT"] = str(tmp_path)
    env["ONX_BACKEND_PORT"] = "59180"
    env["ONX_FRONTEND_PORT"] = "59181"
    env["ONX_DB_PATH"] = str(dummy_db)
    proc = subprocess.run(
        [str(PREFLIGHT_SCRIPT), "--restart"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    assert proc.returncode == 0, f"preflight.sh --restart failed:\n{proc.stdout}\n{proc.stderr}"
    assert "Mode: Force cleanup" in proc.stdout


@skip_on_win32
def test_preflight_db_lock_does_not_kill_pytest_workers(tmp_path: Path):
    """Confirm preflight.sh --restart does NOT kill a process matching pytest/xdist."""
    test_db = tmp_path / "locked_test.db"
    test_db.touch()

    code = (
        "import sqlite3, sys, time; "
        "conn = sqlite3.connect(sys.argv[1]); "
        "conn.execute('BEGIN EXCLUSIVE'); "
        "sys.stdout.write('LOCKED\\n'); sys.stdout.flush(); "
        "time.sleep(10)"
    )
    worker = subprocess.Popen(
        [sys.executable, "-c", code, str(test_db), "pytest_worker_sentinel"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = worker.stdout.readline()
        assert "LOCKED" in line

        env = os.environ.copy()
        env["ONX_PROJECT_ROOT"] = str(tmp_path)
        env["ONX_BACKEND_PORT"] = "59180"
        env["ONX_FRONTEND_PORT"] = "59181"
        env["ONX_DB_PATH"] = str(test_db)

        proc = subprocess.run(
            [str(PREFLIGHT_SCRIPT), "--restart"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=15,
        )

        assert proc.returncode == 0, f"preflight.sh failed:\n{proc.stdout}\n{proc.stderr}"
        assert "held by test worker" in proc.stdout
        assert worker.poll() is None
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=2)
        except subprocess.TimeoutExpired:
            worker.kill()


# ---------------------------------------------------------------------------
# Preflight Port Resolution Tests (Python & Bash Parity)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "config_val", "expected_port"),
    [
        ({"ONX_BACKEND_PORT": "8100", "MCS_BACKEND_PORT": "8200"}, 8300, 8100),
        ({"MCS_BACKEND_PORT": "8200"}, 8300, 8200),
        ({}, 8300, 8300),
        ({}, None, 8000),
    ],
)
def test_preflight_resolve_preferred_backend_port_precedence_chain(
    env: dict[str, str], config_val: int | None, expected_port: int, tmp_path: Path
):
    cfg_file = tmp_path / "config.json"
    if config_val is not None:
        cfg_file.write_text(json.dumps({"backend_port": config_val}), encoding="utf-8")
    warnings: list[str] = []
    port = resolve_preferred_backend_port(env=env, config_path=cfg_file, warn=warnings.append)
    assert port == expected_port
    assert warnings == []


def test_preflight_resolve_preferred_backend_port_onx_invalid_falls_through_to_mcs(tmp_path: Path):
    """Old short-circuit bug: invalid ONX evaluated truthy with 'or' and skipped MCS."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}), encoding="utf-8")
    warnings: list[str] = []
    env = {"ONX_BACKEND_PORT": "notanint", "MCS_BACKEND_PORT": "8200"}
    port = resolve_preferred_backend_port(env=env, config_path=cfg_file, warn=warnings.append)
    assert port == 8200
    assert len(warnings) == 1
    assert "ONX_BACKEND_PORT" in warnings[0]
    assert "notanint" in warnings[0]


def test_preflight_resolve_preferred_backend_port_both_invalid_falls_through_to_config(
    tmp_path: Path,
):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}), encoding="utf-8")
    warnings: list[str] = []
    env = {"ONX_BACKEND_PORT": "invalid", "MCS_BACKEND_PORT": "80"}
    port = resolve_preferred_backend_port(env=env, config_path=cfg_file, warn=warnings.append)
    assert port == 8300
    assert len(warnings) == 2
    assert "ONX_BACKEND_PORT" in warnings[0]
    assert "MCS_BACKEND_PORT" in warnings[1]


def test_preflight_resolve_preferred_backend_port_both_invalid_config_absent(tmp_path: Path):
    cfg_file = tmp_path / "nonexistent" / "config.json"
    warnings: list[str] = []
    env = {"ONX_BACKEND_PORT": "invalid", "MCS_BACKEND_PORT": "80"}
    port = resolve_preferred_backend_port(env=env, config_path=cfg_file, warn=warnings.append)
    assert port == 8000
    assert len(warnings) == 2
    assert "ONX_BACKEND_PORT" in warnings[0]
    assert "MCS_BACKEND_PORT" in warnings[1]


@pytest.mark.parametrize(
    ("raw_config_content", "expect_warn"),
    [
        (json.dumps({"backend_port": 80}), True),
        (json.dumps({"backend_port": 1023}), True),
        (json.dumps({"backend_port": 65536}), True),
        (json.dumps({"backend_port": "abc"}), True),
        (json.dumps({"backend_port": True}), True),
        (json.dumps({"backend_port": None}), True),
        (json.dumps([8000]), False),
        ("{broken json", False),
    ],
)
def test_preflight_resolve_preferred_backend_port_invalid_config(
    raw_config_content: str, expect_warn: bool, tmp_path: Path
):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(raw_config_content, encoding="utf-8")
    warnings: list[str] = []
    port = resolve_preferred_backend_port(env={}, config_path=cfg_file, warn=warnings.append)
    assert port == 8000
    if expect_warn:
        assert len(warnings) == 1
        assert "config backend_port" in warnings[0]
    else:
        assert warnings == []


@pytest.mark.parametrize(
    ("val", "expected_port", "valid"),
    [
        (" 8000 ", 8000, True),
        ("+8000", 8000, True),
        (" +8000 ", 8000, True),
        ("٨٠٠٠", 8000, False),
        ("８０００", 8000, False),
    ],
)
def test_preflight_resolve_preferred_backend_port_formats_and_unicode(
    val: str, expected_port: int, valid: bool, tmp_path: Path
):
    cfg_file = tmp_path / "config.json"
    warnings: list[str] = []
    port = resolve_preferred_backend_port(
        env={"ONX_BACKEND_PORT": val}, config_path=cfg_file, warn=warnings.append
    )
    assert port == expected_port
    if valid:
        assert warnings == []
    else:
        assert len(warnings) == 1
        assert "ONX_BACKEND_PORT" in warnings[0]


@skip_on_win32
@pytest.mark.parametrize(
    ("onx_val", "mcs_val", "cfg_val", "expected_port", "expected_warn_sources"),
    [
        ("8100", "8200", 8300, 8100, []),
        ("abc", "8200", 8300, 8200, ["ONX_BACKEND_PORT"]),
        ("abc", "80", 8300, 8300, ["ONX_BACKEND_PORT", "MCS_BACKEND_PORT"]),
        (None, None, None, 8000, []),
        (" +8000 ", None, None, 8000, []),
    ],
)
def test_preflight_bash_parity(
    onx_val: str | None,
    mcs_val: str | None,
    cfg_val: int | None,
    expected_port: int,
    expected_warn_sources: list[str],
    tmp_path: Path,
):
    cfg_file = tmp_path / "config.json"
    if cfg_val is not None:
        cfg_file.write_text(json.dumps({"backend_port": cfg_val}), encoding="utf-8")

    # 1. Test Python resolver
    py_env: dict[str, str] = {}
    if onx_val is not None:
        py_env["ONX_BACKEND_PORT"] = onx_val
    if mcs_val is not None:
        py_env["MCS_BACKEND_PORT"] = mcs_val
    py_warns: list[str] = []
    py_port = resolve_preferred_backend_port(
        env=py_env, config_path=cfg_file, warn=py_warns.append
    )
    assert py_port == expected_port

    # 2. Test Bash resolver via subprocess
    bash_env = os.environ.copy()
    bash_env["MCS_PROJECT_ROOT"] = str(PROJECT_ROOT)
    bash_env.pop("ONX_BACKEND_PORT", None)
    bash_env.pop("MCS_BACKEND_PORT", None)
    if onx_val is not None:
        bash_env["ONX_BACKEND_PORT"] = onx_val
    if mcs_val is not None:
        bash_env["MCS_BACKEND_PORT"] = mcs_val

    cmd = f'source "{PREFLIGHT_SCRIPT}" 2>/dev/null; resolve_preferred_backend_port "{cfg_file}"'
    proc = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=bash_env,
        timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == str(expected_port)
    for src in expected_warn_sources:
        assert src in proc.stderr
        assert any(src in w for w in py_warns)

