from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from app.modules.server.domain.diagnostics import FailureCode


@dataclass(frozen=True)
class FailurePattern:
    name: str
    pattern: Pattern[str]
    failure_code: FailureCode


FAILURE_PATTERNS: list[FailurePattern] = [
    FailurePattern(
        name="OutOfMemoryError",
        pattern=re.compile(r"OutOfMemoryError|java\.lang\.OutOfMemoryError"),
        failure_code=FailureCode.MEMORY_EXHAUSTED,
    ),
    FailurePattern(
        name="PortAlreadyInUse",
        pattern=re.compile(r"Port\s+already\s+in\s+use"),
        failure_code=FailureCode.PORT_CONFLICT,
    ),
    FailurePattern(
        name="UnsupportedClassVersionError",
        pattern=re.compile(r"UnsupportedClassVersionError|major\.minor\s+version"),
        failure_code=FailureCode.JAVA_VERSION_MISMATCH,
    ),
    FailurePattern(
        name="UnableToAccessJarfile",
        pattern=re.compile(r"Unable\s+to\s+access\s+jarfile|Error:\s+Unable\s+to\s+access"),
        failure_code=FailureCode.INVALID_JAR_PATH,
    ),
    FailurePattern(
        name="CouldNotReserveSpace",
        pattern=re.compile(r"Could\s+not\s+reserve\s+enough\s+space|Failed\s+to\s+reserve"),
        failure_code=FailureCode.MEMORY_CONFIGURATION_ERROR,
    ),
    FailurePattern(
        name="AddressAlreadyInUse",
        pattern=re.compile(r"Address\s+already\s+in\s+use"),
        failure_code=FailureCode.PORT_ALREADY_BOUND,
    ),
    FailurePattern(
        name="FailedToBind",
        pattern=re.compile(r"Failed\s+to\s+bind|BindException"),
        failure_code=FailureCode.NETWORK_BIND_FAILURE,
    ),
    FailurePattern(
        name="NoSuchFile",
        pattern=re.compile(r"No\s+such\s+file|FileNotFoundException"),
        failure_code=FailureCode.FILE_NOT_FOUND,
    ),
    FailurePattern(
        name="PermissionDenied",
        pattern=re.compile(r"Permission\s+denied|AccessDeniedException"),
        failure_code=FailureCode.PERMISSION_ERROR,
    ),
    FailurePattern(
        name="TmuxSessionNotFound",
        pattern=re.compile(r"session\s+not\s+found|no\s+session"),
        failure_code=FailureCode.TMUX_SESSION_LOST,
    ),
]


def detect_failure(log_lines: list[str]) -> tuple[FailureCode | None, str]:
    for line in log_lines:
        for fp in FAILURE_PATTERNS:
            if fp.pattern.search(line):
                return fp.failure_code, fp.name
    return None, ""
