# Domain Event Catalog

**Status:** Living Reference (Synchronized with live codebase)  
**Total Domain Events:** 87 event classes across 9 bounded contexts  
**Transport:** In-process asynchronous `EventBus` with subscriber handlers and WebSocket fan-out (`EventDispatcher`)

---

## Overview

Events represent immutable facts that have occurred within the domain. All domain events inherit from `DomainEvent` (`app.core.events`), carrying:
- `event_id`: Unique UUIDv4 string
- `timestamp`: UTC datetime of event occurrence
- `event_name`: Dot-notated event name identifier
- `version`: Event schema version (integer)

---

## 1. Server Lifecycle & Provisioning Events (`server`)

Location: `backend/app/modules/server/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `ServerCreatedEvent` | `server.created` | `server_id`, `name`, `server_type`, `minecraft_version`, `port` | Emitted when a new server aggregate is created. |
| `ServerStartingEvent` | `server.starting` | `server_id` | Emitted when the server transition to STARTING is recorded. |
| `ServerStartedEvent` | `server.started` | `server_id`, `pid`, `port` | Emitted when process startup is verified alive by supervisor. |
| `ServerStoppingEvent` | `server.stopping` | `server_id`, `reason` | Emitted when a stop signal is issued. |
| `ServerStopUnknownEvent` | `server.stop_unknown` | `server_id`, `reason` | Emitted when stop outcome cannot be confirmed (`stop_confirmed=False`). |
| `ServerStoppedEvent` | `server.stopped` | `server_id` | Emitted when process exit is confirmed. |
| `ServerCrashedEvent` | `server.crashed` | `server_id`, `exit_code`, `reason` | Emitted when an unexpected process death or crash is detected. |
| `ServerConfigChangedEvent` | `server.config_changed` | `server_id`, `changes` | Emitted when server properties or launch configurations are modified. |
| `ServerDeletedEvent` | `server.deleted` | `server_id` | Emitted when a server aggregate is deleted. |
| `ServerDiscoveredEvent` | `server.discovered` | `path`, `name`, `server_type`, `minecraft_version` | Emitted during filesystem reconciliation when an unmanaged directory is found. |
| `ServerVanishedEvent` | `server.vanished` | `path` | Emitted during filesystem reconciliation when a server directory disappears. |
| `ForgeProvisionProgressEvent` | `forge.provision_progress` | `server_id`, `stage`, `percent`, `message` | Emitted during Forge/NeoForge auto-installation stages. |

---

## 2. Health & Recovery Events (`health`)

Location: `backend/app/modules/health/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `HealthStatusChangedEvent` | `health.status_changed` | `server_id`, `old_status`, `new_status`, `reasons` | Emitted when server health classification transitions (HEALTHY, DEGRADED, UNHEALTHY). |
| `IntegrityCheckPassedEvent` | `health.integrity_passed` | `server_id`, `checks` | Emitted when filesystem integrity check passes (jar/run.sh + properties). |
| `IntegrityCheckFailedEvent` | `health.integrity_failed` | `server_id`, `failures` | Emitted when missing files or invalid configurations fail integrity check. |
| `EnvironmentDegradedEvent` | `health.environment_degraded` | `disk_free_mb`, `memory_free_mb`, `load_avg` | Emitted when host resources fall below safe operational thresholds. |
| `StartupValidationPassedEvent` | `health.startup_validation_passed` | `server_id` | Emitted when pre-flight checks pass prior to server launch. |
| `StartupValidationBlockedEvent` | `health.startup_validation_blocked` | `server_id`, `reason` | Emitted when pre-flight checks block startup (e.g. port conflict, disk full). |
| `RuntimeHealthSignalEvent` | `health.runtime_signal` | `server_id`, `signal_type`, `data` | Emitted on heartbeat signals from runtime monitoring. |
| `EvidenceCollectedEvent` | `health.evidence_collected` | `server_id`, `evidence_type`, `summary` | Emitted when crash logs or thread dumps are captured. |
| `CrashClassifiedEvent` | `health.crash_classified` | `server_id`, `crash_type`, `root_cause` | Emitted when crash analyzer classifies failure (OOM, PortConflict, CorruptWorld). |
| `AlertTriggeredEvent` | `health.alert_triggered` | `alert_id`, `severity`, `message` | Emitted when an operational threshold is breached. |
| `RecoveryTriggeredEvent` | `health.recovery_triggered` | `server_id`, `action`, `attempt` | Emitted when automated recovery saga initiates. |
| `RecoveryFailedEvent` | `health.recovery_failed` | `server_id`, `action`, `error` | Emitted when recovery action fails. |
| `RecoverySucceededEvent` | `health.recovery_succeeded` | `server_id`, `action` | Emitted when recovery action successfully restores server. |
| `HealthReportGeneratedEvent` | `health.report_generated` | `server_id`, `report` | Emitted on periodic comprehensive health summary generation. |

---

## 3. Network Exposure & Tunnel Events (`exposure`)

Location: `backend/app/modules/exposure/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `ServerExposureEnabledEvent` | `exposure.server_enabled` | `server_id`, `exposure_type`, `address`, `port` | Emitted when a game server tunnel/port-forward is activated. |
| `ServerExposureDisabledEvent` | `exposure.server_disabled` | `server_id`, `exposure_type` | Emitted when a game server tunnel/port-forward is deactivated. |
| `ServerExposureRemovedEvent` | `exposure.server_removed` | `server_id` | Emitted when exposure configuration is cleared for a server. |
| `AgentClaimGeneratedEvent` | `exposure.agent_claim_generated` | `claim_url`, `expires_at` | Emitted when a new Playit.gg account claim link is generated. |
| `AgentResetEvent` | `exposure.agent_reset` | `reason` | Emitted when Playit agent credentials or state are reset. |
| `AgentCredentialsRemovedEvent` | `exposure.agent_credentials_removed` | `timestamp` | Emitted when Playit agent auth credentials are deleted. |
| `PanelExposureChangedEvent` | `exposure.panel_changed` | `provider`, `is_enabled`, `hostname` | Emitted when web panel public exposure (Cloudflare/Playit) changes state. |
| `ExposureReconciledEvent` | `exposure.reconciled` | `active_count`, `stale_count` | Emitted during exposure background reconciliation cycle. |

---

## 4. Authentication & User Events (`auth`)

Location: `backend/app/modules/auth/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `UserCreatedEvent` | `auth.user_created` | `user_id`, `username`, `role` | Emitted when a new user account is registered or bootstrapped. |
| `UserLoggedInEvent` | `auth.user_logged_in` | `user_id`, `ip_address` | Emitted on successful JWT issuance. |
| `UserLoggedOutEvent` | `auth.user_logged_out` | `user_id` | Emitted on explicit session termination. |
| `UserDeactivatedEvent` | `auth.user_deactivated` | `user_id`, `reason` | Emitted when a user account is locked or deactivated. |
| `UserActivatedEvent` | `auth.user_activated` | `user_id` | Emitted when a user account is re-activated. |
| `ApiKeyCreatedEvent` | `auth.api_key_created` | `key_id`, `user_id`, `name`, `scopes` | Emitted when a new API key is generated. |
| `ApiKeyRevokedEvent` | `auth.api_key_revoked` | `key_id`, `user_id` | Emitted when an API key is revoked. |

---

## 5. Plugin & Marketplace Events (`plugin`)

Location: `backend/app/modules/plugin/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `PluginInstalledEvent` | `plugin.installed` | `server_id`, `plugin_id`, `name`, `version`, `source` | Emitted when a plugin/mod JAR is downloaded and installed. |
| `PluginEnabledEvent` | `plugin.enabled` | `server_id`, `plugin_id` | Emitted when a disabled plugin is re-enabled (.jar renamed). |
| `PluginDisabledEvent` | `plugin.disabled` | `server_id`, `plugin_id` | Emitted when an active plugin is disabled (.disabled appended). |
| `PluginUninstalledEvent` | `plugin.uninstalled` | `server_id`, `plugin_id` | Emitted when a plugin file is deleted from `plugins/` or `mods/`. |
| `PluginUpdatedEvent` | `plugin.updated` | `server_id`, `plugin_id`, `old_version`, `new_version` | Emitted when a plugin is upgraded to a newer release. |

---

## 6. Backup Events (`backup`)

Location: `backend/app/modules/backup/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `BackupStartedEvent` | `backup.started` | `backup_id`, `server_id`, `backup_type` | Emitted when backup archive creation starts. |
| `BackupCompletedEvent` | `backup.completed` | `backup_id`, `server_id`, `size_bytes`, `duration_ms` | Emitted when archive is verified and recorded. |
| `BackupFailedEvent` | `backup.failed` | `backup_id`, `server_id`, `error` | Emitted when backup creation aborts due to error. |
| `BackupRestoredEvent` | `backup.restored` | `backup_id`, `server_id` | Emitted when server directory is restored from backup archive. |
| `BackupDeletedEvent` | `backup.deleted` | `backup_id`, `server_id` | Emitted when a backup archive is removed. |

---

## 7. Metrics & Monitoring Events (`monitoring`)

Location: `backend/app/modules/monitoring/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `MetricRecordedEvent` | `monitoring.metric_recorded` | `server_id`, `cpu_percent`, `memory_bytes`, `tps`, `players` | Emitted on each metrics sampling tick. |
| `AlertTriggeredEvent` | `monitoring.alert_triggered` | `server_id`, `metric`, `threshold`, `current_value` | Emitted when a resource alert rule fires. |
| `AlertResolvedEvent` | `monitoring.alert_resolved` | `server_id`, `metric` | Emitted when a previously triggered alert normalizes. |

---

## 8. Versioning & Branch Runtime Events (`versioning`)

Location: `backend/app/modules/versioning/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `BranchCreatedEvent` | `branch.created` | `server_id`, `branch_name`, `branch_id` | Emitted when a new branch is created. |
| `BranchArchivedEvent` | `branch.archived` | `server_id`, `branch_name`, `branch_id` | Emitted when an active branch is archived. |
| `TagCreatedEvent` | `tag.created` | `server_id`, `tag_name`, `commit_id` | Emitted when an immutable tag is created. |
| `CommitCreatedEvent` | `commit.created` | `server_id`, `commit_id`, `message`, `branch_name` | Emitted when a new commit is created on a branch. |
| `MergeCommitCreatedEvent` | `commit.merged` | `server_id`, `commit_id`, `parent_commit_ids`, `branch_name` | Emitted when two branches/commits are merged. |
| `TestRunStartedEvent` | `test_run.started` | `server_id`, `test_id`, `commit_id`, `bot_count`, `duration_minutes` | Emitted when an isolated test run begins execution. |
| `TestRunCompletedEvent` | `test_run.completed` | `server_id`, `test_id`, `commit_id`, `passed`, `failure_reason` | Emitted when a test run completes. |
| `TestRunFailedEvent` | `test_run.failed` | `server_id`, `test_id`, `commit_id`, `failure_code`, `blamed_mod` | Emitted when a test run fails or crashes. |
| `BranchRuntimeStartedEvent` | `branch_runtime.started` | `server_id`, `branch_name`, `port` | Emitted when an isolated branch runtime container starts. |
| `BranchRuntimeStoppedEvent` | `branch_runtime.stopped` | `server_id`, `branch_name` | Emitted when an isolated branch runtime container stops. |
| `DataTemplateSavedEvent` | `data_template.saved` | `server_id`, `template_id`, `name` | Emitted when a quiescent Class-C data template is captured. |
| `CommitPromotedEvent` | `commit.promoted` | `server_id`, `commit_id`, `test_id`, `keep_world_changes`, `forced`, `actor_id` | Historical event retained for event-store deserialization. |
| `GitHubConnectedEvent` | `github.connected` | `server_id`, `repo_full_name` | Emitted when a server links a GitHub repository. |
| `GitHubDisconnectedEvent` | `github.disconnected` | `server_id` | Emitted when a GitHub remote connection is removed. |
| `GitHubCredentialsRotatedEvent` | `github.credentials_rotated` | `server_id` | Emitted when GitHub deploy key / credentials are rotated. |
| `GitHubSyncedEvent` | `github.synced` | `server_id`, `branch_name` | Emitted when fetch-first GitHub sync completes. |
| `GitHubPushedEvent` | `github.pushed` | `server_id`, `branch_name` | Emitted when a branch is pushed to GitHub. |
| `GitHubWebhookReceivedEvent` | `github.webhook_received` | `server_id`, `event_type`, `delivery_id` | Emitted when an HMAC-verified GitHub webhook is queued. |
| `ModpackInstalledEvent` | `modpack.installed` | `server_id`, `modpack_name`, `loader` | Emitted when a `.mrpack` or CurseForge modpack is installed. |
| `UpgradePlannedEvent` | `upgrade.planned` | `server_id`, `upgrade_id`, `target_version` | Emitted when a 1-click safe upgrade plan is computed. |
| `UpgradeManualBlockerResolvedEvent` | `upgrade.manual_blocker_resolved` | `server_id`, `upgrade_id`, `file_id` | Emitted when a manual CurseForge blocker jar is uploaded. |
| `UpgradeBranchPreparedEvent` | `upgrade.branch_prepared` | `server_id`, `upgrade_id`, `branch_name` | Emitted when an `upgrade/*` test branch is prepared. |
| `UpgradeTestStartedEvent` | `upgrade.test_started` | `server_id`, `upgrade_id`, `branch_name` | Emitted when an upgrade validation branch test starts. |
| `UpgradeAppliedEvent` | `upgrade.applied` | `server_id`, `upgrade_id` | Emitted when a safe upgrade is applied to `main`. |
| `UpgradeConfirmedEvent` | `upgrade.confirmed` | `server_id`, `upgrade_id` | Emitted when an upgrade passes the 4-step health gate and is confirmed. |
| `UpgradeRolledBackEvent` | `upgrade.rolled_back` | `server_id`, `upgrade_id` | Emitted when an upgrade triggers triad rollback. |
| `ServerP55SettingsUpdatedEvent` | `server.p55_settings_updated` | `server_id` | Emitted when P5.5 upgrade/health-gate settings are updated. |

---

## 9. Operations Events (`operations`)

Location: `backend/app/modules/operations/domain/events.py`

| Event Class | Event Name | Key Payload Fields | Description |
|---|---|---|---|
| `OperationStartedEvent` | `operation.started` | `operation_id`, `operation_type`, `target_id` | Emitted when an async multi-step operation starts. |
| `OperationStepEvent` | `operation.step` | `operation_id`, `step_name`, `status` | Emitted as operation steps progress. |
| `OperationLogEvent` | `operation.log` | `operation_id`, `message` | Emitted for structured operation progress logs. |
| `OperationCompletedEvent` | `operation.completed` | `operation_id`, `result` | Emitted when an operation completes successfully. |
| `OperationFailedEvent` | `operation.failed` | `operation_id`, `error` | Emitted when an operation fails terminally. |
| `OperationCancelledEvent` | `operation.cancelled` | `operation_id` | Emitted when cooperative cancellation completes. |
