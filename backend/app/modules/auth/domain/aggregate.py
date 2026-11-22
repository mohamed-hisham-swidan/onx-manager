from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from app.core.exceptions import InvalidValueError
from app.modules.auth.domain.events import (
    ApiKeyCreatedEvent,
    ApiKeyRevokedEvent,
    UserActivatedEvent,
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserLoggedInEvent,
    UserLoggedOutEvent,
)
from app.modules.shared.aggregate import AggregateRoot
from app.modules.shared.value_objects import ApiKeyId, EmailAddress, Permission, RoleId, UserId


class Role(AggregateRoot):
    def __init__(
        self,
        role_id: RoleId,
        name: str,
        permissions: list[Permission] | None = None,
        description: str = "",
    ) -> None:
        super().__init__()
        self._role_id = role_id
        self._name = name
        self._permissions = permissions or []
        self._description = description

    @property
    def role_id(self) -> RoleId:
        return self._role_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def permissions(self) -> list[Permission]:
        return list(self._permissions)

    @property
    def description(self) -> str:
        return self._description

    def has_permission(self, resource: str, action: str) -> bool:
        return any(p.resource == resource and p.action in (action, "*") for p in self._permissions)

    def add_permission(self, permission: Permission) -> None:
        if permission not in self._permissions:
            self._permissions.append(permission)

    def remove_permission(self, permission: Permission) -> None:
        self._permissions = [p for p in self._permissions if p != permission]


class ApiKey(AggregateRoot):
    def __init__(
        self,
        api_key_id: ApiKeyId,
        name: str,
        prefix: str,
        key_hash: str = "",
        permissions: list[Permission] | None = None,
        expires_at: datetime | None = None,
        is_revoked: bool = False,
        created_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._api_key_id = api_key_id
        self._name = name
        self._prefix = prefix
        self._key_hash = key_hash
        self._permissions = permissions or []
        self._expires_at = expires_at
        self._is_revoked = is_revoked
        self._created_at = created_at or datetime.now(UTC)

    @property
    def api_key_id(self) -> ApiKeyId:
        return self._api_key_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def prefix(self) -> str:
        return self._prefix

    @property
    def key_hash(self) -> str:
        return self._key_hash

    @property
    def permissions(self) -> list[Permission]:
        return list(self._permissions)

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def is_revoked(self) -> bool:
        return self._is_revoked

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def is_expired(self) -> bool:
        if self._expires_at is None:
            return False
        return datetime.now(UTC) > self._expires_at

    def revoke(self, user_id: str = "") -> None:
        self._is_revoked = True
        self._add_event(ApiKeyRevokedEvent(user_id=user_id, key_name=self._name))

    def has_permission(self, resource: str, action: str) -> bool:
        return any(p.resource == resource and p.action in (action, "*") for p in self._permissions)


class User(AggregateRoot):
    def __init__(
        self,
        user_id: UserId,
        email: EmailAddress | None = None,
        password_hash: str = "",
        display_name: str = "",
        roles: list[Role] | None = None,
        api_keys: list[ApiKey] | None = None,
        is_active: bool = True,
        created_at: datetime | None = None,
        last_login_at: datetime | None = None,
        username: str | None = None,
    ) -> None:
        super().__init__()
        resolved_username = (
            username if username is not None else (str(email) if email is not None else "")
        ).strip()
        if not resolved_username:
            raise ValueError("username or email is required")
        resolved_display_name = (
            display_name.strip()
            if display_name and display_name.strip()
            else resolved_username
        )
        self._user_id = user_id
        self._username = resolved_username
        self._email = email
        self._password_hash = password_hash
        self._display_name = resolved_display_name
        self._roles = roles or []
        self._api_keys = api_keys or []
        self._is_active = is_active
        self._created_at = created_at or datetime.now(UTC)
        self._last_login_at = last_login_at

    @property
    def user_id(self) -> UserId:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @property
    def email(self) -> EmailAddress | None:
        return self._email

    @property
    def password_hash(self) -> str:
        return self._password_hash

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def roles(self) -> list[Role]:
        return list(self._roles)

    @property
    def api_keys(self) -> list[ApiKey]:
        return list(self._api_keys)

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def last_login_at(self) -> datetime | None:
        return self._last_login_at

    @classmethod
    def create(
        cls,
        user_id: UserId,
        email: EmailAddress | None = None,
        password_hash: str = "",
        display_name: str = "",
        *,
        username: str | None = None,
    ) -> User:
        user = cls(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            username=username,
        )
        user._add_event(
            UserCreatedEvent(
                user_id=str(user_id),
                username=user.username,
                email=str(email) if email is not None else None,
            )
        )
        return user

    def add_role(self, role: Role) -> None:
        if role not in self._roles:
            self._roles.append(role)

    def remove_role(self, role: Role) -> None:
        self._roles = [r for r in self._roles if r.role_id != role.role_id]

    def has_permission(self, resource: str, action: str) -> bool:
        return any(role.has_permission(resource, action) for role in self._roles)

    def set_username(self, username: str) -> None:
        cleaned = username.strip()
        if not cleaned:
            raise ValueError("username cannot be empty")
        self._username = cleaned

    def set_email(self, email: EmailAddress | None) -> None:
        self._email = email

    def set_password_hash(self, password_hash: str) -> None:
        self._password_hash = password_hash

    def set_display_name(self, display_name: str) -> None:
        self._display_name = display_name

    def record_login(self, ip_address: str) -> None:
        self._last_login_at = datetime.now(UTC)
        self._add_event(UserLoggedInEvent(user_id=str(self._user_id), ip_address=ip_address))

    def record_logout(self) -> None:
        self._add_event(UserLoggedOutEvent(user_id=str(self._user_id)))

    def activate(self) -> None:
        self._is_active = True
        self._add_event(UserActivatedEvent(user_id=str(self._user_id)))

    def deactivate(self) -> None:
        self._is_active = False
        self._add_event(UserDeactivatedEvent(user_id=str(self._user_id)))

    def add_api_key(self, api_key: ApiKey) -> None:
        self._api_keys.append(api_key)
        self._add_event(ApiKeyCreatedEvent(user_id=str(self._user_id), key_name=api_key.name))

    def revoke_api_key(self, api_key_id: ApiKeyId) -> None:
        for key in self._api_keys:
            if key.api_key_id == api_key_id and not key.is_revoked:
                key.revoke()
                self._add_event(ApiKeyRevokedEvent(user_id=str(self._user_id), key_name=key.name))
                break


class AccessMode(str, Enum):
    LOCAL = "LOCAL"
    GLOBAL = "GLOBAL"


class InviteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    USED = "USED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SystemState(AggregateRoot):
    def __init__(
        self,
        id: str = "default",
        initialized: bool = False,
        access_mode: AccessMode | str = AccessMode.LOCAL,
        password_configured: bool | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._id = id
        self._initialized = initialized
        self._access_mode = (
            access_mode if isinstance(access_mode, AccessMode) else AccessMode(access_mode)
        )
        self._password_configured = (
            bool(initialized) if password_configured is None else bool(password_configured)
        )
        self._created_at = created_at or datetime.now(UTC)
        self._updated_at = updated_at or datetime.now(UTC)

    @property
    def id(self) -> str:
        return self._id

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def access_mode(self) -> AccessMode:
        return self._access_mode

    @property
    def password_configured(self) -> bool:
        return self._password_configured

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def mark_initialized(
        self,
        access_mode: AccessMode | str | None = None,
        *,
        password_configured: bool = True,
    ) -> None:
        self._initialized = True
        self._password_configured = bool(password_configured)
        if access_mode:
            self._access_mode = (
                access_mode if isinstance(access_mode, AccessMode) else AccessMode(access_mode)
            )
        self._updated_at = datetime.now(UTC)

    def mark_password_configured(self) -> None:
        self._initialized = True
        self._password_configured = True
        self._updated_at = datetime.now(UTC)

    def set_access_mode(self, access_mode: AccessMode | str) -> None:
        self._access_mode = (
            access_mode if isinstance(access_mode, AccessMode) else AccessMode(access_mode)
        )
        self._updated_at = datetime.now(UTC)


class Invitation(AggregateRoot):
    def __init__(
        self,
        invitation_id: str,
        token_hash: str,
        token_prefix: str,
        creator_id: str | None = None,
        email: str | None = None,
        global_role: str = "member",
        server_id: str | None = None,
        server_role: str | None = None,
        status: InviteStatus | str = InviteStatus.ACTIVE,
        max_uses: int = 1,
        use_count: int = 0,
        expires_at: datetime | None = None,
        used_at: datetime | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._invitation_id = invitation_id
        self._token_hash = token_hash
        self._token_prefix = token_prefix
        self._creator_id = creator_id
        self._email = email
        self._global_role = global_role
        self._server_id = server_id
        self._server_role = server_role
        self._status = status if isinstance(status, InviteStatus) else InviteStatus(status)
        self._max_uses = max_uses
        self._use_count = use_count
        self._expires_at = expires_at
        self._used_at = used_at
        self._created_at = created_at or datetime.now(UTC)
        self._updated_at = updated_at or datetime.now(UTC)

    @property
    def invitation_id(self) -> str:
        return self._invitation_id

    @property
    def token_hash(self) -> str:
        return self._token_hash

    @property
    def token_prefix(self) -> str:
        return self._token_prefix

    @property
    def creator_id(self) -> str | None:
        return self._creator_id

    @property
    def email(self) -> str | None:
        return self._email

    @property
    def global_role(self) -> str:
        return self._global_role

    @property
    def server_id(self) -> str | None:
        return self._server_id

    @property
    def server_role(self) -> str | None:
        return self._server_role

    @property
    def status(self) -> InviteStatus:
        return self._status

    @property
    def max_uses(self) -> int:
        return self._max_uses

    @property
    def use_count(self) -> int:
        return self._use_count

    @property
    def expires_at(self) -> datetime | None:
        return self._expires_at

    @property
    def used_at(self) -> datetime | None:
        return self._used_at

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def is_expired(self) -> bool:
        if self._expires_at is None:
            return False
        expires_at = self._expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return datetime.now(UTC) > expires_at

    @property
    def is_valid(self) -> bool:
        if self._status != InviteStatus.ACTIVE:
            return False
        if self.is_expired:
            return False
        if self._use_count >= self._max_uses:
            return False
        return True

    def consume(self) -> None:
        if not self.is_valid:
            raise InvalidValueError(
                "invitation", self._status, "Invitation is no longer valid or active"
            )
        self._use_count += 1
        self._used_at = datetime.now(UTC)
        if self._use_count >= self._max_uses:
            self._status = InviteStatus.USED
        self._updated_at = datetime.now(UTC)

    def revoke(self) -> None:
        self._status = InviteStatus.REVOKED
        self._updated_at = datetime.now(UTC)
