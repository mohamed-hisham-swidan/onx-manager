from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_api_key
from app.modules.auth.infrastructure.jwt import verify_access_token
from app.modules.auth.infrastructure.models import ApiKeyModel, UserModel


def _is_api_key(token: str) -> bool:
    return token.startswith("onx_") or token.startswith("mcs_")


async def resolve_bearer_token(token: str, db: AsyncSession) -> dict:
    if _is_api_key(token):
        return await _resolve_api_key(token, db)
    claims = verify_access_token(token)
    return {
        "user_id": claims["sub"],
        "roles": claims.get("roles", []),
        "permissions": claims.get("permissions", []),
        "scope": claims.get("scope", ""),
    }


async def _resolve_api_key(token: str, db: AsyncSession) -> dict:
    key_hash = hash_api_key(token)
    stmt = select(ApiKeyModel).where(ApiKeyModel.key_hash == key_hash)
    result = await db.execute(stmt)
    api_key_model = result.scalar_one_or_none()
    if api_key_model is None:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("Invalid API key")
    if api_key_model.is_revoked:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("API key is revoked")
    if api_key_model.expires_at and api_key_model.expires_at < datetime.now(UTC):
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("API key has expired")

    user_stmt = select(UserModel).where(UserModel.id == api_key_model.user_id)
    user_result = await db.execute(user_stmt)
    user_model = user_result.scalar_one_or_none()
    if user_model is None:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("API key owner not found")
    if not user_model.is_active:
        from app.core.exceptions import AuthenticationError

        raise AuthenticationError("Account is deactivated")

    role_names = [r.name for r in user_model.roles]
    perms_str = api_key_model.permissions or ""
    permissions = [p.strip() for p in perms_str.split(",") if p.strip()]

    return {
        "user_id": user_model.id,
        "roles": role_names,
        "permissions": permissions,
        "scope": ",".join(permissions),
    }
