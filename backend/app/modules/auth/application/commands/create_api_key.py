import contextlib
import uuid

from pydantic import Field

from app.core.command_bus import Command, CommandHandler, CommandResult
from app.core.event_bus import EventBus
from app.core.exceptions import PermissionDenied
from app.core.persistence.unit_of_work import UnitOfWork
from app.core.security import generate_api_key, hash_api_key
from app.modules.auth.domain.aggregate import ApiKey
from app.modules.auth.infrastructure.repository import SQLUserRepository
from app.modules.shared.value_objects import ApiKeyId, Permission, UserId


class CreateApiKeyCommand(Command):
    user_id: str
    name: str
    permissions: list[str] = Field(default_factory=list)
    caller_permissions: list[str] | None = None
    caller_roles: list[str] | None = None


class CreateApiKeyHandler(CommandHandler[CreateApiKeyCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def handle(self, command: CreateApiKeyCommand) -> CommandResult:
        raw_key = generate_api_key()
        prefix = raw_key[:7]
        key_hash = hash_api_key(raw_key)

        perms = []
        for p in command.permissions:
            with contextlib.suppress(ValueError):
                perms.append(Permission.parse(p))

        if command.caller_permissions is not None or command.caller_roles is not None:
            caller_perms = set(command.caller_permissions or [])
            caller_roles = {str(r).lower() for r in (command.caller_roles or [])}
            is_owner = "owner" in caller_roles
            is_admin = "admin" in caller_roles or "admin:full" in caller_perms

            for p_raw in command.permissions:
                if (
                    p_raw in ("global:*", "global.*")
                    or p_raw.startswith(("global.", "panel."))
                ) and not is_owner:
                    raise PermissionDenied(
                        f"Only the instance Owner can mint API keys with '{p_raw}'"
                    )
                if not is_owner and not is_admin and p_raw not in caller_perms:
                    raise PermissionDenied(
                        f"Cannot grant API key permission '{p_raw}' not held by caller"
                    )

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

        return CommandResult(
            success=True,
            data={
                "api_key_id": str(api_key.api_key_id),
                "name": api_key.name,
                "prefix": prefix,
                "key": raw_key,
                "permissions": [str(p) for p in api_key.permissions],
                "expires_at": None,
                "is_revoked": False,
                "created_at": api_key.created_at,
            },
        )
