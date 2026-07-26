import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in MUTATION_METHODS:
            start = time.time()
            response = await call_next(request)
            duration_ms = int((time.time() - start) * 1000)
            logger.info(
                "Audit: method=%s path=%s status=%d duration_ms=%d",
                request.method,
                request.url.path,
                response.status_code,
                duration_ms,
            )
            return response
        return await call_next(request)
