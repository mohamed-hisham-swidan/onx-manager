import pytest
from pydantic import BaseModel

from app.core.command_bus import Command, CommandBus, CommandHandler, CommandResult, Middleware


class TestCommand(Command):
    value: str


class TestCommandHandler(CommandHandler[TestCommand]):
    async def handle(self, command: TestCommand) -> CommandResult:
        return CommandResult(success=True, data={"echo": command.value})


class TestMiddleware(Middleware):
    def __init__(self) -> None:
        self.called = False

    async def __call__(self, command: Command, next_middleware: CommandResult) -> CommandResult:
        self.called = True
        result = await next_middleware(command)
        result.data["middleware"] = True
        return result


@pytest.mark.asyncio
class TestCommandBus:
    async def test_register_and_send(self, command_bus: CommandBus) -> None:
        handler = TestCommandHandler()
        command_bus.register(TestCommand, handler)
        result = await command_bus.send(TestCommand(value="hello"))
        assert result.success is True
        assert result.data["echo"] == "hello"

    async def test_no_handler_returns_error(self, command_bus: CommandBus) -> None:
        result = await command_bus.send(TestCommand(value="x"))
        assert result.success is False
        assert result.error_code == "HANDLER_NOT_FOUND"

    async def test_middleware_pipeline(self, command_bus: CommandBus) -> None:
        handler = TestCommandHandler()
        middleware = TestMiddleware()
        command_bus.register(TestCommand, handler)
        command_bus.add_middleware(middleware)

        result = await command_bus.send(TestCommand(value="test"))
        assert result.success is True
        assert result.data["middleware"] is True
        assert middleware.called is True

    async def test_multiple_middleware_execute_in_order(self, command_bus: CommandBus) -> None:
        order: list[str] = []

        class M1(Middleware):
            async def __call__(self, cmd: Command, nxt: CommandResult) -> CommandResult:
                order.append("m1_before")
                r = await nxt(cmd)
                order.append("m1_after")
                return r

        class M2(Middleware):
            async def __call__(self, cmd: Command, nxt: CommandResult) -> CommandResult:
                order.append("m2_before")
                r = await nxt(cmd)
                order.append("m2_after")
                return r

        handler = TestCommandHandler()
        command_bus.register(TestCommand, handler)
        command_bus.add_middleware(M1())
        command_bus.add_middleware(M2())

        await command_bus.send(TestCommand(value="order"))
        assert order == ["m1_before", "m2_before", "m2_after", "m1_after"]

    async def test_result_fields(self, command_bus: CommandBus) -> None:
        handler = TestCommandHandler()
        command_bus.register(TestCommand, handler)
        result = await command_bus.send(TestCommand(value="x"))
        assert isinstance(result, CommandResult)
        assert result.error is None
        assert result.error_code is None
