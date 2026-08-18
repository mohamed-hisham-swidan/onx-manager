from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.websocket.authentication import WSAuthenticator
from app.websocket.authorization import ChannelAuthorizer, MAX_CHANNELS_PER_CONNECTION
from app.websocket.buffer import OfflineMessageBuffer
from app.websocket.manager import ConnectionRegistry
from app.websocket.rate_limiter import WSRateLimiter
from app.websocket.serializers import MAX_MESSAGE_SIZE, MessageSerializer, WSMessage

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
        self._authenticator.register_connection(connection_id, user_id, token, time.time() + 3600)
        self._authorizer.set_permissions(user_id, permissions)

        try:
            await self._send_pending_events(connection_id, user_id)

            while True:
                raw = await ws.receive_text()

                self._authenticator.update_activity(connection_id)

                if self._authenticator.is_token_expired(connection_id):
                    await self._send_json(ws, MessageSerializer.auth_expired_message().to_dict())
                    continue

                if not self._rate_limiter.check(connection_id):
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message("RATE_LIMITED", "Rate limit exceeded").to_dict(),
                    )
                    continue

                try:
                    data = MessageSerializer.deserialize(raw)
                except (ValueError, Exception) as e:
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message("PARSE_ERROR", str(e)).to_dict(),
                    )
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

    async def _handle_message(self, ws: WebSocket, connection_id: str, user_id: str, data: dict[str, Any]) -> None:
        msg_type = data.get("type", "")

        if msg_type == "ping":
            await self._send_json(ws, MessageSerializer.pong_message().to_dict())

        elif msg_type == "subscribe":
            channels = data.get("channels", [])
            if not isinstance(channels, list):
                await self._send_json(
                    ws,
                    MessageSerializer.error_message("INVALID_PAYLOAD", "channels must be a list").to_dict(),
                )
                return

            current_subs = await self._registry.get_subscriptions(connection_id)
            if len(current_subs) + len(channels) > MAX_CHANNELS_PER_CONNECTION:
                await self._send_json(
                    ws,
                    MessageSerializer.error_message("CHANNEL_LIMIT", "Maximum 50 channel subscriptions").to_dict(),
                )
                return

            for channel in channels:
                if not self._authorizer.validate_channel(channel):
                    await self._send_json(
                        ws,
                        MessageSerializer.error_message("INVALID_CHANNEL", f"Invalid channel: {channel}").to_dict(),
                    )
                    continue
                if not self._authorizer.can_subscribe(user_id, channel):
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
                    MessageSerializer.error_message("INVALID_PAYLOAD", "channels must be a list").to_dict(),
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
                    MessageSerializer.error_message("INVALID_PAYLOAD", "token is required").to_dict(),
                )
                return
            self._authenticator.refresh_token(connection_id, new_token, time.time() + 3600)

        else:
            await self._send_json(
                ws,
                MessageSerializer.error_message("UNKNOWN_TYPE", f"Unknown message type: {msg_type}").to_dict(),
            )

    async def _send_json(self, ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            msg = WSMessage(type=data.get("type", "unknown"), data={k: v for k, v in data.items() if k != "type"})
            raw = msg.to_json()
            await ws.send_bytes(raw)
        except Exception:
            pass
