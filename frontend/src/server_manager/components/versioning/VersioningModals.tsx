import { useState, useEffect, useCallback } from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import type { ServerBranch, ServerCommit } from "@/server_manager/types";

// ==========================================
// 1. Create Branch Modal
// ==========================================
interface CreateBranchModalProps {
  isOpen: boolean;
  branchName: string;
  onBranchNameChange: (val: string) => void;
  onSubmit: () => void;
  onClose: () => void;
  isPending?: boolean;
}

export function CreateBranchModal({
  isOpen,
  branchName,
  onBranchNameChange,
  onSubmit,
  onClose,
  isPending = false,
}: CreateBranchModalProps) {
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Create New Branch"
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!isPending) onSubmit();
        }}
        className="space-y-4"
      >
        <div>
          <label htmlFor="branch-name-input" className="block text-xs font-medium text-text-secondary mb-1">
            Branch Name
          </label>
          <input
            id="branch-name-input"
            type="text"
            value={branchName}
            onChange={(e) => onBranchNameChange(e.target.value)}
            disabled={isPending}
            placeholder="e.g. feat-mod-upgrade"
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isPending || !branchName.trim()}
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer shadow-xs disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isPending ? "Creating..." : "Create Branch"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ==========================================
// 2. Create Snapshot Commit Modal
// ==========================================
interface CreateCommitModalProps {
  isOpen: boolean;
  message: string;
  onMessageChange: (val: string) => void;
  forceBypass: boolean;
  onForceBypassChange: (val: boolean) => void;
  forceReason: string;
  onForceReasonChange: (val: string) => void;
  selectedBranch: string;
  currentBranchObj: ServerBranch | null;
  isDirectCommitBlocked: boolean;
  allowForceBypass: boolean;
  onSubmit: () => void;
  onClose: () => void;
  isPending?: boolean;
}

export function CreateCommitModal({
  isOpen,
  message,
  onMessageChange,
  forceBypass,
  onForceBypassChange,
  forceReason,
  onForceReasonChange,
  selectedBranch,
  currentBranchObj,
  isDirectCommitBlocked,
  allowForceBypass,
  onSubmit,
  onClose,
  isPending = false,
}: CreateCommitModalProps) {
  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Create Snapshot Commit"
      description={`Captures all configs, mod jars, and creates an instant COW world snapshot on branch ‘${selectedBranch}’.`}
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      <div className="space-y-4">
        {currentBranchObj?.status === "archived" && (
          <div className="flex items-center gap-2 rounded-lg bg-surface-hover p-3 text-xs text-text-secondary">
            <Icon name="alert" size={14} className="shrink-0 text-status-warning" />
            <span>
              Branch &lsquo;{selectedBranch}&rsquo; is archived and read-only. Committing is disabled.
            </span>
          </div>
        )}

        {isDirectCommitBlocked && (
          <div className="p-3 bg-status-warning-bg border border-status-warning/40 rounded-lg text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-semibold text-status-warning">
              <Icon name="alert" size={14} />
              <span>Direct Commits Blocked by Protection Policy</span>
            </div>
            <p className="text-text-secondary">
              Branch &lsquo;{selectedBranch}&rsquo; requires changes to be verified on a working branch and merged.
            </p>
            {allowForceBypass ? (
              <div className="pt-2 border-t border-status-warning/30 space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={forceBypass}
                    onChange={(e) => onForceBypassChange(e.target.checked)}
                    disabled={isPending}
                    className="rounded border-border-default text-accent-primary focus:ring-accent-primary disabled:opacity-50"
                  />
                  <span className="font-semibold text-text-primary">
                    Emergency Force Bypass
                  </span>
                </label>
                {forceBypass && (
                  <div>
                    <label className="block text-[11px] font-medium text-status-warning mb-1">
                      Bypass Reason (Audit Logged)
                    </label>
                    <input
                      type="text"
                      value={forceReason}
                      onChange={(e) => onForceReasonChange(e.target.value)}
                      disabled={isPending}
                      placeholder="e.g. Hotfix for critical crash"
                      className="w-full rounded border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-primary disabled:opacity-50"
                      required
                    />
                  </div>
                )}
              </div>
            ) : (
              <p className="text-status-danger font-semibold text-[11px]">
                Force bypass is disabled on this branch.
              </p>
            )}
          </div>
        )}

        <div>
          <label htmlFor="commit-message-input" className="block text-xs font-medium text-text-secondary mb-1">
            Commit Message
          </label>
          <input
            id="commit-message-input"
            type="text"
            value={message}
            onChange={(e) => onMessageChange(e.target.value)}
            placeholder="e.g. Pre-WorldEdit update snapshot"
            disabled={isPending || currentBranchObj?.status === "archived"}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={
              isPending ||
              !message.trim() ||
              currentBranchObj?.status === "archived" ||
              (isDirectCommitBlocked && (!allowForceBypass || !forceBypass || !forceReason.trim()))
            }
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shadow-xs"
          >
            {isPending ? "Committing..." : forceBypass ? "Force Commit Snapshot" : "Commit Snapshot"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ==========================================
// 4. Manifest Inspect Modal
// ==========================================
interface InspectCommitModalProps {
  commit: ServerCommit | null;
  onClose: () => void;
}

export function InspectCommitModal({ commit, onClose }: InspectCommitModalProps) {
  return (
    <Modal
      open={!!commit}
      onClose={onClose}
      title="Manifest Snapshot Inspector"
      description={commit ? `Commit ${commit.id.slice(0, 8)} • ${commit.message}` : undefined}
      size="xl"
      showCloseButton={true}
      closeButtonAriaLabel="Close"
      closeOnBackdrop={false}
      className="max-h-[85vh] flex flex-col"
    >
      {commit && (
        <div className="flex flex-col flex-1 min-h-0 space-y-4">
          <div className="overflow-y-auto space-y-4 pr-1 flex-1">
            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-text-muted block mb-1">
                Captured Configurations ({Object.keys(commit.manifest?.configs || {}).length} files)
              </span>
              <div className="rounded-lg bg-surface-page p-2.5 border border-border-subtle text-xs font-mono max-h-40 overflow-y-auto">
                {Object.keys(commit.manifest?.configs || {}).map((f) => (
                  <div key={f} className="flex items-center gap-1.5 text-text-primary py-0.5">
                    <Icon name="file" size={13} className="shrink-0 text-text-muted" />
                    <span>{f}</span>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <span className="text-xs font-semibold uppercase tracking-wider text-text-muted block mb-1">
                Captured Mods / Plugins ({(commit.manifest?.mods || []).length} items)
              </span>
              <div className="rounded-lg bg-surface-page p-2.5 border border-border-subtle text-xs font-mono max-h-40 overflow-y-auto">
                {(commit.manifest?.mods || []).map((m) => (
                  <div key={m.filename} className="flex items-center gap-1.5 text-text-primary py-0.5">
                    <Icon name="mod" size={13} className="shrink-0 text-accent-primary" />
                    <span>
                      {m.filename} <span className="text-text-muted">({m.sha256.slice(0, 10)}...)</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-3 border-t border-border-subtle">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-surface-page border border-border-default px-4 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ==========================================
// Merge Branch Modal
// ==========================================
interface MergeBranchModalProps {
  isOpen: boolean;
  serverId: string;
  branches: any[];
  selectedBranch?: string;
  onMerged?: () => void;
  onClose: () => void;
}

export function MergeBranchModal({ isOpen, serverId, branches, selectedBranch, onMerged, onClose }: MergeBranchModalProps) {
  const [targetBranch, setTargetBranch] = useState(selectedBranch || "main");
  const [sourceBranch, setSourceBranch] = useState("");
  const [message, setMessage] = useState("");
  const [forceBypass, setForceBypass] = useState(false);
  const [forceReason, setForceReason] = useState("");
  const [pending, setPending] = useState(false);
  const [warnings, setWarnings] = useState<any[]>([]);
  const [conflicts, setConflicts] = useState<any[]>([]);
  const [findings, setFindings] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  const nonArchived = (branches || []).filter((b: any) => b.status !== "archived");
  const sources = nonArchived.filter((b: any) => b.name !== targetBranch);

  if (!isOpen) return null;

  const submit = async () => {
    setPending(true);
    setWarnings([]);
    setConflicts([]);
    setFindings([]);
    setError(null);
    try {
      const api = (await import("@/services/api")).createAuthenticatedApi();
      const res = await api.mergeServerCommits(serverId, {
        target_branch_name: targetBranch,
        source_branch_name: sourceBranch || null,
        message: message || `Merge branch '${sourceBranch}' into ${targetBranch}`,
        force: forceBypass,
        force_reason: forceBypass ? forceReason || null : null,
        force_bypass_protection: forceBypass,
      });
      if (Array.isArray(res?.warnings)) setWarnings(res.warnings);
      onMerged?.();
      onClose();
    } catch (e: any) {
      const detail = e?.detail ?? null;
      if (detail && typeof detail === "object") {
        if (Array.isArray((detail as any).conflicts)) setConflicts((detail as any).conflicts);
        if (Array.isArray((detail as any).findings)) setFindings((detail as any).findings);
      }
      setError(e?.message ?? "Merge failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal open={isOpen} onClose={onClose} title="Merge Branch">
      <div className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1">Target branch</label>
          <select value={targetBranch} onChange={(e) => setTargetBranch(e.target.value)} className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm">
            {nonArchived.map((b: any) => <option key={b.id ?? b.name} value={b.name}>{b.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1">Source branch</label>
          <select value={sourceBranch} onChange={(e) => setSourceBranch(e.target.value)} className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm">
            <option value="">Select source</option>
            {sources.map((b: any) => <option key={b.id ?? b.name} value={b.name}>{b.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-text-secondary mb-1">Message</label>
          <input value={message} onChange={(e) => setMessage(e.target.value)} className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm" />
        </div>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={forceBypass} onChange={(e) => setForceBypass(e.target.checked)} />
          Force bypass protection
        </label>
        {forceBypass && (
          <input value={forceReason} onChange={(e) => setForceReason(e.target.value)} placeholder="Reason" className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm" />
        )}
        {warnings.length > 0 && (
          <div className="rounded-lg border border-status-warning-border bg-status-warning-bg p-2 text-xs">
            {warnings.map((w, i) => <div key={i}>{String(w)}</div>)}
          </div>
        )}
        {conflicts.length > 0 && (
          <div className="rounded-lg border border-status-danger-border bg-status-danger-bg p-2 text-xs">
            {conflicts.map((c, i) => (
              <div key={i}>
                {c?.path} {c?.key_path} {c?.base} {c?.ours} {c?.theirs}
              </div>
            ))}
          </div>
        )}
        {findings.length > 0 && (
          <div className="rounded-lg border border-status-danger-border bg-status-danger-bg p-2 text-xs">
            {findings.map((f, i) => <div key={i}>{JSON.stringify(f)}</div>)}
          </div>
        )}
        {error && <div className="text-xs text-status-danger">{error}</div>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-border-default px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-hover cursor-pointer">Cancel</button>
          <button type="button" onClick={submit} disabled={pending} className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer disabled:opacity-50">
            {pending ? "Merging..." : "Merge"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ==========================================
// Live Data & Secret Vault Modal
// ==========================================
interface ClassCVaultModalProps {
  isOpen: boolean;
  serverId: string;
  onClose: () => void;
}

export function ClassCVaultModal({ isOpen, serverId, onClose }: ClassCVaultModalProps) {
  const [tab, setTab] = useState("snapshots");
  const [snapshots, setSnapshots] = useState<any[]>([]);
  const [dynamic, setDynamic] = useState<any[]>([]);
  const [secrets, setSecrets] = useState<any[]>([]);
  const [pinned, setPinned] = useState(false);
  const [branch, setBranch] = useState("");
  const [path, setPath] = useState("");
  const [keyName, setKeyName] = useState("");
  const [secretValue, setSecretValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  const reloadVault = useCallback(async () => {
    try {
      const api = (await import("@/services/api")).createAuthenticatedApi();
      const [s, d, sec] = await Promise.all([
        api.listClassCSnapshots(serverId).catch(() => []),
        api.listDynamicClassC(serverId).catch(() => []),
        api.listSecrets(serverId).catch(() => []),
      ]);
      setSnapshots(Array.isArray(s) ? s : []);
      setDynamic(Array.isArray(d) ? d : []);
      setSecrets(Array.isArray(sec) ? sec : []);
    } catch {
      /* ignore */
    }
  }, [serverId]);

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    void (async () => {
      try {
        const api = (await import("@/services/api")).createAuthenticatedApi();
        const [s, d, sec] = await Promise.all([
          api.listClassCSnapshots(serverId).catch(() => []),
          api.listDynamicClassC(serverId).catch(() => []),
          api.listSecrets(serverId).catch(() => []),
        ]);
        if (!active) return;
        setSnapshots(Array.isArray(s) ? s : []);
        setDynamic(Array.isArray(d) ? d : []);
        setSecrets(Array.isArray(sec) ? sec : []);
      } catch {
        /* ignore reload errors */
      }
    })();
    return () => {
      active = false;
    };
  }, [isOpen, serverId]);

  if (!isOpen) return null;

  const apiCall = async (fn: (api: any) => Promise<any>) => {
    const api = (await import("@/services/api")).createAuthenticatedApi();
    return fn(api);
  };

  return (
    <Modal open={isOpen} onClose={onClose} title="Live Data & Secret Vault">
      <div className="space-y-3">
        <div className="flex gap-2 border-b border-border-subtle pb-2">
          <button
            type="button"
            onClick={() => setTab("snapshots")}
            className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors ${
              tab === "snapshots"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Snapshots
          </button>
          <button
            type="button"
            onClick={() => setTab("dynamic")}
            className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors ${
              tab === "dynamic"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Live Runtime
          </button>
          <button
            type="button"
            onClick={() => setTab("secrets")}
            className={`rounded-md px-2.5 py-1 text-xs font-medium cursor-pointer transition-colors ${
              tab === "secrets"
                ? "bg-accent-primary text-accent-contrast-text"
                : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
            }`}
          >
            Secrets
          </button>
        </div>
        {tab === "snapshots" && (
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="inline-flex items-center gap-1.5 text-xs text-text-secondary cursor-pointer">
                <input
                  type="checkbox"
                  checked={pinned}
                  onChange={(e) => setPinned(e.target.checked)}
                  className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
                />
                Pin snapshot
              </label>
              <button
                type="button"
                onClick={async () => {
                  await apiCall((api) => api.createClassCSnapshot(serverId, { pinned }));
                  await reloadVault();
                }}
                className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
              >
                Create Live Data Snapshot
              </button>
            </div>
            {snapshots.map((s: any) => (
              <div key={s.snapshot_id} className="flex items-center justify-between gap-2 text-xs border border-border-subtle bg-surface-page rounded-lg p-2.5">
                <div className="min-w-0">
                  <div className="font-mono text-text-primary truncate">{s.snapshot_id}</div>
                  <div className="text-text-muted">{s.created_at} {s.entry_count} {s.archive_size_bytes} {s.manifest_sha256?.slice(0, 8)}</div>
                  {s.pinned && <span className="text-[10px] font-medium text-text-accent">Pinned</span>}
                </div>
                <div className="flex gap-1.5 shrink-0">
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await apiCall((api) => api.restoreClassCSnapshot(serverId, s.snapshot_id));
                      } catch (e: any) {
                        setMessage(e?.message ?? "Server must be stopped before restoring a live data snapshot");
                      }
                      await reloadVault();
                    }}
                    className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-text-primary hover:bg-surface-hover cursor-pointer"
                  >
                    Restore
                  </button>
                  <button
                    type="button"
                    disabled={s.pinned}
                    title={s.pinned ? "Pinned snapshot cannot be deleted until pins are released" : undefined}
                    onClick={async () => {
                      await apiCall((api) => api.deleteClassCSnapshot(serverId, s.snapshot_id));
                      await reloadVault();
                    }}
                    className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg disabled:opacity-40 cursor-pointer"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        {tab === "dynamic" && (
          <div className="space-y-2">
            {dynamic.map((e: any) => (
              <div key={e.relpath} className="flex items-center justify-between gap-2 text-xs border border-border-subtle bg-surface-page rounded-lg p-2.5">
                <div className="text-text-primary truncate">{e.relpath} {e.promoted_at} {e.main_commit_sha}</div>
                <button
                  type="button"
                  onClick={async () => {
                    await apiCall((api) => api.resetDynamicClassC(serverId, e.relpath));
                    await reloadVault();
                  }}
                  className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-text-primary hover:bg-surface-hover cursor-pointer shrink-0"
                >
                  Track in Git (from main)
                </button>
              </div>
            ))}
          </div>
        )}
        {tab === "secrets" && (
          <div className="space-y-2">
            {secrets.map((s: any) => (
              <div key={s.key_name} className="flex items-center justify-between gap-2 text-xs border border-border-subtle bg-surface-page rounded-lg p-2.5">
                <div className="text-text-primary truncate">{s.key_name} {s.placeholder} {s.kek_version} {s.updated_at}</div>
                <button
                  type="button"
                  onClick={async () => {
                    await apiCall((api) => api.deleteSecret(serverId, s.key_name));
                    await reloadVault();
                  }}
                  className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg cursor-pointer shrink-0"
                >
                  Delete
                </button>
              </div>
            ))}
            <div className="space-y-2 border-t border-border-subtle pt-3">
              <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Branch" className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary" />
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="Config File Path" className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary" />
              <input value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="Secret Key Name" className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary" />
              <input type="password" autoComplete="off" value={secretValue} onChange={(e) => setSecretValue(e.target.value)} placeholder="Secret Plaintext Value" className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary" />
              <button
                type="button"
                onClick={async () => {
                  const value = secretValue;
                  setSecretValue("");
                  try {
                    await apiCall((api) => api.extractSecret(serverId, { branch, path, key_name: keyName, secret_value: value }));
                    await reloadVault();
                  } catch (e: any) {
                    setMessage(e?.message ?? "Extract failed");
                  }
                }}
                className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
              >
                Extract Secret
              </button>
              {message && <div className="text-xs text-text-secondary">{message}</div>}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
