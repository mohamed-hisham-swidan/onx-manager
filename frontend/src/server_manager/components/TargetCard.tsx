import { useState } from "react";
import { Icon } from "@/components/ui/Icon";
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
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-800 space-y-4">
      {/* Target Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-gray-100 pb-3 dark:border-gray-700/60">
        <div className="flex items-center gap-2.5">
          <span className="font-semibold text-sm text-gray-900 dark:text-gray-100">
            {meta.label}
          </span>
          <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 uppercase">
            {target.protocol.toUpperCase()} {target.local_port}
          </span>
          {isPrimary && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
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
              className="p-1 text-gray-400 hover:text-red-600 dark:hover:text-red-400 rounded hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              title="Remove Target"
            >
              <Icon name="trash" size={15} />
            </button>
          )}
        </div>
      </div>

      {/* Target Address & Connection Display */}
      <div className="space-y-2">
        <span className="text-[11px] font-medium uppercase tracking-wider text-gray-500 dark:text-gray-400">
          Public Connection Address
        </span>

        {publicAddress ? (
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-lg bg-gray-50 dark:bg-gray-700/40 border border-gray-200 dark:border-gray-700">
            <span className="font-mono text-sm font-semibold text-blue-600 dark:text-blue-400 break-all select-all">
              {publicAddress}
            </span>

            <div className="flex items-center gap-2 shrink-0">
              <button
                type="button"
                onClick={() => copy(publicAddress, "Public address copied to clipboard")}
                aria-label={`Copy ${meta.label} public address to clipboard`}
                className="px-2.5 py-1 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600 flex items-center gap-1.5 transition-colors shadow-xs"
              >
                <Icon name="copy" size={13} />
                <span>Copy</span>
              </button>

              {!isReadOnly && (
                <button
                  type="button"
                  onClick={() => onEditAddress(target)}
                  aria-label="Edit public address"
                  className="px-2.5 py-1 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-xs font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-600 flex items-center gap-1.5 transition-colors shadow-xs"
                >
                  <Icon name="edit" size={13} />
                  <span>Edit</span>
                </button>
              )}
            </div>
          </div>
        ) : (
          <div className="p-3 rounded-lg bg-gray-50 dark:bg-gray-700/30 border border-dashed border-gray-300 dark:border-gray-700 text-xs text-gray-500 dark:text-gray-400 flex items-center justify-between">
            <span>No public address assigned yet.</span>
            {!isReadOnly && (
              <button
                type="button"
                onClick={() => onEditAddress(target)}
                className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 font-medium"
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
          className="rounded-lg border border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-900/10 p-4 space-y-3"
        >
          <div className="flex items-center gap-2 text-blue-900 dark:text-blue-300 font-semibold text-xs uppercase tracking-wider">
            <Icon name="info" size={16} />
            <span>playit.gg Assisted Setup Required</span>
          </div>

          <div className="space-y-2.5 text-xs text-gray-700 dark:text-gray-300">
            {/* Step 1 */}
            <div className="flex items-start gap-2.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                1
              </span>
              <div className="pt-0.5 flex flex-wrap items-center gap-2">
                <span>Open the playit.gg management dashboard:</span>
                {target.dashboard_url && (
                  <a
                    href={target.dashboard_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 underline"
                  >
                    <span>Open Dashboard</span>
                    <Icon name="external" size={12} />
                  </a>
                )}
              </div>
            </div>

            {/* Step 2 */}
            <div className="flex items-start gap-2.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                2
              </span>
              <div className="pt-0.5">
                <span>Create tunnel: </span>
                <span className="font-mono text-gray-900 dark:text-gray-100 font-medium">
                  {target.setup_instructions || `Create a ${target.protocol.toUpperCase()} tunnel pointing to 127.0.0.1:${target.local_port}`}
                </span>
              </div>
            </div>

            {/* Step 3 */}
            <div className="flex items-start gap-2.5">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
                3
              </span>
              <div className="pt-0.5 flex flex-wrap items-center gap-2">
                <span>Paste the resulting public address:</span>
                {!isReadOnly && (
                  <button
                    type="button"
                    onClick={() => onEditAddress(target)}
                    className="inline-flex items-center gap-1 font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 underline"
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
          className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-xs text-red-700 dark:text-red-300 flex items-center justify-between"
        >
          <span>{target.error_message}</span>
          {target.error_code && (
            <span className="font-mono text-[10px] bg-red-100 dark:bg-red-900/40 px-1.5 py-0.5 rounded">
              {target.error_code}
            </span>
          )}
        </div>
      )}

      {/* Confirm Target Delete Dialog */}
      {isConfirmDeleteOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-target-modal-title"
        >
          <div className="w-full max-w-sm rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-800 space-y-4">
            <h3
              id="delete-target-modal-title"
              className="text-base font-semibold text-gray-900 dark:text-gray-100"
            >
              Remove Companion Target?
            </h3>
            <p className="text-xs text-gray-600 dark:text-gray-300">
              Are you sure you want to remove the <span className="font-semibold">{meta.label}</span> target ({target.protocol.toUpperCase()} {target.local_port})? External access to this companion service will be closed.
            </p>
            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setIsConfirmDeleteOpen(false)}
                className="px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  onRemoveTarget(target.id);
                  setIsConfirmDeleteOpen(false);
                }}
                className="px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-medium shadow-sm"
              >
                Remove Target
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
