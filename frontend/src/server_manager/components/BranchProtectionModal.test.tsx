import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BranchProtectionModal } from "./BranchProtectionModal";
import type { ServerBranch } from "@/server_manager/types";

const mockGetBranchProtection = vi.fn();
const mockSetBranchProtection = vi.fn();
const mockRemoveBranchProtection = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getBranchProtection: mockGetBranchProtection,
    setBranchProtection: mockSetBranchProtection,
    removeBranchProtection: mockRemoveBranchProtection,
  }),
}));

const mockToast = vi.fn();
vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

const mockMainBranch: ServerBranch = {
  id: "branch-1",
  server_id: "srv-1",
  name: "main",
  head_commit_id: "c1",
  created_at: "2026-09-18T10:00:00Z",
  status: "active",
  is_protected: true,
  protection_policy: {
    require_test_pass: false,
    allow_direct_commit: false,
    allow_force_bypass: true,
    prevent_deletion: true,
  },
};

const mockBranch: ServerBranch = {
  id: "branch-2",
  server_id: "srv-1",
  name: "release",
  head_commit_id: "c2",
  created_at: "2026-09-18T10:00:00Z",
  status: "active",
  is_protected: true,
  protection_policy: {
    require_test_pass: false,
    allow_direct_commit: false,
    allow_force_bypass: true,
    prevent_deletion: true,
  },
};

describe("BranchProtectionModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <BranchProtectionModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("fetches and renders branch protection policy without fake require_test_pass and locks main toggle", async () => {
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: {
        require_test_pass: true,
        allow_direct_commit: false,
        allow_force_bypass: true,
        prevent_deletion: true,
      },
    });

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        branch={mockMainBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Branch Protection Policy")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockGetBranchProtection).toHaveBeenCalledWith("srv-1", "main");
    });

    expect(screen.getByText("Enable Branch Protection")).toBeInTheDocument();
    expect(screen.queryByLabelText("Require passing test run")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Enable branch protection")).toBeDisabled();
    expect(screen.getByLabelText("Allow direct commits")).toBeDisabled();
    expect(screen.getByLabelText("Allow administrative force bypass")).toBeChecked();
    expect(screen.getByLabelText("Prevent branch deletion and archival")).toBeDisabled();
  });

  it("calls setBranchProtection when saving updated policy on non-main branch", async () => {
    const user = userEvent.setup();
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "release",
      is_protected: true,
      policy: {
        require_test_pass: false,
        allow_direct_commit: false,
        allow_force_bypass: true,
        prevent_deletion: true,
      },
    });
    mockSetBranchProtection.mockResolvedValueOnce({
      branch_name: "release",
      is_protected: true,
      policy: {
        require_test_pass: false,
        allow_direct_commit: true,
        allow_force_bypass: true,
        prevent_deletion: true,
      },
    });

    const onUpdated = vi.fn();
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={onUpdated}
      />
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Allow direct commits")).toBeInTheDocument();
    });

    const allowDirectCheckbox = screen.getByLabelText("Allow direct commits");
    await user.click(allowDirectCheckbox);

    const saveBtn = screen.getByRole("button", { name: /Apply Protection/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockSetBranchProtection).toHaveBeenCalledWith("srv-1", "release", {
        policy: {
          require_test_pass: false,
          allow_direct_commit: true,
          allow_force_bypass: true,
          prevent_deletion: true,
        },
      });
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("calls removeBranchProtection when protection toggle is unchecked and saved on non-main branch", async () => {
    const user = userEvent.setup();
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "release",
      is_protected: true,
      policy: {
        require_test_pass: false,
        allow_direct_commit: false,
        allow_force_bypass: true,
        prevent_deletion: true,
      },
    });
    mockRemoveBranchProtection.mockResolvedValueOnce({
      branch_name: "release",
      is_protected: false,
      policy: null,
    });

    const onUpdated = vi.fn();
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={onUpdated}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Enable Branch Protection")).toBeInTheDocument();
    });

    // Toggle off protection
    const protectToggle = screen.getByLabelText("Enable branch protection");
    await user.click(protectToggle);

    // Click Save (which now says "Disable Protection")
    const saveBtn = screen.getByRole("button", { name: /Disable Protection/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockRemoveBranchProtection).toHaveBeenCalledWith("srv-1", "release");
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("renders role='dialog' with accessible name, locks body scroll, and releases on unmount", async () => {
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });
    document.body.style.overflow = "";

    const { unmount } = render(
      <BranchProtectionModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Branch Protection Policy" });
    expect(dialog).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");

    unmount();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes on Escape key when idle", async () => {
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "Branch Protection Policy" })).toBeInTheDocument();
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape and disables cancel button while saving policy", async () => {
    const user = userEvent.setup();
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });
    let resolveSet: (value: unknown) => void = () => {};
    mockSetBranchProtection.mockReturnValueOnce(
      new Promise((res) => {
        resolveSet = res;
      })
    );
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Apply Protection/i })).toBeInTheDocument();
    });

    // Click Apply Protection to trigger isSaving
    await user.click(screen.getByRole("button", { name: /Apply Protection/i }));

    // Cancel button should be disabled
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    // Escape should be ignored while saving
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();

    // Cleanup promise
    await act(async () => {
      resolveSet({ success: true });
    });
  });

  it("moves focus into the dialog on open", async () => {
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "Branch Protection Policy" });
    await waitFor(() => {
      expect(dialog.contains(document.activeElement)).toBe(true);
    });
  });

  it("calls onClose when clicking backdrop while idle", async () => {
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "Branch Protection Policy" })).toBeInTheDocument();
    });

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does not call onClose when clicking backdrop while saving policy", async () => {
    const user = userEvent.setup();
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });
    let resolveSet: (value: unknown) => void = () => {};
    mockSetBranchProtection.mockReturnValueOnce(
      new Promise((res) => {
        resolveSet = res;
      })
    );
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Apply Protection/i })).toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: /Apply Protection/i }));

    const backdrop = document.querySelector(".fixed.inset-0.bg-black\\/60");
    expect(backdrop).toBeInTheDocument();
    fireEvent.click(backdrop!);
    expect(onClose).not.toHaveBeenCalled();

    await act(async () => {
      resolveSet({ success: true });
    });
  });

  it("does not call onClose when clicking inside dialog content", async () => {
    mockGetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: null,
    });
    const onClose = vi.fn();

    render(
      <BranchProtectionModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole("dialog", { name: "Branch Protection Policy" })).toBeInTheDocument();
    });

    const dialog = screen.getByRole("dialog", { name: "Branch Protection Policy" });
    fireEvent.click(dialog);
    expect(onClose).not.toHaveBeenCalled();
  });
});
