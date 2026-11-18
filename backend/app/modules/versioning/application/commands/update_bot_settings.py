from __future__ import annotations

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.server.domain.repository import ServerRepository
from app.modules.versioning.application.refresh_orchestrator import parse_retention_policy
from app.modules.versioning.infrastructure.models import ServerRepoLeaseModel


class UpdateBotSettingsCommand(Command):
    server_id: str
    bot_count: int | None = None
    duration_minutes: int | None = None
    bot_tech: str | None = None
    placement_mode: str | None = None
    previous_tree_retention: str | int | None = None


class UpdateBotSettingsHandler(CommandHandler[UpdateBotSettingsCommand]):
    def __init__(self, server_repo: ServerRepository | None = None) -> None:
        self._server_repo = server_repo

    async def handle(self, command: UpdateBotSettingsCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository

        if self._server_repo is not None:
            return await self._execute(command, self._server_repo)

        async with database.session_factory() as session:
            server_repo = self._server_repo or SQLServerRepository(session)
            res = await self._execute(command, server_repo, session=session)
            await session.commit()
            return res

    async def _execute(self, command, server_repo, session=None):

        from app.core.persistence.db import database
        from app.modules.server.infrastructure.models import ServerModel

        if session is None:
            async with database.session_factory() as s:
                return await self._execute(command, server_repo, session=s)

        server = await session.get(ServerModel, command.server_id)
        if server is None:
            raise NotFoundError(f"Server '{command.server_id}' not found")

        stored = server.bot_verification_settings or {}
        new_settings = dict(stored)
        if command.bot_count is not None:
            new_settings["bot_count"] = command.bot_count
        if command.duration_minutes is not None:
            new_settings["duration_minutes"] = command.duration_minutes
        if command.bot_tech is not None:
            new_settings["bot_tech"] = command.bot_tech
        if command.placement_mode is not None:
            new_settings["placement_mode"] = command.placement_mode

        retention = stored.get("previous_tree_retention", "until_health_gate")
        if command.previous_tree_retention is not None:
            try:
                normalized, _ = parse_retention_policy(command.previous_tree_retention)
            except Exception as exc:
                raise ValidationError(str(exc)) from exc
            new_settings["previous_tree_retention"] = normalized
            retention = normalized

            lease = await session.get(ServerRepoLeaseModel, command.server_id)
            if lease is None:
                lease = ServerRepoLeaseModel(
                    server_id=command.server_id, previous_tree_retention=normalized
                )
                session.add(lease)
            else:
                lease.previous_tree_retention = normalized

        server.bot_verification_settings = new_settings
        if retention:
            # ensure lease row exists
            lease = await session.get(ServerRepoLeaseModel, command.server_id)
            if lease is None:
                lease = ServerRepoLeaseModel(
                    server_id=command.server_id, previous_tree_retention=retention
                )
                session.add(lease)
            else:
                if command.previous_tree_retention is None:
                    lease.previous_tree_retention = lease.previous_tree_retention or retention

        return CommandResult(
            success=True,
            entity_id=command.server_id,
            details={
                "server_id": command.server_id,
                "bot_count": new_settings.get("bot_count"),
                "duration_minutes": new_settings.get("duration_minutes"),
                "bot_tech": new_settings.get("bot_tech"),
                "placement_mode": new_settings.get("placement_mode"),
                "previous_tree_retention": retention,
                "settings": new_settings,
            },
        )
