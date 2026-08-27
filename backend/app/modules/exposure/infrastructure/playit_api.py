"""Playit.gg REST API Client (pure infrastructure).

Communicates with https://api.playit.gg using the host agent secret (Authorization: agent-key <secret>).
Strictly decoupled from exposure domain aggregates (PanelExposure, ServerExposure).
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from app.core.http_client import get_http_client
from app.core.identity import IDENTITY

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.exposure.playit.api")

_API_BASE = "https://api.playit.gg"


class PlayitApiError(Exception):
    """Base exception for playit.gg API errors."""


class PlayitAuthError(PlayitApiError):
    """Authentication failure (e.g. invalid/revoked agent secret)."""


class PlayitAllocationFullError(PlayitApiError):
    """Account has reached maximum tunnel/port allocation limits."""


class PlayitRateLimitError(PlayitApiError):
    """Rate limit exceeded (HTTP 429)."""


@dataclass(frozen=True)
class PlayitTunnelDto:
    """Strongly-typed DTO for a playit.gg tunnel."""

    id: str
    name: str
    display_address: str
    port_type: str  # "tcp", "udp", "both"
    local_ip: str
    local_port: int
    is_disabled: bool = False


@dataclass(frozen=True)
class PlayitRundataDto:
    """Strongly-typed DTO for playit.gg agent rundata."""

    agent_id: str
    agent_type: str
    account_status: str
    tunnels: list[PlayitTunnelDto]


class PlayitApiClient:
    """Asynchronous client for interacting with playit.gg control plane API."""

    def __init__(self, base_url: str = _API_BASE) -> None:
        self._base_url = base_url.rstrip("/")

    def _headers(self, secret: str) -> dict[str, str]:
        return {
            "Authorization": f"agent-key {secret.strip()}",
            "User-Agent": "playitd/1.0.10",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        secret: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        client = get_http_client()
        url = f"{self._base_url}{path}"
        headers = self._headers(secret)

        try:
            async with client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body if json_body is not None else {},
            ) as resp:
                if resp.status == 401:
                    err_json = {}
                    with contextlib.suppress(Exception):
                        err_json = await resp.json()
                    raise PlayitAuthError(f"playit.gg auth failed (HTTP 401): {err_json}")

                if resp.status == 429:
                    raise PlayitRateLimitError("playit.gg API rate limit exceeded (HTTP 429)")

                try:
                    payload = await resp.json()
                except Exception as exc:
                    text = await resp.text()
                    raise PlayitApiError(
                        f"Invalid JSON response from playit.gg (HTTP {resp.status}): {text[:200]}"
                    ) from exc

                if resp.status >= 400:
                    err_data = payload.get("data")
                    err_msg = (
                        err_data.get("message") if isinstance(err_data, dict) else str(err_data)
                    )
                    err_type = err_data.get("type") if isinstance(err_data, dict) else ""

                    if resp.status == 400 and (
                        "allocation" in str(err_msg).lower()
                        or "limit" in str(err_msg).lower()
                        or "over_limit" in str(err_type).lower()
                    ):
                        raise PlayitAllocationFullError(
                            f"playit.gg allocation limit reached: {err_msg}"
                        )

                    raise PlayitApiError(
                        f"playit.gg API error (HTTP {resp.status}, type={err_type}): {err_msg}"
                    )

                if payload.get("status") == "error":
                    err_data = payload.get("data", {})
                    raise PlayitApiError(f"playit.gg API returned error: {err_data}")

                return payload
        except (PlayitApiError, PlayitAuthError, PlayitAllocationFullError, PlayitRateLimitError):
            raise
        except Exception as exc:
            raise PlayitApiError(f"Network error communicating with playit.gg: {exc}") from exc

    def _parse_tunnel(self, t: dict[str, Any]) -> PlayitTunnelDto:
        """Parse raw playit tunnel dict into a PlayitTunnelDto."""
        tunnel_id = str(t.get("id") or "")
        name = str(t.get("name") or "")
        display_address = str(t.get("display_address") or t.get("assigned_domain") or "")
        port_type = str(t.get("port_type") or t.get("proto") or "tcp").lower()
        local_ip = str(t.get("local_ip") or t.get("local_addr") or "127.0.0.1")
        local_port = int(t.get("local_port") or t.get("port") or 0)
        is_disabled = bool(t.get("is_disabled", False))

        return PlayitTunnelDto(
            id=tunnel_id,
            name=name,
            display_address=display_address,
            port_type=port_type,
            local_ip=local_ip,
            local_port=local_port,
            is_disabled=is_disabled,
        )

    async def get_rundata(self, secret: str) -> PlayitRundataDto:
        """Fetch runtime metadata and active tunnels for this agent."""
        res = await self._request("POST", "/agents/rundata", secret)
        data = res.get("data", {})

        agent_id = str(data.get("agent_id") or "")
        agent_type = str(data.get("agent_type") or "self-managed")
        account_status = str(data.get("account_status") or "ready")

        raw_tunnels = data.get("tunnels") or []
        tunnels = [self._parse_tunnel(t) for t in raw_tunnels if isinstance(t, dict)]

        return PlayitRundataDto(
            agent_id=agent_id,
            agent_type=agent_type,
            account_status=account_status,
            tunnels=tunnels,
        )

    async def list_tunnels(self, secret: str) -> list[PlayitTunnelDto]:
        """Fetch all tunnels registered on playit.gg."""
        try:
            res = await self._request("POST", "/tunnels/list", secret)
            raw_tunnels = res.get("data", {}).get("tunnels") or []
            return [self._parse_tunnel(t) for t in raw_tunnels if isinstance(t, dict)]
        except Exception:
            # Fallback to get_rundata which also returns tunnels
            rundata = await self.get_rundata(secret)
            return rundata.tunnels

    async def create_tunnel(
        self,
        secret: str,
        name: str,
        local_ip: str,
        local_port: int,
        port_type: str = "tcp",
        tunnel_type: str | None = None,
        port_count: int = 1,
    ) -> PlayitTunnelDto:
        """Request creation of a new tunnel on playit.gg."""
        rundata = await self.get_rundata(secret)
        agent_id = rundata.agent_id

        resolved_tt = tunnel_type
        if not resolved_tt:
            if port_type == "udp" or local_port == 19132:
                resolved_tt = "minecraft-bedrock"
            else:
                resolved_tt = "minecraft-java"

        body: dict[str, Any] = {
            "name": name,
            "tunnel_type": resolved_tt,
            "port_type": port_type,
            "port_count": port_count,
            "origin": {
                "type": "agent",
                "data": {
                    "agent_id": agent_id,
                    "local_ip": local_ip,
                    "local_port": local_port,
                },
            },
            "enabled": True,
            "alloc": None,
        }
        res = await self._request("POST", "/tunnels/create", secret, json_body=body)
        tunnel_data = res.get("data", {})
        if not isinstance(tunnel_data, dict):
            tunnel_data = {"id": str(tunnel_data)}

        # Fetch updated rundata to get full assigned domain and port details
        updated_rundata = await self.get_rundata(secret)
        for t in updated_rundata.tunnels:
            if t.id == tunnel_data.get("id") or (
                t.local_port == local_port and t.port_type == port_type
            ):
                return t

        return self._parse_tunnel(tunnel_data)

    async def delete_tunnel(self, secret: str, tunnel_id: str) -> bool:
        """Best-effort deletion of a tunnel on playit.gg."""
        try:
            await self._request("POST", "/tunnels/delete", secret, json_body={"id": tunnel_id})
            return True
        except Exception as exc:
            logger.warning("Failed to delete remote playit tunnel %s: %s", tunnel_id, exc)
            return False
