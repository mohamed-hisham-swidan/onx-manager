from __future__ import annotations

from enum import StrEnum


class AgentProcessStatus(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    ERROR = "ERROR"


class DesiredState(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class ExposureStatus(StrEnum):
    DISABLED = "DISABLED"
    CLAIM_REQUIRED = "CLAIM_REQUIRED"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    RECLAIM_REQUIRED = "RECLAIM_REQUIRED"


class ExposureMethod(StrEnum):
    PLAYIT = "playit"
    PORT_FORWARD = "port_forward"
    CLOUDFLARE_TCP = "cloudflare_tcp"


class PanelExposureMethod(StrEnum):
    NONE = "none"
    CLOUDFLARE_TUNNEL = "cloudflare_tunnel"
    PLAYIT_HTTP = "playit_http"
    PORT_FORWARD = "port_forward"


class TargetProtocol(StrEnum):
    TCP = "tcp"


class ServiceType(StrEnum):
    JAVA = "java"


# Deterministic aggregate precedence (highest → lowest). Per target-status
# fold (§6a.2 of the Phase-7 roadmap). DISABLED is an override handled by the
# fold logic, not part of the order.
_PRECEDENCE: list[ExposureStatus] = [
    ExposureStatus.RECLAIM_REQUIRED,
    ExposureStatus.CLAIM_REQUIRED,
    ExposureStatus.ERROR,
    ExposureStatus.DEGRADED,
    ExposureStatus.STOPPING,
    ExposureStatus.STARTING,
    ExposureStatus.ACTIVE,
    ExposureStatus.STOPPED,
    ExposureStatus.DISABLED,
]

_PRECEDENCE_RANK: dict[ExposureStatus, int] = {
    status: rank for rank, status in enumerate(_PRECEDENCE)
}


def aggregate_precedence(statuses: list[ExposureStatus]) -> ExposureStatus:
    """Fold a list of per-target statuses into the highest-precedence one.

    An empty list is only valid when the caller's exposure is DISABLED; the
    caller decides how to surface NO_TARGETS for enabled exposures.
    """
    if not statuses:
        return ExposureStatus.DISABLED
    return min(statuses, key=lambda s: _PRECEDENCE_RANK[s])
