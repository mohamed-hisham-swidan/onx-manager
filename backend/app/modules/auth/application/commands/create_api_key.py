from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.security import generate_api_key, hash_api_key
from app.modules.auth.domain.aggregate import ApiKey
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import ApiKeyId, Permission, UserId
from app.storage.unit_of_work import UnitOfWork


class CreateApiKeyCommand(Command):
    user_id: str
    name: str
    permissions: list[str] = []


class CreateApiKeyHandler(CommandHandler[CreateApiKeyCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateApiKeyCommand) -> CommandResult:
        raw_key = generate_api_key()
        prefix = raw_key[:7]
        key_hash = hash_api_key(raw_key)

        perms = []
        for p in command.permissions:
            try:
                perms.append(Permission.parse(p))
            except ValueError:
                pass

        api_key = ApiKey(
            api_key_id=ApiKeyId(uuid.uuid4().hex),
            name=command.name,
            prefix=prefix,
            key_hash=key_hash,
            permissions=perms,
        )
        async with UnitOfWork(self._event_bus) as uow:
            repo = SQLUserRepository(uow.session)
            user = await repo.get(UserId(command.user_id))
            user.add_api_key(api_key)
            await repo.save(user)
            for event in user.collect_events():
                uow.add_event(event)
            await uow.commit()

        return CommandResult(success=True, data={
            "api_key_id": str(api_key.api_key_id),
            "name": api_key.name,
            "prefix": prefix,
            "key": raw_key,
            "permissions": [str(p) for p in api_key.permissions],
            "expires_at": None,
            "is_revoked": False,
            "created_at": api_key.created_at,
        })
