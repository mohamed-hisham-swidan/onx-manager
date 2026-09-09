from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import (
    ConfigFactory,
    get_active_panel_bind,
    panel_ingress_target,
)
from app.core.event_bus import EventBus
from app.core.exceptions import InvalidValueError, NotFoundError, ValidationError
from app.core.idempotency import IdempotencyKey
from app.core.identity import IDENTITY
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.domain.aggregate import AccessMode
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository
from app.modules.exposure.domain.aggregate import (
    DENY_LIST_PORTS,
    HostPlayitAgent,
    PanelExposure,
    ServerExposure,
    ServerExposureTarget,
    _coerce_protocol,
    _coerce_service_type,
)
from app.modules.exposure.domain.exceptions import (
    ClaimActiveError,
    InvalidServiceTypeError,
    MethodProtocolIncompatibleError,
    NoTargetsError,
    PortAlreadyRegisteredError,
    UnregisteredPortError,
    WarningNotAcknowledgedError,
)
from app.modules.exposure.domain.repository import (
    HostAgentRepository,
    PanelExposureRepository,
    ServerExposureRepository,
)
from app.modules.exposure.domain.value_objects import (
    AgentProcessStatus,
    DesiredState,
    ExposureMethod,
    ExposureStatus,
    PanelExposureMethod,
    ServiceType,
    TargetProtocol,
    aggregate_precedence,
    exposure_status_to_process_status,
)
from app.modules.exposure.infrastructure.cloudflare import (
    CloudflareApiError,
    CloudflareAuthError,
    CloudflareClient,
)
from app.modules.exposure.infrastructure.cloudflared import (
    CloudflaredSupervisor,
    get_cloudflared_supervisor,
    get_server_cloudflared_supervisor,
)
from app.modules.exposure.infrastructure.models import ServerRegisteredPortModel
from app.modules.exposure.infrastructure.playit_agent import (
    generate_playit_claim_code,
    get_playit_supervisor,
)
from app.modules.exposure.infrastructure.playit_api import (
    PlayitAllocationFullError,
    PlayitApiClient,
    PlayitAuthError,
)
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
    SQLServerExposureRepository,
    SQLServerRegisteredPortRepository,
)
from app.modules.exposure.infrastructure.upnp import AsyncUPnPService
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.storage.encryption import build_backup_encryption

CLAIM_TTL_MINUTES = 10
logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.exposure")


async def compute_desired_agent_running(session: AsyncSession) -> bool:
    """Authoritative computation of host playit agent desired running state."""
    server_repo = SQLServerExposureRepository(session)
    panel_repo = SQLPanelExposureRepository(session)

    playit_servers = await server_repo.list_playit_enabled()
    panel = await panel_repo.get()

    panel_playit_enabled = (
        panel.method == PanelExposureMethod.PLAYIT_HTTP
        and panel.desired_state == DesiredState.ENABLED
    )
    return len(playit_servers) > 0 or panel_playit_enabled


async def _attempt_server_upnp_mapping(
    server_id: str,
    target: ServerExposureTarget,
) -> None:
    upnp = AsyncUPnPService()
    result = await upnp.attempt_mapping(
        internal_port=target.local_port,
        requested_external_port=target.local_port,
        description=f"ONX-Server-{server_id[:8]}-{target.service_type.value}",
        protocol=target.protocol.value.upper(),
    )
    if result.success:
        target.mark_active(f"{result.external_ip}:{result.external_port}")
    else:
        target.mark_error(code=result.error_code, message=result.error_message)


async def _sync_server_playit_targets(
    server_id: str,
    exposure: ServerExposure,
    secret_bytes: bytes,
) -> None:
    """Discover or create real playit.gg tunnels for server exposure targets."""
    secret_hex = secret_bytes.decode("utf-8")
    api_client = PlayitApiClient()
    rundata = None
    try:
        rundata = await api_client.get_rundata(secret_hex)
    except Exception as exc:
        logger.warning("Failed to query playit rundata for server %s: %s", server_id, exc)

    existing_tunnels = rundata.tunnels if rundata else []

    for target in exposure.targets:
        # 1. Match existing tunnel
        matched = None

        for t in existing_tunnels:
            if (
                t.local_port == target.local_port
                and t.port_type in (target.protocol.value, "both")
                and not t.is_disabled
            ):
                matched = t
                break

        if matched is not None and matched.display_address:
            target.playit_tunnel_id = matched.id
            target.mark_active(matched.display_address)
        else:
            # 2. Attempt creation via API
            try:
                tunnel_type = (
                    "minecraft-java"
                    if target.service_type == ServiceType.JAVA
                    else (
                        "minecraft-bedrock" if target.service_type == ServiceType.BEDROCK else None
                    )
                )
                new_t = await api_client.create_tunnel(
                    secret=secret_hex,
                    name=f"{IDENTITY.temp_prefix_new}{server_id[:6]}-{target.service_type.value[:8]}",
                    local_ip="127.0.0.1",
                    local_port=target.local_port,
                    port_type=target.protocol.value,
                    tunnel_type=tunnel_type,
                )
                if new_t.display_address:
                    target.playit_tunnel_id = new_t.id
                    target.mark_active(new_t.display_address)
                else:
                    target.mark_starting()
                    target.set_error(
                        "PLAYIT_TUNNEL_CREATION_PENDING",
                        "Tunnel creation pending on playit.gg. "
                        "The panel will auto-detect it once created.",
                    )
            except PlayitAllocationFullError:
                target.mark_starting()
                target.set_error(
                    "PLAYIT_ALLOCATION_FULL",
                    "playit.gg tunnel allocation limit reached. Manage tunnels on playit.gg.",
                )
            except Exception as exc:
                logger.warning(
                    "Auto playit tunnel creation failed for server target %s: %s", target.id, exc
                )
                target.mark_starting()
                target.set_error(
                    "PLAYIT_TUNNEL_CREATION_PENDING",
                    "Tunnel creation pending on playit.gg. "
                    "The panel will auto-detect it once created.",
                )


def _extract_target_external_port(target: ServerExposureTarget) -> int:
    if target.public_address and ":" in target.public_address:
        try:
            return int(target.public_address.split(":")[-1])
        except (ValueError, IndexError):
            pass
    return target.local_port


class SetServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    method: str
    desired_state: str
    cloudflare_token: str = ""
    hostname: str = ""
    acknowledged_warning: bool = False
    actor_id: str = ""


class SetServerExposureHandler(CommandHandler[SetServerExposureCommand]):
    """Create or update the exposure for a server (route #10)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: SetServerExposureCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        method = ExposureMethod(command.method.lower())
        desired = DesiredState(command.desired_state.upper())
        post_commit: list[Callable[[], Awaitable[None]]] = []

        # Server-side warning enforcement: must run before any Cloudflare API calls or DB writes
        if (
            method == ExposureMethod.CLOUDFLARE_TCP
            and desired == DesiredState.ENABLED
            and not command.acknowledged_warning
        ):
            raise WarningNotAcknowledgedError()

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            exposure = await repo.get(command.server_id)
            prev_method = exposure.method if exposure else None
            if exposure is None:
                exposure = ServerExposure(
                    server_id=command.server_id,
                    method=method,
                    id=str(uuid.uuid4().hex),
                )
            else:
                exposure.set_method(method)

            if desired == DesiredState.ENABLED:
                if not exposure.targets:
                    exposure.enable(
                        server_port=server.properties.port.value,
                        target_id=str(uuid.uuid4().hex),
                    )
                if not exposure.targets:
                    raise NoTargetsError()
                ports_repo = SQLServerRegisteredPortRepository(uow.session)
                for target in exposure.targets:
                    reg_port = None
                    if target.service_type != ServiceType.JAVA:
                        reg_model = await ports_repo.get_by_service_type(
                            command.server_id, target.service_type.value
                        )
                        reg_port = reg_model.port if reg_model else None
                    exposure.validate_target_port(
                        local_port=target.local_port,
                        server_port=server.properties.port.value,
                        service_type=target.service_type,
                        registered_port=reg_port,
                    )
                exposure.set_desired_state(DesiredState.ENABLED)

                if method == ExposureMethod.PORT_FORWARD:
                    if prev_method == ExposureMethod.CLOUDFLARE_TCP:
                        post_commit.append(
                            get_server_cloudflared_supervisor(command.server_id).stop
                        )
                    for target in exposure.targets:
                        target.mark_starting()

                    async def _run_server_upnp():
                        for target in exposure.targets:
                            await _attempt_server_upnp_mapping(command.server_id, target)
                        _fold_aggregate(exposure)
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLServerExposureRepository(post_uow.session)
                            await p_repo.save(exposure)
                            await post_uow.commit()

                    post_commit.append(_run_server_upnp)
                elif method == ExposureMethod.PLAYIT:
                    if prev_method == ExposureMethod.PORT_FORWARD:
                        for target in exposure.targets:
                            p = _extract_target_external_port(target)
                            proto = target.protocol.value.upper()
                            post_commit.append(
                                lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                    port, protocol=pr
                                )
                            )
                    if prev_method == ExposureMethod.CLOUDFLARE_TCP:
                        post_commit.append(
                            get_server_cloudflared_supervisor(command.server_id).stop
                        )

                    agent = await agent_repo.get()
                    supervisor = get_playit_supervisor()
                    if agent.is_claimed and agent.secret_ciphertext:
                        agent.set_desired_agent_running(True)
                        await agent_repo.save(agent)
                        try:
                            secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                            for target in exposure.targets:
                                target.mark_starting()

                            async def _run_server_playit(s=secret_bytes):
                                await _sync_server_playit_targets(
                                    command.server_id, exposure, s
                                )
                                _fold_aggregate(exposure)
                                async with UnitOfWork() as post_uow:
                                    p_repo = SQLServerExposureRepository(post_uow.session)
                                    await p_repo.save(exposure)
                                    await post_uow.commit()
                                await supervisor.start(
                                    s,
                                    on_status=_persist_playit_status,
                                    on_reconcile=_reconcile_playit_tunnels,
                                )

                            post_commit.append(_run_server_playit)
                        except Exception:
                            for target in exposure.targets:
                                target.mark_reclaim_required(
                                    code="RECLAIM_REQUIRED",
                                    message="Stored playit agent secret cannot be decrypted",
                                )
                    else:
                        for target in exposure.targets:
                            target._transition_to(ExposureStatus.CLAIM_REQUIRED)
                            target.set_error(
                                "CLAIM_REQUIRED",
                                "playit.gg host agent claim required before tunnel activation",
                            )
                        post_commit.append(
                            lambda: supervisor.start(None, on_status=_persist_playit_status)
                        )

                elif method == ExposureMethod.CLOUDFLARE_TCP:
                    if prev_method == ExposureMethod.PORT_FORWARD:
                        for target in exposure.targets:
                            p = _extract_target_external_port(target)
                            proto = target.protocol.value.upper()
                            post_commit.append(
                                lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                    port, protocol=pr
                                )
                            )
                    await self._enable_server_cloudflare_tcp(
                        exposure=exposure,
                        command=command,
                        post_commit=post_commit,
                    )
            else:
                exposure.set_desired_state(DesiredState.DISABLED)
                if (
                    prev_method == ExposureMethod.PORT_FORWARD
                    or method == ExposureMethod.PORT_FORWARD
                ):
                    for target in exposure.targets:
                        p = _extract_target_external_port(target)
                        proto = target.protocol.value.upper()
                        post_commit.append(
                            lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                port, protocol=pr
                            )
                        )
                if (
                    prev_method == ExposureMethod.CLOUDFLARE_TCP
                    or method == ExposureMethod.CLOUDFLARE_TCP
                ):
                    post_commit.append(get_server_cloudflared_supervisor(command.server_id).stop)

                for target in exposure.targets:
                    target.mark_disabled()

            _fold_aggregate(exposure)
            await repo.save(exposure)

            agent = await agent_repo.get()
            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        return CommandResult(success=True, data=_exposure_payload(exposure))

    async def _start_server_supervisor(
        self,
        supervisor: CloudflaredSupervisor,
        token: bytes,
        on_status: Callable[[ExposureStatus], Awaitable[None]],
    ) -> None:
        if supervisor.is_running:
            await supervisor.stop()
        await supervisor.start(token, on_status=on_status)

    async def _enable_server_cloudflare_tcp(
        self,
        exposure: ServerExposure,
        command: SetServerExposureCommand | EnableServerExposureCommand,
        post_commit: list[Callable[[], Awaitable[None]]],
    ) -> None:
        for target in exposure.targets:
            if target.protocol == TargetProtocol.UDP:
                raise MethodProtocolIncompatibleError(
                    "Cloudflare TCP exposure does not support UDP targets (Bedrock / Voice Chat). "
                    "Use playit.gg or Port Forwarding instead."
                )

        token = command.cloudflare_token.strip()
        hostname = command.hostname.strip()
        supervisor = get_server_cloudflared_supervisor(exposure.server_id)
        on_status = _make_persist_server_cloudflare_status(exposure.server_id)

        # Case 1: Token provided
        if token:
            # Subcase 1a: Tunnel already exists -> Token Rotation
            if exposure.cloudflare_tunnel_id:
                fallback = exposure.targets[0].public_address if exposure.targets else ""
                resolved_hostname = hostname or fallback
                if not resolved_hostname:
                    raise ValidationError(
                        "Hostname is required for Cloudflare TCP exposure",
                        field="hostname",
                    )
                ciphertext = _panel_encryption().encrypt(token.encode("utf-8"))
                exposure.set_cloudflare_credentials(exposure.cloudflare_tunnel_id, ciphertext)
                for target in exposure.targets:
                    target.mark_starting()
                    target.set_public_address(target.public_address or resolved_hostname)
                token_bytes = token.encode("utf-8")
                post_commit.append(
                    lambda t=token_bytes: self._start_server_supervisor(supervisor, t, on_status)
                )
                return

            # Subcase 1b: Fresh setup
            if not hostname:
                raise ValidationError(
                    "Hostname is required for Cloudflare TCP exposure",
                    field="hostname",
                )

            for target in exposure.targets:
                target.mark_starting()
                target.set_public_address(target.public_address or hostname)

            async def _run_fresh_cloudflare(tok=token, host=hostname):
                client = CloudflareClient(tok)
                ingress_rules: list[dict[str, str]] = []
                for target in exposure.targets:
                    target_host = target.public_address or host
                    ingress_rules.append(
                        {"hostname": target_host, "service": f"tcp://127.0.0.1:{target.local_port}"}
                    )
                ingress_rules.append({"service": "http_status:404"})

                try:
                    tunnel_name = f"{IDENTITY.temp_prefix_new}srv-{exposure.server_id[:8]}"
                    provisioned = await client.create_named_tunnel(name=tunnel_name)
                    await client.configure_ingress(provisioned.tunnel_id, ingress_rules)
                    for target in exposure.targets:
                        target_host = target.public_address or host
                        await client.create_cname(target_host, provisioned.tunnel_id)
                except CloudflareAuthError as exc:
                    for target in exposure.targets:
                        target.mark_reclaim_required(code="RECLAIM_REQUIRED", message=str(exc))
                    exposure.clear_cloudflare_credentials()
                    _fold_aggregate(exposure)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLServerExposureRepository(post_uow.session)
                        await p_repo.save(exposure)
                        await post_uow.commit()
                    return
                except CloudflareApiError as exc:
                    for target in exposure.targets:
                        target.mark_error(code="CLOUDFLARE_API_ERROR", message=str(exc))
                    exposure.clear_cloudflare_credentials()
                    _fold_aggregate(exposure)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLServerExposureRepository(post_uow.session)
                        await p_repo.save(exposure)
                        await post_uow.commit()
                    return

                ciphertext = _panel_encryption().encrypt(provisioned.token.encode("utf-8"))
                exposure.set_cloudflare_credentials(provisioned.tunnel_id, ciphertext)
                for target in exposure.targets:
                    target.mark_starting()
                    target.set_public_address(target.public_address or host)

                _fold_aggregate(exposure)
                async with UnitOfWork() as post_uow:
                    p_repo = SQLServerExposureRepository(post_uow.session)
                    await p_repo.save(exposure)
                    await post_uow.commit()

                token_bytes = provisioned.token.encode("utf-8")
                await self._start_server_supervisor(supervisor, token_bytes, on_status)

            post_commit.append(_run_fresh_cloudflare)
            return

        # Case 2: No token provided (reuse existing stored credentials)
        if exposure.has_cloudflare_credentials and exposure.cloudflare_token_ciphertext:
            for target in exposure.targets:
                target.mark_starting()
                if not target.public_address and hostname:
                    target.set_public_address(hostname)
            try:
                plaintext = _panel_encryption().decrypt(exposure.cloudflare_token_ciphertext)
                post_commit.append(
                    lambda t=plaintext: self._start_server_supervisor(supervisor, t, on_status)
                )
            except Exception:
                for target in exposure.targets:
                    target.mark_reclaim_required(
                        code="RECLAIM_REQUIRED",
                        message="Stored Cloudflare credentials cannot be decrypted",
                    )
                exposure.clear_cloudflare_credentials()
            return

        # Case 3: No token and no existing credentials
        raise ValidationError(
            "Cloudflare API token is required for Cloudflare TCP exposure",
            field="cloudflare_token",
        )


class EnableServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    cloudflare_token: str = ""
    hostname: str = ""
    acknowledged_warning: bool = False
    actor_id: str = ""
    desired_state: str = "ENABLED"


class EnableServerExposureHandler(CommandHandler[EnableServerExposureCommand]):
    """Enable exposure (route #11). Auto-creates java/tcp target from game port."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: EnableServerExposureCommand) -> CommandResult:
        server_id = ServerId(command.server_id)
        post_commit: list[Callable[[], Awaitable[None]]] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(server_id)
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            exposure = await repo.get(command.server_id)
            if exposure is None:
                exposure = ServerExposure(
                    server_id=command.server_id,
                    method=ExposureMethod.PLAYIT,
                    id=str(uuid.uuid4().hex),
                )

            # Warning check if method is CLOUDFLARE_TCP
            if (
                exposure.method == ExposureMethod.CLOUDFLARE_TCP
                and not command.acknowledged_warning
            ):
                raise WarningNotAcknowledgedError()

            game_port = server.properties.port.value
            exposure.enable(
                server_port=game_port,
                target_id=str(uuid.uuid4().hex),
            )

            agent = await agent_repo.get()
            supervisor = get_playit_supervisor()

            if exposure.method == ExposureMethod.PORT_FORWARD:
                for t in exposure.targets:
                    t.mark_starting()

                async def _run_enable_upnp():
                    for t in exposure.targets:
                        await _attempt_server_upnp_mapping(command.server_id, t)
                    _fold_aggregate(exposure)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLServerExposureRepository(post_uow.session)
                        await p_repo.save(exposure)
                        await post_uow.commit()

                post_commit.append(_run_enable_upnp)
            elif exposure.method == ExposureMethod.PLAYIT:
                if agent.is_claimed and agent.secret_ciphertext:
                    agent.set_desired_agent_running(True)
                    await agent_repo.save(agent)
                    try:
                        secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                        for t in exposure.targets:
                            t.mark_starting()

                        async def _run_enable_playit(s=secret_bytes):
                            await _sync_server_playit_targets(command.server_id, exposure, s)
                            _fold_aggregate(exposure)
                            async with UnitOfWork() as post_uow:
                                p_repo = SQLServerExposureRepository(post_uow.session)
                                await p_repo.save(exposure)
                                await post_uow.commit()
                            await supervisor.start(
                                s,
                                on_status=_persist_playit_status,
                                on_reconcile=_reconcile_playit_tunnels,
                            )

                        post_commit.append(_run_enable_playit)

                    except Exception:
                        for t in exposure.targets:
                            t.mark_reclaim_required(
                                code="RECLAIM_REQUIRED",
                                message="Stored playit agent secret cannot be decrypted",
                            )
                else:
                    for t in exposure.targets:
                        t._transition_to(ExposureStatus.CLAIM_REQUIRED)
                        t.set_error(
                            "CLAIM_REQUIRED",
                            "playit.gg host agent claim required before tunnel activation",
                        )
                    post_commit.append(
                        lambda: supervisor.start(None, on_status=_persist_playit_status)
                    )

            elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                handler = SetServerExposureHandler(self._event_bus)
                set_cmd = SetServerExposureCommand(
                    server_id=command.server_id,
                    method=ExposureMethod.CLOUDFLARE_TCP.value,
                    desired_state="ENABLED",
                    cloudflare_token=command.cloudflare_token,
                    hostname=command.hostname,
                    acknowledged_warning=command.acknowledged_warning,
                )
                await handler._enable_server_cloudflare_tcp(
                    exposure=exposure,
                    command=set_cmd,
                    post_commit=post_commit,
                )

            _fold_aggregate(exposure)
            await repo.save(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        payload = _exposure_payload(exposure)
        payload["target"] = payload["targets"][-1] if payload["targets"] else None
        return CommandResult(success=True, data=payload)


class DisableServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    actor_id: str = ""


class DisableServerExposureHandler(CommandHandler[DisableServerExposureCommand]):
    """Disable exposure (route #11)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DisableServerExposureCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[None]]] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposure = await repo.get(command.server_id)
            if exposure is None:
                raise NotFoundError(f"Exposure not found for server {command.server_id}")
            if exposure.desired_state == DesiredState.ENABLED:
                if exposure.method == ExposureMethod.PORT_FORWARD:
                    for target in exposure.targets:
                        p = _extract_target_external_port(target)
                        proto = target.protocol.value.upper()
                        post_commit.append(
                            lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                port, protocol=pr
                            )
                        )
                elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                    post_commit.append(get_server_cloudflared_supervisor(command.server_id).stop)
                elif (
                    exposure.method == ExposureMethod.PLAYIT
                    and agent.is_claimed
                    and agent.secret_ciphertext
                ):
                    try:
                        secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                        secret_hex = secret_bytes.decode("utf-8")
                        api_client = PlayitApiClient()
                        for target in exposure.targets:
                            if target.playit_tunnel_id:
                                post_commit.append(
                                    lambda s=secret_hex, tid=target.playit_tunnel_id: (
                                        api_client.delete_tunnel(s, tid)
                                    )
                                )
                    except Exception as exc:
                        logger.warning(
                            "Could not queue playit tunnel deletion on server disable: %s", exc
                        )
                exposure.disable()
                for target in exposure.targets:
                    target.mark_disabled()
            _fold_aggregate(exposure)
            await repo.save(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        return CommandResult(success=True, data=_exposure_payload(exposure))


class RemoveServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    actor_id: str = ""


class RemoveServerExposureHandler(CommandHandler[RemoveServerExposureCommand]):
    """Remove exposure config entirely (route #12, idempotent 204)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RemoveServerExposureCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[None]]] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposure = await repo.get(command.server_id)
            if exposure is None:
                return CommandResult(success=True, data={"removed": False})

            if exposure.method == ExposureMethod.PORT_FORWARD:
                for target in exposure.targets:
                    p = _extract_target_external_port(target)
                    proto = target.protocol.value.upper()
                    post_commit.append(
                        lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                            port, protocol=pr
                        )
                    )
            elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                post_commit.append(get_server_cloudflared_supervisor(command.server_id).stop)
            elif (
                exposure.method == ExposureMethod.PLAYIT
                and agent.is_claimed
                and agent.secret_ciphertext
            ):
                try:
                    secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                    secret_hex = secret_bytes.decode("utf-8")
                    api_client = PlayitApiClient()
                    for target in exposure.targets:
                        if target.playit_tunnel_id:
                            post_commit.append(
                                lambda s=secret_hex, tid=target.playit_tunnel_id: (
                                    api_client.delete_tunnel(s, tid)
                                )
                            )
                except Exception as exc:
                    logger.warning(
                        "Could not queue playit tunnel deletion on server remove: %s", exc
                    )
            exposure.mark_deleted()
            await repo.delete(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit server exposure action failed")

        return CommandResult(success=True, data={"removed": True})


class CreateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    service_type: str = "java"
    protocol: str | None = None
    local_port: int | None = None
    public_address: str | None = None
    actor_id: str = ""


class CreateExposureTargetHandler(CommandHandler[CreateExposureTargetCommand]):
    """Create a target for a server exposure (route #14). Validates port + deny-list."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateExposureTargetCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(ServerId(command.server_id))
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            exposure = await repo.get(command.server_id)
            if exposure is None:
                exposure = ServerExposure(
                    server_id=command.server_id,
                    method=ExposureMethod.PLAYIT,
                    id=str(uuid.uuid4().hex),
                )

            st = _coerce_service_type(command.service_type)

            if st == ServiceType.JAVA:
                proto = TargetProtocol.TCP
                if command.protocol and _coerce_protocol(command.protocol) != proto:
                    raise InvalidValueError(
                        field="protocol",
                        value=command.protocol,
                        reason="Java target requires TCP protocol",
                    )
                port = server.properties.port.value
                if command.local_port is not None and command.local_port != port:
                    raise InvalidValueError(
                        field="local_port",
                        value=command.local_port,
                        reason=f"Java target port must equal server game port ({port})",
                    )
                registered_port = None
            else:
                registered = await ports_repo.get_by_service_type(command.server_id, st.value)
                if registered is None:
                    raise UnregisteredPortError(
                        f"Service type {st.value} has no registered port "
                        f"for server {command.server_id}"
                    )
                registered_port = registered.port
                port = command.local_port if command.local_port is not None else registered.port
                proto = (
                    _coerce_protocol(command.protocol)
                    if command.protocol
                    else _coerce_protocol(registered.protocol)
                )

            # Fail-fast check if method is CLOUDFLARE_TCP and protocol is UDP
            if exposure.method == ExposureMethod.CLOUDFLARE_TCP and proto == TargetProtocol.UDP:
                raise MethodProtocolIncompatibleError()

            target = exposure.create_target(
                local_port=port,
                server_port=server.properties.port.value,
                target_id=str(uuid.uuid4().hex),
                service_type=st,
                protocol=proto,
                registered_port=registered_port,
            )
            if command.public_address:
                val = command.public_address.strip()
                if not re.match(r"^[a-zA-Z0-9.-]+(:\d{1,5})?$", val):
                    raise ValidationError("Invalid public address format")
                target.set_public_address(val)

            if (
                exposure.desired_state == DesiredState.ENABLED
                and exposure.method == ExposureMethod.PORT_FORWARD
            ):
                await _attempt_server_upnp_mapping(command.server_id, target)

            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_target_payload(target))


class UpdateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    target_id: str
    public_address: str | None = None
    actor_id: str = ""


class UpdateExposureTargetHandler(CommandHandler[UpdateExposureTargetCommand]):
    """Update an existing exposure target (e.g. manual public_address entry)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: UpdateExposureTargetCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(command.server_id)
            if exposure is None:
                raise NotFoundError(f"Exposure for server {command.server_id} not found")

            target = next((t for t in exposure.targets if t.id == command.target_id), None)
            if target is None:
                raise NotFoundError(
                    f"Target {command.target_id} not found on server {command.server_id}"
                )

            if command.public_address:
                val = command.public_address.strip()
                if not re.match(r"^[a-zA-Z0-9.-]+(:\d{1,5})?$", val):
                    raise ValidationError("Invalid public address format")
                target.set_public_address(val)
            else:
                target.set_public_address(None)

            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_target_payload(target))


class RegisterServerPortCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    service_type: str
    protocol: str
    port: int
    name: str | None = None
    actor_id: str = ""


class RegisterServerPortHandler(CommandHandler[RegisterServerPortCommand]):
    """Register a companion service port for a server."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: RegisterServerPortCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            server_repo = SQLServerRepository(uow.session)
            server = await server_repo.get(ServerId(command.server_id))
            if server is None:
                raise NotFoundError(f"Server {command.server_id} not found")

            st = _coerce_service_type(command.service_type)
            if st == ServiceType.JAVA:
                raise InvalidServiceTypeError(
                    "Java primary port cannot be registered in server_registered_ports "
                    "(managed via ServerModel.port)"
                )

            proto = _coerce_protocol(command.protocol)

            affinity_map = {
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

            if command.port < 1 or command.port > 65535:
                raise InvalidValueError(
                    field="port",
                    value=command.port,
                    reason="Port must be between 1 and 65535",
                )

            if command.port in DENY_LIST_PORTS:
                raise InvalidValueError(
                    field="port",
                    value=command.port,
                    reason="Port is on the deny-list (management/RCON/DB/metrics)",
                )

            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            existing_type = await ports_repo.get_by_service_type(command.server_id, st.value)
            if existing_type is not None:
                raise PortAlreadyRegisteredError(
                    f"A port for service type {st.value} is already registered on this server"
                )

            existing_port = await ports_repo.get_by_port_protocol(
                command.server_id, command.port, proto.value
            )
            if existing_port is not None:
                raise PortAlreadyRegisteredError(
                    f"Port {command.port}/{proto.value} is already registered on this server"
                )

            model = ServerRegisteredPortModel(
                id=uuid.uuid4().hex,
                server_id=command.server_id,
                service_type=st.value,
                protocol=proto.value,
                port=command.port,
                name=command.name,
            )
            await ports_repo.save(model)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "id": model.id,
                "server_id": model.server_id,
                "service_type": model.service_type,
                "protocol": model.protocol,
                "port": model.port,
                "name": model.name,
                "created_at": model.created_at.isoformat() if model.created_at else None,
                "updated_at": model.updated_at.isoformat() if model.updated_at else None,
            },
        )


class DeleteServerPortCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    server_id: str
    port_id: str
    actor_id: str = ""


class DeleteServerPortHandler(CommandHandler[DeleteServerPortCommand]):
    """Delete a registered companion port and clean up associated exposure target."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteServerPortCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[None]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            ports_repo = SQLServerRegisteredPortRepository(uow.session)
            port_model = await ports_repo.get(command.port_id)
            if port_model is None or port_model.server_id != command.server_id:
                raise NotFoundError(
                    f"Registered port {command.port_id} not found on server {command.server_id}"
                )

            st = port_model.service_type
            await ports_repo.delete(command.port_id)

            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(command.server_id)
            if exposure:
                target_to_remove = next(
                    (t for t in exposure.targets if t.service_type.value == st), None
                )
                if target_to_remove:
                    if (
                        exposure.desired_state == DesiredState.ENABLED
                        and exposure.method == ExposureMethod.PORT_FORWARD
                    ):
                        p = _extract_target_external_port(target_to_remove)
                        pr = target_to_remove.protocol.value.upper()
                        post_commit.append(
                            lambda port=p, proto=pr: AsyncUPnPService().delete_mapping(
                                port, protocol=proto
                            )
                        )
                    elif (
                        exposure.method == ExposureMethod.PLAYIT
                        and target_to_remove.playit_tunnel_id
                    ):
                        agent_repo = SQLHostAgentRepository(uow.session)
                        agent = await agent_repo.get()
                        if agent.is_claimed and agent.secret_ciphertext:
                            try:
                                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                                secret_hex = secret_bytes.decode("utf-8")
                                api_client = PlayitApiClient()
                                post_commit.append(
                                    lambda s=secret_hex, tid=target_to_remove.playit_tunnel_id: (
                                        api_client.delete_tunnel(s, tid)
                                    )
                                )
                            except Exception as exc:
                                logger.warning(
                                    "Could not queue playit tunnel deletion on port delete: %s", exc
                                )
                    exposure.remove_target(target_to_remove.id)
                    _fold_aggregate(exposure)
                    await repo.save(exposure)

            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit registered port cleanup failed")

        return CommandResult(success=True, data={"deleted": True})


class StopAllExposuresCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""


class StopAllExposuresHandler(CommandHandler[StopAllExposuresCommand]):
    """Disable all exposures, keep credentials (route #5)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: StopAllExposuresCommand) -> CommandResult:
        count = 0
        post_commit: list[Callable[[], Awaitable[None]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposures = await repo.list()
            for exposure in exposures:
                if exposure.desired_state == DesiredState.ENABLED:
                    if exposure.method == ExposureMethod.PORT_FORWARD:
                        for target in exposure.targets:
                            p = _extract_target_external_port(target)
                            proto = target.protocol.value.upper()
                            post_commit.append(
                                lambda port=p, pr=proto: AsyncUPnPService().delete_mapping(
                                    port, protocol=pr
                                )
                            )
                    elif exposure.method == ExposureMethod.CLOUDFLARE_TCP:
                        post_commit.append(
                            get_server_cloudflared_supervisor(exposure.server_id).stop
                        )
                    exposure.disable()
                    for target in exposure.targets:
                        target.mark_disabled()
                    _fold_aggregate(exposure)
                    await repo.save(exposure)
                    for event in exposure.collect_events():
                        uow.add_event(event)
                    count += 1

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)
                if not desired_running:
                    post_commit.append(get_playit_supervisor().stop)

            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit playit stop failed")

        return CommandResult(success=True, data={"disabled_count": count})


class GenerateClaimCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""
    claim_code: str = ""
    claim_url: str = ""
    force: bool = False


class GenerateClaimHandler(CommandHandler[GenerateClaimCommand]):
    """Generate a playit agent claim (route #2). 409 if active claim."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: GenerateClaimCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()

            if agent.has_active_claim and not command.force:
                raise ClaimActiveError()

            if command.claim_code:
                claim_code = command.claim_code
                claim_url = command.claim_url or f"https://playit.gg/claim/{claim_code}"
            else:
                claim_code, claim_url = await generate_playit_claim_code()

            expires_at = datetime.now(UTC) + timedelta(minutes=CLAIM_TTL_MINUTES)
            agent.generate_claim(claim_code, expires_at)
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        # Start supervisor in background claim exchange mode with the real claim code
        supervisor = get_playit_supervisor()
        try:
            await supervisor.start(
                claim_code=claim_code,
                on_secret=_handle_playit_claimed_secret,
            )
        except Exception:
            logger.warning(
                "Failed to start playit supervisor in claim exchange mode", exc_info=True
            )

        return CommandResult(
            success=True,
            data={
                "claim_code": claim_code,
                "claim_url": claim_url,
                "expires_at": expires_at.isoformat(),
            },
        )


class ResetAgentCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""


class ResetAgentHandler(CommandHandler[ResetAgentCommand]):
    """Reset the host agent (route #3). Clears secret; targets → CLAIM_REQUIRED."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: ResetAgentCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[Any]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.reset()
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        post_commit.append(get_playit_supervisor().stop)
        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.warning("Error executing post-commit action", exc_info=True)

        return CommandResult(success=True, data=_agent_payload(agent))


class RemoveCredentialsCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    actor_id: str = ""


class RemoveCredentialsHandler(CommandHandler[RemoveCredentialsCommand]):
    """Wipe agent credentials (route #6)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: RemoveCredentialsCommand) -> CommandResult:
        post_commit: list[Callable[[], Awaitable[Any]]] = []
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.remove_credentials()
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        post_commit.append(get_playit_supervisor().stop)
        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.warning("Error executing post-commit action", exc_info=True)

        return CommandResult(success=True, data={"success": True})


class SetPanelExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    method: str
    desired_state: str
    cloudflare_token: str = ""
    hostname: str = ""
    external_port: int | None = None
    actor_id: str = ""


def _panel_encryption():
    settings = ConfigFactory.global_settings()
    return build_backup_encryption(settings.backup_encryption_key_path or None)


class SetPanelExposureHandler(CommandHandler[SetPanelExposureCommand]):
    """Set panel exposure method + desired_state (route #8, idempotent).

    Supports:
      - ``cloudflare_tunnel``: Named Tunnel via CloudflareClient and cloudflared supervisor.
      - ``playit_http``: HTTPS edge tunnel via PlayitAgentSupervisor.
      - ``port_forward``: Local IGD port mapping via AsyncUPnPService.
      - ``none``: Disables and tears down any active panel exposure.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: SetPanelExposureCommand) -> CommandResult:
        method = PanelExposureMethod(command.method.lower())
        desired = DesiredState(command.desired_state.upper())

        post_commit: list[callable] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            state_repo = SQLSystemStateRepository(uow.session)
            panel = await repo.get()
            system_state = await state_repo.get()
            access_mode = system_state.access_mode

            # Idempotent no-op for an unchanged request, EXCEPT the
            # RECLAIM_REQUIRED recovery path: an owner-supplied fresh token
            # while the panel is already cloudflare_tunnel/ENABLED MUST reach
            # the rotation flow rather than silently short-circuiting
            # (design §7 "credential replacement").
            if panel.method == method and panel.desired_state == desired:
                is_reclaim_rotation = (
                    method == PanelExposureMethod.CLOUDFLARE_TUNNEL
                    and desired == DesiredState.ENABLED
                    and panel.status == ExposureStatus.RECLAIM_REQUIRED
                    and bool(command.cloudflare_token)
                )
                is_error_retry = (
                    desired == DesiredState.ENABLED and panel.status == ExposureStatus.ERROR
                )
                if not (is_reclaim_rotation or is_error_retry):
                    return CommandResult(
                        success=True, data=_panel_payload(panel, access_mode=access_mode)
                    )

            if method == PanelExposureMethod.CLOUDFLARE_TUNNEL:
                if desired == DesiredState.ENABLED:
                    await self._enable_cloudflare(uow, repo, panel, command, post_commit)
                else:
                    await self._disable_cloudflare(uow, repo, panel, post_commit)
            elif method == PanelExposureMethod.PLAYIT_HTTP:
                if desired == DesiredState.ENABLED:
                    await self._enable_playit_http(uow, repo, panel, post_commit)
                else:
                    await self._disable_playit_http(uow, repo, panel, post_commit)
            elif method == PanelExposureMethod.PORT_FORWARD:
                if desired == DesiredState.ENABLED:
                    await self._enable_port_forward(uow, repo, panel, command, post_commit)
                else:
                    await self._disable_port_forward(uow, repo, panel, post_commit)
            else:
                await self._disable_all_panel_methods(uow, repo, panel, post_commit)

            await repo.save(panel)
            for event in panel.collect_events():
                uow.add_event(event)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                import logging

                logging.getLogger(f"{IDENTITY.logger_prefix_new}.exposure").exception(
                    "post-commit exposure action failed"
                )

        return CommandResult(success=True, data=_panel_payload(panel, access_mode=access_mode))

    async def _enable_cloudflare(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        command: SetPanelExposureCommand,
        post_commit: list[callable],
    ) -> None:
        token = command.cloudflare_token
        hostname = command.hostname.strip().lower() if command.hostname else ""
        if not token:
            raise ValidationError("cloudflare_token is required to enable cloudflare_tunnel")

        # Clear alternative method state
        panel.clear_playit_credentials()
        panel.clear_port_forward_details()

        # RECLAIM_REQUIRED recovery (design §7 credential replacement): reuse
        # the existing tunnel id, rotate the ciphertext in place, restart the
        # supervised child. No new tunnel, no new CNAME, no DNS writes.
        if panel.status == ExposureStatus.RECLAIM_REQUIRED and panel.cloudflare_tunnel_id:
            await self._rotate_cloudflare_token(panel, token, hostname, post_commit)
            return

        if not hostname:
            raise ValidationError("hostname is required to enable cloudflare_tunnel")

        ingress = panel_ingress_target()
        panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
        panel.set_public_address(hostname)
        panel.set_status(ExposureStatus.STARTING)
        panel.set_error(None)

        async def _run_panel_cf(tok=token, host=hostname, ing=ingress):
            client = CloudflareClient(tok)
            try:
                provisioned = await client.create_named_tunnel(
                    name=f"{IDENTITY.temp_prefix_new}panel-{host}"
                )
                await client.configure_ingress(
                    provisioned.tunnel_id,
                    [
                        {"hostname": host, "service": ing},
                        {"service": "http_status:404"},
                    ],
                )
                await client.create_cname(host, provisioned.tunnel_id)
            except CloudflareAuthError as exc:
                panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                panel.set_public_address(None)
                panel.set_error("RECLAIM_REQUIRED", str(exc))
                panel.clear_cloudflare_credentials()
                async with UnitOfWork() as post_uow:
                    p_repo = SQLPanelExposureRepository(post_uow.session)
                    await p_repo.save(panel)
                    await post_uow.commit()
                return
            except CloudflareApiError as exc:
                panel.set_status(ExposureStatus.ERROR)
                panel.set_public_address(None)
                panel.set_error("CLOUDFLARE_API_ERROR", str(exc))
                panel.clear_cloudflare_credentials()
                async with UnitOfWork() as post_uow:
                    p_repo = SQLPanelExposureRepository(post_uow.session)
                    await p_repo.save(panel)
                    await post_uow.commit()
                return

            ciphertext = _panel_encryption().encrypt(provisioned.token.encode("utf-8"))
            panel.set_cloudflare_credentials(provisioned.tunnel_id, ciphertext)
            panel.set_public_address(host)
            panel.set_status(ExposureStatus.STARTING)
            panel.set_error(None)

            async with UnitOfWork() as post_uow:
                p_repo = SQLPanelExposureRepository(post_uow.session)
                await p_repo.save(panel)
                await post_uow.commit()

            token_bytes = provisioned.token.encode("utf-8")
            await self._start_supervisor(token_bytes)

        post_commit.append(_run_panel_cf)

    async def _rotate_cloudflare_token(
        self,
        panel: PanelExposure,
        token: str,
        hostname: str,
        post_commit: list[callable],
    ) -> None:
        """RECLAIM_REQUIRED recovery: replace the tunnel token in place.

        Reuses the existing ``cloudflare_tunnel_id`` and public address — no
        new tunnel, no new CNAME, no DNS writes (design §7 credential
        replacement, §6 single-CNAME). The fresh owner-supplied token is
        re-encrypted under the existing AES-GCM key and the supervised
        ``cloudflared`` child is restarted with it. A still-invalid token is
        re-detected by the supervisor's auth-failure markers, which persist
        RECLAIM_REQUIRED again (design §7) — the command never claims success
        for a token cloudflared rejects.
        """
        resolved_hostname = hostname or panel.public_address or ""
        if not resolved_hostname:
            raise ValidationError("hostname is required to enable cloudflare_tunnel")
        ciphertext = _panel_encryption().encrypt(token.encode("utf-8"))
        panel.set_cloudflare_credentials(panel.cloudflare_tunnel_id, ciphertext)
        panel.set_public_address(resolved_hostname)
        panel.set_status(ExposureStatus.STARTING)
        panel.set_error(None)
        token_bytes = token.encode("utf-8")
        post_commit.append(lambda t=token_bytes: self._restart_supervisor(t))

    async def _disable_cloudflare(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_cloudflare_credentials()
        post_commit.append(self._stop_supervisor)

    async def _enable_playit_http(
        self,
        uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        agent_repo = SQLHostAgentRepository(uow.session)
        agent = await agent_repo.get()

        panel.clear_cloudflare_credentials()
        panel.clear_port_forward_details()

        if agent.is_claimed and agent.secret_ciphertext:
            agent.set_desired_agent_running(True)
            await agent_repo.save(agent)
            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                secret_hex = secret_bytes.decode("utf-8")
            except Exception:
                panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
                panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                panel.set_public_address(None)
                panel.set_error(
                    "RECLAIM_REQUIRED",
                    "Stored playit agent secret cannot be decrypted",
                )
                return

            _active_host, internal_port = get_active_panel_bind()
            panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.STARTING)
            panel.set_public_address(None)
            panel.set_error(None)

            async def _run_panel_playit(s_hex=secret_hex, port=internal_port):
                api_client = PlayitApiClient()
                tunnel_obj = None

                # 1. Idempotency list-first check
                try:
                    rundata = await api_client.get_rundata(s_hex)
                    for t in rundata.tunnels:
                        if (
                            t.local_port == port
                            and t.port_type in ("tcp", "both")
                            and not t.is_disabled
                        ):
                            tunnel_obj = t
                            break
                except Exception as exc:
                    logger.warning("Failed to query playit rundata on panel enable: %s", exc)

                # 2. Attempt creation if not found
                if tunnel_obj is None:
                    try:
                        tunnel_obj = await api_client.create_tunnel(
                            secret=s_hex,
                            name=f"{IDENTITY.temp_prefix_new}panel-{panel.id[:6]}",
                            local_ip="127.0.0.1",
                            local_port=port,
                            port_type="tcp",
                        )
                    except PlayitAuthError:
                        panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                        panel.set_public_address(None)
                        panel.set_error(
                            "RECLAIM_REQUIRED",
                            "playit.gg reported an invalid or revoked agent secret",
                        )
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLPanelExposureRepository(post_uow.session)
                            await p_repo.save(panel)
                            await post_uow.commit()
                        return
                    except PlayitAllocationFullError:
                        panel.set_status(ExposureStatus.STARTING)
                        panel.set_public_address(None)
                        panel.set_error(
                            "PLAYIT_ALLOCATION_FULL",
                            "playit.gg tunnel allocation limit reached. "
                            "Manage tunnels in playit.gg dashboard.",
                        )
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLPanelExposureRepository(post_uow.session)
                            await p_repo.save(panel)
                            await post_uow.commit()
                        return
                    except Exception as exc:
                        logger.warning("Automatic playit tunnel creation failed: %s", exc)
                        panel.set_status(ExposureStatus.STARTING)
                        panel.set_public_address(None)
                        panel.set_error(
                            "PLAYIT_TUNNEL_CREATION_PENDING",
                            "Tunnel creation pending on playit.gg. "
                            "The panel will auto-detect it once created.",
                        )
                        async with UnitOfWork() as post_uow:
                            p_repo = SQLPanelExposureRepository(post_uow.session)
                            await p_repo.save(panel)
                            await post_uow.commit()
                        return

                if tunnel_obj is not None and tunnel_obj.display_address:
                    addr = tunnel_obj.display_address
                    address = f"http://{addr}" if not addr.startswith("http") else addr
                    panel.set_playit_tunnel(tunnel_obj.id)
                    panel.set_public_address(address)
                    panel.set_status(ExposureStatus.ACTIVE)
                    panel.set_error(None)
                    async with UnitOfWork() as post_uow:
                        p_repo = SQLPanelExposureRepository(post_uow.session)
                        await p_repo.save(panel)
                        await post_uow.commit()

            post_commit.append(lambda s=secret_bytes: self._start_playit_supervisor(s))
            post_commit.append(_run_panel_playit)
        else:
            panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.CLAIM_REQUIRED)
            panel.set_public_address(None)
            panel.set_error(
                "CLAIM_REQUIRED",
                "playit.gg host agent claim required before panel tunnel activation",
            )
            post_commit.append(lambda: self._start_playit_supervisor(None))

    async def _disable_playit_http(
        self,
        uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        agent_repo = SQLHostAgentRepository(uow.session)
        agent = await agent_repo.get()

        tunnel_id = panel.playit_tunnel_id
        if tunnel_id and agent.is_claimed and agent.secret_ciphertext:
            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                secret_hex = secret_bytes.decode("utf-8")
                api_client = PlayitApiClient()
                post_commit.append(
                    lambda s=secret_hex, tid=tunnel_id: api_client.delete_tunnel(s, tid)
                )
            except Exception as exc:
                logger.warning("Could not queue playit tunnel deletion on disable: %s", exc)

        panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_playit_credentials()

        desired_running = await compute_desired_agent_running(uow.session)
        if desired_running != agent.desired_agent_running:
            agent.set_desired_agent_running(desired_running)
            await agent_repo.save(agent)
            if not desired_running:
                post_commit.append(self._stop_playit_supervisor)

    async def _enable_port_forward(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        command: SetPanelExposureCommand,
        _post_commit: list[callable],
    ) -> None:
        active_bind_host, internal_port = get_active_panel_bind()
        requested_port = command.external_port or internal_port

        panel.clear_cloudflare_credentials()
        panel.clear_playit_credentials()

        normalized_host = active_bind_host.strip().lower()
        if normalized_host in ("127.0.0.1", "localhost", "::1") or normalized_host.startswith(
            "127."
        ):
            from app.core.settings_store import update_settings as update_settings_store

            update_settings_store({"panel_bind_host": "0.0.0.0"})
            panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.ERROR)
            panel.set_public_address(None)
            panel.set_error(
                "BIND_MISMATCH",
                f"Panel is bound to loopback ({active_bind_host}). Bind address was automatically "
                "updated to 0.0.0.0 in config/settings.yaml. Restart the panel for this to "
                "take effect, then port forwarding will activate.",
            )
            panel.set_port_forward_details(requested_port, "BIND_MISMATCH", datetime.now(UTC))
            return

        valid, err_code, err_msg = AsyncUPnPService.validate_external_port(requested_port)
        if not valid:
            panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.ERROR)
            panel.set_public_address(None)
            panel.set_error(err_code, err_msg)
            panel.set_port_forward_details(requested_port, err_code, datetime.now(UTC))
            return

        panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
        panel.set_status(ExposureStatus.STARTING)

        async def _run_panel_upnp(in_port=internal_port, req_port=requested_port):
            upnp = AsyncUPnPService()
            result = await upnp.attempt_mapping(
                internal_port=in_port,
                requested_external_port=req_port,
                description="ONX-Manager-Panel",
            )
            if result.success:
                panel.set_public_address(f"http://{result.external_ip}:{result.external_port}")
                panel.set_port_forward_details(result.external_port, "SUCCEEDED", datetime.now(UTC))
                panel.set_status(ExposureStatus.ACTIVE)
                panel.set_error(None)
            else:
                panel.set_public_address(None)
                panel.set_port_forward_details(req_port, result.error_code, datetime.now(UTC))
                panel.set_status(ExposureStatus.ERROR)
                panel.set_error(result.error_code, result.error_message)

            async with UnitOfWork() as post_uow:
                p_repo = SQLPanelExposureRepository(post_uow.session)
                await p_repo.save(panel)
                await post_uow.commit()

        _post_commit.append(_run_panel_upnp)

    async def _disable_port_forward(
        self,
        _uow: UnitOfWork,
        _repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        ext_port = panel.external_port
        panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_port_forward_details()
        if ext_port:
            post_commit.append(lambda p=ext_port: AsyncUPnPService().delete_mapping(p))

    async def _disable_all_panel_methods(
        self,
        uow: UnitOfWork,
        repo: PanelExposureRepository,
        panel: PanelExposure,
        post_commit: list[callable],
    ) -> None:
        prev_method = panel.method
        if prev_method == PanelExposureMethod.CLOUDFLARE_TUNNEL:
            await self._disable_cloudflare(uow, repo, panel, post_commit)
        elif prev_method == PanelExposureMethod.PLAYIT_HTTP:
            await self._disable_playit_http(uow, repo, panel, post_commit)
        elif prev_method == PanelExposureMethod.PORT_FORWARD:
            await self._disable_port_forward(uow, repo, panel, post_commit)

        panel.update(PanelExposureMethod.NONE, DesiredState.DISABLED)
        panel.set_status(ExposureStatus.DISABLED)
        panel.set_public_address(None)
        panel.set_error(None)
        panel.clear_cloudflare_credentials()
        panel.clear_playit_credentials()
        panel.clear_port_forward_details()

    async def _start_supervisor(self, token: bytes) -> None:
        supervisor = get_cloudflared_supervisor()
        await supervisor.start(token, on_status=_persist_panel_status)

    async def _restart_supervisor(self, token: bytes) -> None:
        supervisor = get_cloudflared_supervisor()
        if supervisor.is_running:
            await supervisor.stop()
        await supervisor.start(token, on_status=_persist_panel_status)

    async def _stop_supervisor(self) -> None:
        supervisor = get_cloudflared_supervisor()
        await supervisor.stop()

    async def _start_playit_supervisor(self, secret: bytes | None) -> None:
        supervisor = get_playit_supervisor()
        await supervisor.start(
            secret,
            on_status=_persist_playit_status,
            on_reconcile=_reconcile_playit_tunnels,
        )

    async def _stop_playit_supervisor(self) -> None:
        supervisor = get_playit_supervisor()
        await supervisor.stop()


async def _reconcile_playit_tunnels() -> None:
    """Periodically check playit.gg for pending tunnels and auto-adopt discovered ones."""
    try:
        async with UnitOfWork() as uow:
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()
            if not agent.is_claimed or not agent.secret_ciphertext:
                return

            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                secret_hex = secret_bytes.decode("utf-8")
            except Exception:
                return

            api_client = PlayitApiClient()
            rundata = await api_client.get_rundata(secret_hex)

            # Reconcile Panel Exposure
            panel_repo = SQLPanelExposureRepository(uow.session)
            panel = await panel_repo.get()
            if (
                panel.method == PanelExposureMethod.PLAYIT_HTTP
                and panel.desired_state == DesiredState.ENABLED
                and (panel.status != ExposureStatus.ACTIVE or not panel.playit_tunnel_id)
            ):
                _active_host, internal_port = get_active_panel_bind()
                for t in rundata.tunnels:
                    if (
                        t.local_port == internal_port
                        and t.port_type in ("tcp", "both")
                        and not t.is_disabled
                    ):
                        addr = t.display_address
                        address = f"http://{addr}" if not addr.startswith("http") else addr
                        panel.set_playit_tunnel(t.id)
                        panel.set_public_address(address)
                        panel.set_status(ExposureStatus.ACTIVE)
                        panel.set_error(None)
                        await panel_repo.save(panel)
                        break

            # Reconcile Server Exposures
            server_repo = SQLServerExposureRepository(uow.session)
            exposures = await server_repo.list_playit_enabled()
            for exposure in exposures:
                changed = False
                for target in exposure.targets:
                    if target.status != ExposureStatus.DISABLED and (
                        target.status != ExposureStatus.ACTIVE or not target.playit_tunnel_id
                    ):
                        for t in rundata.tunnels:
                            if (
                                t.local_port == target.local_port
                                and t.port_type in (target.protocol.value, "both")
                                and not t.is_disabled
                            ):
                                target.playit_tunnel_id = t.id
                                target.mark_active(t.display_address)
                                changed = True

                                break
                if changed:
                    _fold_aggregate(exposure)
                    await server_repo.save(exposure)

            await uow.commit()
    except Exception as exc:
        logger.debug("Playit background tunnel reconciliation skipped/failed: %s", exc)


async def _persist_panel_status(status: ExposureStatus) -> None:
    try:
        async with UnitOfWork() as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await repo.get()
            if panel.desired_state == DesiredState.DISABLED:
                return
            panel.set_status(status)
            if status == ExposureStatus.RECLAIM_REQUIRED:
                panel.set_error(
                    "RECLAIM_REQUIRED",
                    "cloudflared reported an invalid/revoked tunnel token",
                )
            await repo.save(panel)
            await uow.commit()
    except Exception:
        logger.exception("Failed to persist panel status %s", status.value)


def _make_persist_server_cloudflare_status(
    server_id: str,
) -> Callable[[ExposureStatus], Awaitable[None]]:
    async def _persist_status(status: ExposureStatus) -> None:
        try:
            async with UnitOfWork() as uow:
                repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
                exposure = await repo.get(server_id)
                if exposure is None or exposure.desired_state == DesiredState.DISABLED:
                    return
                for target in exposure.targets:
                    if target.status != ExposureStatus.DISABLED:
                        if status == ExposureStatus.ACTIVE:
                            target.mark_active(target.public_address or "")
                        elif status == ExposureStatus.RECLAIM_REQUIRED:
                            target.mark_reclaim_required(
                                code="RECLAIM_REQUIRED",
                                message="cloudflared reported an invalid/revoked tunnel token",
                            )
                        elif status == ExposureStatus.DEGRADED:
                            target.mark_degraded()
                        elif status == ExposureStatus.ERROR:
                            target.mark_error(
                                code="CLOUDFLARED_CRASHED",
                                message="cloudflared process crashed or failed health check",
                            )
                        elif status == ExposureStatus.STARTING:
                            target.mark_starting()
                        elif status == ExposureStatus.STOPPED:
                            target.mark_stopped()
                _fold_aggregate(exposure)
                await repo.save(exposure)
                await uow.commit()
        except Exception:
            logger.exception(
                "Failed to persist server %s cloudflare status %s",
                server_id,
                status.value,
            )

    return _persist_status


async def _persist_playit_status(status: ExposureStatus) -> None:
    try:
        async with UnitOfWork() as uow:
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()
            agent.set_process_status(exposure_status_to_process_status(status))
            await agent_repo.save(agent)

            server_repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposures = await server_repo.list_playit_enabled()
            for exposure in exposures:
                for target in exposure.targets:
                    if target.status != ExposureStatus.DISABLED:
                        if status == ExposureStatus.ACTIVE:
                            target.mark_active(target.public_address or "")
                        elif status == ExposureStatus.RECLAIM_REQUIRED:
                            target.mark_reclaim_required(
                                code="RECLAIM_REQUIRED",
                                message="playit.gg reported an invalid or revoked agent secret",
                            )
                        elif status == ExposureStatus.DEGRADED:
                            target.mark_degraded()
                        elif status == ExposureStatus.ERROR:
                            target.mark_error(
                                code="AGENT_CRASHED",
                                message="playit agent process crashed",
                            )
                        elif status == ExposureStatus.CLAIM_REQUIRED:
                            target._transition_to(ExposureStatus.CLAIM_REQUIRED)
                            target.set_error(
                                "CLAIM_REQUIRED",
                                "playit.gg host agent claim required before tunnel activation",
                            )
                        elif status == ExposureStatus.STOPPED:
                            target.mark_stopped()
                _fold_aggregate(exposure)
                await server_repo.save(exposure)

            panel_repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await panel_repo.get()
            if (
                panel.method == PanelExposureMethod.PLAYIT_HTTP
                and panel.desired_state == DesiredState.ENABLED
            ):
                panel.set_status(status)
                if status == ExposureStatus.RECLAIM_REQUIRED:
                    panel.set_error(
                        "RECLAIM_REQUIRED",
                        "playit.gg reported an invalid or revoked agent secret",
                    )
                await panel_repo.save(panel)

            await uow.commit()
    except Exception:
        logger.exception("Failed to persist playit status %s", status.value)


async def _handle_playit_claimed_secret(secret: str) -> None:
    """Invoked when PlayitAgentSupervisor captures the secret key from claim exchange."""
    try:
        secret_bytes = secret.strip().encode("utf-8")
        ciphertext = _panel_encryption().encrypt(secret_bytes)

        from app.api.deps import get_event_bus

        event_bus = None
        try:
            event_bus = await get_event_bus()
        except RuntimeError:
            event_bus = None

        async with UnitOfWork(event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.store_secret(ciphertext)
            agent.set_process_status(AgentProcessStatus.STARTING)
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        logger.info("Host playit agent secret encrypted and persisted to database")

        # Now start the daemon with the newly encrypted secret
        supervisor = get_playit_supervisor()
        await supervisor.restart(
            secret=secret_bytes,
            on_status=_persist_playit_status,
        )
    except Exception as exc:
        logger.exception("Failed to handle playit claimed secret: %s", exc)


class ReconcileExposureCommand(Command):
    idempotency_key: IdempotencyKey = Field(default_factory=IdempotencyKey)
    scope: str = "server"
    actor_id: str = ""


class ReconcileExposureHandler(CommandHandler[ReconcileExposureCommand]):
    """Manual reconciliation trigger (route #4). Recomputes derived state."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: ReconcileExposureCommand) -> CommandResult:
        post_commit: list[callable] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()

            exposures = await repo.list()
            for exposure in exposures:
                if (
                    exposure.desired_state == DesiredState.ENABLED
                    and exposure.method == ExposureMethod.PORT_FORWARD
                ):
                    def _make_reconcile_upnp(exp=exposure):
                        async def _act():
                            for target in exp.targets:
                                await _attempt_server_upnp_mapping(exp.server_id, target)
                            _fold_aggregate(exp)
                            async with UnitOfWork() as post_uow:
                                p_repo = SQLServerExposureRepository(post_uow.session)
                                await p_repo.save(exp)
                                await post_uow.commit()
                        return _act

                    post_commit.append(_make_reconcile_upnp())
                elif (
                    exposure.desired_state == DesiredState.ENABLED
                    and exposure.method == ExposureMethod.CLOUDFLARE_TCP
                    and exposure.has_cloudflare_credentials
                ):
                    srv_supervisor = get_server_cloudflared_supervisor(exposure.server_id)
                    should_start = (
                        exposure.aggregate_status != ExposureStatus.RECLAIM_REQUIRED
                        and not srv_supervisor.is_running
                    )
                    if should_start:
                        # ISS-069: move decryption out of the transaction into post_commit
                        def _make_reconcile_cf(
                            sid=exposure.server_id,
                            ctext=exposure.cloudflare_token_ciphertext,
                        ):
                            async def _act():
                                sup = get_server_cloudflared_supervisor(sid)
                                if sup.is_running:
                                    return
                                try:
                                    plaintext = _panel_encryption().decrypt(ctext)
                                    on_status = _make_persist_server_cloudflare_status(sid)
                                    await sup.start(plaintext, on_status=on_status)
                                except Exception:
                                    logger.exception(
                                        "Failed to decrypt server cloudflare token on reconcile"
                                    )
                            return _act

                        post_commit.append(_make_reconcile_cf())
                elif (
                    exposure.desired_state == DesiredState.DISABLED
                    and exposure.method == ExposureMethod.CLOUDFLARE_TCP
                ):
                    srv_supervisor = get_server_cloudflared_supervisor(exposure.server_id)
                    if srv_supervisor.is_running:
                        post_commit.append(srv_supervisor.stop)
                _fold_aggregate(exposure)
                await repo.save(exposure)

            desired_running = await compute_desired_agent_running(uow.session)
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)

            supervisor = get_playit_supervisor()
            if (
                desired_running
                and agent.is_claimed
                and agent.secret_ciphertext
                and not supervisor.is_running
            ):
                def _make_reconcile_playit(ctext=agent.secret_ciphertext):
                    async def _act():
                        sup = get_playit_supervisor()
                        if sup.is_running:
                            return
                        try:
                            secret_bytes = _panel_encryption().decrypt(ctext)
                            await sup.start(secret_bytes, on_status=_persist_playit_status)
                        except Exception:
                            logger.exception("Failed to decrypt secret on reconcile")
                    return _act

                post_commit.append(_make_reconcile_playit())
            elif not desired_running and supervisor.is_running:
                post_commit.append(supervisor.stop)

            await self._reconcile_panel(uow, post_commit)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:
                logger.exception("Post-commit reconcile action failed")

        return CommandResult(success=True, data={"reconciled": True})

    async def _reconcile_panel(self, uow: UnitOfWork, post_commit: list[callable]) -> None:
        """Restore the panel Cloudflare tunnel from the persisted desired state.

        Uses only the stored aggregate (desired_state, method, credentials):
          - ENABLED + cloudflare_tunnel + stored credentials + not running
            -> restart the supervised child.
          - RECLAIM_REQUIRED -> leave it; the owner must provide a new token.
          - DISABLED -> ensure the child is stopped.
        """
        repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
        panel = await repo.get()
        supervisor = get_cloudflared_supervisor()

        if (
            panel.method == PanelExposureMethod.CLOUDFLARE_TUNNEL
            and panel.desired_state == DesiredState.ENABLED
            and panel.has_cloudflare_credentials
        ):
            if panel.status == ExposureStatus.RECLAIM_REQUIRED:
                return
            if supervisor.is_running:
                return
            def _make_panel_cf(ctext=panel.cloudflare_token_ciphertext):
                async def _act():
                    sup = get_cloudflared_supervisor()
                    if sup.is_running:
                        return
                    try:
                        plaintext = _panel_encryption().decrypt(ctext)
                        await sup.start(plaintext, on_status=_persist_panel_status)
                    except Exception:
                        logger.exception("Failed to decrypt panel cloudflare token on reconcile")
                return _act

            post_commit.append(_make_panel_cf())
        elif (
            panel.method == PanelExposureMethod.CLOUDFLARE_TUNNEL
            and panel.desired_state == DesiredState.DISABLED
        ):
            post_commit.append(supervisor.stop)


def _fold_aggregate(exposure: ServerExposure) -> None:
    """Recompute the derived aggregate_status cache.

    desired_state=DISABLED overrides every target status (§4.3). For an
    ENABLED exposure the approved precedence applies; NO_TARGETS for an
    enabled exposure is rejected at the API layer, so an enabled fold always
    sees one or more targets.
    """
    if exposure.desired_state == DesiredState.DISABLED:
        exposure.set_aggregate_status(ExposureStatus.DISABLED)
        return
    statuses = [t.status for t in exposure.targets]
    folded = aggregate_precedence(statuses)
    exposure.set_aggregate_status(folded)


def _agent_payload(agent: HostPlayitAgent) -> dict:
    return {
        "claimed": agent.is_claimed,
        "process_status": agent.process_status.value,
        "desired_agent_running": agent.desired_agent_running,
        "last_health_at": agent.last_health_at.isoformat() if agent.last_health_at else None,
        "claim_active": agent.has_active_claim,
        "claim_expires_at": agent.claim_expires_at.isoformat() if agent.claim_expires_at else None,
    }


def _panel_payload(
    panel: PanelExposure,
    access_mode: AccessMode | str = AccessMode.LOCAL,
) -> dict:
    is_port_forward = panel.method == PanelExposureMethod.PORT_FORWARD
    is_playit = panel.method == PanelExposureMethod.PLAYIT_HTTP
    is_enabled = panel.desired_state == DesiredState.ENABLED
    sec_advisory = None
    mode_str = access_mode.value if isinstance(access_mode, AccessMode) else str(access_mode)

    if is_port_forward and is_enabled:
        if mode_str.upper() == "LOCAL":
            sec_advisory = (
                "Port forwarding exposes the panel over unencrypted HTTP while Access Mode "
                "is LOCAL. Open self-registration is exposed to the public Internet! Switch to "
                "GLOBAL (Invite-Only) mode in Settings -> Access to secure the instance."
            )
        else:
            sec_advisory = (
                "Port forwarding exposes the panel over unencrypted HTTP. "
                "Ensure credentials are not transmitted across untrusted public networks."
            )
    elif is_playit and is_enabled:
        sec_advisory = (
            "Playit.gg free tier exposes the panel over raw TCP (HTTP). Credentials are "
            "transmitted without TLS encryption. For encrypted HTTPS access, switch to "
            "Cloudflare Tunnel or upgrade to Playit Premium."
        )

    fix_hint = None
    auto_fixed = False
    if panel.error_code == "BIND_MISMATCH":
        auto_fixed = True
        fix_hint = (
            "Panel bind address updated to 0.0.0.0 in config/settings.yaml. "
            "Restart the panel for this to take effect, then port forwarding will activate."
        )

    return {
        "method": panel.method.value,
        "desired_state": panel.desired_state.value,
        "status": panel.status.value,
        "public_address": panel.public_address,
        "tls": not (is_port_forward or is_playit),
        "protocol": "http" if (is_port_forward or is_playit) else "https",
        "external_port": panel.external_port,
        "cloudflare_tunnel_id": panel.cloudflare_tunnel_id,
        "playit_tunnel_id": panel.playit_tunnel_id,
        "upnp_last_result": panel.upnp_last_result,
        "error_code": panel.error_code,
        "error_message": panel.error_message,
        "fix_hint": fix_hint,
        "auto_fixed": auto_fixed,
        "security_advisory": sec_advisory,
    }


def _target_payload(target: ServerExposureTarget) -> dict:
    dashboard_url = None
    setup_instructions = None
    if (
        target.status in (ExposureStatus.STARTING, ExposureStatus.ACTIVE)
        and not target.public_address
    ):
        dashboard_url = "https://playit.gg/manage"
        st_name = target.service_type.value.capitalize()
        proto_name = target.protocol.value.upper()
        setup_instructions = (
            f"Add a {st_name} ({proto_name}) tunnel on playit.gg pointing to local address "
            f"127.0.0.1:{target.local_port}."
        )
    return {
        "id": target.id,
        "exposure_id": target.exposure_id,
        "protocol": target.protocol.value,
        "service_type": target.service_type.value,
        "local_port": target.local_port,
        "public_address": target.public_address,
        "dashboard_url": dashboard_url,
        "setup_instructions": setup_instructions,
        "status": target.status.value,
        "error_code": target.error_code,
        "error_message": target.error_message,
    }


def _exposure_payload(exposure: ServerExposure) -> dict:
    return {
        "server_id": exposure.server_id,
        "method": exposure.method.value,
        "desired_state": exposure.desired_state.value,
        "aggregate_status": exposure.aggregate_status.value,
        "error_code": None,
        "error_message": None,
        "cloudflare_tunnel_id": exposure.cloudflare_tunnel_id,
        "has_cloudflare_credentials": exposure.has_cloudflare_credentials,
        "targets": [_target_payload(t) for t in exposure.targets],
    }
