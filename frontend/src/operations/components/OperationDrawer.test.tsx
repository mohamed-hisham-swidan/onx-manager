import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { OperationDrawer } from "./OperationDrawer";
import { useOperationStore } from "../stores/operationStore";
import { queryClient } from "@/services/queryClient";
import type { OperationDetail } from "../types";

const mockApi = vi.hoisted(() => ({
  getOperation: vi.fn(),
  cancelOperation: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => mockApi,
}));

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
    vi.clearAllMocks();
    mockApi.getOperation.mockResolvedValue(mockOp);
    mockApi.cancelOperation.mockResolvedValue({ ...mockOp, status: "CANCEL_REQUESTED" });
    useOperationStore.setState({
      operations: { [mockOp.id]: mockOp },
      activeDrawerId: mockOp.id,
      logs: {
        [mockOp.id]: [{ level: "info", line: "Unpacking archive...", timestamp: 1727438400 }],
      },
      gapDetectedOperations: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
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

    const drawer = screen.getByTestId("operation-drawer");
    expect(drawer.className).toContain("lg:w-[460px]");
    expect(drawer.className).toContain("lg:right-4");
    expect(drawer.className).toContain("lg:h-fit");

    const closeBtn = screen.getByTestId("operation-drawer-close");
    expect(closeBtn).toHaveTextContent("Hide");
    fireEvent.click(closeBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);
    expect(useOperationStore.getState().activeDrawerId).toBeNull();
  });

  it("polls GET /operations/{id} every 1.5s while RUNNING, hydrates logs, and invalidates caches on completion", async () => {
    vi.useFakeTimers();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const runningOp: OperationDetail = {
      ...mockOp,
      id: "op-poll-1",
      type: "SERVER_UPGRADE",
      status: "RUNNING",
      current_step_id: "PREPARE_AND_DOWNLOAD",
      steps: [
        {
          id: "st-1",
          step_id: "PREPARE_AND_DOWNLOAD",
          sequence: 1,
          status: "IN_PROGRESS",
          progress: null,
          elapsed_ms: 0,
          message_key: "Preparing",
          safe_to_retry: false,
          context: {},
          started_at: new Date(Date.now() - 5000).toISOString(),
          completed_at: null,
        },
      ],
      metadata: {
        logs: [
          { level: "info", line: "Downloading Purpur 1.21.11...", timestamp: 1727438401 },
        ],
      },
    };
    const completedOp: OperationDetail = {
      ...runningOp,
      status: "COMPLETED",
      finished_at: new Date().toISOString(),
      steps: [{ ...runningOp.steps[0], status: "COMPLETED", elapsed_ms: 6500 }],
      metadata: {
        logs: [
          { level: "info", line: "Downloading Purpur 1.21.11...", timestamp: 1727438401 },
          { level: "info", line: "Upgrade verified and active.", timestamp: 1727438407 },
        ],
      },
    };
    mockApi.getOperation
      .mockResolvedValueOnce(runningOp)
      .mockResolvedValueOnce(completedOp);

    useOperationStore.setState({
      operations: {},
      activeDrawerId: "op-poll-1",
      logs: {},
      gapDetectedOperations: {},
    });

    render(<OperationDrawer operationId="op-poll-1" />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(mockApi.getOperation).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Downloading Purpur 1.21.11...")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(mockApi.getOperation).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Upgrade verified and active.")).toBeInTheDocument();
    expect(screen.getByTestId("operation-status-badge")).toHaveTextContent("COMPLETED");
    expect(invalidateSpy).toHaveBeenCalled();
    invalidateSpy.mockRestore();
  });

  it("falls back to api.cancelOperation when onCancel prop is omitted", async () => {
    render(<OperationDrawer operationId="op-drawer-1" />);
    const cancelBtn = screen.getByTestId("operation-cancel-button");
    fireEvent.click(cancelBtn);
    await waitFor(() => {
      expect(mockApi.cancelOperation).toHaveBeenCalledWith("op-drawer-1");
    });
  });
});
