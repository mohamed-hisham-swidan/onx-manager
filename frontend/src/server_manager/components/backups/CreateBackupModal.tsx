import { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import { useServersList } from "@/server_manager/hooks/useServers";
import { useCreateBackup } from "@/server_manager/hooks/useBackups";
import { toast } from "@/stores/toastStore";
import { BACKUP_SCOPES, TIER_META } from "./backupUtils";
import type { ServerResponse } from "@/server_manager/types";
import type { CreateBackupRequest } from "@/types";

export interface CreateBackupModalProps {
  open: boolean;
  onClose: () => void;
  defaultServerId?: string;
}

function resolveInitialServerId(
  defaultServerId: string | undefined,
  servers: ServerResponse[],
): string {
  if (defaultServerId && defaultServerId !== "all" && defaultServerId !== "deleted") {
    return defaultServerId;
  }
  if (servers.length === 1) {
    return servers[0].server_id;
  }
  return "";
}

export function CreateBackupModal({
  open,
  onClose,
  defaultServerId,
}: CreateBackupModalProps) {
  const { data: servers } = useServersList();
  const createBackup = useCreateBackup();
  const serverList = servers ?? [];

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="New Backup"
      description="Create a quick snapshot or encrypted archive."
      size="lg"
      closeOnEscape={!createBackup.isPending}
      closeOnBackdrop={!createBackup.isPending}
    >
      {open && (
        <CreateBackupModalForm
          key={defaultServerId ?? "__none__"}
          onClose={onClose}
          defaultServerId={defaultServerId}
          servers={servers}
          serverList={serverList}
          createBackup={createBackup}
        />
      )}
    </Modal>
  );
}

interface CreateBackupModalFormProps {
  onClose: () => void;
  defaultServerId?: string;
  servers: ServerResponse[] | undefined;
  serverList: ServerResponse[];
  createBackup: ReturnType<typeof useCreateBackup>;
}

function CreateBackupModalForm({
  onClose,
  defaultServerId,
  servers,
  serverList,
  createBackup,
}: CreateBackupModalFormProps) {
  const [error, setError] = useState<string | null>(null);
  const [tier, setTier] = useState<"tier_1" | "tier_2">("tier_1");
  const [backupType, setBackupType] = useState("full");
  const [archiveFormat, setArchiveFormat] = useState<"tar.zst" | "tar.gz">("tar.zst");
  const [includeCasJars, setIncludeCasJars] = useState(false);
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);

  const effectiveServerId =
    selectedServerId !== null
      ? selectedServerId
      : resolveInitialServerId(defaultServerId, serverList);
  const hasNoServers = servers !== undefined && serverList.length === 0;
  const isTier2 = tier === "tier_2";

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    if (!effectiveServerId) {
      setError("Please select a server.");
      return;
    }

    const body: CreateBackupRequest = {
      server_id: effectiveServerId,
      backup_type: backupType,
      tier,
    };
    if (tier === "tier_2") {
      body.archive_format = archiveFormat;
      body.include_cas_jars = includeCasJars;
    }

    try {
      await createBackup.mutateAsync(body);
      const serverName =
        serverList.find((s) => s.server_id === effectiveServerId)?.name ?? effectiveServerId;
      toast("success", "Backup started", `Backup started for ${serverName}`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start backup");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {hasNoServers && (
        <div className="rounded-lg border border-status-warning-border bg-status-warning-bg/60 p-3 text-xs text-status-warning flex items-center gap-2">
          <Icon name="alert" size={14} className="shrink-0" />
          <span>No servers available. Create a server before starting a backup.</span>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label
            htmlFor="create-backup-server"
            className="block text-xs font-medium text-text-secondary mb-1.5"
          >
            Server
          </label>
          <select
            id="create-backup-server"
            name="server_id"
            aria-label="Select server"
            value={effectiveServerId}
            onChange={(e) => setSelectedServerId(e.target.value)}
            disabled={createBackup.isPending || hasNoServers}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
          >
            <option value="">Select a server...</option>
            {serverList.map((s) => (
              <option key={s.server_id} value={s.server_id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="create-backup-scope"
            className="block text-xs font-medium text-text-secondary mb-1.5"
          >
            Scope
          </label>
          <select
            id="create-backup-scope"
            name="backup_type"
            aria-label="Backup scope"
            value={backupType}
            onChange={(e) => setBackupType(e.target.value)}
            disabled={createBackup.isPending}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:border-border-focus focus:outline-hidden focus:ring-2 focus:ring-border-focus disabled:opacity-50"
          >
            {BACKUP_SCOPES.map((scope) => (
              <option key={scope.value} value={scope.value}>
                {scope.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Backup Type Visual Cards */}
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-text-secondary">
          Backup Type
        </legend>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {(["tier_1", "tier_2"] as const).map((optionTier) => {
            const meta = TIER_META[optionTier];
            const selected = tier === optionTier;
            return (
              <label
                key={optionTier}
                className={`relative flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors ${
                  selected
                    ? "border-accent-primary bg-accent-primary/8"
                    : "border-border-subtle bg-surface-page hover:border-border-default"
                }`}
              >
                <input
                  type="radio"
                  name="tier"
                  value={optionTier}
                  checked={selected}
                  onChange={() => setTier(optionTier)}
                  disabled={createBackup.isPending}
                  className="mt-0.5 text-accent-primary focus:ring-accent-primary"
                />
                <div className="min-w-0">
                  <div className="text-sm font-semibold text-text-primary">
                    {meta.label}
                  </div>
                  <p className="mt-0.5 text-xs text-text-muted leading-relaxed">
                    {meta.shortDesc}
                  </p>
                </div>
              </label>
            );
          })}
        </div>
      </fieldset>

      {isTier2 && (
        <div
          data-testid="tier-2-options"
          className="rounded-xl border border-border-subtle bg-surface-page p-4 space-y-3"
        >
          <div>
            <span className="block text-xs font-medium text-text-secondary mb-1.5">
              Compression Format
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setArchiveFormat("tar.zst")}
                disabled={createBackup.isPending}
                aria-pressed={archiveFormat === "tar.zst"}
                className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors cursor-pointer ${
                  archiveFormat === "tar.zst"
                    ? "border-accent-primary bg-accent-primary/10 text-text-primary"
                    : "border-border-subtle bg-surface-card text-text-secondary hover:bg-surface-hover"
                }`}
              >
                Zstandard (.tar.zst) — Recommended
              </button>
              <button
                type="button"
                onClick={() => setArchiveFormat("tar.gz")}
                disabled={createBackup.isPending}
                aria-pressed={archiveFormat === "tar.gz"}
                className={`rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors cursor-pointer ${
                  archiveFormat === "tar.gz"
                    ? "border-accent-primary bg-accent-primary/10 text-text-primary"
                    : "border-border-subtle bg-surface-card text-text-secondary hover:bg-surface-hover"
                }`}
              >
                Gzip (.tar.gz)
              </button>
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm text-text-primary cursor-pointer select-none">
            <input
              id="include-cas-jars"
              name="include_cas_jars"
              type="checkbox"
              checked={includeCasJars}
              onChange={(e) => setIncludeCasJars(e.target.checked)}
              disabled={createBackup.isPending}
              className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
            />
            <span>Include cached mod/plugin JARs</span>
          </label>

          <div className="rounded-lg border border-status-info-border bg-status-info-bg/40 px-3 py-2 text-xs text-status-info flex items-center gap-2">
            <Icon name="lock" size={13} className="shrink-0" />
            <span>Encrypted automatically with AES-256-GCM.</span>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-lg border border-status-danger-border bg-status-danger-bg/60 px-3 py-2 text-xs text-status-danger">
          {error}
        </p>
      )}

      <div className="flex items-center justify-end gap-2 pt-2 border-t border-border-subtle">
        <button
          type="button"
          onClick={onClose}
          disabled={createBackup.isPending}
          className="rounded-lg border border-border-default bg-surface-page px-3.5 py-2 text-xs font-medium text-text-secondary hover:bg-surface-hover hover:text-text-primary disabled:opacity-50 cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={createBackup.isPending || hasNoServers}
          className="inline-flex items-center gap-2 rounded-lg bg-accent-primary px-4 py-2 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer shadow-xs"
        >
          {createBackup.isPending && (
            <span
              className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
              aria-hidden="true"
            />
          )}
          <span>{createBackup.isPending ? "Starting..." : "Start Backup"}</span>
        </button>
      </div>
    </form>
  );
}
