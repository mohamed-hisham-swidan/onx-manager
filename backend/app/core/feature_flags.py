from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class FlagDefinition:
    key: str
    enabled: bool = False
    percentage: int = 0
    user_overrides: dict[str, bool] = field(default_factory=dict)
    description: str = ""
    updated_at: float = 0.0


class FlagStorage(ABC):
    @abstractmethod
    async def get_flag(self, key: str) -> FlagDefinition | None: ...

    @abstractmethod
    async def set_flag(self, flag: FlagDefinition) -> None: ...

    @abstractmethod
    async def list_flags(self) -> list[FlagDefinition]: ...

    @abstractmethod
    async def delete_flag(self, key: str) -> None: ...


class InMemoryFlagStorage(FlagStorage):
    def __init__(self) -> None:
        self._flags: dict[str, FlagDefinition] = {}

    async def get_flag(self, key: str) -> FlagDefinition | None:
        return self._flags.get(key)

    async def set_flag(self, flag: FlagDefinition) -> None:
        flag.updated_at = time.time()
        self._flags[flag.key] = flag

    async def list_flags(self) -> list[FlagDefinition]:
        return list(self._flags.values())

    async def delete_flag(self, key: str) -> None:
        self._flags.pop(key, None)


class FeatureFlagRegistry:
    def __init__(self, storage: FlagStorage | None = None) -> None:
        self._storage = storage or InMemoryFlagStorage()

    async def is_enabled(
        self,
        flag: str,
        user_id: str | None = None,
        *,
        fallback: bool = False,
    ) -> bool:
        definition = await self._storage.get_flag(flag)
        if definition is None:
            return fallback

        if not definition.enabled:
            return False

        if user_id and user_id in definition.user_overrides:
            return definition.user_overrides[user_id]

        if user_id and definition.percentage > 0:
            if definition.percentage >= 100:
                return True
            hash_input = f"{flag}:{user_id}"
            hash_val = int(hashlib.md5(hash_input.encode()).hexdigest()[:8], 16)
            return (hash_val % 100) < definition.percentage

        return definition.enabled

    async def enable(self, flag: str) -> None:
        definition = await self._storage.get_flag(flag)
        if definition is None:
            definition = FlagDefinition(key=flag)
        definition.enabled = True
        await self._storage.set_flag(definition)

    async def disable(self, flag: str) -> None:
        definition = await self._storage.get_flag(flag)
        if definition is None:
            return
        definition.enabled = False
        await self._storage.set_flag(definition)

    async def set_percentage(self, flag: str, percentage: int) -> None:
        percentage = max(0, min(100, percentage))
        definition = await self._storage.get_flag(flag)
        if definition is None:
            definition = FlagDefinition(key=flag)
        definition.percentage = percentage
        await self._storage.set_flag(definition)

    async def set_user_override(
        self,
        flag: str,
        user_id: str,
        enabled: bool,
    ) -> None:
        definition = await self._storage.get_flag(flag)
        if definition is None:
            definition = FlagDefinition(key=flag)
        definition.user_overrides[user_id] = enabled
        await self._storage.set_flag(definition)

    async def list_flags(self) -> list[FlagDefinition]:
        return await self._storage.list_flags()

    async def register(self, key: str, description: str = "") -> None:
        existing = await self._storage.get_flag(key)
        if existing is None:
            await self._storage.set_flag(
                FlagDefinition(key=key, description=description),
            )
