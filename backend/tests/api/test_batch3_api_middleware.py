import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request
from starlette.responses import Response

from app.api.errors import _error_response
from app.api.v1.middleware.auth import AuthMiddleware
from app.api.v1.middleware.request_id import RequestIDMiddleware
from app.api.v1.routers.auth import revoke_api_key
from app.api.v1.routers.exposure import delete_server_port, remove_server_exposure
from app.api.v1.schemas.common import ErrorResponse, PaginatedResponse
from app.core.command_bus import CommandBus, CommandResult
from app.core.exceptions import MCSError
from app.main import app
from app.modules.auth.application.commands.revoke_api_key import (
    RevokeApiKeyCommand,
    RevokeApiKeyHandler,
)
from app.modules.auth.domain.aggregate import ApiKey
from app.modules.auth.domain.events import ApiKeyRevokedEvent
from app.modules.shared.value_objects import ApiKeyId


# --- F045: ApiKey revocation domain event ---
def test_f045_api_key_revoke_emits_event():
    key = ApiKey(
        api_key_id=ApiKeyId("key-123"),
        name="test-key",
        prefix="onx_",
    )
    assert not key.is_revoked
    key.collect_events()

    key.revoke("user-123")
    assert key.is_revoked

    events = key.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], ApiKeyRevokedEvent)
    assert events[0].user_id == "user-123"
    assert events[0].key_name == "test-key"


# --- F051: CORS middleware outermost ---
@pytest.mark.asyncio
async def test_f051_cors_middleware_outermost():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Unauthorized request with Origin header should still get CORS response headers
        response = await client.get(
            "/api/v1/servers",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 401
        assert "access-control-allow-origin" in response.headers
        assert response.headers["access-control-allow-origin"] in ("*", "http://localhost:5173")
        # Wildcard origin must never include credentials header
        assert response.headers.get("access-control-allow-credentials") is None


# --- F052: Preflight OPTIONS bypasses auth ---
@pytest.mark.asyncio
async def test_f052_options_preflight_bypasses_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.options(
            "/api/v1/servers",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # Preflight must NOT return 401
        assert response.status_code != 401
        assert "access-control-allow-origin" in response.headers


# --- F053: Schedules endpoint requires authentication at gateway ---
@pytest.mark.asyncio
async def test_f053_schedules_requires_auth():
    # Assert /api/v1/schedules is NOT in public prefixes
    auth_mw = AuthMiddleware(app=MagicMock())
    assert "/api/v1/schedules" not in auth_mw._public_prefixes

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Direct unauthenticated request rejected with 401
        response = await client.get("/api/v1/schedules")
        assert response.status_code == 401


# --- F054: Error response envelope ---
def test_f054_error_response_envelope():
    response = _error_response(
        status=400,
        error="Bad Request",
        code="INVALID_PAYLOAD",
        detail="Invalid payload",
    )
    body = json.loads(response.body)

    # Contract fields
    assert body["code"] == "INVALID_PAYLOAD"
    assert body["message"] == "Bad Request"
    assert body["details"] == "Invalid payload"
    assert "request_id" in body
    assert body["retryable"] is False

    # Legacy fields
    assert body["error"] == "Bad Request"
    assert body["error_code"] == "INVALID_PAYLOAD"
    assert body["detail"] == "Invalid payload"
    assert "timestamp" in body


# --- F055: RequestIDMiddleware assigns request.state.request_id ---
@pytest.mark.asyncio
async def test_f055_request_id_middleware_state():
    captured_state_id = None

    async def mock_call_next(request: Request) -> Response:
        nonlocal captured_state_id
        captured_state_id = getattr(request.state, "request_id", None)
        return Response("ok", status_code=200)

    middleware = RequestIDMiddleware(app=MagicMock())
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "headers": [(b"x-request-id", b"custom-req-id-123")],
    }
    req = Request(scope)
    response = await middleware.dispatch(req, mock_call_next)

    assert response.headers["X-Request-ID"] == "custom-req-id-123"
    assert captured_state_id == "custom-req-id-123"


# --- F056: Common schemas dual-envelope ---
def test_f056_paginated_and_error_response_dual_envelope():
    # PaginatedResponse initialized with items/page_size
    p1 = PaginatedResponse(items=["item1", "item2"], total=10, page=1, page_size=2)
    d1 = p1.model_dump()
    assert d1["items"] == ["item1", "item2"]
    assert d1["data"] == ["item1", "item2"]
    assert d1["page_size"] == 2
    assert d1["per_page"] == 2
    assert d1["total_pages"] == 5

    # PaginatedResponse initialized with data/per_page
    p2 = PaginatedResponse(data=["a"], total=5, page=1, per_page=5, total_pages=1)
    d2 = p2.model_dump()
    assert d2["items"] == ["a"]
    assert d2["data"] == ["a"]
    assert d2["page_size"] == 5
    assert d2["per_page"] == 5

    # ErrorResponse dual envelope
    e1 = ErrorResponse(code="NOT_FOUND", message="Item not found")
    d_e1 = e1.model_dump()
    assert d_e1["error"] == "Item not found"
    assert d_e1["error_code"] == "NOT_FOUND"


# --- F057: Revoke API Key Command result checking ---
@pytest.mark.asyncio
async def test_f057_revoke_api_key_handler_and_router():
    mock_uow = MagicMock()
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    mock_uow.session = MagicMock()

    target_uow = "app.modules.auth.application.commands.revoke_api_key.UnitOfWork"
    target_repo = "app.modules.auth.application.commands.revoke_api_key.SQLUserRepository"
    with (
        patch(target_uow, return_value=mock_uow),
        patch(target_repo) as mock_repo_cls,
    ):
        mock_repo = MagicMock()
        mock_repo.get = AsyncMock(return_value=None)
        mock_repo_cls.return_value = mock_repo

        handler = RevokeApiKeyHandler(MagicMock())
        result = await handler.handle(RevokeApiKeyCommand(user_id="missing", api_key_id="key-1"))
        assert not result.success
        assert result.error_code == "NOT_FOUND"

    # Router check_command_result raises MCSError
    mock_cmd_bus = MagicMock(spec=CommandBus)
    mock_cmd_bus.send = AsyncMock(
        return_value=CommandResult(
            success=False, error="Key not found", error_code="NOT_FOUND"
        )
    )

    with pytest.raises(MCSError) as exc_info:
        await revoke_api_key(
            api_key_id="key-1",
            command_bus=mock_cmd_bus,
            current_user={"user_id": "u1"},
        )
    assert exc_info.value.http_status == 404


# --- F058: Exposure Router checks command results ---
@pytest.mark.asyncio
async def test_f058_exposure_router_checks_command_results():
    mock_cmd_bus = MagicMock(spec=CommandBus)
    mock_cmd_bus.send = AsyncMock(
        return_value=CommandResult(
            success=False, error="Exposure not found", error_code="NOT_FOUND"
        )
    )

    with pytest.raises(MCSError) as exc_info:
        await remove_server_exposure(
            server_id="s1",
            command_bus=mock_cmd_bus,
            current_user={"user_id": "u1"},
        )
    assert exc_info.value.http_status == 404

    mock_cmd_bus.send = AsyncMock(
        return_value=CommandResult(success=False, error="Port conflict", error_code="CONFLICT")
    )
    with pytest.raises(MCSError) as exc_info:
        await delete_server_port(
            server_id="s1",
            port_id="p1",
            command_bus=mock_cmd_bus,
            current_user={"user_id": "u1"},
        )
    assert exc_info.value.http_status == 409
