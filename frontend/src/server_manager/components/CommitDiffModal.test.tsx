import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommitDiffModal } from "./CommitDiffModal";
import type { DiffResponse } from "@/server_manager/types";

const mockDiffCommits = vi.fn();
vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    diffCommits: mockDiffCommits,
  }),
}));

const sampleDiff: DiffResponse = {
  from_commit_id: "1111111111111111",
  to_commit_id: "2222222222222222",
  has_changes: true,
  server_type: null,
  minecraft_version: null,
  java_args: null,
  configs: {
    added: { "server.properties": "motd=Hello" },
    removed: { "old.properties": "deprecated" },
    modified: {},
  },
  mods: {
    added: ["fabric-api.jar"],
    removed: ["optifine.jar"],
    modified: [],
  },
  env_vars: {
    added: { MEMORY: "4G" },
    removed: {},
    modified: {},
  },
};

describe("CommitDiffModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <CommitDiffModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("fetches and renders commit diff summary when open", async () => {
    mockDiffCommits.mockResolvedValueOnce(sampleDiff);

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Commit Diff Inspector")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockDiffCommits).toHaveBeenCalledWith("srv-1", "1111111111111111", "2222222222222222");
    });

    // Check tabs with counts
    expect(screen.getByRole("button", { name: "Config Files (2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mods (2)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Env Vars (1)" })).toBeInTheDocument();
  });

  it("switches to Mods tab and displays added and removed mods", async () => {
    const user = userEvent.setup();
    mockDiffCommits.mockResolvedValueOnce(sampleDiff);

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Mods (2)" })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Mods (2)" }));

    expect(screen.getByText(/\+ fabric-api\.jar/)).toBeInTheDocument();
    expect(screen.getByText(/- optifine\.jar/)).toBeInTheDocument();
  });

  it("renders error alert if diff fails", async () => {
    mockDiffCommits.mockRejectedValueOnce(new Error("Unable to diff commits: missing parent"));

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Unable to diff commits: missing parent")).toBeInTheDocument();
    });
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", () => {
    document.body.style.overflow = "";

    const { unmount } = render(
      <CommitDiffModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Commit Diff Inspector" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key press", () => {
    const onClose = vi.fn();

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <CommitDiffModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Commit Diff Inspector" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("calls onClose when clicking backdrop", () => {
    const onClose = vi.fn();

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking inside dialog content", () => {
    const onClose = vi.fn();

    render(
      <CommitDiffModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        fromCommitId="1111111111111111"
        toCommitId="2222222222222222"
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Commit Diff Inspector" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });
});
