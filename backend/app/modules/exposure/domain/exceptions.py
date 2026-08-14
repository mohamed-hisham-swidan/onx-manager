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
