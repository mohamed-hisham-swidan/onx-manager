import React, { useState, useEffect, useMemo } from "react";
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

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isOpen && !isSubmitting) {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, isSubmitting, onClose]);

  if (!isOpen) return null;

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
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="create-tag-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSubmitting) onClose();
      }}
    >
      <div className="relative w-full max-w-md rounded-xl border border-gray-200 bg-white shadow-2xl dark:border-gray-700 dark:bg-gray-800 p-6 space-y-4 text-gray-900 dark:text-gray-100 overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 dark:border-gray-800 pb-3">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400">
              <Icon name="backup" size={20} />
            </div>
            <div>
              <h2
                id="create-tag-modal-title"
                className="text-lg font-semibold text-gray-900 dark:text-white"
              >
                Create Immutable Tag
              </h2>
              <p className="text-xs text-gray-500 dark:text-gray-400">
                Commit: <span className="font-mono font-semibold">{commitId.slice(0, 7)}</span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="rounded-lg p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-700 dark:hover:text-gray-300 transition-colors"
            aria-label="Close modal"
          >
            <Icon name="x" size={18} />
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            <Icon name="alert" size={16} className="shrink-0" />
            <span className="flex-1">{error}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 dark:text-gray-300 mb-1">
              Tag Name
            </label>
            <input
              type="text"
              value={tagName}
              onChange={(e) => setTagName(e.target.value)}
              placeholder="e.g. v1.0.0 or release-purpur"
              className="w-full text-xs font-mono bg-white dark:bg-gray-900 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-gray-900 dark:text-gray-100 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
              autoFocus
              required
            />
            <p className="text-[11px] text-gray-400 mt-1">
              Tags are permanent immutable checkpoints in the repository DAG.
            </p>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !tagName.trim()}
              className="px-4 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
            >
              {isSubmitting ? "Creating..." : "Create Tag"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
