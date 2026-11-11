from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import NotFoundError
from app.modules.server.domain.repository import ServerRepository
from app.modules.shared.value_objects import ServerId
from app.modules.versioning.domain.entities import TestDefinition
from app.modules.versioning.domain.repository import VersioningRepository
from app.modules.versioning.domain.value_objects import BotTech, PlacementMode


class CreateTestDefinitionCommand(Command):
    server_id: str
    name: str
    description: str = ""
    server_type: str = "vanilla"
    bot_technology: str = "mineflayer"
    bot_count: int = 5
    duration_seconds: int = 60
    join_stagger_seconds: float = 1.0
    connect_grace_seconds: int = 20
    placement_mode: str = "sidecar"
    assertion_rules: dict[str, Any] = {}
    timeout_seconds: int = 300


class CreateTestDefinitionHandler(CommandHandler[CreateTestDefinitionCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: CreateTestDefinitionCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(command, self._server_repo, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    await ensure_versioning_allowed(command.server_id, session=session)
                    server_repo = self._server_repo or SQLServerRepository(session)
                    versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                    res = await self._execute(command, server_repo, versioning_repo)
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise

    async def _execute(
        self,
        command: CreateTestDefinitionCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        try:
            await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        bot_tech = (
            BotTech(command.bot_technology)
            if command.bot_technology in BotTech._value2member_map_
            else BotTech.MINEFLAYER
        )
        placement_mode = (
            PlacementMode(command.placement_mode)
            if command.placement_mode in PlacementMode._value2member_map_
            else PlacementMode.SIDECAR
        )

        def_id = f"td-{uuid.uuid4().hex[:12]}"
        definition = TestDefinition(
            id=def_id,
            server_id=command.server_id,
            name=command.name,
            description=command.description,
            server_type=command.server_type,
            bot_technology=bot_tech,
            bot_count=command.bot_count,
            duration_seconds=command.duration_seconds,
            join_stagger_seconds=command.join_stagger_seconds,
            connect_grace_seconds=command.connect_grace_seconds,
            placement_mode=placement_mode,
            assertion_rules=command.assertion_rules or {},
            timeout_seconds=command.timeout_seconds,
        )
        saved = await versioning_repo.save_test_definition(definition)
        return CommandResult(
            success=True,
            entity_id=saved.id,
            details={
                "id": saved.id,
                "server_id": saved.server_id,
                "name": saved.name,
                "description": saved.description,
                "server_type": saved.server_type,
                "bot_technology": (
                    saved.bot_technology.value
                    if isinstance(saved.bot_technology, BotTech)
                    else saved.bot_technology
                ),
                "bot_count": saved.bot_count,
                "duration_seconds": saved.duration_seconds,
                "join_stagger_seconds": saved.join_stagger_seconds,
                "connect_grace_seconds": saved.connect_grace_seconds,
                "placement_mode": (
                    saved.placement_mode.value
                    if isinstance(saved.placement_mode, PlacementMode)
                    else saved.placement_mode
                ),
                "assertion_rules": saved.assertion_rules,
                "timeout_seconds": saved.timeout_seconds,
                "created_at": saved.created_at.isoformat(),
                "updated_at": saved.updated_at.isoformat(),
            },
        )


class UpdateTestDefinitionCommand(Command):
    server_id: str
    definition_id: str
    name: str | None = None
    description: str | None = None
    server_type: str | None = None
    bot_technology: str | None = None
    bot_count: int | None = None
    duration_seconds: int | None = None
    join_stagger_seconds: float | None = None
    connect_grace_seconds: int | None = None
    placement_mode: str | None = None
    assertion_rules: dict[str, Any] | None = None
    timeout_seconds: int | None = None


class UpdateTestDefinitionHandler(CommandHandler[UpdateTestDefinitionCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: UpdateTestDefinitionCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(command, self._server_repo, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    await ensure_versioning_allowed(command.server_id, session=session)
                    server_repo = self._server_repo or SQLServerRepository(session)
                    versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                    res = await self._execute(command, server_repo, versioning_repo)
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise

    async def _execute(
        self,
        command: UpdateTestDefinitionCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        try:
            await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        existing = await versioning_repo.get_test_definition(command.definition_id)
        if existing is None or existing.server_id != command.server_id:
            raise NotFoundError(
                f"TestDefinition '{command.definition_id}' not found "
                f"for server '{command.server_id}'"
            )

        bot_tech = None
        if command.bot_technology is not None:
            bot_tech = (
                BotTech(command.bot_technology)
                if command.bot_technology in BotTech._value2member_map_
                else BotTech.MINEFLAYER
            )

        placement_mode = None
        if command.placement_mode is not None:
            placement_mode = (
                PlacementMode(command.placement_mode)
                if command.placement_mode in PlacementMode._value2member_map_
                else PlacementMode.SIDECAR
            )

        existing.update(
            name=command.name,
            description=command.description,
            server_type=command.server_type,
            bot_technology=bot_tech,
            bot_count=command.bot_count,
            duration_seconds=command.duration_seconds,
            join_stagger_seconds=command.join_stagger_seconds,
            connect_grace_seconds=command.connect_grace_seconds,
            placement_mode=placement_mode,
            assertion_rules=command.assertion_rules,
            timeout_seconds=command.timeout_seconds,
        )
        saved = await versioning_repo.save_test_definition(existing)
        return CommandResult(
            success=True,
            entity_id=saved.id,
            details={
                "id": saved.id,
                "server_id": saved.server_id,
                "name": saved.name,
                "description": saved.description,
                "server_type": saved.server_type,
                "bot_technology": (
                    saved.bot_technology.value
                    if isinstance(saved.bot_technology, BotTech)
                    else saved.bot_technology
                ),
                "bot_count": saved.bot_count,
                "duration_seconds": saved.duration_seconds,
                "join_stagger_seconds": saved.join_stagger_seconds,
                "connect_grace_seconds": saved.connect_grace_seconds,
                "placement_mode": (
                    saved.placement_mode.value
                    if isinstance(saved.placement_mode, PlacementMode)
                    else saved.placement_mode
                ),
                "assertion_rules": saved.assertion_rules,
                "timeout_seconds": saved.timeout_seconds,
                "created_at": saved.created_at.isoformat(),
                "updated_at": saved.updated_at.isoformat(),
            },
        )


class DeleteTestDefinitionCommand(Command):
    server_id: str
    definition_id: str


class DeleteTestDefinitionHandler(CommandHandler[DeleteTestDefinitionCommand]):
    def __init__(
        self,
        server_repo: ServerRepository | None = None,
        versioning_repo: VersioningRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._server_repo = server_repo
        self._versioning_repo = versioning_repo
        self._event_bus = event_bus

    async def handle(self, command: DeleteTestDefinitionCommand) -> CommandResult:
        from app.core.persistence.db import database
        from app.modules.server.infrastructure.repository import SQLServerRepository
        from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
        from app.modules.versioning.infrastructure.repository import SQLVersioningRepository

        if self._server_repo is not None:
            await ensure_versioning_allowed(command.server_id, server_repo=self._server_repo)

        if self._server_repo is not None and self._versioning_repo is not None:
            return await self._execute(command, self._server_repo, self._versioning_repo)

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with database.session_factory() as session:
                    await ensure_versioning_allowed(command.server_id, session=session)
                    server_repo = self._server_repo or SQLServerRepository(session)
                    versioning_repo = self._versioning_repo or SQLVersioningRepository(session)
                    res = await self._execute(command, server_repo, versioning_repo)
                    await session.commit()
                return res
            except Exception as exc:
                is_lock = "locked" in str(exc).lower() or "busy" in str(exc).lower()
                if is_lock and attempt < max_retries - 1:
                    await asyncio.sleep(0.05 * (2**attempt))
                    continue
                raise

    async def _execute(
        self,
        command: DeleteTestDefinitionCommand,
        server_repo: ServerRepository,
        versioning_repo: VersioningRepository,
    ) -> CommandResult:
        try:
            await server_repo.get(ServerId(command.server_id))
        except Exception as exc:
            raise NotFoundError(f"Server '{command.server_id}' not found") from exc

        existing = await versioning_repo.get_test_definition(command.definition_id)
        if existing is None or existing.server_id != command.server_id:
            raise NotFoundError(
                f"TestDefinition '{command.definition_id}' not found "
                f"for server '{command.server_id}'"
            )

        deleted = await versioning_repo.delete_test_definition(command.definition_id)
        return CommandResult(
            success=deleted,
            entity_id=command.definition_id,
            details={"deleted": deleted, "definition_id": command.definition_id},
        )
