import { useState } from "react";
import { useBackupsList, useRestoreBackup, useVerifyBackup, useDeleteBackup } from "@/server_manager/hooks/useBackups";
import { useServersList } from "@/server_manager/hooks/useServers";
import { Skeleton, TableSkeleton } from "@/components/Skeleton";
import { EmptyState } from "@/components/EmptyState";
import { CreateBackupDialog } from "@/server_manager/components/CreateBackupDialog";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "—";
  return new Date(dateStr).toLocaleString();
}

export function BackupListPage() {
  const { data: backups, isLoading, error } = useBackupsList();
  const { data: servers } = useServersList();
  const restoreBackup = useRestoreBackup();
  const verifyBackup = useVerifyBackup();
  const deleteBackup = useDeleteBackup();
  const [showCreate, setShowCreate] = useState(false);
  const [verifyResult, setVerifyResult] = useState<Record<string, string>>({});

  const serverMap = new Map(servers?.map((s) => [s.server_id, s.name]) ?? []);

  if (isLoading) return <TableSkeleton rows={6} cols={6} />;

  if (error) {
    return (
      <p className="text-red-600 dark:text-red-400">
        {error instanceof Error ? error.message : "Failed to load backups"}
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">Backups</h2>
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
        >
          {showCreate ? "Cancel" : "+ New Backup"}
        </button>
      </div>

      {showCreate && (
        <div className="mb-6">
          <CreateBackupDialog onDone={() => setShowCreate(false)} />
        </div>
      )}

      {backups && backups.length > 0 ? (
        <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/50">
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Server</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Type</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Status</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Size</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Created</th>
                <th className="text-left px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Completed</th>
                <th className="text-right px-4 py-3 font-medium text-gray-600 dark:text-gray-400">Actions</th>
              </tr>
            </thead>
            <tbody>
              {backups.map((b) => (
                <tr key={b.backup_id} className="border-b border-gray-100 dark:border-gray-700/50 hover:bg-gray-50 dark:hover:bg-gray-700/30">
                  <td className="px-4 py-3 text-gray-900 dark:text-gray-100">{serverMap.get(b.server_id) ?? b.server_id}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400 capitalize">{b.backup_type}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      b.status === "completed" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
                      b.status === "failed" ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" :
                      "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                    }`}>
                      {b.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{formatBytes(b.size_bytes)}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{formatDate(b.created_at)}</td>
                  <td className="px-4 py-3 text-gray-600 dark:text-gray-400">{formatDate(b.completed_at)}</td>
                  <td className="px-4 py-3 text-right space-x-1">
                    {b.status === "completed" && (
                      <button
                        onClick={() => {
                          if (confirm("Restore this backup? This may overwrite current server data."))
                            restoreBackup.mutate(b.backup_id);
                        }}
                        disabled={restoreBackup.isPending}
                        className="px-2 py-1 text-xs rounded bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50 disabled:opacity-50"
                      >
                        Restore
                      </button>
                    )}
                    <button
                      onClick={async () => {
                        try {
                          const result = await verifyBackup.mutateAsync(b.backup_id);
                          setVerifyResult((prev) => ({ ...prev, [b.backup_id]: result.valid ? "Valid" : "Invalid" }));
                        } catch {
                          setVerifyResult((prev) => ({ ...prev, [b.backup_id]: "Error" }));
                        }
                      }}
                      disabled={verifyBackup.isPending}
                      className="px-2 py-1 text-xs rounded bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400 hover:bg-purple-200 dark:hover:bg-purple-900/50 disabled:opacity-50"
                    >
                      {verifyResult[b.backup_id] ?? "Verify"}
                    </button>
                    <button
                      onClick={() => {
                        if (confirm("Delete this backup?")) deleteBackup.mutate(b.backup_id);
                      }}
                      disabled={deleteBackup.isPending}
                      className="px-2 py-1 text-xs rounded bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon="◈"
          title="No backups found"
          description="Create your first backup to protect your server data."
          action={
            <button
              onClick={() => setShowCreate(true)}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors"
            >
              + New Backup
            </button>
          }
        />
      )}
    </div>
  );
}
