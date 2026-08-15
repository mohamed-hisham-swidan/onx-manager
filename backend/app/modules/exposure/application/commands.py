from __future__ import annotations

import logging
import re
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import (
    ConfigFactory,
    get_active_panel_bind,
    panel_ingress_target,
)
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
from app.modules.auth.domain.aggregate import AccessMode
from app.modules.auth.infrastructure.repository import SQLSystemStateRepository
from app.modules.exposure.domain.aggregate import (
    HostPlayitAgent,
    PanelExposure,
    ServerExposure,
    ServerExposureTarget,
)
from app.modules.exposure.domain.exceptions import ClaimActiveError, NoTargetsError
from app.modules.exposure.domain.repository import (
    HostAgentRepository,
    PanelExposureRepository,
    ServerExposureRepository,
)
from app.modules.exposure.domain.value_objects import (
    DesiredState,
    ExposureMethod,
    ExposureStatus,
    PanelExposureMethod,
    aggregate_precedence,
)
from app.modules.exposure.infrastructure.cloudflare import (
    CloudflareApiError,
    CloudflareAuthError,
    CloudflareClient,
)
from app.modules.exposure.infrastructure.cloudflared import get_cloudflared_supervisor
from app.modules.exposure.infrastructure.playit_agent import get_playit_supervisor
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
    SQLServerExposureRepository,
)
from app.modules.exposure.infrastructure.upnp import AsyncUPnPService
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.storage.encryption import build_backup_encryption

CLAIM_TTL_MINUTES = 10
logger = logging.getLogger("mcs.exposure")


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


class SetServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    method: str
    desired_state: str
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
                    method=method,
                    id=str(uuid.uuid4().hex),
                )
            else:
                exposure.set_method(method)

            if desired == DesiredState.ENABLED:
                if not exposure.targets:
                    raise NoTargetsError()
                for target in exposure.targets:
                    exposure.validate_target_port(target.local_port, server.properties.port.value)
                exposure.set_desired_state(DesiredState.ENABLED)

                agent = await agent_repo.get()
                if method == ExposureMethod.PLAYIT:
                    supervisor = get_playit_supervisor()
                    if agent.is_claimed and agent.secret_ciphertext:
                        try:
                            secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                            for target in exposure.targets:
                                if supervisor.is_running:
                                    target.mark_active(target.public_address or "")
                                else:
                                    target.mark_starting()
                            post_commit.append(
                                lambda s=secret_bytes: supervisor.start(
                                    s, on_status=_persist_playit_status
                                )
                            )
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
            else:
                exposure.set_desired_state(DesiredState.DISABLED)
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
                logger.exception("Post-commit playit action failed")

        return CommandResult(success=True, data=_exposure_payload(exposure))


class EnableServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
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

            game_port = server.properties.port.value
            exposure.enable(
                server_port=game_port,
                target_id=str(uuid.uuid4().hex),
            )

            agent = await agent_repo.get()
            supervisor = get_playit_supervisor()

            if exposure.method == ExposureMethod.PLAYIT:
                if agent.is_claimed and agent.secret_ciphertext:
                    try:
                        secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                        for target in exposure.targets:
                            if supervisor.is_running:
                                target.mark_active(target.public_address or "")
                            else:
                                target.mark_starting()
                        post_commit.append(
                            lambda s=secret_bytes: supervisor.start(
                                s, on_status=_persist_playit_status
                            )
                        )
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
                logger.exception("Post-commit playit action failed")

        payload = _exposure_payload(exposure)
        payload["target"] = payload["targets"][-1] if payload["targets"] else None
        return CommandResult(success=True, data=payload)


class DisableServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
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
                raise NotFoundError(
                    f"Exposure not found for server {command.server_id}",
                    code="NOT_FOUND",
                )
            if exposure.desired_state == DesiredState.ENABLED:
                exposure.disable()
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
                logger.exception("Post-commit playit stop failed")

        return CommandResult(success=True, data=_exposure_payload(exposure))


class RemoveServerExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
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
                logger.exception("Post-commit playit stop failed")

        return CommandResult(success=True, data={"removed": True})


class CreateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
    public_address: str | None = None
    actor_id: str = ""


class CreateExposureTargetHandler(CommandHandler[CreateExposureTargetCommand]):
    """Create a target for a server exposure (route #14). Validates port + deny-list."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateExposureTargetCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
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

            target = exposure.create_target(
                local_port=server.properties.port.value,
                server_port=server.properties.port.value,
                target_id=str(uuid.uuid4().hex),
            )
            if command.public_address:
                val = command.public_address.strip()
                if not re.match(r"^[a-zA-Z0-9.-]+(:\d{1,5})?$", val):
                    raise ValidationError("Invalid public address format")
                target.set_public_address(val)

            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_target_payload(target))


class UpdateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
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


class StopAllExposuresCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
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
                    exposure.disable()
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
    idempotency_key: IdempotencyKey = IdempotencyKey()
    actor_id: str = ""
    claim_code: str = ""
    claim_url: str = ""


class GenerateClaimHandler(CommandHandler[GenerateClaimCommand]):
    """Generate a playit agent claim (route #2). 409 if active claim."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: GenerateClaimCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()

            if agent.has_active_claim:
                raise ClaimActiveError()

            claim_code = command.claim_code or _fresh_claim_code()
            claim_url = command.claim_url or "https://playit.gg/claim"
            expires_at = datetime.now(UTC) + timedelta(minutes=CLAIM_TTL_MINUTES)
            agent.generate_claim(claim_code, expires_at)
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(
            success=True,
            data={
                "claim_code": claim_code,
                "claim_url": claim_url,
                "expires_at": expires_at.isoformat(),
            },
        )


class ResetAgentCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    actor_id: str = ""


class ResetAgentHandler(CommandHandler[ResetAgentCommand]):
    """Reset the host agent (route #3). Clears secret; targets → CLAIM_REQUIRED."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: ResetAgentCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.reset()
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_agent_payload(agent))


class RemoveCredentialsCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    actor_id: str = ""


class RemoveCredentialsHandler(CommandHandler[RemoveCredentialsCommand]):
    """Wipe agent credentials (route #6)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: RemoveCredentialsCommand) -> CommandResult:
        async with UnitOfWork(self._event_bus) as uow:
            repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await repo.get()
            agent.remove_credentials()
            await repo.save(agent)
            for event in agent.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"success": True})


class SetPanelExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
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
                    desired == DesiredState.ENABLED
                    and panel.status == ExposureStatus.ERROR
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

                logging.getLogger("mcs.exposure").exception(
                    "post-commit exposure action failed"
                )

        return CommandResult(
            success=True, data=_panel_payload(panel, access_mode=access_mode)
        )

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
        client = CloudflareClient(token)
        try:
            provisioned = await client.create_named_tunnel(name=f"mcs-panel-{hostname}")
            await client.configure_ingress(
                provisioned.tunnel_id,
                [
                    {"hostname": hostname, "service": ingress},
                    {"service": "http_status:404"},
                ],
            )
            await client.create_cname(hostname, provisioned.tunnel_id)
        except CloudflareAuthError as exc:
            panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
            panel.set_public_address(None)
            panel.set_error("RECLAIM_REQUIRED", str(exc))
            panel.clear_cloudflare_credentials()
            return
        except CloudflareApiError as exc:
            panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.ERROR)
            panel.set_public_address(None)
            panel.set_error("CLOUDFLARE_API_ERROR", str(exc))
            panel.clear_cloudflare_credentials()
            return

        ciphertext = _panel_encryption().encrypt(provisioned.token.encode("utf-8"))
        panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
        panel.set_cloudflare_credentials(provisioned.tunnel_id, ciphertext)
        panel.set_public_address(hostname)
        panel.set_status(ExposureStatus.STARTING)
        panel.set_error(None)

        # Start the supervised cloudflared child AFTER commit so the persisted
        # credentials are durable before the process depends on them.
        token_bytes = provisioned.token.encode("utf-8")
        post_commit.append(lambda t=token_bytes: self._start_supervisor(t))

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
            try:
                secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
            except Exception:
                panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
                panel.set_status(ExposureStatus.RECLAIM_REQUIRED)
                panel.set_public_address(None)
                panel.set_error(
                    "RECLAIM_REQUIRED",
                    "Stored playit agent secret cannot be decrypted",
                )
                return

            tunnel_id = panel.playit_tunnel_id or f"playit-panel-{panel.id[:8]}"
            address = f"https://mcs-panel-{panel.id[:8]}.at.ply.gg"
            panel.update(PanelExposureMethod.PLAYIT_HTTP, DesiredState.ENABLED)
            panel.set_playit_tunnel(tunnel_id)
            panel.set_public_address(address)
            panel.set_status(ExposureStatus.ACTIVE)
            panel.set_error(None)
            post_commit.append(lambda s=secret_bytes: self._start_playit_supervisor(s))
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
        if (
            normalized_host in ("127.0.0.1", "localhost", "::1")
            or normalized_host.startswith("127.")
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
            panel.set_port_forward_details(
                requested_port, "BIND_MISMATCH", datetime.now(UTC)
            )
            return

        valid, err_code, err_msg = AsyncUPnPService.validate_external_port(requested_port)
        if not valid:
            panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
            panel.set_status(ExposureStatus.ERROR)
            panel.set_public_address(None)
            panel.set_error(err_code, err_msg)
            panel.set_port_forward_details(requested_port, err_code, datetime.now(UTC))
            return

        upnp = AsyncUPnPService()
        result = await upnp.attempt_mapping(
            internal_port=internal_port,
            requested_external_port=requested_port,
            description="MCS-Manager-Panel",
        )

        panel.update(PanelExposureMethod.PORT_FORWARD, DesiredState.ENABLED)
        if result.success:
            panel.set_public_address(f"http://{result.external_ip}:{result.external_port}")
            panel.set_port_forward_details(
                result.external_port, "SUCCEEDED", datetime.now(UTC)
            )
            panel.set_status(ExposureStatus.ACTIVE)
            panel.set_error(None)
        else:
            panel.set_public_address(None)
            panel.set_port_forward_details(
                requested_port, result.error_code, datetime.now(UTC)
            )
            panel.set_status(ExposureStatus.ERROR)
            panel.set_error(result.error_code, result.error_message)

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
        await supervisor.start(secret, on_status=_persist_playit_status)

    async def _stop_playit_supervisor(self) -> None:
        supervisor = get_playit_supervisor()
        await supervisor.stop()


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


async def _persist_playit_status(status: ExposureStatus) -> None:
    try:
        async with UnitOfWork() as uow:
            agent_repo: HostAgentRepository = SQLHostAgentRepository(uow.session)
            agent = await agent_repo.get()
            agent.set_process_status(status.value)
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


class ReconcileExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
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
                try:
                    secret_bytes = _panel_encryption().decrypt(agent.secret_ciphertext)
                    post_commit.append(
                        lambda s=secret_bytes: supervisor.start(
                            s, on_status=_persist_playit_status
                        )
                    )
                except Exception:
                    logger.exception("Failed to decrypt secret on reconcile")
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

    async def _reconcile_panel(
        self, uow: UnitOfWork, post_commit: list[callable]
    ) -> None:
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
            plaintext = _panel_encryption().decrypt(panel.cloudflare_token_ciphertext)
            post_commit.append(
                lambda p=plaintext: supervisor.start(p, on_status=_persist_panel_status)
            )
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
        "tls": not is_port_forward,
        "protocol": "http" if is_port_forward else "https",
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
        setup_instructions = (
            "Add a Minecraft Java (TCP) tunnel on playit.gg pointing to local address "
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
        "targets": [_target_payload(t) for t in exposure.targets],
    }


def _fresh_claim_code() -> str:
    return secrets.token_urlsafe(32)
