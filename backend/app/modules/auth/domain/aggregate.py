from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from app.core.exceptions import InvalidValueError
from app.modules.auth.domain.events import (
    ApiKeyCreatedEvent,
    ApiKeyRevokedEvent,
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
        self._created_at = created_at or datetime.now(timezone.utc)

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
        return datetime.now(timezone.utc) > self._expires_at

    def revoke(self) -> None:
        self._is_revoked = True

    def has_permission(self, resource: str, action: str) -> bool:
        return any(p.resource == resource and p.action in (action, "*") for p in self._permissions)


class User(AggregateRoot):
    def __init__(
        self,
        user_id: UserId,
        email: EmailAddress,
        password_hash: str,
        display_name: str,
        roles: list[Role] | None = None,
        api_keys: list[ApiKey] | None = None,
        is_active: bool = True,
        created_at: datetime | None = None,
        last_login_at: datetime | None = None,
    ) -> None:
        super().__init__()
        self._user_id = user_id
        self._email = email
        self._password_hash = password_hash
        self._display_name = display_name
        self._roles = roles or []
        self._api_keys = api_keys or []
        self._is_active = is_active
        self._created_at = created_at or datetime.now(timezone.utc)
        self._last_login_at = last_login_at

    @property
    def user_id(self) -> UserId:
        return self._user_id

    @property
    def email(self) -> EmailAddress:
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
    def create(cls, user_id: UserId, email: EmailAddress, password_hash: str, display_name: str) -> User:
        user = cls(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            display_name=display_name,
        )
        user._add_event(UserCreatedEvent(user_id=str(user_id), email=str(email)))
        return user

    def add_role(self, role: Role) -> None:
        if role not in self._roles:
            self._roles.append(role)

    def remove_role(self, role: Role) -> None:
        self._roles = [r for r in self._roles if r.role_id != role.role_id]

    def has_permission(self, resource: str, action: str) -> bool:
        return any(role.has_permission(resource, action) for role in self._roles)

    def set_email(self, email: EmailAddress) -> None:
        self._email = email

    def set_display_name(self, display_name: str) -> None:
        self._display_name = display_name

    def record_login(self, ip_address: str) -> None:
        self._last_login_at = datetime.now(timezone.utc)
        self._add_event(UserLoggedInEvent(user_id=str(self._user_id), ip_address=ip_address))

    def record_logout(self) -> None:
        self._add_event(UserLoggedOutEvent(user_id=str(self._user_id)))

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
