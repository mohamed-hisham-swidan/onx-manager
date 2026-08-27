from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

from app.core.identity import IDENTITY

MCS_MARKER = IDENTITY.process_marker_legacy
ONX_MARKER = IDENTITY.process_marker_new
MCS_MARKER_ENV_VAL = "1"


class OwnershipStatus(Enum):
    VERIFIED = "verified"
    NOT_OWNED = "not_owned"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"


@dataclass
class OwnershipResult:
    status: OwnershipStatus
    has_marker: bool = False
    cwd: str | None = None
    cwd_matches: bool = False
    start_time: int | None = None
    detail: str = ""


def _get_process_env(pid: int) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            raw = f.read()
        for item in raw.decode("utf-8", errors="replace").split("\0"):
            if "=" in item:
                k, v = item.split("=", 1)
                env[k] = v
    except OSError:
        pass
    return env


def _get_process_cwd(pid: int) -> str | None:
    try:
        return os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        return None


def _get_process_start_time(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        paren_end = data.rfind(")")
        if paren_end == -1:
            return None
        fields = data[paren_end + 2 :].split()
        if len(fields) >= 20:
            return int(fields[19])
        return None
    except (OSError, ValueError, IndexError):
        return None


def _is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _get_servers_data_dir() -> str:
    try:
        from app.core.config import AppSettings

        settings = AppSettings()
        return os.path.abspath(settings.servers_data_dir)
    except Exception:
        return os.path.abspath("data/servers")


def verify_ownership(
    pid: int,
    servers_data_dir: str | None = None,
    stored_start_time: int | None = None,
) -> OwnershipResult:
    if not _is_pid_alive(pid):
        return OwnershipResult(
            status=OwnershipStatus.NOT_FOUND,
            detail=f"PID {pid} not found",
        )

    env = _get_process_env(pid)
    has_marker = (
        env.get(ONX_MARKER) == MCS_MARKER_ENV_VAL or env.get(MCS_MARKER) == MCS_MARKER_ENV_VAL
    )
    cwd = _get_process_cwd(pid)

    cwd_matches = False
    if cwd is not None and servers_data_dir is not None:
        try:
            common = os.path.commonpath([cwd, servers_data_dir])
            cwd_matches = common == servers_data_dir
        except ValueError:
            pass

    start_time = _get_process_start_time(pid)

    if stored_start_time is not None and start_time is not None:
        if start_time != stored_start_time:
            return OwnershipResult(
                status=OwnershipStatus.NOT_OWNED,
                has_marker=has_marker,
                cwd=cwd,
                cwd_matches=cwd_matches,
                start_time=start_time,
                detail=f"start_time mismatch: process={start_time} stored={stored_start_time} — PID likely recycled",
            )

    if has_marker or cwd_matches:
        status = OwnershipStatus.VERIFIED
        detail_parts = []
        if has_marker:
            detail_parts.append("marker present")
        if cwd_matches:
            detail_parts.append("cwd matches")
        if start_time is not None:
            detail_parts.append(f"start_time={start_time}")
        detail = "; ".join(detail_parts)
    else:
        status = OwnershipStatus.UNKNOWN
        detail = f"no marker, cwd={cwd}"

    return OwnershipResult(
        status=status,
        has_marker=has_marker,
        cwd=cwd,
        cwd_matches=cwd_matches,
        start_time=start_time,
        detail=detail,
    )


def log_ownership_decision(
    logger: logging.Logger,
    decision: str,
    label: str,
    pid: int | None,
    result: OwnershipResult,
    reason: str = "",
):
    logger.info(
        "KILL_DECISION label=%s pid=%s marker=%s cwd=%s start_time=%s status=%s decision=%s reason=%s",
        label,
        pid,
        result.has_marker,
        result.cwd or "",
        result.start_time or "",
        result.status.value,
        decision,
        reason,
    )
