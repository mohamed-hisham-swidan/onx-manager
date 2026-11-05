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
      parent_commit_id: null,
      author_id: null,
      message: "Test commit",
      created_at: new Date().toISOString(),
      world_snapshot_id: null,
      manifest: {
        server_type: "paper",
        minecraft_version: "1.21",
        configs: { "server.properties": "motd=Test" },
        mods: [],
        env_vars: {},
        java_args: "",
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
      commit_id: "abcdef1234567890",
      node_id: "node-1",
      status: "PASSED",
      ephemeral_port: null,
      log_output: "Server started on port 25565",
      failure_reason: null,
      created_at: new Date().toISOString(),
      expires_at: null,
      bot_count: 0,
      duration_minutes: 2,
      placement_mode: "auto",
      bot_tech: "internal",
    };

    render(<ViewLogsModal testRun={testRun} onClose={onClose} />);
    const closeButtons = screen.getAllByRole("button", { name: "Close" });
    expect(closeButtons.length).toBeGreaterThanOrEqual(1);

    // Click top icon close button
    fireEvent.click(closeButtons[0]);
    expect(onClose).toHaveBeenCalled();
  });
});
