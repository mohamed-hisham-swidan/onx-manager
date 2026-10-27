"""Tests for dynamic backend port selection and port classification.

SPEC: docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md
ADR: docs/decisions/0019-dynamic-backend-port.md
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

import pytest

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launcher import (  # noqa: E402
    BACKEND_PORT,
    ConfigManager,
    ErrorHandler,
    LauncherConfig,
    PIDManager,
    PortDecision,
    PortManager,
    PortState,
    ProvenanceStatus,
    StatusDisplay,
    TerminalOpener,
    _backend_supervisor_pid,
    _capture_process_create_time,
    _check_backend_provenance,
    _clear_backend_pid_if,
    _generate_attempt_token,
    _handle_own_unhealthy,
    _has_bind_error,
    _parse_preferred_port,
    _read_backend_log_from,
    _stat_file_identity,
    _verify_process_identity,
    _wait_for_backend_attempt,
    _write_attempt_marker,
    ask_yes_no,
    check_backend_health,
    cmd_stop,
    get_effective_backend_port,
    start_backend,
    start_frontend,
)


def test_preferred_port_free_uses_preferred():
    callback = MagicMock(return_value=False)
    with patch.object(PortManager, "can_bind", return_value=True):
        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )
    assert decision == PortDecision(port=8000, reuse=False, source="preferred")
    callback.assert_not_called()


def test_foreign_live_port_falls_back_and_never_signals():
    callback = MagicMock(return_value=False)

    def fake_can_bind(port: int, _host: str = "0.0.0.0") -> bool:
        return port != 8000

    with patch.object(PortManager, "can_bind", side_effect=fake_can_bind), \
         patch.object(PortManager, "get_pid_by_port", return_value=12345), \
         patch.object(PortManager, "belongs_to_project", return_value=False), \
         patch("launcher.check_backend_health", return_value=False), \
         patch.object(PortManager, "kill_on_port") as mock_kill:

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision == PortDecision(port=8001, reuse=False, source="scan")
    callback.assert_not_called()
    mock_kill.assert_not_called()


def test_foreign_health_200_wrong_payload_falls_back():
    callback = MagicMock(return_value=False)

    def fake_can_bind(port: int, _host: str = "0.0.0.0") -> bool:
        return port != 8000

    with patch.object(PortManager, "can_bind", side_effect=fake_can_bind), \
         patch.object(PortManager, "get_pid_by_port", return_value=9999), \
         patch.object(PortManager, "belongs_to_project", return_value=False), \
         patch("launcher.check_backend_health", return_value=False):

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision == PortDecision(port=8001, reuse=False, source="scan")
    callback.assert_not_called()


def test_own_healthy_backend_is_reused():
    callback = MagicMock(return_value=False)

    with patch.object(PortManager, "can_bind", return_value=False), \
         patch.object(PortManager, "get_pid_by_port", return_value=4321), \
         patch.object(PortManager, "belongs_to_project", return_value=True), \
         patch("launcher.check_backend_health", return_value=True):

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision == PortDecision(port=8000, reuse=True, source="preferred")
    callback.assert_not_called()


def test_reuse_probes_active_port_with_non_default_preferred():
    callback = MagicMock(return_value=False)

    def fake_health(port: int, timeout: float = 2.0) -> bool:
        _ = timeout
        # A revert to the constant 8000 URL must fail this test
        return port == 8123

    with patch.object(PortManager, "can_bind", return_value=False), \
         patch.object(PortManager, "get_pid_by_port", return_value=4321), \
         patch.object(PortManager, "belongs_to_project", return_value=True), \
         patch("launcher.check_backend_health", side_effect=fake_health):

        decision = PortManager.resolve_startup_port(
            preferred=8123,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision == PortDecision(port=8123, reuse=True, source="preferred")


def test_known_active_healthy_reused_when_preferred_foreign():
    callback = MagicMock(return_value=False)

    def fake_classify(port: int, health_timeout: float = 2.0) -> PortState:
        _ = health_timeout
        if port == 8000:
            return PortState.FOREIGN
        if port == 8001:
            return PortState.OWN_HEALTHY
        return PortState.FREE

    with patch.object(PortManager, "classify_backend_port", side_effect=fake_classify):
        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=8001,
            on_own_unhealthy=callback,
        )

    assert decision == PortDecision(port=8001, reuse=True, source="known-active")
    callback.assert_not_called()


def test_scan_reuses_healthy_own_candidate():
    callback = MagicMock(return_value=False)

    def fake_classify(port: int, health_timeout: float = 2.0) -> PortState:
        _ = health_timeout
        if port == 8000:
            return PortState.FOREIGN
        if port == 8001:
            return PortState.OWN_HEALTHY
        return PortState.FREE

    with patch.object(PortManager, "classify_backend_port", side_effect=fake_classify):
        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision == PortDecision(port=8001, reuse=True, source="scan")
    callback.assert_not_called()


def test_scan_unhealthy_own_candidate_prompts_and_does_not_skip():
    # Sub-case A: declined -> abort (None, does not skip to 8002)
    callback_decline = MagicMock(return_value=False)

    def fake_classify(port: int, health_timeout: float = 2.0) -> PortState:
        _ = health_timeout
        if port == 8000:
            return PortState.FOREIGN
        if port == 8001:
            return PortState.OWN_UNHEALTHY
        return PortState.FREE

    with patch.object(PortManager, "classify_backend_port", side_effect=fake_classify):
        decision_declined = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback_decline,
        )

    assert decision_declined is None
    callback_decline.assert_called_once_with(8001)

    # Sub-case B: accepted -> port freed -> reuse=False on 8001
    freed = False

    def fake_classify_freed(port: int, health_timeout: float = 2.0) -> PortState:
        _ = health_timeout
        nonlocal freed
        if port == 8000:
            return PortState.FOREIGN
        if port == 8001:
            return PortState.FREE if freed else PortState.OWN_UNHEALTHY
        return PortState.FREE

    def on_unhealthy(port: int) -> bool:
        _ = port
        nonlocal freed
        freed = True
        return True

    with patch.object(PortManager, "classify_backend_port", side_effect=fake_classify_freed):
        decision_freed = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=on_unhealthy,
        )

    assert decision_freed == PortDecision(port=8001, reuse=False, source="scan")


def test_own_unhealthy_backend_prompts_and_aborts_on_decline():
    callback = MagicMock(return_value=False)

    with patch.object(PortManager, "classify_backend_port", return_value=PortState.OWN_UNHEALTHY):
        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision is None
    callback.assert_called_once_with(8000)


def test_own_unhealthy_backend_uses_preferred_after_confirmed_kill():
    freed = False

    def fake_classify(port: int, health_timeout: float = 2.0) -> PortState:
        _ = port
        _ = health_timeout
        nonlocal freed
        return PortState.FREE if freed else PortState.OWN_UNHEALTHY

    def on_unhealthy(port: int) -> bool:
        _ = port
        nonlocal freed
        freed = True
        return True

    with patch.object(PortManager, "classify_backend_port", side_effect=fake_classify):
        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=on_unhealthy,
        )

    assert decision == PortDecision(port=8000, reuse=False, source="preferred")


def test_stale_pid_file_is_cleared_and_preferred_reused(tmp_path):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir()
    pid_file = mcs_dir / "backend.pid"
    pid_file.write_text("99999\n")
    port_file = mcs_dir / "backend.port"
    port_file.write_text("8001\n")

    callback = MagicMock(return_value=False)

    with patch("launcher.MCS_DIR", mcs_dir), \
         patch.object(PIDManager, "is_alive", return_value=False), \
         patch.object(PortManager, "classify_backend_port") as mock_classify:

        mock_classify.return_value = PortState.FREE

        PIDManager.cleanup_stale()
        assert not pid_file.exists()

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=PIDManager.read_active_port(),
            on_own_unhealthy=callback,
        )

        assert decision == PortDecision(port=8000, reuse=False, source="preferred")
        assert not port_file.exists()


def test_live_wrapper_without_listener_does_not_fake_reuse():
    callback = MagicMock(return_value=False)

    def fake_can_bind(port: int, _host: str = "0.0.0.0") -> bool:
        return port != 8000

    with patch.object(PortManager, "can_bind", side_effect=fake_can_bind), \
         patch.object(PortManager, "get_pid_by_port", return_value=5555), \
         patch.object(PortManager, "belongs_to_project", return_value=False), \
         patch("launcher.check_backend_health", return_value=False):

        state = PortManager.classify_backend_port(8000)
        assert state == PortState.FOREIGN

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )
        assert decision == PortDecision(port=8001, reuse=False, source="scan")


def test_unknown_owner_with_non_panel_health_falls_back():
    callback = MagicMock(return_value=False)

    def fake_can_bind(port: int, _host: str = "0.0.0.0") -> bool:
        return port != 8000

    with patch.object(PortManager, "can_bind", side_effect=fake_can_bind), \
         patch.object(PortManager, "get_pid_by_port", return_value=None), \
         patch("launcher.check_backend_health", return_value=False):

        state = PortManager.classify_backend_port(8000)
        assert state == PortState.UNKNOWN

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )
        assert decision == PortDecision(port=8001, reuse=False, source="scan")


def test_resolved_non_project_pid_with_panel_signature_is_not_reused():
    callback = MagicMock(return_value=False)

    def fake_can_bind(port: int, _host: str = "0.0.0.0") -> bool:
        return port != 8000

    with patch.object(PortManager, "can_bind", side_effect=fake_can_bind), \
         patch.object(PortManager, "get_pid_by_port", return_value=6666), \
         patch.object(PortManager, "belongs_to_project", return_value=False), \
         patch("launcher.check_backend_health", return_value=True):

        state = PortManager.classify_backend_port(8000)
        assert state == PortState.FOREIGN

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )
        assert decision == PortDecision(port=8001, reuse=False, source="scan")


def test_unresolved_pid_with_panel_signature_is_reused_with_warning():
    callback = MagicMock(return_value=False)

    with patch.object(PortManager, "can_bind", return_value=False), \
         patch.object(PortManager, "get_pid_by_port", return_value=None), \
         patch("launcher.check_backend_health", return_value=True):

        state = PortManager.classify_backend_port(8000)
        assert state == PortState.HEALTHY_UNVERIFIED

        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )
        assert decision == PortDecision(port=8000, reuse=True, source="preferred")


def test_scan_exhaustion_aborts_with_no_unchecked_fallback(tmp_path):
    callback = MagicMock(return_value=False)

    with patch("launcher.MCS_DIR", tmp_path / ".onx"), \
         patch("launcher.PROJECT_ROOT", tmp_path), \
         patch.object(PortManager, "classify_backend_port", return_value=PortState.FOREIGN):
        decision = PortManager.resolve_startup_port(
            preferred=8000,
            known_active=None,
            on_own_unhealthy=callback,
        )

    assert decision is None


def test_can_bind_rejects_held_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name == "posix":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 0))
        port = s.getsockname()[1]
        s.listen(1)

        assert not PortManager.can_bind(port)

    assert PortManager.can_bind(port)


def test_active_port_file_lifecycle(tmp_path):
    mcs_dir = tmp_path / ".onx"
    with patch("launcher.MCS_DIR", mcs_dir), \
         patch("launcher.PROJECT_ROOT", tmp_path):

        assert PIDManager.read_active_port() is None

        PIDManager.write_active_port(8001)
        assert (mcs_dir / "backend.port").read_text() == "8001\n"
        assert PIDManager.read_active_port() == 8001

        PIDManager.clear_active_port()
        assert not (mcs_dir / "backend.port").exists()
        assert PIDManager.read_active_port() is None

        (mcs_dir / "backend.port").write_text("invalid\n")
        assert PIDManager.read_active_port() is None

        (mcs_dir / "backend.port").write_text("99999\n")
        assert PIDManager.read_active_port() is None

        PIDManager.clear_active_port()
        legacy_mcs = tmp_path / ".mcs"
        legacy_mcs.mkdir()
        (legacy_mcs / "backend.port").write_text("8002\n")
        assert PIDManager.read_active_port() == 8002

        PIDManager.clear_active_port()
        assert not (legacy_mcs / "backend.port").exists()


def test_check_backend_health_signature():
    class FakeResponse:
        def __init__(self, status: int, body: bytes):
            self.status = status
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    # 1. Valid panel JSON
    resp_ok = FakeResponse(200, b'{"status": "ok", "version": "0.1.0"}')
    with patch("urllib.request.urlopen", return_value=resp_ok):
        assert check_backend_health(8000) is True

    # 2. Status ok but missing version
    resp_no_ver = FakeResponse(200, b'{"status": "ok"}')
    with patch("urllib.request.urlopen", return_value=resp_no_ver):
        assert check_backend_health(8000) is False

    # 3. Status not ok
    resp_bad_status = FakeResponse(200, b'{"status": "error", "version": "0.1.0"}')
    with patch("urllib.request.urlopen", return_value=resp_bad_status):
        assert check_backend_health(8000) is False

    # 4. HTTP 401
    resp_401 = FakeResponse(401, b'Unauthorized')
    with patch("urllib.request.urlopen", return_value=resp_401):
        assert check_backend_health(8000) is False

    # 5. Invalid JSON
    resp_bad_json = FakeResponse(200, b'Not JSON')
    with patch("urllib.request.urlopen", return_value=resp_bad_json):
        assert check_backend_health(8000) is False

    # 6. Network error
    with patch("urllib.request.urlopen", side_effect=URLError("Connection refused")):
        assert check_backend_health(8000) is False


def test_belongs_to_project_heuristics(tmp_path):
    with patch("launcher.PROJECT_ROOT", tmp_path):
        # Exclusions: daemon keywords
        with patch("psutil.Process") as mock_proc:
            p = mock_proc.return_value
            p.cmdline.return_value = ["/usr/bin/java", "-jar", "server.jar"]
            p.cwd.return_value = str(tmp_path)
            p.exe.return_value = "/usr/bin/java"
            assert not PortManager.belongs_to_project(1001)

        with patch("psutil.Process") as mock_proc:
            p = mock_proc.return_value
            p.cmdline.return_value = ["playit"]
            p.cwd.return_value = str(tmp_path)
            p.exe.return_value = ""
            assert not PortManager.belongs_to_project(1002)

        # Exclusions: server data directory
        server_dir = tmp_path / "backend" / "data" / "servers" / "srv1"
        with patch("psutil.Process") as mock_proc:
            p = mock_proc.return_value
            p.cmdline.return_value = ["node", "index.js"]
            p.cwd.return_value = str(server_dir)
            p.exe.return_value = ""
            assert not PortManager.belongs_to_project(1003)

        # Match: project root in cwd
        with patch("psutil.Process") as mock_proc:
            p = mock_proc.return_value
            p.cmdline.return_value = ["python", "-m", "something"]
            p.cwd.return_value = str(tmp_path / "backend")
            p.exe.return_value = ""
            assert PortManager.belongs_to_project(1004)

        # Match: project marker in cmdline
        with patch("psutil.Process") as mock_proc:
            p = mock_proc.return_value
            p.cmdline.return_value = ["uvicorn", "app.main:app"]
            p.cwd.return_value = "/var/unrelated"
            p.exe.return_value = ""
            assert PortManager.belongs_to_project(1005)

        # Unrelated
        with patch("psutil.Process") as mock_proc:
            p = mock_proc.return_value
            p.cmdline.return_value = ["nginx", "-g", "daemon off;"]
            p.cwd.return_value = "/etc/nginx"
            p.exe.return_value = "/usr/sbin/nginx"
            assert not PortManager.belongs_to_project(1006)


def test_start_backend_spawns_on_resolved_port_with_panel_env(tmp_path):
    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    decision = PortDecision(port=8001, reuse=False, source="scan")

    with patch("launcher.MCS_DIR", tmp_path / ".onx"), \
         patch("launcher.PROJECT_ROOT", tmp_path), \
         patch("launcher.BACKEND_LOG", tmp_path / "backend.log"), \
         patch.object(PortManager, "resolve_startup_port", return_value=decision), \
         patch("launcher.get_canonical_db_url", return_value="sqlite:///test.db"), \
         patch("launcher.TerminalOpener.open_backend", return_value=4242) as mock_open, \
         patch("launcher._wait_for_backend_attempt", return_value="healthy"), \
         patch("launcher.Spinner"):

        assert start_backend(cfg, Path("/fake/python")) is True

    assert cfg.active_backend_port == 8001
    args, kwargs = mock_open.call_args
    assert args[1] == 8001
    assert args[2]["ONX_PANEL_BIND_PORT"] == "8001"


def test_start_backend_retries_only_on_bind_failure(tmp_path):
    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    decisions = [
        PortDecision(port=8001, reuse=False, source="scan"),
        PortDecision(port=8002, reuse=False, source="scan"),
    ]

    with patch("launcher.MCS_DIR", tmp_path / ".onx"), \
         patch("launcher.PROJECT_ROOT", tmp_path), \
         patch("launcher.BACKEND_LOG", tmp_path / "backend.log"), \
         patch.object(PortManager, "resolve_startup_port", side_effect=decisions), \
         patch("launcher.get_canonical_db_url", return_value="sqlite:///test.db"), \
         patch("launcher.TerminalOpener.open_backend", return_value=4242) as mock_open, \
         patch("launcher._wait_for_backend_attempt", side_effect=["bind", "healthy"]), \
         patch("launcher.Spinner"):

        assert start_backend(cfg, Path("/fake/python")) is True

    assert [call_args.args[1] for call_args in mock_open.call_args_list] == [8001, 8002]
    assert cfg.active_backend_port == 8002


def test_start_backend_timeout_is_not_retried(tmp_path):
    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    decision = PortDecision(port=8001, reuse=False, source="scan")
    killed_pids: list[int] = []

    with patch("launcher.MCS_DIR", tmp_path / ".onx"), \
         patch("launcher.PROJECT_ROOT", tmp_path), \
         patch("launcher.BACKEND_LOG", tmp_path / "backend.log"), \
         patch.object(PortManager, "resolve_startup_port", return_value=decision), \
         patch("launcher.get_canonical_db_url", return_value="sqlite:///test.db"), \
         patch("launcher.TerminalOpener.open_backend", return_value=4242) as mock_open, \
         patch("launcher._wait_for_backend_attempt", return_value="timeout"), \
         patch("launcher.Spinner"), \
         patch("launcher._capture_process_create_time", return_value=None), \
         patch.object(PIDManager, "is_alive", return_value=True), \
         patch.object(PIDManager, "kill_tree", side_effect=killed_pids.append):

        assert start_backend(cfg, Path("/fake/python")) is False

    assert mock_open.call_count == 1
    assert killed_pids == [4242]
    assert (tmp_path / ".onx" / "backend.port").exists() is False
    assert (tmp_path / ".onx" / "backend.pid").exists() is False
    with patch("launcher.MCS_DIR", tmp_path / ".onx"):
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None


def test_status_does_not_report_foreign_port_as_backend_running():
    with patch.object(PIDManager, "read", return_value=None), \
         patch.object(PortManager, "is_open", return_value=True), \
         patch.object(PortManager, "get_pid_by_port", return_value=12345), \
         patch("launcher.check_backend_health", return_value=False):

        info = StatusDisplay._collect_service("backend", 8000, verify_backend=True)

    assert info.running is False
    assert info.pid is None


def test_effective_backend_port_ignores_stale_active_port():
    with patch.object(PIDManager, "read_active_port", return_value=8001), \
         patch("launcher.check_backend_health", return_value=False):

        assert get_effective_backend_port(8000) == 8000


def test_ask_yes_no_eof_returns_false_even_when_default_true(monkeypatch):
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))
    assert ask_yes_no("Prompt?", default=True) is False

    monkeypatch.setattr("builtins.input", MagicMock(side_effect=KeyboardInterrupt))
    assert ask_yes_no("Prompt?", default=True) is False

    monkeypatch.setattr("builtins.input", lambda _: "")
    assert ask_yes_no("Prompt?", default=True) is True
    assert ask_yes_no("Prompt?", default=False) is False


def test_handle_own_unhealthy_eof_does_not_call_kill_on_port(monkeypatch, tmp_path):
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))
    mock_kill = MagicMock(return_value=True)
    monkeypatch.setattr(PortManager, "kill_on_port", mock_kill)

    result = _handle_own_unhealthy(8000)

    assert result is False
    mock_kill.assert_not_called()


def test_error_handler_eof_does_not_retry(monkeypatch):
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))
    mock_retry = MagicMock(return_value=True)

    result = ErrorHandler.show("Error occurred", retry_cb=mock_retry)

    assert result is False
    mock_retry.assert_not_called()


def test_start_frontend_eof_does_not_kill_port(monkeypatch, tmp_path):
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=EOFError))
    monkeypatch.setattr(PortManager, "is_open", lambda port: port == 5173)
    monkeypatch.setattr("launcher.check_frontend_ready", lambda: False)
    monkeypatch.setattr(PortManager, "get_pid_by_port", lambda port: 9876 if port == 5173 else None)
    mock_kill = MagicMock(return_value=True)
    monkeypatch.setattr(PortManager, "kill_on_port", mock_kill)

    cfg = LauncherConfig(frontend_port=5173, auto_install_deps=False, open_browser=False)
    result = start_frontend(cfg)

    assert result is False
    mock_kill.assert_not_called()


def test_backend_wrapper_uses_append_tee(tmp_path):
    log_file = tmp_path / "backend.log"
    wrapped = TerminalOpener._wrap_command("uvicorn app.main:app", log_file)
    if os.name == "nt":
        assert wrapped == "uvicorn app.main:app"
    else:
        assert f"2>&1 | tee -a '{log_file}'; exec bash" in wrapped


def test_backend_wrapper_appends_to_existing_log(tmp_path):
    if sys.platform == "win32":
        pytest.skip("tee -a wrapper is POSIX-specific; Windows uses cmd_str directly")
    log_file = tmp_path / "backend.log"
    log_file.write_text("existing initial content\n", encoding="utf-8")

    marker_token = _write_attempt_marker(log_file, 1)
    wrapped = TerminalOpener._wrap_command("echo 'new appended line'", log_file)

    subprocess.run(
        ["bash", "-c", wrapped],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=5,
        check=True,
    )
    content = log_file.read_text(encoding="utf-8")
    assert "existing initial content\n" in content
    assert marker_token in content
    marker_pos = content.find(marker_token)
    appended_pos = content.find("new appended line")
    assert marker_pos != -1
    assert appended_pos > marker_pos


def test_wait_for_backend_attempt_detects_bind_error_when_log_shrank(monkeypatch, tmp_path):
    log_file = tmp_path / "backend.log"
    monkeypatch.setattr("launcher.BACKEND_LOG", log_file)
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # Long initial log
    log_file.write_text("Initial log output that was quite long\n" * 20, encoding="utf-8")
    identity = _stat_file_identity(log_file)
    assert identity[2] > 200

    # Log is truncated/rewritten with attempt marker and bind error text (much shorter)
    token = "tok-shrunk-attempt-2"
    log_file.write_text(
        f"--- ONX LAUNCH ATTEMPT 2 (2026-10-21 12:00:00) [token:{token}] ---\n"
        "[ERROR] [uvicorn.error] [Errno 98] Address already in use\n",
        encoding="utf-8",
    )
    assert log_file.stat().st_size < identity[2]

    monkeypatch.setattr("launcher.check_backend_health", lambda _port: False)
    monkeypatch.setattr(PIDManager, "is_alive", lambda _pid: True)

    outcome = _wait_for_backend_attempt(
        port=8000,
        pid=12345,
        timeout=0.2,
        log_identity=identity,
        marker_token=token,
    )
    assert outcome == "bind"


def test_wait_for_backend_attempt_detects_bind_error_on_inode_replacement(monkeypatch, tmp_path):
    log_file = tmp_path / "backend.log"
    monkeypatch.setattr("launcher.BACKEND_LOG", log_file)
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # Old file with saved size (e.g. 350 bytes)
    old_content = "Initial log line from previous run\n" * 10
    log_file.write_text(old_content, encoding="utf-8")
    identity = _stat_file_identity(log_file)
    saved_size = identity[2]
    assert saved_size > 0

    token = "tok-inode-attempt-2"
    marker_line = f"--- ONX LAUNCH ATTEMPT 2 (2026-10-21 12:00:00) [token:{token}] ---\n"
    error_line = "[ERROR] [uvicorn.error] [Errno 98] Address already in use\n"
    prefix = marker_line + error_line
    assert len(prefix.encode("utf-8")) < saved_size

    # Filler after bind-error text: saved_size falls INSIDE filler, new file > saved_size
    filler = "Subsequent clean log output after startup\n" * 15
    new_content = prefix + filler
    assert len(new_content.encode("utf-8")) > saved_size

    new_file = tmp_path / "new_backend.log"
    new_file.write_text(new_content, encoding="utf-8")
    os.replace(new_file, log_file)

    new_identity = _stat_file_identity(log_file)
    assert new_identity[1] != identity[1]  # inode changed
    assert new_identity[2] > saved_size    # larger than saved size (shrink cannot trigger)

    monkeypatch.setattr("launcher.check_backend_health", lambda _port: False)
    monkeypatch.setattr(PIDManager, "is_alive", lambda _pid: True)

    outcome = _wait_for_backend_attempt(
        port=8000,
        pid=12345,
        timeout=0.2,
        log_identity=identity,
        marker_token=token,
    )
    assert outcome == "bind"


def test_wait_for_backend_attempt_detects_bind_error_on_rotation_to_larger(monkeypatch, tmp_path):
    log_file = tmp_path / "backend.log"
    monkeypatch.setattr("launcher.BACKEND_LOG", log_file)
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # Old file with saved size (e.g. 350 bytes)
    old_content = "Pre-rotation initial log content\n" * 10
    log_file.write_text(old_content, encoding="utf-8")
    identity = _stat_file_identity(log_file)
    saved_size = identity[2]
    assert saved_size > 0

    token = "tok-rot-attempt-2"
    marker_line = f"--- ONX LAUNCH ATTEMPT 2 (2026-10-21 12:00:00) [token:{token}] ---\n"
    error_line = "[ERROR] [uvicorn.error] [Errno 98] Address already in use\n"
    prefix = marker_line + error_line
    assert len(prefix.encode("utf-8")) < saved_size

    # Filler after bind-error text: saved_size falls inside filler, new file > saved_size
    filler = "Subsequent clean log output after startup\n" * 15
    new_content = prefix + filler
    assert len(new_content.encode("utf-8")) > saved_size

    # Real rotation: rename old file away, create new file at path
    rotated_file = tmp_path / "backend.log.1"
    log_file.rename(rotated_file)
    log_file.write_text(new_content, encoding="utf-8")

    new_identity = _stat_file_identity(log_file)
    assert new_identity[1] != identity[1]  # different inode
    assert new_identity[2] > saved_size    # larger size

    monkeypatch.setattr("launcher.check_backend_health", lambda _port: False)
    monkeypatch.setattr(PIDManager, "is_alive", lambda _pid: True)

    outcome = _wait_for_backend_attempt(
        port=8000,
        pid=12345,
        timeout=0.2,
        log_identity=identity,
        marker_token=token,
    )
    assert outcome == "bind"


def test_wait_for_backend_attempt_excludes_stale_markers_from_older_attempts(monkeypatch, tmp_path):
    log_file = tmp_path / "backend.log"
    monkeypatch.setattr("launcher.BACKEND_LOG", log_file)
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # Initial log has older attempt marker and bind error
    token_old = "tok-stale-attempt-1"
    token_new = "tok-clean-attempt-2"

    # Suppose between attempts the log shrank or was rotated (causing a reset to 0)
    # The file contains the old error followed by the new attempt marker, but NO new error
    log_file.write_text(
        f"--- ONX LAUNCH ATTEMPT 1 (2026-10-21 10:00:00) [token:{token_old}] ---\n"
        "[ERROR] [uvicorn.error] Address already in use\n"
        f"--- ONX LAUNCH ATTEMPT 2 (2026-10-21 10:01:00) [token:{token_new}] ---\n"
        "INFO: Uvicorn running on http://127.0.0.1:8000\n",
        encoding="utf-8",
    )
    # Capture saved identity as larger than current size or distinct inode to force reset_to_zero
    saved_identity = (log_file.stat().st_dev, log_file.stat().st_ino, 10000)

    monkeypatch.setattr("launcher.check_backend_health", lambda _port: False)
    monkeypatch.setattr(PIDManager, "is_alive", lambda _pid: True)

    outcome = _wait_for_backend_attempt(
        port=8000,
        pid=12345,
        timeout=0.2,
        log_identity=saved_identity,
        marker_token=token_new,
    )
    # With token logic: only parses text after token_new -> no bind error -> returns "timeout"
    # Without token logic: parses from offset 0 -> finds stale "Address already in use"
    # -> returns "bind"
    assert outcome == "timeout"


def test_f2_reader_resets_to_zero_ignores_preceding_stale_marker(monkeypatch, tmp_path):
    log_file = tmp_path / "backend.log"
    monkeypatch.setattr("launcher.BACKEND_LOG", log_file)
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # Case A: Shrink triggers reset to 0
    token_a = "tok-case-a"
    log_file.write_text(
        "stale line: Address already in use\n"
        f"--- ONX LAUNCH ATTEMPT 2 [token:{token_a}] ---\n"
        "clean current attempt log\n",
        encoding="utf-8",
    )
    shrunk_identity = (log_file.stat().st_dev, log_file.stat().st_ino, 99999)
    res_a = _read_backend_log_from(shrunk_identity, marker_token=token_a)
    assert "clean current attempt log\n" in res_a
    assert "Address already in use" not in res_a
    assert not _has_bind_error(res_a)

    # If token is not found after reset to 0, returns empty string ("no evidence")
    res_missing = _read_backend_log_from(shrunk_identity, marker_token="tok-not-in-file")
    assert res_missing == ""

    # Case B: Inode rotation to larger file triggers reset to 0
    token_b = "tok-case-b"
    log_file.write_text(
        "stale line: Address already in use\n"
        f"--- ONX LAUNCH ATTEMPT 2 [token:{token_b}] ---\n"
        "more clean log output\n",
        encoding="utf-8",
    )
    rotated_identity = (log_file.stat().st_dev, 1234567, 10)  # different inode, smaller saved_size
    res_b = _read_backend_log_from(rotated_identity, marker_token=token_b)
    assert "more clean log output\n" in res_b
    assert "Address already in use" not in res_b
    assert not _has_bind_error(res_b)


def test_f2_real_bind_error_end_to_end(monkeypatch, tmp_path):
    log_file = tmp_path / "backend.log"
    monkeypatch.setattr("launcher.BACKEND_LOG", log_file)
    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # Write marker and capture identity
    token = _write_attempt_marker(log_file, 1)
    identity = _stat_file_identity(log_file)

    # Ephemeral unused port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # Spawn real child writing the real bind-error text into log_file after marker
    code = (
        "import time; "
        f"fh = open(r'{log_file}', 'a', encoding='utf-8'); "
        "fh.write('[ERROR] [uvicorn.error] [Errno 98] Address already in use\\n'); "
        "fh.flush(); "
        "time.sleep(1)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code])
    try:
        outcome = _wait_for_backend_attempt(
            port=port,
            pid=proc.pid,
            timeout=2.0,
            log_identity=identity,
            marker_token=token,
        )
        assert outcome == "bind"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def test_start_backend_writes_marker_before_capturing_identity(monkeypatch, tmp_path):
    call_order = []
    fake_token = "tok-test-forwarded"
    captured_wait_kwargs = {}

    def fake_write_marker(_path, _attempt, _token=None):
        call_order.append("write_marker")
        return fake_token

    def fake_stat_identity(_path):
        call_order.append("stat_identity")
        return (1, 2, 3)

    def fake_wait(*_args, **kwargs):
        captured_wait_kwargs.update(kwargs)
        return "healthy"

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    decision = PortDecision(port=8001, reuse=False, source="scan")

    monkeypatch.setattr("launcher.MCS_DIR", tmp_path / ".onx")
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda **_: decision)
    monkeypatch.setattr("launcher.get_canonical_db_url", lambda: "sqlite:///test.db")
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_, **__: 4242)
    monkeypatch.setattr("launcher._wait_for_backend_attempt", fake_wait)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._write_attempt_marker", fake_write_marker)
    monkeypatch.setattr("launcher._stat_file_identity", fake_stat_identity)

    result = start_backend(cfg, Path("/fake/python"))
    assert result is True
    assert call_order == ["write_marker", "stat_identity"]
    assert captured_wait_kwargs.get("marker_token") == fake_token


def test_generate_attempt_token_unique():
    tokens = [_generate_attempt_token() for _ in range(1000)]
    assert len(tokens) == len(set(tokens))
    for t in tokens:
        assert t.startswith("tok-")


def test_reader_api_requires_marker_token_and_rejects_missing():
    with pytest.raises(TypeError):
        _read_backend_log_from((1, 2, 3))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        _wait_for_backend_attempt(8000, 1234, 0.1, (1, 2, 3))  # type: ignore[call-arg]


@pytest.fixture
def clean_config_env(monkeypatch, tmp_path):
    for var in ("ONX_BACKEND_PORT", "MCS_BACKEND_PORT", "BACKEND_PORT"):
        monkeypatch.delenv(var, raising=False)
    fake_mcs = tmp_path / ".onx"
    fake_mcs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", fake_mcs)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")
    ConfigManager._instance = None
    try:
        yield fake_mcs
    finally:
        ConfigManager._instance = None


def test_load_precedence_onx_over_mcs_and_file(monkeypatch, clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}))
    monkeypatch.setenv("ONX_BACKEND_PORT", "8100")
    monkeypatch.setenv("MCS_BACKEND_PORT", "8200")

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8100
    assert cfg.configured_backend_port == 8300


def test_load_precedence_mcs_over_file(monkeypatch, clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}))
    monkeypatch.delenv("ONX_BACKEND_PORT", raising=False)
    monkeypatch.setenv("MCS_BACKEND_PORT", "8200")

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8200
    assert cfg.configured_backend_port == 8300


@pytest.mark.usefixtures("clean_config_env")
def test_load_invalid_env_is_ignored_with_warning(monkeypatch):
    warnings = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)
    monkeypatch.setenv("ONX_BACKEND_PORT", "notanint")
    monkeypatch.setenv("MCS_BACKEND_PORT", "8200")

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8200
    assert any("ONX_BACKEND_PORT" in w and "notanint" in w for w in warnings)


@pytest.mark.parametrize("invalid_port", ["80", "1023", "65536", "-1"])
def test_load_rejects_preferred_ports_outside_1024_65535(
    invalid_port, monkeypatch, clean_config_env
):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}))
    warnings = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)
    monkeypatch.setenv("ONX_BACKEND_PORT", invalid_port)

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8300
    assert cfg.configured_backend_port == 8300
    assert any("ONX_BACKEND_PORT" in w and invalid_port in w for w in warnings)


def test_load_allows_active_ports_in_1_65535(clean_config_env):
    (clean_config_env / "backend.port").write_text("80\n")
    assert PIDManager.read_active_port() == 80


def test_save_does_not_persist_env_override(monkeypatch, clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8000}))
    monkeypatch.setenv("ONX_BACKEND_PORT", "8123")

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8123
    assert cfg.configured_backend_port == 8000
    ConfigManager.instance().save()

    data = json.loads(cfg_file.read_text())
    assert data["backend_port"] == 8000


def test_launcher_config_default_configured_backend_port():
    cfg = LauncherConfig(auto_install_deps=False)
    assert cfg.configured_backend_port == BACKEND_PORT
    assert cfg.auto_install_deps is False


def test_config_manager_update_sets_configured_backend_port(monkeypatch, clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8000}))
    monkeypatch.setenv("ONX_BACKEND_PORT", "8123")
    warnings = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8123

    ConfigManager.instance().update(backend_port=8400)
    assert any("ONX_BACKEND_PORT" in w and "8400" in w for w in warnings)
    assert cfg.configured_backend_port == 8400
    assert cfg.backend_port == 8123

    ConfigManager.instance().save()
    data = json.loads(cfg_file.read_text())
    assert data["backend_port"] == 8400


def test_frontend_env_contains_active_backend_port(monkeypatch):
    captured_env = None

    def fake_open(_title, _cmd, _log_file, extra_env=None, _geometry=None):
        nonlocal captured_env
        captured_env = extra_env
        return 1234

    monkeypatch.setattr(TerminalOpener, "_open", fake_open)
    TerminalOpener.open_frontend(backend_port=8050)
    assert captured_env == {"ONX_BACKEND_PORT": "8050"}


def test_f3_precedence_four_sources_chain(monkeypatch, clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}))

    # 1. ONX overrides all
    monkeypatch.setenv("ONX_BACKEND_PORT", "8100")
    monkeypatch.setenv("MCS_BACKEND_PORT", "8200")
    ConfigManager._instance = None
    cfg1 = ConfigManager.instance().load()
    assert cfg1.backend_port == 8100
    assert cfg1.configured_backend_port == 8300

    # 2. MCS overrides config and default
    monkeypatch.delenv("ONX_BACKEND_PORT", raising=False)
    ConfigManager._instance = None
    cfg2 = ConfigManager.instance().load()
    assert cfg2.backend_port == 8200
    assert cfg2.configured_backend_port == 8300

    # 3. Config overrides default
    monkeypatch.delenv("MCS_BACKEND_PORT", raising=False)
    ConfigManager._instance = None
    cfg3 = ConfigManager.instance().load()
    assert cfg3.backend_port == 8300
    assert cfg3.configured_backend_port == 8300

    # 4. Default applies when config absent
    cfg_file.unlink()
    ConfigManager._instance = None
    cfg4 = ConfigManager.instance().load()
    assert cfg4.backend_port == BACKEND_PORT
    assert cfg4.configured_backend_port == BACKEND_PORT


@pytest.mark.usefixtures("clean_config_env")
@pytest.mark.parametrize(
    "invalid_val",
    ["notanint", "0", "80", "1023", "65536", "-1", "", " "],
)
def test_f3_invalid_env_values_warn_and_fall_through(invalid_val, monkeypatch):
    monkeypatch.setenv("ONX_BACKEND_PORT", invalid_val)
    monkeypatch.setenv("MCS_BACKEND_PORT", "8200")
    warnings = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8200
    assert any("ONX_BACKEND_PORT" in w and invalid_val in w for w in warnings)


def test_f3_save_preserves_config_port_under_env_override(monkeypatch, clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8300}))
    monkeypatch.setenv("ONX_BACKEND_PORT", "8301")

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8301
    assert cfg.configured_backend_port == 8300

    ConfigManager.instance().save()
    assert cfg.configured_backend_port == 8300
    data = json.loads(cfg_file.read_text())
    assert data["backend_port"] == 8300


def test_f3_launcher_config_positional_construction():
    cfg9 = LauncherConfig(8100, 5200, False, True, True, False, 45, 8105, 8100)
    assert cfg9.backend_port == 8100
    assert cfg9.frontend_port == 5200
    assert cfg9.open_browser is False
    assert cfg9.open_swagger is True
    assert cfg9.open_vscode is True
    assert cfg9.auto_install_deps is False
    assert cfg9.startup_timeout == 45
    assert cfg9.active_backend_port == 8105
    assert cfg9.configured_backend_port == 8100

    cfg8 = LauncherConfig(8100, 5200, False, True, True, False, 45, 8105)
    assert cfg8.configured_backend_port == BACKEND_PORT


def test_f3_config_manager_update_without_env_override(clean_config_env):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": 8000}))

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8000
    assert cfg.configured_backend_port == 8000

    ConfigManager.instance().update(backend_port=8400)
    assert cfg.configured_backend_port == 8400
    assert cfg.backend_port == 8400

    ConfigManager.instance().save()
    data = json.loads(cfg_file.read_text())
    assert data["backend_port"] == 8400


@pytest.mark.parametrize(
    "invalid_port",
    [80, 1023, 65536, "abc", -5, True, None],
)
def test_load_invalid_config_port_warns_and_falls_back(
    invalid_port, monkeypatch, clean_config_env
):
    cfg_file = clean_config_env / "config.json"
    cfg_file.write_text(json.dumps({"backend_port": invalid_port}))
    warnings = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == 8000
    assert cfg.configured_backend_port == 8000
    assert any("config backend_port" in w for w in warnings)


@pytest.mark.parametrize(
    ("config_port", "expected_port"),
    [
        (8300, 8300),
        (None, 8000),
    ],
)
def test_load_both_env_invalid_falls_through_to_config(
    config_port, expected_port, monkeypatch, clean_config_env
):
    if config_port is not None:
        cfg_file = clean_config_env / "config.json"
        cfg_file.write_text(json.dumps({"backend_port": config_port}))
    monkeypatch.setenv("ONX_BACKEND_PORT", "notanint")
    monkeypatch.setenv("MCS_BACKEND_PORT", "80")
    warnings = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = ConfigManager.instance().load()
    assert cfg.backend_port == expected_port
    assert cfg.configured_backend_port == expected_port
    assert len(warnings) == 2
    assert any("ONX_BACKEND_PORT" in w and "notanint" in w for w in warnings)
    assert any("MCS_BACKEND_PORT" in w and "80" in w for w in warnings)


def test_parse_preferred_port_rejects_unicode_digits():
    assert _parse_preferred_port("٨٠٠٠") is None
    assert _parse_preferred_port("８０００") is None
    assert _parse_preferred_port("8000") == 8000
    assert _parse_preferred_port(" 8000 ") == 8000
    assert _parse_preferred_port("+8000") == 8000


# ═══════════════════════════════════════════════════════════════════════
# Batch B1 (F1): Stop Path Ownership Guards & Process Identity Revalidation
# ═══════════════════════════════════════════════════════════════════════


def _find_foreign_python() -> str:
    candidates = [
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            resolved = str(Path(cand).resolve()).lower()
            if "onx-manager" not in resolved and "mcs-manager" not in resolved:
                return cand
    return sys.executable


def test_cmd_stop_does_not_signal_foreign_listener_from_active_port(tmp_path, monkeypatch):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        active_port = s.getsockname()[1]

    foreign_py = _find_foreign_python()
    outside_dir = tempfile.mkdtemp()
    code = (
        "import socket, time\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {active_port}))\n"
        "s.listen(1)\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    child = subprocess.Popen([foreign_py, "-c", code], cwd=outside_dir)
    try:
        for _ in range(50):
            if PortManager.get_pid_by_port(active_port) == child.pid:
                break
            time.sleep(0.05)

        if PortManager.get_pid_by_port(active_port) != child.pid:
            pytest.skip("Cannot attribute listener PID on this host")
        assert PortManager.get_pid_by_port(active_port) == child.pid

        PIDManager.write_active_port(active_port)

        warnings: list[str] = []
        monkeypatch.setattr("launcher.log_warn", warnings.append)

        ret = cmd_stop()
        assert ret == 0
        assert child.poll() is None
        assert PIDManager.read_active_port() is None
        assert any(str(child.pid) in w and str(active_port) in w for w in warnings)
    finally:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        shutil.rmtree(outside_dir, ignore_errors=True)


def test_cmd_stop_still_stops_project_owned_listener_from_active_port(tmp_path, monkeypatch):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        active_port = s.getsockname()[1]

    code = (
        "import socket, time\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
        f"s.bind(('127.0.0.1', {active_port}))\n"
        "s.listen(1)\n"
        "while True:\n"
        "    time.sleep(1)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code])
    try:
        for _ in range(50):
            if PortManager.is_open(active_port):
                break
            time.sleep(0.05)

        for _ in range(50):
            if PortManager.get_pid_by_port(active_port) == child.pid:
                break
            time.sleep(0.05)

        if PortManager.get_pid_by_port(active_port) != child.pid:
            pytest.skip("PID attribution unavailable")
        assert PortManager.get_pid_by_port(active_port) == child.pid

        PIDManager.write_active_port(active_port)
        PIDManager.write("backend", child.pid)

        monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == child.pid)

        ret = cmd_stop()
        assert ret == 0
        child.wait(timeout=3)
        assert child.poll() is not None
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None
    finally:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_cmd_stop_foreign_backend_pid_fallback_is_not_signalled(tmp_path, monkeypatch):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    foreign_py = _find_foreign_python()
    outside_dir = tempfile.mkdtemp()
    child = subprocess.Popen(
        [foreign_py, "-c", "import time; time.sleep(10)"], cwd=outside_dir
    )
    try:
        assert not PortManager.belongs_to_project(child.pid)
        PIDManager.write("backend", child.pid)
        assert PIDManager.read_active_port() is None

        warnings: list[str] = []
        monkeypatch.setattr("launcher.log_warn", warnings.append)

        ret = cmd_stop()
        assert ret == 0
        assert child.poll() is None
        assert any(str(child.pid) in w and "foreign" in w.lower() for w in warnings)
    finally:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        shutil.rmtree(outside_dir, ignore_errors=True)


def test_cmd_stop_unresolved_active_listener_does_not_fall_through_to_kill(
    tmp_path, monkeypatch
):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        active_port = s.getsockname()[1]

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        PIDManager.write_active_port(active_port)
        PIDManager.write("backend", child.pid)

        # Explicit exception to no-mock rule per spec F7.8: simulate socket attribution failure
        monkeypatch.setattr(PortManager, "can_bind", lambda p: p != active_port)
        monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: None)
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: False)

        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))

        warnings: list[str] = []
        monkeypatch.setattr("launcher.log_warn", warnings.append)

        ret = cmd_stop()
        assert ret == 0
        assert child.pid not in killed_pids
        assert child.poll() is None
        assert PIDManager.read_active_port() is None
        assert any("ownership cannot be established" in w for w in warnings)
    finally:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_cmd_stop_missing_port_file_stops_owned_backend_pid(tmp_path, monkeypatch):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        PIDManager.write("backend", child.pid)
        assert PIDManager.read_active_port() is None

        monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == child.pid)

        ret = cmd_stop()
        assert ret == 0
        child.wait(timeout=3)
        assert child.poll() is not None
        assert PIDManager.read("backend") is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_cmd_stop_clears_backend_pid_only_if_matching_stopped_process(
    tmp_path, monkeypatch
):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    # 1. Direct unit verification of _clear_backend_pid_if
    PIDManager.write("backend", 1234)
    _clear_backend_pid_if(None)
    assert PIDManager.read("backend") == 1234
    _clear_backend_pid_if(5678)
    assert PIDManager.read("backend") == 1234
    _clear_backend_pid_if(1234)
    assert PIDManager.read("backend") is None

    # 2. Integration with cmd_stop: mismatch leaves backend.pid intact
    child_a = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_b = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        active_port = 8055
        PIDManager.write_active_port(active_port)
        PIDManager.write("backend", child_b.pid)

        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: child_a.pid if p == active_port else None,
        )
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == child_a.pid)
        monkeypatch.setattr(PortManager, "can_bind", lambda _p: True)

        killed: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed.append(pid))

        ret = cmd_stop()
        assert ret == 0
        assert child_a.pid in killed
        assert child_b.pid not in killed
        assert PIDManager.read("backend") == child_b.pid
    finally:
        for p in (child_a, child_b):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def test_kill_on_port_rejects_mismatched_expected_pid(monkeypatch):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        real_time = _capture_process_create_time(child.pid)
        assert real_time is not None

        monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: child.pid)
        killed: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed.append(pid))

        # 1. Mismatched expected_pid
        res_mismatch_pid = PortManager.kill_on_port(8000, expected_pid=child.pid + 9999)
        assert res_mismatch_pid is False
        assert len(killed) == 0

        # 2. Mismatched expected_create_time
        res_mismatch_time = PortManager.kill_on_port(
            8000, expected_pid=child.pid, expected_create_time=real_time + 10.0
        )
        assert res_mismatch_time is False
        assert len(killed) == 0

        # 3. Matching expected_pid and expected_create_time
        monkeypatch.setattr(PortManager, "is_open", lambda _p: False)
        res_match = PortManager.kill_on_port(
            8000, expected_pid=child.pid, expected_create_time=real_time
        )
        assert res_match is True
        assert child.pid in killed
    finally:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_process_identity_helper_unit_and_drift():
    from app.core.process_utils import _verify_process_identity as backend_verify

    # Helper unit cases
    assert _capture_process_create_time(-1) is None
    assert _capture_process_create_time(0) is None
    assert _verify_process_identity(-1, 1000.0) is False
    assert _verify_process_identity(1234, None) is False  # O-8: refusal when None

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        real_create_time = _capture_process_create_time(child.pid)
        assert real_create_time is not None

        # Unit: match, mismatch, dead
        assert _verify_process_identity(child.pid, real_create_time) is True
        assert (
            _verify_process_identity(child.pid, real_create_time + 0.2) is True
        )  # within 0.5s tolerance
        assert (
            _verify_process_identity(child.pid, real_create_time + 5.0) is False
        )  # outside tolerance

        # Dead PID
        assert _verify_process_identity(9999999, real_create_time) is False

        # Drift test against backend process_utils._verify_process_identity
        # 1. Matching identity agrees
        assert (
            _verify_process_identity(child.pid, real_create_time)
            == backend_verify(child.pid, real_create_time)
            is True
        )
        # 2. Mismatched identity agrees
        assert (
            _verify_process_identity(child.pid, real_create_time + 5.0)
            == backend_verify(child.pid, real_create_time + 5.0)
            is False
        )
        # 3. Dead PID agrees
        assert (
            _verify_process_identity(9999999, real_create_time)
            == backend_verify(9999999, real_create_time)
            is False
        )

        # 4. Intentional divergence (O-8): launcher helper refuses (False)
        # on None, while backend returns True.
        assert _verify_process_identity(child.pid, None) is False
        assert backend_verify(child.pid, None) is True
    finally:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_cmd_stop_refuses_kill_on_listener_create_time_mismatch(tmp_path, monkeypatch):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    active_port = 8043
    PIDManager.write_active_port(active_port)

    child_listener = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_supervisor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: child_listener.pid if p == active_port else None,
        )
        monkeypatch.setattr("launcher._backend_supervisor_pid", lambda _pid: child_supervisor.pid)
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)

        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))

        warnings: list[str] = []
        monkeypatch.setattr("launcher.log_warn", warnings.append)

        listener_reads = 0
        real_time_listener = _capture_process_create_time(child_listener.pid)
        real_time_supervisor = _capture_process_create_time(child_supervisor.pid)

        import psutil

        orig_proc = psutil.Process

        class FakeProcess(orig_proc):
            def create_time(self):
                nonlocal listener_reads
                if self.pid == child_listener.pid:
                    listener_reads += 1
                    if listener_reads > 1:
                        return (real_time_listener or 1000.0) + 100.0
                    return real_time_listener
                if self.pid == child_supervisor.pid:
                    return real_time_supervisor
                return super().create_time()

        monkeypatch.setattr(psutil, "Process", FakeProcess)

        ret = cmd_stop()
        assert ret == 0
        assert len(killed_pids) == 0
        assert child_listener.poll() is None
        assert child_supervisor.poll() is None
        assert any(
            "verification failed for listener PID" in w and str(child_listener.pid) in w
            for w in warnings
        )
    finally:
        for p in (child_listener, child_supervisor):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def test_cmd_stop_refuses_kill_on_supervisor_create_time_mismatch(tmp_path, monkeypatch):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    active_port = 8044
    PIDManager.write_active_port(active_port)

    child_listener = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_supervisor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: child_listener.pid if p == active_port else None,
        )
        monkeypatch.setattr("launcher._backend_supervisor_pid", lambda _pid: child_supervisor.pid)
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)

        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))

        warnings: list[str] = []
        monkeypatch.setattr("launcher.log_warn", warnings.append)

        supervisor_reads = 0
        real_time_listener = _capture_process_create_time(child_listener.pid)
        real_time_supervisor = _capture_process_create_time(child_supervisor.pid)

        import psutil

        orig_proc = psutil.Process

        class FakeProcess(orig_proc):
            def create_time(self):
                nonlocal supervisor_reads
                if self.pid == child_listener.pid:
                    return real_time_listener
                if self.pid == child_supervisor.pid:
                    supervisor_reads += 1
                    if supervisor_reads > 1:
                        return (real_time_supervisor or 1000.0) + 100.0
                    return real_time_supervisor
                return super().create_time()

        monkeypatch.setattr(psutil, "Process", FakeProcess)

        ret = cmd_stop()
        assert ret == 0
        assert len(killed_pids) == 0
        assert child_listener.poll() is None
        assert child_supervisor.poll() is None
        assert any(
            "verification failed for backend PID" in w and str(child_supervisor.pid) in w
            for w in warnings
        )
    finally:
        for p in (child_listener, child_supervisor):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def test_cmd_stop_refuses_kill_on_stored_backend_pid_create_time_mismatch(
    tmp_path, monkeypatch
):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        PIDManager.write("backend", child.pid)
        assert PIDManager.read_active_port() is None
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)

        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))

        warnings: list[str] = []
        monkeypatch.setattr("launcher.log_warn", warnings.append)

        reads = 0
        real_time = _capture_process_create_time(child.pid)

        import psutil

        orig_proc = psutil.Process

        class FakeProcess(orig_proc):
            def create_time(self):
                nonlocal reads
                if self.pid == child.pid:
                    reads += 1
                    if reads > 1:
                        return (real_time or 1000.0) + 100.0
                    return real_time
                return super().create_time()

        monkeypatch.setattr(psutil, "Process", FakeProcess)

        ret = cmd_stop()
        assert ret == 0
        assert len(killed_pids) == 0
        assert child.poll() is None
        assert any(
            "verification failed for stored backend PID" in w and str(child.pid) in w
            for w in warnings
        )
    finally:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_cmd_stop_preserves_active_port_when_survivor_still_holds_port(
    tmp_path, monkeypatch
):
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    active_port = 8042
    PIDManager.write_active_port(active_port)

    child_supervisor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_survivor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)

        def fake_get_pid(port):
            if port == active_port:
                if child_supervisor.pid in killed_pids:
                    return child_survivor.pid
                return child_supervisor.pid
            return None

        monkeypatch.setattr(PortManager, "get_pid_by_port", fake_get_pid)
        monkeypatch.setattr(
            PortManager,
            "can_bind",
            lambda port: port != active_port,
        )

        errors: list[str] = []
        monkeypatch.setattr("launcher.log_error", errors.append)

        ret = cmd_stop()
        assert ret == 0
        assert child_supervisor.pid in killed_pids
        assert any("Failed to free port" in e and str(child_survivor.pid) in e for e in errors)
        assert PIDManager.read_active_port() == active_port
    finally:
        for p in (child_supervisor, child_survivor):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


# ═══════════════════════════════════════════════════════════════════════
# Batch B5a (F4a part 1): Dynamic Port Repair & Startup Exit Reconciliation
# ═══════════════════════════════════════════════════════════════════════


def test_backend_supervisor_pid_foreign_pid_guard(monkeypatch):
    """Direct test for _backend_supervisor_pid foreign-PID guard (lines ~3075-3076)."""
    # 1. Non-positive or None PIDs return unchanged
    assert _backend_supervisor_pid(None) is None
    assert _backend_supervisor_pid(0) == 0
    assert _backend_supervisor_pid(-1) == -1

    # 2. Foreign PID guard returns None
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: False)
    assert _backend_supervisor_pid(99999) is None

    # 3. Project-owned PID returns itself or supervisor
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        assert _backend_supervisor_pid(child.pid) == child.pid
    finally:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_check_backend_provenance_verified_and_unknown(monkeypatch):
    """Direct test for _check_backend_provenance (VERIFIED / UNKNOWN)."""
    # 1. Refuses when spawn_time is None (O-8)
    assert _check_backend_provenance(8000, 1234, None) == ProvenanceStatus.UNKNOWN

    # 2. Refuses when wrapper_pid is None or non-positive
    assert _check_backend_provenance(8000, None, 1000.0) == ProvenanceStatus.UNKNOWN
    assert _check_backend_provenance(8000, 0, 1000.0) == ProvenanceStatus.UNKNOWN
    assert _check_backend_provenance(8000, -1, 1000.0) == ProvenanceStatus.UNKNOWN

    # 3. Refuses when port has no listener
    monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: None)
    assert _check_backend_provenance(8000, 1234, 1000.0) == ProvenanceStatus.UNKNOWN

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        real_time = _capture_process_create_time(child.pid)
        assert real_time is not None

        # 4. Refuses when listener is foreign
        monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: child.pid)
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: False)
        assert _check_backend_provenance(8000, child.pid, real_time) == ProvenanceStatus.UNKNOWN

        # 5. Returns VERIFIED when listener == wrapper_pid and create_time matches
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)
        assert _check_backend_provenance(8000, child.pid, real_time) == ProvenanceStatus.VERIFIED

        # 6. Returns UNKNOWN when listener == wrapper_pid but create_time mismatched
        assert (
            _check_backend_provenance(8000, child.pid, real_time + 10.0)
            == ProvenanceStatus.UNKNOWN
        )
    finally:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_check_backend_provenance_descendants(monkeypatch):
    """Direct test for _check_backend_provenance descendant attribution."""
    code = (
        "import subprocess, sys, time\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
        "time.sleep(10)\n"
    )
    child_wrapper = subprocess.Popen([sys.executable, "-c", code])
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_listener_pid = None
    try:
        import psutil

        proc = psutil.Process(child_wrapper.pid)
        for _ in range(50):
            time.sleep(0.05)
            children = proc.children(recursive=True)
            if children:
                child_listener_pid = children[0].pid
                break

        assert child_listener_pid is not None
        wrap_time = _capture_process_create_time(child_wrapper.pid)
        listener_time = _capture_process_create_time(child_listener_pid)
        assert wrap_time is not None and listener_time is not None

        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)

        # 1. Unrelated process returns UNKNOWN
        monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: unrelated.pid)
        assert (
            _check_backend_provenance(8000, child_wrapper.pid, wrap_time)
            == ProvenanceStatus.UNKNOWN
        )

        # 2. Real descendant returns VERIFIED
        monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: child_listener_pid)
        assert (
            _check_backend_provenance(8000, child_wrapper.pid, wrap_time)
            == ProvenanceStatus.VERIFIED
        )

        # 3. Descendant with spawn_time in future returns UNKNOWN
        assert (
            _check_backend_provenance(8000, child_wrapper.pid, listener_time + 10.0)
            == ProvenanceStatus.UNKNOWN
        )
    finally:
        if child_listener_pid:
            with contextlib.suppress(OSError):
                os.kill(child_listener_pid, signal.SIGTERM)
        for p in (child_wrapper, unrelated):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def test_handle_own_unhealthy_passes_expected_args(tmp_path, monkeypatch):
    """Direct test for _handle_own_unhealthy passing expected_pid and expected_create_time."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        real_time = _capture_process_create_time(child.pid)
        assert real_time is not None

        monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: child.pid)
        monkeypatch.setattr("launcher.ask_yes_no", lambda *_args, **_kwargs: True)

        calls: list[tuple[int, int | None, float | None]] = []

        def fake_kill_on_port(port, expected_pid=None, expected_create_time=None):
            calls.append((port, expected_pid, expected_create_time))
            return True

        monkeypatch.setattr(PortManager, "kill_on_port", fake_kill_on_port)

        PIDManager.write_active_port(8042)
        res = _handle_own_unhealthy(8042)
        assert res is True
        assert len(calls) == 1
        assert calls[0][0] == 8042
        assert calls[0][1] == child.pid
        assert calls[0][2] is not None
        assert abs(calls[0][2] - real_time) < 0.001
        assert PIDManager.read_active_port() is None
    finally:
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def test_handle_own_unhealthy_refuses_when_create_time_unreadable(
    tmp_path, monkeypatch, free_port
):
    """Refuse to stop own-unhealthy backend if create_time cannot be read (O-8)."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    fake_pid = 4321
    monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: fake_pid)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: None)

    mock_kill_on_port = MagicMock()
    mock_kill_tree = MagicMock()
    monkeypatch.setattr(PortManager, "kill_on_port", mock_kill_on_port)
    monkeypatch.setattr(PIDManager, "kill_tree", mock_kill_tree)

    warnings: list[str] = []
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    PIDManager.write_active_port(free_port)
    res = _handle_own_unhealthy(free_port)

    assert res is False
    mock_kill_on_port.assert_not_called()
    mock_kill_tree.assert_not_called()
    assert any("identity cannot be proven" in w for w in warnings)
    assert PIDManager.read_active_port() == free_port


def test_timeout_stops_project_owned_attempt_and_clears_matching_backend_pid(
    tmp_path, monkeypatch
):
    """Test timeout stops proven project-owned attempt and clears matching metadata."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    active_port = 8042
    child_wrapper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_supervisor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)
        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: child_supervisor.pid if p == active_port else None,
        )
        monkeypatch.setattr(PortManager, "can_bind", lambda p: p == active_port)
        monkeypatch.setattr("launcher.check_backend_health", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(
            "launcher._check_backend_provenance",
            lambda _port, _w_pid, _s_time: ProvenanceStatus.VERIFIED,
        )
        monkeypatch.setattr(
            "launcher._backend_supervisor_pid",
            lambda _pid: child_supervisor.pid,
        )
        monkeypatch.setattr(
            TerminalOpener,
            "open_backend",
            lambda *_args, **_kwargs: child_wrapper.pid,
        )
        monkeypatch.setattr(
            "launcher._wait_for_backend_attempt",
            lambda *_args, **_kwargs: "timeout",
        )
        monkeypatch.setattr("launcher.Spinner", MagicMock())

        decision = PortDecision(port=active_port, reuse=False, source="preferred")
        monkeypatch.setattr(
            PortManager,
            "resolve_startup_port",
            lambda *_args, **_kwargs: decision,
        )

        cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
        res = start_backend(cfg, Path(sys.executable))

        assert res is False
        assert child_supervisor.pid in killed_pids
        assert child_wrapper.pid in killed_pids
        assert child_wrapper.pid != child_supervisor.pid
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None
    finally:
        for p in (child_wrapper, child_supervisor):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def test_timeout_does_not_signal_foreign_listener_and_stops_wrapper(
    tmp_path, monkeypatch
):
    """Test timeout does not signal foreign listener on active port and stops wrapper only."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    active_port = 8042
    child_wrapper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    foreign_listener = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))
        monkeypatch.setattr(
            PortManager,
            "belongs_to_project",
            lambda pid: pid != foreign_listener.pid,
        )
        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: foreign_listener.pid if p == active_port else None,
        )
        monkeypatch.setattr("launcher.check_backend_health", lambda *_args, **_kwargs: False)
        monkeypatch.setattr(
            TerminalOpener,
            "open_backend",
            lambda *_args, **_kwargs: child_wrapper.pid,
        )
        monkeypatch.setattr(
            "launcher._wait_for_backend_attempt",
            lambda *_args, **_kwargs: "timeout",
        )
        monkeypatch.setattr("launcher.Spinner", MagicMock())

        decision = PortDecision(port=active_port, reuse=False, source="preferred")
        monkeypatch.setattr(
            PortManager,
            "resolve_startup_port",
            lambda *_args, **_kwargs: decision,
        )

        cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
        res = start_backend(cfg, Path(sys.executable))

        assert res is False
        assert foreign_listener.pid not in killed_pids
        assert child_wrapper.pid in killed_pids
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None
    finally:
        for p in (child_wrapper, foreign_listener):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


def test_start_backend_keyboardinterrupt_reconciles_then_reraises(
    tmp_path, monkeypatch
):
    """Test KeyboardInterrupt during attempt/wait reconciles and re-raises (D-12)."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    active_port = 8042
    child_wrapper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)
        monkeypatch.setattr(
            TerminalOpener,
            "open_backend",
            lambda *_args, **_kwargs: child_wrapper.pid,
        )

        def raise_keyboard_interrupt(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr("launcher._wait_for_backend_attempt", raise_keyboard_interrupt)
        monkeypatch.setattr("launcher.Spinner", MagicMock())

        decision = PortDecision(port=active_port, reuse=False, source="preferred")
        monkeypatch.setattr(
            PortManager,
            "resolve_startup_port",
            lambda *_args, **_kwargs: decision,
        )

        cfg = LauncherConfig(auto_install_deps=False, open_browser=False)

        with pytest.raises(KeyboardInterrupt):
            start_backend(cfg, Path(sys.executable))

        assert child_wrapper.pid in killed_pids
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None
    finally:
        child_wrapper.terminate()
        try:
            child_wrapper.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child_wrapper.kill()
            child_wrapper.wait()


def test_timeout_with_unknown_spawn_time_stops_wrapper_only(tmp_path, monkeypatch):
    """Test timeout with unknown spawn_time yields UNKNOWN and stops wrapper only (O-8)."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    # Ephemeral unused port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        active_port = s.getsockname()[1]

    child_wrapper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_listener = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        killed_pids: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_pids.append(pid))
        monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: True)
        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: child_listener.pid if p == active_port else None,
        )
        monkeypatch.setattr(
            "launcher._backend_supervisor_pid",
            lambda _pid: child_listener.pid,
        )
        monkeypatch.setattr("launcher.check_backend_health", lambda *_args, **_kwargs: False)
        monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: None)

        provenance_results: list[ProvenanceStatus] = []
        real_check_provenance = _check_backend_provenance

        def spy_check_provenance(port, w_pid, s_time):
            res = real_check_provenance(port, w_pid, s_time)
            provenance_results.append(res)
            return res

        monkeypatch.setattr("launcher._check_backend_provenance", spy_check_provenance)
        monkeypatch.setattr(
            TerminalOpener,
            "open_backend",
            lambda *_args, **_kwargs: child_wrapper.pid,
        )
        monkeypatch.setattr(
            "launcher._wait_for_backend_attempt",
            lambda *_args, **_kwargs: "timeout",
        )
        monkeypatch.setattr("launcher.Spinner", MagicMock())

        decision = PortDecision(port=active_port, reuse=False, source="preferred")
        monkeypatch.setattr(
            PortManager,
            "resolve_startup_port",
            lambda *_args, **_kwargs: decision,
        )

        cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
        res = start_backend(cfg, Path(sys.executable))

        assert res is False
        assert provenance_results == [ProvenanceStatus.UNKNOWN]
        assert (
            _check_backend_provenance(active_port, child_wrapper.pid, None)
            == ProvenanceStatus.UNKNOWN
        )
        assert killed_pids == [child_wrapper.pid]
        assert child_listener.pid not in killed_pids
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None
    finally:
        for p in (child_wrapper, child_listener):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    # KeyboardInterrupt path with unknown spawn_time (re-raise + wrapper only)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        ki_port = s.getsockname()[1]

    child_wrapper_ki = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    child_listener_ki = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        killed_ki: list[int] = []
        monkeypatch.setattr(PIDManager, "kill_tree", lambda pid: killed_ki.append(pid))
        monkeypatch.setattr(
            PortManager,
            "get_pid_by_port",
            lambda p: child_listener_ki.pid if p == ki_port else None,
        )
        monkeypatch.setattr(
            "launcher._backend_supervisor_pid",
            lambda _pid: child_listener_ki.pid,
        )
        monkeypatch.setattr(
            TerminalOpener,
            "open_backend",
            lambda *_args, **_kwargs: child_wrapper_ki.pid,
        )

        def raise_keyboard_interrupt(*_args, **_kwargs):
            raise KeyboardInterrupt

        monkeypatch.setattr("launcher._wait_for_backend_attempt", raise_keyboard_interrupt)
        decision_ki = PortDecision(port=ki_port, reuse=False, source="preferred")
        monkeypatch.setattr(
            PortManager,
            "resolve_startup_port",
            lambda *_args, **_kwargs: decision_ki,
        )

        with pytest.raises(KeyboardInterrupt):
            start_backend(cfg, Path(sys.executable))

        assert killed_ki == [child_wrapper_ki.pid]
        assert child_listener_ki.pid not in killed_ki
        assert PIDManager.read_active_port() is None
        assert PIDManager.read("backend") is None
    finally:
        for p in (child_wrapper_ki, child_listener_ki):
            p.terminate()
            try:
                p.wait(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()


# ═══════════════════════════════════════════════════════════════════════
# Batch B5b (F4a): Startup Exit Reconciliation & Cleanup
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_backend_initial_decision_none_cleans_metadata(
    tmp_path, monkeypatch, free_port
):
    """Simulate resolve_startup_port returning None; verify metadata cleanup (D-12, AC-8)."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    PIDManager.write_active_port(free_port)
    PIDManager.write("backend", 9876)

    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: None)
    monkeypatch.setattr(ErrorHandler, "show", lambda *_a, **_kw: False)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg)

    assert res is False
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") == 9876


def test_start_backend_python_env_none_cleans_metadata(
    tmp_path, monkeypatch, free_port
):
    """Simulate ensure_python_environment returning None; verify metadata cleanup."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    PIDManager.write_active_port(free_port)
    PIDManager.write("backend", 9876)

    decision = PortDecision(port=free_port, reuse=False, source="preferred")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: decision)
    monkeypatch.setattr("launcher.ensure_python_environment", lambda: None)
    monkeypatch.setattr(ErrorHandler, "show", lambda *_a, **_kw: False)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, python=None)

    assert res is False
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") == 9876


def test_pid_is_none_cleans_metadata(tmp_path, monkeypatch, free_port):
    """Simulate open_backend returning None; verify previous_attempt_pid cleanup logic."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    # Case 1: First attempt fails with pid is None -> backend.pid untouched
    PIDManager.write_active_port(free_port)
    PIDManager.write("backend", 9876)

    decision = PortDecision(port=free_port, reuse=False, source="preferred")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: decision)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: None)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") == 9876

    # Case 2: Attempt 1 succeeds (pid=1111), attempt 2 gets pid is None -> kills 1111 if proven
    open_backend_calls = 0

    def fake_open_backend(*_a, **_kw):
        nonlocal open_backend_calls
        open_backend_calls += 1
        if open_backend_calls == 1:
            return 1111
        return None

    monkeypatch.setattr(TerminalOpener, "open_backend", fake_open_backend)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    decision2 = PortDecision(port=free_port + 1, reuse=False, source="scan")
    resolve_calls = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_calls
        resolve_calls += 1
        return decision if resolve_calls == 1 else decision2

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)

    killed_pids: list[int] = []
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == 1111)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == 1111)
    monkeypatch.setattr("launcher._verify_process_identity", lambda pid, _time: pid == 1111)

    PIDManager.write_active_port(free_port)
    res2 = start_backend(cfg, Path(sys.executable))

    assert res2 is False
    assert killed_pids == [1111]
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_pid_is_none_previous_wrapper_unproven_skips_kill_and_warns(
    tmp_path, monkeypatch, free_port
):
    """If previous wrapper identity is unproven on pid is None, do not kill; warn."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    decision = PortDecision(port=free_port, reuse=False, source="preferred")
    decision2 = PortDecision(port=free_port + 1, reuse=False, source="scan")
    resolve_calls = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_calls
        resolve_calls += 1
        return decision if resolve_calls == 1 else decision2

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)

    open_backend_calls = 0

    def fake_open_backend(*_a, **_kw):
        nonlocal open_backend_calls
        open_backend_calls += 1
        if open_backend_calls == 1:
            return 1111
        return None

    monkeypatch.setattr(TerminalOpener, "open_backend", fake_open_backend)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    warnings: list[str] = []
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == 1111)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == 1111)
    monkeypatch.setattr("launcher._verify_process_identity", lambda _pid, _time: False)
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == []
    assert any("unproven" in w or "untracked" in w for w in warnings)
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_dead_bindable_failure_clears_matching_backend_pid_without_recursive_retry(
    tmp_path, monkeypatch, free_port
):
    """Dead attempt PID and bindable port clears matching backend.pid without recursion."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    decision = PortDecision(port=free_port, reuse=False, source="preferred")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: decision)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: 1234)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "dead")
    monkeypatch.setattr(PortManager, "can_bind", lambda _p: True)

    show_calls: list[tuple] = []

    def fake_show(message, fix=None, retry_cb=None):
        show_calls.append((message, fix, retry_cb))
        return False

    monkeypatch.setattr(ErrorHandler, "show", fake_show)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert len(show_calls) == 1
    assert "Backend crashed during startup." in show_calls[0][0]
    # Verify no recursive callback passed to ErrorHandler.show (per D-7)
    assert show_calls[0][2] is None
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_start_backend_reuse_verifies_stored_pid_ownership(
    tmp_path, monkeypatch, free_port
):
    """Reuse path writes verified supervisor PID, refusing foreign stored backend.pid."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    decision = PortDecision(port=free_port, reuse=True, source="preferred")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: decision)

    foreign_stored_pid = 9999
    listener_pid = 2001
    supervisor_pid = 2000

    PIDManager.write("backend", foreign_stored_pid)

    monkeypatch.setattr(
        PortManager, "get_pid_by_port", lambda p: listener_pid if p == free_port else None
    )
    monkeypatch.setattr("launcher._backend_supervisor_pid", lambda _pid: supervisor_pid)
    monkeypatch.setattr(
        PortManager,
        "belongs_to_project",
        lambda pid: pid in (listener_pid, supervisor_pid),
    )
    monkeypatch.setattr(PIDManager, "is_alive", lambda _pid: True)

    class FakeParent:
        pid = foreign_stored_pid

    class FakeProcess:
        def __init__(self, pid):
            self.pid = pid

        def parents(self):
            return [FakeParent()]

    monkeypatch.setattr("psutil.Process", FakeProcess)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg)

    assert res is True
    assert PIDManager.read_active_port() == free_port
    assert PIDManager.read("backend") == supervisor_pid
    assert PIDManager.read("backend") != foreign_stored_pid


def test_start_backend_reuse_toctou_returns_false_and_no_success_log(
    tmp_path, monkeypatch, free_port
):
    """If _resolve_reused_backend_pid returns None on reuse, abort without writing port."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)

    decision = PortDecision(port=free_port, reuse=True, source="preferred")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: decision)
    monkeypatch.setattr("launcher._resolve_reused_backend_pid", lambda _port: None)

    log_ok_calls: list[str] = []
    log_warn_calls: list[str] = []
    monkeypatch.setattr("launcher.log_ok", log_ok_calls.append)
    monkeypatch.setattr("launcher.log_warn", log_warn_calls.append)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg)

    assert res is False
    assert PIDManager.read_active_port() is None
    assert not any("PID None" in msg for msg in log_ok_calls)
    assert any("reuse verification failed" in msg for msg in log_warn_calls)


def test_start_backend_retry_reuse_toctou_returns_false_and_cleans_metadata(
    tmp_path, monkeypatch, free_port
):
    """Retry reuse where helper returns None aborts, cleans metadata and logs warning."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    decision1 = PortDecision(port=free_port, reuse=False, source="preferred")
    decision2 = PortDecision(port=free_port + 1, reuse=True, source="scan")
    resolve_calls = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_calls
        resolve_calls += 1
        return decision1 if resolve_calls == 1 else decision2

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: 3333)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")
    monkeypatch.setattr("launcher._resolve_reused_backend_pid", lambda _port: None)

    log_ok_calls: list[str] = []
    log_warn_calls: list[str] = []
    monkeypatch.setattr("launcher.log_ok", log_ok_calls.append)
    monkeypatch.setattr("launcher.log_warn", log_warn_calls.append)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None
    assert not any("PID None" in msg for msg in log_ok_calls)
    assert any("reuse verification failed" in msg for msg in log_warn_calls)


def test_start_backend_writes_non_preferred_active_port_on_health(
    tmp_path, monkeypatch, free_port
):
    """Healthy launch on non-default port writes active port file and config property."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    non_default_port = free_port if free_port != 8000 else 8042
    decision = PortDecision(port=non_default_port, reuse=False, source="scan")
    monkeypatch.setattr(PortManager, "resolve_startup_port", lambda *_a, **_kw: decision)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: 3333)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "healthy")
    monkeypatch.setattr(PortManager, "get_pid_by_port", lambda _p: 3333)

    cfg = LauncherConfig(
        auto_install_deps=False, open_browser=False, backend_port=8000
    )
    res = start_backend(cfg, Path(sys.executable))

    assert res is True
    assert cfg.active_backend_port == non_default_port
    assert PIDManager.read_active_port() == non_default_port
    assert PIDManager.read("backend") == 3333


def test_next_decision_none_cleans_matching_backend_pid(
    tmp_path, monkeypatch, free_port
):
    """Simulate candidate exhaustion during retry; verify matching PID and port cleanup."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    decision1 = PortDecision(port=free_port, reuse=False, source="preferred")
    resolve_calls = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == 1:
            return decision1
        return None  # Candidate scan exhausted on retry

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: 4444)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == 4444)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == 4444)
    monkeypatch.setattr("launcher._verify_process_identity", lambda pid, _time: pid == 4444)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == [4444]
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_next_decision_none_identity_unproven_skips_kill_and_warns(
    tmp_path, monkeypatch, free_port
):
    """Candidate exhaustion with unproven wrapper identity skips kill, warns, cleans state."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    decision1 = PortDecision(port=free_port, reuse=False, source="preferred")
    resolve_calls = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_calls
        resolve_calls += 1
        return decision1 if resolve_calls == 1 else None

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: 4444)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    warnings: list[str] = []
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == 4444)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == 4444)
    monkeypatch.setattr("launcher._verify_process_identity", lambda _pid, _time: False)
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == []
    assert any("unproven" in w or "untracked" in w for w in warnings)
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_next_decision_none_foreign_pid_skips_kill(tmp_path, monkeypatch, free_port):
    """Candidate exhaustion with foreign wrapper PID does not kill foreign process."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    decision1 = PortDecision(port=free_port, reuse=False, source="preferred")
    resolve_calls = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_calls
        resolve_calls += 1
        return decision1 if resolve_calls == 1 else None

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)
    monkeypatch.setattr(TerminalOpener, "open_backend", lambda *_a, **_kw: 4444)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == 4444)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: False)
    monkeypatch.setattr("launcher._verify_process_identity", lambda _pid, _time: True)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == []
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_final_exhaustion_cleans_matching_backend_pid(
    tmp_path, monkeypatch, free_port
):
    """Drive attempts to MAX_PORT_ATTEMPTS exhaustion; verify cleanup of matching last PID."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    resolve_count = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_count
        p = free_port + resolve_count
        resolve_count += 1
        return PortDecision(port=p, reuse=False, source="preferred" if p == free_port else "scan")

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)

    attempt_count = 0

    def fake_open_backend(*_a, **_kw):
        nonlocal attempt_count
        attempt_count += 1
        return 5000 + attempt_count

    monkeypatch.setattr(TerminalOpener, "open_backend", fake_open_backend)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    last_pid = 5000 + 3  # MAX_PORT_ATTEMPTS = 3
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == last_pid)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == last_pid)
    monkeypatch.setattr("launcher._verify_process_identity", lambda pid, _time: pid == last_pid)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == [last_pid]
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_final_exhaustion_identity_unproven_skips_kill_and_warns(
    tmp_path, monkeypatch, free_port
):
    """Final retry exhaustion with unproven identity skips kill, warns, and cleans metadata."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    resolve_count = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_count
        p = free_port + resolve_count
        resolve_count += 1
        return PortDecision(port=p, reuse=False, source="preferred" if p == free_port else "scan")

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)

    attempt_count = 0

    def fake_open_backend(*_a, **_kw):
        nonlocal attempt_count
        attempt_count += 1
        return 5000 + attempt_count

    monkeypatch.setattr(TerminalOpener, "open_backend", fake_open_backend)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    warnings: list[str] = []
    last_pid = 5000 + 3
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == last_pid)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda pid: pid == last_pid)
    monkeypatch.setattr("launcher._verify_process_identity", lambda _pid, _time: False)
    monkeypatch.setattr("launcher.log_warn", warnings.append)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == []
    assert any("unproven" in w or "untracked" in w for w in warnings)
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None


def test_final_exhaustion_foreign_pid_skips_kill(tmp_path, monkeypatch, free_port):
    """Final retry exhaustion with foreign PID does not kill foreign process."""
    mcs_dir = tmp_path / ".onx"
    mcs_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("launcher.MCS_DIR", mcs_dir)
    monkeypatch.setattr("launcher.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("launcher.BACKEND_LOG", tmp_path / "backend.log")

    resolve_count = 0

    def fake_resolve(*_a, **_kw):
        nonlocal resolve_count
        p = free_port + resolve_count
        resolve_count += 1
        return PortDecision(port=p, reuse=False, source="preferred" if p == free_port else "scan")

    monkeypatch.setattr(PortManager, "resolve_startup_port", fake_resolve)

    attempt_count = 0

    def fake_open_backend(*_a, **_kw):
        nonlocal attempt_count
        attempt_count += 1
        return 5000 + attempt_count

    monkeypatch.setattr(TerminalOpener, "open_backend", fake_open_backend)
    monkeypatch.setattr("launcher._capture_process_create_time", lambda _pid: 123.45)
    monkeypatch.setattr("launcher.Spinner", MagicMock())
    monkeypatch.setattr("launcher._wait_for_backend_attempt", lambda *_a, **_kw: "bind")

    killed_pids: list[int] = []
    last_pid = 5000 + 3
    monkeypatch.setattr(PIDManager, "kill_tree", killed_pids.append)
    monkeypatch.setattr(PIDManager, "is_alive", lambda pid: pid == last_pid)
    monkeypatch.setattr(PortManager, "belongs_to_project", lambda _pid: False)
    monkeypatch.setattr("launcher._verify_process_identity", lambda _pid, _time: True)

    cfg = LauncherConfig(auto_install_deps=False, open_browser=False)
    res = start_backend(cfg, Path(sys.executable))

    assert res is False
    assert killed_pids == []
    assert PIDManager.read_active_port() is None
    assert PIDManager.read("backend") is None
