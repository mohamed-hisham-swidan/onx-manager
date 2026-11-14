import { useMemo, useState } from "react";
import { useBackupsList, useRestoreBackup, useVerifyBackup, useDeleteBackup } from "@/server_manager/hooks/useBackups";
import { useServersList } from "@/server_manager/hooks/useServers";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { EmptyState, ErrorState } from "@/components/ui/States";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { CreateBackupDialog } from "@/server_manager/components/CreateBackupDialog";
import { HashBadge } from "@/components/ui/HashBadge";
import { toast } from "@/stores/toastStore";
import { formatBytes, formatDateTime } from "@/server_manager/utils/format";
import type { BackupResponse } from "@/types";

const STATUS_FILTERS = ["all", "completed", "failed", "failed_timeout", "pending", "running"];

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-status-success-bg text-status-success border border-status-success-border",
  failed: "bg-status-danger-bg text-status-danger border border-status-danger-border",
  failed_timeout: "bg-status-warning-bg text-status-warning border border-status-warning-border",
  pending: "bg-status-warning-bg text-status-warning border border-status-warning-border",
  running: "bg-status-info-bg text-status-info border border-status-info-border animate-pulse",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Action failed";
}

export function BackupListPage() {
  const { data: backups, isLoading, error } = useBackupsList();
  const { data: servers } = useServersList();
  const restoreBackup = useRestoreBackup();
  const verifyBackup = useVerifyBackup();
  const deleteBackup = useDeleteBackup();
  const [showCreate, setShowCreate] = useState(false);
  const [serverFilter, setServerFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [deleteTarget, setDeleteTarget] = useState<BackupResponse | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<BackupResponse | null>(null);
  const [verifyResult, setVerifyResult] = useState<Record<string, string>>({});

  const serverMap = useMemo(
    () => new Map(servers?.map((s) => [s.server_id, s.name]) ?? []),
    [servers],
  );

  const filtered = useMemo(() => {
    return (backups ?? []).filter((b) => {
      if (serverFilter !== "all" && b.server_id !== serverFilter) return false;
      if (statusFilter !== "all" && b.status !== statusFilter) return false;
      return true;
    });
  }, [backups, serverFilter, statusFilter]);

  const stats = useMemo(() => {
    const total = backups?.length ?? 0;
    const totalBytes = (backups ?? []).reduce((sum, b) => sum + (b.size_bytes || 0), 0);
    const lastCompleted = (backups ?? [])
      .filter((b) => b.status === "completed" && b.completed_at)
      .sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? ""))[0];
    const failed = (backups ?? []).filter((b) => b.status === "failed").length;
    return { total, totalBytes, lastCompleted, failed };
  }, [backups]);

  function handleConfirmRestore() {
    if (!restoreTarget) return;
    restoreBackup.mutate(restoreTarget.backup_id, {
      onSuccess: () => toast("success", "Restore started", "Restoring the backup now."),
      onError: (err) => toast("error", "Restore failed", errorMessage(err)),
      onSettled: () => setRestoreTarget(null),
    });
  }

  async function handleVerify(backup: BackupResponse) {
    try {
      const result = await verifyBackup.mutateAsync(backup.backup_id);
      const label = result.valid ? "Valid" : "Invalid";
      setVerifyResult((prev) => ({ ...prev, [backup.backup_id]: label }));
      toast(result.valid ? "success" : "error", result.valid ? "Backup is valid" : "Backup is invalid");
    } catch {
      setVerifyResult((prev) => ({ ...prev, [backup.backup_id]: "Error" }));
      toast("error", "Verification failed", "Could not verify this backup.");
    }
  }

  function handleConfirmDelete() {
    if (!deleteTarget) return;
    deleteBackup.mutate(deleteTarget.backup_id, {
      onSuccess: () => toast("success", "Backup deleted", "The backup was removed."),
      onError: (err) => toast("error", "Delete failed", errorMessage(err)),
      onSettled: () => setDeleteTarget(null),
    });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Backups"
        description="Protect, restore, and verify your Minecraft world snapshots"
        icon="backup"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              disabled
              aria-disabled="true"
              aria-label="Class-C Secret Vault (Coming soon)"
              title="P3 Class-C Secret Vault / extraction is coming soon"
              className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg border border-border-default bg-surface-elevated px-3.5 py-2 text-sm font-medium text-text-muted/70"
            >
              <Icon name="lock" size={16} />
              <span>Secret Vault</span>
              <span className="rounded bg-surface-muted px-1.5 py-0.5 text-[10px] font-semibold text-text-muted">
                Coming soon
              </span>
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3.5 py-2 text-sm font-bold text-accent-contrast-text hover:bg-accent-hover shadow-2xs transition-colors cursor-pointer"
            >
              <Icon name="plus" size={16} />
              <span>New Backup</span>
            </button>
          </div>
        }
      />

      {showCreate && (
        <div className="mb-6">
          <CreateBackupDialog onDone={() => setShowCreate(false)} />
        </div>
      )}

      {isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : error ? (
        <ErrorState message={error instanceof Error ? error.message : "Failed to load backups"} />
      ) : backups && backups.length === 0 ? (
        <EmptyState
          icon="backup"
          title="No backups found"
          description="Create your first backup to protect your server data."
          action={
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-2 text-sm font-bold text-accent-contrast-text transition-colors hover:bg-accent-hover shadow-2xs cursor-pointer"
            >
              <Icon name="plus" size={16} />
              New Backup
            </button>
          }
        />
      ) : (
        <>
          {/* Slim Stat Strip */}
          <div className="mb-6 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 bg-surface-card border border-border-subtle rounded-xl divide-y sm:divide-y-0 sm:divide-x divide-border-subtle shadow-2xs">
            <div className="p-3.5 flex flex-col justify-center">
              <span className="text-xs font-medium text-text-muted">Total backups</span>
              <span className="mt-0.5 text-lg font-bold tabular-nums text-text-primary">{stats.total}</span>
            </div>

            <div className="p-3.5 flex flex-col justify-center">
              <span className="text-xs font-medium text-text-muted">Total size</span>
              <span className="mt-0.5 text-lg font-bold tabular-nums text-text-primary">{formatBytes(stats.totalBytes)}</span>
            </div>

            <div className="p-3.5 flex flex-col justify-center">
              <span className="text-xs font-medium text-text-muted">Last successful backup</span>
              <div className="mt-0.5 flex items-baseline gap-1.5 truncate">
                <span className="text-sm font-bold text-text-primary truncate">
                  {stats.lastCompleted ? serverMap.get(stats.lastCompleted.server_id) ?? "Server" : "None"}
                </span>
                {stats.lastCompleted?.completed_at && (
                  <span className="text-xs text-text-muted truncate">
                    {formatDateTime(stats.lastCompleted.completed_at)}
                  </span>
                )}
              </div>
            </div>

            <div className="p-3.5 flex flex-col justify-center">
              <span className="text-xs font-medium text-text-muted">Snapshot Engine</span>
              <div
                className="mt-0.5 flex items-center gap-1.5 text-xs font-semibold text-status-success cursor-help"
                title="CoW / Archive ready - zero-copy reflink supported"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
                <span>Instant copy available</span>
              </div>
            </div>
          </div>

          {/* Filter Toolbar */}
          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <div>
              <label className="sr-only" htmlFor="backup-server-filter">
                Filter by server
              </label>
              <select
                id="backup-server-filter"
                value={serverFilter}
                onChange={(e) => setServerFilter(e.target.value)}
                className="rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
              >
                <option value="all">All servers</option>
                {servers?.map((s) => (
                  <option key={s.server_id} value={s.server_id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="sr-only" htmlFor="backup-status-filter">
                Filter by status
              </label>
              <select
                id="backup-status-filter"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-lg border border-border-default bg-surface-card px-3 py-1.5 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus shadow-2xs"
              >
                {STATUS_FILTERS.map((s) => (
                  <option key={s} value={s}>
                    {s === "all" ? "All statuses" : s === "failed_timeout" ? "Failed (Timeout)" : s.charAt(0).toUpperCase() + s.slice(1)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching backups"
              description="No backups match your current filters."
            />
          ) : (
            <div className="overflow-hidden rounded-xl border border-border-subtle bg-surface-card shadow-2xs">
              <table className="w-full text-sm text-text-primary border-collapse">
                <thead>
                  <tr className="border-b border-border-subtle bg-surface-muted/40 text-xs font-semibold uppercase tracking-wider text-text-secondary">
                    <th className="px-4 py-3 text-left">Server</th>
                    <th className="hidden px-4 py-3 text-left sm:table-cell">Type</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="hidden px-4 py-3 text-left sm:table-cell">Size</th>
                    <th className="hidden px-4 py-3 text-left md:table-cell">Created</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle">
                  {filtered.map((b) => (
                    <tr
                      key={b.backup_id}
                      className="transition-colors hover:bg-surface-hover/50"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-text-primary">
                            {serverMap.get(b.server_id) ?? b.server_id}
                          </span>
                          <HashBadge hash={b.backup_id} />
                        </div>
                      </td>
                      <td className="hidden px-4 py-3 capitalize text-text-secondary sm:table-cell font-mono text-xs">
                        {b.backup_type}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                            STATUS_STYLES[b.status] ?? "bg-surface-elevated text-text-muted"
                          }`}
                        >
                          <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-80" aria-hidden="true" />
                          {b.status}
                        </span>
                      </td>
                      <td className="hidden px-4 py-3 font-mono text-xs text-text-secondary sm:table-cell">
                        {formatBytes(b.size_bytes)}
                      </td>
                      <td className="hidden px-4 py-3 text-xs text-text-muted md:table-cell">
                        {formatDateTime(b.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1.5">
                          {b.status === "completed" && (
                            <button
                              type="button"
                              onClick={() => setRestoreTarget(b)}
                              disabled={restoreBackup.isPending}
                              aria-label={`Restore ${b.backup_id}`}
                              title="Restore Backup"
                              className="inline-flex items-center gap-1 rounded-md border border-status-warning-border bg-status-warning-bg px-2.5 py-1 text-xs font-semibold text-status-warning transition-colors hover:bg-status-warning/20 disabled:opacity-40 cursor-pointer"
                            >
                              <Icon name="restart" size={13} />
                              <span className="hidden sm:inline">Restore</span>
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={() => handleVerify(b)}
                            disabled={verifyBackup.isPending}
                            aria-label={`Verify ${b.backup_id}`}
                            title={verifyResult[b.backup_id] ?? "Verify integrity"}
                            className="inline-flex items-center gap-1 rounded-md border border-border-default bg-surface-elevated px-2.5 py-1 text-xs font-medium text-text-secondary transition-colors hover:bg-surface-hover hover:text-text-primary disabled:opacity-40 cursor-pointer"
                          >
                            <Icon name="check" size={13} />
                            <span className="hidden sm:inline">{verifyResult[b.backup_id] ?? "Verify"}</span>
                          </button>
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(b)}
                            disabled={deleteBackup.isPending}
                            aria-label="Delete backup"
                            title="Delete backup"
                            className="rounded-md p-1.5 text-text-muted transition-colors hover:bg-status-danger-bg hover:text-status-danger disabled:opacity-40 cursor-pointer"
                          >
                            <Icon name="trash" size={15} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* Shared Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete backup?"
        description={
          deleteTarget
            ? `Are you sure you want to delete this backup from ${formatDateTime(deleteTarget.created_at)}? This action cannot be undone.`
            : undefined
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />

      {/* Shared Restore Confirmation Dialog */}
      <ConfirmDialog
        open={restoreTarget !== null}
        title="Restore backup?"
        description="Restoring will overwrite current server files with data from this snapshot. Make sure the server is stopped before restoring."
        confirmLabel="Restore"
        cancelLabel="Cancel"
        variant="danger"
        onConfirm={handleConfirmRestore}
        onCancel={() => setRestoreTarget(null)}
      />
    </div>
  );
}
