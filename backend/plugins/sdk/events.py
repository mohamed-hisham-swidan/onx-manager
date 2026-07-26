from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def on_event(event_name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        func._plugin_event = event_name
        return func

    return decorator


class _EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def subscribe(self, event: str, handler: Callable[..., Any]) -> None:
        if event not in self._handlers:
            self._handlers[event] = []
        self._handlers[event].append(handler)

    async def dispatch(self, event: str, payload: dict[str, Any]) -> list[Any]:
        results: list[Any] = []
        handlers = self._handlers.get(event, [])
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    result = await result
                results.append(result)
            except Exception as e:
                logger.error("Event handler error for %s: %s", event, str(e))
                results.append(None)
        return results

    def register_handlers(self, plugin: Any) -> None:
        for attr_name in dir(plugin):
            attr = getattr(plugin, attr_name)
            if hasattr(attr, "_plugin_event"):
                self.subscribe(attr._plugin_event, attr)


async def _stdin_listener(stream: Any, handler: Callable[[str], Any]) -> None:
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, stream)

    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=0.5)
            if not line:
                break
            raw = line.decode("utf-8").strip()
            if raw:
                await handler(raw)
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            logger.error("stdin listener error: %s", str(e))
            break
