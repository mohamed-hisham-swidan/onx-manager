import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InspectCommitModal, ViewLogsModal } from "./VersioningModals";
import type { ServerCommit, ServerTestRun } from "@/server_manager/types";

describe("VersioningModals accessibility", () => {
  it("renders InspectCommitModal close button with accessible name", () => {
    const onClose = vi.fn();
    const commit: ServerCommit = {
      id: "abcdef1234567890",
      server_id: "srv-1",
      branch_id: "main",
      message: "Test commit",
      created_at: new Date().toISOString(),
      parent_ids: [],
      manifest: {
        configs: { "server.properties": "motd=Test" },
        mods: [],
      },
    };

    render(<InspectCommitModal commit={commit} onClose={onClose} />);
    const closeButtons = screen.getAllByRole("button", { name: "Close" });
    expect(closeButtons.length).toBeGreaterThanOrEqual(1);

    // Click the top icon close button
    fireEvent.click(closeButtons[0]);
    expect(onClose).toHaveBeenCalled();
  });

  it("renders ViewLogsModal close button with accessible name", () => {
    const onClose = vi.fn();
    const testRun: ServerTestRun = {
      id: "run-12345678",
      server_id: "srv-1",
      test_definition_id: "test-def-1",
      runtime_id: "rt-1",
      status: "completed",
      started_at: new Date().toISOString(),
      finished_at: new Date().toISOString(),
      log_output: "Server started on port 25565",
      operation_id: null,
      passed: true,
      duration_seconds: 12,
      evidence_bundle: null,
      artifacts_purged: false,
    };

    render(<ViewLogsModal testRun={testRun} onClose={onClose} />);
    const closeButtons = screen.getAllByRole("button", { name: "Close" });
    expect(closeButtons.length).toBeGreaterThanOrEqual(1);

    // Click top icon close button
    fireEvent.click(closeButtons[0]);
    expect(onClose).toHaveBeenCalled();
  });
});
