import { useMemo } from "react";
import { formatBytes, formatDateTime, formatRelativeTime } from "@/server_manager/utils/format";
import { resolveBackupServer } from "./backupUtils";
import type { BackupResponse } from "@/types";

export interface BackupStatsStripProps {
  backups: BackupResponse[];
  serverMap: Map<string, string>;
  serversResolved: boolean;
  onFilterFailed?: () => void;
}

export function BackupStatsStrip({
  backups,
  serverMap,
  serversResolved,
  onFilterFailed,
}: BackupStatsStripProps) {
  const stats = useMemo(() => {
    const total = backups.length;
    let tier1Count = 0;
    let tier2Count = 0;
    let totalBytes = 0;
    let failedCount = 0;
    let inProgressCount = 0;
    let pinnedCount = 0;
    const serverIds = new Set<string>();

    for (const b of backups) {
      if (b.tier === "tier_2") tier2Count += 1;
      else tier1Count += 1;
      totalBytes += b.size_bytes || 0;
      if (b.server_id) serverIds.add(b.server_id);
      if (b.status === "failed" || b.status === "failed_timeout") failedCount += 1;
      if (b.status === "in_progress" || b.status === "running") inProgressCount += 1;
      if (b.pinned) pinnedCount += 1;
    }

    const lastCompleted = backups
      .filter((b) => b.status === "completed")
      .sort((a, b) =>
        (b.completed_at ?? b.created_at).localeCompare(a.completed_at ?? a.created_at),
      )[0];

    return {
      total,
      tier1Count,
      tier2Count,
      totalBytes,
      uniqueServerCount: serverIds.size,
      lastCompleted,
      failedCount,
      inProgressCount,
      pinnedCount,
    };
  }, [backups]);

  const lastServer = stats.lastCompleted
    ? resolveBackupServer(stats.lastCompleted, serverMap, serversResolved)
    : null;
  const lastTimestamp = stats.lastCompleted
    ? stats.lastCompleted.completed_at ?? stats.lastCompleted.created_at
    : null;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
      <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs flex flex-col justify-between">
        <span className="text-xs font-medium text-text-muted">Total Backups</span>
        <div className="mt-1.5">
          <div className="text-2xl font-bold tracking-tight tabular-nums text-text-primary">
            {stats.total}
          </div>
          <p className="mt-1 text-xs text-text-muted">
            {stats.tier1Count} {stats.tier1Count === 1 ? "snapshot" : "snapshots"} ·{" "}
            {stats.tier2Count} {stats.tier2Count === 1 ? "archive" : "archives"}
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs flex flex-col justify-between">
        <span className="text-xs font-medium text-text-muted">Storage Used</span>
        <div className="mt-1.5">
          <div className="text-2xl font-bold tracking-tight tabular-nums text-text-primary">
            {formatBytes(stats.totalBytes)}
          </div>
          <p className="mt-1 text-xs text-text-muted">
            Across {stats.uniqueServerCount}{" "}
            {stats.uniqueServerCount === 1 ? "server" : "servers"}
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs flex flex-col justify-between">
        <span className="text-xs font-medium text-text-muted">Last Successful</span>
        <div className="mt-1.5 min-w-0">
          {stats.lastCompleted && lastServer ? (
            <>
              <div
                className={`text-sm font-semibold truncate ${
                  lastServer.deleted ? "text-text-muted italic" : "text-text-primary"
                }`}
              >
                {lastServer.name}
              </div>
              <p
                className="mt-1 text-xs text-text-muted truncate"
                title={lastTimestamp ? formatDateTime(lastTimestamp) : undefined}
              >
                {lastTimestamp ? formatRelativeTime(lastTimestamp) || "just now" : "Completed"}
              </p>
            </>
          ) : (
            <p className="text-sm font-medium text-text-muted">No completed backups</p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-border-subtle bg-surface-card p-4 shadow-2xs flex flex-col justify-between">
        <span className="text-xs font-medium text-text-muted">Backup Health</span>
        <div className="mt-1.5">
          {stats.failedCount > 0 ? (
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-status-danger shrink-0" aria-hidden="true" />
              {onFilterFailed ? (
                <button
                  type="button"
                  onClick={onFilterFailed}
                  className="text-sm font-semibold text-status-danger hover:underline cursor-pointer text-left"
                >
                  {stats.failedCount} Failed
                </button>
              ) : (
                <span className="text-sm font-semibold text-status-danger">
                  {stats.failedCount} Failed
                </span>
              )}
            </div>
          ) : stats.inProgressCount > 0 ? (
            <div className="flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full bg-status-info animate-pulse shrink-0"
                aria-hidden="true"
              />
              <span className="text-sm font-semibold text-status-info">
                {stats.inProgressCount} Running
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full bg-status-success shrink-0"
                aria-hidden="true"
              />
              <span className="text-sm font-semibold text-status-success">All Healthy</span>
            </div>
          )}
          <p className="mt-1 text-xs text-text-muted">
            {stats.pinnedCount} pinned
          </p>
        </div>
      </div>
    </div>
  );
}
