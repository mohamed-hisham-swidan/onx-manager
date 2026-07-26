from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain.aggregate import ApiKey, Role, User
from app.modules.auth.infrastructure.models import ApiKeyModel, RoleModel, UserModel
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
        model = await self._session.get(UserModel, str(user.user_id))
        if model is None:
            model = UserModel(id=str(user.user_id))
            self._session.add(model)

        model.email = str(user.email)
        model.password_hash = user.password_hash
        model.display_name = user.display_name
        model.is_active = user.is_active
        model.last_login_at = user.last_login_at
        await self._session.flush()

        for role in user.roles:
            role_model = await self._session.get(RoleModel, str(role.role_id))
            if role_model and role_model not in model.roles:
                model.roles.append(role_model)
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
