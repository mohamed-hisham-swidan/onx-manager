import io
import logging
import re

import structlog

from app.core.logging import configure_logging, get_correlation_id, set_correlation_id, correlation_id_var


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


from app.core.logging import correlation_id_var
