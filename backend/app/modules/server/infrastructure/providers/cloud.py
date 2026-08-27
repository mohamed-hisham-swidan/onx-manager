from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
)


class CloudProviderType(Enum):
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    DIGITAL_OCEAN = "digital_ocean"
    HETZNER = "hetzner"


@dataclass(frozen=True)
class CloudVMConfig:
    provider: CloudProviderType
    region: str
    instance_type: str
    image: str
    disk_size_gb: int = 20
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CloudVMInstance:
    instance_id: str
    public_ip: str
    private_ip: str
    status: str
    provider: CloudProviderType


class CloudProvider(ServerProvider, ABC):
    @abstractmethod
    async def provision_vm(self, config: CloudVMConfig) -> CloudVMInstance: ...

    @abstractmethod
    async def deprovision_vm(self, instance_id: str) -> None: ...

    @abstractmethod
    async def get_vm_status(self, instance_id: str) -> str: ...

    @abstractmethod
    async def list_vms(self) -> list[CloudVMInstance]: ...

    @property
    def provider_type(self) -> str:
        return "cloud"

    async def ping(self) -> bool:
        return False

    async def start(self, server_id: str, config: dict[str, Any]) -> DeploymentResult:
        raise NotImplementedError("CloudProvider.start requires a provisioned VM")

    async def stop(self, handle: ServerHandle, force: bool = False) -> None:
        raise NotImplementedError("CloudProvider.stop requires a provisioned VM")

    async def status(self, handle: ServerHandle) -> ServerRuntimeStatus:
        return ServerRuntimeStatus.UNKNOWN

    async def console(self, handle: ServerHandle, tail: int = 100) -> list[str]:
        raise NotImplementedError("CloudProvider.console is not available at this layer")

    async def execute_command(self, handle: ServerHandle, command: str) -> str:
        raise NotImplementedError("CloudProvider.execute_command requires an SSH connection")

    async def destroy(self, handle: ServerHandle) -> None:
        raise NotImplementedError("CloudProvider.destroy requires a provisioned VM")


class CloudProviderStub(CloudProvider):
    """A stub implementation of CloudProvider for development/testing.

    Future implementation guidance:
    - AWS: Use boto3 with EC2 APIs
    - GCP: Use google-cloud-compute SDK
    - Azure: Use azure-mgmt-compute SDK
    - DigitalOcean: Use python-digitalocean SDK
    - Each provider needs its own provisioning logic
    """

    async def provision_vm(self, config: CloudVMConfig) -> CloudVMInstance:
        return CloudVMInstance(
            instance_id="stub-instance",
            public_ip="127.0.0.1",
            private_ip="10.0.0.1",
            status="running",
            provider=config.provider,
        )

    async def deprovision_vm(self, instance_id: str) -> None:
        pass

    async def get_vm_status(self, instance_id: str) -> str:
        return "running"

    async def list_vms(self) -> list[CloudVMInstance]:
        return []
