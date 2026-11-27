import { useState, useMemo } from "react";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toastStore";
import { parseServerDate } from "@/server_manager/utils/format";
import type { ServerBranch } from "@/server_manager/types";

interface ManageBranchesModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  branches: ServerBranch[];
  currentBranchName: string;
  canEdit?: boolean;
  onBranchesChanged: () => void;
  onOpenProtectionModal: (branch: ServerBranch) => void;
}

export function ManageBranchesModal({
  isOpen,
  onClose,
  serverId,
  branches,
  currentBranchName,
  canEdit = true,
  onBranchesChanged,
  onOpenProtectionModal,
}: ManageBranchesModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [busyBranch, setBusyBranch] = useState<string | null>(null);
  const [confirmArchiveName, setConfirmArchiveName] = useState<string | null>(null);
  const [confirmDeleteName, setConfirmDeleteName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setError(null);
      setConfirmArchiveName(null);
      setConfirmDeleteName(null);
    }
  }

  const handleClose = () => {
    if (!busyBranch) {
      onClose();
    }
  };

  const handleArchive = async (branchName: string) => {
    setBusyBranch(branchName);
    setError(null);
    try {
      await api.archiveBranch(serverId, branchName);
      toast("success", "Branch Archived", `Branch '${branchName}' has been archived.`);
      setConfirmArchiveName(null);
      onBranchesChanged();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to archive branch.";
      setError(msg);
    } finally {
      setBusyBranch(null);
    }
  };

  const handleDelete = async (branchName: string) => {
    setBusyBranch(branchName);
    setError(null);
    try {
      await api.deleteServerBranch(serverId, branchName);
      toast("success", "Branch Deleted", `Branch '${branchName}' has been deleted.`);
      setConfirmDeleteName(null);
      onBranchesChanged();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete branch.";
      setError(msg);
    } finally {
      setBusyBranch(null);
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "active":
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-status-success-bg text-status-success border border-status-success-border">
            Active
          </span>
        );
      case "archived":
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-surface-muted text-text-muted border border-border-default">
            Archived
          </span>
        );
      case "created":
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-status-info-bg text-status-info border border-status-info-border">
            Created
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-surface-muted text-text-secondary border border-border-default">
            {status}
          </span>
        );
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={handleClose}
      title="Branch Lifecycle Management"
      description="Manage branch protection rules, archive inactive branches, or delete branches"
      size="xl"
      closeOnBackdrop={!busyBranch}
      closeOnEscape={!busyBranch}
      closeButtonAriaLabel="Close modal"
      footer={
        <div className="flex items-center justify-end">
          <button
            type="button"
            onClick={handleClose}
            disabled={!!busyBranch}
            className="px-4 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
          >
            Close
          </button>
        </div>
      }
    >
      <div className="space-y-4 flex flex-col text-text-primary">
        {error && (
          <div
            role="alert"
            className="flex items-center gap-2 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger"
          >
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-status-danger hover:opacity-80 transition-opacity"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        )}

        {confirmArchiveName && (
          <div
            role="alert"
            className="rounded-lg border border-status-warning-border bg-status-warning-bg p-4 space-y-2 animate-fade-in"
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-status-warning">
              <Icon name="alert" size={18} />
              <span>{`Archive Branch '${confirmArchiveName}'?`}</span>
            </div>
            <p className="text-xs text-text-primary">
              Archived branches become read-only. No new commits can be created on an archived branch.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmArchiveName(null)}
                className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-card border border-border-default rounded-lg hover:bg-surface-hover transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleArchive(confirmArchiveName)}
                disabled={busyBranch === confirmArchiveName}
                className="px-3 py-1.5 text-xs font-medium text-accent-contrast-text bg-status-warning hover:opacity-90 rounded-lg transition-colors disabled:opacity-50"
              >
                {busyBranch === confirmArchiveName ? "Archiving..." : "Yes, Archive Branch"}
              </button>
            </div>
          </div>
        )}

        {confirmDeleteName && (
          <div
            role="alert"
            className="rounded-lg border border-status-danger-border bg-status-danger-bg p-4 space-y-2 animate-fade-in"
          >
            <div className="flex items-center gap-2 text-sm font-semibold text-status-danger">
              <Icon name="trash" size={18} />
              <span>Delete Branch &lsquo;{confirmDeleteName}&rsquo;?</span>
            </div>
            <p className="text-xs text-text-primary">
              Permanently removes this branch&apos;s worktree, Git ref, and any stopped sandbox container.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmDeleteName(null)}
                className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-card border border-border-default rounded-lg hover:bg-surface-hover transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleDelete(confirmDeleteName)}
                disabled={busyBranch === confirmDeleteName}
                className="px-3 py-1.5 text-xs font-semibold text-accent-contrast-text bg-status-danger hover:opacity-90 rounded-lg transition-colors disabled:opacity-50"
              >
                {busyBranch === confirmDeleteName ? "Deleting..." : "Yes, Delete Branch"}
              </button>
            </div>
          </div>
        )}

        <div
          tabIndex={0}
          className="overflow-y-auto max-h-[55vh] divide-y divide-border-subtle border border-border-default rounded-lg bg-surface-card focus:outline-none focus:ring-1 focus:ring-border-focus"
        >
          {branches.length === 0 ? (
            <div className="p-8 text-center text-xs text-text-muted italic">
              No branches found for this server.
            </div>
          ) : (
            branches.map((b) => {
              const isCurrent = b.name === currentBranchName;
              const isArchived = b.status === "archived";
              const isMain = b.name === "main";
              const isRuntimeActive =
                b.runtime_status === "running" || b.runtime_status === "starting";

              return (
                <div
                  key={b.name}
                  className={`flex flex-wrap items-center justify-between gap-2 p-3.5 text-xs transition-colors ${
                    isCurrent
                      ? "bg-accent-primary/10 border-accent-primary/20"
                      : "hover:bg-surface-hover"
                  }`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono font-semibold text-text-primary">
                          {b.name}
                        </span>
                        {isCurrent && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-accent-primary text-accent-contrast-text">
                            CURRENT
                          </span>
                        )}
                        {b.is_protected && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-status-success-bg text-status-success border border-status-success-border">
                            PROTECTED
                          </span>
                        )}
                        {getStatusBadge(b.status || "created")}
                      </div>
                      <p className="text-[11px] text-text-muted font-mono mt-0.5">
                        Head: {b.head_commit_id ? b.head_commit_id.slice(0, 7) : "None"} • Created:{" "}
                        {parseServerDate(b.created_at)?.toLocaleDateString() ?? "—"}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        onClose();
                        onOpenProtectionModal(b);
                      }}
                      className="px-2.5 py-1 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-card border border-border-default rounded-lg hover:bg-surface-hover transition-colors cursor-pointer"
                    >
                      Protection Rules
                    </button>

                    {canEdit && !isArchived && (
                      <button
                        type="button"
                        onClick={() => {
                          setConfirmDeleteName(null);
                          setConfirmArchiveName(b.name);
                        }}
                        disabled={isMain || Boolean(b.is_protected) || isRuntimeActive || !!busyBranch}
                        title={
                          isMain || b.is_protected
                            ? "Protected branches cannot be archived"
                            : isRuntimeActive
                              ? "Stop active sandbox before archiving"
                              : "Archive branch"
                        }
                        className="px-2.5 py-1 text-xs font-medium text-status-warning bg-status-warning-bg border border-status-warning-border rounded-lg hover:opacity-90 disabled:opacity-40 transition-colors cursor-pointer"
                      >
                        Archive
                      </button>
                    )}

                    {canEdit && !isMain && (
                      <button
                        type="button"
                        onClick={() => {
                          setConfirmArchiveName(null);
                          setConfirmDeleteName(b.name);
                        }}
                        disabled={Boolean(b.is_protected) || isRuntimeActive || !!busyBranch}
                        title={
                          b.is_protected
                            ? "Protected branches cannot be deleted"
                            : isRuntimeActive
                              ? "Stop active sandbox before deleting"
                              : "Delete branch"
                        }
                        className="px-2.5 py-1 text-xs font-medium text-status-danger bg-status-danger-bg border border-status-danger-border rounded-lg hover:opacity-90 disabled:opacity-40 transition-colors cursor-pointer"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </Modal>
  );
}
