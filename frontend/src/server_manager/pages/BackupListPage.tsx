import { useMemo, useState } from "react";
import { useBackupsList, useRestoreBackup, useVerifyBackup, useDeleteBackup } from "@/server_manager/hooks/useBackups";
import { useServersList } from "@/server_manager/hooks/useServers";
import { PageHeader } from "@/components/ui/PageHeader";
import { Icon } from "@/components/ui/Icon";
import { StatCard } from "@/components/ui/StatCard";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/Skeleton";
import { CreateBackupDialog } from "@/server_manager/components/CreateBackupDialog";
import { toast } from "@/stores/toastStore";
import { formatBytes, formatDateTime } from "@/server_manager/utils/format";
import type { BackupResponse } from "@/types";

const STATUS_FILTERS = ["all", "completed", "failed", "failed_timeout", "pending", "running"];

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400",
  failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  failed_timeout: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  pending: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400",
  running: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
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

  function handleRestore(backup: BackupResponse) {
    restoreBackup.mutate(backup.backup_id, {
      onSuccess: () => toast("success", "Restore started", "Restoring the backup now."),
      onError: (err) => toast("error", "Restore failed", errorMessage(err)),
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
    <div>
      <PageHeader
        title="Backups"
        description="Protect and restore your server data"
        icon="backup"
        actions={
          <button
            onClick={() => setShowCreate(!showCreate)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
          >
            <Icon name="plus" size={16} />
            {showCreate ? "Cancel" : "New Backup"}
          </button>
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
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700"
            >
              <Icon name="plus" size={16} />
              New Backup
            </button>
          }
        />
      ) : (
        <>
          <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <StatCard icon="backup" label="Total backups" value={stats.total} />
            <StatCard icon="server" label="Total size" value={formatBytes(stats.totalBytes)} />
            <StatCard
              icon="check"
              label="Last successful backup"
              value={stats.lastCompleted ? serverMap.get(stats.lastCompleted.server_id) ?? "Server" : "None"}
              sublabel={stats.lastCompleted ? formatDateTime(stats.lastCompleted.completed_at) : undefined}
              color="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
            />
          </div>

          <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="sr-only" htmlFor="backup-server-filter">
              Filter by server
            </label>
            <select
              id="backup-server-filter"
              value={serverFilter}
              onChange={(e) => setServerFilter(e.target.value)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
            >
              <option value="all">All servers</option>
              {servers?.map((s) => (
                <option key={s.server_id} value={s.server_id}>
                  {s.name}
                </option>
              ))}
            </select>
            <label className="sr-only" htmlFor="backup-status-filter">
              Filter by status
            </label>
            <select
              id="backup-status-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300"
            >
              {STATUS_FILTERS.map((s) => (
                <option key={s} value={s}>
                  {s === "all" ? "All statuses" : s === "failed_timeout" ? "Failed (Timeout)" : s.charAt(0).toUpperCase() + s.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {filtered.length === 0 ? (
            <EmptyState
              icon="search"
              title="No matching backups"
              description="No backups match your current filters."
            />
          ) : (
            <div className="overflow-hidden rounded-xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/50">
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Server</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Type</th>
                    <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">Status</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 sm:table-cell">Size</th>
                    <th className="hidden px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400 md:table-cell">Created</th>
                    <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((b) => (
                    <tr
                      key={b.backup_id}
                      className="border-b border-gray-100 hover:bg-gray-50 dark:border-gray-700/50 dark:hover:bg-gray-700/30"
                    >
                      <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                        {serverMap.get(b.server_id) ?? b.server_id}
                      </td>
                      <td className="hidden px-4 py-3 capitalize text-gray-600 dark:text-gray-400 sm:table-cell">
                        {b.backup_type}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            STATUS_STYLES[b.status] ?? "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-400"
                          }`}
                        >
                          <span className="mr-1.5 h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
                          {b.status}
                        </span>
                      </td>
                      <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 sm:table-cell">
                        {formatBytes(b.size_bytes)}
                      </td>
                      <td className="hidden px-4 py-3 text-gray-600 dark:text-gray-400 md:table-cell">
                        {formatDateTime(b.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          {b.status === "completed" && (
                            <button
                              onClick={() => handleRestore(b)}
                              disabled={restoreBackup.isPending}
                              aria-label={`Restore ${b.backup_id}`}
                              title="Restore"
                              className="rounded-lg p-1.5 text-blue-600 transition-colors hover:bg-blue-100 hover:text-blue-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-blue-400 dark:hover:bg-blue-900/30 dark:hover:text-blue-300"
                            >
                              <Icon name="restart" size={16} />
                            </button>
                          )}
                          <button
                            onClick={() => handleVerify(b)}
                            disabled={verifyBackup.isPending}
                            aria-label={`Verify ${b.backup_id}`}
                            title={verifyResult[b.backup_id] ?? "Verify"}
                            className="rounded-lg p-1.5 text-purple-600 transition-colors hover:bg-purple-100 hover:text-purple-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-purple-400 dark:hover:bg-purple-900/30 dark:hover:text-purple-300"
                          >
                            <Icon name="check" size={16} />
                          </button>
                          <button
                            onClick={() => setDeleteTarget(b)}
                            disabled={deleteBackup.isPending}
                            aria-label={`Delete ${b.backup_id}`}
                            title="Delete"
                            className="rounded-lg p-1.5 text-red-600 transition-colors hover:bg-red-100 hover:text-red-700 disabled:opacity-40 disabled:hover:bg-transparent dark:text-red-400 dark:hover:bg-red-900/30 dark:hover:text-red-300"
                          >
                            <Icon name="trash" size={16} />
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

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete backup?"
        description={
          deleteTarget
            ? `This permanently deletes the backup for "${serverMap.get(deleteTarget.server_id) ?? deleteTarget.server_id}".`
            : undefined
        }
        confirmLabel="Delete"
        cancelLabel="Cancel"
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
