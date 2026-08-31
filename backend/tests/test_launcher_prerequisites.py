"""Unit tests for Launcher Upfront Prerequisite Gate."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launcher import (
    LauncherConfig,
    ValidationError,
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
         patch("launcher.Validator.check_node", side_effect=ValidationError("Node.js is not installed")), \
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
         patch("launcher.Validator.check_node", side_effect=ValidationError("Node.js v16.0.0 is too old (need 18+)")), \
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
         patch("launcher.Validator.check_npm", side_effect=ValidationError("npm is not installed")), \
         patch("launcher.reconcile_database") as mock_reconcile:

        ok, python = validate_startup_prerequisites(cfg)
        assert ok is False
        assert python is None
        mock_reconcile.assert_not_called()
