from __future__ import annotations

import logging
import time
from typing import Any

from app.core.event_bus import DomainEvent, EventHandler
from app.modules.activity.domain.entities import ServerActivityLog
from app.modules.activity.domain.repository import ActivityRepository

logger = logging.getLogger(__name__)


class ActivityEventSubscriber(EventHandler):
    """Subscribes to domain events and persists operational activity logs."""

    def __init__(self, repository: ActivityRepository) -> None:
        self._repository = repository

    async def handle(self, event: DomainEvent) -> None:
        try:
            server_id = getattr(event, "server_id", None)
            if not server_id:
                # Only log activity scoped to a server
                return

            event_name = type(event).__name__
            summary, event_type = self._resolve_summary_and_type(event, event_name)
            if not summary:
                return

            actor_type = getattr(event, "actor_type", "system")
            actor_id = getattr(event, "actor_id", None)
            branch_name = getattr(event, "branch_name", None)

            details: dict[str, Any] = {}
            if hasattr(event, "model_dump"):
                details = event.model_dump()
            elif hasattr(event, "__dict__"):
                details = dict(event.__dict__)

            # Sanitize details
            details.pop("server_id", None)

            log_entry = ServerActivityLog(
                server_id=str(server_id),
                event_type=event_type,
                summary=summary,
                timestamp=getattr(event, "timestamp", None) or time.time(),
                actor_type=str(actor_type) if actor_type else "system",
                actor_id=str(actor_id) if actor_id else None,
                details=details,
                branch_name=str(branch_name) if branch_name else None,
            )
            await self._repository.save(log_entry)
        except Exception as e:
            logger.warning("ActivityEventSubscriber failed to persist event: %s", e)

    def _resolve_summary_and_type(
        self, event: DomainEvent, event_name: str
    ) -> tuple[str, str]:
        # Server lifecycle
        if event_name == "ServerCreatedEvent":
            name = getattr(event, "name", "")
            mv = getattr(event, "minecraft_version", "")
            details_str = f" ({mv})" if mv else ""
            summary = (
                f"Server '{name}' created{details_str}"
                if name
                else f"Server created{details_str}"
            )
            return summary.strip(), "server.created"
        if event_name == "ServerStartingEvent":
            return "Server starting", "server.starting"
        if event_name == "ServerStartedEvent":
            return "Server started successfully", "server.started"
        if event_name == "ServerStoppingEvent":
            return "Server stopping", "server.stopping"
        if event_name == "ServerStoppedEvent":
            return "Server stopped", "server.stopped"
        if event_name == "ServerCrashedEvent":
            code = getattr(event, "exit_code", "unknown")
            return f"Server crashed (exit code: {code})", "server.crashed"
        if event_name == "ServerConfigChangedEvent":
            return "Server configuration updated", "server.config_changed"
        if event_name == "ServerDeletedEvent":
            return "Server deleted", "server.deleted"
        if event_name == "ServerConvertedToAdvancedEvent":
            return "Server converted to advanced", "server.converted.to_advanced"
        if event_name == "ServerConvertedToSimpleEvent":
            return "Server converted to simple", "server.converted.to_simple"

        # Plugins / Mods
        if event_name == "PluginInstalledEvent":
            name = getattr(event, "name", None) or getattr(event, "plugin_id", "plugin")
            ver = getattr(event, "version", "")
            ver_suffix = f" (v{ver})" if ver else ""
            return f"Plugin/mod '{name}' installed{ver_suffix}", "plugin.installed"
        if event_name == "PluginEnabledEvent":
            pid = getattr(event, "plugin_id", "plugin")
            return f"Plugin/mod '{pid}' enabled", "plugin.enabled"
        if event_name == "PluginDisabledEvent":
            pid = getattr(event, "plugin_id", "plugin")
            return f"Plugin/mod '{pid}' disabled", "plugin.disabled"
        if event_name == "PluginUninstalledEvent":
            pid = getattr(event, "plugin_id", "plugin")
            return f"Plugin/mod '{pid}' uninstalled", "plugin.uninstalled"
        if event_name == "PluginUpdatedEvent":
            pid = getattr(event, "plugin_id", "plugin")
            return f"Plugin/mod '{pid}' updated", "plugin.updated"

        # Backups
        if event_name in {
            "BackupStartedEvent",
            "BackupCompletedEvent",
            "BackupFailedEvent",
            "BackupRestoredEvent",
            "BackupDeletedEvent",
        }:
            raw_tier = str(getattr(event, "tier", "") or "").strip().lower()
            tier_label = "Tier-2" if raw_tier == "tier_2" else "Tier-1"
            if event_name == "BackupStartedEvent":
                return f"{tier_label} backup creation started", "backup.started"
            if event_name == "BackupCompletedEvent":
                bid = getattr(event, "backup_id", "")[:8]
                return f"{tier_label} backup completed (ID: {bid})", "backup.completed"
            if event_name == "BackupFailedEvent":
                reason = getattr(event, "reason", "unknown")
                return f"{tier_label} backup failed: {reason}", "backup.failed"
            if event_name == "BackupRestoredEvent":
                bid = getattr(event, "backup_id", "")[:8]
                return f"Restored from {tier_label} backup (ID: {bid})", "backup.restored"
            bid = getattr(event, "backup_id", "")[:8]
            return f"{tier_label} backup deleted (ID: {bid})", "backup.deleted"

        # Exposure
        if event_name == "ServerExposureEnabledEvent":
            method = getattr(event, "method", "exposure")
            return f"Public exposure enabled via {method}", "exposure.enabled"
        if event_name == "ServerExposureDisabledEvent":
            return "Public exposure disabled", "exposure.disabled"
        if event_name == "BranchExposureEnabledEvent":
            bname = getattr(event, "branch_name", "branch")
            method = getattr(event, "method", "exposure")
            return f"Branch '{bname}' exposure enabled via {method}", "branch_exposure_enabled"
        if event_name == "BranchExposureDisabledEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' exposure disabled", "branch_exposure_disabled"

        # Versioning
        if event_name == "BranchCreatedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' created", "versioning.branch_created"
        if event_name == "BranchDeletedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' deleted", "versioning.branch_deleted"
        if event_name == "CommitCreatedEvent":
            msg = getattr(event, "message", "")
            bname = getattr(event, "branch_name", "main")
            return (
                f"Snapshot commit '{msg}' created on branch '{bname}'",
                "versioning.commit_created",
            )
        if event_name == "TestRunStartedEvent":
            cid = getattr(event, "commit_id", "")[:8]
            bots = getattr(event, "bot_count", 1)
            return (
                f"Isolated test run started ({bots} bots) for commit {cid}",
                "versioning.test_started",
            )
        if event_name == "TestRunCompletedEvent":
            passed = getattr(event, "passed", False)
            if passed:
                return "Isolated bot verification passed", "versioning.test_completed"
            reason = getattr(event, "failure_reason", "verification failed")
            return f"Isolated bot verification failed: {reason}", "versioning.test_completed"
        if event_name == "CommitPromotedEvent":
            cid = getattr(event, "commit_id", "")[:8]
            return f"Test commit {cid} promoted to production", "versioning.promoted"
        if event_name == "BranchRuntimeStartedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' runtime started", "versioning.branch_started"
        if event_name == "BranchRuntimeStoppedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' runtime stopped", "versioning.branch_stopped"
        if event_name == "BranchRuntimeDestroyedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' container destroyed", "versioning.branch_destroyed"
        if event_name == "SettingsCommittedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Settings committed on branch '{bname}'", "settings_committed"
        if event_name == "SettingsBranchCreatedEvent":
            bname = getattr(event, "branch_name", "settings")
            return (
                f"Pending settings branch '{bname}' created for next restart",
                "settings_branch_created",
            )
        if event_name == "SettingsBranchAutoMergedOnRestartEvent":
            src = getattr(event, "source_branch", "settings")
            return (
                f"Auto-merged pending settings '{src}' into main on restart",
                "settings_branch_auto_merged_on_restart",
            )
        if event_name == "DataTemplateSavedEvent":
            tname = getattr(event, "template_name", "template")
            return f"Data template '{tname}' saved", "versioning.data_template_saved"
        if event_name == "GitHubConnectedEvent":
            remote_url = getattr(event, "remote_url", "")
            auth_method = getattr(event, "auth_method", "")
            return (
                f"Connected GitHub repository {remote_url} ({auth_method})",
                "versioning.github_connected",
            )
        if event_name == "GitHubDisconnectedEvent":
            remote_url = getattr(event, "remote_url", "")
            preserved = getattr(event, "local_history_preserved", True)
            suffix = " (local history preserved)" if preserved else ""
            return (
                f"Disconnected GitHub repository {remote_url}{suffix}",
                "versioning.github_disconnected",
            )
        if event_name == "GitHubCredentialsRotatedEvent":
            auth_method = getattr(event, "auth_method", "")
            credential_rotated = getattr(event, "credential_rotated", False)
            webhook_secret_rotated = getattr(event, "webhook_secret_rotated", False)
            webhook_enabled = getattr(event, "webhook_enabled", False)
            if credential_rotated and webhook_secret_rotated:
                summary = f"Rotated GitHub {auth_method} credential and webhook secret"
            elif credential_rotated:
                summary = f"Rotated GitHub {auth_method} credential"
            elif webhook_secret_rotated:
                summary = "Rotated GitHub webhook secret"
            else:
                state = "enabled" if webhook_enabled else "disabled"
                summary = f"Updated GitHub webhook configuration ({state})"
            return summary, "versioning.github_credentials_rotated"
        if event_name == "GitHubSyncedEvent":
            sync_status = getattr(event, "sync_status", "")
            trigger = getattr(event, "trigger", "manual")
            main_fast_forwarded = getattr(event, "main_fast_forwarded", False)
            if sync_status == "conflict":
                if getattr(event, "branch_name", None) is None:
                    event.branch_name = "main"
                return (
                    f"GitHub sync conflict on 'main' ({trigger}): "
                    "non-fast-forward update rejected",
                    "versioning.github_synced",
                )
            if main_fast_forwarded:
                main_sha = getattr(event, "main_sha", None) or ""
                return (
                    f"GitHub sync ({trigger}) fast-forwarded 'main' to {main_sha[:8]}",
                    "versioning.github_synced",
                )
            return (
                f"GitHub sync ({trigger}) completed with status '{sync_status}'",
                "versioning.github_synced",
            )
        if event_name == "GitHubPushedEvent":
            branch_name = getattr(event, "branch_name", "")
            commit_sha = getattr(event, "commit_sha", "") or ""
            return (
                f"Pushed branch '{branch_name}' ({commit_sha[:8]}) to GitHub",
                "versioning.github_pushed",
            )
        if event_name == "GitHubWebhookReceivedEvent":
            gh_event = (
                getattr(event, "webhook_event", None)
                or getattr(event, "event_type", "webhook")
            )
            did = str(getattr(event, "delivery_id", ""))[:16]
            if getattr(event, "redelivered", False):
                summary = f"Redelivered GitHub '{gh_event}' webhook ({did})"
            elif getattr(event, "deduplicated", False):
                summary = f"Deduplicated GitHub '{gh_event}' webhook ({did})"
            else:
                summary = f"Received GitHub '{gh_event}' webhook ({did})"
            return summary, "versioning.github_webhook_received"
        if event_name == "ModpackInstalledEvent":
            source = getattr(event, "source", "")
            version_label = getattr(event, "version_label", "")
            loader_id = getattr(event, "loader_id", "")
            mc_version = getattr(event, "mc_version", "")
            return (
                f"Installed {source} modpack '{version_label}' ({loader_id} {mc_version})",
                "modpack.installed",
            )
        if event_name == "UpgradePlannedEvent":
            target_mc = getattr(event, "target_mc", "")
            target_loader_id = getattr(event, "target_loader_id", "")
            target_loader_version = getattr(event, "target_loader_version", "")
            status = getattr(event, "status", "")
            return (
                f"Planned upgrade to Minecraft {target_mc} "
                f"({target_loader_id} {target_loader_version}) [{status}]",
                "upgrade.planned",
            )
        if event_name == "UpgradeManualBlockerResolvedEvent":
            upgrade_id = str(getattr(event, "upgrade_id", ""))
            return (
                f"Resolved manual download blocker for upgrade {upgrade_id[:8]}",
                "upgrade.manual_upload_resolved",
            )
        if event_name == "UpgradeBranchPreparedEvent":
            branch_name = getattr(event, "branch_name", "")
            target_mc = getattr(event, "target_mc", "")
            status = getattr(event, "status", "")
            return (
                f"Prepared upgrade branch '{branch_name}' for Minecraft {target_mc} ({status})",
                "upgrade.branch_prepared",
            )
        if event_name == "UpgradeTestStartedEvent":
            branch_name = getattr(event, "branch_name", "")
            return (
                f"Started isolated upgrade test on branch '{branch_name}'",
                "upgrade.test_started",
            )
        if event_name == "UpgradeAppliedEvent":
            target_mc = getattr(event, "target_mc", "")
            target_loader_id = getattr(event, "target_loader_id", "")
            target_loader_version = getattr(event, "target_loader_version", "")
            return (
                f"Applied upgrade to Minecraft {target_mc} "
                f"({target_loader_id} {target_loader_version}); rollback backup pinned",
                "upgrade.applied",
            )
        if event_name == "UpgradeConfirmedEvent":
            target_mc = getattr(event, "target_mc", "")
            return (
                f"Confirmed upgrade to Minecraft {target_mc} and unpinned rollback artifacts",
                "upgrade.confirmed",
            )
        if event_name == "UpgradeRolledBackEvent":
            target_mc = getattr(event, "target_mc", "")
            reason = getattr(event, "reason", "") or "triad restored"
            return (
                f"Rolled back upgrade to Minecraft {target_mc}: {reason}",
                "upgrade.rolled_back",
            )
        if event_name == "ServerP55SettingsUpdatedEvent":
            return (
                "Updated server modpack & upgrade health-gate settings",
                "server.p55_settings_updated",
            )
        # Generic fallback for any other server-scoped event
        snake_name = "".join(
            ["_" + c.lower() if c.isupper() else c for c in event_name]
        ).lstrip("_")
        return f"Event: {event_name}", snake_name
