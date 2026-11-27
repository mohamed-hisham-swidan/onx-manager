import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { formatBytes, formatDateTime } from "@/server_manager/utils/format";
import { RETENTION_POLICY_OPTIONS } from "@/server_manager/utils/versioningFormat";
import {
  GitHubSyncPanel,
  type GitHubSyncAlertState,
} from "@/server_manager/components/versioning/GitHubSyncPanel";
import type {
  BotSettings,
  ClassCSnapshot,
  DataTemplate,
  DynamicClassCEntry,
  GitHubConnectionStatusResponse,
  SecretMetadata,
  ServerBranch,
} from "@/server_manager/types";

export interface SyncAndVaultTabProps {
  serverId: string;
  selectedBranch: string;
  branches: ServerBranch[];
  canEdit: boolean;
  // Retention settings
  settings: BotSettings | null;
  isSavingRetention: boolean;
  onSaveRetention: (policy: string) => Promise<void>;
  // GitHub
  githubStatus: GitHubConnectionStatusResponse | null;
  isGitHubFetching: boolean;
  isGitHubPushing: boolean;
  githubSyncAlert: GitHubSyncAlertState | null;
  onDismissSyncAlert: () => void;
  onFetchNow: () => void;
  onPushBranch: () => void;
  onOpenConnectGitHub: () => void;
  onOpenRotateGitHub: () => void;
  onOpenDisconnectGitHub: () => void;
  onOpenWebhookDeliveries: () => void;
  // Data Templates
  dataTemplates: DataTemplate[];
  onOpenCreateTemplate: () => void;
  onDeleteTemplate: (templateId: string) => Promise<void>;
}

export function SyncAndVaultTab({
  serverId,
  selectedBranch,
  branches,
  canEdit,
  settings,
  isSavingRetention,
  onSaveRetention,
  githubStatus,
  isGitHubFetching,
  isGitHubPushing,
  githubSyncAlert,
  onDismissSyncAlert,
  onFetchNow,
  onPushBranch,
  onOpenConnectGitHub,
  onOpenRotateGitHub,
  onOpenDisconnectGitHub,
  onOpenWebhookDeliveries,
  dataTemplates,
  onOpenCreateTemplate,
  onDeleteTemplate,
}: SyncAndVaultTabProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [draftRetention, setDraftRetention] = useState<string | null>(null);
  const retentionChoice =
    draftRetention ?? settings?.previous_tree_retention ?? "until_confirm";
  const [retentionSavedMsg, setRetentionSavedMsg] = useState<string | null>(null);
  const [deletingTemplateId, setDeletingTemplateId] = useState<string | null>(null);

  // Vault inline state
  const [vaultTab, setVaultTab] = useState<"snapshots" | "dynamic" | "secrets">("snapshots");
  const [snapshots, setSnapshots] = useState<ClassCSnapshot[]>([]);
  const [dynamicEntries, setDynamicEntries] = useState<DynamicClassCEntry[]>([]);
  const [secrets, setSecrets] = useState<SecretMetadata[]>([]);
  const [pinnedSnapshot, setPinnedSnapshot] = useState(false);
  const [secretBranch, setSecretBranch] = useState(
    selectedBranch !== "main" ? selectedBranch : "",
  );
  const [secretPath, setSecretPath] = useState("");
  const [secretKeyName, setSecretKeyName] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [vaultBusy, setVaultBusy] = useState(false);
  const [vaultMessage, setVaultMessage] = useState<string | null>(null);
  const [vaultError, setVaultError] = useState<string | null>(null);

  const loadVault = async () => {
    try {
      const [s, d, sec] = await Promise.all([
        typeof api.listClassCSnapshots === "function"
          ? api.listClassCSnapshots(serverId)
          : Promise.resolve([]),
        typeof api.listDynamicClassC === "function"
          ? api.listDynamicClassC(serverId)
          : Promise.resolve([]),
        typeof api.listSecrets === "function"
          ? api.listSecrets(serverId)
          : Promise.resolve([]),
      ]);
      setSnapshots(Array.isArray(s) ? s : []);
      setDynamicEntries(Array.isArray(d) ? d : []);
      setSecrets(Array.isArray(sec) ? sec : []);
    } catch (err: unknown) {
      setVaultError(
        err instanceof Error ? err.message : "Failed to load vault items.",
      );
    }
  };

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const [s, d, sec] = await Promise.all([
          typeof api.listClassCSnapshots === "function"
            ? api.listClassCSnapshots(serverId)
            : Promise.resolve([]),
          typeof api.listDynamicClassC === "function"
            ? api.listDynamicClassC(serverId)
            : Promise.resolve([]),
          typeof api.listSecrets === "function"
            ? api.listSecrets(serverId)
            : Promise.resolve([]),
        ]);
        if (!active) return;
        setSnapshots(Array.isArray(s) ? s : []);
        setDynamicEntries(Array.isArray(d) ? d : []);
        setSecrets(Array.isArray(sec) ? sec : []);
      } catch (err: unknown) {
        if (!active) return;
        setVaultError(
          err instanceof Error ? err.message : "Failed to load vault items.",
        );
      }
    })();
    return () => {
      active = false;
    };
  }, [api, serverId]);

  const nonMainBranches = branches.filter(
    (b) => b.name !== "main" && b.status !== "archived",
  );

  return (
    <div className="space-y-5" data-testid="sync-and-vault-tab">
      {/* 1. GitHub Sync */}
      <GitHubSyncPanel
        status={githubStatus}
        selectedBranch={selectedBranch}
        isFetching={isGitHubFetching}
        isPushing={isGitHubPushing}
        syncAlert={githubSyncAlert}
        canEdit={canEdit}
        onDismissSyncAlert={onDismissSyncAlert}
        onFetchNow={onFetchNow}
        onPushBranch={onPushBranch}
        onOpenConnectModal={onOpenConnectGitHub}
        onOpenRotateModal={onOpenRotateGitHub}
        onOpenDisconnectModal={onOpenDisconnectGitHub}
        onOpenDeliveriesModal={onOpenWebhookDeliveries}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* 2. Rollback Retention Policy */}
        <section
          aria-label="Rollback Retention Policy"
          className="rounded-xl border border-border-default bg-surface-card p-4 space-y-3 shadow-2xs"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Icon name="restart" size={16} className="text-accent-primary" />
              <h2 className="text-sm font-bold text-text-primary">
                Undo &amp; Backup Retention Policy
              </h2>
            </div>
            {settings?.previous_tree_retention && (
              <span className="rounded-full border border-border-default bg-surface-elevated px-2 py-0.5 font-mono text-[11px] text-text-secondary">
                {settings.previous_tree_retention}
              </span>
            )}
          </div>
          <p className="text-xs text-text-muted">
            Controls how long previous live server files are retained after deploying or restoring a snapshot so you can undo if needed.
          </p>

          <div className="space-y-2">
            {RETENTION_POLICY_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className={`flex items-start gap-2.5 rounded-lg border p-2.5 text-xs cursor-pointer transition-colors ${
                  retentionChoice === opt.value
                    ? "border-accent-primary/50 bg-accent-primary/5"
                    : "border-border-subtle bg-surface-page hover:bg-surface-hover/40"
                }`}
              >
                <input
                  type="radio"
                  name="previous-tree-retention"
                  value={opt.value}
                  checked={retentionChoice === opt.value}
                  onChange={() => {
                    setDraftRetention(opt.value);
                    setRetentionSavedMsg(null);
                  }}
                  disabled={!canEdit || isSavingRetention}
                  className="mt-0.5 text-accent-primary focus:ring-accent-primary"
                />
                <div className="min-w-0">
                  <div className="font-semibold text-text-primary">{opt.label}</div>
                  <div className="text-[11px] text-text-muted">{opt.description}</div>
                </div>
              </label>
            ))}
          </div>

          {retentionSavedMsg && (
            <div className="text-xs text-status-success font-medium">
              {retentionSavedMsg}
            </div>
          )}

          {canEdit && (
            <div className="flex justify-end pt-1">
              <button
                type="button"
                disabled={isSavingRetention}
                onClick={async () => {
                  await onSaveRetention(retentionChoice);
                  setRetentionSavedMsg("Retention policy updated.");
                }}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
              >
                <Icon name="check" size={13} />
                {isSavingRetention ? "Saving..." : "Save Policy"}
              </button>
            </div>
          )}
        </section>

        {/* 3. Data Templates */}
        <section
          aria-label="Sandbox Data Templates"
          className="rounded-xl border border-border-default bg-surface-card p-4 space-y-3 shadow-2xs flex flex-col"
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Icon name="database" size={16} className="text-accent-primary" />
              <h2 className="text-sm font-bold text-text-primary">
                Sandbox Data Templates ({dataTemplates.length})
              </h2>
            </div>
            {canEdit && (
              <button
                type="button"
                onClick={onOpenCreateTemplate}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs font-medium text-text-primary hover:bg-surface-hover cursor-pointer"
              >
                <Icon name="plus" size={12} />
                Manage Templates
              </button>
            )}
          </div>
          <p className="text-xs text-text-muted">
            Reusable world &amp; plugin data snapshots for seeding isolated branch sandboxes.
          </p>

          <div className="space-y-2 flex-1 max-h-64 overflow-y-auto pr-1">
            {dataTemplates.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
                No data templates saved yet.
              </div>
            ) : (
              dataTemplates.map((tpl) => (
                <div
                  key={tpl.id}
                  className="flex items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-page p-2.5 text-xs"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-text-primary truncate">
                        {tpl.name}
                      </span>
                      <span className="rounded-full border border-border-default bg-surface-elevated px-1.5 py-0.5 text-[10px] font-medium text-text-secondary">
                        {tpl.status}
                      </span>
                    </div>
                    <div className="text-[11px] text-text-muted">
                      {tpl.source_branch_name
                        ? `From branch: ${tpl.source_branch_name}`
                        : "From live server"}{" "}
                      · {tpl.file_count} files · {formatBytes(tpl.total_bytes)}
                    </div>
                  </div>
                  {canEdit && (
                    <button
                      type="button"
                      disabled={deletingTemplateId === tpl.id}
                      onClick={async () => {
                        setDeletingTemplateId(tpl.id);
                        try {
                          await onDeleteTemplate(tpl.id);
                        } finally {
                          setDeletingTemplateId(null);
                        }
                      }}
                      className="rounded border border-border-default bg-surface-card px-2 py-1 text-[11px] text-status-danger hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer shrink-0"
                    >
                      {deletingTemplateId === tpl.id ? "Deleting..." : "Delete"}
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* 4. Live Data & Secret Vault */}
      <section
        aria-label="Live Data & Secret Vault"
        className="rounded-xl border border-border-default bg-surface-card p-4 space-y-3 shadow-2xs"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Icon name="lock" size={16} className="text-accent-primary" />
            <h2 className="text-sm font-bold text-text-primary">
              Live Data &amp; Secret Vault
            </h2>
          </div>

          <div className="flex items-center gap-1 rounded-lg border border-border-subtle bg-surface-page p-1">
            {(
              [
                ["snapshots", `Live Data Snapshots (${snapshots.length})`],
                ["dynamic", `Live Runtime Files (${dynamicEntries.length})`],
                ["secrets", `Secret Vault (${secrets.length})`],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setVaultTab(key)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors ${
                  vaultTab === key
                    ? "bg-accent-primary text-accent-contrast-text"
                    : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {vaultError && (
          <div
            role="alert"
            className="rounded-lg border border-status-danger-border bg-status-danger-bg p-2.5 text-xs text-status-danger"
          >
            {vaultError}
          </div>
        )}
        {vaultMessage && (
          <div className="rounded-lg border border-status-info-border bg-status-info-bg p-2.5 text-xs text-status-info">
            {vaultMessage}
          </div>
        )}

        {vaultTab === "snapshots" && (
          <div className="space-y-3">
            {canEdit && (
              <div className="flex flex-wrap items-center justify-between gap-2">
                <label className="inline-flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
                  <input
                    type="checkbox"
                    checked={pinnedSnapshot}
                    onChange={(e) => setPinnedSnapshot(e.target.checked)}
                    disabled={vaultBusy}
                    className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
                  />
                  Pin snapshot (prevents accidental deletion)
                </label>
                <button
                  type="button"
                  disabled={vaultBusy}
                  onClick={async () => {
                    setVaultBusy(true);
                    setVaultError(null);
                    setVaultMessage(null);
                    try {
                      await api.createClassCSnapshot(serverId, {
                        pinned: pinnedSnapshot,
                      });
                      setVaultMessage("Live data snapshot created.");
                      await loadVault();
                    } catch (err: unknown) {
                      setVaultError(
                        err instanceof Error
                          ? err.message
                          : "Failed to create live data snapshot.",
                      );
                    } finally {
                      setVaultBusy(false);
                    }
                  }}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer"
                >
                  Create Live Data Snapshot
                </button>
              </div>
            )}

            {snapshots.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
                No live data snapshots recorded yet.
              </div>
            ) : (
              <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                {snapshots.map((s) => (
                  <div
                    key={s.snapshot_id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-page p-2.5 text-xs"
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-semibold text-text-primary">
                          {s.snapshot_id.slice(0, 12)}
                        </span>
                        {s.pinned && (
                          <span className="rounded bg-accent-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-accent-primary">
                            Pinned
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-text-muted">
                        {formatDateTime(s.created_at)} · {s.entry_count} entries ·{" "}
                        {formatBytes(s.archive_size_bytes)}
                        {s.manifest_sha256 ? ` · SHA ${s.manifest_sha256.slice(0, 8)}` : ""}
                      </div>
                    </div>
                    {canEdit && (
                      <div className="flex items-center gap-1.5 shrink-0">
                        <button
                          type="button"
                          disabled={vaultBusy}
                          onClick={async () => {
                            setVaultBusy(true);
                            setVaultError(null);
                            setVaultMessage(null);
                            try {
                              await api.restoreClassCSnapshot(serverId, s.snapshot_id);
                              setVaultMessage("Live data snapshot restored.");
                              await loadVault();
                            } catch (err: unknown) {
                              setVaultError(
                                err instanceof Error
                                  ? err.message
                                  : "Server must be stopped before restoring a live data snapshot.",
                              );
                            } finally {
                              setVaultBusy(false);
                            }
                          }}
                          className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-text-primary hover:bg-surface-hover cursor-pointer"
                        >
                          Restore
                        </button>
                        <button
                          type="button"
                          disabled={vaultBusy || s.pinned}
                          title={
                            s.pinned
                              ? "Pinned snapshot cannot be deleted until pins are released"
                              : undefined
                          }
                          onClick={async () => {
                            setVaultBusy(true);
                            setVaultError(null);
                            setVaultMessage(null);
                            try {
                              await api.deleteClassCSnapshot(serverId, s.snapshot_id);
                              await loadVault();
                            } catch (err: unknown) {
                              setVaultError(
                                err instanceof Error
                                  ? err.message
                                  : "Failed to delete snapshot.",
                              );
                            } finally {
                              setVaultBusy(false);
                            }
                          }}
                          className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer"
                        >
                          Delete
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {vaultTab === "dynamic" && (
          <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
            {dynamicEntries.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
                No runtime-excluded config files detected.
              </div>
            ) : (
              dynamicEntries.map((entry) => (
                <div
                  key={entry.relpath}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-page p-2.5 text-xs"
                >
                  <div className="min-w-0 space-y-0.5">
                    <div className="font-mono font-semibold text-text-primary truncate">
                      {entry.relpath}
                    </div>
                    <div className="text-[11px] text-text-muted">
                      Promoted {formatDateTime(entry.promoted_at)}
                      {entry.main_commit_sha
                        ? ` · Baseline ${entry.main_commit_sha.slice(0, 8)}`
                        : ""}
                    </div>
                  </div>
                  {canEdit && (
                    <button
                      type="button"
                      disabled={vaultBusy}
                      onClick={async () => {
                        setVaultBusy(true);
                        setVaultError(null);
                        setVaultMessage(null);
                        try {
                          await api.resetDynamicClassC(serverId, entry.relpath);
                          setVaultMessage(`Reset '${entry.relpath}' back to Git tracking.`);
                          await loadVault();
                        } catch (err: unknown) {
                          setVaultError(
                            err instanceof Error ? err.message : "Failed to reset file.",
                          );
                        } finally {
                          setVaultBusy(false);
                        }
                      }}
                      className="rounded border border-border-default bg-surface-card px-2.5 py-1 text-xs text-text-primary hover:bg-surface-hover cursor-pointer shrink-0"
                    >
                      Track in Git (from main)
                    </button>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {vaultTab === "secrets" && (
          <div className="space-y-3">
            {secrets.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border-default bg-surface-page p-4 text-xs text-text-muted">
                No encrypted secrets extracted yet.
              </div>
            ) : (
              <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                {secrets.map((sec) => (
                  <div
                    key={sec.key_name}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border-subtle bg-surface-page p-2.5 text-xs"
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-text-primary">
                          {sec.key_name}
                        </span>
                        <code className="rounded bg-surface-elevated px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
                          {sec.placeholder}
                        </code>
                      </div>
                      <div className="text-[11px] text-text-muted">
                        Key v{sec.kek_version} · Updated {formatDateTime(sec.updated_at)}
                      </div>
                    </div>
                    {canEdit && (
                      <button
                        type="button"
                        disabled={vaultBusy}
                        onClick={async () => {
                          setVaultBusy(true);
                          setVaultError(null);
                          setVaultMessage(null);
                          try {
                            await api.deleteSecret(serverId, sec.key_name);
                            await loadVault();
                          } catch (err: unknown) {
                            setVaultError(
                              err instanceof Error ? err.message : "Failed to delete secret.",
                            );
                          } finally {
                            setVaultBusy(false);
                          }
                        }}
                        className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg cursor-pointer shrink-0"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}

            {canEdit && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 border-t border-border-subtle pt-3">
                <select
                  aria-label="Secret target branch"
                  value={secretBranch}
                  onChange={(e) => setSecretBranch(e.target.value)}
                  className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary focus:outline-hidden focus:border-accent-primary"
                >
                  <option value="">Select working branch...</option>
                  {nonMainBranches.map((b) => (
                    <option key={b.name} value={b.name}>
                      {b.name}
                    </option>
                  ))}
                </select>
                <input
                  value={secretPath}
                  onChange={(e) => setSecretPath(e.target.value)}
                  placeholder="Config file path"
                  className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                />
                <input
                  value={secretKeyName}
                  onChange={(e) => setSecretKeyName(e.target.value)}
                  placeholder="Secret key name"
                  className="rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                />
                <div className="flex gap-2">
                  <input
                    type="password"
                    autoComplete="off"
                    value={secretValue}
                    onChange={(e) => setSecretValue(e.target.value)}
                    placeholder="Secret plaintext value"
                    className="flex-1 min-w-0 rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                  />
                  <button
                    type="button"
                    disabled={
                      vaultBusy ||
                      !secretBranch ||
                      !secretPath.trim() ||
                      !secretKeyName.trim() ||
                      !secretValue
                    }
                    onClick={async () => {
                      const val = secretValue;
                      setSecretValue("");
                      setVaultBusy(true);
                      setVaultError(null);
                      setVaultMessage(null);
                      try {
                        await api.extractSecret(serverId, {
                          branch: secretBranch,
                          path: secretPath.trim(),
                          key_name: secretKeyName.trim(),
                          secret_value: val,
                        });
                        setVaultMessage(
                          `Extracted secret '${secretKeyName.trim()}' into encrypted vault.`,
                        );
                        await loadVault();
                      } catch (err: unknown) {
                        setVaultError(
                          err instanceof Error ? err.message : "Extract failed.",
                        );
                      } finally {
                        setVaultBusy(false);
                      }
                    }}
                    className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 cursor-pointer shrink-0"
                  >
                    Extract
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
