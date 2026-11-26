from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import structlog

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return correlation_id_var.get()


def set_correlation_id(cid: str | None = None) -> str:
    cid = cid or uuid.uuid4().hex[:12]
    correlation_id_var.set(cid)
    return cid


def _add_correlation_id(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    cid = get_correlation_id()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def _add_timestamp(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    from structlog.processors import TimeStamper

    return TimeStamper(fmt="iso")(logger, method_name, event_dict)


def _clear_rotated_log_files(log_path: Path) -> None:
    """Remove rotated sibling log files (e.g. panel.log.1) on fresh startup."""
    try:
        for rotated in log_path.parent.glob(f"{log_path.name}.*"):
            if rotated.is_file():
                rotated.unlink(missing_ok=True)
    except OSError:
        pass


def configure_logging(
    *,
    json_output: bool = False,
    log_level: str = "INFO",
    log_file: str | Path | None = None,
    clear_log_file: bool = True,
) -> None:
    shared_processors: list[Callable[..., dict[str, Any]]] = [
        structlog.contextvars.merge_contextvars,
        _add_timestamp,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_correlation_id,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler._onx_configured = True  # type: ignore[attr-defined]
    stream_handler.setFormatter(formatter)

    handlers: list[logging.Handler] = [stream_handler]
    if log_file is not None:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if clear_log_file:
            _clear_rotated_log_files(log_path)
        file_mode = "w" if clear_log_file else "a"
        file_handler = logging.FileHandler(log_path, mode=file_mode, encoding="utf-8")
        file_handler._onx_configured = True  # type: ignore[attr-defined]
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    for existing in list(root_logger.handlers):
        if getattr(existing, "_onx_configured", False):
            root_logger.removeHandler(existing)
            existing.close()
    for h in handlers:
        root_logger.addHandler(h)
    root_logger.setLevel(log_level.upper())

    for log_name in ("uvicorn", "uvicorn.access", "sqlalchemy.engine"):
        sub_logger = logging.getLogger(log_name)
        for existing in list(sub_logger.handlers):
            if getattr(existing, "_onx_configured", False):
                existing.close()
        sub_logger.handlers.clear()
        for h in handlers:
            sub_logger.addHandler(h)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
