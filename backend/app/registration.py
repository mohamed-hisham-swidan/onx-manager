import asyncio
import os
from typing import cast

from app.core.command_bus import (
    CommandBus,
    DatabaseBusyRetryMiddleware,
    Middleware,
)
from app.core.event_bus import EventBus
from app.core.idempotency import IdempotencyMiddleware, get_idempotency_store
from app.core.query_bus import QueryBus
from app.modules.activity.application import (
    ActivityEventSubscriber,
    GetServerActivityHandler,
    GetServerActivityQuery,
)
from app.modules.activity.infrastructure import SQLActivityRepository
from app.modules.auth.application import (
    AcceptInviteCommand,
    AcceptInviteHandler,
    BootstrapInstanceCommand,
    BootstrapInstanceHandler,
    CreateApiKeyCommand,
    CreateApiKeyHandler,
    CreateInviteCommand,
    CreateInviteHandler,
    CreateUserCommand,
    CreateUserHandler,
    DeleteUserCommand,
    DeleteUserHandler,
    GetCurrentUserHandler,
    GetCurrentUserQuery,
    GetSystemStatusHandler,
    GetSystemStatusQuery,
    ListInvitesHandler,
    ListInvitesQuery,
    ListUsersHandler,
    ListUsersQuery,
    LoginCommand,
    LoginHandler,
    LogoutCommand,
    LogoutHandler,
    RefreshTokenCommand,
    RefreshTokenHandler,
    RevokeApiKeyCommand,
    RevokeApiKeyHandler,
    RevokeInviteCommand,
    RevokeInviteHandler,
    UpdateAccessModeCommand,
    UpdateAccessModeHandler,
    UpdateUserCommand,
    UpdateUserHandler,
    VerifyInviteHandler,
    VerifyInviteQuery,
)
from app.modules.backup.application import (
    CreateBackupCommand,
    CreateBackupHandler,
    DeleteBackupCommand,
    DeleteBackupHandler,
    GetBackupHandler,
    GetBackupQuery,
    ListBackupsHandler,
    ListBackupsQuery,
    RestoreBackupCommand,
    RestoreBackupHandler,
    VerifyBackupCommand,
    VerifyBackupHandler,
)
from app.modules.exposure.application import (
    CreateExposureTargetCommand,
    CreateExposureTargetHandler,
    DeleteServerPortCommand,
    DeleteServerPortHandler,
    DisableServerExposureCommand,
    DisableServerExposureHandler,
    EnableServerExposureCommand,
    EnableServerExposureHandler,
    GenerateClaimCommand,
    GenerateClaimHandler,
    GetAgentStatusHandler,
    GetAgentStatusQuery,
    GetPanelExposureHandler,
    GetPanelExposureQuery,
    GetServerExposureHandler,
    GetServerExposureQuery,
    ListExposureTargetsHandler,
    ListExposureTargetsQuery,
    ListServerPortsHandler,
    ListServerPortsQuery,
    ReconcileExposureCommand,
    ReconcileExposureHandler,
    RegisterServerPortCommand,
    RegisterServerPortHandler,
    RemoveCredentialsCommand,
    RemoveCredentialsHandler,
    RemoveServerExposureCommand,
    RemoveServerExposureHandler,
    ResetAgentCommand,
    ResetAgentHandler,
    SetPanelExposureCommand,
    SetPanelExposureHandler,
    SetServerExposureCommand,
    SetServerExposureHandler,
    StopAllExposuresCommand,
    StopAllExposuresHandler,
    UpdateExposureTargetCommand,
    UpdateExposureTargetHandler,
)
from app.modules.health.application import (
    EvaluateHealthCommand,
    EvaluateHealthHandler,
    GetHealthStatusHandler,
    GetHealthStatusQuery,
    GetHealthTimelineHandler,
    GetHealthTimelineQuery,
    GetServerCrashReportsHandler,
    GetServerCrashReportsQuery,
)
from app.modules.health.application.event_handlers.health_signal_handler import HealthSignalHandler
from app.modules.health.application.event_handlers.server_crashed_handler import (
    HandleServerCrashHandler,
)
from app.modules.monitoring.application import (
    CreateAlertRuleCommand,
    CreateAlertRuleHandler,
    GetMetricsHandler,
    GetMetricsQuery,
    UpdateAlertRuleCommand,
    UpdateAlertRuleHandler,
)
from app.modules.operations.application import (
    CancelOperationCommand,
    CancelOperationHandler,
    CreateOperationCommand,
    CreateOperationHandler,
    GetOperationHandler,
    GetOperationQuery,
    ListOperationsHandler,
    ListOperationsQuery,
    RetryOperationCommand,
    RetryOperationHandler,
    get_operation_service,
)
from app.modules.plugin.application import (
    DisablePluginCommand,
    DisablePluginHandler,
    EnablePluginCommand,
    EnablePluginHandler,
    GetPluginHandler,
    GetPluginQuery,
    InstallModrinthPluginCommand,
    InstallModrinthPluginHandler,
    ListPluginsHandler,
    ListPluginsQuery,
    ReconcilePluginsCommand,
    ReconcilePluginsHandler,
    ToggleModStateCommand,
    ToggleModStateHandler,
    UninstallPluginCommand,
    UninstallPluginHandler,
    UploadModCommand,
    UploadModHandler,
)
from app.modules.server.application import (
    CreateServerCommand,
    CreateServerHandler,
    DeleteServerCommand,
    DeleteServerHandler,
    GetServerConsoleHandler,
    GetServerConsoleQuery,
    GetServerHandler,
    GetServerQuery,
    GetServerRuntimeDiagnosticsHandler,
    GetServerRuntimeDiagnosticsQuery,
    ImportServerCommand,
    ImportServerHandler,
    ListServersHandler,
    ListServersQuery,
    RestartServerCommand,
    RestartServerHandler,
    RetryProvisioningCommand,
    RetryProvisioningHandler,
    StartServerCommand,
    StartServerHandler,
    StopServerCommand,
    StopServerHandler,
    UpdateServerConfigCommand,
    UpdateServerConfigHandler,
)
from app.modules.server.application.lifecycle_lock import (
    ServerLifecycleLockMiddleware,
    get_lifecycle_lease_manager,
)
from app.modules.versioning.application import (
    ArchiveBranchCommand,
    ArchiveBranchHandler,
    AutoCommitLiveChangesCommand,
    AutoCommitLiveChangesHandler,
    ConfirmImportReviewCommand,
    ConfirmImportReviewHandler,
    CreateBranchCommand,
    CreateBranchHandler,
    CreateCommitCommand,
    CreateCommitHandler,
    CreateMaterializationCommand,
    CreateMaterializationHandler,
    CreateTagCommand,
    CreateTagHandler,
    CreateTestDefinitionCommand,
    CreateTestDefinitionHandler,
    DeleteBranchCommand,
    DeleteBranchHandler,
    DeleteTestDefinitionCommand,
    DeleteTestDefinitionHandler,
    DiffCommitsHandler,
    DiffCommitsQuery,
    DiscardTestCommand,
    DiscardTestHandler,
    DismissImportReviewCommand,
    DismissImportReviewHandler,
    GetBranchFilesRootHandler,
    GetBranchFilesRootQuery,
    GetBranchHistoryHandler,
    GetBranchHistoryQuery,
    GetBranchProtectionHandler,
    GetBranchProtectionQuery,
    GetCommitHistoryHandler,
    GetCommitHistoryQuery,
    GetMaterializationFileHandler,
    GetMaterializationFileQuery,
    GetMaterializationsHandler,
    GetMaterializationsQuery,
    GetMaterializationTreeHandler,
    GetMaterializationTreeQuery,
    GetServerBranchesHandler,
    GetServerBranchesQuery,
    GetServerTagHandler,
    GetServerTagQuery,
    GetServerTagsHandler,
    GetServerTagsQuery,
    GetServerTestRunsHandler,
    GetServerTestRunsQuery,
    GetTestDefinitionHandler,
    GetTestDefinitionQuery,
    GetTestRunEvidenceHandler,
    GetTestRunEvidenceQuery,
    GetTestStatusHandler,
    GetTestStatusQuery,
    ListTestDefinitionsHandler,
    ListTestDefinitionsQuery,
    MergeCommitsCommand,
    MergeCommitsHandler,
    PruneTestArtifactsCommand,
    PruneTestArtifactsHandler,
    RemoveBranchProtectionCommand,
    RemoveBranchProtectionHandler,
    RemoveMaterializationCommand,
    RemoveMaterializationHandler,
    RevertImportReviewCommand,
    RevertImportReviewHandler,
    RunIsolatedTestCommand,
    RunIsolatedTestHandler,
    ScanLiveChangesHandler,
    ScanLiveChangesQuery,
    SetBranchProtectionCommand,
    SetBranchProtectionHandler,
    SetMaterializationEditModeCommand,
    SetMaterializationEditModeHandler,
    UpdateTestDefinitionCommand,
    UpdateTestDefinitionHandler,
    WriteMaterializedFileCommand,
    WriteMaterializedFileHandler,
)
from app.modules.versioning.application.refresh_orchestrator import (
    ConfirmUpgradeCommand,
    ConfirmUpgradeCommandHandler,
    LiveRefreshService,
    RefreshServerCommand,
    RefreshServerCommandHandler,
    ReleaseRefreshPinsCommand,
    ReleaseRefreshPinsCommandHandler,
    RollbackRefreshCommand,
    RollbackRefreshCommandHandler,
    Tier1BackupServiceAdapter,
)
from app.modules.versioning.application.repo_lease import RepoLeaseManager


async def _build_live_refresh_service(
    server_id: str,
    *,
    event_bus: EventBus,
) -> LiveRefreshService:
    """Construct a fresh per-request refresh service and runtime/export adapters.

    Capturing the running loop and loading the server row happens at async
    handler entry. The adapters stay immutable for the rest of the request and
    every blocking half is dispatched with ``asyncio.to_thread``.
    """
    from app.core.exceptions import (
        ServerModeVersioningDisabledError,
        ValidationError,
    )
    from app.core.host_state import ensure_host_state_layout
    from app.core.persistence.unit_of_work import UnitOfWork
    from app.core.settings_store import get_live_settings
    from app.modules.server.application.commands.start_server import (
        StartServerHandler,
    )
    from app.modules.server.application.commands.stop_server import StopServerHandler
    from app.modules.server.infrastructure.repository import SQLServerRepository
    from app.modules.shared.value_objects import ServerId
    from app.modules.versioning.application.lockfile_service import LockfileService
    from app.modules.versioning.application.mode_guard import ensure_versioning_allowed
    from app.modules.versioning.infrastructure.runtime_adapters import (
        CleanExportStageAdapter,
        DockerServerRuntimeAdapter,
        require_docker_provider,
    )

    if os.name != "posix":
        raise ServerModeVersioningDisabledError(
            "Live refresh is only supported on POSIX hosts in this release"
        )

    loop = asyncio.get_running_loop()
    layout = ensure_host_state_layout()
    async with UnitOfWork() as uow:
        server = await SQLServerRepository(uow.session).get(ServerId(server_id))
    await ensure_versioning_allowed(server)
    if server.deployment is None:
        raise ValidationError(
            "Live refresh requires a deployed server directory", field="server_id"
        )
    server_root = server.deployment.server_directory()
    provider = require_docker_provider(
        server.runtime.provider if server.runtime else None
    )
    startup_timeout = float(
        server.startup_timeout_seconds
        or get_live_settings().server_startup_timeout_seconds
    )
    lockfile = await asyncio.to_thread(LockfileService(layout).read, server_id)
    runtime_record = server.runtime
    container_name = (
        str(runtime_record.external_id).strip()
        if runtime_record is not None and runtime_record.external_id
        else None
    )
    runtime = DockerServerRuntimeAdapter(
        server_id=server_id,
        loop=loop,
        start_handler=StartServerHandler(event_bus).handle,
        stop_handler=StopServerHandler(event_bus).handle,
        server_dir=server_root,
        startup_timeout_seconds=startup_timeout,
        provider_name=provider,
        container_name=container_name,
    )
    stage_export = CleanExportStageAdapter(
        layout,
        server_id=server_id,
        server_root=server_root,
        lockfile=lockfile,
        loop=loop,
    )
    return LiveRefreshService(
        layout,
        repo_lease=RepoLeaseManager(locks_dir=layout.locks),
        backup_service=Tier1BackupServiceAdapter(),
        runtime=runtime,
        stage_export=stage_export,
    )


def init_infrastructure() -> None:
    from app.modules.server.infrastructure.location import handler_registry, local_handler

    handler_registry.register(local_handler)


def register_handlers(
    command_bus: CommandBus,
    query_bus: QueryBus,
    event_bus: EventBus,
) -> None:
    init_infrastructure()
    _register_command_handlers(command_bus, event_bus)
    _register_query_handlers(query_bus)
    _register_event_handlers(event_bus)


def _register_event_handlers(event_bus: EventBus) -> None:
    """Wire domain EventHandlers to the EventBus (Decision 2 + 2a).

    HandleServerCrashHandler subscribes with a 60 s per-attempt timeout override
    because log-based evidence collection is disk-bound and can exceed the 10 s
    global.  HealthSignalHandler is DB-bound and keeps the global default.
    """
    # Crash pipeline — one subscription, scoped type, 60 s per-attempt override.
    crash_handler = HandleServerCrashHandler(event_bus)
    event_bus.subscribe("ServerCrashedEvent", crash_handler, timeout=60.0)

    # Health signal handler — three subscriptions, global 10 s timeout.
    health_handler = HealthSignalHandler(event_bus)
    event_bus.subscribe("RuntimeHealthSignalEvent", health_handler)
    event_bus.subscribe("IntegrityCheckFailedEvent", health_handler)
    event_bus.subscribe("CrashClassifiedEvent", health_handler)

    # Activity log subscriber (Feature 4 - Change History Log)
    activity_subscriber = ActivityEventSubscriber(SQLActivityRepository())
    activity_events = [
        "ServerCreatedEvent",
        "ServerStartingEvent",
        "ServerStartedEvent",
        "ServerStoppingEvent",
        "ServerStoppedEvent",
        "ServerCrashedEvent",
        "ServerConfigChangedEvent",
        "ServerDeletedEvent",
        "PluginInstalledEvent",
        "PluginEnabledEvent",
        "PluginDisabledEvent",
        "PluginUninstalledEvent",
        "PluginUpdatedEvent",
        "BackupStartedEvent",
        "BackupCompletedEvent",
        "BackupFailedEvent",
        "BackupRestoredEvent",
        "BackupDeletedEvent",
        "ServerExposureEnabledEvent",
        "ServerExposureDisabledEvent",
        "ServerExposureRemovedEvent",
        "BranchCreatedEvent",
        "CommitCreatedEvent",
        "TestRunStartedEvent",
        "TestRunCompletedEvent",
        "CommitPromotedEvent",
        "BranchRuntimeStartedEvent",
        "BranchRuntimeStoppedEvent",
        "DataTemplateSavedEvent",
    ]
    for ev in activity_events:
        event_bus.subscribe(ev, activity_subscriber)


def _register_command_handlers(command_bus: CommandBus, event_bus: EventBus) -> None:
    command_bus.add_middleware(
        cast(Middleware, IdempotencyMiddleware(get_idempotency_store()))
    )
    command_bus.add_middleware(DatabaseBusyRetryMiddleware())
    command_bus.add_middleware(ServerLifecycleLockMiddleware(get_lifecycle_lease_manager()))
    command_bus.register(CreateServerCommand, CreateServerHandler(event_bus))
    command_bus.register(DeleteServerCommand, DeleteServerHandler(event_bus))
    command_bus.register(StartServerCommand, StartServerHandler(event_bus))
    command_bus.register(StopServerCommand, StopServerHandler(event_bus))
    command_bus.register(RestartServerCommand, RestartServerHandler(event_bus))
    command_bus.register(RetryProvisioningCommand, RetryProvisioningHandler(event_bus))
    command_bus.register(UpdateServerConfigCommand, UpdateServerConfigHandler(event_bus))
    command_bus.register(ImportServerCommand, ImportServerHandler(event_bus))

    command_bus.register(CreateBackupCommand, CreateBackupHandler(event_bus))
    command_bus.register(RestoreBackupCommand, RestoreBackupHandler(event_bus))
    command_bus.register(DeleteBackupCommand, DeleteBackupHandler(event_bus))
    command_bus.register(VerifyBackupCommand, VerifyBackupHandler(event_bus))

    command_bus.register(InstallModrinthPluginCommand, InstallModrinthPluginHandler(event_bus))
    command_bus.register(ReconcilePluginsCommand, ReconcilePluginsHandler(event_bus))
    command_bus.register(UninstallPluginCommand, UninstallPluginHandler(event_bus))
    command_bus.register(EnablePluginCommand, EnablePluginHandler(event_bus))
    command_bus.register(DisablePluginCommand, DisablePluginHandler(event_bus))
    command_bus.register(UploadModCommand, UploadModHandler(event_bus))
    command_bus.register(ToggleModStateCommand, ToggleModStateHandler(event_bus))

    command_bus.register(EvaluateHealthCommand, EvaluateHealthHandler(event_bus))

    command_bus.register(CreateAlertRuleCommand, CreateAlertRuleHandler(event_bus))
    command_bus.register(UpdateAlertRuleCommand, UpdateAlertRuleHandler(event_bus))

    command_bus.register(SetServerExposureCommand, SetServerExposureHandler(event_bus))
    command_bus.register(EnableServerExposureCommand, EnableServerExposureHandler(event_bus))
    command_bus.register(DisableServerExposureCommand, DisableServerExposureHandler(event_bus))
    command_bus.register(RemoveServerExposureCommand, RemoveServerExposureHandler(event_bus))
    command_bus.register(CreateExposureTargetCommand, CreateExposureTargetHandler(event_bus))
    command_bus.register(UpdateExposureTargetCommand, UpdateExposureTargetHandler(event_bus))
    command_bus.register(RegisterServerPortCommand, RegisterServerPortHandler(event_bus))
    command_bus.register(DeleteServerPortCommand, DeleteServerPortHandler(event_bus))
    command_bus.register(StopAllExposuresCommand, StopAllExposuresHandler(event_bus))
    command_bus.register(GenerateClaimCommand, GenerateClaimHandler(event_bus))
    command_bus.register(ResetAgentCommand, ResetAgentHandler(event_bus))
    command_bus.register(RemoveCredentialsCommand, RemoveCredentialsHandler(event_bus))
    command_bus.register(SetPanelExposureCommand, SetPanelExposureHandler(event_bus))
    command_bus.register(ReconcileExposureCommand, ReconcileExposureHandler(event_bus))

    command_bus.register(LoginCommand, LoginHandler(event_bus))
    command_bus.register(LogoutCommand, LogoutHandler(event_bus))
    command_bus.register(RefreshTokenCommand, RefreshTokenHandler(event_bus))
    command_bus.register(CreateApiKeyCommand, CreateApiKeyHandler(event_bus))
    command_bus.register(RevokeApiKeyCommand, RevokeApiKeyHandler(event_bus))
    command_bus.register(CreateUserCommand, CreateUserHandler(event_bus))
    command_bus.register(UpdateUserCommand, UpdateUserHandler(event_bus))
    command_bus.register(DeleteUserCommand, DeleteUserHandler(event_bus))
    command_bus.register(BootstrapInstanceCommand, BootstrapInstanceHandler(event_bus))
    command_bus.register(CreateInviteCommand, CreateInviteHandler(event_bus))
    command_bus.register(AcceptInviteCommand, AcceptInviteHandler(event_bus))
    command_bus.register(RevokeInviteCommand, RevokeInviteHandler(event_bus))
    command_bus.register(UpdateAccessModeCommand, UpdateAccessModeHandler(event_bus))

    command_bus.register(CreateBranchCommand, CreateBranchHandler(event_bus=event_bus))
    command_bus.register(ArchiveBranchCommand, ArchiveBranchHandler(event_bus=event_bus))
    command_bus.register(DeleteBranchCommand, DeleteBranchHandler(event_bus=event_bus))
    command_bus.register(CreateCommitCommand, CreateCommitHandler(event_bus=event_bus))
    command_bus.register(CreateTagCommand, CreateTagHandler(event_bus=event_bus))
    command_bus.register(MergeCommitsCommand, MergeCommitsHandler(event_bus=event_bus))
    command_bus.register(RunIsolatedTestCommand, RunIsolatedTestHandler(event_bus=event_bus))
    command_bus.register(DiscardTestCommand, DiscardTestHandler())
    command_bus.register(
        CreateMaterializationCommand,
        CreateMaterializationHandler(event_bus=event_bus),
    )
    command_bus.register(
        RemoveMaterializationCommand,
        RemoveMaterializationHandler(event_bus=event_bus),
    )
    command_bus.register(
        SetMaterializationEditModeCommand,
        SetMaterializationEditModeHandler(event_bus=event_bus),
    )
    command_bus.register(
        WriteMaterializedFileCommand,
        WriteMaterializedFileHandler(event_bus=event_bus),
    )
    command_bus.register(
        AutoCommitLiveChangesCommand,
        AutoCommitLiveChangesHandler(event_bus=event_bus),
    )
    command_bus.register(
        ConfirmImportReviewCommand,
        ConfirmImportReviewHandler(event_bus=event_bus),
    )
    command_bus.register(
        DismissImportReviewCommand,
        DismissImportReviewHandler(event_bus=event_bus),
    )
    command_bus.register(
        RevertImportReviewCommand,
        RevertImportReviewHandler(event_bus=event_bus),
    )
    command_bus.register(
        CreateTestDefinitionCommand,
        CreateTestDefinitionHandler(event_bus=event_bus),
    )
    command_bus.register(
        UpdateTestDefinitionCommand,
        UpdateTestDefinitionHandler(event_bus=event_bus),
    )
    command_bus.register(
        DeleteTestDefinitionCommand,
        DeleteTestDefinitionHandler(event_bus=event_bus),
    )
    command_bus.register(
        PruneTestArtifactsCommand,
        PruneTestArtifactsHandler(),
    )
    command_bus.register(
        SetBranchProtectionCommand,
        SetBranchProtectionHandler(),
    )
    command_bus.register(
        RemoveBranchProtectionCommand,
        RemoveBranchProtectionHandler(),
    )

    async def build_refresh_service(server_id: str) -> LiveRefreshService:
        return await _build_live_refresh_service(server_id, event_bus=event_bus)

    command_bus.register(
        RefreshServerCommand, RefreshServerCommandHandler(build_refresh_service)
    )
    command_bus.register(
        RollbackRefreshCommand,
        RollbackRefreshCommandHandler(build_refresh_service),
    )
    command_bus.register(
        ConfirmUpgradeCommand,
        ConfirmUpgradeCommandHandler(build_refresh_service),
    )
    command_bus.register(
        ReleaseRefreshPinsCommand,
        ReleaseRefreshPinsCommandHandler(build_refresh_service),
    )
    op_service = get_operation_service(event_bus=event_bus)
    command_bus.register(CreateOperationCommand, CreateOperationHandler(op_service))
    command_bus.register(CancelOperationCommand, CancelOperationHandler(op_service))
    command_bus.register(RetryOperationCommand, RetryOperationHandler(op_service))


def _register_query_handlers(query_bus: QueryBus) -> None:
    query_bus.register(GetServerQuery, GetServerHandler())
    query_bus.register(ListServersQuery, ListServersHandler())
    query_bus.register(GetServerConsoleQuery, GetServerConsoleHandler())
    query_bus.register(GetServerRuntimeDiagnosticsQuery, GetServerRuntimeDiagnosticsHandler())

    query_bus.register(ListBackupsQuery, ListBackupsHandler())
    query_bus.register(GetBackupQuery, GetBackupHandler())

    query_bus.register(ListPluginsQuery, ListPluginsHandler())
    query_bus.register(GetPluginQuery, GetPluginHandler())

    query_bus.register(GetHealthStatusQuery, GetHealthStatusHandler())
    query_bus.register(GetHealthTimelineQuery, GetHealthTimelineHandler())
    query_bus.register(GetServerCrashReportsQuery, GetServerCrashReportsHandler())

    query_bus.register(GetMetricsQuery, GetMetricsHandler())

    query_bus.register(GetServerExposureQuery, GetServerExposureHandler())
    query_bus.register(GetAgentStatusQuery, GetAgentStatusHandler())
    query_bus.register(GetPanelExposureQuery, GetPanelExposureHandler())
    query_bus.register(ListExposureTargetsQuery, ListExposureTargetsHandler())
    query_bus.register(ListServerPortsQuery, ListServerPortsHandler())

    query_bus.register(GetCurrentUserQuery, GetCurrentUserHandler())
    query_bus.register(ListUsersQuery, ListUsersHandler())
    query_bus.register(GetSystemStatusQuery, GetSystemStatusHandler())
    query_bus.register(VerifyInviteQuery, VerifyInviteHandler())
    query_bus.register(ListInvitesQuery, ListInvitesHandler())

    query_bus.register(GetServerBranchesQuery, GetServerBranchesHandler())
    query_bus.register(GetBranchFilesRootQuery, GetBranchFilesRootHandler())
    query_bus.register(GetBranchHistoryQuery, GetBranchHistoryHandler())
    query_bus.register(GetCommitHistoryQuery, GetCommitHistoryHandler())
    query_bus.register(GetServerTagsQuery, GetServerTagsHandler())
    query_bus.register(GetServerTagQuery, GetServerTagHandler())
    query_bus.register(DiffCommitsQuery, DiffCommitsHandler())
    query_bus.register(GetServerTestRunsQuery, GetServerTestRunsHandler())
    query_bus.register(GetTestStatusQuery, GetTestStatusHandler())
    query_bus.register(GetServerActivityQuery, GetServerActivityHandler(SQLActivityRepository()))
    query_bus.register(GetMaterializationsQuery, GetMaterializationsHandler())
    query_bus.register(GetMaterializationTreeQuery, GetMaterializationTreeHandler())
    query_bus.register(GetMaterializationFileQuery, GetMaterializationFileHandler())
    query_bus.register(ScanLiveChangesQuery, ScanLiveChangesHandler())
    query_bus.register(GetTestDefinitionQuery, GetTestDefinitionHandler())
    query_bus.register(ListTestDefinitionsQuery, ListTestDefinitionsHandler())
    query_bus.register(GetTestRunEvidenceQuery, GetTestRunEvidenceHandler())
    query_bus.register(GetBranchProtectionQuery, GetBranchProtectionHandler())
    query_bus.register(GetOperationQuery, GetOperationHandler())
    query_bus.register(ListOperationsQuery, ListOperationsHandler())

