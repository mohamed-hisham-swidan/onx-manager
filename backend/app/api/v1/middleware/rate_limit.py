import ipaddress
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _normalize_ip(raw: str | None) -> str:
    if not raw:
        return ""
    cleaned = raw.strip()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError:
        return ""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(addr)


def _configured_trusted_proxies() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw = os.environ.get("ONX_TRUSTED_PROXIES", "") or os.environ.get("MCS_TRUSTED_PROXIES", "")
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in raw.split(","):
        item = part.strip()
        if not item:
            continue
        try:
            nets.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(nets)


_TRUSTED_INTERNAL_NETS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def is_trusted_proxy_ip(ip_str: str) -> bool:
    """Return True if *ip_str* is loopback, private/Docker bridge, or configured trusted proxy."""
    norm = _normalize_ip(ip_str)
    if not norm:
        return False
    addr = ipaddress.ip_address(norm)
    if addr.is_loopback or addr.is_link_local:
        return True
    if any(addr in net for net in _TRUSTED_INTERNAL_NETS):
        return True
    return any(addr in net for net in _configured_trusted_proxies())


def resolve_client_ip(request: Request) -> str:
    """Resolve client IP safely, honoring proxy headers only from trusted proxies."""
    raw_peer = request.client.host if request.client else ""
    peer_ip = _normalize_ip(raw_peer)
    if not peer_ip:
        return raw_peer or "unknown"

    if not is_trusted_proxy_ip(peer_ip):
        # Untrusted public peer: never honor spoofable forwarding headers.
        return peer_ip

    cf_ip = _normalize_ip(request.headers.get("CF-Connecting-IP"))
    if cf_ip:
        return cf_ip

    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        parsed_chain = [ip for part in xff.split(",") if (ip := _normalize_ip(part))]
        for ip in reversed(parsed_chain):
            if not is_trusted_proxy_ip(ip):
                return ip
        if parsed_chain:
            return parsed_chain[0]

    real_ip = _normalize_ip(request.headers.get("X-Real-IP"))
    if real_ip:
        return real_ip

    return peer_ip


class InMemoryRateLimitStore:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = {}
        self._last_cleanup: float = 0.0

    def check(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds
        self._cleanup_if_needed(now, window_seconds)
        if key not in self._hits:
            self._hits[key] = []
        self._hits[key] = [t for t in self._hits[key] if t > window_start]
        if len(self._hits[key]) >= max_requests:
            return False
        self._hits[key].append(now)
        return True

    def _cleanup_if_needed(self, now: float, window_seconds: int) -> None:
        if now - self._last_cleanup < 60:
            return
        self._last_cleanup = now
        cutoff = now - window_seconds
        self._hits = {
            k: [t for t in v if t > cutoff]
            for k, v in self._hits.items()
            if any(t > cutoff for t in v)
        }


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self._store = InMemoryRateLimitStore()
        self._max_requests = max_requests
        self._window_seconds = window_seconds

    def update_max_requests(self, max_requests: int) -> None:
        """Hot-reload: update the rate limit without a restart."""
        self._max_requests = max_requests

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_ip = resolve_client_ip(request)
        key = f"{client_ip}:{request.url.path}"

        max_requests = self._max_requests
        try:
            from app.core.settings_store import get_live_settings

            max_requests = get_live_settings().rate_limit_per_minute
        except RuntimeError:
            pass

        if not self._store.check(key, max_requests, self._window_seconds):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "error_code": "RATE_LIMIT_EXCEEDED",
                    "detail": {"retry_after": self._window_seconds},
                },
                headers={"Retry-After": str(self._window_seconds)},
            )

        return await call_next(request)
