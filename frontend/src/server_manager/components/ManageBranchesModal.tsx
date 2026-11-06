import React, { useState, useMemo } from "react";
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
  onBranchesChanged: () => void;
  onOpenProtectionModal: (branch: ServerBranch) => void;
}

export function ManageBranchesModal({
  isOpen,
  onClose,
  serverId,
  branches,
  currentBranchName,
  onBranchesChanged,
  onOpenProtectionModal,
}: ManageBranchesModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [archivingBranch, setArchivingBranch] = useState<string | null>(null);
  const [confirmArchiveName, setConfirmArchiveName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // React 19 pattern
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setError(null);
      setConfirmArchiveName(null);
    }
  }

  const handleClose = () => {
    if (!archivingBranch) {
      onClose();
    }
  };

  const handleArchive = async (branchName: string) => {
    setArchivingBranch(branchName);
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
      setArchivingBranch(null);
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
      description="Manage branch status, protection rules, and archive inactive branches"
      size="xl"
      closeOnBackdrop={!archivingBranch}
      closeOnEscape={!archivingBranch}
      closeButtonAriaLabel="Close modal"
    >
      <div className="space-y-4 flex flex-col text-text-primary">
        {/* Error alert */}
        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger">
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

        {/* Confirm Archive Prompt */}
        {confirmArchiveName && (
          <div role="alert" className="rounded-lg border border-status-warning-border bg-status-warning-bg p-4 space-y-2 animate-fade-in">
            <div className="flex items-center gap-2 text-sm font-semibold text-status-warning">
              <Icon name="alert" size={18} />
              <span>Archive Branch '{confirmArchiveName}'?</span>
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
                disabled={archivingBranch === confirmArchiveName}
                className="px-3 py-1.5 text-xs font-medium text-accent-contrast-text bg-status-warning hover:opacity-90 rounded-lg transition-colors disabled:opacity-50"
              >
                {archivingBranch === confirmArchiveName ? "Archiving..." : "Yes, Archive Branch"}
              </button>
            </div>
          </div>
        )}

        {/* Branch List */}
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

              return (
                <div
                  key={b.name}
                  className={`flex items-center justify-between p-3.5 text-xs transition-colors ${
                    isCurrent ? "bg-accent-primary/10 border-accent-primary/20" : "hover:bg-surface-hover"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div>
                      <div className="flex items-center gap-2">
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
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                            </svg>
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

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        onClose();
                        onOpenProtectionModal(b);
                      }}
                      className="px-2.5 py-1 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-card border border-border-default rounded-lg hover:bg-surface-hover transition-colors"
                    >
                      Protection Rules
                    </button>

                    {!isArchived && (
                      <button
                        type="button"
                        onClick={() => setConfirmArchiveName(b.name)}
                        disabled={b.is_protected || !!archivingBranch}
                        title={b.is_protected ? "Protected branches cannot be archived" : "Archive branch"}
                        className="px-2.5 py-1 text-xs font-medium text-status-warning bg-status-warning-bg border border-status-warning-border rounded-lg hover:opacity-90 disabled:opacity-40 transition-colors"
                      >
                        Archive
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end border-t border-border-default pt-3">
          <button
            type="button"
            onClick={handleClose}
            disabled={!!archivingBranch}
            className="px-4 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors disabled:opacity-50"
          >
            Close
          </button>
        </div>
      </div>
    </Modal>
  );
}
