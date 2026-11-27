from __future__ import annotations

from typing import Any

from app.core.authorization import authorize_server_action, is_admin_or_owner_context

CHANNEL_PATTERNS: dict[str, set[str]] = {
    "server:*": {"server:read"},
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
    "operation:*": {"admin:full"},
    "operation:{operation_id}": {"server:read"},
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
    "operation:*",
}


class ChannelAuthorizer:
    def __init__(self) -> None:
        self._user_permissions: dict[str, set[str]] = {}
        self._user_contexts: dict[str, dict[str, Any]] = {}

    def set_permissions(self, user_id: str, permissions: set[str]) -> None:
        self._user_permissions[user_id] = set(permissions)

    def get_permissions(self, user_id: str) -> set[str]:
        return self._user_permissions.get(user_id, set())

    def set_user_context(self, user_id: str, user_ctx: dict[str, Any]) -> None:
        self._user_contexts[user_id] = dict(user_ctx)
        self._user_permissions[user_id] = set(user_ctx.get("permissions", []))

    def get_user_context(self, user_id: str) -> dict[str, Any] | None:
        return self._user_contexts.get(user_id)

    def clear_user(self, user_id: str) -> None:
        self._user_permissions.pop(user_id, None)
        self._user_contexts.pop(user_id, None)

    def can_subscribe(self, user_id: str, channel: str) -> bool:
        if not isinstance(channel, str) or not channel:
            return False
        user_ctx = self._user_contexts.get(user_id)
        permissions = self.get_permissions(user_id)
        if user_ctx is None and not permissions:
            return False

        if user_ctx is not None:
            if user_ctx.get("db_error") or not user_ctx.get("is_active", True):
                return False
            if is_admin_or_owner_context(user_ctx):
                return True

            if channel in WILDCARD_CHANNELS or self.is_wildcard(channel):
                # Wildcard fleet streams are strictly Owner/Admin only.
                return False

            if channel.startswith("user:"):
                target_user_id = channel.split(":", 1)[1]
                return target_user_id == user_id

            parts = channel.split(":")
            if parts[0] == "server" and len(parts) == 2:
                return authorize_server_action(user_ctx, parts[1], "view")
            if parts[0] == "server" and len(parts) == 3 and parts[2] == "console":
                return authorize_server_action(user_ctx, parts[1], "console.view")
            if parts[0] in {"monitoring", "metrics", "provision"} and len(parts) == 2:
                return authorize_server_action(user_ctx, parts[1], "view")
            if parts[0] == "backup" and len(parts) == 2:
                return "backups" not in set(user_ctx.get("denied_permissions", []))
            if parts[0] == "plugin" and len(parts) == 2:
                return "plugins" not in set(user_ctx.get("denied_permissions", []))
            if parts[0] == "test" and len(parts) == 3 and parts[2] in {"console", "metrics"}:
                return "versioning" not in set(user_ctx.get("denied_permissions", []))
            return parts[0] == "operation" and len(parts) == 2

        if "admin:full" in permissions or "global.*" in permissions or "global:*" in permissions:
            return True

        if channel.startswith("user:"):
            target_user_id = channel.split(":", 1)[1]
            if target_user_id != user_id:
                return False

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
            "operation",
        }
        if parts[0] not in valid_prefixes:
            return False
        return not (
            len(parts) == 3
            and not (parts[0] in ("server", "test") and parts[2] in ("console", "metrics"))
        )
