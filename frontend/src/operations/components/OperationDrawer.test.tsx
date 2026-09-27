import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OperationDrawer } from "./OperationDrawer";
import { useOperationStore } from "../stores/operationStore";
import type { OperationDetail } from "../types";

describe("OperationDrawer", () => {
  const mockOp: OperationDetail = {
    id: "op-drawer-1",
    type: "BACKUP_RESTORE",
    target_type: "server",
    target_id: "srv-alpha",
    actor_id: "usr-1",
    status: "RUNNING",
    idempotency_key: "idem-1",
    current_step_id: "ADMISSION_CHECK",
    last_event_seq: 1,
    failure_code: null,
    error_message: null,
    cancellation_requested: false,
    timeout_seconds: 600,
    created_at: "2026-09-27T12:00:00Z",
    started_at: "2026-09-27T12:00:01Z",
    finished_at: null,
    elapsed_ms: 4500,
    steps: [
      {
        id: "step-1",
        step_id: "ADMISSION_CHECK",
        sequence: 1,
        status: "IN_PROGRESS",
        progress: 0.5,
        elapsed_ms: 4500,
        message_key: null,
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
      operations: { [mockOp.id]: mockOp },
      activeDrawerId: mockOp.id,
      logs: {
        [mockOp.id]: [{ level: "info", line: "Unpacking archive...", timestamp: 1727438400 }],
      },
      gapDetectedOperations: {},
    });
  });

  it("renders operation drawer with title, status badge, and target", () => {
    render(<OperationDrawer operationId="op-drawer-1" />);

    expect(screen.getByTestId("operation-drawer")).toBeInTheDocument();
    expect(screen.getByText("BACKUP_RESTORE")).toBeInTheDocument();
    expect(screen.getByTestId("operation-status-badge")).toHaveTextContent("RUNNING");
    expect(screen.getByText("server:srv-alpha")).toBeInTheDocument();
    expect(screen.getByText("Admission Check")).toBeInTheDocument();
    expect(screen.getByText("Unpacking archive...")).toBeInTheDocument();
  });

  it("invokes onCancel when Cancel Operation button is clicked", async () => {
    const handleCancel = vi.fn().mockResolvedValue(undefined);
    render(<OperationDrawer operationId="op-drawer-1" onCancel={handleCancel} />);

    const cancelBtn = screen.getByTestId("operation-cancel-button");
    expect(cancelBtn).toBeInTheDocument();
    fireEvent.click(cancelBtn);
    expect(handleCancel).toHaveBeenCalledWith("op-drawer-1");
  });

  it("invokes onClose and closes drawer on close button click", () => {
    const handleClose = vi.fn();
    render(<OperationDrawer operationId="op-drawer-1" onClose={handleClose} />);

    const closeBtn = screen.getByTestId("operation-drawer-close");
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);
    expect(useOperationStore.getState().activeDrawerId).toBeNull();
  });
});
