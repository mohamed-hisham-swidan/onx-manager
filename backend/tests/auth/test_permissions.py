from __future__ import annotations

import pytest

from app.modules.auth.domain.aggregate import Role, User
from app.modules.auth.infrastructure.permissions import PermissionEvaluator
from app.modules.shared.value_objects import EmailAddress, Permission, RoleId, UserId


@pytest.fixture
def admin_role() -> Role:
    return Role(
        role_id=RoleId("admin"),
        name="Admin",
        permissions=[Permission("server", "*"), Permission("backup", "create")],
    )


@pytest.fixture
def viewer_role() -> Role:
    return Role(
        role_id=RoleId("viewer"),
        name="Viewer",
        permissions=[Permission("server", "list")],
    )


@pytest.fixture
def admin_user(admin_role: Role) -> User:
    user = User.create(
        user_id=UserId("u1"),
        email=EmailAddress("admin@test.com"),
        password_hash="hash",
        display_name="Admin",
    )
    user.collect_events()
    user.add_role(admin_role)
    return user


@pytest.fixture
def viewer_user(viewer_role: Role) -> User:
    user = User.create(
        user_id=UserId("u2"),
        email=EmailAddress("viewer@test.com"),
        password_hash="hash",
        display_name="Viewer",
    )
    user.collect_events()
    user.add_role(viewer_role)
    return user


@pytest.fixture
def evaluator() -> PermissionEvaluator:
    return PermissionEvaluator()


class TestPermissionEvaluator:
    async def test_has_permission_granted(
        self, evaluator: PermissionEvaluator, admin_user: User
    ) -> None:
        assert await evaluator.has_permission(admin_user, "server:read") is True
        assert await evaluator.has_permission(admin_user, "server:write") is True
        assert await evaluator.has_permission(admin_user, "backup:create") is True

    async def test_has_permission_denied(
        self, evaluator: PermissionEvaluator, viewer_user: User
    ) -> None:
        assert await evaluator.has_permission(viewer_user, "server:write") is False
        assert await evaluator.has_permission(viewer_user, "backup:create") is False

    async def test_inactive_user(self, evaluator: PermissionEvaluator, admin_user: User) -> None:
        admin_user.deactivate()
        assert await evaluator.has_permission(admin_user, "server:read") is False

    async def test_invalid_permission_string(
        self, evaluator: PermissionEvaluator, admin_user: User
    ) -> None:
        assert await evaluator.has_permission(admin_user, "invalid") is False

    async def test_get_effective_permissions_admin(
        self, evaluator: PermissionEvaluator, admin_user: User
    ) -> None:
        perms = await evaluator.get_effective_permissions(admin_user)
        assert "server:*" in perms
        assert "backup:create" in perms

    async def test_get_effective_permissions_viewer(
        self, evaluator: PermissionEvaluator, viewer_user: User
    ) -> None:
        perms = await evaluator.get_effective_permissions(viewer_user)
        assert perms == ["server:list"]

    async def test_filter_by_permission(
        self, evaluator: PermissionEvaluator, admin_user: User, viewer_user: User
    ) -> None:
        result = await evaluator.filter_by_permission([admin_user, viewer_user], "server:read")
        assert len(result) == 1
        assert result[0].user_id == admin_user.user_id
