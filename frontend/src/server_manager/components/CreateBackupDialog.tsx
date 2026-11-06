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
    <form onSubmit={handleSubmit} className="bg-surface-card rounded-xl border border-border-default p-4 space-y-3">
      <h3 className="font-semibold text-text-primary">Create Backup</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <select
          name="server_id"
          aria-label="Select server"
          required
          className="px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
        >
          <option value="">Select a server...</option>
          {servers?.map((s) => (
            <option key={s.server_id} value={s.server_id}>{s.name}</option>
          ))}
        </select>
        <select
          name="backup_type"
          aria-label="Backup type"
          className="px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
        >
          <option value="full">Full Backup</option>
          <option value="worlds">Worlds</option>
          <option value="world">World</option>
          <option value="nether">Nether</option>
          <option value="end">End</option>
          <option value="plugins">Plugins</option>
          <option value="config">Config</option>
        </select>
      </div>
      {error && <p role="alert" className="text-sm text-status-danger">{error}</p>}
      <button
        type="submit"
        disabled={createBackup.isPending}
        className="px-4 py-2 rounded-lg bg-accent-primary hover:bg-accent-hover text-accent-contrast-text text-sm font-medium transition-colors disabled:opacity-50"
      >
        {createBackup.isPending ? "Creating..." : "Create Backup"}
      </button>
    </form>
  );
}
