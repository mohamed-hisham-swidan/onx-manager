import React, { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Icon } from "@/components/ui/Icon";
import { createAuthenticatedApi } from "@/services/api";
import { queryClient, queryKeys } from "@/services/queryClient";
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
  const api = useMemo(() => createAuthenticatedApi(), []);
  const storeOp = useOperationStore((state) =>
    operationId ? state.operations[operationId] : undefined
  );
  const logs = useOperationStore((state) =>
    operationId && state.logs[operationId] ? state.logs[operationId] : EMPTY_LOGS
  );
  const closeDrawer = useOperationStore((state) => state.closeDrawer);
  const setOperation = useOperationStore((state) => state.setOperation);

  const [isCancelling, setIsCancelling] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const prevStatusRef = useRef<OperationStatus | undefined>(undefined);

  const opStatus = storeOp?.status;
  const isTerminal = storeOp
    ? ["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"].includes(storeOp.status)
    : false;

  // Poll GET /api/v1/operations/{id} every 1.5s while non-terminal so steps,
  // durations, and persisted OPERATION OUTPUT logs always stay live even if a WS frame is missed.
  useEffect(() => {
    if (!operationId || typeof api.getOperation !== "function") return;
    if (isTerminal) return;

    let cancelled = false;
    const fetchOp = async () => {
      try {
        const detail = await api.getOperation(operationId);
        if (!cancelled && detail) {
          setOperation(detail);
        }
      } catch {
        // Ignore transient polling failures
      }
    };

    void fetchOp();
    const timer = window.setInterval(() => {
      void fetchOp();
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [operationId, isTerminal, api, setOperation]);

  // Live ticking timer for the overall elapsed clock and active step duration.
  useEffect(() => {
    if (!operationId || isTerminal) return;
    const tick = window.setInterval(() => {
      setNowMs(Date.now());
    }, 250);
    return () => {
      window.clearInterval(tick);
    };
  }, [operationId, isTerminal]);

  // Immediately invalidate server, upgrade, and branch caches when an operation finishes.
  useEffect(() => {
    const prev = prevStatusRef.current;
    prevStatusRef.current = opStatus;
    if (!opStatus || !isTerminal) return;
    if (prev === opStatus) return;

    const targetId = storeOp?.target_type === "server" ? storeOp.target_id : null;
    void queryClient.invalidateQueries({ queryKey: queryKeys.servers.all });
    if (targetId) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.servers.detail(targetId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.p55.upgrades(targetId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.versioning.branches(targetId) });
    }
  }, [opStatus, isTerminal, storeOp?.target_type, storeOp?.target_id]);

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

  if (!operationId) {
    return null;
  }

  const handleCancel = async () => {
    if (isCancelling) return;
    setIsCancelling(true);
    try {
      if (onCancel) {
        await onCancel(operationId);
      } else if (typeof api.cancelOperation === "function") {
        const updated = await api.cancelOperation(operationId);
        if (updated) {
          setOperation(updated);
        }
      }
    } catch {
      // Errors surface via polling / status refresh
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

  const isCancelRequested = storeOp?.status === "CANCEL_REQUESTED";

  let effectiveOpElapsedMs = storeOp?.elapsed_ms ?? 0;
  if (storeOp && !isTerminal && storeOp.started_at) {
    const startedMs = Date.parse(storeOp.started_at);
    if (!Number.isNaN(startedMs)) {
      effectiveOpElapsedMs = Math.max(effectiveOpElapsedMs, nowMs - startedMs);
    }
  }

  return (
    <>
      <div
        aria-hidden="true"
        onClick={handleClose}
        className="fixed inset-x-0 top-14 bottom-0 z-40 bg-black/50 backdrop-blur-xs lg:hidden"
      />
      <aside
        role="complementary"
        aria-label="Operation Progress"
        data-testid="operation-drawer"
        className="fixed inset-x-3 top-16 z-50 mx-auto flex max-h-[calc(100dvh-5rem)] max-w-xl flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-card shadow-2xl lg:inset-x-auto lg:left-auto lg:top-16 lg:right-4 lg:bottom-auto lg:mx-0 lg:h-fit lg:max-h-[calc(100dvh-5.5rem)] lg:w-[460px] xl:w-[500px] lg:shadow-xl"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-border-subtle px-4 py-3 shrink-0">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold text-text-primary truncate">
                {storeOp?.type ?? "Operation"}
              </h3>
              <span
                data-testid="operation-status-badge"
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${
                  storeOp
                    ? getStatusBadgeClass(storeOp.status)
                    : "bg-surface-muted text-text-secondary border border-border-subtle"
                }`}
              >
                {storeOp?.status ?? "LOADING"}
              </span>
            </div>
            <p className="text-[11px] text-text-muted mt-0.5 font-mono truncate" title={operationId}>
              ID: {operationId}
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            aria-label="Hide operation panel"
            title="Hide panel (keeps active operation running in background)"
            data-testid="operation-drawer-close"
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium text-text-muted hover:bg-surface-muted hover:text-text-primary focus:outline-none transition-colors shrink-0 cursor-pointer"
          >
            <Icon name="panel-right-close" size={15} />
            <span>Hide</span>
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-5">
          {!storeOp ? (
            <div className="rounded-lg bg-surface-muted p-4 text-xs text-text-secondary">
              Loading live operation state…
            </div>
          ) : (
            <>
              {/* Metadata banner */}
              <div className="flex items-center justify-between gap-2 rounded-lg bg-surface-muted p-3 text-xs">
                <div className="min-w-0 truncate">
                  <span className="text-text-muted">Target: </span>
                  <span className="font-medium text-text-primary">
                    {storeOp.target_type}:{storeOp.target_id || "global"}
                  </span>
                </div>
                <div className="shrink-0">
                  <span className="text-text-muted">Elapsed: </span>
                  <span className="font-medium text-text-primary font-mono">
                    {(effectiveOpElapsedMs / 1000).toFixed(1)}s
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
                  nowMs={isTerminal ? undefined : nowMs}
                  operationStatus={storeOp.status}
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
            </>
          )}
        </div>

        {/* Footer */}
        {storeOp && !isTerminal && (
          <div className="border-t border-border-subtle px-4 py-3 shrink-0">
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
      </aside>
    </>
  );
};
