from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError
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
from app.modules.exposure.infrastructure.repository import (
    SQLHostAgentRepository,
    SQLPanelExposureRepository,
    SQLServerExposureRepository,
)
from app.modules.server.infrastructure.repository import SQLServerRepository
from app.modules.shared.value_objects import ServerId

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
    actor_id: str = ""


class SetPanelExposureHandler(CommandHandler[SetPanelExposureCommand]):
    """Set panel exposure method + desired_state (route #8, idempotent)."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: SetPanelExposureCommand) -> CommandResult:
        method = PanelExposureMethod(command.method.lower())
        desired = DesiredState(command.desired_state.upper())

        async with UnitOfWork(self._event_bus) as uow:
            repo: PanelExposureRepository = SQLPanelExposureRepository(uow.session)
            panel = await repo.get()
            if panel.method == method and panel.desired_state == desired:
                return CommandResult(success=True, data=_panel_payload(panel))
            panel.update(method, desired)
            await repo.save(panel)
            for event in panel.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data=_panel_payload(panel))


class ReconcileExposureCommand(Command):
    idempotency_key: IdempotencyKey = IdempotencyKey()
    scope: str = "server"
    actor_id: str = ""


class ReconcileExposureHandler(CommandHandler[ReconcileExposureCommand]):
    """Manual reconciliation trigger (route #4). Recomputes derived state."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, _command: ReconcileExposureCommand) -> CommandResult:
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
            await uow.commit()

        return CommandResult(success=True, data={"reconciled": True})


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
