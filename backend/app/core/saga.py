from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SagaStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class SagaStepStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    name: str
    forward: Callable[[], Any]
    compensate: Callable[[], Any] | None = None
    status: SagaStepStatus = SagaStepStatus.PENDING
    error: str | None = None


@dataclass
class SagaInstance:
    saga_id: str
    saga_type: str
    status: SagaStatus = SagaStatus.PENDING
    current_step: int = 0
    steps: list[SagaStep] = field(default_factory=list)
    started_at: float = 0.0
    timeout_seconds: float = 300.0
    error: str | None = None

    @property
    def is_timed_out(self) -> bool:
        if self.started_at == 0:
            return False
        return time.time() - self.started_at > self.timeout_seconds


class SagaPersistence(ABC):
    @abstractmethod
    async def save(self, instance: SagaInstance) -> None:
        ...

    @abstractmethod
    async def load(self, saga_id: str) -> SagaInstance | None:
        ...

    @abstractmethod
    async def update_status(
        self,
        saga_id: str,
        status: SagaStatus,
        error: str | None = None,
    ) -> None:
        ...


class InMemorySagaPersistence(SagaPersistence):
    def __init__(self) -> None:
        self._store: dict[str, SagaInstance] = {}

    async def save(self, instance: SagaInstance) -> None:
        self._store[instance.saga_id] = instance

    async def load(self, saga_id: str) -> SagaInstance | None:
        return self._store.get(saga_id)

    async def update_status(
        self,
        saga_id: str,
        status: SagaStatus,
        error: str | None = None,
    ) -> None:
        instance = self._store.get(saga_id)
        if instance:
            instance.status = status
            if error:
                instance.error = error


class SagaOrchestrator:
    def __init__(self, persistence: SagaPersistence | None = None) -> None:
        self._persistence = persistence or InMemorySagaPersistence()

    async def create_saga(
        self,
        saga_type: str,
        steps: list[SagaStep],
        timeout_seconds: float = 300.0,
    ) -> SagaInstance:
        instance = SagaInstance(
            saga_id=uuid.uuid4().hex,
            saga_type=saga_type,
            steps=steps,
            timeout_seconds=timeout_seconds,
        )
        await self._persistence.save(instance)
        return instance

    async def execute(self, saga_id: str) -> SagaInstance:
        instance = await self._persistence.load(saga_id)
        if instance is None:
            raise ValueError(f"Saga {saga_id} not found")

        instance.status = SagaStatus.RUNNING
        instance.started_at = time.time()
        await self._persistence.save(instance)

        for i, step in enumerate(instance.steps):
            instance.current_step = i

            if instance.is_timed_out:
                instance.status = SagaStatus.FAILED
                instance.error = "Saga timed out"
                await self._persistence.update_status(
                    saga_id, SagaStatus.FAILED, "Saga timed out",
                )
                return instance

            step.status = SagaStepStatus.EXECUTING
            await self._persistence.save(instance)

            try:
                result = step.forward()
                if hasattr(result, "__await__"):
                    await result
                step.status = SagaStepStatus.COMPLETED
            except Exception as e:
                step.status = SagaStepStatus.FAILED
                step.error = str(e)
                logger.error(
                    "Saga step failed, starting compensation: saga=%s step=%s error=%s",
                    saga_id,
                    step.name,
                    str(e),
                )
                await self._compensate(instance, i)
                return instance

            await self._persistence.save(instance)

        instance.status = SagaStatus.COMPLETED
        await self._persistence.update_status(saga_id, SagaStatus.COMPLETED)
        return instance

    async def _compensate(self, instance: SagaInstance, failed_at: int) -> None:
        instance.status = SagaStatus.COMPENSATING
        await self._persistence.update_status(
            instance.saga_id, SagaStatus.COMPENSATING,
        )

        for i in range(failed_at, -1, -1):
            step = instance.steps[i]
            if step.compensate is None:
                continue
            try:
                result = step.compensate()
                if hasattr(result, "__await__"):
                    await result
                step.status = SagaStepStatus.COMPENSATED
            except Exception as e:
                logger.error(
                    "Compensation step failed: saga=%s step=%s error=%s",
                    instance.saga_id,
                    step.name,
                    str(e),
                )

        instance.status = SagaStatus.COMPENSATED
        await self._persistence.update_status(
            instance.saga_id, SagaStatus.COMPENSATED,
            error=f"Failed at step '{instance.steps[failed_at].name}'",
        )
