import React, { useState } from "react";
import { useOperationStore } from "../stores/operationStore";
import { OperationStepper } from "./OperationStepper";
import { OperationFailure } from "./OperationFailure";
import { OperationLogs } from "./OperationLogs";
import type { OperationStatus } from "../types";

export interface OperationDrawerProps {
  operationId: string | null;
  onClose?: () => void;
  onCancel?: (operationId: string) => Promise<void>;
  onRetry?: (operationId: string) => Promise<void>;
}

function getStatusBadgeClass(status: OperationStatus): string {
  switch (status) {
    case "COMPLETED":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300";
    case "RUNNING":
    case "PREPARING":
      return "bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300";
    case "QUEUED":
      return "bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300";
    case "CANCEL_REQUESTED":
    case "CANCELLED":
      return "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300";
    case "FAILED":
    case "TIMED_OUT":
      return "bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300";
    default:
      return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
  }
}

export const OperationDrawer: React.FC<OperationDrawerProps> = ({
  operationId,
  onClose,
  onCancel,
  onRetry,
}) => {
  const storeOp = useOperationStore((state) =>
    operationId ? state.operations[operationId] : undefined
  );
  const logs = useOperationStore((state) =>
    operationId ? state.logs[operationId] || [] : []
  );
  const closeDrawer = useOperationStore((state) => state.closeDrawer);

  const [isCancelling, setIsCancelling] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

  if (!operationId || !storeOp) {
    return null;
  }

  const handleClose = () => {
    if (onClose) onClose();
    closeDrawer();
  };

  const handleCancel = async () => {
    if (!onCancel || isCancelling) return;
    setIsCancelling(true);
    try {
      await onCancel(operationId);
    } finally {
      setIsCancelling(false);
    }
  };

  const handleRetry = async () => {
    if (!onRetry || isRetrying) return;
    setIsRetrying(true);
    try {
      await onRetry(operationId);
    } finally {
      setIsRetrying(false);
    }
  };

  const isTerminal = [
    "COMPLETED",
    "FAILED",
    "CANCELLED",
    "TIMED_OUT",
  ].includes(storeOp.status);

  const isCancelRequested = storeOp.status === "CANCEL_REQUESTED";

  return (
    <div
      data-testid="operation-drawer"
      className="fixed inset-y-0 right-0 z-50 flex max-w-full pl-10"
    >
      <div className="w-screen max-w-md bg-white shadow-2xl dark:bg-gray-900 border-l border-gray-200 dark:border-gray-800 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 p-4 dark:border-gray-800">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                {storeOp.type}
              </h3>
              <span
                data-testid="operation-status-badge"
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${getStatusBadgeClass(
                  storeOp.status
                )}`}
              >
                {storeOp.status}
              </span>
            </div>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">
              ID: {storeOp.id}
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            data-testid="operation-drawer-close"
            className="rounded-md p-1.5 text-gray-400 hover:text-gray-500 focus:outline-none dark:hover:text-gray-300"
          >
            <span className="sr-only">Close drawer</span>
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Metadata banner */}
          <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3 text-xs dark:bg-gray-800/50">
            <div>
              <span className="text-gray-500 dark:text-gray-400">Target: </span>
              <span className="font-medium text-gray-900 dark:text-gray-200">
                {storeOp.target_type}:{storeOp.target_id || "global"}
              </span>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Elapsed: </span>
              <span className="font-medium text-gray-900 dark:text-gray-200 font-mono">
                {(storeOp.elapsed_ms / 1000).toFixed(1)}s
              </span>
            </div>
          </div>

          {/* Stepper */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-3">
              Execution Steps
            </h4>
            <OperationStepper
              steps={storeOp.steps}
              currentStepId={storeOp.current_step_id}
            />
          </div>

          {/* Failure Alert */}
          {(storeOp.status === "FAILED" || storeOp.status === "TIMED_OUT") && (
            <OperationFailure
              failureCode={storeOp.failure_code}
              errorMessage={storeOp.error_message}
              failedStepId={storeOp.current_step_id}
              onRetry={onRetry ? handleRetry : undefined}
              isRetrying={isRetrying}
            />
          )}

          {/* Logs */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400 mb-2">
              Operation Output
            </h4>
            <OperationLogs logs={logs} />
          </div>
        </div>

        {/* Footer */}
        {!isTerminal && (
          <div className="border-t border-gray-200 p-4 dark:border-gray-800">
            <button
              type="button"
              onClick={handleCancel}
              disabled={isCancelling || isCancelRequested}
              data-testid="operation-cancel-button"
              className="w-full rounded-md bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 shadow-sm ring-1 ring-inset ring-red-300 hover:bg-red-100 disabled:opacity-50 dark:bg-red-950/40 dark:text-red-300 dark:ring-red-900"
            >
              {isCancelRequested || isCancelling
                ? "Cancelling Operation..."
                : "Cancel Operation"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
