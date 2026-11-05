import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MaterializationBrowserModal } from "./MaterializationBrowserModal";

const mockGetMaterializations = vi.fn();
const mockGetMaterializationTree = vi.fn();

vi.mock("@/services/api", () => ({
  createAuthenticatedApi: () => ({
    getMaterializations: mockGetMaterializations,
    getMaterializationTree: mockGetMaterializationTree,
  }),
}));

describe("MaterializationBrowserModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders delete button with accessible aria-label", async () => {
    mockGetMaterializations.mockResolvedValueOnce([
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
    ]);
    mockGetMaterializationTree.mockResolvedValueOnce({ entries: [] });

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
});
