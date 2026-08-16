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


class MethodProtocolIncompatibleError(MCSError):
    """The selected exposure method cannot support the target protocol."""

    def __init__(
        self,
        message: str = (
            "Cloudflare TCP exposure does not support UDP targets (Bedrock / Voice Chat). "
            "Use playit.gg or Port Forwarding instead."
        ),
    ) -> None:
        super().__init__(
            message,
            code="METHOD_PROTOCOL_INCOMPATIBLE",
            http_status=422,
        )


class DuplicateTargetError(MCSError):
    """A target for this service type and protocol already exists."""

    def __init__(
        self, message: str = "A target for this service type and protocol already exists"
    ) -> None:
        super().__init__(
            message,
            code="DUPLICATE_TARGET",
            http_status=409,
        )


class PortAlreadyRegisteredError(MCSError):
    """A port is already registered for this server/service/protocol."""

    def __init__(
        self, message: str = "A port is already registered for this service type or port/protocol"
    ) -> None:
        super().__init__(
            message,
            code="PORT_ALREADY_REGISTERED",
            http_status=409,
        )


class UnregisteredPortError(MCSError):
    """A companion service port must be registered before creating an exposure target."""

    def __init__(
        self, message: str = "Port must be registered before creating exposure target"
    ) -> None:
        super().__init__(
            message,
            code="UNREGISTERED_PORT",
            http_status=422,
        )


class InvalidServiceTypeError(MCSError):
    """Service type is invalid or disallowed in this context."""

    def __init__(self, message: str = "Invalid service type") -> None:
        super().__init__(
            message,
            code="INVALID_SERVICE_TYPE",
            http_status=422,
        )
