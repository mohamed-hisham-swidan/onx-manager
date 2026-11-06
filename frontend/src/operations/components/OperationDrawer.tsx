import React, { useState, useEffect, useCallback } from "react";
import { useOperationStore } from "../stores/operationStore";
import { OperationStepper } from "./OperationStepper";
import { OperationFailure } from "./OperationFailure";
import { OperationLogs } from "./OperationLogs";
import type { OperationStatus } from "../types";
import type { OperationLogLine } from "../stores/operationStore";

const EMPTY_LOGS: OperationLogLine[] = [];

export interface OperationDrawerProps {
  operationId: string | null;
  onClose?: () => void;
  onCancel?: (operationId: string) => Promise<void>;
  onRetry?: (operationId: string) => Promise<void>;
}

function getStatusBadgeClass(status: OperationStatus): string {
  switch (status) {
    case "COMPLETED":
      return "bg-status-success-bg text-status-success border border-status-success-border";
    case "RUNNING":
    case "PREPARING":
      return "bg-status-info-bg text-status-info border border-status-info-border";
    case "QUEUED":
      return "bg-surface-muted text-text-secondary border border-border-subtle";
    case "CANCEL_REQUESTED":
    case "CANCELLED":
      return "bg-status-warning-bg text-status-warning border border-status-warning-border";
    case "FAILED":
    case "TIMED_OUT":
      return "bg-status-danger-bg text-status-danger border border-status-danger-border";
    default:
      return "bg-surface-muted text-text-secondary border border-border-subtle";
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
    operationId && state.logs[operationId] ? state.logs[operationId] : EMPTY_LOGS
  );
  const closeDrawer = useOperationStore((state) => state.closeDrawer);

  const [isCancelling, setIsCancelling] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);

  const handleClose = useCallback(() => {
    if (onClose) onClose();
    closeDrawer();
  }, [onClose, closeDrawer]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        handleClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [handleClose]);

  if (!operationId || !storeOp) {
    return null;
  }

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
      <div className="w-screen max-w-md bg-surface-card shadow-2xl border-l border-border-subtle flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-subtle p-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-semibold text-text-primary">
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
            <p className="text-xs text-text-muted mt-0.5 font-mono">
              ID: {storeOp.id}
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close drawer"
            data-testid="operation-drawer-close"
            className="rounded-md p-1.5 text-text-muted hover:text-text-primary focus:outline-none"
          >
            <span className="sr-only">Close drawer</span>
            <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Metadata banner */}
          <div className="flex items-center justify-between rounded-lg bg-surface-muted p-3 text-xs">
            <div>
              <span className="text-text-muted">Target: </span>
              <span className="font-medium text-text-primary">
                {storeOp.target_type}:{storeOp.target_id || "global"}
              </span>
            </div>
            <div>
              <span className="text-text-muted">Elapsed: </span>
              <span className="font-medium text-text-primary font-mono">
                {((storeOp.elapsed_ms ?? 0) / 1000).toFixed(1)}s
              </span>
            </div>
          </div>

          {/* Stepper */}
          <div>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-3">
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
            <h4 className="text-xs font-semibold uppercase tracking-wider text-text-muted mb-2">
              Operation Output
            </h4>
            <OperationLogs logs={logs} />
          </div>
        </div>

        {/* Footer */}
        {!isTerminal && (
          <div className="border-t border-border-subtle p-4">
            <button
              type="button"
              onClick={handleCancel}
              disabled={isCancelling || isCancelRequested}
              data-testid="operation-cancel-button"
              className="w-full rounded-md bg-status-danger-bg px-3 py-2 text-sm font-semibold text-status-danger border border-status-danger-border hover:opacity-90 disabled:opacity-50"
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
