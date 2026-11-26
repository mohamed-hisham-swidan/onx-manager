import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { validateNewEntryName } from "./filesUtils";

export interface NewFolderModalProps {
  open: boolean;
  currentPath: string;
  isPending: boolean;
  onClose: () => void;
  onCreate: (folderName: string) => void;
}

export const NewFolderModal: React.FC<NewFolderModalProps> = ({
  open,
  currentPath,
  isPending,
  onClose,
  onCreate,
}) => {
  const [folderName, setFolderName] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleResetAndClose = () => {
    if (isPending) return;
    setFolderName("");
    setValidationError(null);
    onClose();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateNewEntryName(folderName);
    if (err) {
      setValidationError(err);
      return;
    }
    onCreate(folderName.trim());
  };

  return (
    <Modal
      open={open}
      onClose={handleResetAndClose}
      title="New Folder"
      description={
        currentPath
          ? `Create a directory inside "${currentPath}".`
          : "Create a directory in the server root."
      }
      size="sm"
      closeOnBackdrop={!isPending}
      closeOnEscape={!isPending}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="new-folder-name"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-text-muted"
          >
            Folder name
          </label>
          <input
            id="new-folder-name"
            type="text"
            aria-label="Folder name"
            placeholder="Folder name"
            value={folderName}
            onChange={(e) => {
              setFolderName(e.target.value);
              setValidationError(null);
            }}
            disabled={isPending}
            autoFocus
            className="w-full rounded-lg border border-border-subtle hover:border-border-hover bg-surface-page px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-border-focus focus:outline-hidden focus:ring-1 focus:ring-border-focus transition-colors"
          />
          {validationError && (
            <p className="mt-1.5 text-xs text-status-danger">{validationError}</p>
          )}
        </div>

        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={handleResetAndClose}
            disabled={isPending}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            icon="folder"
            loading={isPending}
            disabled={!folderName.trim()}
          >
            Create
          </Button>
        </div>
      </form>
    </Modal>
  );
};
