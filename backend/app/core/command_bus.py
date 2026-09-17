from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.exceptions import MCSError

logger = logging.getLogger(__name__)


class Command(BaseModel):
    pass


TCommand = TypeVar("TCommand", bound=Command)


class CommandResult(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    details: dict[str, Any] | None = None
    entity_id: str | None = None

    @property
    def is_success(self) -> bool:
        return self.success


class CommandHandler(ABC, Generic[TCommand]):
    @abstractmethod
    async def handle(self, command: TCommand) -> CommandResult: ...


class Middleware(ABC):
    @abstractmethod
    async def __call__(
        self,
        command: Command,
        next_middleware: Any,
    ) -> CommandResult: ...


class DatabaseBusyRetryMiddleware(Middleware):
    """Middleware that retries commands on transient SQLite database locks."""

    def __init__(self, max_retries: int = 3, initial_delay: float = 0.05) -> None:
        self._max_retries = max_retries
        self._initial_delay = initial_delay

    async def __call__(self, command: Command, next_middleware: Any) -> CommandResult:
        import asyncio

        for attempt in range(self._max_retries):
            try:
                res: CommandResult = await next_middleware(command)
                if not res.success and res.error_code == "UNEXPECTED_ERROR":
                    err_text = (res.error or "").lower()
                    is_lock = "locked" in err_text or "busy" in err_text
                    if is_lock and attempt < self._max_retries - 1:
                        await asyncio.sleep(self._initial_delay * (2**attempt))
                        continue
                return res
            except Exception as exc:
                err_text = str(exc).lower()
                is_lock = "locked" in err_text or "busy" in err_text
                if is_lock and attempt < self._max_retries - 1:
                    await asyncio.sleep(self._initial_delay * (2**attempt))
                    continue
                raise


class CommandBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Command], CommandHandler] = {}
        self._middleware: list[Middleware] = []

    def register(self, command_type: type[Command], handler: CommandHandler) -> None:
        self._handlers[command_type] = handler

    def add_middleware(self, middleware: Middleware) -> None:
        self._middleware.append(middleware)

    async def send(self, command: Command) -> CommandResult:
        handler = self._handlers.get(type(command))
        if handler is None:
            return CommandResult(
                success=False,
                error=f"No handler registered for {type(command).__name__}",
                error_code="HANDLER_NOT_FOUND",
            )

        async def final_handler(cmd: Command) -> CommandResult:
            return await handler.handle(cmd)

        async def chain(cmd: Command, idx: int) -> CommandResult:
            if idx < len(self._middleware):
                return await self._middleware[idx](cmd, lambda c: chain(c, idx + 1))
            return await final_handler(cmd)

        try:
            return await chain(command, 0)
        except MCSError as e:
            return CommandResult(
                success=False,
                error=e.message,
                error_code=e.code,
                details=e.details or None,
            )
        except Exception as e:
            logger.exception("Unhandled command error")
            return CommandResult(
                success=False,
                error=str(e),
                error_code="UNEXPECTED_ERROR",
                details={"exception": type(e).__name__},
            )
