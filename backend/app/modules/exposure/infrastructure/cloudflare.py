"""Minimal Cloudflare API client for the Panel Named-Tunnel flow (Batch 7.2a).

Scope is strictly limited to the operations the MCS-created tunnel requires
(Phase-7.2 design §7):
  - create a Named Tunnel (``POST /accounts/{account}/cfd_tunnel``),
  - configure its ingress (``PUT .../cfd_tunnel/{id}/configurations``),
  - create the single tunnel CNAME (``POST /zones/{zone}/dns_records``).

No general DNS/zone/record management is implemented here (Phase 8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.core.http_client import get_http_client

logger = logging.getLogger(__name__)

_API_BASE = "https://api.cloudflare.com/client/v4"

# Cloudflare API error codes that indicate an invalid/revoked token.
_AUTH_ERROR_CODES: frozenset[int] = frozenset(
    {
        10000,  # Authentication error (invalid credentials)
        9109,  # Invalid access token
        10001,  # Expired token
    }
)


class CloudflareError(Exception):
    """Base error for Cloudflare API interactions."""


class CloudflareAuthError(CloudflareError):
    """The API token is invalid/revoked -> maps to RECLAIM_REQUIRED."""


class CloudflareApiError(CloudflareError):
    """Any other Cloudflare API failure."""


@dataclass(frozen=True)
class TunnelProvisionResult:
    tunnel_id: str
    token: str


class CloudflareClient:
    def __init__(self, token: str) -> None:
        self._token = token

    # -- internals ---------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        client = get_http_client()
        url = f"{_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        async with client.request(method, url, headers=headers, **kwargs) as resp:
            body = await resp.json(content_type=None)
            if resp.status in (401, 403):
                raise CloudflareAuthError(
                    f"Cloudflare API rejected the token (HTTP {resp.status})"
                )
            if not body.get("success", True):
                errors = body.get("errors", [])
                codes = {e.get("code") for e in errors if isinstance(e, dict)}
                messages = [
                    e.get("message") for e in errors if isinstance(e, dict) and e.get("message")
                ]
                detail = "; ".join(messages) if messages else str(body.get("errors"))
                if codes & _AUTH_ERROR_CODES:
                    raise CloudflareAuthError(
                        f"Cloudflare API reported an invalid token: {detail}"
                    )
                raise CloudflareApiError(
                    f"Cloudflare API error {path}: {detail or 'unknown error'}"
                )
            if resp.status >= 400:
                raise CloudflareApiError(
                    f"Cloudflare API error {path}: HTTP {resp.status}"
                )
            return body.get("result")

    async def _account_id(self) -> str:
        """Resolve the first account the token can manage (tunnel control plane)."""
        result = await self._request("GET", "/accounts?per_page=1")
        if not result:
            raise CloudflareApiError("Cloudflare API returned no accounts for this token")
        return result[0]["id"]

    async def _zone_id_for_hostname(self, hostname: str) -> str:
        """Find the zone that owns ``hostname`` so the CNAME can be created.

        This is a scoped lookup for the single MCS-created tunnel CNAME, not a
        general DNS management API.
        """
        label = hostname.lower().strip().rstrip(".")
        parts = label.split(".")
        # Try progressively shorter suffixes (zone == registrable domain).
        for i in range(len(parts) - 1):
            candidate = ".".join(parts[i:])
            result = await self._request(
                "GET", "/zones", params={"name": candidate, "per_page": 1}
            )
            if result:
                return result[0]["id"]
        raise CloudflareApiError(
            f"No Cloudflare zone found that can own hostname {hostname!r}"
        )

    # -- tunnel lifecycle --------------------------------------------------

    async def create_named_tunnel(self, name: str) -> TunnelProvisionResult:
        account_id = await self._account_id()
        result = await self._request(
            "POST",
            f"/accounts/{account_id}/cfd_tunnel",
            json={"name": name, "config_src": "cloudflare"},
        )
        tunnel_id = result.get("id")
        token = result.get("token")
        if not tunnel_id or not token:
            raise CloudflareApiError("Cloudflare API did not return a tunnel id/token")
        return TunnelProvisionResult(tunnel_id=tunnel_id, token=token)

    async def configure_ingress(
        self, tunnel_id: str, ingress: list[dict[str, str]]
    ) -> None:
        account_id = await self._account_id()
        await self._request(
            "PUT",
            f"/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations",
            json={"config": {"ingress": ingress}},
        )

    async def create_cname(self, hostname: str, tunnel_id: str) -> str:
        """Create the ONLY DNS write of 7.2a: hostname -> <tunnel_id>.cfargotunnel.com."""
        zone_id = await self._zone_id_for_hostname(hostname)
        result = await self._request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            json={
                "type": "CNAME",
                "name": hostname,
                "content": f"{tunnel_id}.cfargotunnel.com",
                "proxied": True,
            },
        )
        return result.get("id", "")
