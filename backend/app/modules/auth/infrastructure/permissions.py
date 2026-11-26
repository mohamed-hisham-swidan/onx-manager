from __future__ import annotations

from app.modules.auth.domain.aggregate import User
from app.modules.shared.value_objects import Permission


class PermissionEvaluator:
    async def has_permission(
        self,
        user: User,
        permission: str,
        resource_id: str | None = None,
    ) -> bool:
        if not user.is_active:
            return False
        try:
            perm = Permission.parse(permission)
        except ValueError:
            return False
        for role in user.roles:
            if role.has_permission(perm.resource, perm.action):
                return True
        return False

    async def get_effective_permissions(self, user: User) -> list[str]:
        result: set[str] = set()
        if not user.is_active:
            return []
        for role in user.roles:
            for perm in role.permissions:
                result.add(str(perm))
        return sorted(result)

    async def filter_by_permission(
        self,
        users: list[User],
        permission: str,
    ) -> list[User]:
        result: list[User] = []
        for user in users:
            if await self.has_permission(user, permission):
                result.append(user)
        return result
