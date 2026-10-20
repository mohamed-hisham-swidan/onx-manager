"""Tests for dynamic backend port selection and port classification.

SPEC: docs/design/SPEC-2026-10-20-DYNAMIC-BACKEND-PORT-01.md
ADR: docs/decisions/0019-dynamic-backend-port.md
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

# Ensure repository root is on sys.path when pytest runs from backend/ directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from launcher import (  # noqa: E402
    LauncherConfig,
    PIDManager,
    PortDecision,
    PortManager,
    PortState,
    StatusDisplay,
    check_backend_health,
    get_effective_backend_port,
    start_backend,
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
