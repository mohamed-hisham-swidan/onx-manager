import pytest

from app.core.circuit_breaker import CircuitBreaker
from app.core.command_bus import Command, CommandBus, CommandHandler, CommandResult
from app.core.event_bus import DomainEvent, EventBus, EventHandler
from app.core.idempotency import IdempotencyKey, IdempotencyMiddleware, InMemoryIdempotencyStore
from app.core.saga import SagaOrchestrator, SagaStatus, SagaStep


class DeployCommand(Command):
    server_id: str
    version: str


class DeployHandler(CommandHandler[DeployCommand]):
    def __init__(self, event_bus: EventBus) -> None:
        self.event_bus = event_bus

    async def handle(self, command: DeployCommand) -> CommandResult:
        await self.event_bus.publish(
            DomainEvent(
                event_type="ServerDeployed",
                correlation_id=command.server_id,
            ),
        )
        return CommandResult(success=True, data={"server_id": command.server_id})


class CollectingHandler(EventHandler):
    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def handle(self, event: DomainEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
class TestCommandBusAndEventBus:
    async def test_command_publishes_event(self) -> None:
        bus = CommandBus()
        event_bus = EventBus()
        collector = CollectingHandler()
        event_bus.subscribe("ServerDeployed", collector)

        handler = DeployHandler(event_bus)
        bus.register(DeployCommand, handler)

        result = await bus.send(DeployCommand(server_id="srv-1", version="1.0"))

        assert result.success is True
        assert result.data["server_id"] == "srv-1"
        assert len(collector.events) == 1
        assert collector.events[0].event_type == "ServerDeployed"


@pytest.mark.asyncio
class TestCommandBusWithIdempotency:
    async def test_idempotency_middleware_prevents_duplicates(self) -> None:
        bus = CommandBus()
        store = InMemoryIdempotencyStore()

        bus.add_middleware(IdempotencyMiddleware(store))

        class TestCmd(Command):
            idempotency_key: IdempotencyKey = IdempotencyKey("unique-key")
            value: str

        class TestHandler(CommandHandler[TestCmd]):
            call_count = 0

            async def handle(self, command: TestCmd) -> CommandResult:
                self.call_count += 1
                return CommandResult(success=True, data={"count": self.call_count})

        handler = TestHandler()
        bus.register(TestCmd, handler)

        cmd = TestCmd(value="first")
        r1 = await bus.send(cmd)
        assert r1.success is True
        assert r1.data["count"] == 1

        r2 = await bus.send(cmd)
        assert r2.success is True
        assert r2.data["count"] == 1

        assert handler.call_count == 1


@pytest.mark.asyncio
class TestSagaAndCircuitBreaker:
    async def test_saga_with_circuit_breaker_step(self) -> None:
        orchestrator = SagaOrchestrator()
        cb = CircuitBreaker("saga-step", max_failures=1, timeout_seconds=0.1)

        async def risky_operation() -> None:
            async def fail() -> None:
                raise RuntimeError("transient error")

            try:
                await cb.call(fail())
            except Exception:
                raise

        execution: list[str] = []
        compensation: list[str] = []

        steps = [
            SagaStep(
                name="prepare",
                forward=lambda: execution.append("prepared"),
                compensate=lambda: compensation.append("rollback_prepare"),
            ),
            SagaStep(
                name="risky",
                forward=risky_operation,
                compensate=lambda: compensation.append("rollback_risky"),
            ),
        ]

        instance = await orchestrator.create_saga("mixed", steps)
        result = await orchestrator.execute(instance.saga_id)

        assert result.status == SagaStatus.COMPENSATED
        assert execution == ["prepared"]
        assert "rollback_prepare" in compensation


@pytest.mark.asyncio
class TestFullPipeline:
    async def test_command_through_middleware_to_event(self) -> None:
        bus = CommandBus()
        event_bus = EventBus()
        idem_store = InMemoryIdempotencyStore()
        collector = CollectingHandler()

        bus.add_middleware(IdempotencyMiddleware(idem_store))
        event_bus.subscribe("ItemCreated", collector)

        class CreateItem(Command):
            idempotency_key: IdempotencyKey = IdempotencyKey("create-item-1")
            name: str

        class CreateItemHandler(CommandHandler[CreateItem]):
            def __init__(self, eb: EventBus) -> None:
                self.eb = eb

            async def handle(self, command: CreateItem) -> CommandResult:
                await self.eb.publish(
                    DomainEvent(
                        event_type="ItemCreated",
                        correlation_id=str(command.idempotency_key),
                    ),
                )
                return CommandResult(success=True, data={"name": command.name})

        bus.register(CreateItem, CreateItemHandler(event_bus))

        result = await bus.send(CreateItem(name="test-item"))

        assert result.success is True
        assert result.data["name"] == "test-item"
        assert len(collector.events) == 1
        assert collector.events[0].event_type == "ItemCreated"

        result2 = await bus.send(CreateItem(name="test-item"))
        assert result2.success is True
        assert len(collector.events) == 1
