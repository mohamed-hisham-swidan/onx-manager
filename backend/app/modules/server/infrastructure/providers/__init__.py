from app.modules.server.infrastructure.fs import local_fs
from app.modules.server.infrastructure.providers.base import (
    DeploymentResult,
    ProviderFactory,
    ServerHandle,
    ServerProvider,
    ServerRuntimeStatus,
    get_dynamic_local_ip,
    provider_factory,
)
from app.modules.server.infrastructure.providers.circuit_breaker_wrapper import (
    CircuitBreakerProviderWrapper,
)
from app.modules.server.infrastructure.providers.cloud import CloudProvider, CloudProviderStub
from app.modules.server.infrastructure.providers.docker import DockerProvider
from app.modules.server.infrastructure.providers.local import LocalLinuxProvider
from app.modules.server.infrastructure.providers.local_windows import LocalWindowsProvider
from app.modules.server.infrastructure.providers.remote import SSHProvider

provider_factory.register(LocalLinuxProvider(fs=local_fs))
provider_factory.register(LocalWindowsProvider())
provider_factory.register(DockerProvider())

__all__ = [
    "ServerProvider",
    "ServerHandle",
    "DeploymentResult",
    "ServerRuntimeStatus",
    "get_dynamic_local_ip",
    "ProviderFactory",
    "provider_factory",
    "LocalLinuxProvider",
    "LocalWindowsProvider",
    "DockerProvider",
    "SSHProvider",
    "CloudProvider",
    "CloudProviderStub",
    "CircuitBreakerProviderWrapper",
]
