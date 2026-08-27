from __future__ import annotations

import logging

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.persistence.db import database
from app.modules.event_store.dead_letter import DeadLetterService

logger = logging.getLogger(__name__)


class ListDeadLetterCommand(Command):
    limit: int = 100


class ReplayDeadLetterCommand(Command):
    event_id: str


class ReplayAllDeadLettersCommand(Command):
    pass


class ResolveDeadLetterCommand(Command):
    event_id: str


class DeleteDeadLetterCommand(Command):
    event_id: str


class ListDeadLetterHandler(CommandHandler[ListDeadLetterCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: ListDeadLetterCommand) -> CommandResult:
        async with database.session_factory() as session:
            service = DeadLetterService(session, self._event_bus)
            entries = await service.list_all(limit=command.limit)
            data = [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "error": e.error,
                    "replay_count": e.replay_count,
                    "resolved": bool(e.resolved),
                    "created_at": e.created_at.isoformat() if e.created_at else "",
                }
                for e in entries
            ]
            return CommandResult(success=True, data=data)


class ReplayDeadLetterHandler(CommandHandler[ReplayDeadLetterCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: ReplayDeadLetterCommand) -> CommandResult:
        async with database.session_factory() as session:
            service = DeadLetterService(session, self._event_bus)
            ok = await service.replay(command.event_id)
            return CommandResult(
                success=ok,
                data={"replayed": ok},
                error=None
                if ok
                else f"Dead letter {command.event_id} not found or already resolved",
            )


class ReplayAllDeadLettersHandler(CommandHandler[ReplayAllDeadLettersCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: ReplayAllDeadLettersCommand) -> CommandResult:
        async with database.session_factory() as session:
            service = DeadLetterService(session, self._event_bus)
            result = await service.replay_all()
            return CommandResult(success=True, data=result)


class ResolveDeadLetterHandler(CommandHandler[ResolveDeadLetterCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: ResolveDeadLetterCommand) -> CommandResult:
        async with database.session_factory() as session:
            service = DeadLetterService(session, self._event_bus)
            ok = await service.resolve(command.event_id)
            return CommandResult(
                success=ok,
                data={"resolved": ok},
                error=None if ok else f"Dead letter {command.event_id} not found",
            )


class DeleteDeadLetterHandler(CommandHandler[DeleteDeadLetterCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: DeleteDeadLetterCommand) -> CommandResult:
        async with database.session_factory() as session:
            service = DeadLetterService(session, self._event_bus)
            ok = await service.delete(command.event_id)
            return CommandResult(
                success=ok,
                data={"deleted": ok},
                error=None if ok else f"Dead letter {command.event_id} not found",
            )
