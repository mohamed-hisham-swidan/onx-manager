import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  CreateBranchModal,
  CreateCommitModal,
  InspectCommitModal,
} from "./VersioningModals";
import type { ServerCommit } from "@/server_manager/types";

const mockCommit: ServerCommit = {
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

describe("VersioningModals accessibility and migration contracts", () => {
  beforeEach(() => {
    document.body.style.overflow = "";
  });

  describe("CreateBranchModal", () => {
    it("renders role='dialog' with accessible name, locks scroll, and responds to Escape", () => {
      const onClose = vi.fn();
      const { unmount } = render(
        <CreateBranchModal
          isOpen={true}
          branchName=""
          onBranchNameChange={vi.fn()}
          onSubmit={vi.fn()}
          onClose={onClose}
        />
      );

      const dialog = screen.getByRole("dialog", { name: "Create New Branch" });
      expect(dialog).toBeInTheDocument();
      expect(document.body.style.overflow).toBe("hidden");

      // Escape key closes modal (new accessible behavior)
      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalled();

      // Backdrop click should not close (preserving closeOnBackdrop=false)
      const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
      expect(backdrop).toBeInTheDocument();
      fireEvent.click(backdrop!);
      expect(onClose).toHaveBeenCalledTimes(1);

      unmount();
      expect(document.body.style.overflow).toBe("");
    });

    it("ignores Escape and disables cancel button while pending", () => {
      const onClose = vi.fn();
      render(
        <CreateBranchModal
          isOpen={true}
          branchName="test"
          onBranchNameChange={vi.fn()}
          onSubmit={vi.fn()}
          onClose={onClose}
          isPending={true}
        />
      );

      const cancelBtn = screen.getByRole("button", { name: "Cancel" });
      expect(cancelBtn).toBeDisabled();

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("CreateCommitModal", () => {
    it("renders role='dialog' with accessible name, locks scroll, and responds to Escape", () => {
      const onClose = vi.fn();
      const { unmount } = render(
        <CreateCommitModal
          isOpen={true}
          message=""
          onMessageChange={vi.fn()}
          forceBypass={false}
          onForceBypassChange={vi.fn()}
          forceReason=""
          onForceReasonChange={vi.fn()}
          selectedBranch="main"
          currentBranchObj={null}
          isDirectCommitBlocked={false}
          allowForceBypass={false}
          onSubmit={vi.fn()}
          onClose={onClose}
        />
      );

      const dialog = screen.getByRole("dialog", { name: "Create Snapshot Commit" });
      expect(dialog).toBeInTheDocument();
      expect(document.body.style.overflow).toBe("hidden");

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalled();

      unmount();
      expect(document.body.style.overflow).toBe("");
    });

    it("ignores Escape and disables cancel button while pending", () => {
      const onClose = vi.fn();
      render(
        <CreateCommitModal
          isOpen={true}
          message="test message"
          onMessageChange={vi.fn()}
          forceBypass={false}
          onForceBypassChange={vi.fn()}
          forceReason=""
          onForceReasonChange={vi.fn()}
          selectedBranch="main"
          currentBranchObj={null}
          isDirectCommitBlocked={false}
          allowForceBypass={false}
          onSubmit={vi.fn()}
          onClose={onClose}
          isPending={true}
        />
      );

      const cancelBtn = screen.getByRole("button", { name: "Cancel" });
      expect(cancelBtn).toBeDisabled();

      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).not.toHaveBeenCalled();
    });
  });

  describe("InspectCommitModal", () => {
    it("renders role='dialog' with accessible name, locks scroll, and responds to Escape and close button", () => {
      const onClose = vi.fn();
      const { unmount } = render(<InspectCommitModal commit={mockCommit} onClose={onClose} />);

      const dialog = screen.getByRole("dialog", { name: "Manifest Snapshot Inspector" });
      expect(dialog).toBeInTheDocument();
      expect(document.body.style.overflow).toBe("hidden");

      const closeButtons = screen.getAllByRole("button", { name: "Close" });
      expect(closeButtons.length).toBeGreaterThanOrEqual(1);

      // Top icon close button
      fireEvent.click(closeButtons[0]);
      expect(onClose).toHaveBeenCalledTimes(1);

      // Escape key closes modal
      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(2);

      unmount();
      expect(document.body.style.overflow).toBe("");
    });
  });
});
