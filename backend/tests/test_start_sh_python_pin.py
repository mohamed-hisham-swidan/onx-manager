"""Tests verifying Python 3.12 pinning contract in start.sh and scripts/bootstrap."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

START_SH = REPO_ROOT / "start.sh"
BOOTSTRAP_SH = REPO_ROOT / "scripts" / "bootstrap"

PROBE_STRING = "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
DELETION_TOKENS = ("rm -rf", "rm -r", "rmdir", "shutil", "Remove-Item")
PYTHON_INSTALLER_TOKENS = (
    "apt-get install",
    "dnf install",
    "pacman -S",
    "brew install",
    "uv python install",
)
VALID_312_TOKENS = ("python3.12", "python@3.12", "install 3.12")
NODE_TOKENS = ("nodejs", "npm", "node@")
STOP_LINE_PREFIXES = (
    "Python 3.12.x is required",
    "Install Python 3.12 with one of",
    "brew install python@3.12",
)

_SKIP_NON_BASH = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="Requires bash on non-win32 system",
)


def _read_text(path: Path) -> str:
    """Read text from file and normalize CRLF to LF."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _normalize_stop_line(line: str) -> str:
    """Normalize a stop message echo line across scripts."""
    s = line.strip()
    if s.endswith(">&2"):
        s = s[:-3].strip()
    if s.startswith("echo"):
        s = s[4:].strip()
    s = s.replace('"', "").replace("'", "").replace("✖", "").strip()
    return s


def _extract_stop_lines(text: str) -> list[str]:
    """Extract and normalize matching STOP text echo lines."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo") and any(p in stripped for p in STOP_LINE_PREFIXES):
            lines.append(_normalize_stop_line(stripped))
    return lines


# ==============================================================================
# Helper / Validator Functions (usable directly or for mutation checks)
# ==============================================================================


def check_start_sh_exists_and_has_exact_probe(text: str | None = None) -> None:
    if text is None:
        assert START_SH.is_file(), f"{START_SH} does not exist"
        text = _read_text(START_SH)
    assert PROBE_STRING in text, f"Exact probe string not found in start.sh: {PROBE_STRING}"


def check_start_sh_has_no_313_or_312plus_or_gte(text: str | None = None) -> None:
    if text is None:
        text = _read_text(START_SH)
    assert "python3.13" not in text, "Found forbidden 'python3.13' in start.sh"
    assert "3.12+" not in text, "Found forbidden '3.12+' in start.sh"
    assert ">= (3" not in text, "Found loose '>= (3' probe in start.sh"


def check_start_sh_never_deletes(text: str | None = None) -> None:
    if text is None:
        text = _read_text(START_SH)
    for token in DELETION_TOKENS:
        assert token not in text, f"start.sh must not contain deletion token: {token}"


def check_start_sh_python_installs_are_versioned(text: str | None = None) -> None:
    if text is None:
        text = _read_text(START_SH)
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Node.js install lines are excluded (they contain nodejs, npm, or node@)
        if any(node_tok in stripped for node_tok in NODE_TOKENS):
            continue
        if "install" in stripped and any(tok in stripped for tok in PYTHON_INSTALLER_TOKENS):
            assert any(ver in stripped for ver in VALID_312_TOKENS), (
                f"Line installs python without exact 3.12 pin: {line}"
            )
        if "pacman" in stripped:
            assert "python" not in stripped.lower(), f"pacman line mentions python: {line}"


def check_start_sh_installer_order(text: str | None = None) -> None:
    if text is None:
        text = _read_text(START_SH)
    idx_uv = text.find("uv python install")
    idx_apt = text.find("apt-get install")
    idx_dnf = text.find("dnf install")
    idx_brew = text.find("brew install python@3.12")
    assert idx_uv != -1, "uv python install not found"
    assert idx_apt != -1, "apt-get install not found"
    assert idx_dnf != -1, "dnf install not found"
    assert idx_brew != -1, "brew install python@3.12 not found"
    assert idx_uv < idx_apt < idx_dnf < idx_brew, (
        f"Installer order inverted: uv={idx_uv}, apt={idx_apt}, dnf={idx_dnf}, brew={idx_brew}"
    )


def check_start_sh_brew_branch_guarded_by_nonempty_prefix(text: str | None = None) -> None:
    if text is None:
        text = _read_text(START_SH)
    idx_brew = text.find("brew --prefix")
    assert idx_brew != -1, "brew --prefix not found"
    idx_guard = text.find('[ -n "$prefix" ]', idx_brew)
    assert idx_guard != -1, 'brew branch not guarded by [ -n "$prefix" ]'


def check_scripts_bootstrap_matches_start_sh_contract(
    boot_text: str | None = None,
    start_text: str | None = None,
) -> None:
    if boot_text is None:
        assert BOOTSTRAP_SH.is_file(), f"{BOOTSTRAP_SH} does not exist"
        boot_text = _read_text(BOOTSTRAP_SH)
    if start_text is None:
        start_text = _read_text(START_SH)

    if sys.platform != "win32":
        assert os.access(BOOTSTRAP_SH, os.X_OK), "scripts/bootstrap is not executable"

    assert PROBE_STRING in boot_text, "Exact probe string not in scripts/bootstrap"
    assert PROBE_STRING in start_text, "Exact probe string not in start.sh"

    assert not re.search(r"(?<![\$\w])python3\s+-m\s+venv", boot_text), (
        "scripts/bootstrap must not contain bare 'python3 -m venv'"
    )

    for token in DELETION_TOKENS:
        assert token not in boot_text, f"scripts/bootstrap must not contain {token}"

    assert "-L .venv/bin/python" in boot_text, (
        "scripts/bootstrap must check dangling symlink via -L .venv/bin/python"
    )

    start_stop = _extract_stop_lines(start_text)
    boot_stop = _extract_stop_lines(boot_text)
    assert len(start_stop) == 3, f"Expected 3 STOP lines in start.sh, found {len(start_stop)}"
    assert start_stop == boot_stop, f"STOP lines differ: {start_stop} != {boot_stop}"


def extract_bootstrap_check_script(boot_text: str | None = None) -> str:
    """Extract resolver block from scripts/bootstrap with venv creation replaced."""
    if boot_text is None:
        boot_text = _read_text(BOOTSTRAP_SH)
    start_marker = "PYTHON_EXACT_PROBE="
    end_marker = "source .venv/bin/activate"
    start_idx = boot_text.find(start_marker)
    if start_idx == -1:
        raise AssertionError(f"Marker {start_marker!r} not found in scripts/bootstrap")
    end_idx = boot_text.find(end_marker, start_idx)
    if end_idx == -1:
        raise AssertionError(f"Marker {end_marker!r} not found in scripts/bootstrap")
    block = boot_text[start_idx:end_idx]
    target = '"$PY312" -m venv .venv'
    if target not in block:
        raise AssertionError(f"Replacement target {target!r} not found in scripts/bootstrap block")
    return block.replace(target, 'echo "RESOLVED:$PY312"')


def create_stub(dir_path: Path, name: str, exit_code: int = 0) -> Path:
    """Create a minimal executable shell stub that exits with the given code."""
    dir_path.mkdir(parents=True, exist_ok=True)
    stub = dir_path / name
    stub.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def snapshot_tree(root: Path) -> dict[str, tuple[int, int, str | None, bytes | None]]:
    """Capture (size, mtime_ns, symlink_target, file_bytes) for every item in tree."""
    tree: dict[str, tuple[int, int, str | None, bytes | None]] = {}
    if not root.exists():
        return tree
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        st = p.lstat()
        is_sym = p.is_symlink()
        link_target = os.readlink(p) if is_sym else None
        content = p.read_bytes() if not is_sym and p.is_file() else None
        tree[rel] = (st.st_size, st.st_mtime_ns, link_target, content)
    return tree


def run_bootstrap_block(
    tmp_path: Path,
    stub_bin: Path,
    boot_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the extracted bootstrap resolver block in a hermetic environment."""
    bash_path = shutil.which("bash")
    if bash_path is None:
        pytest.skip("bash executable not found")
    check_sh = tmp_path / "check.sh"
    check_sh.write_text(extract_bootstrap_check_script(boot_text), encoding="utf-8")
    return subprocess.run(
        [bash_path, str(check_sh)],
        cwd=tmp_path,
        env={"PATH": str(stub_bin)},
        capture_output=True,
        text=True,
        timeout=20,
    )


# ==============================================================================
# Static Tests (1 to 8)
# ==============================================================================


def test_start_sh_exists_and_has_exact_probe() -> None:
    check_start_sh_exists_and_has_exact_probe()


def test_start_sh_has_no_313_or_312plus_or_gte() -> None:
    check_start_sh_has_no_313_or_312plus_or_gte()


def test_start_sh_never_deletes() -> None:
    check_start_sh_never_deletes()


def test_start_sh_python_installs_are_versioned() -> None:
    check_start_sh_python_installs_are_versioned()


def test_start_sh_installer_order() -> None:
    check_start_sh_installer_order()


def test_start_sh_brew_branch_guarded_by_nonempty_prefix() -> None:
    check_start_sh_brew_branch_guarded_by_nonempty_prefix()


def test_scripts_bootstrap_matches_start_sh_contract() -> None:
    check_scripts_bootstrap_matches_start_sh_contract()


@_SKIP_NON_BASH
def test_shell_scripts_pass_bash_n() -> None:
    bash_path = shutil.which("bash")
    assert bash_path is not None
    for script_path in (START_SH, BOOTSTRAP_SH):
        res = subprocess.run(
            [bash_path, "-n", str(script_path)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, f"bash -n failed on {script_path}: {res.stderr}"


# ==============================================================================
# Behavioral Tests (9 to 14)
# ==============================================================================


@_SKIP_NON_BASH
def test_bootstrap_python312_stub_success(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    stub = create_stub(bin_dir, "python3.12", exit_code=0)
    res = run_bootstrap_block(tmp_path, bin_dir)
    assert res.returncode == 0, f"Unexpected failure: {res.stderr}"
    assert f"RESOLVED:{stub}" in res.stdout


@_SKIP_NON_BASH
def test_bootstrap_all_stubs_exit_1_required_message(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    for name in ("python3.12", "python3", "python"):
        create_stub(bin_dir, name, exit_code=1)
    res = run_bootstrap_block(tmp_path, bin_dir)
    assert res.returncode == 1
    assert "Python 3.12.x is required" in res.stderr


@_SKIP_NON_BASH
def test_bootstrap_fallback_to_python3(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    stub = create_stub(bin_dir, "python3", exit_code=0)
    res = run_bootstrap_block(tmp_path, bin_dir)
    assert res.returncode == 0, f"Unexpected failure: {res.stderr}"
    assert f"RESOLVED:{stub}" in res.stdout


@_SKIP_NON_BASH
def test_bootstrap_existing_venv_wrong_version_rejected(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    create_stub(bin_dir, "python3.12", exit_code=0)
    venv_dir = tmp_path / ".venv"
    venv_bin = venv_dir / "bin"
    create_stub(venv_bin, "python", exit_code=1)
    (venv_dir / "pyvenv.cfg").write_text("home = /usr/bin\n", encoding="utf-8")

    before = snapshot_tree(venv_dir)
    res = run_bootstrap_block(tmp_path, bin_dir)
    after = snapshot_tree(venv_dir)

    assert res.returncode == 1
    assert "not Python 3.12" in res.stderr
    assert "RESOLVED" not in res.stdout
    assert before == after


@_SKIP_NON_BASH
def test_bootstrap_existing_venv_valid_preserved(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    create_stub(bin_dir, "python3.12", exit_code=0)
    venv_dir = tmp_path / ".venv"
    venv_bin = venv_dir / "bin"
    create_stub(venv_bin, "python", exit_code=0)

    res = run_bootstrap_block(tmp_path, bin_dir)
    assert res.returncode == 0, f"Unexpected failure: {res.stderr}"
    assert "RESOLVED" not in res.stdout


@_SKIP_NON_BASH
def test_bootstrap_dangling_venv_symlink_rejected(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    create_stub(bin_dir, "python3.12", exit_code=0)
    venv_dir = tmp_path / ".venv"
    venv_bin = venv_dir / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    dangling_py = venv_bin / "python"
    dangling_py.symlink_to("/nonexistent/target/path/to/python")

    cfg_file = venv_dir / "pyvenv.cfg"
    cfg_bytes = b"home = /usr/bin\nversion = 3.12.0\n"
    cfg_file.write_bytes(cfg_bytes)

    res = run_bootstrap_block(tmp_path, bin_dir)

    assert res.returncode == 1
    assert "not Python 3.12" in res.stderr
    assert cfg_file.read_bytes() == cfg_bytes
    assert dangling_py.is_symlink()
    assert not dangling_py.exists()
