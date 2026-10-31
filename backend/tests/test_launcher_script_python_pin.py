import re
import sys
from pathlib import Path

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launcher import PYTHON_INSTALLER_VERSION  # noqa: E402

START_PS1 = REPO_ROOT / "start.ps1"


def _read_start_ps1_text() -> str:
    return START_PS1.read_text(encoding="utf-8")


def test_start_ps1_has_bom():
    raw = START_PS1.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "start.ps1 must start with UTF-8 BOM bytes EF BB BF"


def test_start_ps1_venv_probe():
    text = _read_start_ps1_text()
    # Extract lines around $venvPy check
    venv_block_match = re.search(
        r"if\s*\(Test-Path\s+\$venvPy\)\s*\{(.*?)\}\s*if\s*\(-not\s+\$venvValid\)",
        text,
        re.DOTALL,
    )
    assert venv_block_match is not None, "Could not isolate venv trust block in start.ps1"
    venv_block = venv_block_match.group(1)

    assert "Invoke-OnxProcessProbe" in venv_block
    assert "-TimeoutMs" in venv_block
    assert "sys.version_info[:2] == (3,12)" in venv_block
    assert "$res.Success" in venv_block or "$probe.Success" in venv_block


def test_start_ps1_has_no_313():
    text = _read_start_ps1_text()
    assert "3.13" not in text, "Found unexpected '3.13' in start.ps1"


def test_start_ps1_has_no_312plus():
    text = _read_start_ps1_text()
    assert "3.12+" not in text, "Found unexpected '3.12+' in start.ps1"


def test_start_ps1_has_no_3124():
    text = _read_start_ps1_text()
    assert "3.12.4" not in text, "Found stale installer version '3.12.4' in start.ps1"


def test_start_ps1_has_no_gte_probe():
    text = _read_start_ps1_text()
    assert ">= (3," not in text, "Found loose '>= (3,' probe in start.ps1"
    assert ">= (3,12)" not in text, "Found loose '>= (3,12)' probe in start.ps1"


def test_start_ps1_uses_exact_312_probe():
    text = _read_start_ps1_text()
    assert "sys.version_info[:2] == (3,12)" in text


def test_start_ps1_has_no_remove_or_recurse():
    text = _read_start_ps1_text()
    assert "Remove-Item" not in text, "start.ps1 must not contain Remove-Item"
    assert "-Recurse" not in text, "start.ps1 must not contain -Recurse"


def test_start_ps1_no_bare_foundcmd_python_after_install():
    text = _read_start_ps1_text()
    assert not re.search(r"\$foundCmd\s*=\s*['\"]python['\"]", text), (
        "start.ps1 must not assign bare $foundCmd = 'python'"
    )


def test_start_ps1_prefers_per_user_install():
    text = _read_start_ps1_text()
    assert "InstallAllUsers=0" in text
    assert "InstallAllUsers=1" in text
    per_user_idx = text.find("InstallAllUsers=0")
    system_wide_idx = text.find("InstallAllUsers=1")
    assert per_user_idx < system_wide_idx, "Per-user install must precede system-wide install"


def test_start_ps1_single_installer_version_variable():
    text = _read_start_ps1_text()
    match = re.search(
        r"\$(?:pythonInstallerVersion|PYTHON_INSTALLER_VERSION)\s*=\s*['\"]([^'\"]+)['\"]",
        text,
    )
    assert match is not None, "Could not find installer version variable in start.ps1"
    version_in_ps1 = match.group(1)
    assert version_in_ps1 == PYTHON_INSTALLER_VERSION
    assert version_in_ps1 == "3.12.8"

    # URL and installer path must derive from this variable
    assert "ftp/python/$pythonInstallerVersion/python-$pythonInstallerVersion-amd64.exe" in text
    assert "python-$pythonInstallerVersion-amd64.exe" in text


def test_start_ps1_reprobes_after_install():
    text = _read_start_ps1_text()
    assert "LOCALAPPDATA" in text
    assert "ProgramFiles" in text
    assert "Python312" in text
    assert "py" in text
    assert "-3.12" in text
    assert "sys.executable" in text


def test_start_ps1_has_stop_message():
    text = _read_start_ps1_text()
    assert "Python 3.12.x was not found or could not be installed" in text
    assert "re-run start.bat" in text
    assert "throw" in text
