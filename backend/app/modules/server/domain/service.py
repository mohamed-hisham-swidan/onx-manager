from __future__ import annotations

from app.modules.server.domain.aggregate import Server
from app.modules.shared.value_objects import Permission


class ServerMaintenanceService:
    MIN_DISK_SPACE_MB: int = 1024

    async def can_start(self, server: Server) -> tuple[bool, str]:
        if server.status.value not in ("created", "stopped", "crashed"):
            return False, f"Server is in {server.status.value} state, cannot start"
        return True, ""

    async def estimate_disk_needed_mb(self, server: Server) -> int:
        base = 500
        memory_overhead = (server.memory.max_mb // 1024) * 256
        return base + memory_overhead


class PermissionEvaluationService:
    def has_permission(
        self,
        user_permissions: list[Permission],
        role_permissions: list[Permission],
        required_resource: str,
        required_action: str,
    ) -> bool:
        all_permissions = list(set(user_permissions) | set(role_permissions))
        for p in all_permissions:
            if p.resource == required_resource and p.action in (required_action, "*"):
                return True
            if p.resource == "*" and p.action == "*":
                return True
        return False

    def has_any_permission(
        self,
        user_permissions: list[Permission],
        role_permissions: list[Permission],
        resource: str,
    ) -> bool:
        all_permissions = list(set(user_permissions) | set(role_permissions))
        return any(p.resource in (resource, "*") for p in all_permissions)
