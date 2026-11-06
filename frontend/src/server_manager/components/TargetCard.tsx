import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { Modal } from "@/components/ui/Modal";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useClipboard } from "@/hooks/useClipboard";
import { SERVICE_METADATA, type TargetResponse } from "@/types";

export interface TargetCardProps {
  target: TargetResponse;
  onEditAddress: (target: TargetResponse) => void;
  onRemoveTarget: (targetId: string) => void;
  isReadOnly?: boolean;
}

export function TargetCard({
  target,
  onEditAddress,
  onRemoveTarget,
  isReadOnly = false,
}: TargetCardProps) {
  const { copy } = useClipboard();
  const [isConfirmDeleteOpen, setIsConfirmDeleteOpen] = useState(false);

  const meta = SERVICE_METADATA[target.service_type] || {
    label: target.service_type,
    defaultProtocol: target.protocol,
    defaultPort: target.local_port,
    description: "",
    isPrimary: target.service_type === "java",
  };

  const isPrimary = target.service_type === "java";
  const hasAssistedSetup = Boolean(target.dashboard_url || target.setup_instructions);

  const publicAddress = target.public_address;

  return (
    <div className="rounded-xl border border-border-default bg-surface-card p-5 shadow-xs space-y-4">
      {/* Target Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border-subtle pb-3">
        <div className="flex items-center gap-2.5">
          <span className="font-semibold text-sm text-text-primary">
            {meta.label}
          </span>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-surface-muted text-text-secondary uppercase">
            {target.protocol.toUpperCase()} {target.local_port}
          </span>
          {isPrimary && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-accent-primary/10 text-accent-primary border border-accent-primary/20">
              Primary Game Target
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <StatusBadge status={target.status} />

          {/* Secondary Target Delete Button (Never shown for primary Java target - F-75-13) */}
          {!isPrimary && !isReadOnly && (
            <button
              type="button"
              onClick={() => setIsConfirmDeleteOpen(true)}
              aria-label={`Remove ${meta.label} target`}
              className="p-1 text-text-muted hover:text-status-danger rounded hover:bg-surface-hover transition-colors"
              title="Remove Target"
            >
              <Icon name="trash" size={15} />
            </button>
          )}
        </div>
      </div>

      {/* Target Address & Connection Display */}
      <div className="space-y-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
          Public Connection Address
        </span>

        {publicAddress ? (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg bg-surface-muted border border-border-default">
            <span className="font-mono text-sm font-semibold text-accent-primary break-all select-all">
              {publicAddress}
            </span>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => copy(publicAddress, "Public address copied to clipboard")}
                aria-label={`Copy ${meta.label} public address to clipboard`}
                className="px-2.5 py-1 rounded-md border border-border-default bg-surface-card text-xs font-medium text-text-secondary hover:bg-surface-hover flex items-center gap-1.5 transition-colors shadow-xs"
              >
                <Icon name="copy" size={13} />
                <span>Copy</span>
              </button>

              {!isReadOnly && (
                <button
                  type="button"
                  onClick={() => onEditAddress(target)}
                  aria-label="Edit public address"
                  className="px-2.5 py-1 rounded-md border border-border-default bg-surface-card text-xs font-medium text-text-secondary hover:bg-surface-hover flex items-center gap-1.5 transition-colors shadow-xs"
                >
                  <Icon name="edit" size={13} />
                  <span>Edit</span>
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="p-3 rounded-lg bg-surface-muted border border-dashed border-border-default text-xs text-text-muted flex items-center justify-between">
            <span>No public address assigned yet.</span>
            {!isReadOnly && (
              <button
                type="button"
                onClick={() => onEditAddress(target)}
                className="text-xs text-accent-primary hover:underline font-medium"
              >
                Set Address
              </button>
            )}
          </div>
        )}
      </div>

      {/* playit Assisted Setup 3-Step Numbered Scaffold (F-75-19) */}
      {hasAssistedSetup && (
        <div
          role="region"
          aria-label="Assisted Setup Guide"
          className="rounded-lg border border-border-default bg-surface-muted p-4 space-y-3"
        >
          <div className="flex items-center gap-2 text-text-primary font-semibold text-xs uppercase tracking-wider">
            <Icon name="info" size={16} />
            <span>playit.gg Assisted Setup Required</span>
          </div>

          <div className="space-y-2.5 text-xs text-text-secondary">
            {/* Step 1 */}
            <div className="flex items-start gap-2.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[10px] font-bold text-accent-contrast-text">
                1
              </span>
              <div className="pt-0.5 flex flex-wrap items-center gap-2">
                <span>Open the playit.gg management dashboard:</span>
                {target.dashboard_url && (
                  <a
                    href={target.dashboard_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-semibold text-accent-primary hover:underline"
                  >
                    <span>Open Dashboard</span>
                    <Icon name="external" size={12} />
                  </a>
                )}
              </div>
            </div>

            {/* Step 2 */}
            <div className="flex items-start gap-2.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[10px] font-bold text-accent-contrast-text">
                2
              </span>
              <div className="pt-0.5">
                <span>Create tunnel: </span>
                <span className="font-mono text-text-primary font-medium">
                  {target.setup_instructions || `Create a ${target.protocol.toUpperCase()} tunnel pointing to 127.0.0.1:${target.local_port}`}
                </span>
              </div>
            </div>

            {/* Step 3 */}
            <div className="flex items-start gap-2.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-primary text-[10px] font-bold text-accent-contrast-text">
                3
              </span>
              <div className="pt-0.5 flex flex-wrap items-center gap-2">
                <span>Paste the resulting public address:</span>
                {!isReadOnly && (
                  <button
                    type="button"
                    onClick={() => onEditAddress(target)}
                    className="inline-flex items-center gap-1 font-semibold text-accent-primary hover:underline"
                  >
                    <span>Paste / Enter Address</span>
                    <Icon name="edit" size={12} />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Target Error Message Banner */}
      {target.error_message && (
        <div
          role="alert"
          className="p-3 rounded-lg bg-status-danger-bg border border-status-danger-border text-xs text-status-danger flex items-center justify-between"
        >
          <span>{target.error_message}</span>
          {target.error_code && (
            <span className="font-mono text-[10px] bg-status-danger/20 px-1.5 py-0.5 rounded">
              {target.error_code}
            </span>
          )}
        </div>
      )}

      {/* Confirm Target Delete Dialog */}
      <Modal
        open={isConfirmDeleteOpen}
        onClose={() => setIsConfirmDeleteOpen(false)}
        title="Remove Companion Target?"
        size="sm"
        closeOnBackdrop={false}
        closeOnEscape={true}
        closeButtonAriaLabel="Close dialog"
      >
        <div className="space-y-4">
          <p className="text-xs text-text-secondary">
            Are you sure you want to remove the <span className="font-semibold">{meta.label}</span> target ({target.protocol.toUpperCase()} {target.local_port})? External access to this companion service will be closed.
          </p>
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={() => setIsConfirmDeleteOpen(false)}
              className="px-3 py-1.5 rounded-lg border border-border-default text-xs font-medium text-text-secondary hover:bg-surface-hover"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => {
                onRemoveTarget(target.id);
                setIsConfirmDeleteOpen(false);
              }}
              className="px-3 py-1.5 rounded-lg bg-status-danger hover:opacity-90 text-white text-xs font-medium shadow-xs"
            >
              Remove Target
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
