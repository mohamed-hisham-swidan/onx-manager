import React from "react";
import type {
  OperationArtifactProgress,
  OperationHealthCheckItem,
  OperationStatus,
  OperationStep,
  StepStatus,
} from "../types";

export interface OperationStepperProps {
  steps: OperationStep[];
  currentStepId?: string | null;
  nowMs?: number;
  operationStatus?: OperationStatus;
}

const TERMINAL_OP_STATUSES = new Set<OperationStatus>([
  "COMPLETED",
  "FAILED",
  "CANCELLED",
  "TIMED_OUT",
]);

function formatStepName(stepId: string): string {
  return stepId
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function formatMb(bytes: number): string {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getStepIcon(status: StepStatus) {
  switch (status) {
    case "COMPLETED":
      return (
        <span
          data-testid="step-icon-completed"
          className="flex h-6 w-6 items-center justify-center rounded-full bg-status-success-bg text-status-success"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </span>
      );
    case "IN_PROGRESS":
      return (
        <span
          data-testid="step-icon-in-progress"
          className="flex h-6 w-6 items-center justify-center rounded-full bg-status-info-bg text-status-info"
        >
          <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
        </span>
      );
    case "FAILED":
      return (
        <span
          data-testid="step-icon-failed"
          className="flex h-6 w-6 items-center justify-center rounded-full bg-status-danger-bg text-status-danger"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </span>
      );
    case "CANCELLED":
      return (
        <span
          data-testid="step-icon-cancelled"
          className="flex h-6 w-6 items-center justify-center rounded-full bg-status-warning-bg text-status-warning"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 12H4" />
          </svg>
        </span>
      );
    case "SKIPPED":
      return (
        <span
          data-testid="step-icon-skipped"
          className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-muted text-text-muted"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </span>
      );
    default:
      return (
        <span
          data-testid="step-icon-pending"
          className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-border-default"
        />
      );
  }
}

function getCheckStatusIcon(status: string, parentTerminal: boolean) {
  const effective = parentTerminal && status === "running" ? "failed" : status;
  switch (effective) {
    case "passed":
      return (
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-success-bg text-status-success">
          <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
          </svg>
        </span>
      );
    case "running":
      return (
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-info-bg text-status-info">
          <svg className="h-2.5 w-2.5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        </span>
      );
    case "warned":
      return (
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-warning-bg text-status-warning">
          <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 9v4m0 4h.01" />
          </svg>
        </span>
      );
    case "failed":
      return (
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-danger-bg text-status-danger">
          <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </span>
      );
    case "skipped":
      return (
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-surface-card text-text-muted border border-border-subtle">
          <svg className="h-2.5 w-2.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 12h14" />
          </svg>
        </span>
      );
    default:
      return (
        <span className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-border-default bg-surface-card" />
      );
  }
}

function ArtifactProgressList({
  artifacts,
}: {
  artifacts: OperationArtifactProgress[];
}) {
  return (
    <div
      data-testid="step-artifact-list"
      className="mt-2 rounded-lg border border-border-subtle bg-surface-muted p-2 space-y-1.5"
    >
      {artifacts.map((art, idx) => {
        const pct = Math.max(0, Math.min(100, Math.round(art.progress_pct ?? 0)));
        const isActive = art.status === "downloading" || art.status === "patching";
        let statusLabel = "Pending";
        let statusTone = "text-text-muted";
        if (art.status === "cached") {
          statusLabel = "✓ Cached";
          statusTone = "text-status-success";
        } else if (art.status === "ready") {
          statusLabel = "✓ Ready";
          statusTone = "text-status-success";
        } else if (art.status === "patching") {
          statusLabel = "Patching…";
          statusTone = "text-status-info";
        } else if (art.status === "downloading") {
          statusLabel =
            art.bytes_done != null && art.bytes_total != null && art.bytes_total > 0
              ? `${pct}% · ${formatMb(art.bytes_done)} / ${formatMb(art.bytes_total)}`
              : `${pct}%`;
          statusTone = "text-status-info";
        }

        return (
          <div
            key={`${art.name}-${idx}`}
            data-testid={`artifact-row-${art.name}`}
            className="space-y-1"
          >
            <div className="flex items-center justify-between gap-2 text-[11px]">
              <span className="font-mono text-text-primary truncate" title={art.name}>
                {art.name}
              </span>
              <span className={`shrink-0 font-mono text-[10px] font-medium ${statusTone}`}>
                {statusLabel}
              </span>
            </div>
            {isActive && (
              <div className="h-1 w-full overflow-hidden rounded-full bg-surface-card">
                <div
                  className="h-1 rounded-full bg-accent-primary transition-all duration-300"
                  style={{ width: `${Math.max(4, pct)}%` }}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function HealthGateChecklist({
  checks,
  parentTerminal = false,
}: {
  checks: OperationHealthCheckItem[];
  parentTerminal?: boolean;
}) {
  return (
    <div
      data-testid="health-gate-checklist"
      className="mt-2 rounded-lg border border-border-subtle bg-surface-muted p-2.5 space-y-1.5"
    >
      {checks.map((chk) => {
        const effectiveStatus =
          parentTerminal && chk.status === "running" ? "failed" : chk.status;
        const detailTone =
          effectiveStatus === "failed"
            ? "text-status-danger"
            : effectiveStatus === "warned"
              ? "text-status-warning"
              : "text-text-muted";
        return (
          <div
            key={chk.id}
            data-testid={`health-gate-check-${chk.id}`}
            data-status={effectiveStatus}
            className="flex items-start justify-between gap-2 text-[11px]"
          >
            <div className="flex items-center gap-2 min-w-0">
              {getCheckStatusIcon(chk.status, parentTerminal)}
              <span className="font-medium text-text-primary truncate">
                {chk.label}
              </span>
            </div>
            {chk.detail && (
              <span
                className={`text-right font-mono text-[10px] break-words max-w-[55%] ${detailTone}`}
              >
                {chk.detail}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export const OperationStepper: React.FC<OperationStepperProps> = ({
  steps,
  currentStepId,
  nowMs,
  operationStatus,
}) => {
  if (!steps || steps.length === 0) {
    return <div className="text-sm text-text-muted">No steps defined.</div>;
  }

  const parentTerminal = operationStatus
    ? TERMINAL_OP_STATUSES.has(operationStatus)
    : false;

  return (
    <div className="space-y-4">
      {steps.map((step) => {
        const effectiveStatus: StepStatus =
          parentTerminal && step.status === "IN_PROGRESS" ? "FAILED" : step.status;
        const isCurrent = !parentTerminal && step.step_id === currentStepId;
        let effectiveElapsedMs = step.elapsed_ms ?? 0;
        if (
          !parentTerminal &&
          effectiveStatus === "IN_PROGRESS" &&
          step.started_at &&
          nowMs !== undefined
        ) {
          const startedMs = Date.parse(step.started_at);
          if (!Number.isNaN(startedMs)) {
            effectiveElapsedMs = Math.max(effectiveElapsedMs, nowMs - startedMs);
          }
        }
        const elapsedSec = (effectiveElapsedMs / 1000).toFixed(1);

        const rawArtifacts = step.context?.artifacts;
        const artifacts = Array.isArray(rawArtifacts)
          ? (rawArtifacts as OperationArtifactProgress[])
          : [];
        const rawChecks = step.context?.checks;
        const checks = Array.isArray(rawChecks)
          ? (rawChecks as OperationHealthCheckItem[])
          : [];

        return (
          <div
            key={step.id || step.step_id}
            data-testid={`operation-step-${step.step_id}`}
            className={`flex items-start gap-3 rounded-lg p-2.5 transition-colors ${
              isCurrent
                ? "bg-status-info-bg border border-status-info-border"
                : ""
            }`}
          >
            <div className="pt-0.5">{getStepIcon(effectiveStatus)}</div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-text-primary">
                  {formatStepName(step.step_id)}
                </span>
                <span className="text-xs text-text-muted font-mono">
                  {effectiveStatus === "COMPLETED" ||
                  effectiveStatus === "IN_PROGRESS" ||
                  (effectiveStatus === "FAILED" && effectiveElapsedMs > 0)
                    ? `${elapsedSec}s`
                    : effectiveStatus}
                </span>
              </div>

              {effectiveStatus === "IN_PROGRESS" && step.progress !== null && (
                <div
                  role="progressbar"
                  aria-valuenow={Math.round((step.progress ?? 0) * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  className="mt-2 w-full bg-surface-muted rounded-full h-1.5 overflow-hidden"
                >
                  <div
                    className="bg-accent-primary h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${Math.round((step.progress ?? 0) * 100)}%` }}
                  />
                </div>
              )}

              {artifacts.length > 0 && <ArtifactProgressList artifacts={artifacts} />}
              {checks.length > 0 && (
                <HealthGateChecklist checks={checks} parentTerminal={parentTerminal} />
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
};
