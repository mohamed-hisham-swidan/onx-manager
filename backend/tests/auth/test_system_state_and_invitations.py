import pytest
import uuid
from datetime import datetime, timedelta, timezone
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.exceptions import InvalidValueError
from app.core.persistence.base import Base
from app.modules.auth.domain.aggregate import AccessMode, Invitation, InviteStatus, SystemState
from app.modules.auth.infrastructure.repository import SQLInvitationRepository, SQLSystemStateRepository
from app.modules.server.infrastructure.models import ServerModel


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


class TestSystemStateDomain:
    def test_default_system_state(self):
        state = SystemState()
        assert state.id == "default"
        assert state.initialized is False
        assert state.access_mode == AccessMode.LOCAL

    def test_mark_initialized(self):
        state = SystemState()
        state.mark_initialized(access_mode=AccessMode.GLOBAL)
        assert state.initialized is True
        assert state.access_mode == AccessMode.GLOBAL

    def test_set_access_mode(self):
        state = SystemState(access_mode=AccessMode.LOCAL)
        state.set_access_mode(AccessMode.GLOBAL)
        assert state.access_mode == AccessMode.GLOBAL


class TestInvitationDomain:
    def test_invitation_validity(self):
        invitation = Invitation(
            invitation_id=uuid.uuid4().hex,
            token_hash="hash123",
            token_prefix="mcis_123",
            max_uses=1,
            use_count=0,
        )
        assert invitation.is_valid is True
        assert invitation.is_expired is False

    def test_invitation_expiration(self):
        past_time = datetime.now(timezone.utc) - timedelta(hours=1)
        invitation = Invitation(
            invitation_id=uuid.uuid4().hex,
            token_hash="hash123",
            token_prefix="mcis_123",
            expires_at=past_time,
        )
        assert invitation.is_expired is True
        assert invitation.is_valid is False

    def test_invitation_consume(self):
        invitation = Invitation(
            invitation_id=uuid.uuid4().hex,
            token_hash="hash123",
            token_prefix="mcis_123",
            max_uses=1,
            use_count=0,
        )
        invitation.consume()
        assert invitation.use_count == 1
        assert invitation.status == InviteStatus.USED
        assert invitation.is_valid is False

        with pytest.raises(InvalidValueError):
            invitation.consume()

    def test_invitation_revoke(self):
        invitation = Invitation(
            invitation_id=uuid.uuid4().hex,
            token_hash="hash123",
            token_prefix="mcis_123",
        )
        invitation.revoke()
        assert invitation.status == InviteStatus.REVOKED
        assert invitation.is_valid is False


@pytest.mark.asyncio
class TestSystemStateRepository:
    async def test_system_state_repository_save_and_get(self, db_session: AsyncSession):
        repo = SQLSystemStateRepository(db_session)
        state = await repo.get("default")
        assert state.initialized is False

        state.mark_initialized(AccessMode.GLOBAL)
        await repo.save(state)
        await db_session.commit()

        retrieved = await repo.get("default")
        assert retrieved.initialized is True
        assert retrieved.access_mode == AccessMode.GLOBAL


@pytest.mark.asyncio
class TestInvitationRepository:
    async def test_invitation_repository_crud_and_atomic_consume(self, db_session: AsyncSession):
        repo = SQLInvitationRepository(db_session)
        inv_id = uuid.uuid4().hex
        token_hash = "token_hash_abc_123"

        invitation = Invitation(
            invitation_id=inv_id,
            token_hash=token_hash,
            token_prefix="mcis_abc",
            email="invitee@example.com",
            global_role="member",
            max_uses=1,
        )

        await repo.save(invitation)
        await db_session.commit()

        by_id = await repo.get(inv_id)
        assert by_id is not None
        assert by_id.email == "invitee@example.com"

        by_hash = await repo.get_by_token_hash(token_hash)
        assert by_hash is not None
        assert by_hash.invitation_id == inv_id

        all_invites = await repo.list()
        assert any(i.invitation_id == inv_id for i in all_invites)

        consumed = await repo.atomic_consume(inv_id)
        assert consumed is True
        await db_session.commit()

        # Second attempt should return False
        consumed_again = await repo.atomic_consume(inv_id)
        assert consumed_again is False

