import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

const mockBranch: ServerBranch = {
  id: "branch-1",
  server_id: "srv-1",
  name: "main",
  head_commit_id: "c1",
  created_at: "2026-09-18T10:00:00Z",
  status: "active",
  is_protected: true,
  protection_policy: {
    require_test_pass: true,
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

  it("fetches and renders branch protection policy when open", async () => {
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
        branch={mockBranch}
        onProtectionUpdated={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Branch Protection Policy")).toBeInTheDocument();
    expect(screen.getByText("main")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockGetBranchProtection).toHaveBeenCalledWith("srv-1", "main");
    });

    expect(screen.getByText("Enable Branch Protection")).toBeInTheDocument();
    expect(screen.getByLabelText("Require passing test run")).toBeChecked();
    expect(screen.getByLabelText("Allow direct commits")).not.toBeChecked();
    expect(screen.getByLabelText("Allow administrative force bypass")).toBeChecked();
    expect(screen.getByLabelText("Prevent branch deletion and archival")).toBeChecked();
  });

  it("calls setBranchProtection when saving updated policy", async () => {
    const user = userEvent.setup();
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
    mockSetBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
      is_protected: true,
      policy: {
        require_test_pass: false,
        allow_direct_commit: false,
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
      expect(screen.getByLabelText("Require passing test run")).toBeInTheDocument();
    });

    // Toggle require_test_pass checkbox
    const requireTestCheckbox = screen.getByLabelText("Require passing test run");
    await user.click(requireTestCheckbox);

    // Save changes
    const saveBtn = screen.getByRole("button", { name: /Apply Protection/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(mockSetBranchProtection).toHaveBeenCalledWith("srv-1", "main", {
        policy: {
          require_test_pass: false,
          allow_direct_commit: false,
          allow_force_bypass: true,
          prevent_deletion: true,
        },
      });
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("calls removeBranchProtection when protection toggle is unchecked and saved", async () => {
    const user = userEvent.setup();
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
    mockRemoveBranchProtection.mockResolvedValueOnce({
      branch_name: "main",
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
      expect(mockRemoveBranchProtection).toHaveBeenCalledWith("srv-1", "main");
      expect(onUpdated).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });
});
