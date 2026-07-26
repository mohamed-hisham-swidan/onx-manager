from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class WSConnectionInfo:
    connection_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str = ""
    token: str = ""
    token_expires_at: float = 0.0
    connected_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    subscriptions: set[str] = field(default_factory=set)


class WSAuthenticator:
    IDLE_TIMEOUT = 90.0

    def __init__(self) -> None:
        self._connections: dict[str, WSConnectionInfo] = {}

    def register_connection(self, connection_id: str, user_id: str, token: str, expires_at: float) -> WSConnectionInfo:
        info = WSConnectionInfo(
            connection_id=connection_id,
            user_id=user_id,
            token=token,
            token_expires_at=expires_at,
        )
        self._connections[connection_id] = info
        return info

    def get_connection(self, connection_id: str) -> WSConnectionInfo | None:
        return self._connections.get(connection_id)

    def remove_connection(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    def refresh_token(self, connection_id: str, new_token: str, new_expires_at: float) -> bool:
        info = self._connections.get(connection_id)
        if info is None:
            return False
        info.token = new_token
        info.token_expires_at = new_expires_at
        return True

    def is_token_expired(self, connection_id: str) -> bool:
        info = self._connections.get(connection_id)
        if info is None:
            return True
        return time.time() >= info.token_expires_at

    def update_activity(self, connection_id: str) -> None:
        info = self._connections.get(connection_id)
        if info is not None:
            info.last_activity = time.time()

    def is_idle(self, connection_id: str) -> bool:
        info = self._connections.get(connection_id)
        if info is None:
            return True
        return time.time() - info.last_activity > self.IDLE_TIMEOUT

    @property
    def active_connections(self) -> int:
        return len(self._connections)
