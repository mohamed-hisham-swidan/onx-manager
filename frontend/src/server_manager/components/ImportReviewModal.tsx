import { useState, useMemo } from "react";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { toast } from "@/stores/toastStore";
import { parseServerDate } from "@/server_manager/utils/format";
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

  const handleClose = () => {
    if (isProcessing) return;
    onClose();
  };

  const getChangeType = (c: LiveChangeEntry): "added" | "modified" | "deleted" => {
    const raw = (c.change_type || c.change || "modified").toLowerCase();
    if (raw.includes("add")) return "added";
    if (raw.includes("del") || raw.includes("rem")) return "deleted";
    return "modified";
  };

  if (!liveData) return null;

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
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-status-success-bg text-status-success border border-status-success-border">
            ADDED
          </span>
        );
      case "modified":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-status-warning-bg text-status-warning border border-status-warning-border">
            MODIFIED
          </span>
        );
      case "deleted":
        return (
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-status-danger-bg text-status-danger border border-status-danger-border">
            DELETED
          </span>
        );
    }
  };

  return (
    <Modal
      open={isOpen && Boolean(liveData)}
      onClose={handleClose}
      title="Uncommitted Live Changes Detected"
      ariaLabel="Uncommitted Live Changes Detected"
      description={
        <span>
          Live filesystem has diverged from base commit{" "}
          <span className="font-mono font-semibold text-text-secondary">
            {liveData?.base_commit_id?.slice(0, 7) || "HEAD"}
          </span>
        </span>
      }
      size="xl"
      closeOnBackdrop={!isProcessing}
      closeOnEscape={!isProcessing}
      closeButtonAriaLabel="Close modal"
    >
      <div className="space-y-4 text-text-primary">
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

        {/* Revert Confirmation Banner */}
        {showRevertConfirm && (
          <div role="alert" className="rounded-lg border border-status-danger-border bg-status-danger-bg p-4 space-y-2 animate-fade-in">
            <div className="flex items-center gap-2 text-sm font-semibold text-status-danger">
              <Icon name="alert" size={18} />
              <span>Confirm Destructive Filesystem Revert</span>
            </div>
            <p className="text-xs text-text-primary">
              This will permanently discard all uncommitted changes on the server filesystem and restore files to branch HEAD. This action cannot be undone.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowRevertConfirm(false)}
                disabled={isProcessing}
                className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRevert}
                disabled={isProcessing}
                className="px-3 py-1.5 text-xs font-medium text-accent-contrast-text bg-status-danger hover:opacity-90 rounded-lg transition-colors"
              >
                {isProcessing ? "Reverting..." : "Yes, Revert Filesystem"}
              </button>
            </div>
          </div>
        )}

        {/* Change Stats and Filter Tabs */}
        <div className="flex items-center justify-between border-b border-border-default pb-2 text-xs">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setActiveTab("all")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "all"
                  ? "bg-accent-primary text-accent-contrast-text"
                  : "text-text-secondary hover:bg-surface-hover hover:text-text-primary"
              }`}
            >
              All ({changes.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("added")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "added"
                  ? "bg-status-success text-accent-contrast-text"
                  : "text-status-success hover:bg-status-success-bg"
              }`}
            >
              Added ({added.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("modified")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "modified"
                  ? "bg-status-warning text-accent-contrast-text"
                  : "text-status-warning hover:bg-status-warning-bg"
              }`}
            >
              Modified ({modified.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("deleted")}
              className={`px-2.5 py-1 rounded font-medium transition-colors ${
                activeTab === "deleted"
                  ? "bg-status-danger text-accent-contrast-text"
                  : "text-status-danger hover:bg-status-danger-bg"
              }`}
            >
              Deleted ({deleted.length})
            </button>
          </div>

          {liveData.detected_at && (
            <span className="text-[11px] text-text-muted">
              Scanned: {parseServerDate(liveData.detected_at)?.toLocaleTimeString() ?? "—"}
            </span>
          )}
        </div>

        {/* Changes List */}
        <div
          tabIndex={0}
          className="flex-1 overflow-y-auto max-h-[360px] border border-border-default rounded-lg divide-y divide-border-subtle bg-surface-card focus:outline-none focus:ring-1 focus:ring-border-focus"
        >
          {filteredChanges.length === 0 ? (
            <div className="p-8 text-center text-xs text-text-muted italic">
              No changes in this category.
            </div>
          ) : (
            filteredChanges.map((change, idx) => (
              <div
                key={`${change.path}-${idx}`}
                className="flex items-center justify-between px-3 py-2 text-xs hover:bg-surface-hover transition-colors"
              >
                <div className="flex items-center gap-2.5 truncate">
                  {getChangeBadge(getChangeType(change))}
                  <span className="font-mono text-text-primary truncate">
                    {change.path}
                  </span>
                </div>
                {change.size_bytes !== undefined && (
                  <span className="text-[11px] font-mono text-text-muted shrink-0">
                    {change.size_bytes} bytes
                  </span>
                )}
              </div>
            ))
          )}
        </div>

        {/* Modal Actions Footer */}
        <div className="flex items-center justify-between border-t border-border-default pt-3">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setShowRevertConfirm(true)}
              disabled={isProcessing || showRevertConfirm}
              className="px-3 py-1.5 text-xs font-medium text-status-danger hover:bg-status-danger-bg border border-status-danger-border rounded-lg transition-colors"
            >
              Revert Live Changes
            </button>
            <button
              type="button"
              onClick={handleDismiss}
              disabled={isProcessing}
              className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover border border-border-default rounded-lg transition-colors"
            >
              Dismiss
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleClose}
              disabled={isProcessing}
              className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors disabled:opacity-50"
            >
              Close
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              disabled={isProcessing || changes.length === 0}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-medium text-accent-contrast-text bg-accent-primary hover:bg-accent-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm"
            >
              <Icon name="check" size={14} />
              {isProcessing ? "Processing..." : "Confirm & Commit"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
