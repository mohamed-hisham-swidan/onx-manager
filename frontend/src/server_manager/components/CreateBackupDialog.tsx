import { useState } from "react";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useCreateBackup } from "@/server_manager/hooks/useBackups";

interface CreateBackupDialogProps {
  onDone: () => void;
}

export function CreateBackupDialog({ onDone }: CreateBackupDialogProps) {
  const { data: servers } = useServersList();
  const createBackup = useCreateBackup();
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const form = new FormData(e.currentTarget);
    const serverId = form.get("server_id") as string;
    const backupType = form.get("backup_type") as string;
    if (!serverId) { setError("Please select a server."); return; }
    try {
      await createBackup.mutateAsync({ server_id: serverId, backup_type: backupType || undefined });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create backup");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
      <h3 className="font-semibold text-gray-900 dark:text-gray-100">Create Backup</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <select
          name="server_id"
          required
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Select a server...</option>
          {servers?.map((s) => (
            <option key={s.server_id} value={s.server_id}>{s.name}</option>
          ))}
        </select>
        <select
          name="backup_type"
          className="px-3 py-2 rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Default</option>
          <option value="full">Full</option>
          <option value="incremental">Incremental</option>
          <option value="world_only">World Only</option>
        </select>
      </div>
      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={createBackup.isPending}
        className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium transition-colors disabled:opacity-50"
      >
        {createBackup.isPending ? "Creating..." : "Create Backup"}
      </button>
    </form>
  );
}
