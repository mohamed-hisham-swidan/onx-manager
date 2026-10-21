"""Tests for dynamic backend port selection and port classification.

SPEC: docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md
ADR: docs/decisions/0019-dynamic-backend-port.md
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
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
    StatusDisplay,
    TerminalOpener,
    _generate_attempt_token,
    _handle_own_unhealthy,
    _has_bind_error,
    _parse_preferred_port,
    _read_backend_log_from,
    _stat_file_identity,
    _wait_for_backend_attempt,
    _write_attempt_marker,
    ask_yes_no,
    check_backend_health,
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

    with patch("launcher.MCS_DIR", tmp_path / ".onx"), \
         patch("launcher.PROJECT_ROOT", tmp_path), \
         patch("launcher.BACKEND_LOG", tmp_path / "backend.log"), \
         patch.object(PortManager, "resolve_startup_port", return_value=decision), \
         patch("launcher.get_canonical_db_url", return_value="sqlite:///test.db"), \
         patch("launcher.TerminalOpener.open_backend", return_value=4242) as mock_open, \
         patch("launcher._wait_for_backend_attempt", return_value="timeout"), \
         patch("launcher.Spinner"):

        assert start_backend(cfg, Path("/fake/python")) is False

    assert mock_open.call_count == 1


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

