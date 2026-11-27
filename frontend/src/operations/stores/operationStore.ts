import { create } from "zustand";
import type { OperationDetail, OperationEvent, OperationStep } from "../types";

export interface OperationLogLine {
  level: string;
  line: string;
  timestamp: number;
}

export interface OperationStoreState {
  operations: Record<string, OperationDetail>;
  activeDrawerId: string | null;
  logs: Record<string, OperationLogLine[]>;
  gapDetectedOperations: Record<string, boolean>;

  openDrawer: (operationId: string) => void;
  closeDrawer: () => void;
  setOperation: (operation: OperationDetail) => void;
  removeOperation: (operationId: string) => void;
  appendLog: (operationId: string, level: string, line: string, timestamp?: number) => void;
  clearGap: (operationId: string) => void;
  reset: () => void;
  handleWsEvent: (event: OperationEvent, onGapDetected?: (operationId: string) => void) => void;
}

const MAX_LOG_LINES = 500;

export const useOperationStore = create<OperationStoreState>((set, get) => ({
  operations: {},
  activeDrawerId: null,
  logs: {},
  gapDetectedOperations: {},

  openDrawer: (operationId: string) => set({ activeDrawerId: operationId }),
  closeDrawer: () => set({ activeDrawerId: null }),
  reset: () => set({ operations: {}, activeDrawerId: null, logs: {}, gapDetectedOperations: {} }),

  setOperation: (operation: OperationDetail) =>
    set((state) => {
      const metaLogs = Array.isArray(operation.metadata?.logs)
        ? (operation.metadata.logs as Array<Record<string, unknown>>)
            .filter((entry) => entry && typeof entry.line === "string")
            .map((entry) => ({
              level: typeof entry.level === "string" ? entry.level : "info",
              line: String(entry.line),
              timestamp:
                typeof entry.timestamp === "number"
                  ? entry.timestamp
                  : Date.now() / 1000,
            }))
        : [];
      const existingLogs = state.logs[operation.id] || [];
      let nextLogs = existingLogs;
      if (metaLogs.length > 0 && metaLogs.length >= existingLogs.length) {
        nextLogs = metaLogs.slice(-MAX_LOG_LINES);
      }
      return {
        operations: { ...state.operations, [operation.id]: operation },
        logs:
          nextLogs !== existingLogs
            ? { ...state.logs, [operation.id]: nextLogs }
            : state.logs,
      };
    }),

  removeOperation: (operationId: string) =>
    set((state) => {
      const nextOps = { ...state.operations };
      delete nextOps[operationId];
      const nextLogs = { ...state.logs };
      delete nextLogs[operationId];
      const nextGaps = { ...state.gapDetectedOperations };
      delete nextGaps[operationId];
      return {
        operations: nextOps,
        logs: nextLogs,
        gapDetectedOperations: nextGaps,
        activeDrawerId: state.activeDrawerId === operationId ? null : state.activeDrawerId,
      };
    }),

  appendLog: (operationId: string, level: string, line: string, timestamp?: number) =>
    set((state) => {
      const current = state.logs[operationId] || [];
      const entry: OperationLogLine = {
        level: level || "info",
        line,
        timestamp: timestamp || Date.now() / 1000,
      };
      const updated = [...current, entry].slice(-MAX_LOG_LINES);
      return {
        logs: { ...state.logs, [operationId]: updated },
      };
    }),

  clearGap: (operationId: string) =>
    set((state) => ({
      gapDetectedOperations: { ...state.gapDetectedOperations, [operationId]: false },
    })),

  handleWsEvent: (event: OperationEvent, onGapDetected?: (operationId: string) => void) => {
    const { operation_id, event_seq, event_type } = event;
    if (!operation_id) return;

    // Handle log events directly
    if (event_type === "operation.log" && event.line) {
      get().appendLog(operation_id, event.level || "info", event.line, event.timestamp);
    }

    const currentOp = get().operations[operation_id];

    // Gap detection if operation is already tracked
    if (currentOp && event_seq !== undefined) {
      if (event_seq <= currentOp.last_event_seq) {
        // Stale or duplicate event; ignore
        return;
      }
      if (event_seq > currentOp.last_event_seq + 1) {
        // Gap detected!
        set((state) => ({
          gapDetectedOperations: {
            ...state.gapDetectedOperations,
            [operation_id]: true,
          },
        }));
        if (onGapDetected) {
          onGapDetected(operation_id);
        }
      }
    }

    set((state) => {
      const op = state.operations[operation_id];
      if (!op) {
        // If operation not yet in memory, create a partial projection
        const partialOp: OperationDetail = {
          id: operation_id,
          type: event.type || "GENERIC",
          target_type: event.target_type || "server",
          target_id: event.target_id || event.server_id || null,
          actor_id: null,
          status:
            event_type === "operation.completed"
              ? "COMPLETED"
              : event_type === "operation.failed"
              ? event.failure_code === "OPERATION_TIMEOUT"
                ? "TIMED_OUT"
                : "FAILED"
              : event_type === "operation.cancelled"
              ? "CANCELLED"
              : "RUNNING",
          idempotency_key: null,
          current_step_id: event.step_id || null,
          last_event_seq: event_seq ?? 0,
          failure_code: event.failure_code || null,
          error_message: event.error_message || null,
          cancellation_requested: false,
          timeout_seconds: 600,
          created_at: new Date().toISOString(),
          started_at: new Date().toISOString(),
          finished_at: null,
          elapsed_ms: event.elapsed_ms || 0,
          steps: event.step_id
            ? [
                {
                  id: event.step_id,
                  step_id: event.step_id,
                  sequence: 1,
                  status: event.step_status || "IN_PROGRESS",
                  progress: event.progress ?? null,
                  elapsed_ms: event.elapsed_ms || 0,
                  message_key: event.message_key || null,
                  safe_to_retry: false,
                  context: event.context || {},
                  started_at: new Date().toISOString(),
                  completed_at: null,
                },
              ]
            : [],
          metadata: {},
        };
        return {
          operations: { ...state.operations, [operation_id]: partialOp },
        };
      }

      // Update existing operation
      const updatedOp: OperationDetail = {
        ...op,
        last_event_seq: Math.max(op.last_event_seq, event_seq ?? 0),
        elapsed_ms: event.elapsed_ms !== undefined ? event.elapsed_ms : op.elapsed_ms,
      };

      if (event_type === "operation.started") {
        if (updatedOp.status === "QUEUED" || updatedOp.status === "PREPARING") {
          updatedOp.status = "RUNNING";
        }
      } else if (event_type === "operation.step") {
        if (event.step_id) {
          updatedOp.current_step_id = event.step_id;
          const existingStepIdx = updatedOp.steps.findIndex((s) => s.step_id === event.step_id);
          const nextStatus = event.step_status || "IN_PROGRESS";
          const nextProgress = event.progress !== undefined ? event.progress : null;
          const nextElapsed = event.elapsed_ms !== undefined ? event.elapsed_ms : 0;
          const nextContext = event.context ? { ...event.context } : {};

          if (existingStepIdx >= 0) {
            const currentStep = updatedOp.steps[existingStepIdx];
            const updatedStep: OperationStep = {
              ...currentStep,
              status: nextStatus,
              progress: nextProgress !== null ? nextProgress : currentStep.progress,
              elapsed_ms: nextElapsed || currentStep.elapsed_ms,
              context: { ...currentStep.context, ...nextContext },
            };
            if (nextStatus === "COMPLETED" && !updatedStep.completed_at) {
              updatedStep.completed_at = new Date().toISOString();
            }
            const newSteps = [...updatedOp.steps];
            newSteps[existingStepIdx] = updatedStep;
            updatedOp.steps = newSteps;
          } else {
            const newStep: OperationStep = {
              id: event.step_id,
              step_id: event.step_id,
              sequence: updatedOp.steps.length + 1,
              status: nextStatus,
              progress: nextProgress,
              elapsed_ms: nextElapsed,
              message_key: event.message_key || null,
              safe_to_retry: false,
              context: nextContext,
              started_at: new Date().toISOString(),
              completed_at: nextStatus === "COMPLETED" ? new Date().toISOString() : null,
            };
            updatedOp.steps = [...updatedOp.steps, newStep];
          }
        }
      } else if (event_type === "operation.completed") {
        updatedOp.status = "COMPLETED";
        updatedOp.finished_at = new Date().toISOString();
        // Mark all steps completed if not already
        updatedOp.steps = updatedOp.steps.map((s) =>
          s.status === "IN_PROGRESS" || s.status === "PENDING"
            ? { ...s, status: "COMPLETED", progress: 1.0, completed_at: new Date().toISOString() }
            : s
        );
      } else if (event_type === "operation.failed") {
        updatedOp.status =
          event.failure_code === "OPERATION_TIMEOUT" ? "TIMED_OUT" : "FAILED";
        updatedOp.failure_code = event.failure_code || null;
        updatedOp.error_message = event.error_message || null;
        updatedOp.finished_at = new Date().toISOString();
        if (event.failed_step_id) {
          updatedOp.current_step_id = event.failed_step_id;
          updatedOp.steps = updatedOp.steps.map((s) =>
            s.step_id === event.failed_step_id
              ? { ...s, status: "FAILED" }
              : s
          );
        }
      } else if (event_type === "operation.cancelled") {
        updatedOp.status = "CANCELLED";
        updatedOp.finished_at = new Date().toISOString();
        updatedOp.steps = updatedOp.steps.map((s) =>
          s.status === "IN_PROGRESS"
            ? { ...s, status: "CANCELLED" }
            : s
        );
      }

      return {
        operations: { ...state.operations, [operation_id]: updatedOp },
      };
    });
  },
}));
