from __future__ import annotations

from abc import ABC, abstractmethod

from app.modules.health.domain.value_objects import (
    CrashClassification,
    EnvironmentReport,
    EvidenceBundle,
    HealthSignal,
    HealthStatusEnum,
    IntegrityReport,
)


class CrashClassifier(ABC):
    @abstractmethod
    async def classify(self, evidence: EvidenceBundle) -> CrashClassification:
        ...


class HealthCalculatorService(ABC):
    @abstractmethod
    async def compute(
        self,
        current_status: HealthStatusEnum,
        signals: list[HealthSignal],
    ) -> tuple[HealthStatusEnum, list[str], float]:
        ...


class IntegrityChecker(ABC):
    @abstractmethod
    async def check(self, server_id: str, scope: str = "full") -> IntegrityReport:
        ...


class EnvironmentScanner(ABC):
    @abstractmethod
    async def scan(self, server_id: str | None = None) -> EnvironmentReport:
        ...
