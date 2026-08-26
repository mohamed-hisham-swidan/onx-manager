"""UPnP Port Forwarding service using aioupnp.

Implements the single-action 'scan and attempt' wizard requirement (Decision 2 & 3)
with bounded SSDP discovery, external IP retrieval, CGNAT/Double-NAT detection,
and auto-fix alternate-port retries on conflict.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from typing import Any

from app.core.identity import IDENTITY
from app.modules.exposure.domain.aggregate import DENY_LIST_PORTS

logger = logging.getLogger(f"{IDENTITY.logger_prefix_new}.exposure.upnp")

_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")
DEFAULT_SSDP_TIMEOUT_SECONDS = 3
MAX_ALTERNATE_PORT_ATTEMPTS = 3


@dataclass(frozen=True)
class UPnPResult:
    success: bool
    external_ip: str | None = None
    external_port: int | None = None
    internal_port: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    fix_hint: str | None = None
    auto_fixed: bool = False


class AsyncUPnPService:
    """Async UPnP service for IGD port discovery and mapping."""

    def __init__(self, timeout: int = DEFAULT_SSDP_TIMEOUT_SECONDS) -> None:
        self._timeout = timeout

    @staticmethod
    def is_private_or_cgnat(ip_str: str) -> bool:
        """Check if an IP is RFC 1918 private, link-local, loopback, or RFC 6598 CGNAT."""
        try:
            addr = ipaddress.ip_address(ip_str.strip())
            return addr.is_private or addr.is_loopback or addr.is_link_local or addr in _CGNAT_NET
        except ValueError:
            return True

    @staticmethod
    def validate_external_port(port: int) -> tuple[bool, str | None, str | None]:
        """Validate that external_port is 1..65535 and not in internal DENY_LIST_PORTS."""
        if port < 1 or port > 65535:
            return False, "INVALID_PORT", "External port must be between 1 and 65535."
        if port in DENY_LIST_PORTS:
            return (
                False,
                "DENY_LIST_VIOLATION",
                f"Port {port} is reserved for internal services and cannot be exposed.",
            )
        return True, None, None

    async def _discover_igd(self) -> Any:
        """Discover UPnP IGD router with bounded timeout."""
        try:
            from aioupnp.upnp import UPnP

            return await asyncio.wait_for(
                UPnP.discover(timeout=self._timeout),
                timeout=float(self._timeout + 1),
            )
        except TimeoutError:
            logger.warning("UPnP SSDP discovery timed out after %ds", self._timeout)
            return None
        except Exception as exc:
            logger.warning("UPnP discovery failed: %s", exc)
            return None

    async def attempt_mapping(
        self,
        internal_port: int,
        requested_external_port: int,
        description: str = "MCS-Manager-Panel",
        protocol: str = "TCP",
    ) -> UPnPResult:
        """Execute single-action discover, validate, and port mapping with auto-fix retry."""
        # 1. Port validation
        valid, err_code, err_msg = self.validate_external_port(requested_external_port)
        if not valid:
            return UPnPResult(
                success=False,
                error_code=err_code,
                error_message=err_msg,
                fix_hint="Choose an unreserved port between 1024 and 65535.",
            )

        # 2. Discover IGD Router
        upnp = await self._discover_igd()
        if upnp is None:
            return UPnPResult(
                success=False,
                error_code="UPNP_UNSUPPORTED",
                error_message="UPnP is disabled or not supported by your local router.",
                fix_hint="Enable UPnP in your router settings or use Cloudflare Tunnel/playit.gg.",
            )

        # 3. Read External IP
        try:
            external_ip = await upnp.get_external_ip()
            if not external_ip:
                raise ValueError("Empty external IP returned by router")
        except Exception as exc:
            logger.warning("Failed to retrieve external IP via UPnP: %s", exc)
            return UPnPResult(
                success=False,
                error_code="UPNP_UNSUPPORTED",
                error_message="Unable to read external WAN IP address from router.",
                fix_hint="Ensure router WAN connection is active and UPnP is enabled.",
            )

        # 4. Check Double-NAT / CGNAT
        if self.is_private_or_cgnat(external_ip):
            logger.warning("Double-NAT/CGNAT detected on external IP %s", external_ip)
            return UPnPResult(
                success=False,
                external_ip=external_ip,
                error_code="DOUBLE_NAT_DETECTED",
                error_message=(
                    "Your router is behind Double-NAT or CGNAT; port forwarding cannot "
                    "reach the public Internet."
                ),
                fix_hint=(
                    "Use Cloudflare Tunnel or playit.gg to expose your panel without a public IP."
                ),
            )

        # 5. Attempt Mapping with Bounded Alternate Port Retry (Auto-Fix)
        lan_address = getattr(upnp, "lan_address", "") or "127.0.0.1"
        target_port = requested_external_port
        auto_fixed = False
        fix_hint = None

        for attempt in range(MAX_ALTERNATE_PORT_ATTEMPTS + 1):
            valid, _, _ = self.validate_external_port(target_port)
            if not valid:
                target_port += 1
                continue

            try:
                await upnp.add_port_mapping(
                    external_port=target_port,
                    protocol=protocol,
                    internal_port=internal_port,
                    lan_address=lan_address,
                    description=description,
                )
                if attempt > 0:
                    auto_fixed = True
                    fix_hint = (
                        f"Port {requested_external_port} was unavailable; automatically mapped "
                        f"to alternate port {target_port}."
                    )
                logger.info(
                    "UPnP mapped %s:%d -> %s:%d (%s)",
                    external_ip,
                    target_port,
                    lan_address,
                    internal_port,
                    protocol,
                )
                return UPnPResult(
                    success=True,
                    external_ip=external_ip,
                    external_port=target_port,
                    internal_port=internal_port,
                    auto_fixed=auto_fixed,
                    fix_hint=fix_hint,
                )
            except Exception as exc:
                logger.warning(
                    "Port mapping attempt %d for port %d failed: %s",
                    attempt + 1,
                    target_port,
                    exc,
                )
                target_port += 1

        return UPnPResult(
            success=False,
            external_ip=external_ip,
            error_code="PORT_CONFLICT",
            error_message=(
                f"Requested port {requested_external_port} and adjacent alternate ports "
                "are already mapped or rejected by router."
            ),
            fix_hint="Specify an alternate external port manually.",
        )

    async def delete_mapping(
        self,
        external_port: int,
        protocol: str = "TCP",
    ) -> bool:
        """Delete UPnP port mapping upon disable or switch."""
        if not external_port:
            return True
        upnp = await self._discover_igd()
        if upnp is None:
            return False
        try:
            await upnp.delete_port_mapping(external_port=external_port, protocol=protocol)
            logger.info("UPnP deleted mapping for port %d (%s)", external_port, protocol)
            return True
        except Exception as exc:
            logger.warning("Failed to delete UPnP port mapping %d: %s", external_port, exc)
            return False
