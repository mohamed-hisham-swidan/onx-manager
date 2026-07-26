import asyncio

import pytest

from app.core.event_bus import DomainEvent, EventBus, EventHandler, Priority


class TestEvent(DomainEvent):
    data: str = ""


class CollectingHandler(EventHandler):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def handle(self, event: DomainEvent) -> None:
        self.events.append(event)


class FailingHandler(EventHandler):
    fail_count: int = 0
    call_count: int = 0

    async def handle(self, event: DomainEvent) -> None:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            raise RuntimeError("handler failed")


class SlowHandler(EventHandler):
    async def handle(self, event: DomainEvent) -> None:
        await asyncio.sleep(5)


@pytest.mark.asyncio
class TestEventBus:
    async def test_publish_to_subscriber(self, event_bus: EventBus) -> None:
        handler = CollectingHandler()
        event_bus.subscribe("TestEvent", handler)
        event = TestEvent(data="hello")

        await event_bus.publish(event)

        assert len(handler.events) == 1
        assert handler.events[0].data == "hello"

    async def test_publish_no_subscribers(self, event_bus: EventBus) -> None:
        event = TestEvent(data="orphan")
        await event_bus.publish(event)

    async def test_multiple_subscribers(self, event_bus: EventBus) -> None:
        h1 = CollectingHandler()
        h2 = CollectingHandler()
        event_bus.subscribe("TestEvent", h1)
        event_bus.subscribe("TestEvent", h2)

        await event_bus.publish(TestEvent(data="broadcast"))

        assert len(h1.events) == 1
        assert len(h2.events) == 1

    async def test_event_type_auto_set(self, event_bus: EventBus) -> None:
        handler = CollectingHandler()
        event_bus.subscribe("TestEvent", handler)
        event = TestEvent()
        assert event.event_type == ""

        await event_bus.publish(event)

        assert handler.events[0].event_type == "TestEvent"

    async def test_dead_letter_on_failure(self, event_bus: EventBus) -> None:
        handler = FailingHandler()
        handler.fail_count = 5
        event_bus.subscribe("TestEvent", handler)

        await event_bus.publish(TestEvent(data="fail"))

        assert event_bus.dead_letter_count == 1

    async def test_dead_letter_after_max_retries(self, event_bus: EventBus) -> None:
        handler = FailingHandler()
        handler.fail_count = 10
        event_bus.subscribe("TestEvent", handler)

        await event_bus.publish(TestEvent(data="dlq"))

        assert event_bus.dead_letter_count == 1

    async def test_unsubscribe(self, event_bus: EventBus) -> None:
        handler = CollectingHandler()
        sub = event_bus.subscribe("TestEvent", handler)
        event_bus.unsubscribe(sub)

        await event_bus.publish(TestEvent(data="gone"))

        assert len(handler.events) == 0

    async def test_priority_order(self, event_bus: EventBus) -> None:
        order: list[str] = []

        class OrderedHandler(EventHandler):
            def __init__(self, name: str) -> None:
                self.name = name

            async def handle(self, event: DomainEvent) -> None:
                order.append(self.name)

        event_bus.subscribe("TestEvent", OrderedHandler("low"), priority=Priority.LOW)
        event_bus.subscribe("TestEvent", OrderedHandler("high"), priority=Priority.HIGH)
        event_bus.subscribe("TestEvent", OrderedHandler("critical"), priority=Priority.CRITICAL)

        await event_bus.publish(TestEvent(data="order"))

        assert order[0] == "critical"
        assert order[-1] == "low"
