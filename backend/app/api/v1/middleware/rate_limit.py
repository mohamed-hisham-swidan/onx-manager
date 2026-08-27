import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


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
        client_ip = request.client.host if request.client else "unknown"
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
