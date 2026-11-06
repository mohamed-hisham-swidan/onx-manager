import React from "react";
import type { OperationStep, StepStatus } from "../types";

export interface OperationStepperProps {
  steps: OperationStep[];
  currentStepId?: string | null;
}

function formatStepName(stepId: string): string {
  return stepId
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
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

export const OperationStepper: React.FC<OperationStepperProps> = ({ steps, currentStepId }) => {
  if (!steps || steps.length === 0) {
    return <div className="text-sm text-text-muted">No steps defined.</div>;
  }

  return (
    <div className="space-y-4">
      {steps.map((step) => {
        const isCurrent = step.step_id === currentStepId;
        const elapsedSec = ((step.elapsed_ms ?? 0) / 1000).toFixed(1);

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
            <div className="pt-0.5">{getStepIcon(step.status)}</div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-text-primary">
                  {formatStepName(step.step_id)}
                </span>
                <span className="text-xs text-text-muted">
                  {step.status === "COMPLETED" || step.status === "IN_PROGRESS"
                    ? `${elapsedSec}s`
                    : step.status}
                </span>
              </div>

              {step.status === "IN_PROGRESS" && step.progress !== null && (
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
            </div>
          </div>
        );
      })}
    </div>
  );
};
