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
          className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400"
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
          className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-100 text-blue-600 dark:bg-blue-950/60 dark:text-blue-400"
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
          className="flex h-6 w-6 items-center justify-center rounded-full bg-red-100 text-red-600 dark:bg-red-950/60 dark:text-red-400"
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
          className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-100 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400"
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
          className="flex h-6 w-6 items-center justify-center rounded-full bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
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
          className="flex h-6 w-6 items-center justify-center rounded-full border-2 border-gray-300 dark:border-gray-600"
        />
      );
  }
}

export const OperationStepper: React.FC<OperationStepperProps> = ({ steps, currentStepId }) => {
  if (!steps || steps.length === 0) {
    return <div className="text-sm text-gray-500 dark:text-gray-400">No steps defined.</div>;
  }

  return (
    <div className="space-y-4">
      {steps.map((step) => {
        const isCurrent = step.step_id === currentStepId;
        const elapsedSec = (step.elapsed_ms / 1000).toFixed(1);

        return (
          <div
            key={step.id || step.step_id}
            data-testid={`operation-step-${step.step_id}`}
            className={`flex items-start gap-3 rounded-lg p-2.5 transition-colors ${
              isCurrent
                ? "bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200/60 dark:border-blue-900/40"
                : ""
            }`}
          >
            <div className="pt-0.5">{getStepIcon(step.status)}</div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {formatStepName(step.step_id)}
                </span>
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  {step.status === "COMPLETED" || step.status === "IN_PROGRESS"
                    ? `${elapsedSec}s`
                    : step.status}
                </span>
              </div>

              {step.status === "IN_PROGRESS" && step.progress !== null && (
                <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5 dark:bg-gray-700 overflow-hidden">
                  <div
                    className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${Math.round(step.progress * 100)}%` }}
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
