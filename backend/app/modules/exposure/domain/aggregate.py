from __future__ import annotations

from datetime import UTC, datetime

from app.core.exceptions import InvalidValueError
from app.modules.exposure.domain.events import (
    AgentClaimGeneratedEvent,
    AgentCredentialsRemovedEvent,
    AgentResetEvent,
    PanelExposureChangedEvent,
    ServerExposureDisabledEvent,
    ServerExposureEnabledEvent,
    ServerExposureRemovedEvent,
)
from app.modules.exposure.domain.exceptions import DuplicateTargetError, UnregisteredPortError
from app.modules.exposure.domain.value_objects import (
    AgentProcessStatus,
    DesiredState,
    ExposureMethod,
    ExposureStatus,
    PanelExposureMethod,
    ServiceType,
    TargetProtocol,
)
from app.modules.shared.aggregate import AggregateRoot

# Ports that must never be exposed regardless of ServerModel.port configuration.
# RCON default (25575), common DB (3306, 5432, 6379, 27017), metrics (9100, 9090),
# and the internal management surface. `local_port` MUST also equal the owning
# server's ServerModel.port; the deny-list is defense-in-depth.
DENY_LIST_PORTS: frozenset[int] = frozenset(
    {
        25575,
        3306,
        5432,
        6379,
        27017,
        9090,
        9100,
    }
)


class HostPlayitAgent(AggregateRoot):
    def __init__(
        self,
        id: str = "default",
        secret_ciphertext: bytes | None = None,
        claim_code: str | None = None,
        claim_expires_at: datetime | None = None,
        process_status: AgentProcessStatus | str = AgentProcessStatus.STOPPED,
        last_health_at: datetime | None = None,
        desired_agent_running: bool = False,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._id = id
        self._secret_ciphertext = secret_ciphertext
        self._claim_code = claim_code
        self._claim_expires_at = claim_expires_at
        self._process_status = _coerce_agent_status(process_status)
        self._last_health_at = last_health_at
        self._desired_agent_running = desired_agent_running
        now = datetime.now(UTC)
        self._created_at = created_at or now
        self._updated_at = updated_at or now

    @property
    def id(self) -> str:
        return self._id

    @property
    def secret_ciphertext(self) -> bytes | None:
        return self._secret_ciphertext

    @property
    def claim_code(self) -> str | None:
        return self._claim_code

    @property
    def claim_expires_at(self) -> datetime | None:
        return self._claim_expires_at

    @property
    def process_status(self) -> AgentProcessStatus:
        return self._process_status

    @property
    def last_health_at(self) -> datetime | None:
        return self._last_health_at

    @property
    def desired_agent_running(self) -> bool:
        return self._desired_agent_running

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def is_claimed(self) -> bool:
        return self._secret_ciphertext is not None

    @property
    def has_active_claim(self) -> bool:
        if not self._claim_code or not self._claim_expires_at:
            return False
        expires = self._claim_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return datetime.now(UTC) < expires

    def generate_claim(self, claim_code: str, expires_at: datetime) -> None:
        self._claim_code = claim_code
        self._claim_expires_at = expires_at
        self._secret_ciphertext = None
        self._process_status = AgentProcessStatus.STARTING
        self._updated_at = datetime.now(UTC)
        self._add_event(AgentClaimGeneratedEvent())

    def store_secret(self, secret_ciphertext: bytes) -> None:
        self._secret_ciphertext = secret_ciphertext
        self._claim_code = None
        self._claim_expires_at = None
        self._updated_at = datetime.now(UTC)

    def clear_claim_fields(self) -> None:
        self._claim_code = None
        self._claim_expires_at = None
        self._updated_at = datetime.now(UTC)

    def set_process_status(self, status: AgentProcessStatus | str) -> None:
        self._process_status = _coerce_agent_status(status)
        self._updated_at = datetime.now(UTC)

    def set_desired_agent_running(self, desired: bool) -> None:
        self._desired_agent_running = desired
        self._updated_at = datetime.now(UTC)

    def set_last_health_at(self, value: datetime) -> None:
        self._last_health_at = value
        self._updated_at = datetime.now(UTC)

    def reset(self) -> None:
        """Wipe the secret and claim state. Targets move to CLAIM_REQUIRED."""
        self._secret_ciphertext = None
        self._claim_code = None
        self._claim_expires_at = None
        self._process_status = AgentProcessStatus.STOPPED
        self._updated_at = datetime.now(UTC)
        self._add_event(AgentResetEvent())

    def remove_credentials(self) -> None:
        self.reset()
        self._add_event(AgentCredentialsRemovedEvent())


class ServerExposureTarget(AggregateRoot):
    def __init__(
        self,
        exposure_id: str,
        local_port: int,
        id: str | None = None,
        protocol: TargetProtocol | str = TargetProtocol.TCP,
        service_type: ServiceType | str = ServiceType.JAVA,
        public_address: str | None = None,
        status: ExposureStatus | str = ExposureStatus.DISABLED,
        error_code: str | None = None,
        error_message: str | None = None,
        playit_tunnel_id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._id = id
        self._exposure_id = exposure_id
        self._protocol = _coerce_protocol(protocol)
        self._service_type = _coerce_service_type(service_type)
        self._local_port = local_port
        self._public_address = public_address
        self._status = _coerce_exposure_status(status)
        self._error_code = error_code
        self._error_message = error_message
        self._playit_tunnel_id = playit_tunnel_id
        now = datetime.now(UTC)
        self._created_at = created_at or now
        self._updated_at = updated_at or now

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def exposure_id(self) -> str:
        return self._exposure_id

    @property
    def protocol(self) -> TargetProtocol:
        return self._protocol

    @property
    def service_type(self) -> ServiceType:
        return self._service_type

    @property
    def local_port(self) -> int:
        return self._local_port

    @property
    def public_address(self) -> str | None:
        return self._public_address

    @property
    def playit_tunnel_id(self) -> str | None:
        return self._playit_tunnel_id

    @playit_tunnel_id.setter
    def playit_tunnel_id(self, value: str | None) -> None:
        self._playit_tunnel_id = value
        self._updated_at = datetime.now(UTC)

    def set_playit_tunnel(self, tunnel_id: str | None) -> None:
        self.playit_tunnel_id = tunnel_id

    @property
    def status(self) -> ExposureStatus:
        return self._status

    @property
    def error_code(self) -> str | None:
        return self._error_code

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def set_public_address(self, address: str | None) -> None:
        self._public_address = address
        self._updated_at = datetime.now(UTC)

    def set_error(self, code: str | None, message: str | None = None) -> None:
        self._error_code = code
        self._error_message = message
        self._updated_at = datetime.now(UTC)

    def _transition_to(self, new_status: ExposureStatus) -> None:
        allowed = _TARGET_TRANSITIONS.get(self._status, set())
        if new_status not in allowed:
            raise InvalidValueError(
                field="status",
                value=new_status.value,
                reason=f"Cannot transition from {self._status.value} to {new_status.value}",
            )
        self._status = new_status
        self._updated_at = datetime.now(UTC)

    def mark_starting(self) -> None:
        if self._status != ExposureStatus.STARTING:
            self._transition_to(ExposureStatus.STARTING)

    def mark_active(self, public_address: str | None = None) -> None:
        if self._status != ExposureStatus.ACTIVE:
            self._transition_to(ExposureStatus.ACTIVE)
        if public_address is not None:
            self._public_address = public_address
        self._error_code = None
        self._error_message = None
        self._updated_at = datetime.now(UTC)

    def mark_degraded(self) -> None:
        if self._status != ExposureStatus.DEGRADED:
            self._transition_to(ExposureStatus.DEGRADED)

    def mark_error(self, code: str | None = None, message: str | None = None) -> None:
        if self._status != ExposureStatus.ERROR:
            self._transition_to(ExposureStatus.ERROR)
        self.set_error(code, message)
        self._updated_at = datetime.now(UTC)

    def mark_reclaim_required(self, code: str | None = None, message: str | None = None) -> None:
        if self._status != ExposureStatus.RECLAIM_REQUIRED:
            self._transition_to(ExposureStatus.RECLAIM_REQUIRED)
        self.set_error(code, message)

    def mark_stopping(self) -> None:
        if self._status != ExposureStatus.STOPPING:
            self._transition_to(ExposureStatus.STOPPING)

    def mark_stopped(self) -> None:
        if self._status != ExposureStatus.STOPPED:
            self._transition_to(ExposureStatus.STOPPED)
        self._public_address = None

    def mark_disabled(self) -> None:
        if self._status != ExposureStatus.DISABLED:
            self._transition_to(ExposureStatus.DISABLED)
        self._public_address = None
        self._error_code = None
        self._error_message = None
        self._updated_at = datetime.now(UTC)


_TARGET_TRANSITIONS: dict[ExposureStatus, set[ExposureStatus]] = {
    ExposureStatus.DISABLED: {
        ExposureStatus.CLAIM_REQUIRED,
        ExposureStatus.STARTING,
        ExposureStatus.ACTIVE,
        ExposureStatus.ERROR,
        ExposureStatus.RECLAIM_REQUIRED,
    },
    ExposureStatus.CLAIM_REQUIRED: {
        ExposureStatus.STARTING,
        ExposureStatus.ACTIVE,
        ExposureStatus.DISABLED,
    },
    ExposureStatus.STARTING: {
        ExposureStatus.ACTIVE,
        ExposureStatus.CLAIM_REQUIRED,
        ExposureStatus.ERROR,
        ExposureStatus.RECLAIM_REQUIRED,
        ExposureStatus.DEGRADED,
        ExposureStatus.DISABLED,
    },
    ExposureStatus.ACTIVE: {
        ExposureStatus.STOPPING,
        ExposureStatus.DEGRADED,
        ExposureStatus.ERROR,
        ExposureStatus.RECLAIM_REQUIRED,
        ExposureStatus.DISABLED,
        ExposureStatus.STARTING,
        ExposureStatus.CLAIM_REQUIRED,
    },
    ExposureStatus.STOPPING: {
        ExposureStatus.STOPPED,
        ExposureStatus.ERROR,
        ExposureStatus.DISABLED,
    },
    ExposureStatus.STOPPED: {ExposureStatus.STARTING, ExposureStatus.DISABLED},
    ExposureStatus.DEGRADED: {
        ExposureStatus.ACTIVE,
        ExposureStatus.ERROR,
        ExposureStatus.RECLAIM_REQUIRED,
        ExposureStatus.STARTING,
        ExposureStatus.DISABLED,
    },
    ExposureStatus.ERROR: {
        ExposureStatus.STARTING,
        ExposureStatus.ACTIVE,
        ExposureStatus.RECLAIM_REQUIRED,
        ExposureStatus.DISABLED,
    },
    ExposureStatus.RECLAIM_REQUIRED: {
        ExposureStatus.STARTING,
        ExposureStatus.ACTIVE,
        ExposureStatus.DISABLED,
    },
}


class ServerExposure(AggregateRoot):
    """One exposure config per server, exactly one method, 1–N targets.

    Aggregate root owning lifecycle validation: target port equality with the
    server's ServerModel.port, the deny-list, NO_TARGETS contract, and state
    transitions. aggregate_status is a derived cache computed by the
    application layer (precedence fold), never accepted as a write input.
    """

    def __init__(
        self,
        server_id: str,
        method: ExposureMethod | str,
        id: str | None = None,
        desired_state: DesiredState | str = DesiredState.DISABLED,
        aggregate_status: ExposureStatus | str = ExposureStatus.DISABLED,
        targets: list[ServerExposureTarget] | None = None,
        cloudflare_tunnel_id: str | None = None,
        cloudflare_token_ciphertext: bytes | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._id = id
        self._server_id = server_id
        self._method = _coerce_exposure_method(method)
        self._desired_state = _coerce_desired_state(desired_state)
        self._aggregate_status = _coerce_exposure_status(aggregate_status)
        self._targets = targets or []
        self._cloudflare_tunnel_id = cloudflare_tunnel_id
        self._cloudflare_token_ciphertext = cloudflare_token_ciphertext
        now = datetime.now(UTC)
        self._created_at = created_at or now
        self._updated_at = updated_at or now

    @property
    def id(self) -> str | None:
        return self._id

    @property
    def server_id(self) -> str:
        return self._server_id

    @property
    def method(self) -> ExposureMethod:
        return self._method

    @property
    def desired_state(self) -> DesiredState:
        return self._desired_state

    @property
    def aggregate_status(self) -> ExposureStatus:
        return self._aggregate_status

    @property
    def targets(self) -> list[ServerExposureTarget]:
        return list(self._targets)

    @property
    def cloudflare_tunnel_id(self) -> str | None:
        return self._cloudflare_tunnel_id

    @property
    def cloudflare_token_ciphertext(self) -> bytes | None:
        return self._cloudflare_token_ciphertext

    @property
    def has_cloudflare_credentials(self) -> bool:
        return bool(self._cloudflare_tunnel_id and self._cloudflare_token_ciphertext)

    def set_cloudflare_credentials(self, tunnel_id: str, token_ciphertext: bytes) -> None:
        self._cloudflare_tunnel_id = tunnel_id
        self._cloudflare_token_ciphertext = token_ciphertext
        self._updated_at = datetime.now(UTC)

    def clear_cloudflare_credentials(self) -> None:
        self._cloudflare_tunnel_id = None
        self._cloudflare_token_ciphertext = None
        self._updated_at = datetime.now(UTC)

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def set_method(self, method: ExposureMethod | str) -> None:
        self._method = _coerce_exposure_method(method)
        self._updated_at = datetime.now(UTC)

    def set_desired_state(self, desired_state: DesiredState | str) -> None:
        self._desired_state = _coerce_desired_state(desired_state)
        self._updated_at = datetime.now(UTC)

    def set_aggregate_status(self, status: ExposureStatus | str) -> None:
        self._aggregate_status = _coerce_exposure_status(status)
        self._updated_at = datetime.now(UTC)

    def validate_target_port(
        self,
        local_port: int,
        server_port: int,
        service_type: ServiceType | str = ServiceType.JAVA,
        registered_port: int | None = None,
    ) -> None:
        """Port must equal the owning server's ServerModel.port (for Java) or
        the registered port for companion services, and must not be a
        deny-listed management/internal port."""
        st = _coerce_service_type(service_type)
        if st == ServiceType.JAVA:
            if local_port != server_port:
                raise InvalidValueError(
                    field="local_port",
                    value=local_port,
                    reason=f"must equal the server's game port ({server_port})",
                )
        else:
            if registered_port is None:
                raise UnregisteredPortError(
                    f"Service type {st.value} has no registered port for this server"
                )
            if local_port != registered_port:
                raise InvalidValueError(
                    field="local_port",
                    value=local_port,
                    reason=f"must equal the registered port ({registered_port}) for {st.value}",
                )

        if local_port in DENY_LIST_PORTS:
            raise InvalidValueError(
                field="local_port",
                value=local_port,
                reason="port is on the deny-list (management/RCON/DB/metrics)",
            )

    def create_target(
        self,
        local_port: int,
        server_port: int,
        target_id: str,
        service_type: ServiceType | str = ServiceType.JAVA,
        protocol: TargetProtocol | str = TargetProtocol.TCP,
        registered_port: int | None = None,
    ) -> ServerExposureTarget:
        st = _coerce_service_type(service_type)
        proto = _coerce_protocol(protocol)

        affinity_map = {
            ServiceType.JAVA: TargetProtocol.TCP,
            ServiceType.BEDROCK: TargetProtocol.UDP,
            ServiceType.VOICE: TargetProtocol.UDP,
            ServiceType.BLUEMAP: TargetProtocol.TCP,
        }
        expected_proto = affinity_map.get(st, TargetProtocol.TCP)
        if expected_proto != proto:
            raise InvalidValueError(
                field="protocol",
                value=proto.value,
                reason=f"Service type {st.value} requires protocol {expected_proto.value}",
            )

        self.validate_target_port(
            local_port=local_port,
            server_port=server_port,
            service_type=st,
            registered_port=registered_port,
        )

        existing = [t for t in self._targets if t.service_type == st and t.protocol == proto]
        if existing:
            raise DuplicateTargetError(
                f"a {st.value}/{proto.value} target already exists for this exposure"
            )

        target = ServerExposureTarget(
            id=target_id,
            exposure_id=self._id or "",
            local_port=local_port,
            service_type=st,
            protocol=proto,
        )
        self._targets.append(target)
        self._updated_at = datetime.now(UTC)
        return target

    def remove_target(self, target_id: str) -> ServerExposureTarget | None:
        for idx, t in enumerate(self._targets):
            if t.id == target_id:
                removed = self._targets.pop(idx)
                self._updated_at = datetime.now(UTC)
                return removed
        return None

    def enable(self, server_port: int, target_id: str) -> ServerExposureTarget:
        """Enable the exposure. Auto-creates the single java/tcp target from
        ServerModel.port (Flow 1) if none exists, satisfying NO_TARGETS."""
        self._desired_state = DesiredState.ENABLED
        if not self._targets:
            target = self.create_target(
                local_port=server_port,
                server_port=server_port,
                target_id=target_id,
            )
        else:
            target = self._targets[0]
        self._updated_at = datetime.now(UTC)
        self._add_event(
            ServerExposureEnabledEvent(server_id=self._server_id, method=self._method.value)
        )
        return target

    def disable(self) -> None:
        self._desired_state = DesiredState.DISABLED
        self._updated_at = datetime.now(UTC)
        self._add_event(ServerExposureDisabledEvent(server_id=self._server_id))

    def mark_deleted(self) -> None:
        self._add_event(ServerExposureRemovedEvent(server_id=self._server_id))


class PanelExposure(AggregateRoot):
    """Instance-level singleton. Separate from system_state.access_mode (MODEL B)."""

    def __init__(
        self,
        id: str = "default",
        method: PanelExposureMethod | str = PanelExposureMethod.NONE,
        desired_state: DesiredState | str = DesiredState.DISABLED,
        status: ExposureStatus | str = ExposureStatus.DISABLED,
        public_address: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        cloudflare_tunnel_id: str | None = None,
        cloudflare_token_ciphertext: bytes | None = None,
        external_port: int | None = None,
        playit_tunnel_id: str | None = None,
        upnp_last_result: str | None = None,
        upnp_last_mapped_at: datetime | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._id = id
        self._method = _coerce_panel_method(method)
        self._desired_state = _coerce_desired_state(desired_state)
        self._status = _coerce_exposure_status(status)
        self._public_address = public_address
        self._error_code = error_code
        self._error_message = error_message
        self._cloudflare_tunnel_id = cloudflare_tunnel_id
        self._cloudflare_token_ciphertext = cloudflare_token_ciphertext
        self._external_port = external_port
        self._playit_tunnel_id = playit_tunnel_id
        self._upnp_last_result = upnp_last_result
        self._upnp_last_mapped_at = upnp_last_mapped_at
        now = datetime.now(UTC)
        self._created_at = created_at or now
        self._updated_at = updated_at or now

    @property
    def id(self) -> str:
        return self._id

    @property
    def method(self) -> PanelExposureMethod:
        return self._method

    @property
    def desired_state(self) -> DesiredState:
        return self._desired_state

    @property
    def status(self) -> ExposureStatus:
        return self._status

    @property
    def public_address(self) -> str | None:
        return self._public_address

    @property
    def error_code(self) -> str | None:
        return self._error_code

    @property
    def error_message(self) -> str | None:
        return self._error_message

    @property
    def cloudflare_tunnel_id(self) -> str | None:
        return self._cloudflare_tunnel_id

    @property
    def cloudflare_token_ciphertext(self) -> bytes | None:
        return self._cloudflare_token_ciphertext

    @property
    def has_cloudflare_credentials(self) -> bool:
        return bool(self._cloudflare_tunnel_id and self._cloudflare_token_ciphertext)

    @property
    def external_port(self) -> int | None:
        return self._external_port

    @property
    def playit_tunnel_id(self) -> str | None:
        return self._playit_tunnel_id

    @property
    def upnp_last_result(self) -> str | None:
        return self._upnp_last_result

    @property
    def upnp_last_mapped_at(self) -> datetime | None:
        return self._upnp_last_mapped_at

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def update(self, method: PanelExposureMethod | str, desired_state: DesiredState | str) -> None:
        self._method = _coerce_panel_method(method)
        self._desired_state = _coerce_desired_state(desired_state)
        self._updated_at = datetime.now(UTC)
        self._add_event(
            PanelExposureChangedEvent(
                method=self._method.value, desired_state=self._desired_state.value
            )
        )

    def set_status(self, status: ExposureStatus | str) -> None:
        self._status = _coerce_exposure_status(status)
        self._updated_at = datetime.now(UTC)

    def set_public_address(self, address: str | None) -> None:
        self._public_address = address
        self._updated_at = datetime.now(UTC)

    def set_error(self, code: str | None, message: str | None = None) -> None:
        self._error_code = code
        self._error_message = message
        self._updated_at = datetime.now(UTC)

    def set_cloudflare_credentials(self, tunnel_id: str, token_ciphertext: bytes) -> None:
        self._cloudflare_tunnel_id = tunnel_id
        self._cloudflare_token_ciphertext = token_ciphertext
        self._updated_at = datetime.now(UTC)

    def clear_cloudflare_credentials(self) -> None:
        self._cloudflare_tunnel_id = None
        self._cloudflare_token_ciphertext = None
        self._updated_at = datetime.now(UTC)

    def set_port_forward_details(
        self,
        external_port: int | None,
        result: str | None,
        mapped_at: datetime | None,
    ) -> None:
        self._external_port = external_port
        self._upnp_last_result = result
        self._upnp_last_mapped_at = mapped_at
        self._updated_at = datetime.now(UTC)

    def set_playit_tunnel(self, tunnel_id: str | None) -> None:
        self._playit_tunnel_id = tunnel_id
        self._updated_at = datetime.now(UTC)

    def clear_playit_credentials(self) -> None:
        self._playit_tunnel_id = None
        self._updated_at = datetime.now(UTC)

    def clear_port_forward_details(self) -> None:
        self._external_port = None
        self._upnp_last_result = None
        self._upnp_last_mapped_at = None
        self._updated_at = datetime.now(UTC)


def _coerce_agent_status(value: AgentProcessStatus | str) -> AgentProcessStatus:
    if isinstance(value, AgentProcessStatus):
        return value
    return AgentProcessStatus(value.upper())


def _coerce_exposure_status(value: ExposureStatus | str) -> ExposureStatus:
    if isinstance(value, ExposureStatus):
        return value
    return ExposureStatus(value.upper())


def _coerce_desired_state(value: DesiredState | str) -> DesiredState:
    if isinstance(value, DesiredState):
        return value
    return DesiredState(value.upper())


def _coerce_exposure_method(value: ExposureMethod | str) -> ExposureMethod:
    if isinstance(value, ExposureMethod):
        return value
    return ExposureMethod(value.lower())


def _coerce_panel_method(value: PanelExposureMethod | str) -> PanelExposureMethod:
    if isinstance(value, PanelExposureMethod):
        return value
    return PanelExposureMethod(value.lower())


def _coerce_protocol(value: TargetProtocol | str) -> TargetProtocol:
    if isinstance(value, TargetProtocol):
        return value
    return TargetProtocol(value.lower())


def _coerce_service_type(value: ServiceType | str) -> ServiceType:
    if isinstance(value, ServiceType):
        return value
    return ServiceType(value.lower())
