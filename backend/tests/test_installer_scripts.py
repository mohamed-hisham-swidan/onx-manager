"""Tests verifying Python 3.12 pinning and CLI/BOM contracts across installers and bootstrap."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

INSTALL_SH = REPO_ROOT / "install.sh"
INSTALL_PS1 = REPO_ROOT / "install.ps1"
BOOTSTRAP_SH = REPO_ROOT / "scripts" / "bootstrap"

PROBE_STRING = "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
DELETION_TOKENS = ("rm -rf", "rm -r", "rmdir", "shutil", "Remove-Item")
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
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _normalize_stop_line(line: str) -> str:
    s = line.strip()
    if s.endswith(">&2"):
        s = s[:-3].strip()
    if s.startswith("echo"):
        s = s[4:].strip()
    s = s.replace('"', "").replace("'", "").replace("✖", "").strip()
    return s


def _extract_stop_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo") and any(p in stripped for p in STOP_LINE_PREFIXES):
            lines.append(_normalize_stop_line(stripped))
    return lines


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
    dir_path.mkdir(parents=True, exist_ok=True)
    stub = dir_path / name
    stub.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    stub.chmod(0o755)
    return stub


def snapshot_tree(root: Path) -> dict[str, tuple[int, int, str | None, bytes | None]]:
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


def test_install_sh_exists_and_pins_python_312() -> None:
    assert INSTALL_SH.is_file(), f"{INSTALL_SH} does not exist"
    text = _read_text(INSTALL_SH)
    assert PROBE_STRING in text
    assert "3.12+" not in text
    assert "python3.13" not in text
    for token in DELETION_TOKENS:
        assert token not in text, f"install.sh must not contain {token}"
    assert "uv python install 3.12" in text
    assert "ONX_DEPLOYMENT_PROFILE" in text


def test_install_ps1_exists_with_bom_and_pins_python_312() -> None:
    assert INSTALL_PS1.is_file(), f"{INSTALL_PS1} does not exist"
    raw = INSTALL_PS1.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "install.ps1 must have UTF-8 BOM"
    text = raw.decode("utf-8-sig")
    assert "sys.version_info[:2] == (3,12)" in text
    assert "3.12+" not in text
    assert "3.13" not in text
    assert "uv python install 3.12" in text
    assert "ONX_DEPLOYMENT_PROFILE" in text


def test_scripts_bootstrap_matches_install_sh_contract() -> None:
    assert BOOTSTRAP_SH.is_file()
    boot_text = _read_text(BOOTSTRAP_SH)
    install_text = _read_text(INSTALL_SH)

    if sys.platform != "win32":
        assert os.access(BOOTSTRAP_SH, os.X_OK), "scripts/bootstrap is not executable"
        assert os.access(INSTALL_SH, os.X_OK), "install.sh is not executable"

    assert PROBE_STRING in boot_text
    assert PROBE_STRING in install_text
    assert not re.search(r"(?<![\$\w])python3\s+-m\s+venv", boot_text)
    for token in DELETION_TOKENS:
        assert token not in boot_text
    assert "-L .venv/bin/python" in boot_text

    install_stop = _extract_stop_lines(install_text)
    boot_stop = _extract_stop_lines(boot_text)
    assert len(install_stop) == 3
    assert install_stop == boot_stop


@_SKIP_NON_BASH
def test_shell_scripts_pass_bash_n() -> None:
    bash_path = shutil.which("bash")
    assert bash_path is not None
    for script_path in (INSTALL_SH, BOOTSTRAP_SH):
        res = subprocess.run(
            [bash_path, "-n", str(script_path)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, f"bash -n failed on {script_path}: {res.stderr}"


@_SKIP_NON_BASH
def test_install_sh_help_and_dry_run_modes(tmp_path: Path) -> None:
    bash_path = shutil.which("bash")
    assert bash_path is not None

    help_res = subprocess.run(
        [bash_path, str(INSTALL_SH), "--help"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert help_res.returncode == 0
    for flag in ("--mode", "--dir", "--port", "--yes", "--dry-run", "--uninstall"):
        assert flag in help_res.stdout

    vps_res = subprocess.run(
        [
            bash_path,
            str(INSTALL_SH),
            "--dry-run",
            "--mode=vps",
            f"--dir={tmp_path / 'vps'}",
            "--port=8080",
            "--yes",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert vps_res.returncode == 0, vps_res.stderr
    assert "ONX_DEPLOYMENT_PROFILE=vps" in vps_res.stdout
    assert "systemd" in vps_res.stdout

    local_res = subprocess.run(
        [
            bash_path,
            str(INSTALL_SH),
            "--dry-run",
            "--mode=local",
            f"--dir={tmp_path / 'local'}",
            "--port=8081",
            "--yes",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert local_res.returncode == 0, local_res.stderr
    assert "ONX_DEPLOYMENT_PROFILE=local" in local_res.stdout
    assert ".desktop" in local_res.stdout

    uninstall_res = subprocess.run(
        [bash_path, str(INSTALL_SH), "--uninstall", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert uninstall_res.returncode == 0, uninstall_res.stderr


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
