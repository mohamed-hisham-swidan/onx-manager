import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launcher import (  # noqa: E402
    LauncherConfig,
    ValidationError,
    Validator,
    _format_for_terminal,
    detect_unicode_support,
    render_line,
    validate_startup_prerequisites,
)


def test_prerequisites_all_pass():
    cfg = LauncherConfig(auto_install_deps=False)
    fake_python = Path("/fake/bin/python")

    with patch("launcher.ensure_python_environment", return_value=fake_python), \
         patch("launcher.Validator.check_python", return_value=("3.12.0", str(fake_python))), \
         patch("launcher.Validator.check_backend_deps", return_value=True), \
         patch("launcher.Validator.check_node", return_value="v20.11.0"), \
         patch("launcher.Validator.check_npm", return_value="10.2.4"), \
         patch("launcher.Validator.check_frontend_deps", return_value=True), \
         patch("launcher.reconcile_database", return_value=True):

        ok, python = validate_startup_prerequisites(cfg)
        assert ok is True
        assert python == fake_python


def test_prerequisites_fail_on_missing_node():
    cfg = LauncherConfig(auto_install_deps=False)
    fake_python = Path("/fake/bin/python")

    with patch("launcher.ensure_python_environment", return_value=fake_python), \
         patch("launcher.Validator.check_python", return_value=("3.12.0", str(fake_python))), \
         patch("launcher.Validator.check_backend_deps", return_value=True), \
         patch(
             "launcher.Validator.check_node",
             side_effect=ValidationError("Node.js is not installed"),
         ), \
         patch("launcher.reconcile_database") as mock_reconcile:

        ok, python = validate_startup_prerequisites(cfg)
        assert ok is False
        assert python is None
        # Verify that database reconciliation / backend startup was never called
        mock_reconcile.assert_not_called()


def test_prerequisites_fail_on_old_node():
    cfg = LauncherConfig(auto_install_deps=False)
    fake_python = Path("/fake/bin/python")

    with patch("launcher.ensure_python_environment", return_value=fake_python), \
         patch("launcher.Validator.check_python", return_value=("3.12.0", str(fake_python))), \
         patch("launcher.Validator.check_backend_deps", return_value=True), \
         patch(
             "launcher.Validator.check_node",
             side_effect=ValidationError("Node.js v16.0.0 is too old (need 18+)"),
         ), \
         patch("launcher.reconcile_database") as mock_reconcile:

        ok, python = validate_startup_prerequisites(cfg)
        assert ok is False
        assert python is None
        mock_reconcile.assert_not_called()


def test_prerequisites_fail_on_missing_npm():
    cfg = LauncherConfig(auto_install_deps=False)
    fake_python = Path("/fake/bin/python")

    with patch("launcher.ensure_python_environment", return_value=fake_python), \
         patch("launcher.Validator.check_python", return_value=("3.12.0", str(fake_python))), \
         patch("launcher.Validator.check_backend_deps", return_value=True), \
         patch("launcher.Validator.check_node", return_value="v20.11.0"), \
         patch(
             "launcher.Validator.check_npm",
             side_effect=ValidationError("npm is not installed"),
         ), \
         patch("launcher.reconcile_database") as mock_reconcile:

        ok, python = validate_startup_prerequisites(cfg)
        assert ok is False
        assert python is None
        mock_reconcile.assert_not_called()


def test_prerequisites_fail_on_missing_frontend_deps():
    cfg = LauncherConfig(auto_install_deps=False)
    fake_python = Path("/fake/bin/python")

    with patch("launcher.ensure_python_environment", return_value=fake_python), \
         patch("launcher.Validator.check_python", return_value=("3.12.0", str(fake_python))), \
         patch("launcher.Validator.check_backend_deps", return_value=True), \
         patch("launcher.Validator.check_node", return_value="v20.11.0"), \
         patch("launcher.Validator.check_npm", return_value="10.2.4"), \
         patch("launcher.Validator.check_frontend_deps", return_value=False), \
         patch("launcher.reconcile_database") as mock_reconcile:

        ok, python = validate_startup_prerequisites(cfg)
        assert ok is False
        assert python is None
        mock_reconcile.assert_not_called()


def test_detect_unicode_support_env_overrides():
    with patch.dict("os.environ", {"ONX_FORCE_ASCII": "1"}, clear=False):
        assert detect_unicode_support() is False

    with patch.dict("os.environ", {"ONX_FORCE_ASCII": "0", "ONX_FORCE_UNICODE": "1"}, clear=False):
        assert detect_unicode_support() is True

    with patch.dict("os.environ", {"ONX_FORCE_ASCII": "0", "WT_SESSION": "some-guid"}, clear=False):
        assert detect_unicode_support() is True


def test_ascii_glyph_fallback():
    with patch("launcher._unicode_enabled", False):
        raw_text = "✔ Backend running  ▸ Step 1  ═ Line  █ Block  ✖ Error  ⚠ Warn"
        formatted = _format_for_terminal(raw_text)
        assert "✔" not in formatted
        assert "▸" not in formatted
        assert "═" not in formatted
        assert "█" not in formatted
        assert "✖" not in formatted
        assert "⚠" not in formatted

        assert "[OK]" in formatted
        assert ">" in formatted
        assert "=" in formatted
        assert "#" in formatted
        assert "[X]" in formatted
        assert "[!]" in formatted

        line = render_line("═", 10)
        assert line == "=========="


def test_unicode_glyphs_preserved_when_supported():
    with patch("launcher._unicode_enabled", True):
        raw_text = "✔ Backend running  ▸ Step 1"
        formatted = _format_for_terminal(raw_text)
        assert "✔" in formatted
        assert "▸" in formatted


def test_validator_check_npm_timeout_distinction():
    with patch("launcher.find_or_activate_node"), \
         patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["npm", "--version"], 20)):
        with pytest.raises(ValidationError) as exc_info:
            Validator.check_npm(timeout_sec=20)
        assert "timed out after 20 seconds" in str(exc_info.value)
        assert exc_info.value.fix is not None
        assert "antivirus" in exc_info.value.fix or "npm --version" in exc_info.value.fix


def test_validator_check_npm_not_found_distinction():
    with patch("launcher.find_or_activate_node"), \
         patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(ValidationError) as exc_info:
            Validator.check_npm()
        assert "npm is not installed" in str(exc_info.value)
        assert "reinstall Node.js" in (exc_info.value.fix or "")


def test_validator_check_npm_execution_failure_distinction():
    mock_res = MagicMock(returncode=1, stdout="", stderr="npm ERR! missing script")
    with patch("launcher.find_or_activate_node"), \
         patch("subprocess.run", return_value=mock_res):
        with pytest.raises(ValidationError) as exc_info:
            Validator.check_npm()
        assert "npm execution failed (exit code 1)" in str(exc_info.value)


def test_validator_check_npm_retry_success():
    mock_ok = MagicMock(returncode=0, stdout="10.8.2\n", stderr="")
    with patch("launcher.find_or_activate_node"), \
         patch("os.name", "nt"), \
         patch(
             "subprocess.run",
             side_effect=[subprocess.TimeoutExpired(["npm", "--version"], 20), mock_ok],
         ):
        ver = Validator.check_npm(timeout_sec=20)
        assert ver == "10.8.2"
