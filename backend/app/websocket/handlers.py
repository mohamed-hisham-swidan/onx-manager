from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect, status

from app.core.authorization import (
    authorize_server_action,
    database_has_users,
    is_admin_or_owner_context,
    load_user_auth_context,
    load_user_model_with_roles,
)
from app.modules.auth.infrastructure.jwt import verify_access_token
from app.websocket.authentication import WSAuthenticator
from app.websocket.authorization import MAX_CHANNELS_PER_CONNECTION, ChannelAuthorizer
from app.websocket.buffer import OfflineMessageBuffer
from app.websocket.manager import ConnectionRegistry
from app.websocket.rate_limiter import WSRateLimiter
from app.websocket.serializers import MessageSerializer, WSMessage

logger = logging.getLogger(__name__)


class WSConnectionHandler:
    def __init__(
        self,
        registry: ConnectionRegistry,
        authenticator: WSAuthenticator,
        authorizer: ChannelAuthorizer,
        buffer: OfflineMessageBuffer,
        rate_limiter: WSRateLimiter,
    ) -> None:
        self._registry = registry
        self._authenticator = authenticator
        self._authorizer = authorizer
        self._buffer = buffer
        self._rate_limiter = rate_limiter

    async def handle(self, ws: WebSocket, token: str, user_id: str, permissions: set[str]) -> None:
        connection_id = uuid.uuid4().hex

        await self._registry.register(connection_id, ws)
        await self._registry.link_user(user_id, connection_id)
        initial_expires_at = time.time() + 3600
        if token == "local_zero_login" or not token:
            initial_expires_at = time.time() + 86400 * 365
        else:
            try:
                claims = verify_access_token(token)
                if "exp" in claims:
                    initial_expires_at = float(claims["exp"])
            except Exception:
                pass
        self._authenticator.register_connection(connection_id, user_id, token, initial_expires_at)
        self._authorizer.set_permissions(user_id, permissions)

        try:
            await self._send_pending_events(connection_id, user_id)

            while True:
                raw = await ws.receive_text()

                self._authenticator.update_activity(connection_id)

                if not self._rate_limiter.check(connection_id):
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "RATE_LIMITED", "Rate limit exceeded"
                        ).to_dict(),
                    )
                    continue

                try:
                    data = MessageSerializer.deserialize(raw)
                except (ValueError, Exception):
                    err_msg = MessageSerializer.error_message("PARSE_ERROR", "Invalid JSON message")
                    await self._send_json(ws, err_msg.to_dict())
                    continue

                if not isinstance(data, dict):
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "INVALID_PAYLOAD", "Message payload must be a JSON object"
                        ).to_dict(),
                    )
                    continue

                if (
                    self._authenticator.is_token_expired(connection_id)
                    and data.get("type") != "refresh_token"
                ):
                    await self._send_json(ws, MessageSerializer.auth_expired_message().to_dict())
                    continue

                await self._handle_message(ws, connection_id, user_id, data)

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.warning("WS handler error: %s", str(e))
        finally:
            self._authenticator.remove_connection(connection_id)
            await self._registry.deregister(connection_id)

    async def _send_pending_events(self, connection_id: str, user_id: str) -> None:
        pending = self._buffer.get_pending(user_id)
        if not pending:
            return
        # Decision 3 security requirement: drop buffered events whose channels
        # the current token no longer authorizes (permission downgrade).
        authorized_events = [
            m.data
            for m in pending
            if any(self._authorizer.can_subscribe(user_id, ch) for ch in m.channels)
        ]
        ws = await self._registry.get(connection_id)
        if ws is not None and authorized_events:
            msg = MessageSerializer.state_sync_message(authorized_events)
            await self._send_json(ws, msg.to_dict())
        self._buffer.clear(user_id)

    async def _handle_message(
        self, ws: WebSocket, connection_id: str, user_id: str, data: dict[str, Any]
    ) -> None:
        msg_type = data.get("type", "")

        if msg_type == "ping":
            await self._send_json(ws, MessageSerializer.pong_message().to_dict())

        elif msg_type == "subscribe":
            channels = data.get("channels", [])
            if not isinstance(channels, list):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "INVALID_PAYLOAD", "channels must be a list"
                    ).to_dict(),
                )
                return

            live_ctx = self._authorizer.get_user_context(user_id)
            if live_ctx is not None and live_ctx.get("db_resolved"):
                live_ctx = await self._refresh_user_context_from_db(user_id)
            if live_ctx is not None and (
                live_ctx.get("db_error") or not live_ctx.get("is_active", True)
            ):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "PERMISSION_DENIED",
                        "Authorization check failed"
                        if live_ctx.get("db_error")
                        else "User account is inactive or deleted",
                    ).to_dict(),
                )
                if not live_ctx.get("db_error"):
                    await ws.close(
                        code=status.WS_1008_POLICY_VIOLATION, reason="Account disabled"
                    )
                return

            current_subs = await self._registry.get_subscriptions(connection_id)
            if len(current_subs) + len(channels) > MAX_CHANNELS_PER_CONNECTION:
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "CHANNEL_LIMIT", "Maximum 50 channel subscriptions"
                    ).to_dict(),
                )
                return

            for channel in channels:
                if not isinstance(channel, str) or not self._authorizer.validate_channel(channel):
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "INVALID_CHANNEL", f"Invalid channel: {channel}"
                        ).to_dict(),
                    )
                    continue
                if not self._authorizer.can_subscribe(
                    user_id, channel
                ) or not await self._can_subscribe_resource_from_db(
                    user_id, channel, live_ctx
                ):
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "PERMISSION_DENIED", f"Not authorized for channel: {channel}"
                        ).to_dict(),
                    )
                    continue
                await self._registry.subscribe(connection_id, channel)
                # Decision 3: record persistent user↔channel binding so that
                # offline buffering remains possible after disconnect.
                await self._registry.bind_user_channel(user_id, channel)

        elif msg_type == "unsubscribe":
            channels = data.get("channels", [])
            if not isinstance(channels, list):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "INVALID_PAYLOAD", "channels must be a list"
                    ).to_dict(),
                )
                return
            for channel in channels:
                await self._registry.unsubscribe(connection_id, channel)
                # Decision 3: mirror removal so an explicitly-left channel is
                # never buffered for this user while offline.
                await self._registry.unbind_user_channel(user_id, channel)

        elif msg_type == "refresh_token":
            new_token = data.get("token", "")
            if not new_token:
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "INVALID_PAYLOAD", "token is required"
                    ).to_dict(),
                )
                return
            try:
                claims = verify_access_token(new_token)
            except Exception as e:
                await self._send_json(
                    ws,
                    MessageSerializer.error_message("INVALID_TOKEN", str(e)).to_dict(),
                )
                return

            token_sub = str(claims.get("sub", ""))
            if token_sub != user_id or (data.get("sub") and str(data.get("sub")) != user_id):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "FORBIDDEN", "Token subject mismatch"
                    ).to_dict(),
                )
                return

            new_permissions = set(claims.get("permissions", []))
            self._authorizer.set_permissions(user_id, new_permissions)
            live_ctx = await self._refresh_user_context_from_db(
                user_id, fallback_permissions=new_permissions
            )
            if live_ctx is not None and (
                live_ctx.get("db_error") or not live_ctx.get("is_active", True)
            ):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "PERMISSION_DENIED",
                        "Authorization check failed"
                        if live_ctx.get("db_error")
                        else "User account is inactive or deleted",
                    ).to_dict(),
                )
                if not live_ctx.get("db_error"):
                    await ws.close(
                        code=status.WS_1008_POLICY_VIOLATION, reason="Account disabled"
                    )
                return
            expires_at = float(claims.get("exp", time.time() + 3600))
            self._authenticator.refresh_token(connection_id, new_token, expires_at)

        elif msg_type == "exec_input":
            target_type = str(data.get("target_type", "server"))
            target_id = str(data.get("target_id", ""))
            input_data = str(data.get("input", ""))
            if not target_id:
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "INVALID_PAYLOAD", "target_id is required"
                    ).to_dict(),
                )
                return

            live_ctx = self._authorizer.get_user_context(user_id)
            if live_ctx is not None and live_ctx.get("db_resolved"):
                live_ctx = await self._refresh_user_context_from_db(user_id)
            if live_ctx is not None and (
                live_ctx.get("db_error") or not live_ctx.get("is_active", True)
            ):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "PERMISSION_DENIED",
                        "Authorization check failed"
                        if live_ctx.get("db_error")
                        else "User account is inactive or deleted",
                    ).to_dict(),
                )
                return
            permissions = self._authorizer.get_permissions(user_id)
            is_admin = (
                is_admin_or_owner_context(live_ctx)
                if live_ctx is not None
                else ("admin:full" in permissions)
            )

            if target_type == "test":
                from sqlalchemy import select

                from app.core.persistence.db import database
                from app.modules.server.infrastructure.providers import (
                    ServerHandle,
                    provider_factory,
                )
                from app.modules.versioning.infrastructure.models import ServerTestRunModel

                try:
                    async with database.session_factory() as session:
                        stmt = select(ServerTestRunModel).where(
                            ServerTestRunModel.id == target_id
                        )
                        res = await session.execute(stmt)
                        test_run = res.scalar_one_or_none()
                except Exception as exc:
                    logger.warning(
                        "WS exec_input test lookup failed for %s: %s", target_id, exc
                    )
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "PERMISSION_DENIED",
                            f"Authorization check failed for test run: {target_id}",
                        ).to_dict(),
                    )
                    return

                if not test_run:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "TARGET_NOT_FOUND", f"Test run not found: {target_id}"
                        ).to_dict(),
                    )
                    return

                server_id = test_run.server_id
                if live_ctx is not None and live_ctx.get("db_resolved"):
                    has_perm = authorize_server_action(
                        live_ctx, str(server_id), "console"
                    ) and authorize_server_action(
                        live_ctx, str(server_id), "versioning"
                    )
                else:
                    has_perm = (
                        is_admin
                        or f"server.{server_id}.console" in permissions
                        or "server:test:execute" in permissions
                        or f"server.{server_id}.test:execute" in permissions
                    )
                if not has_perm:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "PERMISSION_DENIED",
                            f"Not authorized to execute commands on test run: {target_id}",
                        ).to_dict(),
                    )
                    return

                container_name = f"onx-test-{target_id}"
                handle = ServerHandle(
                    provider="docker",
                    server_id=server_id,
                    external_id=container_name,
                )
                try:
                    provider = provider_factory.get("docker")
                    output = await provider.write_exec_input(handle, input_data)
                    await self._send_json(
                        ws,
                        MessageSerializer.exec_result_message(
                            target_id=target_id,
                            target_type=target_type,
                            output=output or "",
                            exit_code=0,
                        ).to_dict(),
                    )
                except Exception as exc:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "EXEC_FAILED", f"Failed to execute command on test {target_id}: {exc}"
                        ).to_dict(),
                    )

            elif target_type == "server":
                from app.core.persistence.db import database
                from app.modules.server.domain.value_objects import (
                    default_provider_for_platform,
                )
                from app.modules.server.infrastructure.providers import (
                    ServerHandle,
                    provider_factory,
                )
                from app.modules.server.infrastructure.repository import SQLServerRepository
                from app.modules.shared.value_objects import ServerId

                server_id = target_id
                server = None
                try:
                    async with database.session_factory() as session:
                        repo = SQLServerRepository(session)
                        server = await repo.get(ServerId(server_id))
                except Exception as exc:
                    from app.core.exceptions import ServerNotFoundError

                    if not isinstance(exc, ServerNotFoundError):
                        logger.warning(
                            "WS exec_input server lookup failed for %s: %s", server_id, exc
                        )
                        await self._send_json(
                            ws,
                            MessageSerializer.error_message(
                                "PERMISSION_DENIED",
                                f"Authorization check failed for server: {server_id}",
                            ).to_dict(),
                        )
                        return
                    server = None

                if not server:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "TARGET_NOT_FOUND", f"Server not found: {server_id}"
                        ).to_dict(),
                    )
                    return

                if live_ctx is not None and live_ctx.get("db_resolved"):
                    has_perm = authorize_server_action(
                        live_ctx,
                        str(server_id),
                        "console",
                        server_owner_id=server.owner_id,
                    )
                else:
                    has_perm = (
                        is_admin
                        or f"server.{server_id}.console" in permissions
                        or "server:write" in permissions
                        or f"server.{server_id}.write" in permissions
                    )
                if not has_perm:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "PERMISSION_DENIED",
                            f"Not authorized to execute commands on server: {server_id}",
                        ).to_dict(),
                    )
                    return

                if not server.runtime or not server.runtime.external_id:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "EXEC_FAILED",
                            f"Server {server_id} has no active runtime process",
                        ).to_dict(),
                    )
                    return

                provider_name = server.runtime.provider or default_provider_for_platform()
                handle_meta: dict[str, Any] = {}
                if server.deployment and server.deployment.root_path:
                    handle_meta["server_dir"] = server.deployment.server_directory()
                handle = ServerHandle(
                    provider=provider_name,
                    server_id=server_id,
                    external_id=server.runtime.external_id,
                    metadata=handle_meta,
                )
                try:
                    provider = provider_factory.get(provider_name)
                    output = await provider.write_exec_input(handle, input_data)
                    await self._send_json(
                        ws,
                        MessageSerializer.exec_result_message(
                            target_id=target_id,
                            target_type=target_type,
                            output=output or "",
                            exit_code=0,
                        ).to_dict(),
                    )
                except Exception as exc:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message(
                            "EXEC_FAILED", f"Failed to execute command on server {server_id}: {exc}"
                        ).to_dict(),
                    )

            else:
                await self._send_json(
                    ws,
                    MessageSerializer.error_message(
                        "INVALID_PAYLOAD", f"Unknown target_type: {target_type}"
                    ).to_dict(),
                )

        elif msg_type == "exec_resize":
            cols = data.get("cols", 80)
            rows = data.get("rows", 24)
            await self._send_json(
                ws,
                {"type": "exec_resize_ack", "cols": cols, "rows": rows},
            )

        else:
            await self._send_json(
                ws,
                MessageSerializer.error_message(
                    "UNKNOWN_TYPE", f"Unknown message type: {msg_type}"
                ).to_dict(),
            )

    async def _refresh_user_context_from_db(
        self, user_id: str, *, fallback_permissions: set[str] | None = None
    ) -> dict[str, Any] | None:
        from app.core.persistence.db import database

        if database._session_factory is None:
            return None
        try:
            async with database.session_factory() as db:
                user_model = await load_user_model_with_roles(db, user_id)
                if user_model is None:
                    if await database_has_users(db):
                        self._authorizer.clear_user(user_id)
                        return {"user_id": user_id, "is_active": False, "permissions": []}
                    if fallback_permissions is not None:
                        self._authorizer.set_permissions(user_id, fallback_permissions)
                    return None
                if not user_model.is_active:
                    self._authorizer.clear_user(user_id)
                    return {"user_id": user_id, "is_active": False, "permissions": []}
                live_ctx = await load_user_auth_context(db, user_model)
                self._authorizer.set_user_context(user_id, live_ctx)
                return live_ctx
        except Exception as exc:
            logger.warning(
                "WS DB context refresh failed for user %s: %s", user_id, exc
            )
            err_ctx: dict[str, Any] = {
                "user_id": user_id,
                "is_active": False,
                "db_error": True,
                "permissions": [],
            }
            self._authorizer.set_user_context(user_id, err_ctx)
            return err_ctx

    async def _can_subscribe_resource_from_db(
        self, user_id: str, channel: str, live_ctx: dict[str, Any] | None
    ) -> bool:
        """Verify resource-level server ownership/membership for backup/test/operation channels."""
        if live_ctx is not None and live_ctx.get("db_error"):
            return False
        if live_ctx is None or not live_ctx.get("db_resolved"):
            if self._authorizer.is_empty_db_user(user_id):
                return True
            from app.core.persistence.db import database

            if database._session_factory is not None:
                try:
                    async with database.session_factory() as db:
                        if await database_has_users(db):
                            return False
                except Exception as exc:
                    logger.warning(
                        "WS resource subscribe DB check failed for user %s: %s",
                        user_id,
                        exc,
                    )
                    return False
            return True
        if is_admin_or_owner_context(live_ctx):
            return True
        parts = channel.split(":")
        prefix = parts[0]
        if prefix not in {"backup", "plugin", "test", "operation"}:
            return True

        from sqlalchemy import select

        from app.core.persistence.db import database

        if database._session_factory is None:
            return False

        target_id = parts[1] if len(parts) > 1 else ""
        try:
            async with database.session_factory() as db:
                if prefix == "backup":
                    from app.modules.backup.infrastructure.models import BackupJobModel

                    row = (
                        await db.execute(
                            select(BackupJobModel.server_id).where(BackupJobModel.id == target_id)
                        )
                    ).scalar_one_or_none()
                    if not row:
                        return False
                    return authorize_server_action(live_ctx, str(row), "backups.view")
                if prefix == "plugin":
                    from app.modules.plugin.infrastructure.models import PluginModel

                    row = (
                        await db.execute(
                            select(PluginModel.server_id).where(PluginModel.id == target_id)
                        )
                    ).scalar_one_or_none()
                    if not row:
                        return False
                    return authorize_server_action(live_ctx, str(row), "plugins.view")
                if prefix == "test":
                    from app.modules.versioning.infrastructure.models import ServerTestRunModel

                    row = (
                        await db.execute(
                            select(ServerTestRunModel.server_id).where(
                                ServerTestRunModel.id == target_id
                            )
                        )
                    ).scalar_one_or_none()
                    if not row:
                        return False
                    return authorize_server_action(
                        live_ctx, str(row), "versioning.view"
                    ) and authorize_server_action(live_ctx, str(row), "console.view")
                if prefix == "operation":
                    from app.modules.operations.infrastructure.models import OperationModel

                    row = await db.get(OperationModel, target_id)
                    if row is None or str(row.target_type) != "server" or not row.target_id:
                        return False
                    return authorize_server_action(live_ctx, str(row.target_id), "view")
        except Exception:
            return False
        return True

    async def _send_json(self, ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            msg = WSMessage(
                type=data.get("type", "unknown"),
                data={k: v for k, v in data.items() if k != "type"},
            )
            raw = msg.to_json()
            await ws.send_bytes(raw)
        except Exception:
            pass
