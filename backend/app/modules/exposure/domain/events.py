from __future__ import annotations

from app.core.event_bus import DomainEvent


class ServerExposureEnabledEvent(DomainEvent):
    server_id: str
    method: str
    branch_name: str | None = None

    def __init__(self, server_id: str, method: str, branch_name: str | None = None) -> None:
        super().__init__(server_id=server_id, method=method, branch_name=branch_name)


class ServerExposureDisabledEvent(DomainEvent):
    server_id: str
    branch_name: str | None = None

    def __init__(self, server_id: str, branch_name: str | None = None) -> None:
        super().__init__(server_id=server_id, branch_name=branch_name)


class ServerExposureRemovedEvent(DomainEvent):
    server_id: str
    branch_name: str | None = None

    def __init__(self, server_id: str, branch_name: str | None = None) -> None:
        super().__init__(server_id=server_id, branch_name=branch_name)


class BranchExposureEnabledEvent(DomainEvent):
    server_id: str
    branch_name: str
    method: str

    def __init__(self, server_id: str, branch_name: str, method: str) -> None:
        super().__init__(server_id=server_id, branch_name=branch_name, method=method)


class BranchExposureDisabledEvent(DomainEvent):
    server_id: str
    branch_name: str

    def __init__(self, server_id: str, branch_name: str) -> None:
        super().__init__(server_id=server_id, branch_name=branch_name)


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
