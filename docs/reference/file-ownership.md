# File Ownership Map

> Cross-references: [Module Map](module-map.md), [Dependency Graph](dependency-graph.md), [Contract Registry](contract-registry.md)

Every file belongs to exactly one batch. No shared ownership. Directory trees verified against the current filesystem.

---

## Batch 01 — Core Foundation

```
backend/app/core/
  ├── __init__.py
  ├── auth_utils.py
  ├── circuit_breaker.py
  ├── command_bus.py
  ├── config.py
  ├── event_bus.py
  ├── exceptions.py
  ├── feature_flags.py
  ├── idempotency.py
  ├── logging.py
  ├── query_bus.py
  ├── saga.py
  └── security.py

backend/app/core/persistence/
  ├── __init__.py
  ├── base.py
  ├── db.py
  └── unit_of_work.py

backend/alembic/
  ├── env.py
  ├── script.py.mako
  └── versions/
      ├── 001_initial_schema.py
      ├── 002_batch09_tables.py
      ├── 003_add_deployment_columns.py
      ├── 16f9e2a1f2d6_add_auth_users_tables.py
      ├── 5a50140d37df_add_server_type_to_servers.py
      ├── 876be46160d3_add_missing_orm_only_tables.py
      ├── 876be46160d4_add_health_tables.py
      ├── 902b076bfa36_add_external_id_to_servers.py
      ├── a1b2c3d4e5f6_add_missing_since_to_servers.py
      ├── a2b2c3d4e5f7_add_updated_at_to_alert_rules.py
      ├── a3b2c3d4e5f6_add_deployment_start_time_to_servers.py
      ├── fcc7545db19e_add_launch_config_json_to_servers.py
      └── ff9c2b3a8e4d_add_updated_at_to_metric_points.py

backend/pyproject.toml
backend/requirements.txt
backend/Dockerfile
```

## Batch 02 — Domain Model

```
backend/app/modules/server/domain/
  ├── __init__.py
  ├── aggregate.py
  ├── diagnostics.py
  ├── events.py
  ├── repository.py
  ├── runtime_exceptions.py
  ├── service.py
  └── value_objects.py

backend/app/modules/backup/domain/
  ├── __init__.py
  ├── aggregate.py
  ├── events.py
  └── repository.py

backend/app/modules/plugin/domain/
  ├── __init__.py
  ├── aggregate.py
  ├── events.py
  └── repository.py

backend/app/modules/monitoring/domain/
  ├── __init__.py
  ├── aggregate.py
  └── events.py

backend/app/modules/auth/domain/
  ├── __init__.py
  ├── aggregate.py
  └── events.py

backend/app/modules/shared/
  ├── __init__.py
  ├── aggregate.py
  └── value_objects.py
```

## Batch 03 — Infrastructure Providers

```
backend/app/modules/server/infrastructure/
  ├── __init__.py
  ├── fs.py
  ├── location.py
  ├── models.py
  ├── repository.py
  └── providers/
      ├── __init__.py
      ├── base.py
      ├── circuit_breaker_wrapper.py
      ├── cloud.py
      ├── docker.py
      ├── local.py
      ├── local_windows.py
      ├── patterns.py
      └── remote.py

backend/app/modules/backup/infrastructure/
  ├── __init__.py
  ├── models.py
  └── repository.py

backend/app/modules/plugin/infrastructure/
  ├── __init__.py
  ├── models.py
  └── repository.py

backend/app/modules/storage/
  ├── __init__.py
  ├── base.py
  ├── encryption.py
  ├── local.py
  └── s3.py
```

## Batch 04 — Application Layer

```
backend/app/modules/server/application/
  ├── __init__.py
  ├── logging_utils.py
  ├── migrate_import_arch.py
  ├── ownership_verifier.py
  ├── read_models.py
  ├── reconciliation.py
  ├── runtime_ownership.py
  ├── runtime_reconciliation.py
  ├── startup_guard.py
  ├── supervisor.py
  ├── commands/
  │   ├── __init__.py
  │   ├── create_server.py
  │   ├── delete_server.py
  │   ├── import_server.py
  │   ├── restart_server.py
  │   ├── start_server.py
  │   ├── stop_server.py
  │   └── update_server_config.py
  ├── queries/
  │   ├── __init__.py
  │   ├── get_runtime_diagnostics.py
  │   ├── get_server.py
  │   ├── get_server_console.py
  │   └── list_servers.py
  └── services/
      ├── __init__.py
      ├── filesystem_reconciliation.py
      ├── import_service.py
      └── jar_service.py

backend/app/modules/backup/application/
  ├── __init__.py
  ├── commands/
  │   ├── __init__.py
  │   ├── create_backup.py
  │   ├── delete_backup.py
  │   ├── restore_backup.py
  │   └── verify_backup.py
  └── queries/
      ├── __init__.py
      ├── get_backup.py
      └── list_backups.py

backend/app/modules/plugin/application/
  ├── __init__.py
  ├── commands/
  │   ├── __init__.py
  │   ├── disable_plugin.py
  │   ├── enable_plugin.py
  │   ├── install_plugin.py
  │   └── uninstall_plugin.py
  └── queries/
      ├── __init__.py
      ├── get_plugin.py
      └── list_plugins.py

backend/app/modules/monitoring/application/
  ├── __init__.py
  ├── commands/
  │   ├── __init__.py
  │   ├── create_alert_rule.py
  │   └── update_alert_rule.py
  └── queries/
      ├── __init__.py
      └── get_metrics.py

backend/app/services/
  ├── __init__.py
  ├── backup_orchestrator.py
  ├── deployment_orchestrator.py
  └── server_orchestrator.py
```

## Batch 05 — API Layer

```
backend/app/main.py

backend/app/registration.py

backend/app/api/
  ├── __init__.py
  ├── deps.py
  ├── errors.py
  └── v1/
      ├── __init__.py
      ├── routers/
      │   ├── auth.py
      │   ├── backups.py
      │   ├── monitoring.py
      │   ├── plugins.py
      │   ├── schedules.py
      │   ├── servers.py
      │   ├── settings.py
      │   ├── software.py
      │   └── users.py
      ├── schemas/
      │   ├── auth.py
      │   ├── backup.py
      │   ├── common.py
      │   ├── import_server.py
      │   ├── plugin.py
      │   ├── server.py
      │   └── user.py
      └── middleware/
          ├── audit.py
          ├── auth.py
          ├── rate_limit.py
          └── request_id.py

backend/openapi.yaml
```

## Batch 06 — WebSocket Layer

```
backend/app/websocket/
  ├── __init__.py
  ├── authentication.py
  ├── authorization.py
  ├── buffer.py
  ├── dispatcher.py
  ├── endpoint.py
  ├── handlers.py
  ├── manager.py
  ├── rate_limiter.py
  └── serializers.py

frontend/src/websocket/
  ├── channels.ts
  ├── channels.test.ts
  ├── client.ts
  ├── client.test.ts
  ├── handler.ts
  ├── handler.test.ts
  └── types.ts
```

## Batch 07 — Plugin System

```
backend/app/modules/plugin/infrastructure/
  ├── dependency_resolver.py
  ├── lifecycle.py
  ├── manifest.py
  ├── sandbox.py
  └── runner/
      ├── __init__.py
      ├── base.py
      ├── container.py
      └── subprocess.py

backend/plugins/
  ├── __init__.py
  └── sdk/
      ├── __init__.py
      ├── commands.py
      ├── config.py
      ├── events.py
      ├── http.py
      ├── plugin.py
      └── storage.py
```

## Batch 08 — Auth System

```
backend/app/modules/auth/infrastructure/
  ├── __init__.py
  ├── audit.py
  ├── jwt.py
  ├── models.py
  ├── permissions.py
  ├── password.py
  └── repository.py

backend/app/modules/auth/application/
  ├── __init__.py
  ├── commands/
  │   ├── __init__.py
  │   ├── create_api_key.py
  │   ├── create_user.py
  │   ├── delete_user.py
  │   ├── login.py
  │   ├── logout.py
  │   ├── refresh_token.py
  │   ├── revoke_api_key.py
  │   └── update_user.py
  └── queries/
      ├── __init__.py
      ├── get_current_user.py
      └── list_users.py
```

## Batch 09 — Monitoring & Tasks

```
backend/app/tasks/
  ├── __init__.py
  ├── arq_queue.py
  ├── base.py
  ├── queue.py
  ├── scheduler.py
  └── definitions/
      ├── __init__.py
      ├── backup_task.py
      ├── cleanup_task.py
      ├── event_cleanup.py
      ├── health_check_task.py
      └── metrics_collector.py

backend/app/modules/monitoring/infrastructure/
  ├── __init__.py
  ├── collector.py
  ├── health.py
  ├── metrics.py
  ├── models.py
  └── repository.py

backend/app/modules/event_store/
  ├── __init__.py
  ├── chain.py
  ├── commands.py
  ├── dead_letter.py
  ├── models.py
  └── repository.py
```

## Health Engine — post-Batch 10

```
backend/app/modules/health/domain/
  ├── __init__.py
  ├── aggregate.py
  ├── events.py
  ├── repository.py
  ├── services.py
  └── value_objects.py

backend/app/modules/health/application/
  ├── __init__.py
  ├── commands/
  │   ├── __init__.py
  │   ├── classify_crash.py
  │   ├── collect_evidence.py
  │   └── evaluate_health.py
  ├── event_handlers/
  │   ├── __init__.py
  │   ├── health_signal_handler.py
  │   └── server_crashed_handler.py
  ├── queries/
  │   ├── __init__.py
  │   ├── generate_health_report.py
  │   ├── get_health_status.py
  │   └── get_health_timeline.py
  └── services/
      └── __init__.py

backend/app/modules/health/infrastructure/
  ├── __init__.py
  ├── crash_analyzer.py
  ├── environment.py
  ├── evidence_collector.py
  ├── health_calculator.py
  ├── integrity.py
  ├── models.py
  ├── recovery_orchestrator.py
  └── repository.py
```

## Batch 10 — Frontend

```
frontend/
  ├── index.html
  ├── package.json
  ├── tsconfig.json
  ├── vitest.config.ts
  ├── vite.config.ts
  ├── eslint.config.js
  └── src/
      ├── main.tsx
      ├── App.tsx
      ├── index.css
      ├── test-setup.ts
      ├── types/
      │   └── index.ts
      ├── services/
      │   ├── api.ts
      │   ├── api.test.ts
      │   └── queryClient.ts
      ├── stores/
      │   ├── authStore.ts
      │   ├── authStore.test.ts
      │   ├── uiStore.ts
      │   ├── uiStore.test.ts
      │   ├── wsStore.ts
      │   └── wsStore.test.ts
      ├── hooks/
      │   └── useWebSocket.ts
      ├── components/
      │   ├── EmptyState.tsx
      │   ├── EmptyState.test.tsx
      │   ├── ErrorBoundary.tsx
      │   ├── ErrorBoundary.test.tsx
      │   ├── Skeleton.tsx
      │   ├── Skeleton.test.tsx
      │   ├── WebSocketManager.tsx
      │   ├── WebSocketManager.test.tsx
      │   ├── guards/
      │   │   ├── AuthGuard.tsx
      │   │   └── AuthGuard.test.tsx
      │   └── layout/
      │       ├── Sidebar.tsx
      │       ├── Sidebar.test.tsx
      │       ├── TopNav.tsx
      │       └── TopNav.test.tsx
      ├── layouts/
      │   ├── AppLayout.tsx
      │   └── AppLayout.test.tsx
      ├── pages/
      │   ├── LoginPage.tsx
      │   ├── LoginPage.test.tsx
      │   └── RegisterPage.tsx
      └── server_manager/
          ├── index.ts
          ├── types.ts
          ├── components/
          │   ├── CreateBackupDialog.tsx
          │   ├── CreateBackupDialog.test.tsx
          │   ├── InstallPluginDialog.tsx
          │   ├── InstallPluginDialog.test.tsx
          │   ├── ServerConfigEditor.tsx
          │   ├── ServerConfigEditor.test.tsx
          │   ├── ServerConsole.tsx
          │   ├── ServerMetricsCharts.tsx
          │   ├── Sparkline.tsx
          │   └── Sparkline.test.tsx
          ├── hooks/
          │   ├── useApiKeys.ts
          │   ├── useBackups.ts
          │   ├── usePlugins.ts
          │   ├── useServers.ts
          │   └── useSettings.ts
          └── pages/
              ├── ApiKeysPage.tsx
              ├── ApiKeysPage.test.tsx
              ├── BackupListPage.tsx
              ├── BackupListPage.test.tsx
              ├── CreateServerPage.tsx
              ├── DashboardPage.tsx
              ├── DashboardPage.test.tsx
              ├── ImportServerPage.tsx
              ├── PluginListPage.tsx
              ├── PluginListPage.test.tsx
              ├── ServerDetailPage.tsx
              ├── ServerDetailPage.test.tsx
              ├── ServersPage.tsx
              ├── ServersPage.test.tsx
              ├── SettingsPage.tsx
              └── SettingsPage.test.tsx
```

## Files Not Owned by Any Batch

```
Implementation/           — Execution framework
docs/                     — Product documentation
deploy/                   — Deployment configurations
README.md                 — Project README
```

These are managed by project leads, not implementation batches.

## Infrastructure Files (Managed by Project Lead / First Session)

```
Implementation/PROJECT_STATE.json         — Machine-readable project state
Implementation/Requests/                  — Cross-batch requests
Implementation/LOCKS/                     — File locks
Implementation/QA/                        — Quality reports

Implementation/Shared/Contracts/          — Contract registry (read-only to batches)
Implementation/Shared/Interfaces/         — Interface stubs (written via Request)
Implementation/Shared/Events/             — Event catalog (read-only, updated via Request)
Implementation/Shared/Schemas/            — Shared schemas (empty, updated via Request)
Implementation/Shared/Types/              — Shared types (empty, updated via Request)
Implementation/Shared/API/                — API fragments (empty, updated via Request)
Implementation/Shared/ADR/                — ADRs (empty, written by project lead)

Implementation/Batch-*/STATE.md           — Session state (written by the batch itself)
Implementation/Batch-*/CHANGELOG.md       — Change log (written by the batch itself)
```
