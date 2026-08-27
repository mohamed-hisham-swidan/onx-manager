from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.deps import require_server_permission
from app.core.persistence.base import Base
from app.modules.auth.infrastructure.models import UserModel
from app.modules.server.infrastructure.models import ServerMembershipModel, ServerModel
from app.modules.server.infrastructure.repository import SQLServerMembershipRepository


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


class MockRequest:
    def __init__(self, path_params: dict | None = None, query_params: dict | None = None) -> None:
        self.path_params = path_params or {}
        self.query_params = query_params or {}


@pytest.mark.asyncio
async def test_repository_crud_operations(db_session: AsyncSession) -> None:
    repo = SQLServerMembershipRepository(db_session)

    user = UserModel(
        id="u1", email="test@example.com", password_hash="hash", display_name="Test User"
    )
    server = ServerModel(id="s1", name="Test Server", minecraft_version="1.20.1")
    db_session.add_all([user, server])
    await db_session.flush()

    # Add membership
    mem = await repo.add_membership(id="m1", server_id="s1", user_id="u1", role="dev")
    assert mem.id == "m1"
    assert mem.role == "dev"

    # Get membership
    fetched = await repo.get_membership(server_id="s1", user_id="u1")
    assert fetched is not None
    assert fetched.role == "dev"

    # List memberships
    by_server = await repo.list_memberships_for_server("s1")
    assert len(by_server) == 1
    by_user = await repo.list_memberships_for_user("u1")
    assert len(by_user) == 1

    # Update role
    updated = await repo.update_membership_role("s1", "u1", "admin")
    assert updated is not None
    assert updated.role == "admin"

    # Remove membership
    removed = await repo.remove_membership("s1", "u1")
    assert removed is True
    assert await repo.get_membership("s1", "u1") is None


@pytest.mark.asyncio
async def test_require_server_permission_jwt_short_circuit(db_session: AsyncSession) -> None:
    check_fn = require_server_permission("server.files")
    req = MockRequest(path_params={"server_id": "non-existent-server"})

    admin_user = {"user_id": "u_admin", "permissions": ["admin:full"]}
    res = await check_fn(request=req, db=db_session, current_user=admin_user)
    assert res == admin_user

    global_user = {"user_id": "u_global", "permissions": ["global.*"]}
    res = await check_fn(request=req, db=db_session, current_user=global_user)
    assert res == global_user


@pytest.mark.asyncio
async def test_require_server_permission_non_existent_server_404(db_session: AsyncSession) -> None:
    check_fn = require_server_permission("server.files")
    req = MockRequest(path_params={"server_id": "missing_s1"})
    user = {"user_id": "u1", "permissions": []}

    with pytest.raises(HTTPException) as exc_info:
        await check_fn(request=req, db=db_session, current_user=user)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Server not found"


@pytest.mark.asyncio
async def test_require_server_permission_owner_access_granted(db_session: AsyncSession) -> None:
    user_owner = UserModel(
        id="u_owner", email="owner@example.com", password_hash="h", display_name="Owner"
    )
    server = ServerModel(
        id="s1", name="Owner Server", minecraft_version="1.20.1", owner_id="u_owner"
    )
    db_session.add_all([user_owner, server])
    await db_session.flush()

    check_fn = require_server_permission("server.console")
    req = MockRequest(path_params={"server_id": "s1"})
    current_user = {"user_id": "u_owner", "permissions": []}

    res = await check_fn(request=req, db=db_session, current_user=current_user)
    assert res == current_user


@pytest.mark.asyncio
async def test_require_server_permission_membership_role_matching(db_session: AsyncSession) -> None:
    user = UserModel(id="u_dev", email="dev@example.com", password_hash="h", display_name="Dev")
    server = ServerModel(id="s1", name="Dev Server", minecraft_version="1.20.1")
    mem = ServerMembershipModel(id="m1", server_id="s1", user_id="u_dev", role="dev")
    db_session.add_all([user, server, mem])
    await db_session.flush()

    check_fn = require_server_permission("server.files")
    req = MockRequest(path_params={"server_id": "s1"})
    current_user = {"user_id": "u_dev", "permissions": []}

    res = await check_fn(request=req, db=db_session, current_user=current_user)
    assert res == current_user


@pytest.mark.asyncio
async def test_require_server_permission_membership_role_non_matching_403(
    db_session: AsyncSession,
) -> None:
    user = UserModel(
        id="u_viewer", email="viewer@example.com", password_hash="h", display_name="Viewer"
    )
    server = ServerModel(id="s1", name="Viewer Server", minecraft_version="1.20.1")
    mem = ServerMembershipModel(id="m1", server_id="s1", user_id="u_viewer", role="viewer")
    db_session.add_all([user, server, mem])
    await db_session.flush()

    check_fn = require_server_permission("server.files")
    req = MockRequest(path_params={"server_id": "s1"})
    current_user = {"user_id": "u_viewer", "permissions": []}

    with pytest.raises(HTTPException) as exc_info:
        await check_fn(request=req, db=db_session, current_user=current_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied"


@pytest.mark.asyncio
async def test_require_server_permission_no_membership_403(db_session: AsyncSession) -> None:
    user = UserModel(
        id="u_outsider", email="out@example.com", password_hash="h", display_name="Outsider"
    )
    server = ServerModel(id="s1", name="Private Server", minecraft_version="1.20.1")
    db_session.add_all([user, server])
    await db_session.flush()

    check_fn = require_server_permission("server.view")
    req = MockRequest(path_params={"server_id": "s1"})
    current_user = {"user_id": "u_outsider", "permissions": []}

    with pytest.raises(HTTPException) as exc_info:
        await check_fn(request=req, db=db_session, current_user=current_user)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Permission denied"


@pytest.mark.asyncio
async def test_require_server_permission_multiple_permissions_any_of(
    db_session: AsyncSession,
) -> None:
    user = UserModel(id="u_viewer", email="v@example.com", password_hash="h", display_name="Viewer")
    server = ServerModel(id="s1", name="Server", minecraft_version="1.20.1")
    mem = ServerMembershipModel(id="m1", server_id="s1", user_id="u_viewer", role="viewer")
    db_session.add_all([user, server, mem])
    await db_session.flush()

    # Viewer has server.{id}.view, so calling with ("server.{id}.files", "server.{id}.view") should succeed
    check_fn = require_server_permission("server.{id}.files", "server.{id}.view")
    req = MockRequest(path_params={"server_id": "s1"})
    current_user = {"user_id": "u_viewer", "permissions": []}

    res = await check_fn(request=req, db=db_session, current_user=current_user)
    assert res == current_user

    # Calling with only ("server.{id}.files", "server.{id}.console") should fail (403)
    check_fn_strict = require_server_permission("server.{id}.files", "server.{id}.console")
    with pytest.raises(HTTPException) as exc_info:
        await check_fn_strict(request=req, db=db_session, current_user=current_user)
    assert exc_info.value.status_code == 403
