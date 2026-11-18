import { useState, useEffect } from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import type { ServerBranch, ServerCommit, ServerTestRun } from "@/server_manager/types";

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
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover cursor-pointer shadow-xs disabled:opacity-50 disabled:cursor-not-allowed"
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
          <div className="rounded-lg bg-surface-hover p-3 text-xs text-text-secondary">
            ⚠️ Branch &lsquo;{selectedBranch}&rsquo; is archived and read-only. Committing is disabled.
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
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shadow-xs"
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
                  <div key={f} className="text-text-primary py-0.5">
                    📄 {f}
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
                  <div key={m.filename} className="text-text-primary py-0.5">
                    📦 {m.filename} <span className="text-text-muted">({m.sha256.slice(0, 10)}...)</span>
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
// 5. Test Run Log Modal
// ==========================================
interface ViewLogsModalProps {
  testRun: ServerTestRun | null;
  onClose: () => void;
}

export function ViewLogsModal({ testRun, onClose }: ViewLogsModalProps) {
  return (
    <Modal
      open={!!testRun}
      onClose={onClose}
      title={testRun ? `Test Run Console Output (${testRun.id.slice(0, 8)})` : "Test Run Console Output"}
      size="2xl"
      showCloseButton={true}
      closeButtonAriaLabel="Close"
      closeOnBackdrop={false}
      className="max-h-[85vh] flex flex-col"
    >
      {testRun && (
        <div className="flex flex-col flex-1 min-h-0 space-y-4">
          <pre className="overflow-y-auto rounded-lg bg-surface-page border border-border-subtle p-3 text-xs font-mono text-status-success flex-1 whitespace-pre-wrap max-h-[60vh]">
            {testRun.log_output || "No log output recorded."}
          </pre>
          <div className="flex justify-end pt-2 border-t border-border-subtle">
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
// 6. Bot Verification Settings Modal
// ==========================================
interface BotSettingsModalProps {
  isOpen: boolean;
  botCount: number;
  onBotCountChange: (val: number) => void;
  duration: number;
  onDurationChange: (val: number) => void;
  tech: string;
  onTechChange: (val: string) => void;
  placement: string;
  onPlacementChange: (val: string) => void;
  retention: string;
  onRetentionChange: (val: string) => void;
  onSubmit: () => void;
  onClose: () => void;
  isPending?: boolean;
}

export function BotSettingsModal({
  isOpen,
  botCount,
  onBotCountChange,
  duration,
  onDurationChange,
  tech,
  onTechChange,
  placement,
  onPlacementChange,
  retention,
  onRetentionChange,
  onSubmit,
  onClose,
  isPending = false,
}: BotSettingsModalProps) {
  const [rawBotCount, setRawBotCount] = useState<string>(String(botCount));
  const [rawDuration, setRawDuration] = useState<string>(String(duration));
  const [prevProps, setPrevProps] = useState({ isOpen, botCount, duration });

  if (isOpen !== prevProps.isOpen || botCount !== prevProps.botCount || duration !== prevProps.duration) {
    setPrevProps({ isOpen, botCount, duration });
    if (isOpen) {
      setRawBotCount(String(botCount));
      setRawDuration(String(duration));
    }
  }

  const handleBotCountBlur = () => {
    const parsed = parseInt(rawBotCount, 10);
    const valid = isNaN(parsed) || parsed < 1 ? 1 : parsed;
    setRawBotCount(String(valid));
    onBotCountChange(valid);
  };

  const handleDurationBlur = () => {
    const parsed = parseInt(rawDuration, 10);
    const valid = isNaN(parsed) || parsed < 1 ? 1 : parsed;
    setRawDuration(String(valid));
    onDurationChange(valid);
  };

  const stepBotCount = (delta: number) => {
    const cur = parseInt(rawBotCount, 10) || 1;
    const next = Math.max(1, cur + delta);
    setRawBotCount(String(next));
    onBotCountChange(next);
  };

  const stepDuration = (delta: number) => {
    const cur = parseInt(rawDuration, 10) || 1;
    const next = Math.max(1, cur + delta);
    setRawDuration(String(next));
    onDurationChange(next);
  };

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Bot Verification Server Defaults"
      description="Configure baseline parameters applied when launching dry-runs on this server."
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!isPending) {
            const finalBot = Math.max(1, parseInt(rawBotCount, 10) || 1);
            const finalDur = Math.max(1, parseInt(rawDuration, 10) || 1);
            onBotCountChange(finalBot);
            onDurationChange(finalDur);
            onSubmit();
          }
        }}
        className="space-y-4"
      >
        <div className="space-y-3 text-xs">
          <div>
            <label htmlFor="settings-bot-count-input" className="block font-medium text-text-secondary mb-1">
              Default Bot Count
            </label>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                aria-label="Decrease default bot count"
                onClick={() => stepBotCount(-1)}
                disabled={isPending}
                className="h-9 w-9 rounded-lg border border-border-default bg-surface-card flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 disabled:opacity-50 cursor-pointer"
              >
                -
              </button>
              <input
                id="settings-bot-count-input"
                type="number"
                min={1}
                value={rawBotCount}
                onChange={(e) => setRawBotCount(e.target.value)}
                onBlur={handleBotCountBlur}
                disabled={isPending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50 text-center"
              />
              <button
                type="button"
                aria-label="Increase default bot count"
                onClick={() => stepBotCount(1)}
                disabled={isPending}
                className="h-9 w-9 rounded-lg border border-border-default bg-surface-card flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 disabled:opacity-50 cursor-pointer"
              >
                +
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="settings-duration-input" className="block font-medium text-text-secondary mb-1">
              Default Duration (Minutes)
            </label>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                aria-label="Decrease default duration"
                onClick={() => stepDuration(-1)}
                disabled={isPending}
                className="h-9 w-9 rounded-lg border border-border-default bg-surface-card flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 disabled:opacity-50 cursor-pointer"
              >
                -
              </button>
              <input
                id="settings-duration-input"
                type="number"
                min={1}
                value={rawDuration}
                onChange={(e) => setRawDuration(e.target.value)}
                onBlur={handleDurationBlur}
                disabled={isPending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50 text-center"
              />
              <button
                type="button"
                aria-label="Increase default duration"
                onClick={() => stepDuration(1)}
                disabled={isPending}
                className="h-9 w-9 rounded-lg border border-border-default bg-surface-card flex items-center justify-center text-text-secondary hover:text-text-primary hover:bg-surface-hover text-sm font-semibold transition-colors shrink-0 disabled:opacity-50 cursor-pointer"
              >
                +
              </button>
            </div>
          </div>

          <div>
            <label htmlFor="settings-tech-select" className="block font-medium text-text-secondary mb-1">
              Default Bot Technology
            </label>
            <select
              id="settings-tech-select"
              value={tech}
              onChange={(e) => onTechChange(e.target.value)}
              disabled={isPending}
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
            >
              <option value="auto">Auto (Server-type aware)</option>
              <option value="mineflayer">Mineflayer (External Protocol)</option>
              <option value="fakeplayer_next">FakePlayerNext (Paper In-Process)</option>
            </select>
          </div>

          <div>
            <label htmlFor="settings-placement-select" className="block font-medium text-text-secondary mb-1">
              Default Placement Mode
            </label>
            <select
              id="settings-placement-select"
              value={placement}
              onChange={(e) => onPlacementChange(e.target.value)}
              disabled={isPending}
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
            >
              <option value="sidecar">Sidecar (Container Isolation)</option>
              <option value="in_container">In Container</option>
            </select>
          </div>

          <div>
            <label htmlFor="settings-retention-select" className="block font-medium text-text-secondary mb-1">
              Previous Tree Retention Policy
            </label>
            <select
              id="settings-retention-select"
              aria-label="Previous Tree Retention Policy"
              value={retention}
              onChange={(e) => onRetentionChange(e.target.value)}
              disabled={isPending}
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
            >
              <option value="until_health_gate">Until Health Gate Passes (Default)</option>
              <option value="until_confirm">Until Operator Confirms Upgrade</option>
              <option value="1h">1 Hour</option>
              <option value="6h">6 Hours</option>
              <option value="24h">24 Hours</option>
              <option value="72h">72 Hours</option>
              <option value="168h">168 Hours (7 Days)</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-border-subtle">
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
            disabled={isPending}
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover cursor-pointer shadow-xs disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isPending ? "Saving..." : "Save Defaults"}
          </button>
        </div>
      </form>
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
  onClose: () => void;
}

export function MergeBranchModal({ isOpen, serverId, branches, selectedBranch, onClose }: MergeBranchModalProps) {
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
          <button type="button" onClick={onClose} className="rounded-lg border border-border-default px-3 py-1.5 text-xs">Cancel</button>
          <button type="button" onClick={submit} disabled={pending} className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs text-white">
            {pending ? "Merging..." : "Merge"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// ==========================================
// Class-C & Secret Vault Modal
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

  const load = async () => {
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
    } catch {}
  };

  useEffect(() => {
    if (isOpen) load();
  }, [isOpen]);

  if (!isOpen) return null;

  const apiCall = async (fn: (api: any) => Promise<any>) => {
    const api = (await import("@/services/api")).createAuthenticatedApi();
    return fn(api);
  };

  return (
    <Modal open={isOpen} onClose={onClose} title="Class-C & Secret Vault">
      <div className="space-y-3">
        <div className="flex gap-2">
          <button type="button" onClick={() => setTab("snapshots")} className="text-xs">Snapshots</button>
          <button type="button" onClick={() => setTab("dynamic")} className="text-xs">Dynamic Class-C</button>
          <button type="button" onClick={() => setTab("secrets")} className="text-xs">Secrets</button>
        </div>
        {tab === "snapshots" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <label className="text-xs"><input type="checkbox" checked={pinned} onChange={(e) => setPinned(e.target.checked)} /> Pin snapshot</label>
              <button type="button" onClick={async () => {
                await apiCall((api) => api.createClassCSnapshot(serverId, { pinned }));
                await load();
              }} className="rounded-lg bg-accent-primary px-2 py-1 text-xs text-white">Create Class-C Snapshot</button>
            </div>
            {snapshots.map((s: any) => (
              <div key={s.snapshot_id} className="flex items-center justify-between text-xs border rounded p-2">
                <div>
                  <div>{s.snapshot_id}</div>
                  <div>{s.created_at} {s.entry_count} {s.archive_size_bytes} {s.manifest_sha256?.slice(0, 8)}</div>
                  {s.pinned && <span className="text-[10px]">Pinned</span>}
                </div>
                <div className="flex gap-1">
                  <button type="button" onClick={async () => {
                    try {
                      await apiCall((api) => api.restoreClassCSnapshot(serverId, s.snapshot_id));
                    } catch (e: any) {
                      setMessage(e?.message ?? "Server must be stopped before restoring a Class-C snapshot");
                    }
                    await load();
                  }}>Restore</button>
                  <button type="button" disabled={s.pinned} title={s.pinned ? "Pinned snapshot cannot be deleted until pins are released" : undefined} onClick={async () => {
                    await apiCall((api) => api.deleteClassCSnapshot(serverId, s.snapshot_id));
                    await load();
                  }}>Delete</button>
                </div>
              </div>
            ))}
          </div>
        )}
        {tab === "dynamic" && (
          <div className="space-y-2">
            {dynamic.map((e: any) => (
              <div key={e.relpath} className="flex items-center justify-between text-xs border rounded p-2">
                <div>{e.relpath} {e.promoted_at} {e.main_commit_sha}</div>
                <button type="button" onClick={async () => {
                  await apiCall((api) => api.resetDynamicClassC(serverId, e.relpath));
                  await load();
                }}>Reset to Class B (Track from main)</button>
              </div>
            ))}
          </div>
        )}
        {tab === "secrets" && (
          <div className="space-y-2">
            {secrets.map((s: any) => (
              <div key={s.key_name} className="flex items-center justify-between text-xs border rounded p-2">
                <div>{s.key_name} {s.placeholder} {s.kek_version} {s.updated_at}</div>
                <button type="button" onClick={async () => {
                  await apiCall((api) => api.deleteSecret(serverId, s.key_name));
                  await load();
                }}>Delete</button>
              </div>
            ))}
            <div className="space-y-2 border-t pt-2">
              <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="Branch" className="w-full rounded-lg border px-2 py-1 text-xs" />
              <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="Config File Path (Class B)" className="w-full rounded-lg border px-2 py-1 text-xs" />
              <input value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="Secret Key Name" className="w-full rounded-lg border px-2 py-1 text-xs" />
              <input type="password" autoComplete="off" value={secretValue} onChange={(e) => setSecretValue(e.target.value)} placeholder="Secret Plaintext Value" className="w-full rounded-lg border px-2 py-1 text-xs" />
              <button type="button" onClick={async () => {
                const value = secretValue;
                setSecretValue("");
                try {
                  await apiCall((api) => api.extractSecret(serverId, { branch, path, key_name: keyName, secret_value: value }));
                  await load();
                } catch {}
              }} className="rounded-lg bg-accent-primary px-2 py-1 text-xs text-white">Extract Secret</button>
              {message && <div className="text-xs">{message}</div>}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
