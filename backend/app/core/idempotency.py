from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

from app.core.command_bus import CommandResult


class IdempotencyKey:
    def __init__(self, key: str | None = None) -> None:
        self.value = key or uuid.uuid4().hex

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, IdempotencyKey):
            return self.value == other.value
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.value)

    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: Any) -> Any:
        from pydantic_core.core_schema import no_info_plain_validator_function

        def validate(v: object) -> IdempotencyKey:
            if isinstance(v, IdempotencyKey):
                return v
            if isinstance(v, str):
                return cls(v)
            raise ValueError(f"Expected IdempotencyKey or str, got {type(v)}")

        return no_info_plain_validator_function(validate)


class IdempotencyStore(ABC):
    @abstractmethod
    async def is_duplicate(self, key: str) -> bool: ...

    @abstractmethod
    async def mark_completed(self, key: str, result: CommandResult) -> None: ...

    @abstractmethod
    async def get_result(self, key: str) -> CommandResult | None: ...

    @abstractmethod
    async def reserve(self, key: str) -> bool: ...

    @abstractmethod
    async def release_reservation(self, key: str) -> None: ...

    @abstractmethod
    async def wait_for_result(self, key: str, timeout: float = 30.0) -> CommandResult | None: ...

    @abstractmethod
    async def _init_db(self) -> None: ...


class InMemoryIdempotencyStore(IdempotencyStore):
    def __init__(self, ttl_hours: int = 24) -> None:
        self._store: dict[str, CommandResult] = {}
        self._expiry: dict[str, float] = {}
        self._ttl = ttl_hours * 3600
        self._lock = asyncio.Lock()
        self._in_flight: dict[str, asyncio.Event] = {}

    async def _init_db(self) -> None:
        pass

    async def reserve(self, key: str) -> bool:
        async with self._lock:
            self._evict_expired()
            if key in self._store or key in self._in_flight:
                return False
            self._in_flight[key] = asyncio.Event()
            return True

    async def release_reservation(self, key: str) -> None:
        async with self._lock:
            event = self._in_flight.pop(key, None)
            if event:
                event.set()

    async def wait_for_result(self, key: str, timeout: float = 30.0) -> CommandResult | None:
        event = None
        async with self._lock:
            self._evict_expired()
            if key in self._store:
                return self._store[key]
            event = self._in_flight.get(key)

        if event is not None:
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            except TimeoutError:
                return None

        async with self._lock:
            return self._store.get(key)

    async def is_duplicate(self, key: str) -> bool:
        async with self._lock:
            self._evict_expired()
            return key in self._store

    async def mark_completed(self, key: str, result: CommandResult) -> None:
        async with self._lock:
            self._store[key] = result
            self._expiry[key] = time.time() + self._ttl
            event = self._in_flight.pop(key, None)
            if event:
                event.set()

    async def get_result(self, key: str) -> CommandResult | None:
        async with self._lock:
            self._evict_expired()
            return self._store.get(key)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [k for k, t in self._expiry.items() if t <= now]
        for k in expired:
            del self._store[k]
            del self._expiry[k]


class IdempotencyMiddleware:
    def __init__(self, store: IdempotencyStore) -> None:
        self._store = store

    async def __call__(self, command: Any, next_middleware: Any) -> CommandResult:
        idem_key = getattr(command, "idempotency_key", None)
        if not idem_key:
            return await next_middleware(command)

        key_str = str(idem_key)
        if await self._store.is_duplicate(key_str):
            cached = await self._store.get_result(key_str)
            if cached:
                return CommandResult(
                    success=cached.success,
                    data=cached.data,
                    error=cached.error,
                    error_code=cached.error_code,
                )

        acquired = await self._store.reserve(key_str)
        if not acquired:
            cached = await self._store.wait_for_result(key_str)
            if cached:
                return CommandResult(
                    success=cached.success,
                    data=cached.data,
                    error=cached.error,
                    error_code=cached.error_code,
                )
            if not await self._store.reserve(key_str):
                cached = await self._store.get_result(key_str)
                if cached:
                    return CommandResult(
                        success=cached.success,
                        data=cached.data,
                        error=cached.error,
                        error_code=cached.error_code,
                    )

        try:
            result = await next_middleware(command)
            if result.success:
                await self._store.mark_completed(key_str, result)
            else:
                await self._store.release_reservation(key_str)
            return result
        except Exception:
            await self._store.release_reservation(key_str)
            raise


_default_idempotency_store: InMemoryIdempotencyStore | None = None


def get_idempotency_store() -> InMemoryIdempotencyStore:
    global _default_idempotency_store
    if _default_idempotency_store is None:
        _default_idempotency_store = InMemoryIdempotencyStore()
    return _default_idempotency_store


def reset_idempotency_store() -> None:
    global _default_idempotency_store
    _default_idempotency_store = None
