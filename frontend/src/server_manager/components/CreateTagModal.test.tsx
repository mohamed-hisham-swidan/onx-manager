import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateTagModal } from "./CreateTagModal";

const mockCreateTag = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    createTag: mockCreateTag,
  }),
}));

const mockToast = vi.fn();
vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

describe("CreateTagModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <CreateTagModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", () => {
    document.body.style.overflow = "";

    const { unmount } = render(
      <CreateTagModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Create Immutable Tag" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("submits tag creation successfully", async () => {
    const user = userEvent.setup();
    mockCreateTag.mockResolvedValueOnce({ success: true });
    const onTagCreated = vi.fn();
    const onClose = vi.fn();

    render(
      <CreateTagModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={onTagCreated}
      />
    );

    const input = screen.getByLabelText("Tag Name");
    fireEvent.change(input, { target: { value: "v1.0.0" } });

    const submitBtn = screen.getByRole("button", { name: "Create Tag" });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(mockCreateTag).toHaveBeenCalledWith("srv-1", {
        name: "v1.0.0",
        commit_id: "abcdef1234567890",
      });
      expect(mockToast).toHaveBeenCalledWith("success", "Tag Created", expect.stringContaining("v1.0.0"));
      expect(onTagCreated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("displays error message when createTag fails", async () => {
    const user = userEvent.setup();
    mockCreateTag.mockRejectedValueOnce(new Error("Tag name already exists"));

    render(
      <CreateTagModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const input = screen.getByLabelText("Tag Name");
    fireEvent.change(input, { target: { value: "duplicate-tag" } });

    const submitBtn = screen.getByRole("button", { name: "Create Tag" });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText("Tag name already exists")).toBeInTheDocument();
    });
  });

  it("closes on Escape key press when idle", () => {
    const onClose = vi.fn();

    render(
      <CreateTagModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and disables cancel button while submitting", async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: unknown) => void = () => {};
    mockCreateTag.mockReturnValueOnce(
      new Promise((res) => {
        resolveCreate = res;
      })
    );
    const onClose = vi.fn();

    render(
      <CreateTagModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const input = screen.getByLabelText("Tag Name");
    fireEvent.change(input, { target: { value: "v2.0.0" } });

    const submitBtn = screen.getByRole("button", { name: "Create Tag" });
    await user.click(submitBtn);

    // Cancel button should be disabled
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    // Escape should be ignored while submitting
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    // Resolve
    await act(async () => {
      resolveCreate({ success: true });
    });
  });

  it("moves focus into the dialog on open", async () => {
    render(
      <CreateTagModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Create Immutable Tag" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("calls onClose when clicking backdrop while idle", () => {
    const onClose = vi.fn();
    render(
      <CreateTagModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking backdrop while submitting", async () => {
    const user = userEvent.setup();
    let resolveCreate: (value: unknown) => void = () => {};
    mockCreateTag.mockReturnValueOnce(
      new Promise((res) => {
        resolveCreate = res;
      })
    );
    const onClose = vi.fn();

    render(
      <CreateTagModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const input = screen.getByLabelText("Tag Name");
    fireEvent.change(input, { target: { value: "v2.0.0" } });

    const submitBtn = screen.getByRole("button", { name: "Create Tag" });
    await user.click(submitBtn);

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreate({ success: true });
    });
  });

  it("does not call onClose when clicking inside dialog content", () => {
    const onClose = vi.fn();
    render(
      <CreateTagModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        commitId="abcdef1234567890"
        onTagCreated={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Create Immutable Tag" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });
});
