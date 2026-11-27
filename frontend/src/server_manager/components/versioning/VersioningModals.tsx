import { useState, useEffect, useCallback, useMemo } from "react";
import { Modal } from "@/components/ui/Modal";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { formatBytes, formatDateTime } from "@/server_manager/utils/format";
import {
  formatServerTypeLabel,
  RETENTION_POLICY_OPTIONS,
  validateBranchName,
} from "@/server_manager/utils/versioningFormat";
import type {
  ClassCSnapshot,
  DiffResponse,
  DynamicClassCEntry,
  SecretMetadata,
  ServerBranch,
  ServerCommit,
} from "@/server_manager/types";

type AuthenticatedApi = ReturnType<typeof createAuthenticatedApi>;

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
  const [touched, setTouched] = useState(false);
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setTouched(false);
    }
  }

  const validationError = branchName.trim() ? validateBranchName(branchName) : null;
  const canSubmit = Boolean(branchName.trim()) && !validationError && !isPending;

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Create New Branch"
      description="Branches isolate config & plugin edits from production main."
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
      footer={
        <div className="flex justify-end gap-2">
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
            form="create-branch-form"
            disabled={!canSubmit}
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer shadow-xs disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isPending ? "Creating..." : "Create Branch"}
          </button>
        </div>
      }
    >
      <form
        id="create-branch-form"
        onSubmit={(e) => {
          e.preventDefault();
          setTouched(true);
          if (canSubmit) onSubmit();
        }}
        className="space-y-3"
      >
        <div>
          <label
            htmlFor="branch-name-input"
            className="block text-xs font-medium text-text-secondary mb-1"
          >
            Branch Name
          </label>
          <input
            id="branch-name-input"
            type="text"
            value={branchName}
            onChange={(e) => {
              setTouched(true);
              onBranchNameChange(e.target.value);
            }}
            disabled={isPending}
            placeholder="e.g. feat-mod-upgrade"
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
          />
          <p className="mt-1 text-[11px] text-text-muted">
            Allowed: letters, numbers, dots, underscores, or hyphens (1–63 chars).
          </p>
          {touched && validationError && (
            <p className="mt-1 text-[11px] font-medium text-status-danger">
              {validationError}
            </p>
          )}
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
  const isMainBranch = selectedBranch === "main";
  const isArchived = currentBranchObj?.status === "archived";
  const submitDisabled =
    isPending ||
    isMainBranch ||
    isArchived ||
    !message.trim() ||
    (isDirectCommitBlocked &&
      (!allowForceBypass || !forceBypass || !forceReason.trim()));

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Create Snapshot Commit"
      description={`Captures configs and addon lockfile changes into branch '${selectedBranch}'.`}
      size="md"
      showCloseButton={false}
      closeOnBackdrop={false}
      closeOnEscape={!isPending}
      footer={
        <div className="flex justify-end gap-2">
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
            disabled={submitDisabled}
            className="rounded-lg bg-accent-primary px-3.5 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer shadow-xs"
          >
            {isPending
              ? "Saving..."
              : forceBypass
                ? "Force Save Snapshot"
                : "Commit Snapshot"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {isMainBranch && (
          <div className="flex items-start gap-2 rounded-lg border border-status-warning-border bg-status-warning-bg p-3 text-xs text-status-warning">
            <Icon name="alert" size={14} className="mt-0.5 shrink-0" />
            <span>
              Direct commits to <code className="font-mono font-semibold">main</code>{" "}
              are blocked to protect production. Save snapshots on a working branch and merge into{" "}
              <code className="font-mono font-semibold">main</code> instead.
            </span>
          </div>
        )}

        {isArchived && (
          <div className="flex items-center gap-2 rounded-lg bg-surface-hover p-3 text-xs text-text-secondary">
            <Icon name="alert" size={14} className="shrink-0 text-status-warning" />
            <span>
              Branch &lsquo;{selectedBranch}&rsquo; is archived and read-only. Committing is disabled.
            </span>
          </div>
        )}

        {!isMainBranch && isDirectCommitBlocked && (
          <div className="p-3 bg-status-warning-bg border border-status-warning/40 rounded-lg text-xs space-y-2">
            <div className="flex items-center gap-1.5 font-semibold text-status-warning">
              <Icon name="alert" size={14} />
              <span>Direct Commits Blocked by Protection Policy</span>
            </div>
            <p className="text-text-secondary">
              Branch &lsquo;{selectedBranch}&rsquo; has direct commits disabled in its protection rules.
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
          <label
            htmlFor="commit-message-input"
            className="block text-xs font-medium text-text-secondary mb-1"
          >
            Commit Message
          </label>
          <input
            id="commit-message-input"
            type="text"
            value={message}
            onChange={(e) => onMessageChange(e.target.value)}
            placeholder="e.g. Pre-WorldEdit update snapshot"
            disabled={isPending || isArchived || isMainBranch}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary disabled:opacity-50"
          />
        </div>
      </div>
    </Modal>
  );
}

// ==========================================
// 3. Manifest Inspect Modal (retained for compatibility)
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
      footer={
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg bg-surface-page border border-border-default px-4 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Close
          </button>
        </div>
      }
    >
      {commit && (
        <div className="space-y-4">
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
                    {m.filename}{" "}
                    <span className="text-text-muted">({m.sha256.slice(0, 10)}...)</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ==========================================
// 4. Deploy / Restore to Live Confirmation Modal
// ==========================================
export interface DeployLiveModalProps {
  isOpen: boolean;
  targetCommit?: ServerCommit | null;
  mainHeadSha?: string | null;
  defaultRetention?: string;
  isPending?: boolean;
  onConfirm: (retentionPolicy: string, targetCommitSha?: string | null) => Promise<void> | void;
  onClose: () => void;
}

export function DeployLiveModal({
  isOpen,
  targetCommit,
  mainHeadSha,
  defaultRetention,
  isPending = false,
  onConfirm,
  onClose,
}: DeployLiveModalProps) {
  const preferredDefault =
    defaultRetention && defaultRetention !== "until_health_gate"
      ? defaultRetention
      : "until_confirm";
  const [retention, setRetention] = useState(preferredDefault);
  const [error, setError] = useState<string | null>(null);
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setError(null);
      setRetention(preferredDefault);
    }
  }

  const isRestore = Boolean(targetCommit);
  const displaySha = targetCommit?.id ?? mainHeadSha ?? null;

  const handleConfirm = async () => {
    setError(null);
    try {
      await onConfirm(retention, targetCommit?.id ?? null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Deployment failed.");
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={isPending ? () => undefined : onClose}
      title={isRestore ? "Restore Snapshot to Live Server" : "Deploy main to Live Server"}
      description={
        displaySha
          ? `Target snapshot: ${displaySha.slice(0, 8)}${targetCommit?.message ? ` — ${targetCommit.message}` : ""}`
          : "Exports main branch files safely onto your live server."
      }
      size="lg"
      closeOnBackdrop={!isPending}
      closeOnEscape={!isPending}
      footer={
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg border border-border-default bg-surface-page px-3.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer disabled:opacity-50 shadow-xs"
          >
            <Icon name={isRestore ? "restart" : "upload"} size={13} />
            {isPending
              ? isRestore
                ? "Restoring..."
                : "Deploying..."
              : isRestore
                ? "Restore to Live"
                : "Deploy to Live"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <div
            role="alert"
            className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
          >
            {error}
          </div>
        )}

        <div className="rounded-lg border border-status-info-border bg-status-info-bg p-3.5 text-xs text-text-primary space-y-1.5">
          <div className="font-semibold text-status-info flex items-center gap-1.5">
            <Icon name="info" size={14} />
            <span>Safe Live Update Guarantees</span>
          </div>
          <ul className="list-disc pl-5 space-y-1 text-text-secondary">
            <li>Stops the live server cleanly before swapping files.</li>
            <li>Creates a pinned full backup and live world/plugin data snapshot.</li>
            <li>Preserves your worlds, player data, and runtime exclusions intact.</li>
            <li>Runs startup health checks and automatically rolls back on crash.</li>
          </ul>
        </div>

        <div className="space-y-2">
          <label
            htmlFor="deploy-retention-select"
            className="block text-xs font-semibold text-text-secondary"
          >
            Undo Backup Retention
          </label>
          <select
            id="deploy-retention-select"
            value={retention}
            onChange={(e) => setRetention(e.target.value)}
            disabled={isPending}
            className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-xs text-text-primary focus:outline-none focus:border-accent-primary"
          >
            {RETENTION_POLICY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          <p className="text-[11px] text-text-muted">
            {RETENTION_POLICY_OPTIONS.find((o) => o.value === retention)?.description}
          </p>
        </div>
      </div>
    </Modal>
  );
}

// ==========================================
// 5. Merge Branch Modal (Redesigned)
// ==========================================
interface MergeConflictItem {
  path?: string;
  key_path?: string;
  base?: string;
  ours?: string;
  theirs?: string;
}

interface SecretFindingItem {
  path?: string;
  key_path?: string;
  pattern?: string;
  message?: string;
  line?: number;
}

interface MergeBranchModalProps {
  isOpen: boolean;
  serverId: string;
  branches: ServerBranch[];
  selectedBranch?: string;
  initialSourceBranch?: string | null;
  onMerged?: () => void;
  onDeployMain?: () => void;
  onClose: () => void;
}

export function MergeBranchModal({
  isOpen,
  serverId,
  branches,
  selectedBranch,
  initialSourceBranch,
  onMerged,
  onDeployMain,
  onClose,
}: MergeBranchModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const nonArchived = useMemo(
    () => (branches || []).filter((b) => b.status !== "archived"),
    [branches],
  );

  const [targetBranch, setTargetBranch] = useState("main");
  const [sourceBranch, setSourceBranch] = useState("");
  const [message, setMessage] = useState("");
  const [forceBypass, setForceBypass] = useState(false);
  const [forceReason, setForceReason] = useState("");
  const [pending, setPending] = useState(false);
  const [mergeCompleted, setMergeCompleted] = useState(false);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [conflicts, setConflicts] = useState<MergeConflictItem[]>([]);
  const [findings, setFindings] = useState<SecretFindingItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [rawPreviewDiff, setRawPreviewDiff] = useState<DiffResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      const preferredTarget = "main";
      const preferredSource =
        initialSourceBranch && initialSourceBranch !== preferredTarget
          ? initialSourceBranch
          : selectedBranch && selectedBranch !== preferredTarget
            ? selectedBranch
            : nonArchived.find((b) => b.name !== preferredTarget)?.name ?? "";
      setTargetBranch(preferredTarget);
      setSourceBranch(preferredSource);
      setMessage("");
      setForceBypass(false);
      setForceReason("");
      setMergeCompleted(false);
      setWarnings([]);
      setConflicts([]);
      setFindings([]);
      setError(null);
      setRawPreviewDiff(null);
    }
  }

  const canPreviewDiff =
    isOpen &&
    Boolean(serverId) &&
    Boolean(sourceBranch) &&
    Boolean(targetBranch) &&
    sourceBranch !== targetBranch;
  const previewDiff = canPreviewDiff ? rawPreviewDiff : null;

  // Live pre-merge diff preview
  useEffect(() => {
    if (!canPreviewDiff) {
      return;
    }
    let alive = true;
    void Promise.resolve().then(() => {
      if (alive) setPreviewLoading(true);
    });
    api
      .diffCommits(serverId, targetBranch, sourceBranch)
      .then((res) => {
        if (alive) setRawPreviewDiff(res);
      })
      .catch(() => {
        if (alive) setRawPreviewDiff(null);
      })
      .finally(() => {
        if (alive) setPreviewLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [canPreviewDiff, serverId, sourceBranch, targetBranch, api]);

  if (!isOpen) return null;

  const sources = nonArchived.filter((b) => b.name !== targetBranch);
  const targetBranchObj = nonArchived.find((b) => b.name === targetBranch) ?? null;
  const requiresForceForCustomProtected = Boolean(
    targetBranch !== "main" &&
      targetBranchObj?.is_protected &&
      targetBranchObj.protection_policy &&
      !targetBranchObj.protection_policy.allow_direct_commit,
  );

  const configChangeCount = previewDiff
    ? (Array.isArray(previewDiff.configs?.added)
        ? previewDiff.configs.added.length
        : Object.keys(previewDiff.configs?.added ?? {}).length) +
      (Array.isArray(previewDiff.configs?.modified)
        ? previewDiff.configs.modified.length
        : Object.keys(previewDiff.configs?.modified ?? {}).length) +
      (Array.isArray(previewDiff.configs?.removed)
        ? previewDiff.configs.removed.length
        : Object.keys(previewDiff.configs?.removed ?? {}).length)
    : 0;
  const modChangeCount = previewDiff
    ? (previewDiff.mods?.added?.length ?? 0) +
      (previewDiff.mods?.modified?.length ?? 0) +
      (previewDiff.mods?.removed?.length ?? 0)
    : 0;

  const canSubmit =
    !pending &&
    Boolean(sourceBranch) &&
    Boolean(targetBranch) &&
    sourceBranch !== targetBranch;

  const submit = async () => {
    if (!canSubmit) return;
    setPending(true);
    setWarnings([]);
    setConflicts([]);
    setFindings([]);
    setError(null);
    try {
      const res = await api.mergeServerCommits(serverId, {
        target_branch_name: targetBranch,
        source_branch_name: sourceBranch,
        message: message.trim() || `Merge branch '${sourceBranch}' into ${targetBranch}`,
        force: forceBypass,
        force_reason: forceBypass ? forceReason.trim() || null : null,
        force_bypass_protection: forceBypass,
      });
      const nextWarnings = Array.isArray(res?.warnings)
        ? res.warnings.map((w) => String(w))
        : [];
      setWarnings(nextWarnings);
      onMerged?.();

      if (targetBranch === "main" || nextWarnings.length > 0) {
        setMergeCompleted(true);
      } else {
        onClose();
      }
    } catch (e: unknown) {
      const errObj = e as { detail?: unknown; message?: string } | null;
      const detail = errObj?.detail ?? null;
      if (detail && typeof detail === "object") {
        const detailRec = detail as { conflicts?: unknown; findings?: unknown };
        if (Array.isArray(detailRec.conflicts)) {
          setConflicts(detailRec.conflicts as MergeConflictItem[]);
        }
        if (Array.isArray(detailRec.findings)) {
          setFindings(detailRec.findings as SecretFindingItem[]);
        }
      }
      setError(errObj?.message ?? "Merge failed.");
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={pending ? () => undefined : onClose}
      title="Merge Branch"
      description="Combine verified changes from a working branch into another branch."
      size="xl"
      closeOnBackdrop={!pending}
      closeOnEscape={!pending}
      footer={
        mergeCompleted ? (
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-border-default bg-surface-page px-3.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
            >
              Done
            </button>
            {targetBranch === "main" && onDeployMain && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onDeployMain();
                }}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer shadow-xs"
              >
                <Icon name="upload" size={13} />
                Deploy main to Live Now
              </button>
            )}
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={pending}
              className="rounded-lg border border-border-default bg-surface-page px-3.5 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={submit}
              disabled={!canSubmit}
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent-primary px-4 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed shadow-xs"
            >
              <Icon name="version-branch" size={13} />
              {pending ? "Merging..." : "Merge Branch"}
            </button>
          </div>
        )
      }
    >
      {mergeCompleted ? (
        <div className="space-y-4">
          <div className="rounded-lg border border-status-success-border bg-status-success-bg p-3.5 text-xs text-status-success space-y-1">
            <div className="font-semibold flex items-center gap-1.5">
              <Icon name="check" size={14} />
              <span>
                Merged <code className="font-mono">{sourceBranch}</code> into{" "}
                <code className="font-mono">{targetBranch}</code>
              </span>
            </div>
            {targetBranch === "main" && (
              <p className="text-text-secondary">
                Your changes are now committed on <code className="font-mono">main</code>. Deploy{" "}
                <code className="font-mono">main</code> to apply them to the running live server.
              </p>
            )}
          </div>

          {warnings.length > 0 && (
            <div className="rounded-lg border border-status-warning-border bg-status-warning-bg p-3 text-xs text-status-warning space-y-1">
              <div className="font-semibold">Merge Warnings</div>
              <ul className="list-disc pl-4 space-y-0.5 text-text-primary">
                {warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="merge-source-select"
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Source Branch (changes from)
              </label>
              <select
                id="merge-source-select"
                value={sourceBranch}
                onChange={(e) => setSourceBranch(e.target.value)}
                disabled={pending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
              >
                <option value="">Select source branch</option>
                {sources.map((b) => (
                  <option key={b.id ?? b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label
                htmlFor="merge-target-select"
                className="block text-xs font-medium text-text-secondary mb-1"
              >
                Target Branch (merge into)
              </label>
              <select
                id="merge-target-select"
                value={targetBranch}
                onChange={(e) => setTargetBranch(e.target.value)}
                disabled={pending}
                className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
              >
                {nonArchived.map((b) => (
                  <option key={b.id ?? b.name} value={b.name}>
                    {b.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Pre-merge Diff Preview */}
          {sourceBranch && targetBranch && sourceBranch !== targetBranch && (
            <div className="rounded-lg border border-border-subtle bg-surface-page p-3 text-xs space-y-1.5">
              <div className="font-semibold text-text-secondary flex items-center justify-between">
                <span>
                  Preview: <code className="font-mono">{targetBranch}</code> ←{" "}
                  <code className="font-mono">{sourceBranch}</code>
                </span>
                {previewLoading && (
                  <span className="text-[11px] text-text-muted italic">
                    Checking changes...
                  </span>
                )}
              </div>
              {!previewLoading && previewDiff && (
                <div className="flex flex-wrap items-center gap-3 text-[11px] text-text-muted">
                  <span>
                    <strong className="text-text-primary">{configChangeCount}</strong> config file
                    {configChangeCount === 1 ? "" : "s"} changed
                  </span>
                  <span>·</span>
                  <span>
                    <strong className="text-text-primary">{modChangeCount}</strong> plugin/mod
                    {modChangeCount === 1 ? "" : "s"} changed
                  </span>
                  {previewDiff.server_type && (
                    <>
                      <span>·</span>
                      <span>
                        Loader: {formatServerTypeLabel(previewDiff.server_type.from)} →{" "}
                        {formatServerTypeLabel(previewDiff.server_type.to)}
                      </span>
                    </>
                  )}
                  {previewDiff.minecraft_version && (
                    <>
                      <span>·</span>
                      <span>
                        MC: {previewDiff.minecraft_version.from} →{" "}
                        {previewDiff.minecraft_version.to}
                      </span>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          <div>
            <label
              htmlFor="merge-message-input"
              className="block text-xs font-medium text-text-secondary mb-1"
            >
              Merge Commit Message (optional)
            </label>
            <input
              id="merge-message-input"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              disabled={pending}
              placeholder={
                sourceBranch
                  ? `Merge branch '${sourceBranch}' into ${targetBranch}`
                  : "Merge message"
              }
              className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-primary"
            />
          </div>

          {requiresForceForCustomProtected && (
            <div className="rounded-lg border border-status-warning-border bg-status-warning-bg p-3 text-xs space-y-2">
              <label className="flex items-center gap-2 font-semibold text-status-warning cursor-pointer">
                <input
                  type="checkbox"
                  checked={forceBypass}
                  onChange={(e) => setForceBypass(e.target.checked)}
                />
                Override branch protection on &lsquo;{targetBranch}&rsquo;
              </label>
              {forceBypass && (
                <input
                  value={forceReason}
                  onChange={(e) => setForceReason(e.target.value)}
                  placeholder="Override reason (audit logged)"
                  className="w-full rounded-lg border border-border-default bg-surface-page px-3 py-1.5 text-xs text-text-primary"
                />
              )}
            </div>
          )}

          {conflicts.length > 0 && (
            <div
              role="alert"
              className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs space-y-2"
            >
              <div className="font-semibold text-status-danger">
                Merge Conflicts Detected ({conflicts.length})
              </div>
              <div className="max-h-44 overflow-y-auto space-y-2">
                {conflicts.map((c, i) => (
                  <div
                    key={i}
                    className="rounded border border-status-danger-border/60 bg-surface-card p-2 space-y-1 break-all"
                  >
                    <div className="font-mono font-semibold text-text-primary">
                      {c.path || "(unknown path)"}
                      {c.key_path ? ` → ${c.key_path}` : ""}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5 font-mono text-[11px]">
                      <div className="rounded bg-surface-page p-1.5 text-text-muted">
                        <span className="block text-[10px] uppercase">Base</span>
                        {c.base ?? "—"}
                      </div>
                      <div className="rounded bg-surface-page p-1.5 text-text-primary">
                        <span className="block text-[10px] uppercase text-text-muted">
                          Target ({targetBranch})
                        </span>
                        {c.ours ?? "—"}
                      </div>
                      <div className="rounded bg-surface-page p-1.5 text-accent-primary">
                        <span className="block text-[10px] uppercase text-text-muted">
                          Incoming ({sourceBranch})
                        </span>
                        {c.theirs ?? "—"}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {findings.length > 0 && (
            <div
              role="alert"
              className="rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs space-y-2"
            >
              <div className="font-semibold text-status-danger">
                Secret Scan Blocked Merge ({findings.length} finding
                {findings.length === 1 ? "" : "s"})
              </div>
              <p className="text-text-secondary">
                Extract sensitive tokens into the encrypted Secret Vault (Sync &amp; Vault tab) before merging.
              </p>
              <div className="max-h-36 overflow-y-auto space-y-1.5">
                {findings.map((f, i) => (
                  <div
                    key={i}
                    className="rounded border border-status-danger-border/60 bg-surface-card p-2 font-mono text-[11px] text-text-primary break-all"
                  >
                    {f.path || "config"}{" "}
                    {f.key_path ? `· ${f.key_path}` : ""}{" "}
                    {f.pattern ? `(${f.pattern})` : ""}{" "}
                    {f.message ? `— ${f.message}` : ""}
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div
              role="alert"
              className="rounded-lg border border-status-danger-border bg-status-danger-bg p-2.5 text-xs text-status-danger"
            >
              {error}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

// ==========================================
// 6. Live Data & Secret Vault Modal (upgraded to size="xl" + sticky footer)
// ==========================================
interface ClassCVaultModalProps {
  isOpen: boolean;
  serverId: string;
  canEdit?: boolean;
  onClose: () => void;
}

export function ClassCVaultModal({
  isOpen,
  serverId,
  canEdit = true,
  onClose,
}: ClassCVaultModalProps) {
  const [tab, setTab] = useState("snapshots");
  const [snapshots, setSnapshots] = useState<ClassCSnapshot[]>([]);
  const [dynamic, setDynamic] = useState<DynamicClassCEntry[]>([]);
  const [secrets, setSecrets] = useState<SecretMetadata[]>([]);
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
      setMessage("Failed to load vault data.");
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
        if (active) setMessage("Failed to load vault data.");
      }
    })();
    return () => {
      active = false;
    };
  }, [isOpen, serverId]);

  if (!isOpen) return null;

  const apiCall = async <T,>(fn: (api: AuthenticatedApi) => Promise<T>): Promise<T> => {
    const api = (await import("@/services/api")).createAuthenticatedApi();
    return fn(api);
  };

  return (
    <Modal
      open={isOpen}
      onClose={onClose}
      title="Live Data & Secret Vault"
      size="xl"
      footer={
        <div className="flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-border-default bg-surface-page px-4 py-1.5 text-xs font-medium text-text-secondary hover:bg-surface-hover cursor-pointer"
          >
            Close
          </button>
        </div>
      }
    >
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
            {canEdit && (
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
                    try {
                      await apiCall((api) => api.createClassCSnapshot(serverId, { pinned }));
                      setMessage(null);
                      await reloadVault();
                    } catch (e: unknown) {
                      setMessage(e instanceof Error ? e.message : "Failed to create snapshot");
                    }
                  }}
                  className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
                >
                  Create Live Data Snapshot
                </button>
              </div>
            )}
            {snapshots.map((s) => (
              <div
                key={s.snapshot_id}
                className="flex items-center justify-between gap-2 text-xs border border-border-subtle bg-surface-page rounded-lg p-2.5"
              >
                <div className="min-w-0">
                  <div className="font-mono text-text-primary truncate">{s.snapshot_id}</div>
                  <div className="text-text-muted">
                    {formatDateTime(s.created_at)} · {s.entry_count} entries ·{" "}
                    {formatBytes(s.archive_size_bytes)}
                    {s.manifest_sha256 ? ` · ${s.manifest_sha256.slice(0, 8)}` : ""}
                  </div>
                  {s.pinned && (
                    <span className="text-[10px] font-medium text-accent-primary">Pinned</span>
                  )}
                </div>
                {canEdit && (
                  <div className="flex gap-1.5 shrink-0">
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          await apiCall((api) =>
                            api.restoreClassCSnapshot(serverId, s.snapshot_id),
                          );
                          setMessage("Live data snapshot restored.");
                        } catch (e: unknown) {
                          setMessage(
                            e instanceof Error
                              ? e.message
                              : "Server must be stopped before restoring a live data snapshot",
                          );
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
                      title={
                        s.pinned
                          ? "Pinned snapshot cannot be deleted until pins are released"
                          : undefined
                      }
                      onClick={async () => {
                        try {
                          await apiCall((api) =>
                            api.deleteClassCSnapshot(serverId, s.snapshot_id),
                          );
                          setMessage(null);
                          await reloadVault();
                        } catch (e: unknown) {
                          setMessage(
                            e instanceof Error ? e.message : "Failed to delete snapshot",
                          );
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

        {tab === "dynamic" && (
          <div className="space-y-2">
            {dynamic.map((e) => (
              <div
                key={e.relpath}
                className="flex items-center justify-between gap-2 text-xs border border-border-subtle bg-surface-page rounded-lg p-2.5"
              >
                <div className="min-w-0">
                  <div className="font-mono text-text-primary truncate">{e.relpath}</div>
                  <div className="text-[11px] text-text-muted">
                    Promoted {formatDateTime(e.promoted_at)}
                    {e.main_commit_sha ? ` · ${e.main_commit_sha.slice(0, 8)}` : ""}
                  </div>
                </div>
                {canEdit && (
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await apiCall((api) => api.resetDynamicClassC(serverId, e.relpath));
                        setMessage(null);
                        await reloadVault();
                      } catch (err: unknown) {
                        setMessage(err instanceof Error ? err.message : "Failed to reset file");
                      }
                    }}
                    className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-text-primary hover:bg-surface-hover cursor-pointer shrink-0"
                  >
                    Track in Git (from main)
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {tab === "secrets" && (
          <div className="space-y-2">
            {secrets.map((s) => (
              <div
                key={s.key_name}
                className="flex items-center justify-between gap-2 text-xs border border-border-subtle bg-surface-page rounded-lg p-2.5"
              >
                <div className="min-w-0">
                  <div className="font-semibold text-text-primary truncate">
                    {s.key_name}{" "}
                    <code className="font-mono font-normal text-text-secondary">
                      {s.placeholder}
                    </code>
                  </div>
                  <div className="text-[11px] text-text-muted">
                    Key v{s.kek_version} · Updated {formatDateTime(s.updated_at)}
                  </div>
                </div>
                {canEdit && (
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        await apiCall((api) => api.deleteSecret(serverId, s.key_name));
                        setMessage(null);
                        await reloadVault();
                      } catch (err: unknown) {
                        setMessage(
                          err instanceof Error ? err.message : "Failed to delete secret",
                        );
                      }
                    }}
                    className="rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-status-danger hover:bg-status-danger-bg cursor-pointer shrink-0"
                  >
                    Delete
                  </button>
                )}
              </div>
            ))}
            {canEdit && (
              <div className="space-y-2 border-t border-border-subtle pt-3">
                <input
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  placeholder="Branch"
                  className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                />
                <input
                  value={path}
                  onChange={(e) => setPath(e.target.value)}
                  placeholder="Config File Path"
                  className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                />
                <input
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  placeholder="Secret Key Name"
                  className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                />
                <input
                  type="password"
                  autoComplete="off"
                  value={secretValue}
                  onChange={(e) => setSecretValue(e.target.value)}
                  placeholder="Secret Plaintext Value"
                  className="w-full rounded-lg border border-border-default bg-surface-page px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-hidden focus:border-accent-primary"
                />
                <button
                  type="button"
                  onClick={async () => {
                    const value = secretValue;
                    setSecretValue("");
                    try {
                      await apiCall((api) =>
                        api.extractSecret(serverId, {
                          branch,
                          path,
                          key_name: keyName,
                          secret_value: value,
                        }),
                      );
                      setMessage(null);
                      await reloadVault();
                    } catch (e: unknown) {
                      setMessage(e instanceof Error ? e.message : "Extract failed");
                    }
                  }}
                  className="rounded-lg bg-accent-primary px-3 py-1.5 text-xs font-semibold text-accent-contrast-text hover:bg-accent-hover cursor-pointer"
                >
                  Extract Secret
                </button>
              </div>
            )}
          </div>
        )}
        {message && <div className="text-xs text-text-secondary">{message}</div>}
      </div>
    </Modal>
  );
}
