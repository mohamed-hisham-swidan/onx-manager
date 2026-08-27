from __future__ import annotations

import copy
from typing import Any


class HttpResponse:
    def __init__(
        self, status_code: int, body: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.status_code = status_code
        self.body = body
        self._headers = headers or {}

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.body)


class _TimeoutError(Exception):
    pass


class _DnsError(Exception):
    pass


class _ConnectionError(Exception):
    pass


MAX_RESPONSE_SIZE = 10 * 1024 * 1024


class HttpClient:
    def __init__(self) -> None:
        self._default_timeout = 30

    async def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> HttpResponse:
        return await self._request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> HttpResponse:
        return await self._request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> HttpResponse:
        return await self._request("DELETE", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        import asyncio
        import urllib.error
        import urllib.request

        data = kwargs.get("data")
        headers = copy.copy(kwargs.get("headers", {}))
        timeout = kwargs.get("timeout", self._default_timeout)
        max_size = kwargs.get("max_response_size", MAX_RESPONSE_SIZE)

        if isinstance(data, dict):
            import json

            data = json.dumps(data).encode("utf-8")
            if "Content-Type" not in headers:
                headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        def _fetch() -> HttpResponse:
            try:
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    body = response.read(max_size)
                    if len(body) >= max_size and len(response.read(1)) > 0:
                        raise ValueError(
                            f"Response exceeds maximum size of {max_size} bytes",
                        )
                    return HttpResponse(
                        status_code=response.status,
                        body=body,
                        headers=dict(response.headers),
                    )
            except urllib.error.HTTPError as e:
                body = e.read(max_size)
                return HttpResponse(
                    status_code=e.code,
                    body=body,
                    headers=dict(e.headers),
                )
            except urllib.error.URLError as e:
                reason = str(e.reason) if e.reason else "Unknown error"
                if "timed out" in reason.lower() or "timeout" in reason.lower():
                    raise _TimeoutError(reason) from e
                if "Name or service not known" in reason or "getaddrinfo" in reason.lower():
                    raise _DnsError(reason) from e
                if "Connection refused" in reason or "Connection reset" in reason:
                    raise _ConnectionError(reason) from e
                raise RuntimeError(f"Request failed: {reason}") from e

        return await asyncio.to_thread(_fetch)
