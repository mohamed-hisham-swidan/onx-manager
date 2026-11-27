import React, { useState, useMemo } from "react";
import { Modal } from "@/components/ui/Modal";
import { createAuthenticatedApi } from "@/services/api";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toastStore";

interface CreateTagModalProps {
  isOpen: boolean;
  onClose: () => void;
  serverId: string;
  commitId: string;
  onTagCreated: () => void;
}

export function CreateTagModal({
  isOpen,
  onClose,
  serverId,
  commitId,
  onTagCreated,
}: CreateTagModalProps) {
  const api = useMemo(() => createAuthenticatedApi(), []);
  const [tagName, setTagName] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // React 19 pattern
  const [prevIsOpen, setPrevIsOpen] = useState(isOpen);
  if (isOpen !== prevIsOpen) {
    setPrevIsOpen(isOpen);
    if (isOpen) {
      setTagName("");
      setError(null);
    }
  }

  const handleClose = () => {
    if (!isSubmitting) {
      onClose();
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = tagName.trim();
    if (!cleanName) {
      setError("Tag name is required.");
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      await api.createTag(serverId, {
        name: cleanName,
        commit_id: commitId,
      });
      toast("success", "Tag Created", `Tag '${cleanName}' created on commit ${commitId.slice(0, 7)}`);
      onTagCreated();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to create tag.";
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal
      open={isOpen}
      onClose={handleClose}
      title="Create Immutable Tag"
      description={
        <span>
          Commit: <span className="font-mono font-semibold">{commitId.slice(0, 7)}</span>
        </span>
      }
      size="md"
      closeOnBackdrop={!isSubmitting}
      closeOnEscape={!isSubmitting}
      closeButtonAriaLabel="Close modal"
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={isSubmitting}
            className="px-3 py-1.5 text-xs font-medium text-text-secondary hover:text-text-primary bg-surface-muted hover:bg-surface-hover border border-border-default rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={(e) => void handleSubmit(e)}
            disabled={isSubmitting || !tagName.trim()}
            className="px-4 py-1.5 text-xs font-medium text-accent-contrast-text bg-accent-primary hover:bg-accent-hover disabled:opacity-50 rounded-lg transition-colors shadow-sm cursor-pointer"
          >
            {isSubmitting ? "Creating..." : "Create Tag"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Error Alert */}
        {error && (
          <div role="alert" className="flex items-center gap-2 rounded-lg border border-status-danger-border bg-status-danger-bg p-3 text-xs text-status-danger">
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="create-tag-input" className="block text-xs font-medium text-text-secondary mb-1">
              Tag Name
            </label>
            <input
              id="create-tag-input"
              type="text"
              value={tagName}
              onChange={(e) => setTagName(e.target.value)}
              disabled={isSubmitting}
              placeholder="e.g. v1.0.0 or release-purpur"
              className="w-full text-xs font-mono bg-surface-card border border-border-default rounded-lg px-3 py-2 text-text-primary focus:ring-2 focus:ring-accent-primary focus:outline-none disabled:opacity-50"
              autoFocus
              required
            />
            <p className="text-[11px] text-text-muted mt-1">
              Tags are permanent immutable checkpoints in the repository DAG.
            </p>
          </div>
        </form>
      </div>
    </Modal>
  );
}
