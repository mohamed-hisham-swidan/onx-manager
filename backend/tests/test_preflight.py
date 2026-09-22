"""Tests for scripts/preflight.sh process reconciliation and ownership logic."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="preflight.sh is a POSIX bash script; not executed on Windows host",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PREFLIGHT_SCRIPT = PROJECT_ROOT / "scripts" / "preflight.sh"


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


def test_preflight_script_executable():
    assert PREFLIGHT_SCRIPT.exists(), f"preflight.sh not found at {PREFLIGHT_SCRIPT}"
    assert os.access(PREFLIGHT_SCRIPT, os.X_OK), "preflight.sh is not executable"


def test_preflight_belongs_to_project_exclusions():
    """Verify that current process is recognized."""
    rc, _ = run_bash_preflight_fn("belongs_to_project", str(os.getpid()))
    # Current python test process is inside PROJECT_ROOT so belongs_to_project should return 0
    assert rc == 0


def test_preflight_dry_run_success():
    """Verify preflight.sh runs cleanly in smart mode without errors."""
    proc = subprocess.run(
        [str(PREFLIGHT_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"preflight.sh failed with stdout/err:\n{proc.stdout}\n{proc.stderr}"
    )
    assert "onx-manager — Preflight" in proc.stdout
    assert "Smart reconciliation" in proc.stdout
    assert "Preflight Summary" in proc.stdout


def test_preflight_force_clean_flag(tmp_path: Path):
    """Verify preflight.sh recognizes --restart / --stop as force clean mode."""
    dummy_db = tmp_path / "dummy_preflight.db"
    dummy_db.touch()
    env = os.environ.copy()
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

