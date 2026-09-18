import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportReviewModal } from "./ImportReviewModal";
import type { ScanLiveChangesResponse } from "@/server_manager/types";

const mockConfirmImportReview = vi.fn();
const mockDismissImportReview = vi.fn();
const mockRevertImportReview = vi.fn();
const mockAutoCommitLiveChanges = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    confirmImportReview: mockConfirmImportReview,
    dismissImportReview: mockDismissImportReview,
    revertImportReview: mockRevertImportReview,
    autoCommitLiveChanges: mockAutoCommitLiveChanges,
  }),
}));

const mockToast = vi.fn();
vi.mock("@/stores/toastStore", () => ({
  toast: (...args: unknown[]) => mockToast(...args),
}));

const sampleLiveDataWithReview: ScanLiveChangesResponse = {
  has_changes: true,
  review_id: "rev-12345",
  changes: [
    { path: "server.properties", change_type: "modified", size_bytes: 1024 },
    { path: "mods/newmod.jar", change_type: "added", size_bytes: 204800 },
  ],
};

const sampleLiveDataNoReview: ScanLiveChangesResponse = {
  has_changes: true,
  review_id: undefined,
  changes: [
    { path: "config/paper-global.yml", change_type: "modified", size_bytes: 4096 },
  ],
};

describe("ImportReviewModal Component", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not render when isOpen is false", () => {
    render(
      <ImportReviewModal
        isOpen={false}
        onClose={vi.fn()}
        serverId="srv-1"
        liveData={sampleLiveDataWithReview}
        onReviewResolved={vi.fn()}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("renders live changes list and review buttons", () => {
    render(
      <ImportReviewModal
        isOpen={true}
        onClose={vi.fn()}
        serverId="srv-1"
        liveData={sampleLiveDataWithReview}
        onReviewResolved={vi.fn()}
      />
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Uncommitted Live Changes Detected")).toBeInTheDocument();
    expect(screen.getByText("server.properties")).toBeInTheDocument();
    expect(screen.getByText("mods/newmod.jar")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm & Commit/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Dismiss/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Revert Live Changes/i })).toBeInTheDocument();
  });

  it("calls confirmImportReview when review_id exists and Confirm & Commit is clicked", async () => {
    const user = userEvent.setup();
    mockConfirmImportReview.mockResolvedValueOnce({
      review_id: "rev-12345",
      status: "confirmed",
      commit_id: "abcdef123456",
    });

    const onResolved = vi.fn();
    const onClose = vi.fn();

    render(
      <ImportReviewModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        liveData={sampleLiveDataWithReview}
        onReviewResolved={onResolved}
      />
    );

    const confirmBtn = screen.getByRole("button", { name: /Confirm & Commit/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockConfirmImportReview).toHaveBeenCalledWith("srv-1", "rev-12345");
      expect(onResolved).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("calls autoCommitLiveChanges when review_id is undefined and Confirm & Commit is clicked", async () => {
    const user = userEvent.setup();
    mockAutoCommitLiveChanges.mockResolvedValueOnce({
      commit_id: "9876543210ab",
      branch: "main",
      status: "committed",
    });

    const onResolved = vi.fn();
    const onClose = vi.fn();

    render(
      <ImportReviewModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        liveData={sampleLiveDataNoReview}
        onReviewResolved={onResolved}
      />
    );

    const confirmBtn = screen.getByRole("button", { name: /Confirm & Commit/i });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(mockAutoCommitLiveChanges).toHaveBeenCalledWith("srv-1", { branch: "main" });
      expect(onResolved).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("shows confirmation and reverts live changes when Revert is selected and confirmed", async () => {
    const user = userEvent.setup();
    mockRevertImportReview.mockResolvedValueOnce({
      review_id: "rev-12345",
      status: "reverted",
    });

    const onResolved = vi.fn();
    const onClose = vi.fn();

    render(
      <ImportReviewModal
        isOpen={true}
        onClose={onClose}
        serverId="srv-1"
        liveData={sampleLiveDataWithReview}
        onReviewResolved={onResolved}
      />
    );

    // Click Revert Live Changes
    const revertBtn = screen.getByRole("button", { name: /Revert Live Changes/i });
    await user.click(revertBtn);

    // Confirmation warning appears
    expect(screen.getByText("Confirm Destructive Filesystem Revert")).toBeInTheDocument();

    // Click confirm revert
    const confirmRevertBtn = screen.getByRole("button", { name: /Yes, Revert Filesystem/i });
    await user.click(confirmRevertBtn);

    await waitFor(() => {
      expect(mockRevertImportReview).toHaveBeenCalledWith("srv-1", "rev-12345");
      expect(onResolved).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });
});
