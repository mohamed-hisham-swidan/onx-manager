import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ManageBranchesModal } from "./ManageBranchesModal";
import type { ServerBranch } from "@/server_manager/types";

const mockArchiveBranch = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    archiveBranch: mockArchiveBranch,
  }),
}));

const mockToast = vi.fn();
vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

const mockBranches: ServerBranch[] = [
  {
    id: "b-1",
    server_id: "srv-1",
    name: "main",
    head_commit_id: "11111112222222",
    created_at: "2026-09-18T10:00:00Z",
    status: "active",
    is_protected: true,
  },
  {
    id: "b-2",
    server_id: "srv-1",
    name: "feat-mods",
    head_commit_id: "33333334444444",
    created_at: "2026-09-19T10:00:00Z",
    status: "active",
    is_protected: false,
  },
];

describe("ManageBranchesModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <ManageBranchesModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", () => {
    document.body.style.overflow = "";

    const { unmount } = render(
      <ManageBranchesModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Branch Lifecycle Management" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("calls onClose and onOpenProtectionModal when Protection Rules button is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onOpenProtectionModal = vi.fn();

    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={onOpenProtectionModal}
      />
    );

    const protectionBtns = screen.getAllByRole("button", { name: "Protection Rules" });
    await user.click(protectionBtns[0]);

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onOpenProtectionModal).toHaveBeenCalledWith(mockBranches[0]);
  });

  it("handles branch archiving workflow with confirmation", async () => {
    const user = userEvent.setup();
    mockArchiveBranch.mockResolvedValueOnce({ success: true });
    const onBranchesChanged = vi.fn();

    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={onBranchesChanged}
        onOpenProtectionModal={vi.fn()}
      />
    );

    // feat-mods has an archive button (main is protected so disabled)
    const archiveBtns = screen.getAllByRole("button", { name: "Archive" });
    await user.click(archiveBtns[1]);

    // Confirm prompt appears
    expect(screen.getByText("Archive Branch 'feat-mods'?")).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: "Yes, Archive Branch" });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockArchiveBranch).toHaveBeenCalledWith("srv-1", "feat-mods");
      expect(mockToast).toHaveBeenCalledWith("success", "Branch Archived", expect.stringContaining("feat-mods"));
      expect(onBranchesChanged).toHaveBeenCalled();
    });
  });

  it("closes on Escape key press when idle", () => {
    const onClose = vi.fn();

    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and disables close button while archiving is pending", async () => {
    const user = userEvent.setup();
    let resolveArchive: (value: unknown) => void = () => {};
    mockArchiveBranch.mockReturnValueOnce(
      new Promise((res) => {
        resolveArchive = res;
      })
    );
    const onClose = vi.fn();

    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    const archiveBtns = screen.getAllByRole("button", { name: "Archive" });
    await user.click(archiveBtns[1]);

    const confirmBtn = screen.getByRole("button", { name: "Yes, Archive Branch" });
    await user.click(confirmBtn);

    // Close button should be disabled
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();

    // Escape should be ignored while archiving
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    // Resolve
    await act(async () => {
      resolveArchive({ success: true });
    });
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Branch Lifecycle Management" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("calls onClose when clicking backdrop while idle", () => {
    const onClose = vi.fn();
    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking backdrop while archiving is pending", async () => {
    const user = userEvent.setup();
    let resolveArchive: (value: unknown) => void = () => {};
    mockArchiveBranch.mockReturnValueOnce(
      new Promise((res) => {
        resolveArchive = res;
      })
    );
    const onClose = vi.fn();

    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    const archiveBtns = screen.getAllByRole("button", { name: "Archive" });
    await user.click(archiveBtns[1]);

    const confirmBtn = screen.getByRole("button", { name: "Yes, Archive Branch" });
    await user.click(confirmBtn);

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveArchive({ success: true });
    });
  });

  it("does not call onClose when clicking inside dialog content", () => {
    const onClose = vi.fn();
    render(
      <ManageBranchesModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branches={mockBranches}
        currentBranchName="main"
        onBranchesChanged={vi.fn()}
        onOpenProtectionModal={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Branch Lifecycle Management" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });
});
