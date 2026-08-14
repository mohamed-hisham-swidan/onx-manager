from __future__ import annotations

from app.core.event_bus import DomainEvent


class ServerExposureEnabledEvent(DomainEvent):
    server_id: str
    method: str

    def __init__(self, server_id: str, method: str) -> None:
        super().__init__(server_id=server_id, method=method)


class ServerExposureDisabledEvent(DomainEvent):
    server_id: str

    def __init__(self, server_id: str) -> None:
        super().__init__(server_id=server_id)


class ServerExposureRemovedEvent(DomainEvent):
    server_id: str

    def __init__(self, server_id: str) -> None:
        super().__init__(server_id=server_id)


class AgentClaimGeneratedEvent(DomainEvent):
    pass

    def __init__(self) -> None:
        super().__init__()


class AgentResetEvent(DomainEvent):
    pass

    def __init__(self) -> None:
        super().__init__()


class AgentCredentialsRemovedEvent(DomainEvent):
    pass

    def __init__(self) -> None:
        super().__init__()


class PanelExposureChangedEvent(DomainEvent):
    method: str
    desired_state: str

    def __init__(self, method: str, desired_state: str) -> None:
        super().__init__(method=method, desired_state=desired_state)


class ExposureReconciledEvent(DomainEvent):
    pass

    def __init__(self) -> None:
        super().__init__()
