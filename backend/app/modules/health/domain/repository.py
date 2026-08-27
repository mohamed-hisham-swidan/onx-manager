from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.modules.health.domain.aggregate import DiagnosticsReport, HealthStatus
from app.modules.health.domain.value_objects import (
    CrashClassification,
    EvidenceBundle,
    HealthTimelineEntry,
)


class HealthRepository(ABC):
    @abstractmethod
    async def get(self, server_id: str) -> HealthStatus | None: ...

    @abstractmethod
    async def save(self, status: HealthStatus) -> None: ...

    @abstractmethod
    async def list_all(self) -> list[HealthStatus]: ...

    @abstractmethod
    async def list_by_classification(self, classification: str) -> list[HealthStatus]: ...

    @abstractmethod
    async def append_timeline(self, entry: HealthTimelineEntry) -> None: ...

    @abstractmethod
    async def get_timeline(
        self,
        server_id: str,
        limit: int = 100,
        since: datetime | None = None,
    ) -> list[HealthTimelineEntry]: ...

    @abstractmethod
    async def get_timeline_by_status(
        self,
        status: str,
        limit: int = 100,
    ) -> list[HealthTimelineEntry]: ...


class DiagnosticsRepository(ABC):
    @abstractmethod
    async def save_evidence(self, bundle: EvidenceBundle) -> None: ...

    @abstractmethod
    async def save_classification(self, classification: CrashClassification) -> None: ...

    @abstractmethod
    async def save_report(self, report: DiagnosticsReport) -> None: ...

    @abstractmethod
    async def get_report(self, report_id: str) -> DiagnosticsReport | None: ...

    @abstractmethod
    async def list_reports(
        self,
        server_id: str,
        limit: int = 50,
    ) -> list[DiagnosticsReport]: ...
