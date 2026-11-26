import React, { useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { validateNewEntryName } from "./filesUtils";

export interface NewFileModalProps {
  open: boolean;
  currentPath: string;
  isPending: boolean;
  onClose: () => void;
  onCreate: (fileName: string, initialContent: string) => void;
}

const FILE_TEMPLATES: Array<{ label: string; name: string; content: string }> = [
  { label: "config.yml", name: "config.yml", content: "# Configuration\n" },
  { label: "whitelist.json", name: "whitelist.json", content: "[]\n" },
  { label: "ops.json", name: "ops.json", content: "[]\n" },
  { label: "custom.properties", name: "custom.properties", content: "# Server properties\n" },
  { label: "notes.txt", name: "notes.txt", content: "" },
];

export const NewFileModal: React.FC<NewFileModalProps> = ({
  open,
  currentPath,
  isPending,
  onClose,
  onCreate,
}) => {
  const [fileName, setFileName] = useState("");
  const [starterContent, setStarterContent] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);

  const handleResetAndClose = () => {
    if (isPending) return;
    setFileName("");
    setStarterContent("");
    setValidationError(null);
    onClose();
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateNewEntryName(fileName);
    if (err) {
      setValidationError(err);
      return;
    }
    onCreate(fileName.trim(), starterContent);
  };

  return (
    <Modal
      open={open}
      onClose={handleResetAndClose}
      title="New File"
      description={
        currentPath
          ? `Create a new text or config file inside "${currentPath}".`
          : "Create a new text or config file in the server root."
      }
      size="sm"
      closeOnBackdrop={!isPending}
      closeOnEscape={!isPending}
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label
            htmlFor="new-file-name"
            className="mb-1.5 block text-xs font-semibold uppercase tracking-wider text-text-muted"
          >
            File name
          </label>
          <input
            id="new-file-name"
            type="text"
            aria-label="File name"
            placeholder="e.g. config/custom.yml"
            value={fileName}
            onChange={(e) => {
              setFileName(e.target.value);
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

        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Quick templates
          </div>
          <div className="flex flex-wrap gap-1.5">
            {FILE_TEMPLATES.map((tpl) => (
              <button
                key={tpl.name}
                type="button"
                disabled={isPending}
                onClick={() => {
                  setFileName(tpl.name);
                  setStarterContent(tpl.content);
                  setValidationError(null);
                }}
                className="rounded-md border border-border-subtle bg-surface-muted px-2 py-1 text-xs font-mono text-text-secondary hover:border-border-hover hover:bg-surface-hover hover:text-text-primary transition-colors cursor-pointer"
              >
                {tpl.label}
              </button>
            ))}
          </div>
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
            icon="plus"
            loading={isPending}
            disabled={!fileName.trim()}
          >
            Create &amp; Edit
          </Button>
        </div>
      </form>
    </Modal>
  );
};
