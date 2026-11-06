from __future__ import annotations

import pytest

from app.modules.auth.domain.aggregate import ApiKey, Role, User
from app.modules.auth.domain.events import (
    ApiKeyCreatedEvent,
    ApiKeyRevokedEvent,
    UserActivatedEvent,
    UserCreatedEvent,
    UserDeactivatedEvent,
    UserLoggedInEvent,
)
from app.modules.shared.value_objects import ApiKeyId, EmailAddress, Permission, RoleId, UserId


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
def sample_user(admin_role: Role) -> User:
    user = User.create(
        user_id=UserId("u1"),
        email=EmailAddress("admin@example.com"),
        password_hash="hashed_pw",
        display_name="Admin User",
    )
    user.collect_events()
    user.add_role(admin_role)
    return user


class TestUser:
    def test_create_emits_event(self) -> None:
        user = User.create(
            user_id=UserId("u1"),
            email=EmailAddress("test@example.com"),
            password_hash="hashed",
            display_name="Test",
        )
        events = user.collect_events()
        assert len(events) == 1
        assert isinstance(events[0], UserCreatedEvent)

    def test_properties(self, sample_user: User) -> None:
        assert sample_user.user_id == UserId("u1")
        assert str(sample_user.email) == "admin@example.com"
        assert sample_user.display_name == "Admin User"
        assert sample_user.is_active is True

    def test_add_role(self, sample_user: User, viewer_role: Role) -> None:
        sample_user.add_role(viewer_role)
        assert len(sample_user.roles) == 2

    def test_remove_role(self, sample_user: User, admin_role: Role) -> None:
        sample_user.remove_role(admin_role)
        assert len(sample_user.roles) == 0

    def test_has_permission(self, sample_user: User) -> None:
        assert sample_user.has_permission("server", "start") is True
        assert sample_user.has_permission("backup", "create") is True

    def test_has_permission_denied(self, sample_user: User) -> None:
        assert sample_user.has_permission("plugin", "install") is False

    def test_record_login(self, sample_user: User) -> None:
        sample_user.collect_events()
        sample_user.record_login(ip_address="192.168.1.1")
        assert sample_user.last_login_at is not None
        events = sample_user.collect_events()
        assert any(isinstance(e, UserLoggedInEvent) for e in events)

    def test_deactivate(self, sample_user: User) -> None:
        sample_user.collect_events()
        sample_user.deactivate()
        assert sample_user.is_active is False
        events = sample_user.collect_events()
        assert any(isinstance(e, UserDeactivatedEvent) for e in events)

    def test_activate(self, sample_user: User) -> None:
        sample_user.deactivate()
        sample_user.collect_events()
        sample_user.activate()
        assert sample_user.is_active is True
        events = sample_user.collect_events()
        assert any(isinstance(e, UserActivatedEvent) for e in events)

    def test_add_api_key(self, sample_user: User) -> None:
        sample_user.collect_events()
        api_key = ApiKey(
            api_key_id=ApiKeyId("key1"),
            name="My Key",
            prefix="mcs_abc",
        )
        sample_user.add_api_key(api_key)
        assert len(sample_user.api_keys) == 1
        events = sample_user.collect_events()
        assert any(isinstance(e, ApiKeyCreatedEvent) for e in events)

    def test_revoke_api_key(self, sample_user: User) -> None:
        api_key = ApiKey(
            api_key_id=ApiKeyId("key1"),
            name="My Key",
            prefix="mcs_abc",
        )
        sample_user.add_api_key(api_key)
        sample_user.collect_events()
        sample_user.revoke_api_key(ApiKeyId("key1"))
        assert sample_user.api_keys[0].is_revoked is True
        events = sample_user.collect_events()
        assert any(isinstance(e, ApiKeyRevokedEvent) for e in events)


class TestRole:
    def test_create_role(self) -> None:
        role = Role(
            role_id=RoleId("mod"),
            name="Moderator",
            permissions=[Permission("server", "list")],
        )
        assert role.name == "Moderator"
        assert role.has_permission("server", "list") is True

    def test_has_permission_wildcard(self) -> None:
        role = Role(
            role_id=RoleId("admin"),
            name="Admin",
            permissions=[Permission("server", "*")],
        )
        assert role.has_permission("server", "start") is True
        assert role.has_permission("server", "stop") is True

    def test_add_permission(self) -> None:
        role = Role(role_id=RoleId("r1"), name="Role")
        role.add_permission(Permission("server", "start"))
        assert role.has_permission("server", "start") is True

    def test_remove_permission(self) -> None:
        role = Role(
            role_id=RoleId("r1"),
            name="Role",
            permissions=[Permission("server", "start")],
        )
        role.remove_permission(Permission("server", "start"))
        assert role.has_permission("server", "start") is False


class TestApiKey:
    def test_create(self) -> None:
        key = ApiKey(
            api_key_id=ApiKeyId("k1"),
            name="CI Key",
            prefix="mcs_ci",
        )
        assert key.name == "CI Key"
        assert key.is_revoked is False
        assert key.is_expired is False

    def test_revoke(self) -> None:
        key = ApiKey(
            api_key_id=ApiKeyId("k1"),
            name="Key",
            prefix="mcs_",
        )
        key.revoke()
        assert key.is_revoked is True

    def test_has_permission(self) -> None:
        key = ApiKey(
            api_key_id=ApiKeyId("k1"),
            name="Key",
            prefix="mcs_",
            permissions=[Permission("server", "start")],
        )
        assert key.has_permission("server", "start") is True
        assert key.has_permission("server", "stop") is False
