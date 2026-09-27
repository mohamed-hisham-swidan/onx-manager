import { describe, it, expect, beforeEach, vi } from "vitest";
import { useOperationStore } from "./operationStore";
import type { OperationDetail } from "../types";

describe("operationStore", () => {
  const dummyOp: OperationDetail = {
    id: "op-123",
    type: "RUN_TEST",
    target_type: "server",
    target_id: "srv-1",
    actor_id: "usr-1",
    status: "PREPARING",
    idempotency_key: "key-1",
    current_step_id: "ADMISSION_CHECK",
    last_event_seq: 1,
    failure_code: null,
    error_message: null,
    cancellation_requested: false,
    timeout_seconds: 600,
    created_at: "2026-09-27T12:00:00Z",
    started_at: "2026-09-27T12:00:01Z",
    finished_at: null,
    elapsed_ms: 1000,
    steps: [
      {
        id: "s-1",
        step_id: "ADMISSION_CHECK",
        sequence: 1,
        status: "IN_PROGRESS",
        progress: 0.5,
        elapsed_ms: 500,
        message_key: "checking_admission",
        safe_to_retry: true,
        context: {},
        started_at: "2026-09-27T12:00:01Z",
        completed_at: null,
      },
    ],
    metadata: {},
  };

  beforeEach(() => {
    useOperationStore.setState({
      operations: {},
      activeDrawerId: null,
      logs: {},
      gapDetectedOperations: {},
    });
  });

  it("opens and closes the active drawer", () => {
    const store = useOperationStore.getState();
    store.openDrawer("op-123");
    expect(useOperationStore.getState().activeDrawerId).toBe("op-123");

    store.closeDrawer();
    expect(useOperationStore.getState().activeDrawerId).toBeNull();
  });

  it("stores and removes an operation", () => {
    const store = useOperationStore.getState();
    store.setOperation(dummyOp);
    expect(useOperationStore.getState().operations["op-123"]).toBeDefined();

    store.removeOperation("op-123");
    expect(useOperationStore.getState().operations["op-123"]).toBeUndefined();
  });

  it("appends and caps log lines", () => {
    const store = useOperationStore.getState();
    for (let i = 0; i < 550; i++) {
      store.appendLog("op-123", "info", `Log line ${i}`);
    }
    const lines = useOperationStore.getState().logs["op-123"];
    expect(lines).toHaveLength(500);
    expect(lines[499].line).toBe("Log line 549");
  });

  it("updates step progress and transitions status on WebSocket events", () => {
    const store = useOperationStore.getState();
    store.setOperation(dummyOp);

    // Sequence 2: Step update
    store.handleWsEvent({
      event_type: "operation.step",
      operation_id: "op-123",
      event_seq: 2,
      step_id: "ADMISSION_CHECK",
      step_status: "COMPLETED",
      progress: 1.0,
      elapsed_ms: 1200,
    });

    const opAfterStep = useOperationStore.getState().operations["op-123"];
    expect(opAfterStep.last_event_seq).toBe(2);
    expect(opAfterStep.steps[0].status).toBe("COMPLETED");
    expect(opAfterStep.steps[0].progress).toBe(1.0);

    // Sequence 3: Completion
    store.handleWsEvent({
      event_type: "operation.completed",
      operation_id: "op-123",
      event_seq: 3,
      elapsed_ms: 3000,
    });

    const opCompleted = useOperationStore.getState().operations["op-123"];
    expect(opCompleted.status).toBe("COMPLETED");
    expect(opCompleted.finished_at).toBeDefined();
  });

  it("detects event_seq gap and triggers onGapDetected callback", () => {
    const store = useOperationStore.getState();
    store.setOperation(dummyOp); // last_event_seq is 1

    const gapHandler = vi.fn();

    // Event with seq 4 arrives (expected 2, gap of 2 missed events)
    store.handleWsEvent(
      {
        event_type: "operation.step",
        operation_id: "op-123",
        event_seq: 4,
        step_id: "BOOTSTRAP_VERIFY",
        step_status: "IN_PROGRESS",
      },
      gapHandler
    );

    expect(gapHandler).toHaveBeenCalledWith("op-123");
    expect(useOperationStore.getState().gapDetectedOperations["op-123"]).toBe(true);
  });

  it("ignores stale or duplicate events with event_seq <= last_event_seq", () => {
    const store = useOperationStore.getState();
    store.setOperation({ ...dummyOp, last_event_seq: 5 });

    // Event with seq 3 arrives (stale)
    store.handleWsEvent({
      event_type: "operation.step",
      operation_id: "op-123",
      event_seq: 3,
      step_id: "ADMISSION_CHECK",
      step_status: "FAILED",
    });

    // Aggregate should NOT have been updated
    const op = useOperationStore.getState().operations["op-123"];
    expect(op.last_event_seq).toBe(5);
    expect(op.steps[0].status).toBe("IN_PROGRESS");
  });
});
