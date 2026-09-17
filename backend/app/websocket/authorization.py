from __future__ import annotations

CHANNEL_PATTERNS: dict[str, set[str]] = {
    "server:*": {"server:read", "server:write"},
    "server:{server_id}": {"server:read"},
    "server:{server_id}:console": {"server:read"},
    "backup:*": {"backup:read"},
    "backup:{backup_id}": {"backup:read"},
    "plugin:*": {"plugin:read"},
    "plugin:{plugin_id}": {"plugin:read"},
    "monitoring:*": {"server:read"},
    "monitoring:{server_id}": {"server:read"},
    "metrics:*": {"server:read"},
    "metrics:{server_id}": {"server:read"},
    "auth:*": {"user:read"},
    "user:{user_id}": {"user:read"},
    "provision:*": {"server:read"},
    "provision:{server_id}": {"server:read"},
    "test:*": {"server:read"},
    "test:{test_id}:console": {"server:read"},
    "test:{test_id}:metrics": {"server:read"},
}

MAX_CHANNELS_PER_CONNECTION = 50

WILDCARD_CHANNELS: set[str] = {
    "server:*",
    "backup:*",
    "plugin:*",
    "monitoring:*",
    "metrics:*",
    "auth:*",
    "provision:*",
    "test:*",
}


class ChannelAuthorizer:
    def __init__(self) -> None:
        self._user_permissions: dict[str, set[str]] = {}

    def set_permissions(self, user_id: str, permissions: set[str]) -> None:
        self._user_permissions[user_id] = permissions

    def get_permissions(self, user_id: str) -> set[str]:
        return self._user_permissions.get(user_id, set())

    def can_subscribe(self, user_id: str, channel: str) -> bool:
        permissions = self.get_permissions(user_id)
        if not permissions:
            return False

        if "admin:full" in permissions:
            return True

        if channel in WILDCARD_CHANNELS:
            required = CHANNEL_PATTERNS.get(channel, set())
            return required.issubset(permissions)

        for pattern, required in CHANNEL_PATTERNS.items():
            if self._match_pattern(channel, pattern) and required.issubset(permissions):
                return True

        return False

    @staticmethod
    def _match_pattern(channel: str, pattern: str) -> bool:
        if pattern == channel:
            return True
        if "{" not in pattern:
            return False
        pattern_parts = pattern.split(":")
        channel_parts = channel.split(":")
        if len(pattern_parts) != len(channel_parts):
            return False
        for p, c in zip(pattern_parts, channel_parts, strict=False):
            if p.startswith("{") and p.endswith("}"):
                continue
            if p != c:
                return False
        return True

    @staticmethod
    def is_wildcard(channel: str) -> bool:
        return channel in WILDCARD_CHANNELS or channel.endswith(":*")

    @staticmethod
    def validate_channel(channel: str) -> bool:
        if not channel or len(channel) > 128:
            return False
        parts = channel.split(":")
        if len(parts) not in (2, 3):
            return False
        valid_prefixes = {
            "server",
            "test",
            "backup",
            "plugin",
            "monitoring",
            "metrics",
            "auth",
            "user",
            "provision",
        }
        if parts[0] not in valid_prefixes:
            return False
        return not (
            len(parts) == 3
            and not (parts[0] in ("server", "test") and parts[2] in ("console", "metrics"))
        )
