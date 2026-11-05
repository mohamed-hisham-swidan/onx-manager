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
}

export function CreateBranchModal({
  isOpen,
  branchName,
  onBranchNameChange,
  onSubmit,
  onClose,
}: CreateBranchModalProps) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-card p-6 space-y-4 shadow-2xl border border-border-default">
        <h3 className="text-base font-semibold text-text-primary">Create New Branch</h3>
        <div>
          <label htmlFor="branch-name-input" className="block text-xs font-medium text-text-secondary mb-1">
            Branch Name
          </label>
          <input
            id="branch-name-input"
            type="text"
            value={branchName}
            onChange={(e) => onBranchNameChange(e.target.value)}
            placeholder="e.g. feat-mod-upgrade"
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover cursor-pointer shadow-xs"
          >
            Create Branch
          </button>
        </div>
      </div>
    </div>
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
}: CreateCommitModalProps) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-card p-6 space-y-4 shadow-2xl border border-border-default">
        <h3 className="text-base font-semibold text-text-primary">Create Snapshot Commit</h3>
        <p className="text-xs text-text-muted">
          Captures all configs, mod jars, and creates an instant COW world snapshot on branch &lsquo;{selectedBranch}&rsquo;.
        </p>

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
              Branch &lsquo;{selectedBranch}&rsquo; requires changes to be verified in an isolated test run and promoted.
            </p>
            {allowForceBypass ? (
              <div className="pt-2 border-t border-status-warning/30 space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={forceBypass}
                    onChange={(e) => onForceBypassChange(e.target.checked)}
                    className="rounded border-border-default text-accent-primary focus:ring-accent-primary"
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
                      placeholder="e.g. Hotfix for critical crash"
                      className="w-full rounded border border-border-default bg-surface-page px-2.5 py-1 text-xs text-text-primary"
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
            disabled={currentBranchObj?.status === "archived"}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={
              !message.trim() ||
              currentBranchObj?.status === "archived" ||
              (isDirectCommitBlocked && (!allowForceBypass || !forceBypass || !forceReason.trim()))
            }
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shadow-xs"
          >
            {forceBypass ? "Force Commit Snapshot" : "Commit Snapshot"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ==========================================
// 3. Promote Commit Modal
// ==========================================
interface PromoteModalProps {
  isOpen: boolean;
  isForcePromote: boolean;
  promoteTestRun: ServerTestRun | null;
  forceReason: string;
  onForceReasonChange: (val: string) => void;
  keepWorldChanges: boolean;
  onKeepWorldChangesChange: (val: boolean) => void;
  onSubmit: () => void;
  onClose: () => void;
}

export function PromoteModal({
  isOpen,
  isForcePromote,
  promoteTestRun,
  forceReason,
  onForceReasonChange,
  keepWorldChanges,
  onKeepWorldChangesChange,
  onSubmit,
  onClose,
}: PromoteModalProps) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-card p-6 space-y-4 shadow-2xl border border-border-default">
        {isForcePromote ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 text-status-warning">
              <Icon name="alert" size={24} />
              <h3 className="text-base font-semibold text-text-primary">
                Force Promotion Override
              </h3>
            </div>
            <div className="rounded-lg bg-status-warning-bg border border-status-warning/40 p-3 space-y-2 text-xs">
              <p className="text-text-primary">
                This test run did not pass (status: <strong>{promoteTestRun?.status}</strong>).
                Promoting this commit bypasses automated verification gating and requires the{" "}
                <code className="font-mono bg-surface-page px-1 py-0.5 rounded text-accent-primary">
                  server:version:promote:force
                </code>{" "}
                permission.
              </p>
              <p className="text-text-muted">
                This administrative bypass will be permanently recorded in the server activity log.
              </p>
            </div>
            <div>
              <label
                htmlFor="force-reason-input"
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Bypass Reason (Required for audit log)
              </label>
              <input
                id="force-reason-input"
                type="text"
                value={forceReason}
                onChange={(e) => onForceReasonChange(e.target.value)}
                placeholder="e.g. Verified manually in offline client"
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
              />
            </div>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 text-status-success">
              <Icon name="check" size={24} />
              <h3 className="text-base font-semibold text-text-primary">
                Promote Verified Commit
              </h3>
            </div>
            <p className="text-xs text-text-secondary">
              This will atomically swap verified config and addon files into your production
              server. If the server is running, it will be safely restarted.
            </p>
          </>
        )}

        <div className="rounded-lg bg-surface-page p-3 border border-border-subtle">
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={keepWorldChanges}
              onChange={(e) => onKeepWorldChangesChange(e.target.checked)}
              className="mt-0.5 rounded border-border-default text-accent-primary focus:ring-accent-primary"
            />
            <span className="text-xs text-text-secondary">
              <strong className="block text-text-primary">Keep World Changes</strong>
              Also copy world block/entity modifications made by test bots into production. Leave
              unchecked for config-only promotion.
            </span>
          </label>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={isForcePromote && !forceReason.trim()}
            className={`rounded-lg px-3.5 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors cursor-pointer ${
              isForcePromote
                ? "bg-status-warning hover:bg-status-warning/90 disabled:opacity-50 disabled:cursor-not-allowed"
                : "bg-status-success hover:bg-status-success/90"
            }`}
          >
            {isForcePromote ? "Confirm Force Promotion" : "Confirm Promotion"}
          </button>
        </div>
      </div>
    </div>
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
  if (!commit) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
    >
      <div className="w-full max-w-2xl rounded-xl bg-surface-card p-6 space-y-4 shadow-2xl border border-border-default max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between border-b border-border-subtle pb-3">
          <div>
            <h3 className="text-base font-semibold text-text-primary">
              Manifest Snapshot Inspector
            </h3>
            <span className="font-mono text-xs text-text-muted">
              Commit {commit.id.slice(0, 8)} • {commit.message}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-muted hover:bg-surface-hover cursor-pointer"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        <div className="overflow-y-auto space-y-4 pr-1">
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
    </div>
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
  if (!testRun) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
    >
      <div className="w-full max-w-3xl rounded-xl bg-surface-card p-6 space-y-4 shadow-2xl border border-border-default max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between border-b border-border-subtle pb-3">
          <h3 className="text-base font-semibold text-text-primary">
            Test Run Console Output ({testRun.id.slice(0, 8)})
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-muted hover:bg-surface-hover cursor-pointer"
          >
            <Icon name="x" size={18} />
          </button>
        </div>
        <pre className="overflow-y-auto rounded-lg bg-surface-page border border-border-subtle p-3 text-xs font-mono text-status-success flex-1 whitespace-pre-wrap">
          {testRun.log_output || "No log output recorded."}
        </pre>
        <div className="flex justify-end pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-surface-page border border-border-default px-4 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    </div>
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
  onSubmit: () => void;
  onClose: () => void;
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
  onSubmit,
  onClose,
}: BotSettingsModalProps) {
  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs"
    >
      <div className="w-full max-w-md rounded-xl bg-surface-card p-6 space-y-4 shadow-2xl border border-border-default">
        <h3 className="text-base font-semibold text-text-primary">
          Bot Verification Server Defaults
        </h3>
        <p className="text-xs text-text-muted">
          Configure baseline parameters applied when launching dry-runs on this server.
        </p>

        <div className="space-y-3 text-xs">
          <div>
            <label htmlFor="settings-bot-count-input" className="block font-medium text-text-secondary mb-1">
              Default Bot Count
            </label>
            <input
              id="settings-bot-count-input"
              type="number"
              min={1}
              value={botCount}
              onChange={(e) => onBotCountChange(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
            />
          </div>

          <div>
            <label htmlFor="settings-duration-input" className="block font-medium text-text-secondary mb-1">
              Default Duration (Minutes)
            </label>
            <input
              id="settings-duration-input"
              type="number"
              min={1}
              value={duration}
              onChange={(e) => onDurationChange(Math.max(1, parseInt(e.target.value) || 1))}
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
            />
          </div>

          <div>
            <label htmlFor="settings-tech-select" className="block font-medium text-text-secondary mb-1">
              Default Bot Technology
            </label>
            <select
              id="settings-tech-select"
              value={tech}
              onChange={(e) => onTechChange(e.target.value)}
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
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
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
            >
              <option value="sidecar">Sidecar (Container Isolation)</option>
              <option value="in_container">In Container</option>
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-3 border-t border-border-subtle">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-accent-hover cursor-pointer shadow-xs"
          >
            Save Defaults
          </button>
        </div>
      </div>
    </div>
  );
}
