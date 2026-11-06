import React from "react";

export interface OperationFailureProps {
  failureCode: string | null;
  errorMessage: string | null;
  failedStepId?: string | null;
  onRetry?: () => void;
  isRetrying?: boolean;
}

export const OperationFailure: React.FC<OperationFailureProps> = ({
  failureCode,
  errorMessage,
  failedStepId,
  onRetry,
  isRetrying = false,
}) => {
  return (
    <div
      role="alert"
      data-testid="operation-failure-card"
      className="rounded-lg border border-status-danger-border bg-status-danger-bg p-4"
    >
      <div className="flex items-start gap-3">
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-status-danger-bg text-status-danger">
          <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between">
            <h4
              data-testid="failure-code-badge"
              className="text-sm font-semibold text-status-danger"
            >
              {failureCode || "OPERATION_FAILED"}
            </h4>
            {failedStepId && (
              <span className="text-xs text-status-danger opacity-80">
                Step: {failedStepId}
              </span>
            )}
          </div>
          <p
            data-testid="failure-error-message"
            className="mt-1 text-sm text-status-danger break-words"
          >
            {errorMessage || "An unexpected error occurred during execution."}
          </p>

          {onRetry && (
            <div className="mt-3">
              <button
                type="button"
                onClick={onRetry}
                disabled={isRetrying}
                data-testid="operation-retry-button"
                className="inline-flex items-center gap-1.5 rounded-md bg-status-danger px-3 py-1.5 text-xs font-medium text-accent-contrast-text shadow-sm hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-border-focus focus:ring-offset-2 disabled:opacity-50"
              >
                {isRetrying ? "Retrying..." : "Retry Operation"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
