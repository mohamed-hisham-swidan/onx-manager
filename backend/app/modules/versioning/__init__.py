"""ONX Manager - Standalone Git/CI-CD-Inspired Versioning & Isolated-Testing Subsystem."""

from app.modules.versioning.domain.deployment import TestServerDeployment
from app.modules.versioning.domain.entities import (
    ServerBranch,
    ServerCommit,
    ServerTestRun,
    ServerWorldSnapshot,
)
from app.modules.versioning.domain.value_objects import (
    BotTech,
    BotVerificationConfig,
    CommitManifest,
    ModReference,
    PlacementMode,
    TestRunStatus,
)
from app.modules.versioning.infrastructure.config_writer import write_test_server_properties
from app.modules.versioning.infrastructure.repository import SQLVersioningRepository
from app.modules.versioning.infrastructure.resource_probe import (
    ResourceCheckResult,
    ResourcePreflightProbe,
)
from app.modules.versioning.infrastructure.storage_probe import StorageCapabilityProbe

__all__ = [
    "BotTech",
    "BotVerificationConfig",
    "CommitManifest",
    "ModReference",
    "PlacementMode",
    "ResourceCheckResult",
    "ResourcePreflightProbe",
    "SQLVersioningRepository",
    "ServerBranch",
    "ServerCommit",
    "ServerTestRun",
    "ServerWorldSnapshot",
    "StorageCapabilityProbe",
    "TestRunStatus",
    "TestServerDeployment",
    "write_test_server_properties",
]
