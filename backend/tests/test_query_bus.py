import pytest

from app.core.query_bus import Query, QueryBus, QueryHandler, QueryMiddleware


class TestQuery(Query):
    __test__ = False
    item_id: str


class TestQueryHandler(QueryHandler[TestQuery]):
    __test__ = False
    async def handle(self, query: TestQuery) -> dict:
        return {"id": query.item_id, "name": "test-item"}


class TestQueryMiddleware(QueryMiddleware):
    __test__ = False
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, query: Query, next_middleware: object) -> object:
        self.called = True
        result = await next_middleware(query)
        result["via_middleware"] = True
        return result


@pytest.mark.asyncio
class TestQueryBus:
    async def test_register_and_ask(self, query_bus: QueryBus) -> None:
        handler = TestQueryHandler()
        query_bus.register(TestQuery, handler)
        result = await query_bus.ask(TestQuery(item_id="abc"))
        assert result["id"] == "abc"
        assert result["name"] == "test-item"

    async def test_no_handler_raises_error(self, query_bus: QueryBus) -> None:
        with pytest.raises(Exception) as exc:
            await query_bus.ask(TestQuery(item_id="x"))
        assert exc.value.code == "HANDLER_NOT_FOUND"

    async def test_middleware_execution(self, query_bus: QueryBus) -> None:
        handler = TestQueryHandler()
        mw = TestQueryMiddleware()
        query_bus.register(TestQuery, handler)
        query_bus.add_middleware(mw)

        result = await query_bus.ask(TestQuery(item_id="xyz"))
        assert result["via_middleware"] is True
        assert mw.called is True

    async def test_multiple_middleware_order(self, query_bus: QueryBus) -> None:
        order: list[str] = []

        class M1(QueryMiddleware):
            async def __call__(self, q: Query, nxt: object) -> object:
                order.append("m1")
                return await nxt(q)

        class M2(QueryMiddleware):
            async def __call__(self, q: Query, nxt: object) -> object:
                order.append("m2")
                return await nxt(q)

        query_bus.register(TestQuery, TestQueryHandler())
        query_bus.add_middleware(M1())
        query_bus.add_middleware(M2())

        await query_bus.ask(TestQuery(item_id="1"))
        assert order == ["m1", "m2"]
