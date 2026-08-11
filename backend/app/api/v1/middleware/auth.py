from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.auth_utils import _is_api_key, _resolve_api_key
from app.modules.auth.infrastructure.jwt import verify_access_token


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._public_routes: set[str] = {
            "/health",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/.well-known/jwks.json",
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/setup/status",
            "/api/v1/setup/bootstrap",
            "/api/v1/invites/accept",
        }
        self._public_prefixes: set[str] = {
            "/api/v1/schedules",
            "/api/v1/invites/verify",
        }
        self._public_post_only: set[str] = {
            "/api/v1/users",
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path in self._public_routes:
            return await call_next(request)
        if any(path.startswith(r) for r in ("/docs", "/openapi.json", "/redoc")):
            return await call_next(request)
        if any(path.startswith(prefix) for prefix in self._public_prefixes):
            return await call_next(request)
        if request.method == "POST" and path in self._public_post_only:
            return await call_next(request)

        if request.method in ("POST", "PUT", "PATCH") and path not in self._public_routes:
            ct = request.headers.get("content-type", "")
            if ct and "application/json" not in ct and "multipart/form-data" not in ct:
                return JSONResponse(
                    status_code=415,
                    content={"error": "Content-Type must be application/json or multipart/form-data", "error_code": "VALIDATION_ERROR"},
                )

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or invalid Authorization header", "error_code": "AUTHENTICATION_ERROR"},
            )

        token = auth_header.removeprefix("Bearer ")
        if not token:
            return JSONResponse(
                status_code=401,
                content={"error": "Empty token", "error_code": "AUTHENTICATION_ERROR"},
            )

        if _is_api_key(token):
            from app.core.persistence.db import database

            async with database.session_factory() as db:
                try:
                    claims = await _resolve_api_key(token, db)
                    request.state.user_id = claims["user_id"]
                    request.state.roles = claims["roles"]
                    request.state.permissions = claims["permissions"]
                except Exception as e:
                    return JSONResponse(
                        status_code=401,
                        content={"error": str(e), "error_code": "AUTHENTICATION_ERROR"},
                    )
        else:
            try:
                claims = verify_access_token(token)
                request.state.user_id = claims["sub"]
                request.state.roles = claims.get("roles", [])
                request.state.permissions = claims.get("permissions", [])
            except Exception as e:
                return JSONResponse(
                    status_code=401,
                    content={"error": str(e), "error_code": "AUTHENTICATION_ERROR"},
                )

        response = await call_next(request)
        return response
