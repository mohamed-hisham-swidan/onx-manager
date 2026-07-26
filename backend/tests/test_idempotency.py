import pytest

from app.core.command_bus import CommandResult
from app.core.idempotency import IdempotencyKey, InMemoryIdempotencyStore


@pytest.mark.asyncio
class TestIdempotencyKey:
    def test_generates_unique_keys(self) -> None:
        k1 = IdempotencyKey()
        k2 = IdempotencyKey()
        assert k1.value != k2.value

    def test_equality(self) -> None:
        k1 = IdempotencyKey("same")
        k2 = IdempotencyKey("same")
        assert k1 == k2

    def test_hashable(self) -> None:
        k = IdempotencyKey("key-1")
        s = {k, IdempotencyKey("key-1")}
        assert len(s) == 1

    def test_string_representation(self) -> None:
        k = IdempotencyKey("my-key")
        assert str(k) == "my-key"


@pytest.mark.asyncio
class TestInMemoryIdempotencyStore:
    async def test_not_duplicate_on_first_call(self, idempotency_store: InMemoryIdempotencyStore) -> None:
        result = await idempotency_store.is_duplicate("key-1")
        assert result is False

    async def test_detects_duplicate_after_mark(self, idempotency_store: InMemoryIdempotencyStore) -> None:
        await idempotency_store.mark_completed("key-1", CommandResult(success=True, data={"done": True}))
        assert await idempotency_store.is_duplicate("key-1") is True

    async def test_get_result_returns_cached(self, idempotency_store: InMemoryIdempotencyStore) -> None:
        original = CommandResult(success=True, data={"result": 42})
        await idempotency_store.mark_completed("key-1", original)
        cached = await idempotency_store.get_result("key-1")
        assert cached is not None
        assert cached.success is True
        assert cached.data["result"] == 42

    async def test_get_result_none_for_missing(self, idempotency_store: InMemoryIdempotencyStore) -> None:
        result = await idempotency_store.get_result("missing")
        assert result is None

    async def test_expiry(self) -> None:
        store = InMemoryIdempotencyStore(ttl_hours=0)
        await store.mark_completed("expired", CommandResult(success=True))
        assert await store.is_duplicate("expired") is False

    async def test_multiple_keys_independent(self, idempotency_store: InMemoryIdempotencyStore) -> None:
        await idempotency_store.mark_completed("a", CommandResult(success=True, data={"x": 1}))
        await idempotency_store.mark_completed("b", CommandResult(success=True, data={"x": 2}))
        assert (await idempotency_store.get_result("a")).data["x"] == 1
        assert (await idempotency_store.get_result("b")).data["x"] == 2
