import { useState } from "react";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useCreateBackup } from "@/server_manager/hooks/useBackups";
import { Icon } from "@/components/ui/Icon";
import type { CreateBackupRequest } from "@/types";

interface CreateBackupDialogProps {
  onDone: () => void;
  defaultServerId?: string;
}

const TIER_1_RETENTION = "Retention: last 5 unpinned. Pinned backups are exempt from automated retention pruning.";
const TIER_2_RETENTION = "Retention: 7 daily + 4 weekly unpinned. Pinned backups are exempt from automated retention pruning.";

export function CreateBackupDialog({ onDone, defaultServerId }: CreateBackupDialogProps) {
  const { data: servers } = useServersList();
  const createBackup = useCreateBackup();
  const [error, setError] = useState<string | null>(null);
  const [tier, setTier] = useState<"tier_1" | "tier_2">("tier_1");
  const [archiveFormat, setArchiveFormat] = useState<"tar.zst" | "tar.gz">("tar.zst");
  const [includeCasJars, setIncludeCasJars] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState(defaultServerId ?? "");

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    const form = new FormData(e.currentTarget);
    const serverId = selectedServerId || (form.get("server_id") as string) || "";
    const backupType = (form.get("backup_type") as string) || "full";
    if (!serverId) { setError("Please select a server."); return; }
    try {
      const body: CreateBackupRequest = {
        server_id: serverId,
        backup_type: backupType,
        tier,
      };
      if (tier === "tier_2") {
        body.archive_format = archiveFormat;
        body.include_cas_jars = includeCasJars;
      }
      await createBackup.mutateAsync(body);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create backup");
    }
  };

  const isTier2 = tier === "tier_2";

  return (
    <form onSubmit={handleSubmit} className="bg-surface-card rounded-xl border border-border-default p-4 space-y-3">
      <h3 className="font-semibold text-text-primary">Create Backup</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <select
          name="server_id"
          aria-label="Select server"
          value={selectedServerId}
          onChange={(e) => setSelectedServerId(e.target.value)}
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
          defaultValue="full"
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

      {/* Tier Selector */}
      <fieldset className="border border-border-default rounded-lg p-3">
        <legend className="px-2 text-xs font-semibold text-text-secondary">Backup Tier</legend>
        <div className="flex gap-2">
          <label className="inline-flex items-center gap-2 cursor-pointer select-none">
            <input
              type="radio"
              name="tier"
              value="tier_1"
              checked={tier === "tier_1"}
              onChange={() => setTier("tier_1")}
              className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
            />
            <span className="text-sm font-medium text-text-primary">Tier-1 Snapshot</span>
          </label>
          <label className="inline-flex items-center gap-2 cursor-pointer select-none">
            <input
              type="radio"
              name="tier"
              value="tier_2"
              checked={tier === "tier_2"}
              onChange={() => setTier("tier_2")}
              className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
            />
            <span className="text-sm font-medium text-text-primary">Tier-2 Archive</span>
          </label>
        </div>
        <p className={`mt-2 text-sm ${isTier2 ? "text-text-primary" : "text-text-muted"}`}>
          {isTier2
            ? "Self-contained portable archive with chunked AEAD envelope encryption. " + TIER_2_RETENTION
            : "Instant directory snapshot finalized with integrity manifest. Zero-copy reflink storage. " + TIER_1_RETENTION}
        </p>
      </fieldset>

      {isTier2 && (
        <fieldset data-testid="tier-2-options" className="border border-border-default rounded-lg p-3">
          <legend className="px-2 text-xs font-semibold text-text-secondary">Tier-2 Archive Options</legend>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label htmlFor="archive-format" className="text-xs font-semibold text-text-secondary">
                Archive format
              </label>
              <select
                id="archive-format"
                name="archive_format"
                defaultValue="tar.zst"
                onChange={(e) => setArchiveFormat(e.target.value as "tar.zst" | "tar.gz")}
                className="px-3 py-2 rounded-lg border border-border-default bg-surface-card text-sm text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-primary"
              >
                <option value="tar.zst">tar.zst (Zstandard, recommended)</option>
                <option value="tar.gz">tar.gz (Gzip)</option>
              </select>
              <p className="text-xs text-text-muted">Default: tar.zst.</p>
            </div>
            <div className="flex items-end gap-2">
              <input
                id="include-cas-jars"
                name="include_cas_jars"
                type="checkbox"
                checked={includeCasJars}
                onChange={(e) => setIncludeCasJars(e.target.checked)}
                className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
              />
              <label htmlFor="include-cas-jars" className="text-sm text-text-primary cursor-pointer">
                Include CAS Jars
              </label>
            </div>
            <p className="col-span-2 text-xs text-text-muted">
              Bundle user JARs and plugins directly into the archive for complete offline portability.
            </p>
          </div>
          <div className="mt-3 rounded-lg border border-status-info-bg bg-status-info-bg/50 p-3 text-sm text-status-info flex items-start gap-2">
            <Icon name="info" size={14} />
            <p className="leading-relaxed">
              Automatic Envelope Encryption: Tier-2 archives are automatically encrypted using AES-256-GCM. No manual key configuration required.
            </p>
          </div>
        </fieldset>
      )}

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
