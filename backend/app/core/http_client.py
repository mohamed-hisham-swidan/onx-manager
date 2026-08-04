from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

HTTP_DEFAULT_TIMEOUT_SECONDS: int = 30

_client: aiohttp.ClientSession | None = None


def init_http_client(timeout_seconds: int = HTTP_DEFAULT_TIMEOUT_SECONDS) -> aiohttp.ClientSession:
    """Create the module-level shared ClientSession (idempotent).

    Called from the app lifespan startup, following the same module-level
    singleton pattern as ``init_storage`` / ``init_task_queue``.
    """
    global _client
    if _client is None or _client.closed:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        _client = aiohttp.ClientSession(timeout=timeout)
        logger.info("HTTP client initialized (timeout=%ss)", timeout_seconds)
    return _client


def get_http_client() -> aiohttp.ClientSession:
    """Return the shared session, initializing it on first use if needed."""
    if _client is None or _client.closed:
        return init_http_client()
    return _client


async def close_http_client() -> None:
    """Close the shared session during app shutdown (idempotent)."""
    global _client
    if _client is not None and not _client.closed:
        await _client.close()
        logger.info("HTTP client closed")
    _client = None
