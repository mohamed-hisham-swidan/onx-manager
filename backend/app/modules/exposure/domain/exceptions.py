from app.core.exceptions import MCSError, ValidationError


class ClaimActiveError(MCSError):
    """A host agent claim is already active under a different key."""

    def __init__(self) -> None:
        super().__init__(
            "An agent claim is already active",
            code="CLAIM_ACTIVE",
            http_status=409,
        )


class NoTargetsError(ValidationError):
    """Enabling an exposure with zero targets violates the NO_TARGETS contract."""

    def __init__(self) -> None:
        super().__init__(
            "Exposure has no targets (NO_TARGETS)",
            field="targets",
            details={"code": "NO_TARGETS"},
        )


class WarningNotAcknowledgedError(MCSError):
    """Cloudflare TCP requires acknowledged_warning=True."""

    def __init__(self) -> None:
        super().__init__(
            "Players must install Modflared (or run cloudflared) to connect. "
            "This is not a normal public address.",
            code="WARNING_NOT_ACKNOWLEDGED",
            http_status=422,
        )
