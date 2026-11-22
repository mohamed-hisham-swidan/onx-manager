from __future__ import annotations

from typing import Any

from app.core.event_bus import DomainEvent


class UserCreatedEvent(DomainEvent):
    user_id: str
    username: str = ""
    email: str | None = None

    def __init__(
        self,
        user_id: str,
        username: str = "",
        email: str | None = None,
        **data: Any,
    ) -> None:
        resolved_username = username or (email or "")
        super().__init__(
            user_id=user_id,
            username=resolved_username,
            email=email,
            **data,
        )


class UserLoggedInEvent(DomainEvent):
    user_id: str
    ip_address: str

    def __init__(self, user_id: str, ip_address: str, **data: Any) -> None:
        super().__init__(user_id=user_id, ip_address=ip_address, **data)


class UserLoggedOutEvent(DomainEvent):
    user_id: str

    def __init__(self, user_id: str, **data: Any) -> None:
        super().__init__(user_id=user_id, **data)


class UserDeactivatedEvent(DomainEvent):
    user_id: str

    def __init__(self, user_id: str, **data: Any) -> None:
        super().__init__(user_id=user_id, **data)


class UserActivatedEvent(DomainEvent):
    user_id: str

    def __init__(self, user_id: str, **data: Any) -> None:
        super().__init__(user_id=user_id, **data)



class ApiKeyCreatedEvent(DomainEvent):
    user_id: str
    key_name: str

    def __init__(self, user_id: str, key_name: str, **data: Any) -> None:
        super().__init__(user_id=user_id, key_name=key_name, **data)


class ApiKeyRevokedEvent(DomainEvent):
    user_id: str
    key_name: str

    def __init__(self, user_id: str, key_name: str, **data: Any) -> None:
        super().__init__(user_id=user_id, key_name=key_name, **data)
