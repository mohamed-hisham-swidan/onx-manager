from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.config import ConfigFactory, panel_ingress_target
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError, ValidationError
from app.core.idempotency import IdempotencyKey
from app.core.persistence.unit_of_work import UnitOfWork
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
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
    SQLServerExposureRepository,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.storage.encryption import build_backup_encryption

CLAIM_TTL_MINUTES = 10


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

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
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
            else:
                exposure.set_desired_state(DesiredState.DISABLED)

            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

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

        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
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

            if exposure.desired_state == DesiredState.ENABLED:
                _fold_aggregate(exposure)
                return CommandResult(success=True, data=_exposure_payload(exposure))

            exposure.enable(
                server_port=server.properties.port.value,
                target_id=str(uuid.uuid4().hex),
            )
            _fold_aggregate(exposure)
            await repo.save(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

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
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
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
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

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
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposure = await repo.get(command.server_id)
            if exposure is None:
                return CommandResult(success=True, data={"removed": False})
            exposure.mark_deleted()
            await repo.delete(exposure)
            for event in exposure.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={"removed": True})


class CreateExposureTargetCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    server_id: str
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
        async with UnitOfWork(self._event_bus) as uow:
            repo: ServerExposureRepository = SQLServerExposureRepository(uow.session)
            exposures = await repo.list()
            for exposure in exposures:
                if exposure.desired_state == DesiredState.ENABLED:
                    exposure.disable()
                    _fold_aggregate(exposure)
                    await repo.save(exposure)
                    for event in exposure.collect_events():
                        uow.add_event(event)
                    count += 1
            await uow.commit()

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
    actor_id: str = ""


def _panel_encryption():
    settings = ConfigFactory.global_settings()
    return build_backup_encryption(settings.backup_encryption_key_path or None)


class SetPanelExposureHandler(CommandHandler[SetPanelExposureCommand]):
    """Set panel exposure method + desired_state (route #8, idempotent).

    For ``cloudflare_tunnel``:
      - ENABLED provisions a Named Tunnel, sets the ingress (loopback Panel
        bind only + catch-all 404), creates ONLY the tunnel CNAME, persists
        the AES-GCM ciphertext + tunnel id, and starts the supervised
        ``cloudflared --token-file`` child.
      - DISABLED stops the child and clears the stored secret + public address.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: SetPanelExposureCommand) -> CommandResult:
        method = PanelExposureMethod(command.method.lower())
        desired = DesiredState(command.desired_state.upper())

        post_commit: list[callable] = []

        async with UnitOfWork(self._event_bus) as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await repo.get()

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
                if not is_reclaim_rotation:
                    return CommandResult(success=True, data=_panel_payload(panel))

            if method == PanelExposureMethod.CLOUDFLARE_TUNNEL:
                if desired == DesiredState.ENABLED:
                    await self._enable_cloudflare(uow, repo, panel, command, post_commit)
                else:
                    await self._disable_cloudflare(uow, repo, panel, post_commit)
            else:
                # non-Cloudflare panel methods (playit_http/port_forward) are
                # Batch 7.2b — keep the state transition for now.
                panel.update(method, desired)
                panel.set_status(ExposureStatus.DISABLED)
                panel.set_public_address(None)
                panel.clear_cloudflare_credentials()

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

        return CommandResult(success=True, data=_panel_payload(panel))

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
        panel.set_cloudflare_credentials(provisioned.tunnel_id, ciphertext)
        panel.set_public_address(hostname)
        panel.update(PanelExposureMethod.CLOUDFLARE_TUNNEL, DesiredState.ENABLED)
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

    async def _start_supervisor(self, token: bytes) -> None:
        supervisor = get_cloudflared_supervisor()
        await supervisor.start(token, on_status=_persist_panel_status)

    async def _restart_supervisor(self, token: bytes) -> None:
        """Stop any surviving child, then (re)start cloudflared with the token.

        Used by the RECLAIM rotation path so a stale process still holding the
        old (revoked) token cannot keep serving while the new token is applied.
        """
        supervisor = get_cloudflared_supervisor()
        if supervisor.is_running:
            await supervisor.stop()
        await supervisor.start(token, on_status=_persist_panel_status)

    async def _stop_supervisor(self) -> None:
        supervisor = get_cloudflared_supervisor()
        await supervisor.stop()


async def _persist_panel_status(status: ExposureStatus) -> None:
    """Persist a supervisor-driven panel status change (health/RECLAIM).

    Runs in the supervisor's event loop (not inside a command UoW), so it
    opens its own short-lived UnitOfWork.
    """
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
        import logging

        logging.getLogger("mcs.exposure").exception(
            "failed to persist panel status %s", status.value
        )


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

            desired_running = len(await repo.list_playit_enabled()) > 0
            if desired_running != agent.desired_agent_running:
                agent.set_desired_agent_running(desired_running)
                await agent_repo.save(agent)

            await self._reconcile_panel(uow, post_commit)
            await uow.commit()

        for action in post_commit:
            try:
                await action()
            except Exception:

                import logging

                logging.getLogger("mcs.exposure").exception(
                    "post-commit reconcile action failed"
                )

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


def _panel_payload(panel: PanelExposure) -> dict:
    return {
        "method": panel.method.value,
        "desired_state": panel.desired_state.value,
        "status": panel.status.value,
        "public_address": panel.public_address,
        "cloudflare_tunnel_id": panel.cloudflare_tunnel_id,
        "error_code": panel.error_code,
        "error_message": panel.error_message,
    }


def _target_payload(target: ServerExposureTarget) -> dict:
    return {
        "id": target.id,
        "exposure_id": target.exposure_id,
        "protocol": target.protocol.value,
        "service_type": target.service_type.value,
        "local_port": target.local_port,
        "public_address": target.public_address,
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
