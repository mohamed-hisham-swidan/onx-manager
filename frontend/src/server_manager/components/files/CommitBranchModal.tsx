import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";

export interface CommitBranchModalProps {
  open: boolean;
  activeBranch?: string;
  isPending: boolean;
  onClose: () => void;
  onCommit: (message: string) => void;
}

export const CommitBranchModal: React.FC<CommitBranchModalProps> = ({
  open,
  activeBranch,
  isPending,
  onClose,
  onCommit,
}) => {
  const [commitMessage, setCommitMessage] = useState("");

  const handleClose = () => {
    if (isPending) return;
    setCommitMessage("");
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Save & Commit"
      description={
        activeBranch
          ? `Commit validated config changes on branch "${activeBranch}".`
          : "Commit validated config changes."
      }
      size="sm"
      closeOnBackdrop={!isPending}
      closeOnEscape={!isPending}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (commitMessage.trim() && !isPending) {
            onCommit(commitMessage.trim());
          }
        }}
      >
        <label
          htmlFor="commit-message"
          className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-text-muted"
        >
          Commit message
        </label>
        <input
          id="commit-message"
          type="text"
          aria-label="Commit message"
          placeholder="Describe this change"
          value={commitMessage}
          onChange={(e) => setCommitMessage(e.target.value)}
          autoFocus
          maxLength={500}
          disabled={isPending}
          className="w-full rounded-lg border border-border-subtle hover:border-border-hover bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus transition-colors"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={handleClose}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            icon="save"
            loading={isPending}
            disabled={!commitMessage.trim()}
          >
            Commit
          </Button>
        </div>
      </form>
    </Modal>
  );
};
