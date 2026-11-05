import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MaterializationBrowserModal } from "./MaterializationBrowserModal";

const mockGetMaterializations = vi.fn();
const mockGetMaterializationTree = vi.fn();
const mockCreateMaterialization = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getMaterializations: mockGetMaterializations,
    getMaterializationTree: mockGetMaterializationTree,
    createMaterialization: mockCreateMaterialization,
  }),
}));

const sampleWorktrees = [
  {
    id: "mat-1",
    server_id: "srv-1",
    revision_type: "branch",
    revision_ref: "main",
    mode: "readonly",
    status: "ready",
    path: "/tmp/mat-1",
    created_at: new Date().toISOString(),
  },
];

describe("MaterializationBrowserModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetMaterializations.mockResolvedValue(sampleWorktrees);
    mockGetMaterializationTree.mockResolvedValue({ entries: [] });
  });

  it("does not render when isOpen is false", () => {
    render(
      <MaterializationBrowserModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders delete button with accessible aria-label", async () => {
    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
      />
    );

    await waitFor(() => {
      const deleteBtn = screen.getByRole("button", { name: "Delete worktree" });
      expect(deleteBtn).toBeInTheDocument();
      expect(deleteBtn).toHaveAttribute("title", "Delete worktree");
    });
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", () => {
    document.body.style.overflow = "";

    const { unmount } = render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Worktree Materialization Explorer" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key press when idle", () => {
    const handleClose = vi.fn();

    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={handleClose}
        serverId="srv-1"
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and disables Close button while creating worktree", async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: unknown) => void = () => {};
    mockCreateMaterialization.mockReturnValueOnce(
      new Promise((res) => {
        resolveCreate = res;
      })
    );
    const handleClose = vi.fn();

    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={handleClose}
        serverId="srv-1"
      />
    );

    // Click "Materialize Revision" to show form
    const openFormBtn = screen.getByRole("button", { name: "Materialize Revision" });
    await user.click(openFormBtn);

    // Submit creation form
    const createBtn = screen.getByRole("button", { name: "Create Worktree" });
    await user.click(createBtn);

    // Close button should be disabled
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();

    // Escape should be ignored while busy
    fireEvent.keyDown(window, { key: "Escape" });
    expect(handleClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreate({ materialization_id: "mat-new-1" });
    });
  });

  it("calls onClose when clicking backdrop while idle", () => {
    const handleClose = vi.fn();

    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={handleClose}
        serverId="srv-1"
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(handleClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking backdrop while creating worktree", async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: unknown) => void = () => {};
    mockCreateMaterialization.mockReturnValueOnce(
      new Promise((res) => {
        resolveCreate = res;
      })
    );
    const handleClose = vi.fn();

    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={handleClose}
        serverId="srv-1"
      />
    );

    const openFormBtn = screen.getByRole("button", { name: "Materialize Revision" });
    await user.click(openFormBtn);

    const createBtn = screen.getByRole("button", { name: "Create Worktree" });
    await user.click(createBtn);

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(handleClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreate({ materialization_id: "mat-new-1" });
    });
  });

  it("does not call onClose when clicking inside dialog content", () => {
    const handleClose = vi.fn();

    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={handleClose}
        serverId="srv-1"
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Worktree Materialization Explorer" });
    fireEvent.click(dialog);
    expect(handleClose).not.toHaveBeenCalled();
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <MaterializationBrowserModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Worktree Materialization Explorer" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });
});
