from app.core.command_bus import CommandBus
from app.core.event_bus import EventBus
from app.core.query_bus import QueryBus
from app.modules.auth.application import (
    CreateApiKeyCommand,
    CreateApiKeyHandler,
    CreateUserCommand,
    CreateUserHandler,
    DeleteUserCommand,
    DeleteUserHandler,
    GetCurrentUserHandler,
    GetCurrentUserQuery,
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
    UpdateUserCommand,
    UpdateUserHandler,
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
from app.modules.health.application import (
    EvaluateHealthCommand,
    EvaluateHealthHandler,
    GetHealthStatusHandler,
    GetHealthStatusQuery,
    GetHealthTimelineHandler,
    GetHealthTimelineQuery,
)
from app.modules.monitoring.application import (
    CreateAlertRuleCommand,
    CreateAlertRuleHandler,
    GetMetricsHandler,
    GetMetricsQuery,
    UpdateAlertRuleCommand,
    UpdateAlertRuleHandler,
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
    UninstallPluginCommand,
    UninstallPluginHandler,
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
    StartServerCommand,
    StartServerHandler,
    StopServerCommand,
    StopServerHandler,
    UpdateServerConfigCommand,
    UpdateServerConfigHandler,
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


def _register_command_handlers(command_bus: CommandBus, event_bus: EventBus) -> None:
    command_bus.register(CreateServerCommand, CreateServerHandler(event_bus))
    command_bus.register(DeleteServerCommand, DeleteServerHandler(event_bus))
    command_bus.register(StartServerCommand, StartServerHandler(event_bus))
    command_bus.register(StopServerCommand, StopServerHandler(event_bus))
    command_bus.register(RestartServerCommand, RestartServerHandler(event_bus))
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

    command_bus.register(EvaluateHealthCommand, EvaluateHealthHandler(event_bus))

    command_bus.register(CreateAlertRuleCommand, CreateAlertRuleHandler(event_bus))
    command_bus.register(UpdateAlertRuleCommand, UpdateAlertRuleHandler(event_bus))

    command_bus.register(LoginCommand, LoginHandler(event_bus))
    command_bus.register(LogoutCommand, LogoutHandler(event_bus))
    command_bus.register(RefreshTokenCommand, RefreshTokenHandler(event_bus))
    command_bus.register(CreateApiKeyCommand, CreateApiKeyHandler(event_bus))
    command_bus.register(RevokeApiKeyCommand, RevokeApiKeyHandler(event_bus))
    command_bus.register(CreateUserCommand, CreateUserHandler(event_bus))
    command_bus.register(UpdateUserCommand, UpdateUserHandler(event_bus))
    command_bus.register(DeleteUserCommand, DeleteUserHandler(event_bus))


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

    query_bus.register(GetMetricsQuery, GetMetricsHandler())

    query_bus.register(GetCurrentUserQuery, GetCurrentUserHandler())
    query_bus.register(ListUsersQuery, ListUsersHandler())
