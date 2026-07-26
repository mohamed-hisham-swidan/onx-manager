from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

from app.core.event_bus import DomainEvent

logger = logging.getLogger("mcs.lifecycle")


def format_event(event: DomainEvent, server_name: str | None = None) -> str:
    event_type = type(event).__name__
    name = server_name or getattr(event, "name", None) or getattr(event, "server_id", "?")

    if event_type == "ServerCreatedEvent":
        return f'Server "{name}" created — version={getattr(event, "minecraft_version", "?")}'
    if event_type == "ServerStartingEvent":
        return f'Server "{name}" is starting…'
    if event_type == "ServerStartedEvent":
        return f'Server "{name}" started — pid={getattr(event, "pid", "?")} port={getattr(event, "port", "?")}'
    if event_type == "ServerStoppingEvent":
        reason = getattr(event, "reason", "")
        suffix = f' reason="{reason}"' if reason else ""
        return f'Server "{name}" is stopping…{suffix}'
    if event_type == "ServerStoppedEvent":
        return f'Server "{name}" stopped'
    if event_type == "ServerCrashedEvent":
        code = getattr(event, "exit_code", "?")
        log_count = len(getattr(event, "last_log_lines", []) or [])
        return f'Server "{name}" crashed — exit_code={code} last_log_lines={log_count}'
    if event_type == "ServerConfigChangedEvent":
        keys = getattr(event, "changed_keys", [])
        return f'Server "{name}" config changed — keys={",".join(keys)}'
    if event_type == "ServerDeletedEvent":
        return f'Server "{name}" deleted'

    return f"[{event_type}] server_id={getattr(event, 'server_id', '?')}"


@contextmanager
def progress_phase(
    label: str,
    phase: int,
    total: int,
    server_name: str | None = None,
    server_id: str | None = None,
    logger_name: str = "mcs.lifecycle",
) -> Iterator[None]:
    log = logging.getLogger(logger_name)
    pct = int((phase - 1) / total * 100)
    info = f"server_id={server_id}" if server_id else ""
    log.info(
        "[%d/%d] %d%% — %s %s",
        phase, total, pct, label, info,
    )
    start = time.monotonic()
    try:
        yield
    except Exception:
        elapsed = time.monotonic() - start
        log.error(
            "[%d/%d] %s FAILED after %.1fs %s",
            phase, total, label, elapsed, info,
        )
        raise
    elapsed = time.monotonic() - start
    log.info(
        "[%d/%d] %s done (%.1fs) %s",
        phase, total, label, elapsed, info,
    )


@contextmanager
def startup_timeline(
    server_name: str,
    server_id: str,
    logger_name: str = "mcs.lifecycle",
) -> Iterator[list[dict[str, Any]]]:
    log = logging.getLogger(logger_name)
    milestones: list[dict[str, Any]] = []
    started_at = time.monotonic()
    log.info(
        'Startup timeline started for server "%s" server_id=%s',
        server_name, server_id,
    )
    try:
        yield milestones
    finally:
        elapsed = time.monotonic() - started_at
        log.info(
            'Startup timeline complete for server "%s" — %.1fs elapsed milestones=%d server_id=%s',
            server_name, elapsed, len(milestones), server_id,
        )


@contextmanager
def shutdown_timeline(
    server_name: str,
    server_id: str,
    logger_name: str = "mcs.lifecycle",
) -> Iterator[list[dict[str, Any]]]:
    log = logging.getLogger(logger_name)
    milestones: list[dict[str, Any]] = []
    started_at = time.monotonic()
    log.info(
        'Shutdown timeline started for server "%s" server_id=%s',
        server_name, server_id,
    )
    try:
        yield milestones
    finally:
        elapsed = time.monotonic() - started_at
        log.info(
            'Shutdown timeline complete for server "%s" — %.1fs elapsed milestones=%d server_id=%s',
            server_name, elapsed, len(milestones), server_id,
        )


def add_timeline_milestone(
    milestones: list[dict[str, Any]] | None,
    name: str,
    server_name: str,
    server_id: str,
) -> None:
    now = time.monotonic()
    if milestones is not None:
        milestones.append({"name": name, "timestamp": now})
    logger.info(
        'Timeline — %s server="%s" server_id=%s',
        name, server_name, server_id,
    )


def log_crash_diagnostics(
    message: str,
    server_name: str,
    server_id: str,
    pid: int | None = None,
    exit_code: int | None = None,
    log_lines: list[str] | None = None,
    failure_code: str | None = None,
    failure_reason: str | None = None,
) -> None:
    lines_count = len(log_lines) if log_lines else 0
    logger.error(
        'CRASH — %s server="%s" server_id=%s pid=%s exit_code=%s failure=%s reason="%s" log_lines=%d',
        message, server_name, server_id,
        pid or "?", exit_code or "?",
        failure_code or "?",
        (failure_reason or "")[:200],
        lines_count,
    )
    if log_lines:
        last = log_lines[-10:]
        for i, line in enumerate(last):
            logger.error(
                'CRASH %s last_log[-%d] server_id=%s: %s',
                server_name, len(last) - i, server_id, line.rstrip(),
            )
