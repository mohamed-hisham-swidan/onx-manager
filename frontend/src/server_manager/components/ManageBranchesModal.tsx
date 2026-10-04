import React, { useState, useEffect, useMemo } from "react";
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !archivingBranch) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, archivingBranch, onClose]);

  if (!isOpen) return null;

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
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
            Active
          </span>
        );
      case "archived":
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-gray-200 text-gray-700 dark:bg-gray-800 dark:text-gray-400">
            Archived
          </span>
        );
      case "created":
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">
            Created
          </span>
        );
      default:
        return (
          <span className="px-2 py-0.5 rounded text-[11px] font-semibold uppercase bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            {status}
          </span>
        );
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="manage-branches-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget && !archivingBranch) onClose();
      }}
    >
      <div className="relative w-full max-w-xl max-h-[85vh] flex flex-col rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4 text-gray-900 dark:text-gray-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400">
              <Icon name="backup" size={20} />
            </div>
            <div>
              <h2
                id="manage-branches-modal-title"
                className="text-lg font-semibold text-gray-900 dark:text-white"
              >
                Branch Lifecycle Management
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Manage branch status, protection rules, and archive inactive branches
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={!!archivingBranch}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300 transition-colors"
            aria-label="Close modal"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        {/* Error alert */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-red-500 hover:text-red-700"
            >
              <Icon name="x" size={14} />
            </button>
          </div>
        )}

        {/* Confirm Archive Prompt */}
        {confirmArchiveName && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/50 p-4 space-y-2 animate-fade-in">
            <div className="flex items-center gap-2 text-sm font-semibold text-amber-800 dark:text-amber-200">
              <Icon name="alert" size={18} />
              <span>Archive Branch '{confirmArchiveName}'?</span>
            </div>
            <p className="text-xs text-amber-700 dark:text-amber-300">
              Archived branches become read-only. No new commits can be created on an archived branch.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setConfirmArchiveName(null)}
                className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleArchive(confirmArchiveName)}
                disabled={archivingBranch === confirmArchiveName}
                className="px-3 py-1.5 text-xs font-medium text-white bg-amber-600 hover:bg-amber-700 rounded-lg transition-colors"
              >
                {archivingBranch === confirmArchiveName ? "Archiving..." : "Yes, Archive Branch"}
              </button>
            </div>
          </div>
        )}

        {/* Branch List */}
        <div className="flex-1 overflow-y-auto divide-y divide-gray-100 dark:divide-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg">
          {branches.length === 0 ? (
            <div className="p-8 text-center text-xs text-gray-400 italic">
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
                    isCurrent ? "bg-indigo-50/50 dark:bg-indigo-950/20" : "hover:bg-gray-50 dark:hover:bg-gray-800/50"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-semibold text-gray-900 dark:text-white">
                          {b.name}
                        </span>
                        {isCurrent && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">
                            CURRENT
                          </span>
                        )}
                        {b.is_protected && (
                          <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
                            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                            </svg>
                            PROTECTED
                          </span>
                        )}
                        {getStatusBadge(b.status || "created")}
                      </div>
                      <p className="text-[11px] text-gray-400 font-mono mt-0.5">
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
                      className="px-2.5 py-1 text-xs font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
                    >
                      Protection Rules
                    </button>

                    {!isArchived && (
                      <button
                        type="button"
                        onClick={() => setConfirmArchiveName(b.name)}
                        disabled={b.is_protected || !!archivingBranch}
                        title={b.is_protected ? "Protected branches cannot be archived" : "Archive branch"}
                        className="px-2.5 py-1 text-xs font-medium text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 rounded-lg hover:bg-amber-100 disabled:opacity-40 transition-colors"
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
        <div className="flex items-center justify-end border-t border-gray-100 dark:border-gray-800 pt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
