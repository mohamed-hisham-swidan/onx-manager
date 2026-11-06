from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.domain.aggregate import (
    AccessMode,
    ApiKey,
    Invitation,
    InviteStatus,
    Role,
    SystemState,
    User,
)
from app.modules.auth.infrastructure.models import (
    ApiKeyModel,
    InvitationModel,
    RoleModel,
    SystemStateModel,
    UserModel,
)
from app.modules.shared.value_objects import ApiKeyId, EmailAddress, Permission, RoleId, UserId


class SQLUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> User:
        model = await self._session.get(UserModel, str(user_id))
        if model is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"User '{user_id}' not found")
        return await self._model_to_domain_user(model)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(UserModel).where(UserModel.email == email)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return await self._model_to_domain_user(model)

    async def list(self) -> list[User]:
        stmt = select(UserModel).order_by(UserModel.display_name)
        result = await self._session.execute(stmt)
        users = []
        for model in result.scalars().all():
            users.append(await self._model_to_domain_user(model))
        return users

    async def save(self, user: User) -> None:
        stmt = (
            select(UserModel)
            .where(UserModel.id == str(user.user_id))
            .options(selectinload(UserModel.roles))
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        user_role_ids = {str(r.role_id) for r in user.roles}
        if model is None:
            model = UserModel(
                id=str(user.user_id),
                email=str(user.email),
                password_hash=user.password_hash,
                display_name=user.display_name,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
                roles=[],
            )
            self._session.add(model)
            existing_role_ids = set()
        else:
            model.email = str(user.email)
            model.password_hash = user.password_hash
            model.display_name = user.display_name
            model.is_active = user.is_active
            model.last_login_at = user.last_login_at
            model.roles = [r for r in model.roles if r.id in user_role_ids]
            existing_role_ids = {r.id for r in model.roles}

        for role in user.roles:
            if str(role.role_id) not in existing_role_ids:
                role_model = await self._session.get(RoleModel, str(role.role_id))
                if role_model:
                    model.roles.append(role_model)
                    existing_role_ids.add(role_model.id)

        await self._session.flush()

        for api_key in user.api_keys:
            await self.save_api_key(api_key, str(user.user_id))

    async def delete(self, user_id: UserId) -> None:
        model = await self._session.get(UserModel, str(user_id))
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def save_role(self, role: Role) -> None:
        model = await self._session.get(RoleModel, str(role.role_id))
        if model is None:
            model = RoleModel(id=str(role.role_id))
            self._session.add(model)

        model.name = role.name
        model.description = role.description
        model.permissions = ",".join(str(p) for p in role.permissions)
        await self._session.flush()

    async def get_role(self, role_id: RoleId) -> Role | None:
        model = await self._session.get(RoleModel, str(role_id))
        if model is None:
            return None
        return self._model_to_domain_role(model)

    async def get_role_by_name(self, name: str) -> Role | None:
        stmt = select(RoleModel).where(RoleModel.name == name)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._model_to_domain_role(model)

    async def count_users(self) -> int:
        from sqlalchemy import func

        stmt = select(func.count(UserModel.id))
        result = await self._session.execute(stmt)
        return result.scalar() or 0

    async def save_api_key(self, api_key: ApiKey, user_id: str = "") -> None:
        model = await self._session.get(ApiKeyModel, str(api_key.api_key_id))
        if model is None:
            model = ApiKeyModel(id=str(api_key.api_key_id))
            self._session.add(model)

        if user_id:
            model.user_id = user_id
        model.name = api_key.name
        model.prefix = api_key.prefix
        if api_key.key_hash:
            model.key_hash = api_key.key_hash
        model.permissions = ",".join(str(p) for p in api_key.permissions)
        model.expires_at = api_key.expires_at
        model.is_revoked = api_key.is_revoked
        await self._session.flush()

    async def _model_to_domain_user(self, model: UserModel) -> User:
        roles = [self._model_to_domain_role(r) for r in model.roles]

        api_keys_stmt = select(ApiKeyModel).where(ApiKeyModel.user_id == model.id)
        api_keys_result = await self._session.execute(api_keys_stmt)
        api_keys = [self._model_to_domain_api_key(m) for m in api_keys_result.scalars().all()]

        return User(
            user_id=UserId(model.id),
            email=EmailAddress(model.email),
            password_hash=model.password_hash,
            display_name=model.display_name,
            roles=roles,
            api_keys=api_keys,
            is_active=model.is_active,
            created_at=model.created_at,
            last_login_at=model.last_login_at,
        )

    def _model_to_domain_role(self, model: RoleModel) -> Role:
        perms = []
        for p_str in model.permissions.split(","):
            p_str = p_str.strip()
            if p_str:
                perms.append(Permission.parse(p_str))

        return Role(
            role_id=RoleId(model.id),
            name=model.name,
            permissions=perms,
            description=model.description,
        )

    def _model_to_domain_api_key(self, model: ApiKeyModel) -> ApiKey:
        perms = []
        for p_str in model.permissions.split(","):
            p_str = p_str.strip()
            if p_str:
                perms.append(Permission.parse(p_str))

        return ApiKey(
            api_key_id=ApiKeyId(model.id),
            name=model.name,
            prefix=model.prefix,
            key_hash=model.key_hash or "",
            permissions=perms,
            expires_at=model.expires_at,
            is_revoked=model.is_revoked,
            created_at=model.created_at,
        )


class SQLSystemStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, id: str = "default") -> SystemState:
        model = await self._session.get(SystemStateModel, id)
        if model is None:
            return SystemState(id=id, initialized=False, access_mode=AccessMode.LOCAL)
        return self._model_to_domain(model)

    async def get_with_lock(self, id: str = "default") -> SystemState:
        stmt = select(SystemStateModel).where(SystemStateModel.id == id).with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return SystemState(id=id, initialized=False, access_mode=AccessMode.LOCAL)
        return self._model_to_domain(model)

    async def save(self, system_state: SystemState) -> None:
        model = await self._session.get(SystemStateModel, system_state.id)
        if model is None:
            model = SystemStateModel(id=system_state.id)
            self._session.add(model)

        model.initialized = system_state.initialized
        model.access_mode = str(
            system_state.access_mode.value
            if isinstance(system_state.access_mode, AccessMode)
            else system_state.access_mode
        )
        await self._session.flush()

    def _model_to_domain(self, model: SystemStateModel) -> SystemState:
        return SystemState(
            id=model.id,
            initialized=model.initialized,
            access_mode=model.access_mode,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SQLInvitationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, invitation_id: str) -> Invitation | None:
        model = await self._session.get(InvitationModel, invitation_id)
        if model is None:
            return None
        return self._model_to_domain(model)

    async def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        stmt = select(InvitationModel).where(InvitationModel.token_hash == token_hash)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._model_to_domain(model)

    async def list(self) -> list[Invitation]:
        stmt = select(InvitationModel).order_by(InvitationModel.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._model_to_domain(m) for m in result.scalars().all()]

    async def save(self, invitation: Invitation) -> None:
        model = await self._session.get(InvitationModel, invitation.invitation_id)
        if model is None:
            model = InvitationModel(id=invitation.invitation_id)
            self._session.add(model)

        model.token_hash = invitation.token_hash
        model.token_prefix = invitation.token_prefix
        model.creator_id = invitation.creator_id
        model.email = invitation.email
        model.global_role = invitation.global_role
        model.server_id = invitation.server_id
        model.server_role = invitation.server_role
        model.status = str(
            invitation.status.value
            if isinstance(invitation.status, InviteStatus)
            else invitation.status
        )
        model.max_uses = invitation.max_uses
        model.use_count = invitation.use_count
        model.expires_at = invitation.expires_at
        model.used_at = invitation.used_at
        await self._session.flush()

    async def atomic_consume(self, invitation_id: str) -> bool:
        """Atomically verifies, consumes, and saves invitation status under row lock."""
        stmt = select(InvitationModel).where(InvitationModel.id == invitation_id).with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            return False

        domain = self._model_to_domain(model)
        if not domain.is_valid:
            return False

        domain.consume()
        model.use_count = domain.use_count
        model.status = str(
            domain.status.value if isinstance(domain.status, InviteStatus) else domain.status
        )
        model.used_at = domain.used_at
        await self._session.flush()
        return True

    def _model_to_domain(self, model: InvitationModel) -> Invitation:
        return Invitation(
            invitation_id=model.id,
            token_hash=model.token_hash,
            token_prefix=model.token_prefix,
            creator_id=model.creator_id,
            email=model.email,
            global_role=model.global_role,
            server_id=model.server_id,
            server_role=model.server_role,
            status=model.status,
            max_uses=model.max_uses,
            use_count=model.use_count,
            expires_at=model.expires_at,
            used_at=model.used_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
