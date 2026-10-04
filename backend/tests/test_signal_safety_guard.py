import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import _ORIGINAL_OS_KILL


def test_guard_blocks_unrelated_pid_kill():
    """Unrelated PID signaling must be blocked and raise AssertionError without sending signals."""
    unrelated_pid = 999999
    with pytest.raises(AssertionError, match=r"real os\.kill\(999999, .*\) blocked in tests"):
        os.kill(unrelated_pid, signal.SIGTERM)


@pytest.mark.skipif(sys.platform == "win32", reason="os.killpg is POSIX only")
def test_guard_blocks_unrelated_pgid_killpg():
    """Unrelated PGID signaling must be blocked and raise AssertionError."""
    unrelated_pgid = 999999
    with pytest.raises(AssertionError, match=r"real os\.killpg\(999999, .*\) blocked in tests"):
        os.killpg(unrelated_pgid, signal.SIGTERM)


def test_guard_allows_descendant_child_kill():
    """Descendant child process spawned by test must be signalable."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        assert proc.poll() is None
        # Must succeed without raising AssertionError
        os.kill(proc.pid, signal.SIGTERM)
        proc.wait(timeout=3.0)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()


@pytest.mark.allow_real_signals
def test_guard_opt_out_marker():
    """Tests marked with allow_real_signals retain original os.kill without wrapper."""
    assert os.kill is _ORIGINAL_OS_KILL


def _check_file_for_banned_signal_patterns(file_path: Path) -> list[tuple[int, str, str]]:
    """Scan a Python file for banned bypass patterns:
    - from os import kill/killpg
    - signal.raise_signal / signal.pthread_kill
    - psutil.Process(...).kill() / .terminate()
    """
    import ast
    violations: list[tuple[int, str, str]] = []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except Exception as exc:
        violations.append((0, "parse_error", f"Could not parse file: {exc}"))
        return violations

    for node in ast.walk(tree):
        # 1. from os import kill / killpg
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            for alias in node.names:
                if alias.name in ("kill", "killpg"):
                    violations.append((
                        node.lineno,
                        "banned_import",
                        f"Banned 'from os import {alias.name}' bypasses os.kill/killpg guard",
                    ))

        # 2. signal.raise_signal or signal.pthread_kill
        if isinstance(node, ast.Attribute) and node.attr in ("raise_signal", "pthread_kill"):
            violations.append((
                node.lineno,
                "banned_signal_function",
                f"Banned use of signal.{node.attr}",
            ))
        if isinstance(node, ast.ImportFrom) and node.module == "signal":
            for alias in node.names:
                if alias.name in ("raise_signal", "pthread_kill"):
                    violations.append((
                        node.lineno,
                        "banned_signal_function",
                        f"Banned 'from signal import {alias.name}'",
                    ))

        # 3. psutil.Process(...).kill() or psutil.Process(...).terminate()
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("kill", "terminate")
        ):
            target = node.func.value
            if isinstance(target, ast.Call):
                target_func = target.func
                if (
                    (isinstance(target_func, ast.Attribute) and target_func.attr == "Process")
                    or (isinstance(target_func, ast.Name) and target_func.id in ("Process",))
                ):
                    violations.append((
                        node.lineno,
                        "banned_psutil_kill",
                        f"Banned direct call to psutil.Process(...).{node.func.attr}()",
                    ))

    return violations


def test_repo_wide_no_banned_signal_bypass_patterns():
    """Verify repo app/ and tests/ contain no banned signal bypass patterns unless in allowlist."""
    import json

    backend_dir = Path(__file__).resolve().parents[1]
    app_dir = backend_dir / "app"
    tests_dir = backend_dir / "tests"
    allowlist_path = backend_dir / "tests" / "signal_bypass_allowlist.json"

    allowed: set[tuple[str, int, str] | tuple[str, str]] = set()
    if allowlist_path.exists():
        data = json.loads(allowlist_path.read_text(encoding="utf-8"))
        for item in data.get("allowed_bypasses", []):
            if "line" in item:
                allowed.add((item.get("file", ""), int(item["line"]), item.get("pattern", "")))
            else:
                allowed.add((item.get("file", ""), item.get("pattern", "")))

    all_violations: list[str] = []
    for search_dir in (app_dir, tests_dir):
        for py_file in search_dir.rglob("*.py"):
            rel_path = str(py_file.relative_to(backend_dir)).replace("\\", "/")
            file_violations = _check_file_for_banned_signal_patterns(py_file)
            for lineno, pattern, desc in file_violations:
                is_allowed = (
                    (rel_path, lineno, pattern) in allowed or (rel_path, pattern) in allowed
                )
                if not is_allowed:
                    all_violations.append(f"{rel_path}:{lineno} [{pattern}] {desc}")

    assert not all_violations, (
        f"Found {len(all_violations)} banned signal bypass pattern(s):\n"
        + "\n".join(all_violations)
        + "\nTo resolve: refactor to use guarded pathways or add to signal_bypass_allowlist.json"
    )


def test_scanner_detects_banned_patterns(tmp_path: Path):
    """Verify scanner identifies banned import, signal function, and psutil calls."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text(
        "from os import kill\n"
        "import signal\n"
        "signal.raise_signal(signal.SIGTERM)\n"
        "signal.pthread_kill(1, 2)\n"
        "import psutil\n"
        "psutil.Process(123).kill()\n"
        "psutil.Process(123).terminate()\n"
    )
    violations = _check_file_for_banned_signal_patterns(bad_file)
    patterns = {p for _, p, _ in violations}
    assert "banned_import" in patterns
    assert "banned_signal_function" in patterns
    assert "banned_psutil_kill" in patterns
