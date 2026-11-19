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
        if event_name == "BackupStartedEvent":
            return "Backup creation started", "backup.started"
        if event_name == "BackupCompletedEvent":
            bid = getattr(event, "backup_id", "")[:8]
            return f"Backup completed (ID: {bid})", "backup.completed"
        if event_name == "BackupFailedEvent":
            reason = getattr(event, "reason", "unknown")
            return f"Backup failed: {reason}", "backup.failed"
        if event_name == "BackupRestoredEvent":
            bid = getattr(event, "backup_id", "")[:8]
            return f"Restored from backup (ID: {bid})", "backup.restored"
        if event_name == "BackupDeletedEvent":
            bid = getattr(event, "backup_id", "")[:8]
            return f"Backup deleted (ID: {bid})", "backup.deleted"

        # Exposure
        if event_name == "ServerExposureEnabledEvent":
            method = getattr(event, "method", "exposure")
            return f"Public exposure enabled via {method}", "exposure.enabled"
        if event_name == "ServerExposureDisabledEvent":
            return "Public exposure disabled", "exposure.disabled"

        # Versioning
        if event_name == "BranchCreatedEvent":
            bname = getattr(event, "branch_name", "branch")
            return f"Branch '{bname}' created", "versioning.branch_created"
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
        if event_name == "DataTemplateSavedEvent":
            tname = getattr(event, "template_name", "template")
            return f"Data template '{tname}' saved", "versioning.data_template_saved"
        # Generic fallback for any other server-scoped event
        snake_name = "".join(
            ["_" + c.lower() if c.isupper() else c for c in event_name]
        ).lstrip("_")
        return f"Event: {event_name}", snake_name
