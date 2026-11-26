import logging
import sys
from pathlib import Path

import structlog

from app.core.logging import configure_logging, get_correlation_id, set_correlation_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import launcher  # noqa: E402


class TestCorrelationId:
    def test_set_and_get(self) -> None:
        cid = set_correlation_id()
        assert len(cid) == 12
        assert get_correlation_id() == cid

    def test_custom_value(self) -> None:
        set_correlation_id("custom-123")
        assert get_correlation_id() == "custom-123"

    def test_context_isolation(self) -> None:
        set_correlation_id("ctx-1")
        cid1 = get_correlation_id()

        set_correlation_id("ctx-2")
        assert get_correlation_id() == "ctx-2"

        set_correlation_id(cid1)
        assert get_correlation_id() == cid1


class TestLoggingConfiguration:
    def test_configure_console(self) -> None:
        configure_logging(json_output=False, log_level="DEBUG")
        logger = structlog.get_logger("test")
        assert logger is not None
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_configure_json(self) -> None:
        configure_logging(json_output=True, log_level="INFO")
        logger = structlog.get_logger("test")
        assert logger is not None
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_configure_log_file_truncates_on_start_and_preserves_on_stop(
        self, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "panel.log"
        rotated = tmp_path / "panel.log.1"
        log_file.write_text("stale-session-line\n", encoding="utf-8")
        rotated.write_text("stale-rotated-line\n", encoding="utf-8")

        try:
            configure_logging(json_output=False, log_level="INFO", log_file=log_file)
            assert not rotated.exists()
            logger = logging.getLogger("onx.test.session")
            logger.info("session-one-entry")
            for h in logging.getLogger().handlers:
                h.flush()

            content = log_file.read_text(encoding="utf-8")
            assert "stale-session-line" not in content
            assert "session-one-entry" in content

            # Stopping (closing/detaching handlers) must keep session logs intact on disk.
            root = logging.getLogger()
            for existing in list(root.handlers):
                if getattr(existing, "_onx_configured", False):
                    root.removeHandler(existing)
                    existing.close()

            assert log_file.is_file()
            assert "session-one-entry" in log_file.read_text(encoding="utf-8")

            # Restarting (re-initializing configure_logging) truncates previous session logs.
            configure_logging(json_output=False, log_level="INFO", log_file=log_file)
            logger.info("session-two-entry")
            for h in logging.getLogger().handlers:
                h.flush()

            restarted_content = log_file.read_text(encoding="utf-8")
            assert "session-one-entry" not in restarted_content
            assert "session-two-entry" in restarted_content
        finally:
            configure_logging(json_output=False, log_level="INFO")


class TestLauncherPanelLogLifecycle:
    def test_clear_truncates_log_and_removes_rotated_files(self, tmp_path: Path) -> None:
        log_file = tmp_path / "backend.log"
        rotated = tmp_path / "backend.log.1"
        unrelated = tmp_path / "other.log"
        log_file.write_text("old backend output\n", encoding="utf-8")
        rotated.write_text("old rotated output\n", encoding="utf-8")
        unrelated.write_text("keep me\n", encoding="utf-8")

        launcher.LogManager.clear(log_file)

        assert log_file.is_file()
        assert log_file.read_text(encoding="utf-8") == ""
        assert not rotated.exists()
        assert unrelated.read_text(encoding="utf-8") == "keep me\n"

    def test_cmd_stop_preserves_panel_logs(self, monkeypatch, tmp_path: Path) -> None:
        backend_log = tmp_path / "backend.log"
        frontend_log = tmp_path / "frontend.log"
        backend_log.write_text("backend crash trace\n", encoding="utf-8")
        frontend_log.write_text("frontend build log\n", encoding="utf-8")

        monkeypatch.setattr(launcher, "BACKEND_LOG", backend_log)
        monkeypatch.setattr(launcher, "FRONTEND_LOG", frontend_log)
        monkeypatch.setattr(launcher.PIDManager, "read", staticmethod(lambda _name: None))
        monkeypatch.setattr(launcher.PIDManager, "clear", staticmethod(lambda _name: None))
        monkeypatch.setattr(launcher.PIDManager, "read_active_port", staticmethod(lambda: None))
        monkeypatch.setattr(launcher.PIDManager, "clear_active_port", staticmethod(lambda: None))
        monkeypatch.setattr(launcher.PIDManager, "clear_started_at", staticmethod(lambda: None))
        monkeypatch.setattr(launcher.PIDManager, "cleanup_stale", staticmethod(lambda: None))

        rc = launcher.cmd_stop()

        assert rc == 0
        assert backend_log.read_text(encoding="utf-8") == "backend crash trace\n"
        assert frontend_log.read_text(encoding="utf-8") == "frontend build log\n"
