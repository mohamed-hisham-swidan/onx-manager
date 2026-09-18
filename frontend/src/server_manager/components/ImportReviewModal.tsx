import React, { useState, useEffect, useMemo } from "react";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toastStore";
import type { ScanLiveChangesResponse, LiveChangeEntry } from "@/server_manager/types";

interface ImportReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  liveData: ScanLiveChangesResponse | null;
  onReviewResolved: () => void;
}

export function ImportReviewModal({
  isOpen,
  onClose,
  serverId,
  liveData,
  onReviewResolved,
}: ImportReviewModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"all" | "added" | "modified" | "deleted">("all");
  const [showRevertConfirm, setShowRevertConfirm] = useState(false);

  // React 19 state reset pattern
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setError(null);
      setActiveTab("all");
      setShowRevertConfirm(false);
    }
  }

  // Escape key handler
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isProcessing) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isProcessing, onClose]);

  if (!isOpen || !liveData) return null;

  const getChangeType = (c: LiveChangeEntry): "added" | "modified" | "deleted" => {
    const raw = (c.change_type || c.change || "modified").toLowerCase();
    if (raw.includes("add")) return "added";
    if (raw.includes("del") || raw.includes("rem")) return "deleted";
    return "modified";
  };

  const changes = liveData.changes || [];
  const added = changes.filter((c) => getChangeType(c) === "added");
  const modified = changes.filter((c) => getChangeType(c) === "modified");
  const deleted = changes.filter((c) => getChangeType(c) === "deleted");

  const filteredChanges = activeTab === "all"
    ? changes
    : activeTab === "added"
    ? added
    : activeTab === "modified"
    ? modified
    : deleted;

  const handleConfirm = async () => {
    setIsProcessing(true);
    setError(null);
    try {
      if (liveData.review_id) {
        const resp = await api.confirmImportReview(serverId, liveData.review_id);
        toast(
          "success",
          "Review Confirmed",
          resp.commit_id ? `Created commit ${resp.commit_id.slice(0, 7)}` : "Live changes confirmed and staged."
        );
      } else {
        const resp = await api.autoCommitLiveChanges(serverId, { branch: "main" });
        toast(
          "success",
          "Live Changes Committed",
          resp.commit_id ? `Created commit ${resp.commit_id.slice(0, 7)}` : "Live changes committed."
        );
      }
      onReviewResolved();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to process live changes.";
      setError(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDismiss = async () => {
    if (!liveData.review_id) {
      onClose();
      return;
    }
    setIsProcessing(true);
    setError(null);
    try {
      await api.dismissImportReview(serverId, liveData.review_id);
      toast("info", "Review Dismissed", "Uncommitted live changes review dismissed.");
      onReviewResolved();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to dismiss import review.";
      setError(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleRevert = async () => {
    if (!liveData.review_id) {
      setError("No active review ID to revert.");
      return;
    }
    setIsProcessing(true);
    setError(null);
    try {
      await api.revertImportReview(serverId, liveData.review_id);
      toast("success", "Live Changes Reverted", "Filesystem reset back to branch head.");
      setShowRevertConfirm(false);
      onReviewResolved();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to revert live changes.";
      setError(msg);
    } finally {
      setIsProcessing(false);
    }
  };

  const getChangeBadge = (type: LiveChangeEntry["change_type"]) => {
    switch (type) {
      case "added":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
            ADDED
          </span>
        );
      case "modified":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
            MODIFIED
          </span>
        );
      case "deleted":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300">
            DELETED
          </span>
        );
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="import-review-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isProcessing) onClose();
      }}
    >
      <div className="relative w-full max-w-2xl max-h-[85vh] flex flex-col rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4 text-gray-900 dark:text-gray-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-400">
              <Icon name="alert" size={20} />
            </div>
            <div>
              <h2
                id="import-review-modal-title"
                className="text-lg font-semibold text-gray-900 dark:text-white"
              >
                Uncommitted Live Changes Detected
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Live filesystem has diverged from base commit{" "}
                <span className="font-mono font-semibold text-gray-700 dark:text-gray-300">
                  {liveData.base_commit_id?.slice(0, 7) || "HEAD"}
                </span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isProcessing}
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

        {/* Revert Confirmation Banner */}
        {showRevertConfirm && (
          <div className="rounded-lg border border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/60 p-4 space-y-2 animate-fade-in">
            <div className="flex items-center gap-2 text-sm font-semibold text-red-800 dark:text-red-200">
              <Icon name="alert" size={18} />
              <span>Confirm Destructive Filesystem Revert</span>
            </div>
            <p className="text-xs text-red-700 dark:text-red-300">
              This will permanently discard all uncommitted changes on the server filesystem and restore files to branch HEAD. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowRevertConfirm(false)}
                disabled={isProcessing}
                className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRevert}
                disabled={isProcessing}
                className="px-3 py-1.5 text-xs font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors"
              >
                {isProcessing ? "Reverting..." : "Yes, Revert Filesystem"}
              </button>
            </div>
          </div>
        )}

        {/* Change Stats and Filter Tabs */}
        <div className="flex items-center justify-between border-b border-gray-200 dark:border-gray-700 pb-2 text-xs">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("all")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "all"
                  ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
                  : "text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"
              }`}
            >
              All ({changes.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("added")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "added"
                  ? "bg-emerald-600 text-white"
                  : "text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40"
              }`}
            >
              Added ({added.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("modified")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "modified"
                  ? "bg-amber-600 text-white"
                  : "text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40"
              }`}
            >
              Modified ({modified.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("deleted")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "deleted"
                  ? "bg-red-600 text-white"
                  : "text-red-700 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40"
              }`}
            >
              Deleted ({deleted.length})
            </button>
          </div>

          {liveData.detected_at && (
            <span className="text-[11px] text-gray-400">
              Scanned: {new Date(liveData.detected_at).toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* Changes List */}
        <div className="flex-1 overflow-y-auto max-h-[360px] border border-gray-200 dark:border-gray-700 rounded-lg divide-y divide-gray-100 dark:divide-gray-800 bg-gray-50/50 dark:bg-gray-900/40">
          {filteredChanges.length === 0 ? (
            <div className="p-8 text-center text-xs text-gray-400 italic">
              No changes in this category.
            </div>
          ) : (
            filteredChanges.map((change, idx) => (
              <div
                key={`${change.path}-${idx}`}
                className="flex items-center justify-between px-3 py-2 text-xs hover:bg-gray-100/60 dark:hover:bg-gray-800/60 transition-colors"
              >
                <div className="flex items-center gap-2.5 truncate">
                  {getChangeBadge(getChangeType(change))}
                  <span className="font-mono text-gray-800 dark:text-gray-200 truncate">
                    {change.path}
                  </span>
                </div>
                {change.size_bytes !== undefined && (
                  <span className="text-[11px] font-mono text-gray-400 shrink-0">
                    {change.size_bytes} bytes
                  </span>
                )}
              </div>
            ))
          )}
        </div>

        {/* Modal Actions Footer */}
        <div className="flex items-center justify-between border-t border-gray-100 dark:border-gray-800 pt-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowRevertConfirm(true)}
              disabled={isProcessing || showRevertConfirm}
              className="px-3 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 border border-red-200 dark:border-red-900 rounded-lg transition-colors"
            >
              Revert Live Changes
            </button>
            <button
              type="button"
              onClick={handleDismiss}
              disabled={isProcessing}
              className="px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              Dismiss
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={isProcessing}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              Close
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={isProcessing || changes.length === 0}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
            >
              <Icon name="check" size={14} />
              {isProcessing ? "Processing..." : "Confirm & Commit"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
