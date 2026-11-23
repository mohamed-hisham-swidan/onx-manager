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
_RFC1918_NETS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
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

    def __init__(
        self,
        timeout: int = DEFAULT_SSDP_TIMEOUT_SECONDS,
        rpc_timeout: float | None = None,
    ) -> None:
        self._timeout = timeout
        self._rpc_timeout = rpc_timeout if rpc_timeout is not None else max(5.0, float(timeout * 2))

    @staticmethod
    def is_private_or_cgnat(ip_str: str) -> bool:
        """Check if an IP is RFC 1918 private, RFC 6598 CGNAT, loopback, link-local, or unspecified.

        Home routers behind ISP Carrier-Grade NAT (100.64.0.0/10) or upstream
        double-NAT (RFC 1918 ranges) report a non-public WAN IP from IGD
        ``GetExternalIPAddress`` even when ``AddPortMapping`` returns HTTP 200.
        """
        try:
            addr = ipaddress.ip_address(ip_str.strip())
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified:
                return True
            if addr.version == 4:
                if addr in _CGNAT_NET:
                    return True
                if any(addr in net for net in _RFC1918_NETS):
                    return True
            return False
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
        description: str = "ONX-Manager-Panel",
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

        rpc_timeout = self._rpc_timeout

        # 3. Read External IP
        try:
            external_ip = await asyncio.wait_for(
                upnp.get_external_ip(), timeout=rpc_timeout
            )
            if not external_ip:
                raise ValueError("Empty external IP returned by router")
        except TimeoutError:
            logger.warning("UPnP get_external_ip timed out after %.1fs", rpc_timeout)
            return UPnPResult(
                success=False,
                error_code="UPNP_TIMEOUT",
                error_message="Timed out waiting for router external WAN IP response.",
                fix_hint="Check router UPnP responsiveness or use Cloudflare Tunnel/playit.gg.",
            )
        except Exception as exc:
            logger.warning("Failed to retrieve external IP via UPnP: %s", exc)
            return UPnPResult(
                success=False,
                error_code="UPNP_UNSUPPORTED",
                error_message="Unable to read external WAN IP address from router.",
                fix_hint="Ensure router WAN connection is active and UPnP is enabled.",
            )

        # 4. Check Double-NAT / CGNAT (ISP WAN IP check)
        if self.is_private_or_cgnat(external_ip):
            logger.warning("CGNAT/Double-NAT detected on external WAN IP %s", external_ip)
            return UPnPResult(
                success=False,
                external_ip=external_ip,
                error_code="CGNAT_DETECTED",
                error_message=(
                    f"ISP CGNAT or Double-NAT detected: router reported non-public WAN IP "
                    f"({external_ip}). Port forwarding cannot reach the public Internet."
                ),
                fix_hint=(
                    f"Detected non-public WAN IP ({external_ip}). Switch to Cloudflare Tunnel "
                    "or playit.gg to expose your panel without router port forwarding."
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
                await asyncio.wait_for(
                    upnp.add_port_mapping(
                        external_port=target_port,
                        protocol=protocol,
                        internal_port=internal_port,
                        lan_address=lan_address,
                        description=description,
                    ),
                    timeout=rpc_timeout,
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
            rpc_timeout = self._rpc_timeout
            await asyncio.wait_for(
                upnp.delete_port_mapping(external_port=external_port, protocol=protocol),
                timeout=rpc_timeout,
            )
            logger.info("UPnP deleted mapping for port %d (%s)", external_port, protocol)
            return True
        except Exception as exc:
            logger.warning("Failed to delete UPnP port mapping %d: %s", external_port, exc)
            return False
