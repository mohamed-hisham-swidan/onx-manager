import re

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.auth_utils import _is_api_key, _resolve_api_key, resolve_bearer_token
from app.core.authorization import is_admin_or_owner_context
from app.core.config import ConfigFactory
from app.core.exceptions import AuthenticationError
from app.core.local_auth import has_proxy_forwarding_headers, is_loopback_client_ip
from app.core.settings_store import get_live_settings
from app.modules.auth.infrastructure.jwt import verify_access_token


def _is_docs_path(path: str) -> bool:
    return (
        path in ("/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc")
        or path.startswith("/docs/")
        or path.startswith("/redoc/")
    )


def _is_debug_enabled() -> bool:
    try:
        return bool(get_live_settings().debug)
    except RuntimeError:
        return bool(ConfigFactory.global_settings().debug)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._public_routes: set[str] = {
            "/health",
            "/.well-known/jwks.json",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/setup/status",
            "/api/v1/setup/bootstrap",
            "/api/v1/invites/accept",
            "/api/v1/invites/verify",
        }
        self._public_post_only: set[str] = {
            "/api/v1/users",
        }
        self._public_post_patterns: tuple[re.Pattern[str], ...] = (
            re.compile(r"\A/api/v1/webhooks/github/[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z"),
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        client_host = request.client.host if request.client else None
        is_direct_loopback = (
            is_loopback_client_ip(client_host)
            and not has_proxy_forwarding_headers(request.headers)
        )

        if _is_docs_path(path):
            settings = ConfigFactory.global_settings()
            if not _is_debug_enabled() and (
                settings.deployment_profile == "vps" or not is_direct_loopback
            ):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
            return await call_next(request)

        if path == "/metrics" and is_direct_loopback:
            return await call_next(request)

        if path in self._public_routes:
            return await call_next(request)
        if request.method == "POST" and path in self._public_post_only:
            return await call_next(request)
        if request.method == "POST" and any(
            pattern.fullmatch(path) for pattern in self._public_post_patterns
        ):
            ct = request.headers.get("content-type", "")
            if ct and "application/json" not in ct.lower():
                return JSONResponse(
                    status_code=415,
                    content={
                        "error": "Content-Type must be application/json",
                        "error_code": "VALIDATION_ERROR",
                    },
                )
            return await call_next(request)

        if request.method in ("POST", "PUT", "PATCH") and path not in self._public_routes:
            ct = request.headers.get("content-type", "").lower()
            if ct and "application/json" not in ct and "multipart/form-data" not in ct:
                return JSONResponse(
                    status_code=415,
                    content={
                        "error": "Content-Type must be application/json or multipart/form-data",
                        "error_code": "VALIDATION_ERROR",
                    },
                )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            from app.core.local_auth import resolve_local_auto_auth
            from app.core.persistence.db import database

            if database._session_factory is not None:
                client_host = request.client.host if request.client else None
                async with database.session_factory() as db:
                    claims = await resolve_local_auto_auth(client_host, request.headers, db)
                if claims is not None:
                    request.state.user_id = claims["user_id"]
                    request.state.roles = claims["roles"]
                    request.state.permissions = claims["permissions"]
                    request.state.auth_mode = claims.get("auth_mode", "local_zero_login")
                    return await call_next(request)
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Missing or invalid Authorization header",
                    "error_code": "AUTHENTICATION_ERROR",
                },
            )

        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Missing or invalid Authorization header",
                    "error_code": "AUTHENTICATION_ERROR",
                },
            )

        token = auth_header.removeprefix("Bearer ")
        if not token:
            return JSONResponse(
                status_code=401,
                content={"error": "Empty token", "error_code": "AUTHENTICATION_ERROR"},
            )

        if _is_api_key(token):
            from app.core.persistence.db import database

            if database._session_factory is None:
                return JSONResponse(
                    status_code=503,
                    content={
                        "error": "Database not initialized",
                        "error_code": "SERVICE_UNAVAILABLE",
                    },
                )
            async with database.session_factory() as db:
                try:
                    claims = await _resolve_api_key(token, db)
                    request.state.user_id = claims["user_id"]
                    request.state.roles = claims["roles"]
                    request.state.permissions = claims["permissions"]
                    request.state.auth_type = "api_key"
                except AuthenticationError as e:
                    return JSONResponse(
                        status_code=401,
                        content={"error": e.message, "error_code": "AUTHENTICATION_ERROR"},
                    )
                except Exception:
                    return JSONResponse(
                        status_code=401,
                        content={
                            "error": "Authentication failed",
                            "error_code": "AUTHENTICATION_ERROR",
                        },
                    )
        else:
            from app.core.persistence.db import database

            try:
                if database._session_factory is not None:
                    async with database.session_factory() as db:
                        claims = await resolve_bearer_token(token, db)
                    request.state.user_id = claims["user_id"]
                    request.state.roles = claims.get("roles", [])
                    request.state.permissions = claims.get("permissions", [])
                    request.state.denied_permissions = claims.get("denied_permissions", [])
                    request.state.all_servers_access = claims.get("all_servers_access", False)
                else:
                    claims = verify_access_token(token)
                    request.state.user_id = claims["sub"]
                    request.state.roles = claims.get("roles", [])
                    request.state.permissions = claims.get("permissions", [])
            except AuthenticationError as e:
                return JSONResponse(
                    status_code=401,
                    content={"error": e.message, "error_code": "AUTHENTICATION_ERROR"},
                )
            except Exception:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "Invalid or expired token",
                        "error_code": "AUTHENTICATION_ERROR",
                    },
                )

        if path == "/metrics" and not is_admin_or_owner_context(claims):
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Admin or Owner access required for /metrics",
                    "error_code": "PERMISSION_DENIED",
                },
            )

        response = await call_next(request)
        return response
